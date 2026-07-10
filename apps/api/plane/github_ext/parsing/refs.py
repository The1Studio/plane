# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1 — identifier extraction. Pure function, no DB access: given raw text
# (a branch name, a PR title/body, a commit message), find every substring
# shaped like a Plane work-item identifier ("PROJ-123"). Scope resolution
# (does "PROJ" match a real, mapped project? does "123" resolve to a real
# Issue.sequence_id?) is deliberately NOT done here — see
# services/link_writer.py, which is the only place identifiers are trusted
# enough to write a row.

import re

# `[A-Z]+` maps to a Plane project identifier, `\d+` to Issue.sequence_id.
# Deliberately case-sensitive (uppercase only) and deliberately simple/linear
# (no nested quantifiers) so it cannot exhibit catastrophic backtracking on
# adversarial or merely very long input (phase-P1.md risk table).
_IDENTIFIER_RE = re.compile(r"\b[A-Z]+-\d+\b")


def extract_identifiers(text):
    """Return every Plane identifier ("PROJ-123") found in `text`.

    - Case-sensitive: lowercase `proj-1` is never a valid Plane identifier
      and is intentionally ignored — GitHub branch/commit text is otherwise
      free-form prose and lower-casing it would produce false positives.
    - De-duplicated, order-stable (first occurrence wins).
    - Never touches the database; never raises on malformed/empty input.
    """
    if not text:
        return []

    seen = set()
    ordered = []
    for match in _IDENTIFIER_RE.finditer(text):
        identifier = match.group(0)
        if identifier not in seen:
            seen.add(identifier)
            ordered.append(identifier)
    return ordered
