#!/usr/bin/env python3
"""Propagate the repo-root collection contract into each service subtree.

Each service is deployed with ``git subtree split --prefix=services/<name>``,
which ships only that directory -- the repo-root ``conf/`` never reaches the
Space. So the contract has to exist inside each service, and the only way to
keep three copies honest is to generate them.

Run with no arguments to regenerate; ``--check`` reports drift without writing
and exits non-zero, which is what CI and the pre-commit hook use.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# source -> the generated copies that actually ship
TARGETS = {
    Path("conf/collection.yaml"): (
        Path("services/api/conf/collection.yaml"),
        Path("services/db/conf/collection.yaml"),
    ),
    Path("conf/contract.py"): (
        Path("services/api/app/contract.py"),
        Path("services/db/app/contract.py"),
    ),
}

BANNER = """\
# ---------------------------------------------------------------------------
# GENERATED FILE -- DO NOT EDIT.
#
# Source of truth: {source}
# Regenerate with: python scripts/sync_contract.py
#
# This copy exists because the service is deployed as a `git subtree split`,
# which ships only services/<name>/. The repo-root contract never reaches the
# running Space, so it is vendored here instead.
# ---------------------------------------------------------------------------
"""


def render(source: Path) -> str:
    """Return the generated content for a source file: banner plus the source itself."""
    return BANNER.format(source=source.as_posix()) + (REPO_ROOT / source).read_text()


def main() -> int:
    """Regenerate the vendored contract copies, or report drift under --check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    args = parser.parse_args()

    stale = []
    for source, copies in TARGETS.items():
        expected = render(source)
        for copy in copies:
            path = REPO_ROOT / copy
            if path.exists() and path.read_text() == expected:
                continue
            stale.append(copy)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected)

    if not stale:
        return 0
    verb = "out of date" if args.check else "regenerated"
    print(f"Contract copies {verb}:", file=sys.stderr)
    for copy in stale:
        print(f"  {copy.as_posix()}", file=sys.stderr)
    if args.check:
        print("\nRun `python scripts/sync_contract.py` and commit the result.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
