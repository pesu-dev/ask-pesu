"""Runs ``scripts/populate_db.py``'s backfill from an uploaded r/PESU export.

A full run takes about a day: the Spaces have two CPU cores and the image
installs the CPU build of torch. ``notebooks/backfill.ipynb`` is the GPU path.

Requests carry the caller's own Qdrant key in ``X-Qdrant-Api-Key``, and the job
writes with that key. The Space's ``QDRANT_API_KEY`` is not used here, so Qdrant
refuses a read-only key. ``QDRANT_URL`` is read from the environment, never from
the request.
"""

import asyncio
import gzip
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app import contract as contract_mod
from fastapi import APIRouter, HTTPException, Request, UploadFile
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from starlette.datastructures import FormData

from scripts.populate_db import backfill

SERVICE_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = SERVICE_ROOT / "scripts" / "generate_processed_data.py"

# Sized off the corpus as it stands: the two raw exports are about 233 MB
# together, and a tar.gz of them about 22 MB. Raise them if it outgrows these.
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024

# Finished jobs kept for polling; the oldest beyond this are dropped. A record is
# where a run's outcome is read, so it has to outlive the run.
FINISHED_JOBS_KEPT = 10

RUNNING_STATES = ("extracting", "processing", "writing")

router = APIRouter(tags=["backfill"])

# Job records by id, and the id of the running job. One runs at a time; a second
# request is refused.
_jobs: dict[str, dict] = {}
_active: str | None = None
_lock = threading.Lock()


class _CancelledError(RuntimeError):
    """Raised out of the progress hook to stop a running backfill."""


def _now() -> str:
    """Current time, as an ISO-8601 string with an offset."""
    return datetime.now(UTC).isoformat()


def _view(job: dict) -> dict:
    """The job record as it is served, without the internal cancellation flag."""
    return {key: value for key, value in job.items() if key != "cancel"}


def _finish(job: dict, state: str, detail: str | None = None) -> None:
    """Put a job into a terminal state and release the slot if it held it."""
    global _active
    job.update(state=state, detail=detail, finished_at=_now())
    with _lock:
        if _active == job["job_id"]:
            _active = None


def _copy_part(part: UploadFile, destination: Path, decompress: bool) -> None:
    """Write one uploaded part to ``destination``.

    Call this while the request is still in scope. Starlette spools a part over
    a megabyte to a temporary file and deletes it when the request ends, so the
    job thread would find nothing there.

    Args:
        part: The uploaded file from the parsed form.
        destination: Where to write it.
        decompress: Expand a gzip stream on the way. False for the archive,
            whose own ``.gz`` suffix is tarfile's business.
    """
    part.file.seek(0)
    if decompress and (part.filename or "").lower().endswith(".gz"):
        with gzip.open(part.file, "rb") as source, open(destination, "wb") as handle:
            shutil.copyfileobj(source, handle, 1024 * 1024)
        return
    with open(destination, "wb") as handle:
        shutil.copyfileobj(part.file, handle, 1024 * 1024)


def _extract(archive: Path, posts: Path, comments: Path) -> None:
    """Pull the two exports out of an uploaded tar archive.

    Members are copied to paths chosen here rather than unpacked with
    ``extractall``: a member name is only ever read, never used as a
    destination, so ``../../etc/passwd`` has nowhere to land. Tar headers
    declare uncompressed sizes, so the total is checked before anything is
    written. The first member matching each kind wins.

    Raises:
        ValueError: If either export is missing, or the two together exceed
            ``MAX_EXTRACTED_BYTES``.
    """
    destinations = {"posts": posts, "comments": comments}
    found: dict[str, str] = {}
    total = 0
    with tarfile.open(archive, mode="r:*") as tar:
        for member in tar:
            name = PurePosixPath(member.name).name.lower()
            if not member.isfile() or not name.endswith(".jsonl"):
                continue
            kind = "posts" if "posts" in name else "comments" if "comments" in name else None
            if kind is None or kind in found:
                continue
            total += member.size
            if total > MAX_EXTRACTED_BYTES:
                raise ValueError(f"Archive expands to more than {MAX_EXTRACTED_BYTES} bytes; refusing to extract it.")
            source = tar.extractfile(member)
            if source is None:
                continue
            with open(destinations[kind], "wb") as handle:
                shutil.copyfileobj(source, handle, 1024 * 1024)
            found[kind] = member.name

    missing = sorted(set(destinations) - set(found))
    if missing:
        raise ValueError(
            f"Archive has no {' or '.join(missing)} export. Looking for members named *.jsonl "
            f"containing 'posts' and 'comments'; found {sorted(found.values()) or 'none'}."
        )


