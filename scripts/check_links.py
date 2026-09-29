"""Check that links between this repository's Markdown files resolve.

Every tracked ``.md`` file is scanned for Markdown links. A link is checked when
it points inside the repository: a relative path, a bare ``#anchor``, or a URL
under ``https://github.com/pesu-dev/ask-pesu/blob/dev/``. The target file must
exist, and an anchor into a Markdown file must match one of its headings, using
GitHub's rules for turning a heading into an anchor.

Links inside fenced code blocks and inline code are ignored.

    uv run python scripts/check_links.py
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/pesu-dev/ask-pesu/blob/dev/"

# [text](target) or [text](target "title"); images are links too.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")


def tracked_markdown() -> list[Path]:
    """Every Markdown file git tracks."""
    output = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in output.splitlines() if line]


def prose_lines(path: Path) -> list[tuple[int, str]]:
    """The file's lines outside fenced code blocks, numbered from 1."""
    lines = []
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append((number, line))
    return lines


def slug(heading: str) -> str:
    """The anchor GitHub generates for a heading's text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # a link keeps only its text
    text = text.lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    """Every anchor GitHub generates for the headings in a Markdown file."""
    found: set[str] = set()
    counts: dict[str, int] = {}
    for _, line in prose_lines(path):
        match = HEADING.match(line)
        if not match:
            continue
        base = slug(match.group(2))
        count = counts.get(base, 0)
        counts[base] = count + 1
        found.add(base if count == 0 else f"{base}-{count}")
    return found


def check(path: Path) -> list[str]:
    """Return one message per link in ``path`` that does not resolve."""
    errors = []
    relative = path.relative_to(ROOT)
    for number, line in prose_lines(path):
        for target in LINK.findall(INLINE_CODE.sub("", line)):
            if target.startswith(REPO_URL):
                resolved_from = ROOT
                target = target[len(REPO_URL) :]
            elif re.match(r"^[a-z][a-z0-9+.-]*:", target):
                continue  # any other URL, or mailto:
            else:
                resolved_from = path.parent

            file_part, _, anchor = target.partition("#")
            destination = (resolved_from / unquote(file_part)).resolve() if file_part else path
            if not destination.exists():
                errors.append(f"{relative}:{number}: {target}: no such file")
                continue
            if anchor and destination.suffix == ".md" and anchor not in anchors(destination):
                errors.append(f"{relative}:{number}: {target}: no heading with anchor #{anchor}")
    return errors


def main() -> int:
    """Check every tracked Markdown file and report the links that do not resolve."""
    errors = [error for path in tracked_markdown() for error in check(path)]
    for error in errors:
        print(error)
    if errors:
        print(f"\n{len(errors)} broken link(s).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
