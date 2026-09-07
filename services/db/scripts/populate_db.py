"""Bulk-load processed r/PESU threads into the Qdrant collection.

The live listener in ``app/app.py`` only sees comments posted after it starts,
so this is how a collection gets its history. It reads the JSON files produced
by ``generate_processed_data.py`` and writes the same shape of point the
listener does: same id derivation, same text layout, same payload keys, and the
same dense + sparse vectors.

Everything about the target -- which collection, which embedding model, which
vector names -- comes from the contract, so this cannot drift from the service
it is backfilling. See ``conf/collection.yaml``.

Safe to re-run: point ids are derived from the root comment id, so a repeat is
an overwrite rather than a duplicate, and already-present ids are skipped
outright to avoid re-embedding them.

    python scripts/populate_db.py --data-dir processed_data

Run it with the listener stopped where possible. Both write by the same id so
they converge rather than conflict, but there is no reason to pay for the same
embedding twice.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient

# The scripts run from services/db, where `app` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import contract as contract_mod  # noqa: E402
from app.utils import convert_to_uuid  # noqa: E402


def existing_point_ids(client: QdrantClient, collection: str) -> set[str]:
    """Collect every point id already in the collection.

    Scrolling the whole collection once is far cheaper than embedding documents
    that are already stored, which is what makes an interrupted run resumable.
    """
    found: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            with_payload=False,
            with_vectors=False,
            offset=offset,
            limit=10_000,
        )
        found.update(str(p.id) for p in points)
        if offset is None:
            return found


def flush_batch(vector_store: QdrantVectorStore, batch: list[tuple], seen: set[str], written: list[str]) -> int:
    """Embed and upsert one batch, then clear it. Returns how many were written."""
    if not batch:
        return 0
    texts = [text for text, _, _ in batch]
    metadatas = [meta for _, meta, _ in batch]
    ids = [point_id for _, _, point_id in batch]
    vector_store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
    seen.update(ids)
    written.extend(ids)
    count = len(ids)
    batch.clear()
    return count


def print_progress(done: int, total: int, started: float) -> None:
    """Draw a single-line progress bar with an ETA."""
    elapsed = time.time() - started
    rate = done / elapsed if elapsed else 0
    eta = (total - done) / rate if rate else 0
    filled = int(30 * done / total) if total else 0
    bar = "#" * filled + "-" * (30 - filled)
    sys.stdout.write(f"\r[{bar}] {done / total * 100 if total else 0:5.1f}% | {done}/{total} | ETA {eta:5.0f}s")
    sys.stdout.flush()


def build_vector_store(contract: contract_mod.Contract, client: QdrantClient) -> QdrantVectorStore:
    """Open the collection for writing, in the same mode the listener uses.

    ``sparse_vector_name`` has to be passed explicitly: langchain_qdrant
    defaults it to "langchain-sparse", which is not what the collection calls
    it. HYBRID also makes ``sparse_embedding`` mandatory.
    """
    embeddings = HuggingFaceEmbeddings(model_name=contract.model)
    contract_mod.validate_embedding(contract, embeddings)
    if not contract.sparse_vector_name:
        return QdrantVectorStore(
            client=client,
            collection_name=contract.name,
            embedding=embeddings,
            vector_name=contract.vector_name,
        )
    return QdrantVectorStore(
        client=client,
        collection_name=contract.name,
        embedding=embeddings,
        vector_name=contract.vector_name,
        sparse_embedding=FastEmbedSparse(model_name=contract.sparse_model),
        sparse_vector_name=contract.sparse_vector_name,
        retrieval_mode=RetrievalMode.HYBRID,
    )


def documents_in(path: Path) -> list[tuple[str, dict, str]]:
    """Turn one processed-post file into (text, payload, point id) tuples.

    The text layout mirrors ``listen_comments`` exactly -- the title and body
    give the thread its topic, without which a reply like "yes, around 8.5"
    embeds with no idea what it is about.
    """
    post = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for comment in post["comments"]:
        text = f"TITLE: {post['title']}\nCONTENT: {post['content']}\nCOMMENT TREE: {comment['body']}"
        rows.append((text, dict(post["metadata"]), convert_to_uuid(comment["id"])))
    return rows


def main() -> int:
    """Backfill the contracted collection from a directory of processed posts."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=Path("processed_data"), help="Processed post JSON files.")
    parser.add_argument("--completed-dir", type=Path, default=Path("completed"), help="Where finished files move to.")
    parser.add_argument("--batch-size", type=int, default=64, help="Documents embedded per upsert.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be written, write nothing.")
    args = parser.parse_args()

    load_dotenv()
    contract = contract_mod.load()

    files = sorted(p for p in args.data_dir.iterdir() if p.suffix == ".json")
    if not files:
        print(f"No .json files in {args.data_dir}", file=sys.stderr)
        return 1

    client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"), timeout=120.0)
    # Fails here rather than after embedding thousands of documents into a
    # collection the reader cannot use.
    contract_mod.validate_collection(contract, client)
    print(f"Collection {contract.name!r} matches the contract.")

    if args.dry_run:
        total = sum(len(documents_in(f)) for f in files)
        print(f"Dry run: {len(files)} files, {total} documents would be written to {contract.name!r}.")
        return 0

    vector_store = build_vector_store(contract, client)
    args.completed_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching existing point ids ...")
    seen = existing_point_ids(client, contract.name)
    print(f"Found {len(seen)} existing points")

    inserted = skipped = 0
    written: list[str] = []
    batch: list[tuple] = []
    started = time.time()
    print_progress(0, len(files), started)

    for index, path in enumerate(files, start=1):
        for text, payload, point_id in documents_in(path):
            if point_id in seen:
                skipped += 1
                continue
            # Reject a drifting payload before it reaches Qdrant, the same way
            # the listener does on every write.
            contract_mod.validate_payload(contract, payload)
            batch.append((text, payload, point_id))
            if len(batch) >= args.batch_size:
                inserted += flush_batch(vector_store, batch, seen, written)
        # Drain before moving the file, so a file in completed/ is fully stored.
        inserted += flush_batch(vector_store, batch, seen, written)
        shutil.move(str(path), args.completed_dir / path.name)
        print_progress(index, len(files), started)

    print(f"\nFiles: {len(files)} | Inserted: {inserted} | Skipped (already present): {skipped}")

    missing = []
    for start in range(0, len(written), 100):
        chunk = written[start : start + 100]
        found = {str(p.id) for p in client.retrieve(collection_name=contract.name, ids=chunk)}
        missing.extend(pid for pid in chunk if pid not in found)

    if missing:
        Path("missing_points.json").write_text(json.dumps(missing, indent=2))
        print(f"WARNING: {len(missing)} inserted points could not be read back; ids in missing_points.json")
        return 1
    print("All inserted points verified present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
