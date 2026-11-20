#!/usr/bin/env python3
"""Stage A1: Deterministic website readiness, ProseMirror AST budget, and notation audit."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SET_2_DIR = ROOT / "output" / "set_2_corrected"
KG_PATH = ROOT / "output" / "graph" / "knowledge_graph.json"
WEB_EXPORT_DIR = ROOT / "output" / "web_export"
AUDIT_JSON_PATH = WEB_EXPORT_DIR / "web_readiness_audit.json"
AUDIT_MD_PATH = WEB_EXPORT_DIR / "WEB_READINESS_AUDIT.md"

# Target web CMS DB/Worker hard limits & 75%/95% safety thresholds
LIMITS = {
    "pg_jsonb_bytes": 500_000,
    "request_bytes": 600_000,
    "visited_nodes": 10_000,
    "max_depth": 24,
}
PASS_THRESHOLDS = {
    "pg_jsonb_bytes": 375_000,   # 75% of 500,000
    "request_bytes": 450_000,    # 75% of 600,000
    "visited_nodes": 7_500,      # 75% of 10,000
    "max_depth": 20,             # Task 6 explicit depth <= 20 PASS threshold
}
WARN_UPPER_THRESHOLDS = {
    "pg_jsonb_bytes": 475_000,   # 95% of 500,000
    "request_bytes": 570_000,    # 95% of 600,000
    "visited_nodes": 9_500,      # 95% of 10,000
    "max_depth": 22,             # <= 22 (~92%, floor(0.95*24))
}

# Supplementary KaTeX/Worker renderer limits observed on the site
RENDERER_ADVISORY_LIMITS = {
    "equations_per_article": 250,
    "equation_chars_per_article": 65_536,
    "single_equation_max_chars": 4_096,
    "plain_paste_max_chars": 100_000,
}


def is_escaped(text: str, idx: int) -> bool:
    """Return True if character at idx is preceded by an odd number of backslashes."""
    slashes = 0
    j = idx - 1
    while j >= 0 and text[j] == "\\":
        slashes += 1
        j -= 1
    return (slashes % 2) == 1


def find_closing_backticks(text: str, start: int, count: int) -> int:
    """Find matching closing backtick run of exact length `count` starting at `start`."""
    i = start
    n = len(text)
    while i < n:
        if text[i] == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            if (j - i) == count:
                return i
            i = j
        else:
            i += 1
    return -1


def parse_inline_formatting(text: str, active_marks: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Parse links, autolinks, bold, italic, and hard breaks in non-math, non-code text."""
    if not text:
        return []
    marks = active_marks or []
    nodes: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    buf: list[str] = []

    def flush_buf() -> None:
        if buf:
            txt = "".join(buf)
            buf.clear()
            if txt:
                node: dict[str, Any] = {"type": "text", "text": txt}
                if marks:
                    node["marks"] = [dict(m) for m in marks]
                nodes.append(node)

    while i < n:
        ch = text[i]
        # Escaped markdown punctuation
        if ch == "\\" and i + 1 < n and text[i + 1] in "\\`*_{}[]()#+-.!|<>":
            buf.append(text[i + 1])
            i += 2
            continue

        # Autolink <https://...>, <http://...>, <mailto:...>
        if ch == "<":
            m_auto = re.match(r"<((?:https?://|mailto:)[^>\s]+)>", text[i:])
            if m_auto:
                flush_buf()
                url = m_auto.group(1)
                link_marks = marks + [{"type": "link", "attrs": {"href": url}}]
                nodes.append({"type": "text", "text": url, "marks": link_marks})
                i += m_auto.end()
                continue
            if text[i:].startswith("<br>") or text[i:].startswith("<br/>") or text[i:].startswith("<br />"):
                flush_buf()
                nodes.append({"type": "hardBreak"})
                i += text[i:].index(">") + 1
                continue

        # Markdown link [label](url)
        if ch == "[":
            m_link = re.match(r"\[([^\[\]\n]+)\]\(([^)\s]+(?:\s+\"[^\"]*\")?)\)", text[i:])
            if m_link:
                flush_buf()
                label = m_link.group(1)
                href = m_link.group(2).split()[0]
                link_marks = marks + [{"type": "link", "attrs": {"href": href}}]
                nodes.extend(parse_inline_formatting(label, link_marks))
                i += m_link.end()
                continue

        # Bold **...** or __...__
        if text.startswith("**", i) or text.startswith("__", i):
            delim = text[i : i + 2]
            end = text.find(delim, i + 2)
            if end != -1 and end > i + 2:
                flush_buf()
                inner = text[i + 2 : end]
                nodes.extend(parse_inline_formatting(inner, marks + [{"type": "bold"}]))
                i = end + 2
                continue

        # Italic *...* or _..._
        if ch in ("*", "_") and i + 1 < n and not text[i + 1].isspace():
            if ch == "_" and i > 0 and text[i - 1].isalnum():
                buf.append(ch)
                i += 1
                continue
            end = i + 1
            found = -1
            while end < n:
                if text[end] == ch and not is_escaped(text, end) and not text[end - 1].isspace():
                    if ch == "*" and end + 1 < n and text[end + 1] == "*":
                        end += 2
                        continue
                    if ch == "_" and end + 1 < n and text[end + 1].isalnum():
                        end += 1
                        continue
                    found = end
                    break
                end += 1
            if found != -1 and found > i + 1:
                flush_buf()
                inner = text[i + 1 : found]
                nodes.extend(parse_inline_formatting(inner, marks + [{"type": "italic"}]))
                i = found + 1
                continue

        buf.append(ch)
        i += 1

    flush_buf()
    return nodes


def coalesce_text_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent text nodes sharing identical marks."""
    merged: list[dict[str, Any]] = []
    for node in nodes:
        if (
            merged
            and node.get("type") == "text"
            and merged[-1].get("type") == "text"
            and merged[-1].get("marks") == node.get("marks")
        ):
            merged[-1]["text"] += node["text"]
        else:
            merged.append(node)
    return merged


def parse_inline(text: str) -> list[dict[str, Any]]:
    """Tokenize inline code, inline math ($...$, \\(...\\)), links, and text marks."""
    if not text:
        return []
    nodes: list[dict[str, Any]] = []
    n = len(text)
    i = 0
    plain_start = 0

    def emit_plain(chunk: str) -> None:
        if chunk:
            nodes.extend(parse_inline_formatting(chunk))

    while i < n:
        # Escaped character
        if text[i] == "\\":
            # Inline math \( ... \)
            if text.startswith("\\(", i) and not is_escaped(text, i):
                end = i + 2
                found = -1
                while (end := text.find("\\)", end)) != -1:
                    if not is_escaped(text, end):
                        found = end
                        break
                    end += 2
                if found != -1:
                    emit_plain(text[plain_start:i])
                    latex = text[i + 2 : found]
                    if latex.strip():
                        nodes.append({"type": "inlineMath", "attrs": {"latex": latex}})
                    else:
                        emit_plain(text[i : found + 2])
                    i = found + 2
                    plain_start = i
                    continue
            i += 2
            continue

        # Code span `...` (including $`...`$)
        if text[i] == "$" and i + 1 < n and text[i + 1] == "`" and not is_escaped(text, i):
            j = i + 2
            while j < n and text[j] == "`":
                j += 1
            tick_len = j - (i + 1)
            end = find_closing_backticks(text, j, tick_len)
            if end != -1 and end + tick_len < n and text[end + tick_len] == "$":
                emit_plain(text[plain_start:i])
                latex = text[j:end]
                nodes.append({"type": "inlineMath", "attrs": {"latex": latex}})
                i = end + tick_len + 1
                plain_start = i
                continue

        if text[i] == "`" and not is_escaped(text, i):
            j = i
            while j < n and text[j] == "`":
                j += 1
            tick_len = j - i
            end = find_closing_backticks(text, j, tick_len)
            if end != -1:
                emit_plain(text[plain_start:i])
                code_txt = text[j:end]
                if tick_len >= 2 and code_txt.startswith(" ") and code_txt.endswith(" ") and code_txt.strip():
                    code_txt = code_txt[1:-1]
                if code_txt:
                    nodes.append({"type": "text", "marks": [{"type": "code"}], "text": code_txt})
                i = end + tick_len
                plain_start = i
                continue
            i = j
            continue

        # Inline math $...$ (single $, not $$)
        if text[i] == "$" and not is_escaped(text, i):
            if i + 1 < n and text[i + 1] == "$":
                i += 2
                continue
            start = i + 1
            if start < n and not text[start].isspace():
                end = start
                found = -1
                while end < n:
                    if text[end] == "$" and not is_escaped(text, end):
                        if end + 1 < n and text[end + 1] == "$":
                            end += 2
                            continue
                        if not text[end - 1].isspace():
                            found = end
                            break
                    end += 1
                if found != -1:
                    latex = text[start:found]
                    if latex.strip():
                        emit_plain(text[plain_start:i])
                        nodes.append({"type": "inlineMath", "attrs": {"latex": latex}})
                        i = found + 1
                        plain_start = i
                        continue
            i += 1
            continue

        i += 1

    emit_plain(text[plain_start:])
    return coalesce_text_nodes(nodes)


def is_table_separator(line: str) -> bool:
    """Return True if line is a GFM pipe table delimiter row like | :--- | :---: |."""
    s = line.strip()
    if "|" not in s:
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return bool(cells) and all(bool(re.match(r"^:?-{3,}:?$", c)) for c in cells)


def split_table_row(line: str) -> list[str]:
    """Split a GFM pipe table row into trimmed cell strings, respecting \\| escapes."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not is_escaped(s, len(s) - 1):
        s = s[:-1]
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if s[i] == "|":
            cells.append("".join(buf).strip())
            buf.clear()
            i += 1
            continue
        buf.append(s[i])
        i += 1
    cells.append("".join(buf).strip())
    return cells


