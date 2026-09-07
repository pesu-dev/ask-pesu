# ---------------------------------------------------------------------------
# GENERATED FILE -- DO NOT EDIT.
#
# Source of truth: conf/contract.py
# Regenerate with: python scripts/sync_contract.py
#
# This copy exists because the service is deployed as a `git subtree split`,
# which ships only services/<name>/. The repo-root contract never reaches the
# running Space, so it is vendored here instead.
# ---------------------------------------------------------------------------
"""Loader and enforcement for the shared Qdrant collection contract.

``services/db`` writes the collection described by ``conf/collection.yaml``;
``services/api`` reads it. Both load this module and check themselves against
the same file at startup, so a writer/reader mismatch surfaces as a loud failure
instead of silently degraded retrieval.

Authored at ``conf/contract.py`` and copied into each service subtree by
``scripts/sync_contract.py``, because a ``git subtree split`` ships only
``services/<name>/`` -- the repo root never reaches the deployed Space. Edit the
copy under ``conf/``; the per-service copies are generated.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

# Resolved relative to this module, not the working directory: both containers
# lay the service out as /app/app/contract.py + /app/conf/collection.yaml, and
# the authored copy at conf/contract.py resolves to its sibling the same way.
CONTRACT_PATH = Path(__file__).resolve().parent.parent / "conf" / "collection.yaml"


class ContractViolationError(RuntimeError):
    """Raised when a live collection, payload, or model disagrees with the contract."""


@dataclass(frozen=True)
class CollectionContract:
    """The writer/reader agreement recorded in ``conf/collection.yaml``."""

    name: str
    model: str
    size: int
    distance: str
    vector_name: str
    metadata: tuple[str, ...]

    @classmethod
    def load(cls, path: Path | str | None = None) -> "CollectionContract":
        """Read the contract from YAML, defaulting to the copy shipped with this service."""
        contract_path = Path(path) if path is not None else CONTRACT_PATH
        with open(contract_path) as file:
            collection = yaml.safe_load(file)["collection"]
        dense = collection["dense"]
        return cls(
            name=collection["name"],
            model=dense["model"],
            size=int(dense["size"]),
            distance=str(dense["distance"]),
            vector_name=dense.get("vector_name", ""),
            metadata=tuple(collection["metadata"]),
        )

    @property
    def vectors_config(self) -> VectorParams | dict[str, VectorParams]:
        """Qdrant ``vectors_config`` for creating the collection from this contract."""
        params = VectorParams(size=self.size, distance=Distance(self.distance))
        return {self.vector_name: params} if self.vector_name else params

    def _live_vector_params(self, client: QdrantClient) -> VectorParams:
        """Return the live collection's params for the contracted vector, or raise."""
        vectors = client.get_collection(self.name).config.params.vectors
        described = f"named vector {self.vector_name!r}" if self.vector_name else "the unnamed vector"
        if self.vector_name:
            if not isinstance(vectors, dict) or self.vector_name not in vectors:
                available = sorted(vectors) if isinstance(vectors, dict) else ["<unnamed>"]
                raise ContractViolationError(
                    f"Collection {self.name!r} has no {described}; it exposes {available}. "
                    f"Fix conf/collection.yaml or re-index the collection."
                )
            return vectors[self.vector_name]
        if isinstance(vectors, dict):
            raise ContractViolationError(
                f"Collection {self.name!r} uses named vectors {sorted(vectors)}, but the contract "
                f"expects {described}. Fix conf/collection.yaml or re-index the collection."
            )
        return vectors

    def validate_collection(self, client: QdrantClient) -> None:
        """Check that the live Qdrant collection matches the contract, or raise."""
        if not client.collection_exists(self.name):
            raise ContractViolationError(
                f"Qdrant collection {self.name!r} does not exist. services/db creates it on startup; "
                f"run that service first, or correct the name in conf/collection.yaml."
            )
        params = self._live_vector_params(client)
        live_distance = str(getattr(params.distance, "value", params.distance))
        mismatches = []
        if params.size != self.size:
            mismatches.append(f"vector size {params.size} != contracted {self.size}")
        if live_distance != self.distance:
            mismatches.append(f"distance {live_distance!r} != contracted {self.distance!r}")
        if mismatches:
            raise ContractViolationError(
                f"Collection {self.name!r} violates conf/collection.yaml: {'; '.join(mismatches)}. "
                f"The collection must be re-indexed, or the contract corrected."
            )

    def ensure_collection(self, client: QdrantClient) -> bool:
        """Create the collection from the contract if absent, else validate it. True if created."""
        if not client.collection_exists(self.name):
            try:
                client.create_collection(collection_name=self.name, vectors_config=self.vectors_config)
            except Exception:
                # Lost a race with another starting writer. Only tolerate that
                # specific outcome: if the collection still is not there, the
                # create failed for a real reason and must not be swallowed --
                # which is what the previous bare try/except did, reporting any
                # failure as "collection already exists".
                if not client.collection_exists(self.name):
                    raise
            else:
                return True
        self.validate_collection(client)
        return False

    def validate_embedding(self, embedding: Embeddings) -> None:
        """Check the loaded embedding model against the contracted name and dimension."""
        model_name = getattr(embedding, "model_name", None)
        if model_name is not None and model_name != self.model:
            raise ContractViolationError(f"Embedding model {model_name!r} != contracted {self.model!r}.")
        # Measured with a probe through the public Embeddings interface rather than
        # read off the wrapped SentenceTransformer: the two services use different
        # HuggingFaceEmbeddings classes, and they keep that object under different
        # attribute names (`client` vs `_client`), so reaching for it makes the
        # check silently no-op on whichever side does not match.
        dimension = len(embedding.embed_query("contract dimension probe"))
        if dimension != self.size:
            raise ContractViolationError(
                f"Embedding model {self.model!r} produces {dimension}-dim vectors, but "
                f"conf/collection.yaml contracts size {self.size}."
            )

    def validate_payload(self, metadata: dict[str, object]) -> None:
        """Check that a payload about to be written carries exactly the contracted keys."""
        written, contracted = set(metadata), set(self.metadata)
        if written == contracted:
            return
        missing = sorted(contracted - written)
        unexpected = sorted(written - contracted)
        raise ContractViolationError(
            f"Payload for collection {self.name!r} violates conf/collection.yaml: "
            f"missing {missing}, unexpected {unexpected}."
        )

    def require_metadata(self, *keys: str) -> None:
        """Check that keys this service reads are ones the contract guarantees are written."""
        absent = sorted(set(keys) - set(self.metadata))
        if absent:
            raise ContractViolationError(
                f"This service reads payload keys {absent}, which conf/collection.yaml does not "
                f"list as written to collection {self.name!r}."
            )
