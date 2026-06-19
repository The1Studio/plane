# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# BGE-M3 dense embedding sidecar client (SP2 P1/P4a).
# Dense-only /embed endpoint; L2-normalize; assert dim==1024 and |norm-1|<1e-3.

import logging
import math
import os
from typing import NamedTuple

import httpx

logger = logging.getLogger("plane.ai_ext")

# Expected embedding dimensions for BGE-M3 dense model.
_EXPECTED_DIM = 1024
_NORM_TOLERANCE = 1e-3

# Embed version constant — bump when model or pooling changes to trigger re-embed.
BGE_EMBED_VERSION = "1"

# Default model ID; overridden by BGE_EMBED_MODEL_ID env var so the sidecar
# compose service and this client always agree without a code change.
_DEFAULT_BGE_MODEL_ID = "BAAI/bge-m3"


class EmbedResult(NamedTuple):
    embedding: list[float]
    model_id: str
    embed_version: str


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vec))


def _normalize(vec: list[float]) -> list[float]:
    norm = _l2_norm(vec)
    if norm == 0:
        return vec
    return [x / norm for x in vec]


class BgeClient:
    """HTTP client for the self-hosted BGE-M3 HuggingFace TEI sidecar.

    Environment variables (must match plane-deploy compose definition):
      BGE_EMBEDDINGS_URL   — base URL of the TEI service (default http://bge-embeddings:80)
      BGE_EMBED_MODEL_ID   — model identifier stored on each embedding row (default BAAI/bge-m3)

    TEI wire format:
      POST {base}/embed   body: {"inputs": ["text1", "text2", …]}
                          response: [[f32, …], …]  (one array per input)
      GET  {base}/health  → 200 when ready

    Assertion contract (hard failures, not silent fallbacks):
      - response array length == len(inputs)
      - each vector dim == 1024
      - |norm - 1| < 1e-3 after client-side L2 normalization (TEI may or may not
        normalize; we normalize ourselves to ensure cosine-safe unit vectors)
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        # BGE_EMBEDDINGS_URL is the env var the compose sidecar contract defines.
        # Default matches the service name in plane-deploy's compose file.
        self._base_url = base_url or os.environ.get(
            "BGE_EMBEDDINGS_URL", "http://bge-embeddings:80"
        )
        # Model ID comes from env so compose and client stay in sync with no code change.
        self._model_id = os.environ.get("BGE_EMBED_MODEL_ID", _DEFAULT_BGE_MODEL_ID)
        self._timeout = timeout
        self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout)

    def embed(self, texts: list[str]) -> list[EmbedResult]:
        """Return EmbedResult for each text, normalized and validated.

        Raises ValueError if dim or norm assertions fail.
        """
        if not texts:
            return []

        response = self._client.post("/embed", json={"inputs": texts})
        response.raise_for_status()
        raw: list[list[float]] = response.json()

        if len(raw) != len(texts):
            raise ValueError(
                f"ai_ext BGE: expected {len(texts)} embeddings, got {len(raw)}"
            )

        results = []
        for idx, vec in enumerate(raw):
            if len(vec) != _EXPECTED_DIM:
                raise ValueError(
                    f"ai_ext BGE: embedding[{idx}] dim={len(vec)}, expected {_EXPECTED_DIM}"
                )
            normalized = _normalize(vec)
            norm = _l2_norm(normalized)
            if abs(norm - 1.0) > _NORM_TOLERANCE:
                raise ValueError(
                    f"ai_ext BGE: post-normalization |norm-1|={abs(norm-1.0):.6f} "
                    f"exceeds tolerance {_NORM_TOLERANCE}"
                )
            results.append(EmbedResult(
                embedding=normalized,
                model_id=self._model_id,
                embed_version=BGE_EMBED_VERSION,
            ))
        return results

    def embed_one(self, text: str) -> EmbedResult:
        """Convenience wrapper for a single text."""
        return self.embed([text])[0]

    def health(self) -> bool:
        """Return True if the sidecar responds to GET /health."""
        try:
            resp = self._client.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
