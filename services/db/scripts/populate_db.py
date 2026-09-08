"""Bulk-load processed r/PESU threads into the Qdrant collection.

The live listener in ``app/app.py`` only sees comments posted after it starts,
so this is how a collection gets its history. It reads the JSON files produced
by ``generate_processed_data.py`` and writes the same shape of point the
listener does: same id derivation, same text layout, same payload keys, and the
same dense + sparse vectors.

Everything about the target -- which collection, which embedding model, which
vector names -- comes from the contract, so this cannot drift from the service
it is backfilling. See ``conf/collection.yaml``.

**The dump always wins.** It is a fresh snapshot of r/PESU taken at backfill
time, so for any thread it is at least as complete as what the listener has --
the listener indexes a thread when a comment arrives and never revisits it
afterwards, while the snapshot carries every reply up to the moment it was
taken. Anything already stored is therefore re-embedded and replaced, with no
opt-out: an option to keep the older copy would only ever preserve a staler one.

Point ids come from the root comment id, so a repeat is an overwrite rather than
a duplicate, and interrupted runs resume because each file moves to
``completed/`` only once every document in it is stored.

    uv run python scripts/populate_db.py --data-dir processed_data

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


def flush_batch(vector_store: QdrantVectorStore, batch: list[tuple], written: list[str]) -> int:
    """Embed and upsert one batch, then clear it. Returns how many were written.

    Qdrant upserts by id, so this overwrites any existing point with the same id
    rather than adding a second copy.
    """
    if not batch:
        return 0
    texts = [text for text, _, _ in batch]
    metadatas = [meta for _, meta, _ in batch]
    ids = [point_id for _, _, point_id in batch]
    vector_store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
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


def build_vector_store(
    contract: contract_mod.Contract, client: QdrantClient, encode_batch_size: int
) -> QdrantVectorStore:
    """Open the collection for writing, in the same mode the listener uses.

    ``sparse_vector_name`` has to be passed explicitly: langchain_qdrant
    defaults it to "langchain-sparse", which is not what the collection calls
    it. HYBRID also makes ``sparse_embedding`` mandatory.

    Args:
        contract: The loaded contract.
        client: Qdrant client with write access.
        encode_batch_size: Documents the embedding model processes at once.
            Bounds peak GPU memory and nothing else -- a vector does not depend
            on how many were computed alongside it -- so lowering it cannot make
            this write documents the listener would embed differently.
    """
    embeddings = HuggingFaceEmbeddings(model_name=contract.model, encode_kwargs={"batch_size": encode_batch_size})
    contract_mod.validate_embedding(contract, embeddings)

    # Say which device this is about to use, because the difference is not
    # marginal: measured on this corpus, the contracted model runs at roughly
    # 0.5 documents per second on CPU and 137 on a consumer GPU. A full backfill
    # is therefore either five minutes or the better part of a day, and nothing
    # else in the output distinguishes the two until the ETA has been wrong for
    # an hour. sentence-transformers picks the device itself; this only reports
    # what it chose.
    device = str(getattr(getattr(embeddings, "_client", None), "device", "unknown"))
    print(f"Embedding on {device}.")
    if device.startswith("cpu"):
        print(
            "  WARNING: no GPU in use. The default `cpu` dependency group pins the CPU build "
            "of torch, which is right for the Spaces but makes a full backfill take many hours.\n"
            "  For a CUDA build:\n"
            "    uv sync --extra api --extra db --no-group cpu --group gpu\n"
            "  then carry the same flags on every run, because `uv run` syncs first and would "
            "otherwise reinstall the CPU build:\n"
            "    uv run --no-group cpu --group gpu python scripts/populate_db.py --data-dir ..."
        )
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


def _retire(staged: list[Path], completed_dir: Path) -> list[Path]:
    """Move every fully-written file to ``completed_dir`` and return an empty list.

    Called only after the batch holding those files' documents has been written,
    so presence in ``completed/`` always means "stored", never "attempted".
    """
    for path in staged:
        shutil.move(str(path), completed_dir / path.name)
    return []


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
        # The generator writes metadata once per post, so its root_comment_id is
        # the post's FIRST root comment for every document. Each document is a
        # different thread, and the listener stores the id of the comment it is
        # actually indexing -- so set it per document or the two disagree.
        payload = dict(post["metadata"])
        payload["root_comment_id"] = comment["id"]
        rows.append((text, payload, convert_to_uuid(comment["id"])))
    return rows


def main() -> int:
    """Backfill the contracted collection from a directory of processed posts."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=Path("processed_data"), help="Processed post JSON files.")
    parser.add_argument("--completed-dir", type=Path, default=Path("completed"), help="Where finished files move to.")
    parser.add_argument(
        "--batch-size", type=int, default=128, help="Documents per upsert. Filled across files, not per file."
    )
    # sentence-transformers sorts by length before batching, so the longest
    # threads in the corpus arrive in one batch together. At 8k tokens each that
    # is enough to exhaust a 6 GB card partway through a run: measured here, the
    # default of 32 asked for 1.11 GiB with 869 MiB free and killed the run at
    # file 4,322. Only peak memory depends on this, not the vectors, so the
    # default is set to survive a laptop GPU rather than to saturate a large one.
    parser.add_argument(
        "--encode-batch-size", type=int, default=8, help="Documents the embedding model encodes at once."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the collection and the input files, report the document count, and write nothing.",
    )
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
        # Everything that can go wrong cheaply, before the expensive part: the
        # collection is already validated above, and this parses every input
        # file and checks each payload against the contract. It deliberately
        # does not build the vector store, so no model is downloaded and nothing
        # is written.
        total = 0
        for path in files:
            for _text, payload, _point_id in documents_in(path):
                contract_mod.validate_payload(contract, payload)
                total += 1
        print(f"Dry run: {len(files)} files, {total} documents would be written to {contract.name!r}.")
        print("Every payload matches the contract. Nothing was written.")
        return 0

    vector_store = build_vector_store(contract, client, args.encode_batch_size)
    args.completed_dir.mkdir(parents=True, exist_ok=True)

    print(f"Writing {contract.name!r} from the dump; anything already stored is replaced.")

    inserted = 0
    written: list[str] = []
    batch: list[tuple] = []
    # Files whose documents are all sitting in the current batch. They move to
    # completed/ only once that batch is written, which is what makes an
    # interrupted run safe to resume: a file is there only if it is fully stored.
    staged: list[Path] = []
    started = time.time()
    print_progress(0, len(files), started)

    for index, path in enumerate(files, start=1):
        for text, payload, point_id in documents_in(path):
            # Reject a drifting payload before it reaches Qdrant, the same way
            # the listener does on every write.
            contract_mod.validate_payload(contract, payload)
            batch.append((text, payload, point_id))
        staged.append(path)
        # The batch fills across files rather than draining after each one. A
        # post averages about three root comments, so draining per file would
        # embed and upsert in threes however large --batch-size is -- roughly
        # forty times the round trips, and the dominant cost of a full backfill.
        # Whole files only: a file is added complete, so every file in `staged`
        # is fully covered by the batch about to be written.
        if len(batch) >= args.batch_size:
            inserted += flush_batch(vector_store, batch, written)
            staged = _retire(staged, args.completed_dir)
        print_progress(index, len(files), started)

    # Whatever the last full batch left behind.
    inserted += flush_batch(vector_store, batch, written)
    staged = _retire(staged, args.completed_dir)

    print(f"\nFiles: {len(files)} | Documents written: {inserted}")

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
