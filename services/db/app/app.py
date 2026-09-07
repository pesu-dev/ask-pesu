"""Reddit listener that keeps askPESU's shared Qdrant collection up to date.

Runs as a Hugging Face Space, which expects a web server, so this is a FastAPI
app whose only real job happens on a background thread: consume new r/PESU
comments forever and upsert the thread each one belongs to.

The unit of indexing is a **thread**, not a comment. When any comment arrives the
whole thread is re-rendered and written under a point id derived from the root
comment, so a busy thread is repeatedly overwritten rather than duplicated, and
retrieval returns a conversation with its context instead of an orphan reply.

What it writes is fixed by ``conf/collection.yaml`` and enforced on every upsert;
see :mod:`app.contract`.
"""

import asyncio
import html
import os
import threading
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import praw
import uvicorn
from app import contract as contract_mod
from app.utils import build_thread_string, convert_to_uuid
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from praw.models import Comment
from qdrant_client import QdrantClient

# Before anything below reads the environment. One .env at the repository root
# serves both services: load_dotenv() searches upwards from this module, so it
# is found whether the service runs from a monorepo checkout or from its own
# Space root. In a Space there is no .env and this is a no-op -- the values
# arrive as real environment variables from the Space's secrets.
load_dotenv()

vector_store = None
reddit = None
subreddit = None

# The collection this service writes is contracted with services/api rather than
# configured here -- name, embedding model, vector geometry and payload schema
# all come from conf/collection.yaml and are enforced at startup and on write.
contract = contract_mod.load()

# Set when the listener dies on a contract violation. Retrying would just write
# more bad payloads, so the thread stops and /health starts failing instead of
# leaving a live-looking Space with a dead writer.
listener_error = None

# Set on shutdown so the listener stops retrying. The inner praw stream call
# blocks until the next comment arrives, so the thread does not necessarily
# exit promptly -- it is a daemon, so it never holds up process exit.
shutdown = threading.Event()

# How far back the startup catch-up looks. The stream cannot see anything posted
# before it opens, so this is what covers a restart -- generous on purpose, since
# writes are idempotent and the service has no way to know how long it was down.
CATCH_UP_COMMENTS = 100

client_id = os.getenv("REDDIT_CLIENT_ID")
client_secret = os.getenv("REDDIT_CLIENT_SECRET")
qdrant_url = os.getenv("QDRANT_URL")
qdrant_api_key = os.getenv("QDRANT_API_KEY")


def update_chunk(chunk_id: str, text: str, metadata: dict) -> None:
    """Embed and upsert one thread, replacing any previous version of it.

    Qdrant upserts by id, so passing a stable id makes re-processing idempotent.

    Args:
        chunk_id: Point id -- a UUID derived from the root comment id.
        text: The rendered thread; this is what gets embedded and later retrieved.
        metadata: Payload stored alongside the vector. Validated against the
            contract first, so a drifting schema fails here rather than being
            discovered later by a reader that cannot find a key it needs.

    Raises:
        ContractViolationError: If the payload's keys differ from the contract.
    """
    contract_mod.validate_payload(contract, metadata)
    vector_store.add_texts(
        texts=[text],
        metadatas=[metadata],
        ids=[chunk_id],
    )


def get_root_comment(comment: Comment) -> Comment:
    """Walk up to the top-level comment that starts this thread.

    Each ``parent()`` call may hit the network, so this is a few requests deep on
    a nested reply -- acceptable because it runs once per new comment.

    Args:
        comment: Any comment in the thread.

    Returns:
        The top-level comment; the same object if it was already root.
    """
    parent = comment
    while not parent.is_root:
        parent = parent.parent()
    return parent


def index_comment(comment: Comment, root_comment: Comment | None = None) -> bool:
    """Index the thread one comment belongs to. False if the comment was skipped.

    Shared by the live stream and the startup catch-up so the two cannot produce
    different documents for the same thread -- the same reason the tree renderer
    is shared with the backfill.

    Args:
        comment: Any comment; the thread is found by walking up from it.
        root_comment: The thread's root, when the caller has already resolved it.
            Walking up costs a network request per level, so the catch-up passes
            the root it needed for deduplication rather than paying for it twice.

    Returns:
        True if a point was written, False if the comment was skipped.

    Raises:
        ContractViolationError: If the payload disagrees with the contract.
    """
    # AutoModerator posts boilerplate on many threads; indexing it would put the
    # same text in front of unrelated questions.
    if str(comment.author).lower() == "automoderator":
        return False

    submission = comment.submission
    if root_comment is None:
        root_comment = get_root_comment(comment)

    # Title and body give the thread its topic; without them a reply like
    # "yes, around 8.5" embeds with no idea what it is about.
    chunk = (
        f"TITLE: {submission.title}\nCONTENT: {submission.selftext}\nCOMMENT TREE: {build_thread_string(root_comment)}"
    )

    metadata = {
        "root_comment_id": root_comment.id,
        "post_id": submission.id,
        "author": str(submission.author) if submission.author else None,
        "url": submission.url,
        "permalink": "https://reddit.com" + submission.permalink,
        "score": submission.score,
        "upvote_ratio": submission.upvote_ratio,
        "created_utc": submission.created_utc,
        "flair": submission.link_flair_text,
        "nsfw": submission.over_18,
    }

    # Qdrant point ids must be a UUID or an unsigned integer, and Reddit ids are
    # neither -- hashing gives a stable UUID, so the same thread always lands on
    # the same point and overwrites it.
    update_chunk(convert_to_uuid(root_comment.id), chunk, metadata)
    return True