def _process(posts: Path, comments: Path, processed: Path) -> None:
    """Rebuild the threads by running the generator as a separate process.

    It must not be imported and called here. ``generate_processed_data.py``
    shards with the ``spawn`` start method, and spawning from inside the server
    re-imports ``app/app.py`` in every child, contract load and embedding stack
    included. A subprocess also releases its peak memory when it exits.

    Raises:
        RuntimeError: If the generator exits non-zero.
    """
    processed.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--posts",
            str(posts),
            "--comments",
            str(comments),
            "--output-dir",
            str(processed),
        ],
        cwd=str(SERVICE_ROOT),
        # stdout is a progress bar redrawn once per post. stderr carries the
        # failures, and is what a failed job reports.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"generate_processed_data.py exited {result.returncode}: {result.stderr.strip()[-2000:]}")


def _run(job: dict, workdir: Path, uploads: dict[str, Path], api_key: str) -> None:
    """Extract, process and write, then remove the working directory.

    Runs on a daemon thread. ``api_key`` is a parameter and not a field on the
    job record, which is served by ``GET /backfill/{job_id}``.
    """
    posts = workdir / "posts.jsonl"
    comments = workdir / "comments.jsonl"
    processed = workdir / "processed"
    completed = workdir / "completed"

    def hook(files_done: int, files_total: int, documents: int) -> None:
        if job["cancel"]:
            raise _CancelledError
        job.update(files_done=files_done, files_total=files_total, documents=documents)

    try:
        if "archive" in uploads:
            _extract(uploads["archive"], posts, comments)
        else:
            posts, comments = uploads["posts"], uploads["comments"]

        job["state"] = "processing"
        _process(posts, comments, processed)
        if not any(processed.glob("*.json")):
            raise RuntimeError(
                "The export produced no threads. Check that the two files are the r/PESU posts and "
                "comments exports, and that the comments belong to the posts."
            )

        job["state"] = "writing"
        contract = contract_mod.load(job["collection"])
        client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=api_key, timeout=120.0)
        code = backfill(
            processed,
            completed,
            contract=contract,
            client=client,
            dry_run=job["dry_run"],
            on_progress=hook,
            show_progress=False,
        )
        if code:
            _finish(job, "failed", "backfill() reported a failure; see the Space logs.")
        else:
            _finish(job, "done")
    except _CancelledError:
        _finish(job, "cancelled", "Cancelled on request. Documents already written are stored.")
    except Exception as error:
        traceback.print_exc()
        _finish(job, "failed", f"{type(error).__name__}: {error}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _check_key(collection: str, api_key: str) -> None:
    """Check the key and the collection in one round trip, before the body is read.

    Raises:
        HTTPException: The response to send instead of starting a job.
    """
    client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=api_key, timeout=30.0)
    try:
        exists = await asyncio.to_thread(client.collection_exists, collection)
    except UnexpectedResponse as error:
        if error.status_code in (401, 403):
            raise HTTPException(403, "Qdrant rejected this key. A backfill needs write access.") from error
        raise HTTPException(502, f"Qdrant is not reachable: {error}") from error
    except Exception as error:
        raise HTTPException(502, f"Qdrant is not reachable: {error}") from error
    if not exists:
        raise HTTPException(
            400,
            f"Collection {collection!r} does not exist. This endpoint writes an existing collection "
            f"and does not create one; the listener does that at startup.",
        )


def _claim(collection: str, dry_run: bool) -> dict:
    """Take the single job slot, or raise 409. Returns the new job record."""
    global _active
    with _lock:
        if _active is not None and _jobs[_active]["state"] in RUNNING_STATES:
            raise HTTPException(409, f"Backfill {_active} is already running. One at a time.")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {
            "job_id": job_id,
            "state": "extracting",
            "collection": collection,
            "dry_run": dry_run,
            "files_done": 0,
            "files_total": 0,
            "documents": 0,
            "started_at": _now(),
            "finished_at": None,
            "detail": None,
            "cancel": False,
        }
        _active = job_id

        finished = [j for j in _jobs.values() if j["state"] not in RUNNING_STATES]
        for stale in sorted(finished, key=lambda j: j["started_at"])[:-FINISHED_JOBS_KEPT]:
            del _jobs[stale["job_id"]]
        return _jobs[job_id]


