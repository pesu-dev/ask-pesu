"""Turn raw r/PESU dumps into the per-post JSON files that populate_db.py loads.

Input is two JSONL exports -- posts and comments -- which this reassembles into
threads: for each post, every top-level comment becomes one document containing
that comment and all of its replies, rendered as indented text.

This is the offline half of what the live listener does per comment. The tree
rendering is deliberately imported from ``app.utils`` rather than reimplemented,
so a thread backfilled from a dump is byte-identical to the same thread indexed
from the stream.

Posts are sharded across worker processes because the work is CPU-bound tree
building over tens of thousands of posts, and each shard carries its own slice
of the id maps so nothing is shared between processes.

    python scripts/generate_processed_data.py
    python scripts/generate_processed_data.py --posts dump/posts.jsonl \
        --comments dump/comments.jsonl --output-dir processed_data

Its output is what ``populate_db.py`` reads, so run that next.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from multiprocessing import Queue
from pathlib import Path

from anytree import Node

# The scripts run from services/db, where `app` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils import render_tree  # noqa: E402

# Defaults matching the file names the r/PESU exports arrive with; override on
# the command line if yours are named differently.
DEFAULT_POSTS_FILE = "r_r_PESU_posts.jsonl"
DEFAULT_COMMENTS_FILE = "r_r_PESU_comments.jsonl"
DEFAULT_OUTPUT_FOLDER = "processed_data"

# AutoModerator's standard reply. It appears on a large share of threads, so
# indexing it would put identical boilerplate in front of unrelated questions.
AUTOMOD_TEXT = "While you wait for a response, please take a moment to review some important and helpful resources."

# The comment id maps for the shard this process is handling: id -> comment, and
# parent id -> child ids. Module-level because each worker sets them once from
# its job and then recurses through build_comment_tree, which would otherwise
# have to thread both maps through every call.
_CHILD_MAP = {}
_CHILDREN_MAP = {}


def clean_comment(body: str | None) -> str | None:
    """Drop comments that carry no content worth indexing.

    Removed and deleted comments leave placeholder bodies, and AutoModerator
    posts the same boilerplate on many threads -- indexing it would put
    identical text in front of unrelated questions.
    """
    if not body or body.lower() in ["[deleted]", "[removed]"]:
        return None
    if AUTOMOD_TEXT in body:
        return None
    return body


def build_comment_tree(comment_id: str, parent: Node | None = None) -> Node | None:
    """Rebuild one comment and its replies as an anytree node.

    The dump gives a flat list with parent pointers, so the tree is rebuilt from
    the id maps this module populates. Returns None when the comment itself has
    no usable body, which prunes that whole branch.
    """
    comment = _CHILD_MAP[comment_id]
    text = clean_comment(comment.get("body"))
    if not text:
        return None
    node = Node(text, parent=parent)
    for child_id in _CHILDREN_MAP.get(comment_id, []):
        build_comment_tree(child_id, parent=node)
    return node


def worker(job: dict, progress_q: Queue) -> None:
    """Process one shard of posts, writing a JSON file per post with comments.

    Progress and failures both travel back over ``progress_q``: a positive int
    counts posts finished, and a final dict reports how many of them failed.
    A worker's return value would be discarded -- ``multiprocessing.Process``
    does not collect one -- so the queue is the only channel there is.

    Args:
        job: One shard, as built by :func:`build_job`.
        progress_q: Queue back to the parent process.
    """
    global _CHILD_MAP, _CHILDREN_MAP
    _CHILD_MAP = job["child_map"]
    _CHILDREN_MAP = job["children_map"]

    posts = job["posts"]
    roots = job["roots"]
    output_folder = job["output_folder"]
    failures = 0

    for post_id, post in posts.items():
        try:
            comment_objs = []
            for root_id in roots.get(post_id, []):
                if root_id not in _CHILD_MAP:
                    continue
                tree_root = build_comment_tree(root_id)
                if tree_root:
                    comment_objs.append({"id": root_id, "body": render_tree(tree_root)})

            if comment_objs:
                output = {
                    "id": post_id,
                    "title": post.get("title", ""),
                    "content": post.get("selftext", ""),
                    "metadata": {
                        # One metadata block per post, but each entry in
                        # "comments" is a separate thread with its own root.
                        # populate_db.py overwrites this per document with the
                        # id of the thread it is actually writing, so what is
                        # stored here is only a placeholder.
                        "root_comment_id": roots[post_id][0],
                        "post_id": post_id,
                        "author": post.get("author"),
                        "url": post.get("url"),
                        "permalink": "https://reddit.com" + post.get("permalink", ""),
                        "score": post.get("score"),
                        "upvote_ratio": post.get("upvote_ratio"),
                        "created_utc": post.get("created_utc"),
                        "flair": post.get("link_flair_text"),
                        "nsfw": post.get("over_18"),
                    },
                    "comments": comment_objs,
                }
                with open(
                    os.path.join(output_folder, f"{post_id}.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(output, f, indent=2, ensure_ascii=False)
        except Exception as e:
            failures += 1
            sys.stderr.write(f"FAIL [{post_id}]: {e!r}\n")
            sys.stderr.flush()
        finally:
            progress_q.put(1)

    progress_q.put({"failures": failures})


def load_jsonl(path: str) -> Iterator[dict]:
    """Yield each JSON object from a JSONL file, skipping blank lines."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def chunkify(lst: list, n: int) -> list[list]:
    """Split a list into n contiguous, near-equal shards, dropping empty ones."""
    k, m = divmod(len(lst), n)
    out = []
    i = 0
    for j in range(n):
        size = k + (1 if j < m else 0)
        out.append(lst[i : i + size])
        i += size
    return [c for c in out if c]


