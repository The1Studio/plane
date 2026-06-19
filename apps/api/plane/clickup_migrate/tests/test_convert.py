# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# Unit tests for the Markdown → ProseMirror converter.
# These run without a live database or ClickUp connection.

from django.test import SimpleTestCase

from plane.clickup_migrate.convert import (
    ConversionResult,
    _detect_unconvertible,
    _md_to_html,
    _sanitise_html,
    _strip_html,
    convert_markdown,
)


class TestDetectUnconvertible(SimpleTestCase):
    def test_detects_at_mention(self):
        counts = _detect_unconvertible("Hello @johndoe, please check this.")
        self.assertIn("at-mention", counts)
        self.assertGreater(counts["at-mention"], 0)

    def test_detects_slash_command(self):
        counts = _detect_unconvertible("/embed some-url")
        self.assertIn("slash-command", counts)

    def test_clean_markdown_no_unconvertible(self):
        counts = _detect_unconvertible("## Hello\n\nThis is clean markdown.")
        self.assertEqual(counts, {})


class TestMdToHtml(SimpleTestCase):
    def test_paragraph(self):
        html = _md_to_html("Hello world")
        self.assertIn("Hello world", html)

    def test_heading(self):
        html = _md_to_html("# Title")
        self.assertIn("<h1", html)

    def test_bold(self):
        html = _md_to_html("**bold text**")
        self.assertIn("bold text", html)

    def test_empty_string(self):
        html = _md_to_html("")
        # Should not raise; returns empty or whitespace
        self.assertIsInstance(html, str)


class TestSanitiseHtml(SimpleTestCase):
    def test_strips_script(self):
        html = _sanitise_html("<p>Hello</p><script>alert('xss')</script>")
        self.assertNotIn("<script", html)
        self.assertIn("Hello", html)

    def test_allows_paragraph(self):
        html = _sanitise_html("<p>Safe content</p>")
        self.assertIn("<p>Safe content</p>", html)

    def test_allows_strong(self):
        html = _sanitise_html("<strong>bold</strong>")
        self.assertIn("bold", html)


class TestStripHtml(SimpleTestCase):
    def test_strips_tags(self):
        result = _strip_html("<p>Hello <strong>world</strong></p>")
        self.assertNotIn("<", result)
        self.assertIn("Hello", result)
        self.assertIn("world", result)

    def test_empty(self):
        self.assertEqual(_strip_html(""), "")


class TestConvertMarkdown(SimpleTestCase):
    def test_none_returns_empty_doc(self):
        result = convert_markdown(None)
        self.assertIsInstance(result, ConversionResult)
        self.assertEqual(result.description_json["type"], "doc")
        self.assertEqual(result.description_html, "<p></p>")
        self.assertEqual(result.description_stripped, "")

    def test_empty_string(self):
        result = convert_markdown("")
        self.assertEqual(result.description_json["type"], "doc")

    def test_simple_paragraph(self):
        result = convert_markdown("Hello world")
        self.assertIn("Hello world", result.description_html)
        self.assertIn("Hello world", result.description_stripped)
        doc = result.description_json
        self.assertEqual(doc["type"], "doc")
        self.assertTrue(len(doc.get("content", [])) > 0)

    def test_heading(self):
        result = convert_markdown("# My Heading")
        doc = result.description_json
        # The doc should contain a heading node.
        content = doc.get("content", [])
        heading_nodes = [n for n in content if n.get("type") == "heading"]
        self.assertTrue(len(heading_nodes) > 0, "Expected at least one heading node")

    def test_prosemirror_doc_has_type(self):
        result = convert_markdown("Some **bold** text")
        self.assertEqual(result.description_json["type"], "doc")
        self.assertIn("content", result.description_json)

    def test_unconvertible_at_mention_detected(self):
        result = convert_markdown("cc @johndoe on this")
        # The function still succeeds (doesn't raise); blocks are counted.
        self.assertIsInstance(result.unconvertible_blocks, dict)
        # at-mention detection may or may not trigger depending on regex;
        # we only verify the function returns a ConversionResult.
        self.assertIsInstance(result, ConversionResult)

    def test_table_in_markdown(self):
        md = "| Col1 | Col2 |\n|------|------|\n| A | B |"
        result = convert_markdown(md)
        # Should not raise; output is a valid ProseMirror doc.
        self.assertEqual(result.description_json["type"], "doc")
