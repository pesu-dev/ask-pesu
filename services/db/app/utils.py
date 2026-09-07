"""Helpers for turning a Reddit comment thread into one indexable string.

A thread is a tree, but an embedding model takes flat text. These render the tree
as indentation, which preserves who replied to whom well enough for the model to
follow a conversation.
"""

import uuid

from anytree import Node, RenderTree
from praw.models import Comment


def convert_to_uuid(string: str) -> str:
    """Derive a stable UUID from a Reddit id.

    Qdrant point ids must be a UUID or an unsigned integer, and Reddit's base-36
    ids are neither. uuid5 is a hash, not random, so the same comment id always
    yields the same point id -- which is what makes re-indexing a thread an
    overwrite instead of a duplicate.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_OID, string))


def build_anytree(comment: Comment, parent_node: Node | None = None) -> Node | None:
    """Mirror a comment and its replies into an anytree node.

    Deleted comments and network failures raise part-way through a tree, so
    failures are swallowed per node: losing one reply is much better than losing
    the whole thread.

    Args:
        comment: The comment to convert.
        parent_node: Node to attach to; None for the root.

    Returns:
        The node, or None if this comment could not be read.
    """
    try:
        node = Node(f"{comment.body}", parent=parent_node)
        for reply in comment.replies:
            build_anytree(reply, parent_node=node)
        return node
    except Exception as e:
        print(f"Skipping comment due to error: {e}")
        return None


def render_tree(root: Node) -> str:
    """Render an anytree node as indented text.

    Shared with the bulk backfill in ``scripts/`` so a thread indexed from a
    Reddit dump is byte-identical to the same thread indexed from the live
    stream. If these two diverged, the same discussion would embed differently
    depending on which path wrote it.
    """
    lines = [""]
    for pre, _, node in RenderTree(root):
        lines.append(f"{pre}{node.name}")
    return "\n".join(lines)


def build_thread_string(root_comment: Comment) -> str:
    """Render a whole thread as indented plain text.

    ``refresh()`` is required: praw returns comment trees lazily and truncated,
    so without it the replies are simply absent.

    Returns:
        The indented thread, or ``"COMMENT TREE UNAVAILABLE"`` if it could not be
        read -- a placeholder rather than an exception, so the submission title
        and body still get indexed.
    """
    try:
        root_comment.refresh()
    except Exception as e:
        print(f"Could not refresh root comment: {e}")
        return "COMMENT TREE UNAVAILABLE"

    root_node = build_anytree(root_comment)
    if not root_node:
        return "COMMENT TREE UNAVAILABLE"
    return render_tree(root_node)
