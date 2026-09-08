"""Assert the things this repository must keep in step but cannot share.

Five pairs of files have to agree and are written separately, because each side
is shipped somewhere the other never reaches. A `git subtree split` sends only
``services/<name>/``, so the two services cannot import a common module; the
frontend is TypeScript; a Space's README frontmatter is read by the platform
before any code runs; and pre-commit resolves its own hook environments from a
git ref, never from this project's lockfile. That leaves agreement by hand,
which is the kind that drifts silently -- the contract loaders already did
once.

So each pair is checked here instead, and CI runs this on every push and pull
request. Run it directly to check a working tree:

    uv run python scripts/check_duplication.py
"""

import ast
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = yaml.safe_load((ROOT / "conf" / "collection.yaml").read_text())["collection"]


class _BlankStrings(ast.NodeTransformer):
    """Replace every string literal with a constant, leaving structure behind.

    The two contract loaders are meant to behave identically while wording their
    error messages for a reader or a writer. Comparing them literally would fail
    on that difference and say nothing useful; comparing them with the strings
    removed asks the question that matters -- does the code do the same thing?
    """

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        """Blank a string constant, leaving numbers and None alone."""
        return ast.Constant(value="") if isinstance(node.value, str) else node

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.Constant:
        """Blank an f-string wholesale; its interpolations are message text."""
        return ast.Constant(value="")


def _definitions(path: Path) -> dict[str, str]:
    """Map every top-level def/class in a module to a string-blanked AST dump."""
    out = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            stripped = _BlankStrings().visit(ast.parse(ast.unparse(node)))
            ast.fix_missing_locations(stripped)
            out[node.name] = ast.dump(stripped)
    return out


def check_contract_loaders() -> list[str]:
    """The two app/contract.py files must behave identically where they overlap.

    Each service carries its own copy because neither can import from the other
    once split into a Space. They diverge on purpose -- the reader adds
    ``require_metadata``, the writer adds collection creation and payload
    validation -- so only the shared names are compared.
    """
    api = _definitions(ROOT / "services" / "api" / "app" / "contract.py")
    db = _definitions(ROOT / "services" / "db" / "app" / "contract.py")
    shared = sorted(set(api) & set(db))
    if not shared:
        return ["the two contract loaders share no definitions at all; one of them is not being parsed"]
    return [
        f"contract loaders disagree on {name}(): same name, different logic. "
        f"Compare services/api/app/contract.py and services/db/app/contract.py."
        for name in shared
        if api[name] != db[name]
    ]


def _dict_keys_named(path: Path, target: str) -> set[str] | None:
    """Find a dict literal assigned to, or keyed by, ``target`` and return its keys."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        # `metadata = {...}`
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if target in names:
                return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        # `{"metadata": {...}}`
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if isinstance(key, ast.Constant) and key.value == target and isinstance(value, ast.Dict):
                    return {k.value for k in value.keys if isinstance(k, ast.Constant)}
    return None


def check_payload_keys() -> list[str]:
    """Every writer's payload must carry exactly the contracted keys.

    ``validate_payload`` enforces this at run time, but only once a deploy is
    live -- and for the listener that means stopping and turning /health into a
    503. Catching it here turns that outage into a failed check.
    """
    contracted = set(CONTRACT["metadata"])
    problems = []
    for relative, target in (
        ("services/db/app/app.py", "metadata"),
        ("services/db/scripts/generate_processed_data.py", "metadata"),
    ):
        found = _dict_keys_named(ROOT / relative, target)
        if found is None:
            problems.append(f"{relative}: no payload dict named {target!r} found -- has it been renamed?")
        elif found != contracted:
            missing = sorted(contracted - found)
            extra = sorted(found - contracted)
            problems.append(
                f"{relative}: payload keys disagree with conf/collection.yaml -- missing {missing}, unexpected {extra}"
            )
    return problems


def _frontmatter(path: Path) -> dict:
    """Parse the YAML frontmatter a Hugging Face Space reads from its README."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def check_space_frontmatter() -> list[str]:
    """Each Space must declare the contracted embedding model.

    The platform reads this frontmatter before any code runs, so it cannot be
    derived from the contract at startup. ``preload_from_hub`` is what fetches
    the weights at build time; a stale entry there means the model is downloaded
    on every cold start instead.
    """
    model = CONTRACT["dense"]["model"]
    problems = []
    for service in ("api", "db"):
        readme = ROOT / "services" / service / "README.md"
        front = _frontmatter(readme)
        for field in ("models", "preload_from_hub"):
            declared = front.get(field) or []
            if model not in declared:
                problems.append(
                    f"services/{service}/README.md: {field}: does not list {model!r}, "
                    f"the model contracted in conf/collection.yaml (declares {declared})"
                )
    return problems


