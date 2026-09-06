import uuid
from anytree import Node, RenderTree


def convert_to_uuid(string: str) -> str:
    """Convert Reddit comment ID to UUID."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, string))


def build_anytree(comment, parent_node=None):
    try:
        node = Node(f"{comment.body}", parent=parent_node)
        for reply in comment.replies:
            build_anytree(reply, parent_node=node)
        return node
    except Exception as e:
        print(f"Skipping comment due to error: {e}")
        return None


def build_thread_string(root_comment):
    try:
        root_comment.refresh()
    except Exception as e:
        print(f"Could not refresh root comment: {e}")
        return "COMMENT TREE UNAVAILABLE"

    root_node = build_anytree(root_comment)
    if not root_node:
        return "COMMENT TREE UNAVAILABLE"

    lines = [""]
    for pre, _, node in RenderTree(root_node):
        lines.append(f"{pre}{node.name}")
    return "\n".join(lines)
