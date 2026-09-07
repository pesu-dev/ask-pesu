"""Tests for the shared Qdrant collection contract.

conf/collection.yaml is the single authored contract; services/db writes the
collection it describes and services/api reads it. Each service has its own
small loader, so both are loaded here by path -- they share the module name
`app.contract` and would otherwise collide on sys.path.
"""

import ast
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, SparseVectorParams, VectorParams

REPO_ROOT = Path(__file__).resolve().parent.parent

# The collection name is deployment configuration, not contract, so loading one
# requires it. Set before the modules are imported so every load() below works.
TEST_COLLECTION = "ask-pesu-test"
os.environ.setdefault("QDRANT_COLLECTION", TEST_COLLECTION)


def load_module(service):
    spec = importlib.util.spec_from_file_location(
        f"{service}_contract", REPO_ROOT / "services" / service / "app" / "contract.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = load_module("api")
db = load_module("db")


@pytest.fixture(params=[api, db], ids=["api", "db"])
def mod(request):
    """Each service's loader; the checks they share must agree."""
    return request.param


@pytest.fixture
def client():
    return QdrantClient(":memory:")


def make_collection(client, contract, size=None, distance=Distance.COSINE, vector_name=None):
    """Create a collection in the contract's shape, with any field overridden.

    Tests build the geometry they assert on rather than assuming whatever
    conf/collection.yaml currently says, so switching the contract between a
    named and an unnamed vector does not invalidate them.
    """
    name = contract.vector_name if vector_name is None else vector_name
    params = VectorParams(size=size or contract.size, distance=distance)
    client.create_collection(contract.name, vectors_config={name: params} if name else params)
    return client


class TestSingleSourceOfTruth:
    def test_only_one_contract_file_is_tracked(self):
        """The whole point: one authored file, not a vendored copy per service.

        Asks git, not the filesystem -- a local build or deploy rehearsal leaves
        an untracked copy under services/*/conf/, and that is expected.
        """
        tracked = subprocess.run(
            ["git", "ls-files", "*collection.yaml"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert tracked == ["conf/collection.yaml"], tracked

    def test_both_services_load_exactly_the_authored_file(self):
        """Compares every field, not just the path.

        After an image build each service has a vendored copy that the loader
        finds first. Checking the whole contract means a stale copy fails here
        rather than quietly changing which collection a service talks to.
        """
        authored = yaml.safe_load((REPO_ROOT / "conf" / "collection.yaml").read_text())["collection"]
        assert "name" not in authored, "the collection name is environment config, not contract"
        expected = (
            TEST_COLLECTION,
            authored["dense"]["model"],
            int(authored["dense"]["size"]),
            str(authored["dense"]["distance"]),
            authored["dense"].get("vector_name", ""),
            tuple(authored["metadata"]),
            (authored.get("sparse") or {}).get("vector_name", ""),
            str((authored.get("sparse") or {}).get("modifier", "")),
            str((authored.get("sparse") or {}).get("model", "")),
        )
        assert tuple(api.load()) == expected
        assert tuple(db.load()) == expected

    def test_a_stale_vendored_copy_is_rejected_not_silently_preferred(self, tmp_path):
        """The regression this design could have introduced.

        The service-local copy sits below the authored one in the walk, so it
        wins. Identical copies are fine; a differing one must be an error.
        """
        service = tmp_path / "services" / "api"
        (service / "app").mkdir(parents=True)
        (service / "conf").mkdir()
        (tmp_path / "conf").mkdir()
        source = (REPO_ROOT / "services/api/app/contract.py").read_text()
        (service / "app" / "contract.py").write_text(source)
        authored = (REPO_ROOT / "conf" / "collection.yaml").read_text()
        (tmp_path / "conf" / "collection.yaml").write_text(authored)

        spec = importlib.util.spec_from_file_location("stale_probe", service / "app" / "contract.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        (service / "conf" / "collection.yaml").write_text(authored)  # identical: fine
        assert mod.load().name == api.load().name

        (service / "conf" / "collection.yaml").write_text(authored.replace("ask-pesu", "stale"))
        with pytest.raises(mod.ContractViolationError, match="Conflicting contracts"):
            mod.contract_path()

    def test_the_two_loaders_cannot_drift_in_logic(self):
        """Both services carry their own loader, so guard the duplication.

        Compares the AST of every shared function with string constants
        normalised away: error wording and docstrings may differ per role, the
        behaviour may not.
        """
        sources = {name: (REPO_ROOT / f"services/{name}/app/contract.py").read_text() for name in ("api", "db")}

        def normalised(source):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    node.value = ""
            return {fn.name: ast.dump(fn) for fn in tree.body if isinstance(fn, ast.FunctionDef)}

        api_fns, db_fns = normalised(sources["api"]), normalised(sources["db"])
        shared = set(api_fns) & set(db_fns)
        assert shared >= {"contract_path", "load", "validate_collection", "validate_embedding"}
        for name in sorted(shared):
            assert api_fns[name] == db_fns[name], f"{name}() has drifted between the two services"

    def test_the_collection_name_comes_from_the_environment(self, mod):
        """One cluster, one collection per environment, so the name cannot live in
        a file shared by every environment."""
        assert mod.load("explicitly-passed").name == "explicitly-passed"
        assert mod.load().name == TEST_COLLECTION

    def test_a_missing_collection_name_is_fatal(self, mod, monkeypatch):
        """Never default. A default would let a misconfigured deployment quietly
        read or write another environment's data."""
        monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
        with pytest.raises(mod.ContractViolationError, match="QDRANT_COLLECTION is not set"):
            mod.load()

    def test_loader_walks_up_from_the_service(self, mod):
        """Deployed, the file sits at /app/conf/; in the monorepo, at the repo root."""
        path = mod.contract_path()
        assert path.is_file()
        assert path.name == "collection.yaml" and path.parent.name == "conf"


class TestSpaceFrontmatter:
    """Hugging Face Space frontmatter is static YAML in each service README.

    It cannot read conf/collection.yaml, so `models:` and `preload_from_hub:` --
    which bake the embedding model into the Space image -- are an uncontracted
    copy of a contracted value. Changing the model in the contract while leaving
    these behind makes the Space preload the wrong weights.
    """

    @pytest.mark.parametrize("service", ["api", "db"])
    def test_declared_models_match_the_contract(self, service):
        text = (REPO_ROOT / "services" / service / "README.md").read_text()
        assert text.startswith("---\n"), "Space README must open with YAML frontmatter"
        front = yaml.safe_load(text.split("---\n", 2)[1])
        contract = api.load()
        for key in ("models", "preload_from_hub"):
            declared = front.get(key)
            if declared is None:
                continue
            assert contract.model in declared, (
                f"services/{service}/README.md {key}: {declared} does not include the "
                f"contracted model {contract.model!r}"
            )


class TestCollectionGeometry:
    def test_missing_collection_is_a_contract_error_in_both_services(self, mod, client):
        """Not parametrised originally, which is how the db came to raise a bare
        ValueError here while the api raised a contract error."""
        with pytest.raises(mod.ContractViolationError, match="does not exist"):
            mod.validate_collection(mod.load(), client)

    def test_writer_creates_then_reader_accepts(self, client):
        contract = db.load()
        assert db.ensure_collection(contract, client) is True
        assert db.ensure_collection(contract, client) is False
        api.validate_collection(api.load(), client)

    def test_rejects_wrong_vector_size(self, mod, client):
        contract = mod.load()
        make_collection(client, contract, size=384)
        with pytest.raises(mod.ContractViolationError, match="vector size 384"):
            mod.validate_collection(contract, client)

    def test_rejects_wrong_distance(self, mod, client):
        contract = mod.load()
        make_collection(client, contract, distance=Distance.DOT)
        with pytest.raises(mod.ContractViolationError, match="distance"):
            mod.validate_collection(contract, client)

    def test_rejects_named_vector_when_contract_expects_unnamed(self, mod, client):
        """Built explicitly rather than from the shipped contract, so these hold
        whichever way conf/collection.yaml is currently configured."""
        unnamed = mod.load()._replace(vector_name="")
        make_collection(client, unnamed, vector_name="dense")
        with pytest.raises(mod.ContractViolationError, match="named vectors"):
            mod.validate_collection(unnamed, client)

    def test_rejects_unnamed_vector_when_contract_expects_named(self, mod, client):
        named = mod.load()._replace(vector_name="dense")
        make_collection(client, named, vector_name="")
        with pytest.raises(mod.ContractViolationError, match="has no named vector 'dense'"):
            mod.validate_collection(named, client)

    def test_named_contract_round_trips(self, client):
        named = db.load()._replace(vector_name="dense")
        assert db.ensure_collection(named, client) is True
        db.validate_collection(named, client)

    def test_ensure_collection_reraises_a_real_create_failure(self, client):
        """The tolerance for a lost create race must not become a bare swallow."""

        def boom(*_args, **_kwargs):
            raise RuntimeError("qdrant unreachable")

        client.create_collection = boom
        with pytest.raises(RuntimeError, match="qdrant unreachable"):
            db.ensure_collection(db.load(), client)

    def test_ensure_collection_tolerates_a_lost_create_race(self, client):
        real_create = client.create_collection

        def racing_create(*args, **kwargs):
            real_create(*args, **kwargs)
            raise RuntimeError("409 conflict")

        client.create_collection = racing_create
        assert db.ensure_collection(db.load(), client) is False


class TestSparseVector:
    """The sparse vector exists for hybrid retrieval that is not built yet.

    It is contracted now because the `idf` modifier is easy to omit and produces
    no visible symptom -- writes succeed and only the ranking is wrong -- which
    is exactly the class of failure this contract exists to make loud.
    """

    def test_writer_creates_the_sparse_vector_with_its_modifier(self, client):
        contract = db.load()
        assert db.ensure_collection(contract, client) is True
        live = client.get_collection(contract.name).config.params.sparse_vectors or {}
        assert contract.sparse_vector_name in live
        assert str(getattr(live[contract.sparse_vector_name].modifier, "value", "")) == contract.sparse_modifier

    def test_a_missing_sparse_vector_is_caught(self, mod, client):
        contract = mod.load()
        make_collection(client, contract)  # dense only
        with pytest.raises(mod.ContractViolationError, match="no sparse vector"):
            mod.validate_collection(contract, client)

    def test_a_missing_idf_modifier_is_caught(self, mod, client):
        """The bug that shipped: the vector was created, the modifier was not."""
        contract = mod.load()
        client.create_collection(
            contract.name,
            vectors_config={contract.vector_name: VectorParams(size=contract.size, distance=Distance.COSINE)},
            sparse_vectors_config={contract.sparse_vector_name: SparseVectorParams()},
        )
        with pytest.raises(mod.ContractViolationError, match="sparse modifier"):
            mod.validate_collection(contract, client)

    def test_no_sparse_block_means_no_sparse_checks(self, mod, client):
        """Opting out must not fail a dense-only collection."""
        contract = mod.load()._replace(sparse_vector_name="", sparse_modifier="")
        make_collection(client, contract)
        mod.validate_collection(contract, client)


class TestWriterPayload:
    def test_accepts_exact_key_set(self):
        contract = db.load()
        db.validate_payload(contract, dict.fromkeys(contract.metadata))

    def test_rejects_missing_key(self):
        contract = db.load()
        with pytest.raises(db.ContractViolationError, match=f"missing \\['{contract.metadata[-1]}'\\]"):
            db.validate_payload(contract, dict.fromkeys(contract.metadata[:-1]))

    def test_rejects_unexpected_key(self):
        contract = db.load()
        with pytest.raises(db.ContractViolationError, match="unexpected \\['surprise'\\]"):
            db.validate_payload(contract, dict.fromkeys(contract.metadata) | {"surprise": 1})

    def test_db_payload_literal_matches_the_contract(self):
        """services/db builds its payload as a dict literal inside listen_comments.

        validate_payload catches drift, but only at runtime -- and the failure
        mode there is the listener thread dying in production. Parse the literal
        out of the source so a drifting key fails in CI instead.
        """
        source = (REPO_ROOT / "services/db/app/app.py").read_text()
        payloads = [
            {k.value for k in node.keys}
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Dict)
            and node.keys
            and all(isinstance(k, ast.Constant) for k in node.keys)
            and "root_comment_id" in {k.value for k in node.keys}
        ]
        assert len(payloads) == 1, f"expected one payload literal, found {len(payloads)}"
        assert payloads[0] == set(db.load().metadata)


class TestReaderDependencies:
    def test_accepts_contracted_key(self):
        api.require_metadata(api.load(), "url")

    def test_rejects_uncontracted_key(self):
        with pytest.raises(api.ContractViolationError, match="title"):
            api.require_metadata(api.load(), "title")

    def test_api_declared_keys_are_all_contracted(self):
        """Guards the api's real REQUIRED_METADATA, read with ast so importing
        app.rag (and therefore torch) is not required."""
        source = (REPO_ROOT / "services/api/app/rag.py").read_text()
        declared = next(
            ast.literal_eval(node.value)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "REQUIRED_METADATA" for t in node.targets)
        )
        assert declared
        api.require_metadata(api.load(), *declared)


class FakeEmbeddings:
    """Only the public Embeddings surface: the width check must not depend on the
    wrapped SentenceTransformer, which the two libraries name differently."""

    def __init__(self, model_name, width):
        self.model_name = model_name
        self.width = width

    def embed_query(self, text):
        return [0.0] * self.width


class TestEmbeddingModel:
    def test_accepts_matching_model(self, mod):
        contract = mod.load()
        mod.validate_embedding(contract, FakeEmbeddings(contract.model, contract.size))

    def test_rejects_wrong_model_name(self, mod):
        contract = mod.load()
        with pytest.raises(mod.ContractViolationError, match="other/model"):
            mod.validate_embedding(contract, FakeEmbeddings("other/model", contract.size))

    def test_rejects_wrong_width(self, mod):
        contract = mod.load()
        with pytest.raises(mod.ContractViolationError, match="1024-dim"):
            mod.validate_embedding(contract, FakeEmbeddings(contract.model, 1024))
