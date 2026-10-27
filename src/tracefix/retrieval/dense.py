"""Optional dense retrieval adapter (task A3.4).

Feature-flagged and **disabled by default**. The configuration boundary is
`DenseConfig` / `build_dense_strategy`: when `enabled` is false the factory
returns `None` and constructs no backend, so no model is downloaded or
initialized. When enabled, a backend must be available; enabling a model
backend without an injected `DenseBackend` raises a typed
`DenseBackendUnavailableError`.

No semantic model is chosen here — model selection is not an approved decision.
To keep dense retrieval runnable and testable without committing to a model, a
deterministic offline backend (`HashingEmbeddingBackend`, feature hashing with a
stable blake2b digest) is provided. It is a **non-semantic** baseline: it only
demonstrates the adapter and ranking plumbing, not retrieval quality. A real
model backend can be supplied at runtime by implementing the `DenseBackend`
protocol; nothing else changes.

The ranking, dedup-by-id, provenance, and failure semantics mirror
`LexicalBM25Strategy` exactly so the two arms are comparable and fusable.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from tracefix.graph.models import Provenance
from tracefix.retrieval.interfaces import (
    EvidenceTarget,
    PartialReason,
    RankedItem,
    RetrievalError,
    RetrievalQuery,
    RetrievalResult,
)
from tracefix.retrieval.lexical import CorpusDocument

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class DenseError(Exception):
    """Base class for dense-retrieval configuration/backend errors."""


class DenseBackendUnavailableError(DenseError):
    """Dense retrieval was enabled but no usable backend is available."""


@runtime_checkable
class DenseBackend(Protocol):
    name: str
    dimension: int

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class DenseConfig(BaseModel):
    """Serializable dense-retrieval configuration (feature-flagged off)."""

    enabled: bool = False
    backend: str = "hashing"
    dimension: int = Field(default=256, ge=1)
    model: str | None = None
    seed: int = 0


class HashingEmbeddingBackend:
    """Deterministic feature-hashing embedder; no model, no network.

    Non-semantic by construction: it exists so the dense adapter can run and be
    tested offline. Tokenization matches the lexical baseline (lowercase,
    `[a-z0-9]+`); each token is hashed (blake2b) to a signed dimension and the
    vector is L2-normalized.
    """

    name = "hashing"

    def __init__(self, dimension: int = 256, seed: int = 0) -> None:
        if dimension < 1:
            raise ValueError("dimension must be >= 1")
        self.dimension = dimension
        self.seed = seed

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.blake2b(f"{self.seed}:{token}".encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dimension
            sign = 1.0 if (value >> 63) & 1 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(component * component for component in vector))
        if norm > 0.0:
            vector = [component / norm for component in vector]
        return vector


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise DenseBackendUnavailableError("embedding dimension mismatch")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_dense_strategy(
    config: DenseConfig,
    documents: Sequence[CorpusDocument],
    *,
    backend: DenseBackend | None = None,
) -> DenseRetrievalStrategy | None:
    """Return a dense strategy when enabled, else `None` (no backend built)."""
    if not config.enabled:
        return None
    resolved = backend
    if resolved is None:
        if config.backend == "hashing":
            resolved = HashingEmbeddingBackend(config.dimension, config.seed)
        elif config.backend == "model":
            raise DenseBackendUnavailableError(
                "dense backend 'model' requires an injected DenseBackend; no model "
                f"{config.model!r} is approved/selected (D4/model selection open)"
            )
        else:
            raise DenseBackendUnavailableError(f"unknown dense backend {config.backend!r}")
    return DenseRetrievalStrategy(list(documents), resolved, config=config)


class DenseRetrievalStrategy:
    """Dense retrieval over an embedded corpus; mirrors lexical semantics."""

    name = "dense"

    def __init__(
        self,
        documents: Sequence[CorpusDocument],
        backend: DenseBackend,
        *,
        config: DenseConfig | None = None,
    ) -> None:
        self.documents = list(documents)
        self.backend = backend
        self.config_model = config or DenseConfig(enabled=True)
        try:
            vectors = backend.encode([doc.text for doc in self.documents])
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed error
            raise DenseBackendUnavailableError(f"backend failed to embed corpus: {exc}") from exc
        if len(vectors) != len(self.documents):
            raise DenseBackendUnavailableError(
                "backend returned an embedding count that does not match the corpus"
            )
        for vector in vectors:
            if len(vector) != backend.dimension:
                raise DenseBackendUnavailableError(
                    f"backend returned dimension {len(vector)}, expected {backend.dimension}"
                )
        self._vectors: list[list[float]] = [list(vector) for vector in vectors]

    @property
    def config(self) -> dict[str, Any]:
        return {
            "strategy": self.name,
            "backend": self.backend.name,
            "dimension": self.backend.dimension,
            "document_count": len(self.documents),
            "model": self.config_model.model,
            "estimated": True,
        }

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        started = time.perf_counter()
        limits = query.limits
        take = min(query.k, limits.max_items)
        if not self.documents:
            return RetrievalResult(
                items=[],
                complete=False,
                partial_reason=PartialReason.INDEX_INCOMPLETE,
                strategy=self.name,
                config=self.config,
                revision=query.revision,
                elapsed_ms=_ms(started),
            )
        try:
            query_vector = self.backend.encode([query.text])[0]
        except Exception as exc:  # noqa: BLE001 - no raw exception crosses the boundary
            raise RetrievalError(f"dense backend failed to embed the query: {exc}") from exc
        ranked = sorted(
            zip(self.documents, self._vectors, strict=True),
            key=lambda pair: (-_cosine(query_vector, pair[1]), pair[0].evidence_id),
        )
        items: list[RankedItem] = []
        for doc, vector in ranked[:take]:
            score = _cosine(query_vector, vector)
            if score <= 0.0:
                continue
            items.append(
                RankedItem(
                    evidence_id=doc.evidence_id,
                    strategy=self.name,
                    rank=len(items) + 1,
                    score=float(score),
                    target=EvidenceTarget(file=doc.file, symbol=doc.symbol, lines=doc.lines),
                    source_revision=query.revision,
                    provenance=Provenance.OBSERVED,
                    source="dense",
                )
            )
        elapsed = _ms(started)
        if elapsed > limits.timeout_ms:
            return RetrievalResult(
                items=items,
                complete=False,
                partial_reason=PartialReason.TIMEOUT,
                strategy=self.name,
                config=self.config,
                revision=query.revision,
                elapsed_ms=elapsed,
            )
        matched = sum(1 for _, vector in ranked if _cosine(query_vector, vector) > 0.0)
        if matched > len(items):
            return RetrievalResult(
                items=items,
                complete=False,
                partial_reason=PartialReason.LIMIT_REACHED,
                strategy=self.name,
                config=self.config,
                revision=query.revision,
                elapsed_ms=elapsed,
            )
        return RetrievalResult(
            items=items,
            complete=True,
            strategy=self.name,
            config=self.config,
            revision=query.revision,
            elapsed_ms=elapsed,
        )


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
