"""Download and index four official Apple filings for a local classroom demo."""

from urllib.request import urlopen

from app import connection, index_pdf

SOURCES = {
    "Apple-2026-10K.pdf": "https://s2.q4cdn.com/470004039/files/doc_earnings/2026/q4/filing/10K-Q4-2026-as-filed.pdf",
    "Apple-2025-10K.pdf": "https://s2.q4cdn.com/470004039/files/doc_earnings/2025/q4/filing/10K-Q4-2025-as-filed.pdf",
    "Apple-2026-Q3-10Q.pdf": "https://s2.q4cdn.com/470004039/files/doc_earnings/2026/q3/filing/10Q-Q3-2026-as-filed.pdf",
    "Apple-2026-Q2-10Q.pdf": "https://s2.q4cdn.com/470004039/files/doc_earnings/2026/q2/filing/10Q-Q2-2026-as-filed.pdf",
}


def main():
    with connection() as db:
        present = {row["name"] for row in db.execute("SELECT name FROM documents")}
        for name, url in SOURCES.items():
            if name in present:
                print(f"Already indexed: {name}")
                continue
            print(f"Downloading {name}...", flush=True)
            with urlopen(url, timeout=60) as response:
                raw = response.read()
            if len(raw) > 50 * 1024 * 1024:
                raise ValueError(f"{name} exceeds the app's 50 MB limit")
            print(f"Indexing {name}...", flush=True)
            result = index_pdf(db, name, raw)
            print(f"  {result['pages']} pages, {result['chunks']} passages, {result['embedded_chunks']} embeddings", flush=True)


if __name__ == "__main__":
    main()
