# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# HMAC-SHA256 verification for inbound GitHub webhook deliveries.
# Mirrors the outbound signing primitive at
# plane/bgtasks/webhook_task.py:316-322 (hmac.new(secret, body, sha256)),
# applied in reverse with a constant-time compare.

import hashlib
import hmac

_SIGNATURE_PREFIX = "sha256="


def verify_signature(secret: str | None, raw_body: bytes, signature_header: str | None) -> bool:
    """Verify a GitHub `X-Hub-Signature-256` header against the raw request
    body bytes.

    Constant-time via `hmac.compare_digest` — NEVER use `==` to compare
    signatures (timing-attack risk). Fails closed (returns False, never
    raises) on a missing secret, missing header, or malformed
    (non-`sha256=`-prefixed) header.
    """
    if not secret or not signature_header:
        return False

    if not signature_header.startswith(_SIGNATURE_PREFIX):
        return False

    expected = _SIGNATURE_PREFIX + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)