def build_job(post_ids: list[str], comments_by_post: dict, roots: dict, posts: dict, output_folder: str) -> dict:
    """Build one worker payload: its posts plus the id maps needed to rebuild trees.

    Each shard is self-contained. ``spawn`` pickles the job to the child process,
    so carrying only this shard's comments keeps that transfer proportional to
    the shard rather than to the whole dump.

    Args:
        post_ids: The posts this worker owns.
        comments_by_post: All comments, grouped by post id.
        roots: Top-level comment ids, by post id.
        posts: All posts, by id.
        output_folder: Where the worker writes its JSON files.

    Returns:
        The job dict :func:`worker` consumes.
    """
    child_map = {}
    children_map = {}
    for pid in post_ids:
        for c in comments_by_post.get(pid, []):
            child_map[c["id"]] = c
            # Reddit fullnames prefix the type: t1_ is a comment, t3_ is a post.
            # Either way the parent is the id after the prefix -- a t3_ parent
            # just means this comment is top-level, and roots are tracked
            # separately, so both prefixes are stripped the same way.
            parent_id = c.get("parent_id", "")
            parent = parent_id[3:] if parent_id[:3] in ("t1_", "t3_") else parent_id
            children_map.setdefault(parent, []).append(c["id"])
    return {
        "posts": {pid: posts[pid] for pid in post_ids},
        "roots": {pid: roots.get(pid, []) for pid in post_ids},
        "child_map": child_map,
        "children_map": children_map,
        "output_folder": output_folder,
    }


def print_progress(done: int, total: int, t0: float) -> None:
    """Draw a single-line progress bar with an ETA."""
    elapsed = time.time() - t0
    pct = done / total * 100
    rate = done / elapsed if elapsed else 0
    eta = (total - done) / rate if rate else 0
    bar_w = 30
    filled = int(bar_w * done / total)
    bar = "#" * filled + "-" * (bar_w - filled)
    sys.stdout.write(f"\r[{bar}] {pct:5.1f}% | {done}/{total} | {elapsed:5.0f}s elapsed | ETA {eta:5.0f}s")
    sys.stdout.flush()