def parse_blocks(lines: list[str]) -> list[dict[str, Any]]:
    """Parse Markdown lines into ProseMirror block nodes."""
    blocks: list[dict[str, Any]] = []
    i = 0
    n = len(lines)

    while i < n:
        ln = lines[i]
        stripped = ln.strip()

        if not stripped:
            i += 1
            continue

        # HTML comments (like <!-- MEDIA: ... --> or <!-- DEMO: ... -->)
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            i += 1
            continue

        # Fenced code block ``` or ~~~
        m_fence = re.match(r"^\s{0,3}(`{3,}|~{3,})([^\n]*)$", ln)
        if m_fence:
            fence_char = m_fence.group(1)[0]
            fence_len = len(m_fence.group(1))
            lang = m_fence.group(2).strip()
            j = i + 1
            code_lines: list[str] = []
            while j < n:
                if re.match(rf"^\s{{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$", lines[j]):
                    j += 1
                    break
                code_lines.append(lines[j])
                j += 1
            body = "\n".join(code_lines)
            if lang == "math":
                if body.strip():
                    blocks.append({"type": "blockMath", "attrs": {"latex": body}})
            else:
                node: dict[str, Any] = {"type": "codeBlock", "attrs": {"language": lang or None}}
                if body:
                    node["content"] = [{"type": "text", "text": body}]
                blocks.append(node)
            i = j
            continue

        # Display math block $$...$$ or \[...\]
        m_dd_open = re.match(r"^\s*(\$\$|\\\[)(.*)$", ln)
        if m_dd_open:
            delim_open = m_dd_open.group(1)
            delim_close = "$$" if delim_open == "$$" else "\\]"
            rest = m_dd_open.group(2)
            # Single-line display math: $$ ... $$
            if delim_close in rest and not rest.strip().startswith(delim_close):
                idx_c = rest.rfind(delim_close)
                if idx_c != -1 and not rest[idx_c + len(delim_close) :].strip():
                    latex = rest[:idx_c].strip()
                    blocks.append({"type": "blockMath", "attrs": {"latex": latex}})
                    i += 1
                    continue
            if rest.strip() and rest.strip().endswith(delim_close) and rest.strip() != delim_close:
                latex = rest.strip()[: -len(delim_close)].strip()
                blocks.append({"type": "blockMath", "attrs": {"latex": latex}})
                i += 1
                continue

            # Multi-line display math
            math_lines = [rest] if rest.strip() else []
            j = i + 1
            while j < n:
                cur = lines[j]
                if delim_close in cur:
                    before, _, _after = cur.partition(delim_close)
                    if before.strip():
                        math_lines.append(before.rstrip())
                    j += 1
                    break
                math_lines.append(cur)
                j += 1
            latex = "\n".join(math_lines).strip("\n")
            blocks.append({"type": "blockMath", "attrs": {"latex": latex}})
            i = j
            continue

        # Horizontal rule
        if re.match(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", ln):
            blocks.append({"type": "horizontalRule"})
            i += 1
            continue

        # Heading
        m_hdr = re.match(r"^\s{0,3}(#{1,6})(?:\s+(.*?))?\s*#*\s*$", ln)
        if m_hdr and (m_hdr.group(2) is not None or ln.strip() == "#" * len(m_hdr.group(1))):
            level = len(m_hdr.group(1))
            hdr_body = (m_hdr.group(2) or "").strip()
            content = parse_inline(hdr_body)
            hnode: dict[str, Any] = {"type": "heading", "attrs": {"level": level}}
            if content:
                hnode["content"] = content
            blocks.append(hnode)
            i += 1
            continue

        # Blockquote
        if re.match(r"^\s{0,3}>", ln):
            bq_lines: list[str] = []
            j = i
            while j < n and (re.match(r"^\s{0,3}>", lines[j]) or (lines[j].strip() and bq_lines and not re.match(r"^\s{0,3}(#{1,6}\s|```|~~~|[-*_]{3,}\s*$)", lines[j]))):
                if re.match(r"^\s{0,3}>", lines[j]):
                    bq_lines.append(re.sub(r"^\s{0,3}>\s?", "", lines[j]))
                else:
                    bq_lines.append(lines[j])
                j += 1
            inner = parse_blocks(bq_lines) or [{"type": "paragraph"}]
            blocks.append({"type": "blockquote", "content": inner})
            i = j
            continue

        # GFM Pipe Table
        if "|" in ln and i + 1 < n and is_table_separator(lines[i + 1]):
            header_cells = split_table_row(ln)
            rows_cells: list[tuple[bool, list[str]]] = [(True, header_cells)]
            j = i + 2
            while j < n and lines[j].strip() and "|" in lines[j] and not re.match(r"^\s{0,3}(#{1,6}\s|```|>)", lines[j]):
                rows_cells.append((False, split_table_row(lines[j])))
                j += 1
            t_rows: list[dict[str, Any]] = []
            for is_hdr, row in rows_cells:
                cell_type = "tableHeader" if is_hdr else "tableCell"
                t_cells = []
                for ctext in row:
                    ic = parse_inline(ctext)
                    pnode: dict[str, Any] = {"type": "paragraph"}
                    if ic:
                        pnode["content"] = ic
                    t_cells.append({"type": cell_type, "content": [pnode]})
                t_rows.append({"type": "tableRow", "content": t_cells})
            blocks.append({"type": "table", "content": t_rows})
            i = j
            continue

        # Lists (bullet or ordered)
        m_list = re.match(r"^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$", ln)
        if m_list:
            base_indent = len(m_list.group(1).replace("\t", "    "))
            is_ordered = m_list.group(3) is not None
            start_num = int(m_list.group(3)) if is_ordered else 1
            list_items: list[dict[str, Any]] = []
            j = i

            while j < n:
                cur = lines[j]
                if not cur.strip():
                    # Look ahead to see if list continues
                    k = j + 1
                    while k < n and not lines[k].strip():
                        k += 1
                    if k < n:
                        nxt = lines[k]
                        m_nxt_item = re.match(r"^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$", nxt)
                        nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                        if m_nxt_item and len(m_nxt_item.group(1).replace("\t", "    ")) == base_indent and (m_nxt_item.group(3) is not None) == is_ordered:
                            j = k
                            continue
                        if nxt_indent > base_indent:
                            j = k
                            continue
                    break

                m_item = re.match(r"^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$", cur)
                if not m_item:
                    break
                item_indent = len(m_item.group(1).replace("\t", "    "))
                item_ordered = m_item.group(3) is not None
                if item_indent != base_indent or item_ordered != is_ordered:
                    break

                # Determine content indent of this list item
                prefix_len = len(m_item.group(0)) - len(m_item.group(4))
                item_lines: list[str] = [m_item.group(4)]
                j += 1
                while j < n:
                    nxt = lines[j]
                    if not nxt.strip():
                        # Peek ahead for indented continuation
                        k = j + 1
                        while k < n and not lines[k].strip():
                            k += 1
                        if k < n:
                            m_nxt = re.match(r"^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$", lines[k])
                            nxt_lead = len(lines[k].replace("\t", "    ")) - len(lines[k].replace("\t", "    ").lstrip(" "))
                            if m_nxt and len(m_nxt.group(1).replace("\t", "    ")) <= base_indent:
                                break
                            if nxt_lead > base_indent:
                                item_lines.append("")
                                j += 1
                                continue
                        break
                    m_nxt = re.match(r"^(\s*)(?:([-*+])|(\d+)[.)])\s+(.*)$", nxt)
                    nxt_exp = nxt.replace("\t", "    ")
                    nxt_lead = len(nxt_exp) - len(nxt_exp.lstrip(" "))
                    if m_nxt and len(m_nxt.group(1).replace("\t", "    ")) <= base_indent:
                        break
                    if nxt_lead > base_indent or not re.match(r"^\s{0,3}(#{1,6}\s|```|~~~|>|[-*_]{3,}\s*$|\$\$)", nxt):
                        dedent = min(nxt_lead, max(prefix_len, base_indent + 2))
                        item_lines.append(nxt_exp[dedent:] if nxt_lead > base_indent else nxt)
                        j += 1
                    else:
                        break

                item_blocks = parse_blocks(item_lines) or [{"type": "paragraph"}]
                list_items.append({"type": "listItem", "content": item_blocks})

            if is_ordered:
                blocks.append({"type": "orderedList", "attrs": {"start": start_num}, "content": list_items})
            else:
                blocks.append({"type": "bulletList", "content": list_items})
            i = max(j, i + 1)
            continue

        # Paragraph: accumulate contiguous plain lines
        para_lines: list[str] = []
        j = i
        while j < n:
            cur = lines[j]
            if not cur.strip():
                break
            if re.match(r"^\s{0,3}(#{1,6}\s|```|~~~|>|[-*_]{3,}\s*$|\$\$|\\\[)", cur):
                break
            if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", cur):
                break
            if "|" in cur and j + 1 < n and is_table_separator(lines[j + 1]):
                break
            para_lines.append(cur.strip())
            j += 1
        if j == i:
            para_lines.append(lines[j].strip())
            j += 1
        para_text = " ".join(para_lines)
        inline_nodes = parse_inline(para_text)
        pnode = {"type": "paragraph"}
        if inline_nodes:
            pnode["content"] = inline_nodes
        blocks.append(pnode)
        i = j

    return blocks


def markdown_to_prosemirror_doc(markdown_text: str) -> dict[str, Any]:
    """Convert Markdown string into a synthetic Tiptap/ProseMirror doc AST."""
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    return {"type": "doc", "content": parse_blocks(lines)}


def measure_prosemirror_ast(doc: dict[str, Any], title: str = "", summary: str = "") -> dict[str, Any]:
    """Measure PostgreSQL JSONB bytes, save request bytes, visited nodes, max depth, and math metrics."""
    visited_nodes = 0
    max_depth = 0
    equation_count = 0
    equation_chars = 0
    max_single_eq_chars = 0
    inline_math_count = 0
    block_math_count = 0

    def walk(node: dict[str, Any], depth: int) -> None:
        nonlocal visited_nodes, max_depth, equation_count, equation_chars, max_single_eq_chars
        nonlocal inline_math_count, block_math_count
        visited_nodes += 1
        if depth > max_depth:
            max_depth = depth
        ntype = node.get("type")
        if ntype in ("inlineMath", "blockMath"):
            latex = (node.get("attrs") or {}).get("latex", "")
            equation_count += 1
            equation_chars += len(latex)
            if len(latex) > max_single_eq_chars:
                max_single_eq_chars = len(latex)
            if ntype == "inlineMath":
                inline_math_count += 1
            else:
                block_math_count += 1
        for child in node.get("content", []) or []:
            walk(child, depth + 1)

    walk(doc, 0)

    # PostgreSQL jsonb::text formats with ", " and ": " spacing
    pg_json_str = json.dumps(doc, ensure_ascii=False, separators=(", ", ": "))
    est_pg_jsonb_bytes = len(pg_json_str.encode("utf-8"))

    capped_summary = summary[:500]
    req_obj = {
        "title": title[:180],
        "summary": capped_summary,
        "document": doc,
        "revision": 0,
    }
    est_request_bytes = len(json.dumps(req_obj, ensure_ascii=False, separators=(", ", ": ")).encode("utf-8"))

    return {
        "est_pg_jsonb_bytes": est_pg_jsonb_bytes,
        "est_request_bytes": est_request_bytes,
        "est_visited_nodes": visited_nodes,
        "est_max_depth": max_depth,
        "est_equation_count": equation_count,
        "est_inline_math_count": inline_math_count,
        "est_block_math_count": block_math_count,
        "est_equation_chars": equation_chars,
        "max_single_equation_chars": max_single_eq_chars,
    }


def classify_budget(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    """Classify article against DB/Worker limits using 75%/95% safety thresholds."""
    reasons_over: list[str] = []
    reasons_warn: list[str] = []

    pg = metrics["est_pg_jsonb_bytes"]
    req = metrics["est_request_bytes"]
    nodes = metrics["est_visited_nodes"]
    depth = metrics["est_max_depth"]

    if pg > WARN_UPPER_THRESHOLDS["pg_jsonb_bytes"]:
        reasons_over.append(f"pg_jsonb_bytes={pg:,} > {WARN_UPPER_THRESHOLDS['pg_jsonb_bytes']:,} (95%)")
    elif pg > PASS_THRESHOLDS["pg_jsonb_bytes"]:
        reasons_warn.append(f"pg_jsonb_bytes={pg:,} > {PASS_THRESHOLDS['pg_jsonb_bytes']:,} (75%)")

    if req > WARN_UPPER_THRESHOLDS["request_bytes"]:
        reasons_over.append(f"request_bytes={req:,} > {WARN_UPPER_THRESHOLDS['request_bytes']:,} (95%)")
    elif req > PASS_THRESHOLDS["request_bytes"]:
        reasons_warn.append(f"request_bytes={req:,} > {PASS_THRESHOLDS['request_bytes']:,} (75%)")

    if nodes > WARN_UPPER_THRESHOLDS["visited_nodes"]:
        reasons_over.append(f"visited_nodes={nodes:,} > {WARN_UPPER_THRESHOLDS['visited_nodes']:,} (95%)")
    elif nodes > PASS_THRESHOLDS["visited_nodes"]:
        reasons_warn.append(f"visited_nodes={nodes:,} > {PASS_THRESHOLDS['visited_nodes']:,} (75%)")

    if depth > WARN_UPPER_THRESHOLDS["max_depth"]:
        reasons_over.append(f"max_depth={depth} > {WARN_UPPER_THRESHOLDS['max_depth']} (95%)")
    elif depth > PASS_THRESHOLDS["max_depth"]:
        reasons_warn.append(f"max_depth={depth} > {PASS_THRESHOLDS['max_depth']} (PASS<=20)")

    if reasons_over:
        return "OVER_LIMIT_SPLIT_REQUIRED", reasons_over + reasons_warn
    if reasons_warn:
        return "WARN_SPLIT_RECOMMENDED", reasons_warn
    return "PASS", []


def split_top_level_h2(markdown_text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split Markdown into (preamble_before_first_h2, [(h2_heading_text, section_md), ...])."""
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    h2_indices: list[tuple[int, str]] = []
    in_fence = False
    for idx, ln in enumerate(lines):
        if re.match(r"^\s{0,3}(`{3,}|~{3,})", ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^##\s+(.+?)\s*#*\s*$", ln)
        if m:
            h2_indices.append((idx, m.group(1).strip()))

    if not h2_indices:
        return markdown_text, []

    preamble = "\n".join(lines[: h2_indices[0][0]]).strip()
    sections: list[tuple[str, str]] = []
    for k, (start_idx, h_title) in enumerate(h2_indices):
        end_idx = h2_indices[k + 1][0] if k + 1 < len(h2_indices) else len(lines)
        sec_text = "\n".join(lines[start_idx:end_idx]).strip()
        sections.append((h_title, sec_text))
    return preamble, sections


def propose_h2_splits(
    markdown_text: str,
    title: str,
    summary: str,
) -> list[dict[str, Any]]:
    """Find minimum balanced partition of top-level ## sections so every part satisfies PASS."""
    preamble, sections = split_top_level_h2(markdown_text)
    if not sections:
        return []

    # Pre-measure each individual section + small overhead buffer
    sec_metrics: list[dict[str, Any]] = []
    for h_title, sec_text in sections:
        doc = markdown_to_prosemirror_doc(sec_text)
        m = measure_prosemirror_ast(doc, title=title, summary=summary)
        sec_metrics.append({"heading": h_title, "text": sec_text, "metrics": m})

    preamble_clean = re.sub(r"^#\s+.+\n*", "", preamble, count=1).strip()
    pre_doc = markdown_to_prosemirror_doc(preamble_clean)
    pre_m = measure_prosemirror_ast(pre_doc, title=title, summary=summary) if preamble_clean else {"est_visited_nodes": 0, "est_pg_jsonb_bytes": 0}

    # Try K = 2, 3, ... parts using balanced node-count partitioning, then verify full AST PASS on each part
    total_nodes = pre_m["est_visited_nodes"] + sum(s["metrics"]["est_visited_nodes"] for s in sec_metrics)
    total_bytes = pre_m["est_pg_jsonb_bytes"] + sum(s["metrics"]["est_pg_jsonb_bytes"] for s in sec_metrics)

    min_k = max(2, (total_nodes // 6_500) + 1, (total_bytes // 320_000) + 1)

    for k in range(min_k, len(sections) + 1):
        # DP / greedy balanced split by section weight (max(nodes/7500, bytes/375000))
        weights = [
            max(s["metrics"]["est_visited_nodes"] / 7_500.0, s["metrics"]["est_pg_jsonb_bytes"] / 375_000.0)
            for s in sec_metrics
        ]
        pre_weight = max(pre_m["est_visited_nodes"] / 7_500.0, pre_m["est_pg_jsonb_bytes"] / 375_000.0)

        # Binary search max per-part weight using greedy bin-packing over contiguous sections
        def pack_with_cap(cap: float) -> list[list[int]] | None:
            groups: list[list[int]] = []
            cur: list[int] = []
            cur_w = pre_weight
            for idx, w in enumerate(weights):
                if (pre_weight if not groups and not cur else 0.0) + w > cap and not cur:
                    return None
                if cur and cur_w + w > cap:
                    groups.append(cur)
                    cur = [idx]
                    cur_w = w
                else:
                    cur.append(idx)
                    cur_w += w
            if cur:
                groups.append(cur)
            return groups if len(groups) <= k else None

        lo, hi = max(weights), sum(weights) + pre_weight
        best_groups: list[list[int]] | None = None
        for _ in range(40):
            mid = (lo + hi) / 2
            g = pack_with_cap(mid)
            if g is not None:
                best_groups = g
                hi = mid
            else:
                lo = mid
        if best_groups is None:
            continue

        # Verify actual AST metrics on every assembled part (with body H1 stripped & nav context buffer)
        parts_info: list[dict[str, Any]] = []
        all_pass = True
        for p_idx, grp in enumerate(best_groups, 1):
            chunks: list[str] = [
                f"> **Reading Context (Part {p_idx} of {len(best_groups)}):** Continuing study module for *{title}*.\n"
            ]
            if p_idx == 1 and preamble_clean:
                chunks.append(preamble_clean)
            for s_idx in grp:
                chunks.append(sec_metrics[s_idx]["text"])
            part_md = "\n\n".join(chunks)
            part_doc = markdown_to_prosemirror_doc(part_md)
            part_title = f"{title} (Part {p_idx}/{len(best_groups)})"[:180]
            pm = measure_prosemirror_ast(part_doc, title=part_title, summary=summary)
            p_status, _ = classify_budget(pm)
            if p_status != "PASS":
                all_pass = False
                break
            parts_info.append({
                "part_index": p_idx,
                "start_heading": f"## {sec_metrics[grp[0]]['heading']}",
                "end_heading": f"## {sec_metrics[grp[-1]]['heading']}",
                "section_count": len(grp),
                "section_headings": [f"## {sec_metrics[idx]['heading']}" for idx in grp],
                **pm,
                "budget_status": p_status,
            })
        if all_pass:
            return parts_info

    return []


def strip_code_spans_and_blocks(text: str) -> str:
    """Mask code blocks and inline code with spaces preserving line numbers."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_fence = False
    fence_char = "`"
    fence_len = 3
    for ln in lines:
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", ln)
        if not in_fence and m:
            in_fence = True
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            out.append("\n" if ln.endswith("\n") else "")
            continue
        if in_fence:
            if re.match(rf"^\s{{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$", ln.rstrip("\r\n")):
                in_fence = False
            out.append("\n" if ln.endswith("\n") else "")
            continue
        # Mask inline `...` preserving length
        masked = re.sub(r"`[^`\n]+`", lambda m: " " * len(m.group(0)), ln)
        out.append(masked)
    return "".join(out)


def mask_math_preserving_lines(text: str) -> str:
    """Replace $$...$$ and $...$ math contents with spaces while keeping line offsets intact."""
    chars = list(text)
    n = len(chars)
    i = 0
    while i < n:
        if chars[i] == "\\" and i + 1 < n:
            if text.startswith("\\(", i) and not is_escaped(text, i):
                end = text.find("\\)", i + 2)
                if end != -1:
                    for k in range(i, end + 2):
                        if chars[k] != "\n":
                            chars[k] = " "
                    i = end + 2
                    continue
            if text.startswith("\\[", i) and not is_escaped(text, i):
                end = text.find("\\]", i + 2)
                if end != -1:
                    for k in range(i, end + 2):
                        if chars[k] != "\n":
                            chars[k] = " "
                    i = end + 2
                    continue
            i += 2
            continue
        if text.startswith("$$", i) and not is_escaped(text, i):
            end = i + 2
            while (end := text.find("$$", end)) != -1:
                if not is_escaped(text, end):
                    break
                end += 2
            if end != -1:
                for k in range(i, end + 2):
                    if chars[k] != "\n":
                        chars[k] = " "
                i = end + 2
                continue
        if chars[i] == "$" and not is_escaped(text, i):
            end = i + 1
            found = -1
            while end < n and chars[end] != "\n":
                if chars[end] == "$" and not is_escaped(text, end):
                    found = end
                    break
                end += 1
            if found != -1:
                for k in range(i, found + 1):
                    if chars[k] != "\n":
                        chars[k] = " "
                i = found + 1
                continue
        i += 1
    return "".join(chars)


def scan_unsupported_features(raw_text: str) -> dict[str, Any]:
    """Inventory unsupported website features with exact counts and line references."""
    no_code = strip_code_spans_and_blocks(raw_text)
    no_code_no_math = mask_math_preserving_lines(no_code)
    raw_lines = raw_text.splitlines()
    clean_lines = no_code_no_math.splitlines()
    no_code_lines = no_code.splitlines()

    # 1. Cross-equation LaTeX references: \label, \ref, \eqref
    latex_refs: list[dict[str, Any]] = []
    for lno, ln in enumerate(no_code_lines, 1):
        for m in re.finditer(r"\\(label|eqref|ref)\{([^}]+)\}", ln):
            latex_refs.append({"line": lno, "cmd": f"\\{m.group(1)}", "key": m.group(2)})

    # 2. GFM pipe tables
    tables: list[dict[str, Any]] = []
    i = 0
    while i < len(raw_lines):
        if "|" in raw_lines[i] and i + 1 < len(raw_lines) and is_table_separator(raw_lines[i + 1]):
            cols = len(split_table_row(raw_lines[i]))
            j = i + 2
            data_rows = 0
            has_math = "$" in raw_lines[i]
            while j < len(raw_lines) and raw_lines[j].strip() and "|" in raw_lines[j] and not re.match(r"^\s{0,3}(#{1,6}\s|```|>)", raw_lines[j]):
                if "$" in raw_lines[j]:
                    has_math = True
                data_rows += 1
                j += 1
            tables.append({
                "start_line": i + 1,
                "end_line": j,
                "total_rows": data_rows + 1,  # header + data rows
                "data_rows": data_rows,
                "cols": cols,
                "contains_math": has_math,
            })
            i = j
        else:
            i += 1

    # 3. Markdown footnotes [^...]
    footnotes: list[dict[str, Any]] = []
    for lno, ln in enumerate(clean_lines, 1):
        for m in re.finditer(r"\[\^([^\]]+)\]", ln):
            is_def = ln[m.end() :].startswith(":")
            footnotes.append({"line": lno, "id": m.group(1), "kind": "definition" if is_def else "reference"})

    # 4. Heading depth violations (leading h1 vs body h1, and h5/h6)
    leading_h1: list[dict[str, Any]] = []
    body_h1: list[dict[str, Any]] = []
    deep_headings: list[dict[str, Any]] = []
    seen_first_h1 = False
    for lno, ln in enumerate(clean_lines, 1):
        m = re.match(r"^(#{1,6})\s+(.+)$", ln)
        if not m:
            continue
        lvl = len(m.group(1))
        text_hdr = raw_lines[lno - 1].lstrip("#").strip()
        if lvl == 1:
            if not seen_first_h1 and lno <= 5:
                seen_first_h1 = True
                leading_h1.append({"line": lno, "level": 1, "text": text_hdr})
            else:
                body_h1.append({"line": lno, "level": 1, "text": text_hdr})
        elif lvl >= 5:
            deep_headings.append({"line": lno, "level": lvl, "text": text_hdr})

    # 5. Links & invalid link schemes (must start with http://, https://, or mailto:)
    invalid_links: list[dict[str, Any]] = []
    valid_links_count = 0
    for lno, ln in enumerate(clean_lines, 1):
        for m in re.finditer(r"(?<!!)\[([^\[\]\n]*)\]\(([^)\s]+)", ln):
            href = m.group(2)
            if re.match(r"^(?:https?://|mailto:)", href, re.IGNORECASE):
                valid_links_count += 1
            else:
                invalid_links.append({"line": lno, "text": m.group(1), "href": href})
        for m in re.finditer(r"<([^>\s]+)>", ln):
            inner = m.group(1)
            if re.match(r"^(?:https?://|mailto:)", inner, re.IGNORECASE):
                valid_links_count += 1
            elif "/" in inner or inner.startswith("#") or ":" in inner:
                invalid_links.append({"line": lno, "text": inner, "href": inner})

    return {
        "latex_cross_refs": latex_refs,
        "tables": tables,
        "footnotes": footnotes,
        "leading_h1": leading_h1,
        "body_h1_violations": body_h1,
        "deep_heading_violations": deep_headings,
        "invalid_links": invalid_links,
        "valid_links_count": valid_links_count,
    }


def extract_math_expressions(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """Collect (node_type, latex_string) from parsed AST."""
    exprs: list[tuple[str, str]] = []

    def walk(node: dict[str, Any]) -> None:
        nt = node.get("type")
        if nt in ("inlineMath", "blockMath"):
            exprs.append((nt, (node.get("attrs") or {}).get("latex", "")))
        for ch in node.get("content", []) or []:
            walk(ch)

    walk(doc)
    return exprs


def analyze_latex_constructs(exprs: list[tuple[str, str]]) -> dict[str, Any]:
    """Inventory environments, nontrivial commands, nested structures, and KaTeX flags."""
    env_counts: Counter[str] = Counter()
    cmd_counts: Counter[str] = Counter()
    multiline_rows = 0
    nested_envs = 0
    custom_macros: Counter[str] = Counter()
    tag_count = 0
    oversized_eqs = 0

    for _nt, latex in exprs:
        if len(latex) > 4096:
            oversized_eqs += 1
        envs = re.findall(r"\\begin\{([^}]+)\}", latex)
        for ev in envs:
            env_counts[ev] += 1
        if len(envs) >= 2:
            nested_envs += 1
        if "\\\\" in latex:
            multiline_rows += 1
        if "\\tag{" in latex:
            tag_count += 1
        for m in re.finditer(r"\\(newcommand|renewcommand|def|DeclareMathOperator)\b", latex):
            custom_macros[m.group(1)] += 1
        for m in re.finditer(r"\\([a-zA-Z]+\*?)", latex):
            cmd_counts[m.group(1)] += 1

    return {
        "env_counts": dict(env_counts),
        "cmd_counts": dict(cmd_counts),
        "multiline_row_equations": multiline_rows,
        "nested_env_equations": nested_envs,
        "tag_count": tag_count,
        "custom_macro_defs": dict(custom_macros),
        "oversized_equations_gt_4096": oversized_eqs,
    }


def analyze_notation_drift(raw_text: str, exprs: list[tuple[str, str]], topic_id: str = "") -> dict[str, Any]:
    """Scan math expressions and callout lines for notation inconsistencies."""
    all_math = "\n".join(latex for _nt, latex in exprs)

    def count_pat(pat: str, target: str = all_math) -> int:
        return len(re.findall(pat, target))

    # Vectors
    vec_mathbf_lower = count_pat(r"\\mathbf\{[a-z]\}")
    vec_boldsymbol_lower = count_pat(r"\\boldsymbol\{(?:[a-z]|\\[a-z]+)\}")
    vec_arrow = count_pat(r"\\vec\{")
    vec_bm = count_pat(r"\\bm\{")

    # Transpose
    t_plain = count_pat(r"\^T(?![a-zA-Z])")
    t_braced = count_pat(r"\^\{T\}")
    t_top = count_pat(r"\^\\top(?![a-zA-Z])|\^\{\\top\}")
    t_mathsf = count_pat(r"\^\{\\mathsf\{T\}\}|\^\\mathsf\{T\}")
    t_prime = count_pat(r"\\mathbf\{[A-Za-z]\}'|\\boldsymbol\{[^}]+\}'")

    # Probability, Expectation, Variance, Covariance (only count plain E/P in prob/stats/ML topics, excluding T08 DFT E[k])
    prob_stats_topic = True
    e_mathbb = count_pat(r"\\mathbb\{E\}")
    e_mathbb_paren = count_pat(r"\\mathbb\{E\}\s*(?:\\bigl|\\Bigl|\\left)?\(")
    e_plain_bracket = count_pat(r"(?<![A-Za-z\\])E\[") if prob_stats_topic else 0
    e_plain_paren = count_pat(r"(?<![A-Za-z\\])E\((?![A-Za-z\\]*\\mathbf\{y\})") if prob_stats_topic else 0
    p_mathbb = count_pat(r"\\mathbb\{P\}")
    p_pr = count_pat(r"\\Pr\b")
    # Exclude P(n, k) combinatorics and P(x) predicates in combinatorics/algebra
    p_plain_paren = count_pat(r"(?<![A-Za-z\\])P\((?!n,\s*k)") if prob_stats_topic else 0
    var_op = count_pat(r"\\operatorname\{Var\}")
    var_rm = count_pat(r"\\mathrm\{Var\}")
    var_text = count_pat(r"\\text\{Var\}")
    cov_op = count_pat(r"\\operatorname\{Cov\}")
    cov_rm = count_pat(r"\\mathrm\{Cov\}")
    cov_text = count_pat(r"\\text\{Cov\}")

    # Norms, Inner products, Indicators, Absolute values
    norm_l_r_vert = count_pat(r"\\lVert")
    norm_escaped_bar = count_pat(r"\\\|")
    # True double-pipe norm (not |x||y| or \bigl||x| - |y|\bigr|)
    norm_double_pipe = count_pat(r"(?<![|\\a-zA-Z])\|\|[^|\n]+\|\|")
    abs_lvert = count_pat(r"\\lvert")
    inner_langle = count_pat(r"\\langle\s*[^,]+,\s*[^>]+\s*\\rangle")
    ind_mathbf1 = count_pat(r"\\mathbf\{1\}")
    ind_mathbb1 = count_pat(r"\\mathbb\{1\}")
    ind_mathbbm1 = count_pat(r"\\mathbbm\{1\}")

    # Differentials, argmin/argmax, span/trace, sets
    dx_mathrm = count_pat(r"\\mathrm\{d\}[a-zA-Z]")
    dx_plain = count_pat(r"(?:\\,|\\;|\\quad|\s)d[xyztuwvs](?![a-zA-Z])")
    argmin_opstar = count_pat(r"\\operatorname\*\{arg\s*min\}|\\operatorname\*\{argmin\}|\\operatorname\*\{arg\s*max\}|\\operatorname\*\{argmax\}")
    argmin_cmd = count_pat(r"\\arg\\min|\\arg\\max")
    span_op = count_pat(r"\\operatorname\{span\}")
    span_text = count_pat(r"\\(?:text|mathrm)\{span\}")
    tr_op = count_pat(r"\\operatorname\{tr\}")
    tr_text = count_pat(r"\\(?:text|mathrm)\{tr\}")
    set_r = count_pat(r"\\mathbb\{R\}")

    # Callout formatting styles in raw Markdown
    no_code = strip_code_spans_and_blocks(raw_text)
    callout_blockquote = len(re.findall(r"^>\s*\*\*(?:Theorem|Definition|Proposition|Lemma|Corollary|Axiom|Remark|Example)", no_code, re.M))
    callout_bold_lead = len(re.findall(r"^\*\*(?:Theorem|Definition|Proposition|Lemma|Corollary|Axiom|Remark|Example)", no_code, re.M))
    callout_heading = len(re.findall(r"^#{2,6}\s+(?:Theorem|Definition|Proposition|Lemma|Corollary|Axiom|Remark|Example)", no_code, re.M))
    proof_italic = len(re.findall(r"^\*Proof(?:\s|\.)", no_code, re.M))
    proof_bold = len(re.findall(r"^(?:>\s*)?\*\*Proof", no_code, re.M))
    proof_heading = len(re.findall(r"^#{2,6}\s+Proof\b", no_code, re.M))
    qed_square = count_pat(r"\\square")
    qed_blacksquare = count_pat(r"\\blacksquare")

    return {
        "vectors": {
            "mathbf_lower": vec_mathbf_lower,
            "boldsymbol": vec_boldsymbol_lower,
            "vec_arrow": vec_arrow,
            "bm": vec_bm,
        },
        "transpose": {
            "caret_T": t_plain,
            "caret_braced_T": t_braced,
            "caret_top": t_top,
            "caret_mathsf_T": t_mathsf,
            "bold_prime": t_prime,
        },
        "probability_operators": {
            "E_mathbb": e_mathbb,
            "E_mathbb_paren": e_mathbb_paren,
            "E_plain_bracket": e_plain_bracket,
            "E_plain_paren": e_plain_paren,
            "P_mathbb": p_mathbb,
            "P_Pr": p_pr,
            "P_plain_paren": p_plain_paren,
            "Var_operatorname": var_op,
            "Var_mathrm": var_rm,
            "Var_text": var_text,
            "Cov_operatorname": cov_op,
            "Cov_mathrm": cov_rm,
            "Cov_text": cov_text,
        },
        "norms_and_indicators": {
            "norm_lVert_rVert": norm_l_r_vert,
            "norm_backslash_bar": norm_escaped_bar,
            "norm_double_pipe": norm_double_pipe,
            "abs_lvert": abs_lvert,
            "inner_langle_rangle": inner_langle,
            "indicator_mathbf1": ind_mathbf1,
            "indicator_mathbb1": ind_mathbb1,
            "indicator_mathbbm1": ind_mathbbm1,
        },
        "operators_and_differentials": {
            "dx_mathrm_d": dx_mathrm,
            "dx_italic_d": dx_plain,
            "argmin_max_opstar": argmin_opstar,
            "argmin_max_arg_min": argmin_cmd,
            "span_operatorname": span_op,
            "span_text_rm": span_text,
            "tr_operatorname": tr_op,
            "tr_text_rm": tr_text,
            "set_mathbb_R": set_r,
        },
        "callouts": {
            "blockquote_bold": callout_blockquote,
            "paragraph_bold_lead": callout_bold_lead,
            "heading_callout": callout_heading,
            "proof_italic": proof_italic,
            "proof_bold": proof_bold,
            "proof_heading": proof_heading,
            "qed_square": qed_square,
            "qed_blacksquare": qed_blacksquare,
        },
    }


def extract_title_from_md(raw_text: str, fallback: str) -> str:
    for ln in raw_text.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", ln)
        if m:
            return m.group(1).strip()
    return fallback


def audit_corpus() -> dict[str, Any]:
    """Run Stage A1 audit across all Set 2 articles."""
    kg = json.loads(KG_PATH.read_text(encoding="utf-8"))
    topic_by_fn = {t["filename"]: t for t in kg["topics"]}

    article_records: list[dict[str, Any]] = []
    corpus_envs: Counter[str] = Counter()
    corpus_cmds: Counter[str] = Counter()
    cmd_files: defaultdict[str, set[str]] = defaultdict(set)
    env_files: defaultdict[str, set[str]] = defaultdict(set)

    for md_path in sorted(SET_2_DIR.glob("*.md")):
        fn = md_path.name
        tmeta = topic_by_fn[fn]
        tid = tmeta["id"]
        raw_text = md_path.read_text(encoding="utf-8")
        title = extract_title_from_md(raw_text, tmeta["title"])
        summary = tmeta["summary"]

        doc = markdown_to_prosemirror_doc(raw_text)
        metrics = measure_prosemirror_ast(doc, title=title, summary=summary)
        status, reasons = classify_budget(metrics)

        proposed_splits: list[dict[str, Any]] = []
        if status != "PASS":
            proposed_splits = propose_h2_splits(raw_text, title=title, summary=summary)

        unsupported = scan_unsupported_features(raw_text)
        exprs = extract_math_expressions(doc)
        latex_info = analyze_latex_constructs(exprs)
        drift = analyze_notation_drift(raw_text, exprs, topic_id=tid)

        for env, cnt in latex_info["env_counts"].items():
            corpus_envs[env] += cnt
            env_files[env].add(tid)
        for cmd, cnt in latex_info["cmd_counts"].items():
            corpus_cmds[cmd] += cnt
            cmd_files[cmd].add(tid)

        article_records.append({
            "topic_id": tid,
            "filename": fn,
            "title": title,
            "discipline": tmeta["discipline"],
            "raw_chars": len(raw_text),
            "word_count": len(raw_text.split()),
            "metrics": metrics,
            "budget_status": status,
            "budget_reasons": reasons,
            "proposed_splits": proposed_splits,
            "unsupported_features": unsupported,
            "latex_inventory": latex_info,
            "notation_drift": drift,
        })

    # Aggregate summaries
    status_counts = Counter(r["budget_status"] for r in article_records)
    nontrivial_cmd_names = sorted({
        cmd for cmd in corpus_cmds
        if cmd in {
            "operatorname", "operatorname*", "mathbbm", "bm", "xrightarrow", "xleftarrow",
            "substack", "tag", "boldsymbol", "mathbf", "mathbb", "mathcal", "mathscr",
            "mathfrak", "mathsf", "mathrm", "text", "textbf", "textit", "lVert", "rVert",
            "lvert", "rvert", "langle", "rangle", "top", "vec", "underset", "overset",
            "stackrel", "binom", "dfrac", "tfrac", "boxed", "cancel", "phantom",
            "implies", "impliedby", "iff", "pmod", "bmod", "coloneqq", "triangleq",
            "succeq", "preceq", "succ", "prec", "otimes", "oplus", "bigoplus",
            "bigsqcup", "bigcup", "bigcap", "prod", "coprod", "iint", "iiint", "oint",
            "varlimsup", "varliminf", "limsup", "liminf", "sup", "inf", "argmax", "argmin",
            "Pr", "square", "blacksquare", "mathcal", "overline", "underline", "widehat",
            "widetilde", "bar", "hat", "tilde", "dot", "ddot", "checkmark",
        } or corpus_cmds[cmd] <= 25
    })

    return {
        "schema_version": "1.0",
        "limits": LIMITS,
        "pass_thresholds": PASS_THRESHOLDS,
        "warn_upper_thresholds": WARN_UPPER_THRESHOLDS,
        "renderer_advisory_limits": RENDERER_ADVISORY_LIMITS,
        "summary": {
            "total_articles": len(article_records),
            "status_counts": dict(status_counts),
            "total_proposed_web_parts": sum(len(r["proposed_splits"]) if r["proposed_splits"] else 1 for r in article_records),
            "total_tables": sum(len(r["unsupported_features"]["tables"]) for r in article_records),
            "total_latex_cross_refs": sum(len(r["unsupported_features"]["latex_cross_refs"]) for r in article_records),
            "total_footnotes": sum(len(r["unsupported_features"]["footnotes"]) for r in article_records),
            "total_body_h1": sum(len(r["unsupported_features"]["body_h1_violations"]) for r in article_records),
            "total_h5_h6": sum(len(r["unsupported_features"]["deep_heading_violations"]) for r in article_records),
            "total_invalid_links": sum(len(r["unsupported_features"]["invalid_links"]) for r in article_records),
            "total_equations": sum(r["metrics"]["est_equation_count"] for r in article_records),
            "articles_over_250_equations": sum(1 for r in article_records if r["metrics"]["est_equation_count"] > 250),
            "articles_over_65536_math_chars": sum(1 for r in article_records if r["metrics"]["est_equation_chars"] > 65_536),
            "articles_over_100k_raw_chars": sum(1 for r in article_records if r["raw_chars"] > 100_000),
        },
        "corpus_latex_environments": {
            env: {"count": cnt, "topic_count": len(env_files[env]), "topics": sorted(env_files[env])}
            for env, cnt in corpus_envs.most_common()
        },
        "corpus_latex_commands": {
            cmd: {"count": corpus_cmds[cmd], "topic_count": len(cmd_files[cmd]), "topics": sorted(cmd_files[cmd])}
            for cmd in sorted(corpus_cmds.keys(), key=lambda c: (-corpus_cmds[c], c))
        },
        "highlighted_nontrivial_commands": {
            cmd: {"count": corpus_cmds[cmd], "topic_count": len(cmd_files[cmd]), "topics": sorted(cmd_files[cmd])}
            for cmd in sorted(nontrivial_cmd_names, key=lambda c: (-corpus_cmds[c], c))
        },
        "articles": article_records,
    }


def render_audit_markdown(report: dict[str, Any]) -> str:
    """Format Stage A1 audit findings as a comprehensive Markdown report."""
    s = report["summary"]
    articles = report["articles"]

    lines: list[str] = [
        "# Stage A1: Website Readiness, ProseMirror Budget & Notation Drift Audit",
        "",
        "Generated strictly from `output/set_2_corrected/` and `output/graph/knowledge_graph.json`.",
        "",
        "## 1. Executive Summary",
        "",
        f"- **Articles Audited:** {s['total_articles']} (`T01`–`T{s['total_articles']:02d}`)",
        f"- **ProseMirror Budget Breakdown (75%/95% thresholds against 500,000 B stored, 600,000 B request, 10,000 nodes, depth 24):**",
        f"  - `PASS`: **{s['status_counts'].get('PASS', 0)}**",
        f"  - `WARN_SPLIT_RECOMMENDED`: **{s['status_counts'].get('WARN_SPLIT_RECOMMENDED', 0)}**",
        f"  - `OVER_LIMIT_SPLIT_REQUIRED`: **{s['status_counts'].get('OVER_LIMIT_SPLIT_REQUIRED', 0)}**",
        f"- **Total Staging Web Parts After Proposed `##` Splits:** **{s['total_proposed_web_parts']}**",
        f"- **Unsupported Feature Totals:**",
        f"  - Cross-equation LaTeX refs (`\\label`/`\\ref`/`\\eqref`): **{s['total_latex_cross_refs']}**",
        f"  - GFM Pipe Tables: **{s['total_tables']}**",
        f"  - Markdown Footnotes (`[^...]`): **{s['total_footnotes']}**",
        f"  - Body `h1` violations (excluding leading page title `h1`): **{s['total_body_h1']}**",
        f"  - Deep heading (`h5`/`h6`) violations: **{s['total_h5_h6']}**",
        f"  - Invalid link schemes (non-`http/https/mailto`): **{s['total_invalid_links']}**",
        f"- **Supplementary Target Renderer Advisory Telemetry:**",
        f"  - Total corpus equations (`inlineMath + blockMath`): **{s['total_equations']:,}**",
        f"  - Articles > 250 equations/article: **{s['articles_over_250_equations']}** / {s['total_articles']} (advisory threshold telemetry)",
        f"  - Articles > 65,536 total equation source chars: **{s['articles_over_65536_math_chars']}** / {s['total_articles']}",
        f"  - Articles > 100,000 raw Markdown chars (`clipboardTextParser` paste limit): **{s['articles_over_100k_raw_chars']}** / {s['total_articles']}",
        "",
        "## 2. Synthetic Tiptap/ProseMirror Budget Estimates (All Corpus Articles)",
        "",
        "| ID | Words | Raw Chars | Est PG JSONB Bytes | Est Request Bytes | Visited Nodes | Max Depth | Equations (`inline`/`block`) | Math Chars | Status |",
        "| :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]

    for r in articles:
        m = r["metrics"]
        eq_str = f"{m['est_equation_count']:,} ({m['est_inline_math_count']}/{m['est_block_math_count']})"
        lines.append(
            f"| **{r['topic_id']}** | {r['word_count']:,} | {r['raw_chars']:,} | {m['est_pg_jsonb_bytes']:,} | "
            f"{m['est_request_bytes']:,} | {m['est_visited_nodes']:,} | {m['est_max_depth']} | {eq_str} | "
            f"{m['est_equation_chars']:,} | `{r['budget_status']}` |"
        )

    lines.extend([
        "",
        "## 3. Proposed Multi-Part Splits at Top-Level `##` Headings (`WARN` & `OVER_LIMIT` Articles)",
        "",
    ])

    split_articles = [r for r in articles if r["budget_status"] != "PASS"]
    if not split_articles:
        lines.append("All articles satisfy `PASS` without splitting.")
    else:
        for r in split_articles:
            lines.append(f"### {r['topic_id']} — {r['title']} (`{r['budget_status']}`)")
            lines.append(f"- **Trigger(s):** {'; '.join(r['budget_reasons'])}")
            lines.append("")
            lines.append("| Part | Start Heading | End Heading | Sections | Est PG Bytes | Est Request Bytes | Visited Nodes | Max Depth | Equations | Status |")
            lines.append("| :---: | :--- | :--- | :---: | ---: | ---: | ---: | ---: | ---: | :--- |")
            for p in r["proposed_splits"]:
                lines.append(
                    f"| **{r['topic_id']}_p{p['part_index']}** | `{p['start_heading']}` | `{p['end_heading']}` | {p['section_count']} | "
                    f"{p['est_pg_jsonb_bytes']:,} | {p['est_request_bytes']:,} | {p['est_visited_nodes']:,} | {p['est_max_depth']} | "
                    f"{p['est_equation_count']:,} | `{p['budget_status']}` |"
                )
            lines.append("")

    lines.extend([
        "## 4. Unsupported Website Feature Inventory",
        "",
        "| ID | Leading `h1` | Body `h1` | `h5`/`h6` | Pipe Tables (w/ math) | Footnotes | `\\label`/`\\ref`/`\\eqref` | Invalid Links |",
        "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for r in articles:
        uf = r["unsupported_features"]
        tbl_cnt = len(uf["tables"])
        tbl_math = sum(1 for t in uf["tables"] if t["contains_math"])
        lines.append(
            f"| **{r['topic_id']}** | {len(uf['leading_h1'])} | {len(uf['body_h1_violations'])} | "
            f"{len(uf['deep_heading_violations'])} | {tbl_cnt} ({tbl_math}) | {len(uf['footnotes'])} | "
            f"{len(uf['latex_cross_refs'])} | {len(uf['invalid_links'])} |"
        )
    lines.append("")

    lines.append("### Detailed Line References for Violations & Tables")
    lines.append("")
    for r in articles:
        uf = r["unsupported_features"]
        details: list[str] = []
        if uf["body_h1_violations"]:
            details.append("Body `h1`: " + ", ".join(f"L{x['line']} (`{x['text']}`)" for x in uf["body_h1_violations"]))
        if uf["deep_heading_violations"]:
            details.append("Deep `h5`/`h6`: " + ", ".join(f"L{x['line']} (h{x['level']} `{x['text']}`)" for x in uf["deep_heading_violations"]))
        if uf["tables"]:
            details.append(
                "Pipe tables: " + ", ".join(
                    f"L{t['start_line']}–L{t['end_line']} ({t['total_rows']}x{t['cols']}, math={t['contains_math']})"
                    for t in uf["tables"]
                )
            )
        if uf["footnotes"]:
            details.append("Footnotes: " + ", ".join(f"L{x['line']} ([^{x['id']}] {x['kind']})" for x in uf["footnotes"]))
        if uf["latex_cross_refs"]:
            details.append("LaTeX refs: " + ", ".join(f"L{x['line']} (`{x['cmd']}{{{x['key']}}}`)" for x in uf["latex_cross_refs"]))
        if uf["invalid_links"]:
            details.append("Invalid links: " + ", ".join(f"L{x['line']} (`{x['href']}`)" for x in uf["invalid_links"]))
        if details:
            lines.append(f"- **{r['topic_id']} (`{r['filename']}`):** " + " | ".join(details))
    lines.append("")

    # Section 5: LaTeX Macro & Environment Inventory
    lines.extend([
        "## 5. LaTeX Environment & Macro Inventory",
        "",
        "### Environments (`\\begin{...}`)",
        "",
        "| Environment | Total Uses | Articles Using | Topic IDs |",
        "| :--- | ---: | ---: | :--- |",
    ])
    for env, info in report["corpus_latex_environments"].items():
        lines.append(f"| `\\begin{{{env}}}` | {info['count']:,} | {info['topic_count']} | {', '.join(info['topics'])} |")

    lines.extend([
        "",
        "### Selected Non-Trivial & Rare Commands/Macros",
        "",
        "| Command | Total Uses | Articles Using |",
        "| :--- | ---: | ---: |",
    ])
    for cmd, info in list(report["highlighted_nontrivial_commands"].items())[:60]:
        lines.append(f"| `\\{cmd}` | {info['count']:,} | {info['topic_count']} |")
    lines.append("")

    # Section 6: Cross-Article Notation Drift Audit
    lines.extend([
        "## 6. Cross-Article Notation Drift Audit",
        "",
    ])

    def sum_drift(group: str, key: str) -> int:
        return sum(r["notation_drift"][group][key] for r in articles)

    def topics_with(group: str, key: str) -> str:
        tids = [r["topic_id"] for r in articles if r["notation_drift"][group][key] > 0]
        return ", ".join(tids) if tids else "*(none)*"

    drift_rows = [
        ("Vectors", "`\\mathbf{x}` (lowercase bold)", sum_drift("vectors", "mathbf_lower"), topics_with("vectors", "mathbf_lower")),
        ("Vectors", "`\\boldsymbol{...}` (bold italic/Greek)", sum_drift("vectors", "boldsymbol"), topics_with("vectors", "boldsymbol")),
        ("Vectors", "`\\vec{...}`", sum_drift("vectors", "vec_arrow"), topics_with("vectors", "vec_arrow")),
        ("Vectors", "`\\bm{...}`", sum_drift("vectors", "bm"), topics_with("vectors", "bm")),
        ("Transpose", "`^T` (plain superscript)", sum_drift("transpose", "caret_T"), topics_with("transpose", "caret_T")),
        ("Transpose", "`^{T}` (braced T)", sum_drift("transpose", "caret_braced_T"), topics_with("transpose", "caret_braced_T")),
        ("Transpose", "`^\\top`", sum_drift("transpose", "caret_top"), topics_with("transpose", "caret_top")),
        ("Transpose", "`^{\\mathsf{T}}`", sum_drift("transpose", "caret_mathsf_T"), topics_with("transpose", "caret_mathsf_T")),
        ("Expectation", "`\\mathbb{E}`", sum_drift("probability_operators", "E_mathbb"), topics_with("probability_operators", "E_mathbb")),
        ("Expectation", "`\\mathbb{E}(...)` (paren)", sum_drift("probability_operators", "E_mathbb_paren"), topics_with("probability_operators", "E_mathbb_paren")),
        ("Expectation", "Plain `E[...]` (prob/stats)", sum_drift("probability_operators", "E_plain_bracket"), topics_with("probability_operators", "E_plain_bracket")),
        ("Expectation", "Plain `E(...)` (prob/stats)", sum_drift("probability_operators", "E_plain_paren"), topics_with("probability_operators", "E_plain_paren")),
        ("Probability", "`\\mathbb{P}`", sum_drift("probability_operators", "P_mathbb"), topics_with("probability_operators", "P_mathbb")),
        ("Probability", "`\\Pr`", sum_drift("probability_operators", "P_Pr"), topics_with("probability_operators", "P_Pr")),
        ("Probability", "Plain `P(...)` (prob/stats)", sum_drift("probability_operators", "P_plain_paren"), topics_with("probability_operators", "P_plain_paren")),
        ("Variance", "`\\operatorname{Var}`", sum_drift("probability_operators", "Var_operatorname"), topics_with("probability_operators", "Var_operatorname")),
        ("Variance", "`\\mathrm{Var}`", sum_drift("probability_operators", "Var_mathrm"), topics_with("probability_operators", "Var_mathrm")),
        ("Variance", "`\\text{Var}`", sum_drift("probability_operators", "Var_text"), topics_with("probability_operators", "Var_text")),
        ("Covariance", "`\\operatorname{Cov}`", sum_drift("probability_operators", "Cov_operatorname"), topics_with("probability_operators", "Cov_operatorname")),
        ("Covariance", "`\\text{Cov}`", sum_drift("probability_operators", "Cov_text"), topics_with("probability_operators", "Cov_text")),
        ("Norms", "`\\lVert ... \\rVert`", sum_drift("norms_and_indicators", "norm_lVert_rVert"), topics_with("norms_and_indicators", "norm_lVert_rVert")),
        ("Norms", "`\\| ... \\|`", sum_drift("norms_and_indicators", "norm_backslash_bar"), topics_with("norms_and_indicators", "norm_backslash_bar")),
        ("Norms", "`||...||` (raw double pipe)", sum_drift("norms_and_indicators", "norm_double_pipe"), topics_with("norms_and_indicators", "norm_double_pipe")),
        ("Inner Product", "`\\langle u, v \\rangle`", sum_drift("norms_and_indicators", "inner_langle_rangle"), topics_with("norms_and_indicators", "inner_langle_rangle")),
        ("Indicator", "`\\mathbf{1}`", sum_drift("norms_and_indicators", "indicator_mathbf1"), topics_with("norms_and_indicators", "indicator_mathbf1")),
        ("Indicator", "`\\mathbb{1}`", sum_drift("norms_and_indicators", "indicator_mathbb1"), topics_with("norms_and_indicators", "indicator_mathbb1")),
        ("Indicator", "`\\mathbbm{1}`", sum_drift("norms_and_indicators", "indicator_mathbbm1"), topics_with("norms_and_indicators", "indicator_mathbbm1")),
        ("Differential", "`\\mathrm{d}x`", sum_drift("operators_and_differentials", "dx_mathrm_d"), topics_with("operators_and_differentials", "dx_mathrm_d")),
        ("Differential", "`\\,dx` / `dx`", sum_drift("operators_and_differentials", "dx_italic_d"), topics_with("operators_and_differentials", "dx_italic_d")),
        ("Optimization", "`\\operatorname*{argmin/max}`", sum_drift("operators_and_differentials", "argmin_max_opstar"), topics_with("operators_and_differentials", "argmin_max_opstar")),
        ("Optimization", "`\\arg\\min` / `\\arg\\max`", sum_drift("operators_and_differentials", "argmin_max_arg_min"), topics_with("operators_and_differentials", "argmin_max_arg_min")),
        ("Operators", "`\\operatorname{span}` vs `\\text/\\mathrm{span}`", sum_drift("operators_and_differentials", "span_operatorname"), topics_with("operators_and_differentials", "span_operatorname") + f" (text/rm={sum_drift('operators_and_differentials', 'span_text_rm')})"),
        ("Operators", "`\\operatorname{tr}` vs `\\text/\\mathrm{tr}`", sum_drift("operators_and_differentials", "tr_operatorname"), topics_with("operators_and_differentials", "tr_operatorname") + f" (text/rm={sum_drift('operators_and_differentials', 'tr_text_rm')})"),
        ("Sets", "`\\mathbb{R}`", sum_drift("operators_and_differentials", "set_mathbb_R"), topics_with("operators_and_differentials", "set_mathbb_R")),
        ("Callouts", "Blockquote `> **Theorem...**`", sum_drift("callouts", "blockquote_bold"), topics_with("callouts", "blockquote_bold")),
        ("Callouts", "Bold lead-in `**Theorem...**`", sum_drift("callouts", "paragraph_bold_lead"), topics_with("callouts", "paragraph_bold_lead")),
        ("Callouts", "Heading `### Theorem...`", sum_drift("callouts", "heading_callout"), topics_with("callouts", "heading_callout")),
        ("Proofs", "Italic `*Proof.*`", sum_drift("callouts", "proof_italic"), topics_with("callouts", "proof_italic")),
        ("Proofs", "Bold `**Proof.**`", sum_drift("callouts", "proof_bold"), topics_with("callouts", "proof_bold")),
        ("Proofs", "Heading `##### Proof`", sum_drift("callouts", "proof_heading"), topics_with("callouts", "proof_heading")),
        ("QED", "`\\square`", sum_drift("callouts", "qed_square"), topics_with("callouts", "qed_square")),
        ("QED", "`\\blacksquare`", sum_drift("callouts", "qed_blacksquare"), topics_with("callouts", "qed_blacksquare")),
    ]

    lines.extend([
        "| Category | Variant | Total Occurrences | Topics Present |",
        "| :--- | :--- | ---: | :--- |",
    ])
    for cat, var, cnt, tids in drift_rows:
        lines.append(f"| {cat} | {var} | {cnt:,} | {tids} |")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage A1: Website readiness & ProseMirror budget audit.")
    parser.parse_args()

    WEB_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = audit_corpus()
    AUDIT_JSON_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    AUDIT_MD_PATH.write_text(render_audit_markdown(report), encoding="utf-8")

    s = report["summary"]
    print(f"Wrote {AUDIT_JSON_PATH}")
    print(f"Wrote {AUDIT_MD_PATH}")
    print(f"Articles={s['total_articles']} | Statuses={s['status_counts']} | ProposedParts={s['total_proposed_web_parts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