def catch_up(limit: int = CATCH_UP_COMMENTS) -> None:
    """Index the most recent comments before opening the live stream.

    The stream only ever yields comments posted after it opens, so everything
    posted while this service was down is invisible to it -- and this service
    goes down on every deploy. Without this, each restart left a permanent hole
    that only a full backfill could fill.

    Writes are upserts keyed by the thread's root comment, so re-indexing a
    thread the stream already handled costs an embedding and changes nothing.
    That is what makes overlapping with the stream safe, and why the window is
    generous rather than exact: it does not need to know how long it was down.

    Threads are deduplicated, because a busy thread contributes many of the
    recent comments and they all resolve to one point.

    Args:
        limit: How many recent comments to look back over.
    """
    print(f"Catching up on the last {limit} r/PESU comments...")
    seen: set[str] = set()
    written = 0
    for comment in subreddit.comments(limit=limit):
        # Cheapest test first: skipping AutoModerator here avoids walking a
        # thread only to discard it.
        if str(comment.author).lower() == "automoderator":
            continue
        # Resolved once and handed on. get_root_comment() costs a request per
        # level of nesting, so letting index_comment() walk again would double
        # the traffic of the whole catch-up.
        root_comment = get_root_comment(comment)
        if root_comment.id in seen:
            continue
        seen.add(root_comment.id)
        if index_comment(comment, root_comment=root_comment):
            written += 1
    print(f"Catch-up complete: {written} threads indexed from {len(seen)} distinct threads seen.")


def listen_comments() -> None:
    """Consume new r/PESU comments forever, indexing the thread each belongs to.

    Runs the catch-up first, then streams. ``skip_existing=True`` means the
    stream only yields comments posted after it opens; the catch-up is what
    covers the window before that, so a restart no longer loses the comments
    posted while this service was down.

    Two failure modes, deliberately treated differently. Network and Reddit errors
    are transient, so the stream is simply re-entered. A contract violation is a
    bug that retrying cannot fix, so the loop stops and records the reason for
    /health to report -- better a visibly dead writer than one silently writing
    payloads the reader cannot use.

    The catch-up runs once, not per reconnect. A reconnect follows a transient
    error and its gap is seconds, where a restart's is minutes; re-scanning the
    backlog on every network blip would cost far more than it recovered.
    """
    global listener_error
    try:
        catch_up()
    except contract_mod.ContractViolationError as error:
        # Same fatal case as below: a payload the reader cannot use.
        listener_error = str(error)
        print("FATAL: contract violation during catch-up, stopping:")
        traceback.print_exc()
        return
    except Exception:
        # Anything else is not worth refusing to stream over -- the catch-up is
        # a recovery pass, and the live stream is the service's actual job.
        print("Catch-up failed; continuing to the live stream anyway:")
        traceback.print_exc()

    while not shutdown.is_set():
        try:
            for comment in subreddit.stream.comments(skip_existing=True):
                if index_comment(comment):
                    print("Updated chunk:", comment.id)
        except contract_mod.ContractViolationError as error:
            # A payload schema mismatch is a code/contract bug, not a transient
            # failure -- retrying cannot fix it, so stop and surface it.
            listener_error = str(error)
            print("FATAL: contract violation in listener, stopping:")
            traceback.print_exc()
            return
        except Exception:
            print("Unexpected error in listener:")
            traceback.print_exc()


