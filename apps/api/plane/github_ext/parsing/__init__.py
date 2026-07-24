# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1 — pure-function text parsing (no DB, no Django imports). Identifier
# extraction (refs.py) and closing-word detection (closing_words.py) are
# intentionally side-effect-free so they can be unit-tested without a
# database and reused from any future entry point (P2/P3).

from plane.github_ext.parsing.closing_words import find_closing_links
from plane.github_ext.parsing.refs import extract_identifiers

__all__ = ["extract_identifiers", "find_closing_links"]
