"""Add embeddings to PDFs that were uploaded while the embedding model was unavailable."""

import json

from app import connection, embed_many


def main():
    with connection() as db:
        rows = db.execute("SELECT id, body FROM chunks WHERE vector IS NULL ORDER BY id").fetchall()
        print(f"Embedding {len(rows)} passages...", flush=True)
        for offset in range(0, len(rows), 24):
            batch = rows[offset:offset + 24]
            vectors = embed_many([row["body"] for row in batch])
            with db:
                db.executemany("UPDATE chunks SET vector=? WHERE id=?",
                               [(json.dumps(vector), row["id"]) for row, vector in zip(batch, vectors)])
            print(f"{min(offset + len(batch), len(rows))}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