def check_stream_events() -> list[str]:
    """The NDJSON event names must match between the backend and its client.

    The backend declares them in a pydantic ``Literal``; the client declares a
    TypeScript union and compares against the same strings. Nothing connects the
    two, and a mismatch is silent: an event the client does not know is dropped
    on the floor mid-answer.
    """
    model = (ROOT / "services" / "api" / "app" / "models" / "response" / "ask.py").read_text()
    match = re.search(r"Literal\[([^\]]+)\]", model)
    if not match:
        return ["services/api/app/models/response/ask.py: no Literal[...] of event types found"]
    backend = set(re.findall(r'"([a-z]+)"', match.group(1)))

    client_path = ROOT / "services" / "api" / "frontend" / "src" / "lib" / "api.ts"
    lines = client_path.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("export type StreamEvent")), None)
    if start is None:
        return [f"{client_path.relative_to(ROOT)}: no `export type StreamEvent = ...` union found"]
    # Take the declaration and every continuation line after it. A regex is the
    # wrong tool: each union member ends in a semicolon of its own, so matching
    # up to the first one stops inside the first member.
    union = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip().startswith("|"):
            break
        union.append(line)
    client = set(re.findall(r'type:\s*"([a-z]+)"', "\n".join(union)))

    if backend == client:
        return []
    return [
        "stream event types disagree: services/api/app/models/response/ask.py emits "
        f"{sorted(backend)}, frontend/src/lib/api.ts handles {sorted(client)}. "
        "Change both together."
    ]


def check_ruff_pin() -> list[str]:
    """The ruff a contributor runs must be the ruff CI enforces.

    pre-commit installs its hooks into environments it builds itself from the
    ``rev`` in .pre-commit-config.yaml, and never consults uv.lock. The `dev`
    dependency group is what puts ruff on a contributor's PATH for
    ``uv run ruff``. So the version is written twice, and if the two drift a
    rule can pass locally and fail in CI -- or the reverse, which is worse,
    because it looks like CI is broken.
    """
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hooked = next(
        (repo["rev"].removeprefix("v") for repo in config["repos"] if "ruff-pre-commit" in repo["repo"]),
        None,
    )
    if hooked is None:
        return ["no ruff-pre-commit repo in .pre-commit-config.yaml; this check can no longer see the hook version"]

    group = tomllib.loads((ROOT / "pyproject.toml").read_text()).get("dependency-groups", {}).get("dev")
    if group is None:
        return ["pyproject.toml has no `dev` dependency group; `uv sync` would install no ruff at all"]

    pinned = next((spec.split("==", 1)[1] for spec in group if spec.startswith("ruff==")), None)
    if pinned is None:
        return [
            "pyproject.toml's `dev` group does not pin ruff with `==`. It has to, so that "
            f"`uv run ruff` is the {hooked} that .pre-commit-config.yaml runs."
        ]

    if pinned == hooked:
        return []
    return [
        f"ruff versions disagree: .pre-commit-config.yaml runs {hooked}, pyproject.toml's `dev` "
        f"group installs {pinned}. Change both together."
    ]


def main() -> int:
    """Run every check and report all failures, not just the first."""
    checks = (
        ("contract loaders", check_contract_loaders),
        ("payload keys", check_payload_keys),
        ("Space frontmatter", check_space_frontmatter),
        ("stream events", check_stream_events),
        ("ruff pin", check_ruff_pin),
    )
    failed = 0
    for label, check in checks:
        problems = check()
        if problems:
            failed += 1
            for problem in problems:
                print(f"::error::{problem}")
            print(f"FAIL {label}")
        else:
            print(f"ok   {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
