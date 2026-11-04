"""Local PDF-grounded stock research assistant. Python 3.9+."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import fitz
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FILES = DATA / "files"
DB = DATA / "index.sqlite3"
WEB = ROOT / "web"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen3:1.7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
MAX_UPLOAD = 50 * 1024 * 1024
CHUNK_SIZE = 1300
CHUNK_OVERLAP = 180
SEARCH_LIMIT = 8


def connection():
    DATA.mkdir(exist_ok=True)
    FILES.mkdir(exist_ok=True)
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL,
            bytes INTEGER NOT NULL, pages INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL, indexed_chunks INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
            page INTEGER NOT NULL, body TEXT NOT NULL, vector TEXT,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS chunks_document_id ON chunks(document_id);
    """)
    return db


def ollama(path, payload, timeout=240):
    request = Request(
        OLLAMA_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Ollama request failed: {exc}. Check that Ollama is running and the models are installed.") from exc


def split_text(text):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for start in range(0, len(text), step):
        part = text[start:start + CHUNK_SIZE]
        if part:
            parts.append(part)
        if start + CHUNK_SIZE >= len(text):
            break
    return parts


def embed_many(texts):
    if not texts:
        return []
    result = ollama("/api/embed", {"model": EMBED_MODEL, "input": texts}, timeout=180)
    vectors = result.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError("Ollama returned an unexpected embedding response")
    return vectors


def index_pdf(db, name, raw):
    if not raw.startswith(b"%PDF-"):
        raise ValueError("Please upload a valid PDF file")
    digest = hashlib.sha256(raw).hexdigest()
    reader = PdfReader(__import__("io").BytesIO(raw))
    if reader.is_encrypted:
        raise ValueError("Password-protected PDFs are not supported")
    passages = []
    for page_no, page in enumerate(reader.pages, start=1):
        for body in split_text(page.extract_text() or ""):
            passages.append((page_no, body))
    if not passages:
        raise ValueError("No selectable text found. Scanned PDFs need OCR before upload")
    document_id = uuid.uuid4().hex
    stored = FILES / f"{document_id}.pdf"
    stored.write_bytes(raw)
    try:
        with db:
            db.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (document_id, name, digest, len(raw), len(reader.pages),
                        time.strftime("%Y-%m-%d %H:%M:%S"), len(passages)))
            for page_no, body in passages:
                db.execute("INSERT INTO chunks(document_id, page, body, vector) VALUES (?, ?, ?, NULL)",
                           (document_id, page_no, body))
        # A missing embedding model should not make the PDF disappear. Keyword
        # search remains available and the UI reports the embedding status.
        embedded = 0
        try:
            rows = db.execute("SELECT id, body FROM chunks WHERE document_id=? ORDER BY id", (document_id,)).fetchall()
            for offset in range(0, len(rows), 24):
                batch = rows[offset:offset + 24]
                vectors = embed_many([row["body"] for row in batch])
                with db:
                    db.executemany("UPDATE chunks SET vector=? WHERE id=?",
                                   [(json.dumps(vector), row["id"]) for row, vector in zip(batch, vectors)])
                embedded += len(batch)
        except RuntimeError:
            pass
        return {"id": document_id, "name": name, "pages": len(reader.pages),
                "chunks": len(passages), "embedded_chunks": embedded}
    except Exception:
        stored.unlink(missing_ok=True)
        raise


def tokens(text):
    return set(re.findall(r"[a-z0-9][a-z0-9.-]{1,}", text.lower()))


def cosine(a, b):
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    aa = math.sqrt(sum(x * x for x in a))
    bb = math.sqrt(sum(y * y for y in b))
    return dot / (aa * bb) if aa and bb else 0.0