def load_dumps(posts_path: str, comments_path: str) -> tuple[dict, dict, dict]:
    """Read both JSONL exports and index them by post.

    Comments arrive as one flat list for the whole subreddit, so this groups them
    by the post they belong to and notes which are top-level. A comment's
    ``link_id`` is always its post; its ``parent_id`` is the post only when the
    comment is top-level, which is exactly what makes it a thread root.

    Comments whose post is not in the posts dump are dropped -- without the title
    and body there is no thread to index.

    Args:
        posts_path: Posts JSONL export.
        comments_path: Comments JSONL export.

    Returns:
        ``(posts, comments_by_post, roots)``, all keyed by post id.
    """
    print(f"Loading {posts_path} ...", flush=True)
    posts = {p["id"]: p for p in load_jsonl(posts_path)}
    print(f"Loading {comments_path} ...", flush=True)

    comments_by_post: dict[str, list[dict]] = {}
    roots: dict[str, list[str]] = {}
    for comment in load_jsonl(comments_path):
        link = comment.get("link_id", "")
        post_id = link[3:] if link.startswith("t3_") else link
        if post_id in posts:
            comments_by_post.setdefault(post_id, []).append(comment)
            if comment.get("parent_id", "").startswith("t3_"):
                roots.setdefault(post_id, []).append(comment["id"])
    return posts, comments_by_post, roots


def run_workers(jobs: list[dict], total: int) -> int:
    """Run every shard in its own process and draw one progress bar for all of them.

    Args:
        jobs: Shards, as built by :func:`build_job`.
        total: Posts across all shards, which is what the bar counts up to.

    Returns:
        How many posts failed.
    """
    import multiprocessing as mp

    # `spawn` rather than the platform default: each worker re-imports this
    # module and receives its maps in the pickled job, so nothing depends on
    # inheriting the parent's memory and behaviour is identical on every OS.
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    procs = []
    for job in jobs:
        proc = ctx.Process(target=worker, args=(job, queue))
        proc.start()
        procs.append(proc)
    print(f"Starting {len(procs)} workers", flush=True)

    done = 0
    failures = 0
    started = time.time()
    print_progress(0, total, started)
    while done < total:
        try:
            item = queue.get(timeout=30)
        except Exception:
            # Nothing for 30 seconds. If every worker has exited, the counts that
            # are still missing are never coming, and waiting would hang here.
            if not any(proc.is_alive() for proc in procs):
                break
            continue
        if isinstance(item, dict):
            failures += item["failures"]
            continue
        done += item
        print_progress(done, total, started)

    for proc in procs:
        proc.join()

    # Drain what the workers queued after the loop stopped counting, so the
    # failure total covers every shard and not only those that reported early.
    while not queue.empty():
        item = queue.get()
        if isinstance(item, dict):
            failures += item["failures"]

    print()
    print(f"Done. {done}/{total} posts processed in {time.time() - started:.1f}s")
    return failures


def main() -> int:
    """Turn the dumps into per-post JSON files, sharded across worker processes.

    Returns:
        0 if every post was processed, 1 if any worker reported a failure -- so a
        partial run is visible to a caller and not only in the scrollback.
    """
    import multiprocessing as mp

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--posts", default=DEFAULT_POSTS_FILE, help="Posts JSONL export.")
    parser.add_argument("--comments", default=DEFAULT_COMMENTS_FILE, help="Comments JSONL export.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_FOLDER, help="Where per-post JSON files are written.")
    parser.add_argument("--workers", type=int, default=0, help="Worker processes. Default: one per core.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    posts, comments_by_post, roots = load_dumps(args.posts, args.comments)

    post_ids = list(posts)
    total = len(post_ids)
    if not total:
        print(f"No posts found in {args.posts}", file=sys.stderr)
        return 1

    workers = min(args.workers or mp.cpu_count(), total)
    comment_count = sum(len(v) for v in comments_by_post.values())
    print(f"Posts: {total} | Comments: {comment_count} | Workers: {workers} ({mp.cpu_count()} cores)", flush=True)

    jobs = [build_job(chunk, comments_by_post, roots, posts, args.output_dir) for chunk in chunkify(post_ids, workers)]
    # The parent's copies are no longer needed; every job carries its own slice.
    # On a full dump this is the difference between holding one copy and two.
    del posts, comments_by_post, roots

    failures = run_workers(jobs, total)
    if failures:
        print(f"WARNING: {failures} posts failed; see the FAIL lines above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
