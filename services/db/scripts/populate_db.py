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
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient
from tqdm.auto import tqdm

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
    # marginal -- a GPU is orders of magnitude faster here, so the same backfill
    # is minutes or most of a day. Nothing else in the output distinguishes the
    # two until the ETA has been wrong for a long time.
    # sentence-transformers picks the device itself; this only reports what it
    # chose.
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
        # Same reason: per document, not per post.
        payload["root_comment_score"] = comment.get("score")
        payload["root_comment_author"] = comment.get("author")
        rows.append((text, payload, convert_to_uuid(comment["id"])))
    return rows


# Documents per upsert, filled across files rather than per file.
DEFAULT_BATCH_SIZE = 128

# Documents the embedding model encodes at once. sentence-transformers sorts by
# length before batching, so the longest threads arrive in one batch together --
# enough to exhaust a modest card partway through a run, long after it looked
# like it was working. Only peak memory depends on this, not the vectors it
# produces, so the default is set to survive a laptop GPU rather than to
# saturate a large one.
DEFAULT_ENCODE_BATCH_SIZE = 8


def _dry_run(
    contract: contract_mod.Contract,
    files: list[Path],
    on_progress: Callable[[int, int, int], None] | None,
) -> int:
    """Parse every input file and check each payload, writing nothing.

    Everything that can go wrong cheaply, before the expensive part. The
    collection is validated by the caller; this deliberately does not build the
    vector store, so no model is downloaded either.
    """
    total = 0
    for done, path in enumerate(files, start=1):
        for _text, payload, _point_id in documents_in(path):
            contract_mod.validate_payload(contract, payload)
            total += 1
        if on_progress:
            on_progress(done, len(files), total)
    print(f"Dry run: {len(files)} files, {total} documents would be written to {contract.name!r}.")
    print("Every payload matches the contract. Nothing was written.")
    return 0


def _verify_written(
    contract: contract_mod.Contract,
    client: QdrantClient,
    written: list[str],
    completed_dir: Path,
) -> int:
    """Read every inserted id back, and report any the collection does not hold.

    Returns:
        0 if all of them are present, 1 otherwise.
    """
    missing = []
    for start in range(0, len(written), 100):
        chunk = written[start : start + 100]
        found = {str(p.id) for p in client.retrieve(collection_name=contract.name, ids=chunk)}
        missing.extend(pid for pid in chunk if pid not in found)

    if missing:
        # Beside completed_dir rather than in the working directory. The CLI
        # default puts that in the same place, but a caller elsewhere may not be
        # able to write where the process happens to be running -- in the image
        # the working directory is /app, owned by root while the process is uid
        # 1000, so writing there raises at the very end of a finished run.
        report = completed_dir.parent / "missing_points.json"
        report.write_text(json.dumps(missing, indent=2))
        print(f"WARNING: {len(missing)} inserted points could not be read back; ids in {report}")
        return 1
    print("All inserted points verified present.")
    return 0