def _stash(form: FormData, workdir: Path) -> dict[str, Path]:
    """Write the uploaded parts into ``workdir`` and say which shape arrived.

    Raises:
        HTTPException: If the form is neither an archive nor both exports.
    """
    fields = set(form.keys())
    archive = "archive" in fields
    loose = {"posts", "comments"} <= fields
    if archive == loose:
        raise HTTPException(
            400,
            f"Send either archive=@dump.tar.gz, or posts=@... and comments=@... together. Got {sorted(fields)}.",
        )

    if archive:
        destination = workdir / "upload.tar.gz"
        _copy_part(form["archive"], destination, decompress=False)
        return {"archive": destination}

    uploads = {}
    for field in ("posts", "comments"):
        destination = workdir / f"{field}.jsonl"
        _copy_part(form[field], destination, decompress=True)
        uploads[field] = destination
    return uploads


@router.post(
    "/backfill",
    status_code=202,
    summary="Rebuild a collection from a raw r/PESU export",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "archive": {"type": "string", "format": "binary"},
                            "posts": {"type": "string", "format": "binary"},
                            "comments": {"type": "string", "format": "binary"},
                        },
                    }
                }
            },
        }
    },
)
async def start_backfill(request: Request, collection: str | None = None, dry_run: bool = False) -> dict:
    """Start a backfill and return its job id.

    The body is not declared as a parameter. FastAPI parses a declared body
    before it resolves anything else, so an ``UploadFile`` parameter would read
    the whole upload before the checks below could reject it.
    """
    api_key = request.headers.get("x-qdrant-api-key")
    if not api_key:
        raise HTTPException(401, "X-Qdrant-Api-Key header is required: send the key you would backfill with.")
    if not collection:
        raise HTTPException(
            400,
            "The ?collection= query parameter is required. It has no default because writing the wrong "
            "collection succeeds silently.",
        )

    declared = request.headers.get("content-length")
    if declared is None:
        raise HTTPException(411, "Content-Length is required, because it is what bounds the upload.")
    try:
        length = int(declared)
    except ValueError as error:
        raise HTTPException(400, f"Content-Length {declared!r} is not a number.") from error
    if length > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Upload is {length} bytes; the limit is {MAX_UPLOAD_BYTES}.")

    await _check_key(collection, api_key)

    job = _claim(collection, dry_run)
    workdir = Path(tempfile.mkdtemp(prefix="backfill-"))
    try:
        # max_fields=0: every expected part is a file. Capping the file count
        # stops many small parts standing in for the one large upload that the
        # Content-Length check would have caught.
        async with request.form(max_files=3, max_fields=0) as form:
            uploads = await asyncio.to_thread(_stash, form, workdir)
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        _finish(job, "failed", "Rejected before it started.")
        raise
    except Exception as error:
        shutil.rmtree(workdir, ignore_errors=True)
        _finish(job, "failed", f"{type(error).__name__}: {error}")
        raise HTTPException(400, f"Could not read the upload: {error}") from error

    threading.Thread(target=_run, args=(job, workdir, uploads, api_key), daemon=True).start()
    return _view(job)


@router.get("/backfill/{job_id}", summary="Report on a backfill")
async def backfill_status(job_id: str) -> dict:
    """Return one job record. Job state is in memory, so a restart loses it."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No job {job_id!r}. Records are held in memory and do not survive a restart.")
    return _view(job)


@router.delete("/backfill/{job_id}", summary="Stop a running backfill")
async def cancel_backfill(job_id: str) -> dict:
    """Ask a running job to stop.

    The flag is read between batches, so a job embedding one takes minutes to
    notice. Documents already written stay written.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No job {job_id!r}.")
    if job["state"] not in RUNNING_STATES:
        raise HTTPException(409, f"Job {job_id} is already {job['state']}.")
    job["cancel"] = True
    return _view(job)
