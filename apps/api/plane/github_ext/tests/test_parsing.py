# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# P1 — pure-function parser tests. No DB, no Django models: `refs.py` and
# `closing_words.py` take raw text in and return plain Python data out.
# Plain `unittest.TestCase` is enough (mirrors the "pure" split test_webhook.py
# calls out — this file intentionally never touches the ORM).

import time
import unittest

from plane.github_ext.parsing.closing_words import find_closing_links
from plane.github_ext.parsing.refs import extract_identifiers


class ExtractIdentifiersTests(unittest.TestCase):
    def test_finds_single_identifier(self):
        self.assertEqual(extract_identifiers("PROJ-1"), ["PROJ-1"])

    def test_finds_identifier_embedded_in_branch_slug(self):
        self.assertEqual(
            extract_identifiers("feature/PROJ-3-add-webhook"), ["PROJ-3"]
        )

    def test_finds_multiple_identifiers(self):
        self.assertEqual(
            extract_identifiers("PROJ-1 relates to ABC-22 and XYZ-7"),
            ["PROJ-1", "ABC-22", "XYZ-7"],
        )

    def test_dedups_and_preserves_first_seen_order(self):
        self.assertEqual(
            extract_identifiers("ABC-2 PROJ-1 ABC-2 PROJ-1 PROJ-1"),
            ["ABC-2", "PROJ-1"],
        )

    def test_ignores_lowercase_identifier(self):
        self.assertEqual(extract_identifiers("proj-1 is not a match"), [])

    def test_empty_and_none_input(self):
        self.assertEqual(extract_identifiers(""), [])
        self.assertEqual(extract_identifiers(None), [])

    def test_long_input_does_not_hang(self):
        # Adversarial-shaped input (long runs of letters with no matching
        # trailing digits) - the regex has no nested quantifiers, so this
        # must stay linear rather than exhibiting catastrophic backtracking
        # (phase-P1.md risk table).
        big_text = ("A" * 200 + " ") * 20000 + "PROJ-99"
        start = time.monotonic()
        result = extract_identifiers(big_text)
        elapsed = time.monotonic() - start

        self.assertEqual(result, ["PROJ-99"])
        self.assertLess(elapsed, 2.0)


class FindClosingLinksTests(unittest.TestCase):
    def test_matches_all_five_words_and_tenses(self):
        cases = [
            ("fixes PROJ-12", [("fixes", "PROJ-12")]),
            ("Resolved ABC-3", [("resolved", "ABC-3")]),
            ("implementing PROJ-9", [("implementing", "PROJ-9")]),
            ("closing X-3", [("closing", "X-3")]),
            ("completes Y-4", [("completes", "Y-4")]),
            ("close X-1", [("close", "X-1")]),
            ("fix PROJ-1", [("fix", "PROJ-1")]),
            ("resolve ABC-1", [("resolve", "ABC-1")]),
            ("complete Y-1", [("complete", "Y-1")]),
            ("implement PROJ-1", [("implement", "PROJ-1")]),
            ("closed PROJ-2", [("closed", "PROJ-2")]),
            ("fixed PROJ-2", [("fixed", "PROJ-2")]),
            ("completed PROJ-2", [("completed", "PROJ-2")]),
            ("implemented PROJ-2", [("implemented", "PROJ-2")]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(find_closing_links(text), expected)

    def test_matches_multiple_pairs_in_one_text(self):
        self.assertEqual(
            find_closing_links("This closing X-3, and also completes Y-4."),
            [("closing", "X-3"), ("completes", "Y-4")],
        )

    def test_ignores_closing_word_with_no_adjacent_identifier(self):
        self.assertEqual(find_closing_links("we should fix this later"), [])
        self.assertEqual(find_closing_links("Resolved nothing today"), [])

    def test_ignores_closing_word_not_immediately_before_identifier(self):
        # "close" is not immediately followed by an identifier - "to" sits
        # in between, so this must NOT count as a closing-word match.
        self.assertEqual(find_closing_links("close to PROJ-1"), [])

    def test_does_not_false_positive_on_substring_of_closing_word(self):
        # "prefix" contains "fix" as a substring but is not the word "fix".
        self.assertEqual(find_closing_links("prefix PROJ-1"), [])

    def test_empty_and_none_input(self):
        self.assertEqual(find_closing_links(""), [])
        self.assertEqual(find_closing_links(None), [])


if __name__ == "__main__":
    unittest.main()
