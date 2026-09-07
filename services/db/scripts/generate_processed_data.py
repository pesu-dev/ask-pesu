import json
import os
import sys
import time
from anytree import Node, RenderTree

POSTS_FILE = "r_r_PESU_posts.jsonl"
COMMENTS_FILE = "r_r_PESU_comments.jsonl"
OUTPUT_FOLDER = "processed_data"
AUTOMOD_TEXT = "While you wait for a response, please take a moment to review some important and helpful resources."

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

_CHILD_MAP = {}
_CHILDREN_MAP = {}


def clean_comment(body):
    if not body or body.lower() in ["[deleted]", "[removed]"]:
        return None
    if AUTOMOD_TEXT in body:
        return None
    return body


def build_comment_tree(comment_id, parent=None):
    comment = _CHILD_MAP[comment_id]
    text = clean_comment(comment.get("body"))
    if not text:
        return None
    node = Node(text, parent=parent)
    for child_id in _CHILDREN_MAP.get(comment_id, []):
        build_comment_tree(child_id, parent=node)
    return node


def tree_to_string(root):
    lines = []
    for pre, _, node in RenderTree(root):
        lines.append(f"{pre}{node.name}")
    return "\n".join(lines)


def worker(job, progress_q):
    global _CHILD_MAP, _CHILDREN_MAP
    _CHILD_MAP = job["child_map"]
    _CHILDREN_MAP = job["children_map"]

    posts = job["posts"]
    roots = job["roots"]
    failures = 0

    for post_id, post in posts.items():
        try:
            comment_objs = []
            for root_id in roots.get(post_id, []):
                if root_id not in _CHILD_MAP:
                    continue
                tree_root = build_comment_tree(root_id)
                if tree_root:
                    comment_objs.append(
                        {"id": root_id, "body": tree_to_string(tree_root)}
                    )

            if comment_objs:
                output = {
                    "id": post_id,
                    "title": post.get("title", ""),
                    "content": post.get("selftext", ""),
                    "metadata": {
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
                    os.path.join(OUTPUT_FOLDER, f"{post_id}.json"),
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

    progress_q.put(-1)
    return failures


def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def chunkify(lst, n):
    k, m = divmod(len(lst), n)
    out = []
    i = 0
    for j in range(n):
        size = k + (1 if j < m else 0)
        out.append(lst[i : i + size])
        i += size
    return [c for c in out if c]


def build_job(post_ids, comments_by_post, roots, posts):
    child_map = {}
    children_map = {}
    for pid in post_ids:
        for c in comments_by_post.get(pid, []):
            child_map[c["id"]] = c
            parent_id = c.get("parent_id", "")
            if parent_id.startswith("t1_"):
                p = parent_id[3:]
            elif parent_id.startswith("t3_"):
                p = parent_id[3:]
            else:
                p = parent_id
            children_map.setdefault(p, []).append(c["id"])
    return {
        "posts": {pid: posts[pid] for pid in post_ids},
        "roots": {pid: roots.get(pid, []) for pid in post_ids},
        "child_map": child_map,
        "children_map": children_map,
    }


def print_progress(done, total, t0):
    elapsed = time.time() - t0
    pct = done / total * 100
    rate = done / elapsed if elapsed else 0
    eta = (total - done) / rate if rate else 0
    bar_w = 30
    filled = int(bar_w * done / total)
    bar = "#" * filled + "-" * (bar_w - filled)
    sys.stdout.write(
        f"\r[{bar}] {pct:5.1f}% | {done}/{total} | {elapsed:5.0f}s elapsed | ETA {eta:5.0f}s"
    )
    sys.stdout.flush()


def main():
    import multiprocessing as mp

    workers = int(sys.argv[1]) if len(sys.argv) > 1 else mp.cpu_count()

    t0 = time.time()
    print(f"Loading {POSTS_FILE} ...", flush=True)
    posts = {p["id"]: p for p in load_jsonl(POSTS_FILE)}
    print(f"Loading {COMMENTS_FILE} ...", flush=True)

    comments_by_post = {}
    roots = {}
    for c in load_jsonl(COMMENTS_FILE):
        link = c.get("link_id", "")
        pid = link[3:] if link.startswith("t3_") else link
        if pid in posts:
            comments_by_post.setdefault(pid, []).append(c)
            if c.get("parent_id", "").startswith("t3_"):
                roots.setdefault(pid, []).append(c["id"])

    post_ids = list(posts.keys())
    total = len(post_ids)
    n = min(workers, total)
    print(f"Posts: {total} | Comments: {sum(len(v) for v in comments_by_post.values())} | Workers: {n} ({mp.cpu_count()} cores detected)", flush=True)

    chunks = chunkify(post_ids, n)

    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = []
    for chunk in chunks:
        job = build_job(chunk, comments_by_post, roots, posts)
        p = ctx.Process(target=worker, args=(job, q))
        p.start()
        procs.append(p)

    del posts, comments_by_post, roots
    print(f"Starting {len(procs)} workers", flush=True)

    done = 0
    t_start = time.time()
    print_progress(0, total, t_start)
    while done < total:
        try:
            item = q.get(timeout=30)
        except Exception:
            if not any(p.is_alive() for p in procs):
                break
            continue
        if isinstance(item, int) and item < 0:
            continue
        done += item
        print_progress(done, total, t_start)

    for p in procs:
        p.join()

    print()
    print(f"Done. {total} posts processed in {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()