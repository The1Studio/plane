# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — Markdown → ProseMirror converter (Phase 4a).
#
# Pipeline: raw ClickUp Markdown → HTML (mistune) → sanitise (nh3)
#           → ProseMirror JSON doc + stripped text.
#
# ClickUp-specific blocks that cannot convert cleanly are enumerated
# and counted for the not-migrated report.

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import mistune
    _MISTUNE_OK = True
except ImportError:
    _MISTUNE_OK = False
    logger.warning("mistune not installed — MD→HTML conversion unavailable")

try:
    import nh3
    _NH3_OK = True
except ImportError:
    _NH3_OK = False
    logger.warning("nh3 not installed — HTML sanitisation unavailable")


# ClickUp-specific block patterns that can't be converted faithfully.
_UNCONVERTIBLE_PATTERNS = [
    (re.compile(r"@\w+"), "at-mention"),
    (re.compile(r"/[a-z]+\s"), "slash-command"),
    (re.compile(r"!\[.*?\]\(view:embed://"), "embed-block"),
    (re.compile(r"!\[.*?\]\(https?://.*?\)", re.IGNORECASE), "inline-image"),
    (re.compile(r"\[\[.*?\]\]"), "wiki-link"),
]

# Allowed HTML tags for nh3 sanitisation.
_ALLOWED_TAGS = {
    "p", "br", "strong", "em", "s", "u",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "blockquote",
    "code", "pre", "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "hr",
}

_ALLOWED_ATTRS: dict = {
    "a": {"href", "title"},
    "img": {"src", "alt"},
}


@dataclass
class ConversionResult:
    description_json: dict
    description_html: str
    description_stripped: str
    unconvertible_blocks: dict = field(default_factory=dict)
    # {block_type: count}


def _detect_unconvertible(markdown: str) -> dict[str, int]:
    """Count ClickUp-specific blocks that won't convert cleanly."""
    counts: dict[str, int] = {}
    for pattern, label in _UNCONVERTIBLE_PATTERNS:
        matches = pattern.findall(markdown)
        if matches:
            counts[label] = counts.get(label, 0) + len(matches)
    return counts


def _md_to_html(markdown: str) -> str:
    """Convert Markdown → HTML using mistune."""
    if not _MISTUNE_OK:
        return f"<p>{markdown}</p>"
    md = mistune.create_markdown(
        plugins=["table", "strikethrough", "task_lists"],
    )
    return md(markdown)


def _sanitise_html(html: str) -> str:
    """Strip dangerous tags/attrs using nh3."""
    if not _NH3_OK:
        return html
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
    )


def _html_to_prosemirror(html: str) -> dict:
    """Convert sanitised HTML to a minimal valid ProseMirror document.

    This is a best-effort structural mapping.  Complex nested structures
    (deep list nesting, tables with merged cells) are flattened to paragraphs
    to ensure the output is a valid ProseMirror doc that the Plane editor
    can accept.

    ProseMirror doc schema used by Plane:
      doc → {type: "doc", content: [...nodes]}
      paragraph → {type: "paragraph", content: [...inline]}
      text → {type: "text", text: "..."}
      hard_break → {type: "hardBreak"}
      heading → {type: "heading", attrs: {level: N}, content: [...]}
      bullet_list / ordered_list → list nodes
      list_item → {type: "listItem", content: [...]}
      code_block → {type: "codeBlock", content: [...text]}
      blockquote → {type: "blockquote", content: [...]}
      horizontal_rule → {type: "horizontalRule"}
    """
    try:
        return _html_to_prosemirror_impl(html)
    except Exception as exc:
        logger.warning("HTML→ProseMirror conversion failed: %s", exc)
        # Fallback: wrap the entire text in a single paragraph.
        stripped = re.sub(r"<[^>]+>", " ", html).strip()
        return {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": stripped}]}
            ] if stripped else [{"type": "paragraph"}],
        }


