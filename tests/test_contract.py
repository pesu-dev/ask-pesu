"""Tests for the shared Qdrant collection contract.

These exercise the vendored copy under services/api (pytest's `pythonpath`), but
the copies are byte-identical by construction -- `scripts/sync_contract.py`
generates them and CI fails on drift -- so covering one covers both services.
"""

import ast
import dataclasses
from pathlib import Path

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.contract import CollectionContract, ContractViolationError

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def contract():
    """The real contract as shipped, not a fixture-invented one."""
    return CollectionContract.load()


@pytest.fixture
def empty_client():
    return QdrantClient(":memory:")


def collection_with(client, name, vectors_config):
    client.create_collection(name, vectors_config=vectors_config)
    return client


class TestCollectionGeometry:
    def test_reader_refuses_missing_collection(self, contract, empty_client):
        with pytest.raises(ContractViolationError, match="does not exist"):
            contract.validate_collection(empty_client)

    def test_writer_creates_collection_then_reader_accepts_it(self, contract, empty_client):
        assert contract.ensure_collection(empty_client) is True
        contract.validate_collection(empty_client)
        # A second call validates rather than recreating.
        assert contract.ensure_collection(empty_client) is False

    def test_rejects_wrong_vector_size(self, contract, empty_client):
        collection_with(empty_client, contract.name, VectorParams(size=384, distance=Distance.COSINE))
        with pytest.raises(ContractViolationError, match="vector size 384"):
            contract.validate_collection(empty_client)

    def test_rejects_wrong_distance(self, contract, empty_client):
        collection_with(empty_client, contract.name, VectorParams(size=contract.size, distance=Distance.DOT))
        with pytest.raises(ContractViolationError, match="distance"):
            contract.validate_collection(empty_client)

    def test_rejects_named_vector_when_contract_expects_unnamed(self, contract, empty_client):
        """The exact shape a hybrid re-index would leave behind if the contract were not updated."""
        collection_with(
            empty_client,
            contract.name,
            {"dense": VectorParams(size=contract.size, distance=Distance.COSINE)},
        )
        with pytest.raises(ContractViolationError, match="named vectors"):
            contract.validate_collection(empty_client)

    def test_rejects_unnamed_vector_when_contract_expects_named(self, contract, empty_client):
        contract.ensure_collection(empty_client)
        named = dataclasses.replace(contract, vector_name="dense")
        with pytest.raises(ContractViolationError, match="has no named vector 'dense'"):
            named.validate_collection(empty_client)

    def test_named_contract_round_trips(self, contract, empty_client):
        """A named-vector contract creates and then validates its own collection."""
        named = dataclasses.replace(contract, vector_name="dense")
        assert named.ensure_collection(empty_client) is True
        named.validate_collection(empty_client)


class TestPayloadSchema:
    def test_accepts_exact_key_set(self, contract):
        contract.validate_payload(dict.fromkeys(contract.metadata))

    def test_rejects_missing_key(self, contract):
        payload = dict.fromkeys(contract.metadata[:-1])
        with pytest.raises(ContractViolationError, match=f"missing \\['{contract.metadata[-1]}'\\]"):
            contract.validate_payload(payload)

    def test_rejects_unexpected_key(self, contract):
        payload = dict.fromkeys(contract.metadata) | {"surprise": 1}
        with pytest.raises(ContractViolationError, match="unexpected \\['surprise'\\]"):
            contract.validate_payload(payload)


class TestReaderDependencies:
    def test_accepts_contracted_key(self, contract):
        contract.require_metadata("url")

    def test_rejects_uncontracted_key(self, contract):
        with pytest.raises(ContractViolationError, match="title"):
            contract.require_metadata("title")

    def test_api_declared_keys_are_all_contracted(self, contract):
        """Guards the api's real REQUIRED_METADATA.

        Read out of the source with `ast` rather than imported, because importing
        app.rag pulls in torch and the whole LangChain stack.
        """
        source = (REPO_ROOT / "services/api/app/rag.py").read_text()
        declared = next(
            ast.literal_eval(node.value)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "REQUIRED_METADATA" for t in node.targets)
        )
        assert declared, "app.rag.REQUIRED_METADATA not found"
        contract.require_metadata(*declared)


class FakeEncoder:
    def __init__(self, dimension):
        self.dimension = dimension

    def get_sentence_embedding_dimension(self):
        return self.dimension


class FakeEmbeddings:
    """Stands in for HuggingFaceEmbeddings so the tests never download a model."""

    def __init__(self, model_name, dimension):
        self.model_name = model_name
        self.client = FakeEncoder(dimension)


class TestEmbeddingModel:
    def test_accepts_matching_model(self, contract):
        contract.validate_embedding(FakeEmbeddings(contract.model, contract.size))

    def test_rejects_wrong_model_name(self, contract):
        with pytest.raises(ContractViolationError, match="other/model"):
            contract.validate_embedding(FakeEmbeddings("other/model", contract.size))

    def test_rejects_wrong_dimension(self, contract):
        with pytest.raises(ContractViolationError, match="1024-dim"):
            contract.validate_embedding(FakeEmbeddings(contract.model, 1024))