def background_listener() -> None:
    """Start the listener on a daemon thread.

    The stream blocks, so it cannot share the event loop. Daemon means a stopping
    process is never held up by a thread parked waiting for the next comment.
    """
    thread = threading.Thread(target=listen_comments, daemon=True)
    thread.start()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the Qdrant writer and the Reddit listener, and stop them on shutdown.

    Anything raised here aborts startup, which is what should happen when the
    collection or the embedding model disagrees with conf/collection.yaml --
    writing into a collection services/api cannot read is worse than not
    starting at all.
    """
    global vector_store, reddit, subreddit

    # A previous lifespan in this process would otherwise leave this set, and
    # the listener would start and exit immediately while /health still said ok.
    shutdown.clear()

    client = QdrantClient(
        url=qdrant_url,
        api_key=qdrant_api_key,
        timeout=120.0,
    )

    embeddings = HuggingFaceEmbeddings(model_name=contract.model)
    contract_mod.validate_embedding(contract, embeddings)

    # Creates the collection from the contract when absent; when it already
    # exists, checks its geometry and raises rather than writing into a
    # collection services/api will not be able to read.
    created = contract_mod.ensure_collection(contract, client)
    print(f"Collection {contract.name!r} {'created' if created else 'already exists and matches the contract'}")

    # Hybrid, so every point carries a sparse BM25 vector alongside the dense
    # one. Writing dense-only would leave the collection's sparse vector empty
    # and make enabling hybrid retrieval later a full re-index -- the cost the
    # named dense vector was chosen to avoid. `sparse_vector_name` must be
    # passed: langchain_qdrant defaults it to "langchain-sparse", not ours.
    if contract.sparse_vector_name:
        vector_store = QdrantVectorStore(
            client=client,
            collection_name=contract.name,
            embedding=embeddings,
            vector_name=contract.vector_name,
            sparse_embedding=FastEmbedSparse(model_name=contract.sparse_model),
            sparse_vector_name=contract.sparse_vector_name,
            retrieval_mode=RetrievalMode.HYBRID,
        )
    else:
        # conf/collection.yaml documents that removing the `sparse` block opts
        # out. Without this branch that escape hatch crashes at startup, because
        # HYBRID requires a sparse embedding and FastEmbedSparse("") is invalid.
        vector_store = QdrantVectorStore(
            client=client,
            collection_name=contract.name,
            embedding=embeddings,
            vector_name=contract.vector_name,
        )

    # Fail here rather than in the listener. praw builds the client and resolves
    # a subreddit lazily, so bad credentials do not surface until the stream
    # makes its first request -- on the background thread, inside the catch-all
    # that treats errors as transient. The listener would then retry a 401
    # forever while /health reported ok, which is the silently-dead writer this
    # service is built to avoid.
    if not client_id or not client_secret:
        raise RuntimeError(
            "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must both be set. Create a 'script' app "
            "at https://www.reddit.com/prefs/apps."
        )

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="langchain-reddit-loader",
    )
    subreddit = reddit.subreddit("PESU")

    # One cheap read that forces the OAuth token exchange and proves the
    # credentials work against r/PESU. next() is enough: praw fetches lazily, so
    # this pulls a single listing page rather than the whole subreddit.
    #
    # Run off the event loop. praw is synchronous, so calling it here directly
    # would block the loop for a network round trip -- and praw checks for a
    # running loop and warns that you should be using Async PRAW, which is noise
    # in every startup log. A worker thread has no running loop, so it neither
    # blocks nor warns. The listener itself already runs on its own thread for
    # the same reason.
    def probe_reddit() -> None:
        next(iter(subreddit.new(limit=1)))

    try:
        await asyncio.to_thread(probe_reddit)
    except Exception as error:
        raise RuntimeError(f"Reddit credentials rejected, or r/PESU unreachable: {error}") from error

    background_listener()
    print("Background listener started.")

    yield

    shutdown.set()
    print("Shutdown requested; listener will stop after its current wait.")


app = FastAPI(
    title="askPESU DB updater",
    description="Streams new r/PESU comment threads into the shared Qdrant collection.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve a small status page.

    Hugging Face renders a Space at ``/``, so without this the Space page is a
    404 for anyone who opens it. There is no UI to show -- the work happens on a
    background thread -- so this reports what a reader of that page would want to
    know: whether the listener is alive, and where the code lives.

    It always returns 200, even with the listener stopped. ``/`` is what the
    platform polls to decide the app is up, and a contract violation is
    permanent -- serving 503 here could have the Space restarted on a loop it
    cannot recover from, and every restart of this service loses the comments
    posted while it is down. The failure is reported by ``/health``, which is
    the endpoint that exists to be machine-read.
    """
    ok = listener_error is None
    status = "listening" if ok else "stopped"
    detail = "" if ok else f"<p><strong>Reason:</strong> {html.escape(listener_error)}</p>"
    return HTMLResponse(
        f"""<!doctype html><meta charset="utf-8"><title>askPESU DB updater</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem}}
code{{background:#0001;padding:.1em .3em;border-radius:3px}}</style>
<h1>askPESU DB updater</h1>
<p>Status: <strong>{status}</strong> &middot; collection <code>{html.escape(contract.name)}</code></p>
{detail}
<p>Streams new r/PESU comment threads into the shared Qdrant collection that
<a href="https://huggingface.co/spaces/pesu-dev/askpesu">askPESU</a> answers from.
There is no interface here; see <a href="/health">/health</a>.</p>
<p>Source: <a href="https://github.com/pesu-dev/ask-pesu">pesu-dev/ask-pesu</a></p>""",
        status_code=200,
    )


@app.get("/health")
async def health() -> JSONResponse:
    """Report writer health; 503 once the listener has stopped on a contract violation."""
    if listener_error:
        return JSONResponse({"status": "error", "detail": listener_error}, status_code=503)
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run("app.app:app", host="0.0.0.0", port=7860)
