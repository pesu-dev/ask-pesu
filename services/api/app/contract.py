"""Reader side of the shared Qdrant collection contract.

``conf/collection.yaml`` is the one place the collection name, embedding model
and vector geometry are written down. ``services/db`` creates the collection
from it; this service refuses to start unless the live collection matches, so a
writer/reader mismatch is a loud failure rather than silently wrong retrieval.
"""

from pathlib import Path
from typing import NamedTuple

import yaml
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient


class ContractViolationError(RuntimeError):
    """Raised when the live collection or embedding model disagrees with the contract."""


class Contract(NamedTuple):
    """Values read from conf/collection.yaml."""

    name: str
    model: str
    size: int
    distance: str
    vector_name: str
    metadata: tuple[str, ...]


def contract_path() -> Path:
    """Locate conf/collection.yaml by walking up from this module.

    Deployed, the service is its own repository root and the file sits beside it
    at ``/app/conf/``; in the monorepo the same walk reaches the repo root, where
    the single authored copy lives. Deploy and image builds vendor it into the
    service tree, because a `git subtree split` ships only ``services/<name>/``.
    """
    for base in Path(__file__).resolve().parents:
        candidate = base / "conf" / "collection.yaml"
        if candidate.is_file():
            return candidate
    raise ContractViolationError("conf/collection.yaml not found above app/contract.py.")


def load() -> Contract:
    """Read the contract."""
    collection = yaml.safe_load(contract_path().read_text())["collection"]
    dense = collection["dense"]
    return Contract(
        name=collection["name"],
        model=dense["model"],
        size=int(dense["size"]),
        distance=str(dense["distance"]),
        vector_name=dense.get("vector_name", ""),
        metadata=tuple(collection["metadata"]),
    )


def validate_collection(contract: Contract, client: QdrantClient) -> None:
    """Check the live Qdrant collection against the contract, or raise."""
    if not client.collection_exists(contract.name):
        raise ContractViolationError(
            f"Qdrant collection {contract.name!r} does not exist. services/db creates it on startup; "
            f"deploy that service first, or correct the name in conf/collection.yaml."
        )
    vectors = client.get_collection(contract.name).config.params.vectors
    if contract.vector_name:
        if not isinstance(vectors, dict) or contract.vector_name not in vectors:
            found = sorted(vectors) if isinstance(vectors, dict) else ["<unnamed>"]
            raise ContractViolationError(
                f"Collection {contract.name!r} has no named vector {contract.vector_name!r}; it exposes {found}."
            )
        params = vectors[contract.vector_name]
    else:
        if isinstance(vectors, dict):
            raise ContractViolationError(
                f"Collection {contract.name!r} uses named vectors {sorted(vectors)}, "
                f"but the contract expects the unnamed vector."
            )
        params = vectors

    distance = str(getattr(params.distance, "value", params.distance))
    mismatches = []
    if params.size != contract.size:
        mismatches.append(f"vector size {params.size} != contracted {contract.size}")
    if distance != contract.distance:
        mismatches.append(f"distance {distance!r} != contracted {contract.distance!r}")
    if mismatches:
        raise ContractViolationError(
            f"Collection {contract.name!r} violates conf/collection.yaml: {'; '.join(mismatches)}. "
            f"Re-index the collection, or correct the contract."
        )


def validate_embedding(contract: Contract, embedding: Embeddings) -> None:
    """Check the loaded model is the contracted one, at the contracted width."""
    model_name = getattr(embedding, "model_name", None)
    if model_name is not None and model_name != contract.model:
        raise ContractViolationError(f"Embedding model {model_name!r} != contracted {contract.model!r}.")
    # Measured through the public interface: the two services wrap the
    # SentenceTransformer under different attribute names, so reaching for it
    # makes this check silently pass on whichever side does not match.
    width = len(embedding.embed_query("contract dimension probe"))
    if width != contract.size:
        raise ContractViolationError(
            f"Embedding model {contract.model!r} produces {width}-dim vectors, "
            f"but conf/collection.yaml contracts size {contract.size}."
        )


def require_metadata(contract: Contract, *keys: str) -> None:
    """Check payload keys this service reads are ones the contract guarantees."""
    absent = sorted(set(keys) - set(contract.metadata))
    if absent:
        raise ContractViolationError(
            f"This service reads payload keys {absent}, which conf/collection.yaml does not list "
            f"as written to collection {contract.name!r}."
        )