def search(db, question):
    rows = db.execute("""SELECT c.id, c.document_id, c.page, c.body, c.vector,
                              d.name FROM chunks c JOIN documents d ON d.id=c.document_id""").fetchall()
    if not rows:
        return []
    lower_question = question.lower()
    # Full fiscal-year figures belong to annual filings. Interim 10-Q tables
    # often contain year-to-date totals that a small model can mistake for a
    # full-year total when both are in the same context.
    if "fiscal" in lower_question and not any(word in lower_question for word in ("quarter", "q1", "q2", "q3", "q4", "interim")):
        annual = [row for row in rows if "10k" in row["name"].lower() or "10-k" in row["name"].lower()]
        if annual:
            rows = annual
    query_words = tokens(question)
    qvector = None
    if any(row["vector"] for row in rows):
        try:
            qvector = embed_many([question])[0]
        except RuntimeError:
            pass
    scored = []
    for row in rows:
        body_words = tokens(row["body"])
        lexical = len(query_words & body_words) / max(1, len(query_words))
        dense = cosine(qvector, json.loads(row["vector"])) if qvector and row["vector"] else 0.0
        score = 0.7 * dense + 0.3 * lexical if qvector else lexical
        scored.append((score, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [row for score, row in scored[:SEARCH_LIMIT] if score > 0]


def answer(db, question):
    docs = db.execute("SELECT id, name, pages, indexed_chunks, uploaded_at FROM documents ORDER BY uploaded_at DESC").fetchall()
    if not docs:
        return {"answer": "Upload a PDF first, then ask a question about it.", "sources": []}
    if re.search(r"\b(what|which|list|show)\b.*\b(files|documents|reports|pdfs|papers)\b", question.lower()):
        listing = "\n".join(f"- {doc['name']} ({doc['pages']} pages)" for doc in docs)
        return {"answer": "Your document collection contains:\n" + listing,
                "sources": [{"id": doc["id"], "name": doc["name"], "page": 1} for doc in docs]}
    found = search(db, question)
    if not found:
        return {"answer": "I could not find relevant text in the uploaded PDFs. Try a more specific question.", "sources": []}
    context = "\n\n".join(
        f"[{i}] {row['name']}, PDF page {row['page']}\n{row['body']}"
        for i, row in enumerate(found, start=1)
    )
    system = (
        "You are a careful research assistant for US stocks. Answer only from the provided PDF excerpts. "
        "Cite the supporting excerpt number as [1], [2], etc. after each factual claim. "
        "Separate evidence, interpretation, and missing information. If the evidence is insufficient, say so. "
        "For full fiscal-year questions, use annual Form 10-K figures, never nine-month or quarterly 10-Q figures. "
        "Copy financial numbers exactly from the relevant table and check the year column before answering. "
        "Do not invent prices, dates, news, or a guaranteed buy/sell signal. "
        "A buy or sell discussion should identify conditions to monitor, not promise returns. "
        "Keep the response concise and readable."
    )
    result = ollama("/api/chat", {"model": CHAT_MODEL, "stream": False, "think": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": f"PDF EXCERPTS:\n{context}\n\nQUESTION: {question}"}],
        "options": {"num_predict": 700, "temperature": 0.2}}, timeout=240)
    text = result.get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("Ollama returned an empty answer")
    return {"answer": text, "sources": [
        {"number": i, "id": row["document_id"], "name": row["name"], "page": row["page"]}
        for i, row in enumerate(found, start=1)]}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, value):
        data = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self, limit=MAX_UPLOAD + 1024 * 1024):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > limit:
            raise ValueError("Request is empty or too large (50 MB PDF limit)")
        return self.rfile.read(length)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/documents":
            with connection() as db:
                docs = [dict(row) for row in db.execute(
                    "SELECT id, name, bytes, pages, uploaded_at, indexed_chunks FROM documents ORDER BY uploaded_at DESC")]
            return self.send_json(200, docs)
        match = re.fullmatch(r"/api/documents/([a-f0-9]{32})/file", path)
        if match:
            document_id = match.group(1)
            with connection() as db:
                row = db.execute("SELECT name FROM documents WHERE id=?", (document_id,)).fetchone()
            stored = FILES / f"{document_id}.pdf"
            if not row or not stored.is_file():
                return self.send_json(404, {"error": "PDF not found"})
            data = stored.read_bytes()
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", row["name"])
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{safe_name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        page_match = re.fullmatch(r"/api/documents/([a-f0-9]{32})/page/(\d+)", path)
        if page_match:
            document_id, page_no = page_match.group(1), int(page_match.group(2))
            with connection() as db:
                row = db.execute("SELECT pages FROM documents WHERE id=?", (document_id,)).fetchone()
            stored = FILES / f"{document_id}.pdf"
            if not row or not stored.is_file() or page_no < 1 or page_no > row["pages"]:
                return self.send_json(404, {"error": "Page not found"})
            pdf = fitz.open(stored)
            try:
                data = pdf[page_no - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")
            finally:
                pdf.close()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=3600")
            self.end_headers()
            return self.wfile.write(data)
        file_path = WEB / ("index.html" if path == "/" else path.lstrip("/"))
        if file_path.parent != WEB or not file_path.is_file():
            return self.send_json(404, {"error": "Not found"})
        data = file_path.read_bytes()
        mime = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}.get(file_path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/documents":
                content_type = self.headers.get("Content-Type", "")
                if not content_type.startswith("multipart/form-data"):
                    raise ValueError("Upload must be multipart/form-data")
                raw = self.read_body()
                message = BytesParser(policy=default).parsebytes(
                    f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
                part = next((part for part in message.iter_parts() if part.get_param("name", header="content-disposition") == "file"), None)
                if not part:
                    raise ValueError("No PDF file was selected")
                name = Path(part.get_filename() or "document.pdf").name
                data = part.get_payload(decode=True)
                if not name.lower().endswith(".pdf") or len(data) > MAX_UPLOAD:
                    raise ValueError("Select a PDF up to 50 MB")
                with connection() as db:
                    result = index_pdf(db, name, data)
                return self.send_json(201, result)
            if path == "/api/chat":
                data = json.loads(self.read_body(64 * 1024))
                question = str(data.get("question", "")).strip()
                if not question or len(question) > 2000:
                    raise ValueError("Enter a question up to 2,000 characters")
                with connection() as db:
                    result = answer(db, question)
                return self.send_json(200, result)
            return self.send_json(404, {"error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            return self.send_json(500, {"error": str(exc)})

    def do_DELETE(self):
        match = re.fullmatch(r"/api/documents/([a-f0-9]{32})", urlparse(self.path).path)
        if not match:
            return self.send_json(404, {"error": "Not found"})
        document_id = match.group(1)
        with connection() as db:
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            db.commit()
        (FILES / f"{document_id}.pdf").unlink(missing_ok=True)
        return self.send_json(200, {"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    with connection():
        pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Stock Research Assistant: http://127.0.0.1:{port}")
    server.serve_forever()
