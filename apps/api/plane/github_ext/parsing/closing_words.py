# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1 — Linear-style closing-word detection. Pure function, no DB access.
# P1 only records the (word, identifier) pair on WorkItemGithubLink.metadata
# (services/link_writer.py) — acting on it (merged PR -> Done transition) is
# P2's job (phase-P1.md step 2 / phase-P2.md).

import re

# Explicit conjugation list per base word rather than programmatic stemming
# (e.g. "resolve" + "ing" is "resolving", not "resolveing") — five base
# words is small enough that an explicit list is both correct and obviously
# auditable, unlike a stemmer that would need special-casing anyway.
_CLOSING_WORDS = (
    "close", "closes", "closed", "closing",
    "fix", "fixes", "fixed", "fixing",
    "resolve", "resolves", "resolved", "resolving",
    "complete", "completes", "completed", "completing",
    "implement", "implements", "implemented", "implementing",
)

# The closing word itself is matched case-insensitively (scoped inline flag
# `(?i:...)` — Python re, 3.6+), but the identifier stays case-sensitive
# (only `[A-Z]+-\d+` is ever a real Plane identifier, matching refs.py).
_CLOSING_PATTERN = re.compile(
    r"(?i:\b(" + "|".join(_CLOSING_WORDS) + r")\b)" r"\s+" r"\b([A-Z]+-\d+)\b"
)


def find_closing_links(text):
    """Find `(closing_word, identifier)` pairs where a Linear-style closing
    word (close/fix/resolve/complete/implement, any tense) immediately
    precedes a Plane identifier — e.g. "fixes PROJ-12", "Resolved ABC-3".

    A closing word with no adjacent identifier is NOT returned — it is not
    on the same line-of-reasoning as a work-item reference and P2 would have
    nothing to act on. Never touches the database; never raises on
    malformed/empty input.
    """
    if not text:
        return []

    return [(word.lower(), identifier) for word, identifier in _CLOSING_PATTERN.findall(text)]