def _html_to_prosemirror_impl(html: str) -> dict:
    """Parse HTML into a ProseMirror document using Python's html.parser."""
    from html.parser import HTMLParser

    nodes: list[dict] = []
    stack: list[dict] = []

    BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6",
                  "ul", "ol", "li", "blockquote", "pre", "table",
                  "thead", "tbody", "tr", "th", "td"}
    HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    INLINE_MARKS = {
        "strong": "bold", "b": "bold",
        "em": "italic", "i": "italic",
        "s": "strike", "del": "strike",
        "u": "underline",
        "code": "code",
    }

    current_marks: list[dict] = []

    class _Parser(HTMLParser):
        def handle_starttag(self, tag: str, attrs):
            nonlocal current_marks
            tag = tag.lower()
            if tag in HEADING_LEVELS:
                node = {"type": "heading", "attrs": {"level": HEADING_LEVELS[tag]}, "content": []}
                stack.append(node)
            elif tag == "p":
                stack.append({"type": "paragraph", "content": []})
            elif tag in ("ul",):
                stack.append({"type": "bulletList", "content": []})
            elif tag in ("ol",):
                stack.append({"type": "orderedList", "content": []})
            elif tag == "li":
                stack.append({"type": "listItem", "content": [{"type": "paragraph", "content": []}]})
            elif tag == "blockquote":
                stack.append({"type": "blockquote", "content": []})
            elif tag == "pre":
                stack.append({"type": "codeBlock", "content": []})
            elif tag == "code" and stack and stack[-1].get("type") == "codeBlock":
                pass  # already in code block
            elif tag in INLINE_MARKS:
                current_marks.append({"type": INLINE_MARKS[tag]})
            elif tag == "br":
                _push_inline({"type": "hardBreak"})
            elif tag == "hr":
                nodes.append({"type": "horizontalRule"})
            elif tag == "a":
                href = dict(attrs).get("href", "")
                current_marks.append({"type": "link", "attrs": {"href": href}})
            elif tag == "img":
                src = dict(attrs).get("src", "")
                alt = dict(attrs).get("alt", "")
                _push_inline({"type": "image", "attrs": {"src": src, "alt": alt}})
            elif tag in ("table", "thead", "tbody", "tr", "th", "td"):
                # Tables: push a paragraph to capture the cell text inline.
                if tag in ("td", "th"):
                    stack.append({"type": "paragraph", "content": []})

        def handle_endtag(self, tag: str):
            nonlocal current_marks
            tag = tag.lower()
            if tag in INLINE_MARKS or tag == "a":
                # pop the most recent matching mark
                mark_type = INLINE_MARKS.get(tag, "link")
                for j in range(len(current_marks) - 1, -1, -1):
                    if current_marks[j]["type"] == mark_type:
                        current_marks.pop(j)
                        break
            elif tag in BLOCK_TAGS or tag in HEADING_LEVELS:
                if stack:
                    node = stack.pop()
                    if stack:
                        _append_to_parent(node)
                    else:
                        nodes.append(node)

        def handle_data(self, data: str):
            text = data
            if not text:
                return
            # If we're inside a code block, text goes directly.
            if stack and stack[-1].get("type") == "codeBlock":
                stack[-1].setdefault("content", []).append({"type": "text", "text": text})
                return
            _push_inline({"type": "text", "text": text, "marks": list(current_marks)} if current_marks
                         else {"type": "text", "text": text})

    def _push_inline(node: dict):
        if stack:
            parent = stack[-1]
            # Navigate to the innermost paragraph of list items.
            if parent.get("type") == "listItem":
                para = parent.get("content", [{}])[0]
                para.setdefault("content", []).append(node)
            else:
                parent.setdefault("content", []).append(node)
        else:
            # Top-level inline — wrap in paragraph.
            nodes.append({"type": "paragraph", "content": [node]})

    def _append_to_parent(node: dict):
        if stack:
            parent = stack[-1]
            if parent.get("type") == "listItem":
                parent.setdefault("content", []).append(node)
            else:
                parent.setdefault("content", []).append(node)

    p = _Parser()
    p.feed(html)

    # Flush any unclosed stack entries.
    while stack:
        node = stack.pop()
        nodes.append(node)

    # Ensure at least one block.
    if not nodes:
        nodes = [{"type": "paragraph"}]

    return {"type": "doc", "content": nodes}


def _strip_html(html: str) -> str:
    """Remove all HTML tags to produce plain text."""
    return re.sub(r"<[^>]+>", "", html).strip()


def convert_markdown(markdown: Optional[str]) -> ConversionResult:
    """Full pipeline: Markdown → ProseMirror doc + HTML + stripped text.

    Retains raw Markdown in ClickupCustomFieldArchive separately (callers
    are responsible for archiving before calling this).
    """
    if not markdown:
        return ConversionResult(
            description_json={"type": "doc", "content": [{"type": "paragraph"}]},
            description_html="<p></p>",
            description_stripped="",
        )

    unconvertible = _detect_unconvertible(markdown)
    html_raw = _md_to_html(markdown)
    html_clean = _sanitise_html(html_raw)
    pm_doc = _html_to_prosemirror(html_clean)
    stripped = _strip_html(html_clean)

    return ConversionResult(
        description_json=pm_doc,
        description_html=html_clean,
        description_stripped=stripped,
        unconvertible_blocks=unconvertible,
    )