def backfill(
    data_dir: Path,
    completed_dir: Path,
    *,
    contract: contract_mod.Contract | None = None,
    client: QdrantClient | None = None,
    encode_batch_size: int = DEFAULT_ENCODE_BATCH_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    on_progress: Callable[[int, int, int], None] | None = None,
    show_progress: bool = True,
) -> int:
    """Backfill the contracted collection from a directory of processed posts.

    The whole write path, callable. :func:`main` is argument parsing around this
    and nothing else, so a notebook or another script runs exactly what the
    command line runs rather than reassembling the batching, the file retiring
    and the read-back check. A second copy of those would be free to drift from
    the one the collection is actually built by, which is the failure this
    project spends a CI check preventing elsewhere.

    Credentials and the collection name are read from the environment
    (``QDRANT_URL``, ``QDRANT_API_KEY``, ``QDRANT_COLLECTION``) unless
    ``contract`` and ``client`` are passed. Deliberately no ``load_dotenv``
    here -- that belongs to the command line, so a caller that has already set
    them cannot have them silently replaced by a file.

    Args:
        data_dir: Directory of processed post JSON files.
        completed_dir: Where each file moves once the batch containing it is
            stored. Created if absent.
        contract: Which collection to write, and its shape. Defaults to the
            environment's.
        client: Qdrant client with write access. Defaults to one built from
            ``QDRANT_URL`` and ``QDRANT_API_KEY``. Pass one to write with
            credentials other than the process's own, which setting
            ``os.environ`` would share with every other caller in the process.
        encode_batch_size: Documents the embedding model encodes at once.
            Bounds peak GPU memory and nothing else.
        batch_size: Documents per upsert, filled across files rather than per
            file.
        dry_run: Validate the collection and every payload, then stop without
            building the model or writing anything.
        on_progress: Called after each file with
            ``(files_done, files_total, documents_written)``. Raise from it to
            stop the run; a file reaches ``completed_dir`` only once the batch
            holding it is stored, so what is there stays accurate.
        show_progress: Draw the tqdm bar. Turn it off where a redrawing bar is
            noise, such as a server log.

    Returns:
        0 on success; 1 if there was nothing to read, or a written point could
        not be read back afterwards.
    """
    contract = contract or contract_mod.load()

    files = sorted(p for p in data_dir.iterdir() if p.suffix == ".json")
    if not files:
        print(f"No .json files in {data_dir}", file=sys.stderr)
        return 1

    if client is None:
        client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"), timeout=120.0)
    # Fails here rather than after embedding thousands of documents into a
    # collection the reader cannot use.
    contract_mod.validate_collection(contract, client)
    print(f"Collection {contract.name!r} matches the contract.")

    if dry_run:
        return _dry_run(contract, files, on_progress)

    vector_store = build_vector_store(contract, client, encode_batch_size)
    completed_dir.mkdir(parents=True, exist_ok=True)

    print(f"Writing {contract.name!r} from the dump; anything already stored is replaced.")

    inserted = 0
    written: list[str] = []
    batch: list[tuple] = []
    # Files whose documents are all sitting in the current batch. They move to
    # completed/ only once that batch is written, which is what makes an
    # interrupted run safe to resume: a file is there only if it is fully stored.
    staged: list[Path] = []

    # tqdm.auto picks a widget in a notebook and a text bar in a terminal. A
    # carriage-return bar writes one output line per redraw in a notebook.
    #
    # Driven by hand rather than by iterating the bar: tqdm closes itself when
    # the iterator it wraps runs out, and the last partial batch is written
    # after that, so an iterated bar finishes showing the second-to-last count.
    with tqdm(
        total=len(files), unit="file", desc=f"Backfilling {contract.name}", disable=not show_progress
    ) as progress:
        for done, path in enumerate(files, start=1):
            for text, payload, point_id in documents_in(path):
                # Reject a drifting payload before it reaches Qdrant, the same
                # way the listener does on every write.
                contract_mod.validate_payload(contract, payload)
                batch.append((text, payload, point_id))
            staged.append(path)
            # The batch fills across files rather than draining after each one. A
            # post averages about three root comments, so draining per file would
            # embed and upsert in threes however large --batch-size is -- roughly
            # forty times the round trips, and the dominant cost of a full backfill.
            # Whole files only: a file is added complete, so every file in `staged`
            # is fully covered by the batch about to be written.
            if len(batch) >= batch_size:
                inserted += flush_batch(vector_store, batch, written)
                staged = _retire(staged, completed_dir)
                # The bar counts files; one post holds several threads, so show
                # the document count too.
                progress.set_postfix(documents=inserted)
            progress.update(1)
            # After the flush, so `inserted` counts stored documents rather
            # than staged ones. Raising here leaves `batch` unwritten and
            # `staged` unretired, so completed/ stays accurate.
            if on_progress:
                on_progress(done, len(files), inserted)

        # Whatever the last full batch left behind.
        inserted += flush_batch(vector_store, batch, written)
        staged = _retire(staged, completed_dir)
        progress.set_postfix(documents=inserted)
        if on_progress:
            on_progress(len(files), len(files), inserted)

    print(f"Files: {len(files)} | Documents written: {inserted}")

    return _verify_written(contract, client, written, completed_dir)


def main() -> int:
    """Parse the command line and run :func:`backfill`."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=Path("processed_data"), help="Processed post JSON files.")
    parser.add_argument("--completed-dir", type=Path, default=Path("completed"), help="Where finished files move to.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Documents per upsert. Filled across files, not per file.",
    )
    parser.add_argument(
        "--encode-batch-size",
        type=int,
        default=DEFAULT_ENCODE_BATCH_SIZE,
        help="Documents the embedding model encodes at once.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the collection and the input files, report the document count, and write nothing.",
    )
    args = parser.parse_args()

    # Only the command line reads a .env; backfill() takes the environment as
    # it finds it.
    load_dotenv()
    return backfill(
        args.data_dir,
        args.completed_dir,
        encode_batch_size=args.encode_batch_size,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
