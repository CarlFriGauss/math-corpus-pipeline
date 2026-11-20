#!/usr/bin/env python3
"""Stage A5: Dual-target corpus exporter (--target web and --target local)."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_web_readiness import (  # noqa: E402
    classify_budget,
    is_table_separator,
    markdown_to_prosemirror_doc,
    mask_math_preserving_lines,
    measure_prosemirror_ast,
    scan_unsupported_features,
    split_table_row,
    split_top_level_h2,
    strip_code_spans_and_blocks,
)

SET_2_DIR = ROOT / "output" / "set_2_corrected"
KG_PATH = ROOT / "output" / "graph" / "knowledge_graph.json"
PUB_MANIFEST_PATH = ROOT / "output" / "web_export" / "publication_manifest.json"
WEB_ESSAYS_DIR = ROOT / "output" / "web_export" / "essays"
LOCAL_HTML_DIR = ROOT / "output" / "local_html"
TEMPLATE_HTML_PATH = SCRIPTS_DIR / "templates" / "article.html"
TEMPLATE_CSS_PATH = SCRIPTS_DIR / "templates" / "article.css"


def strip_outer_bold(cell: str) -> str:
    """Remove redundant outer **...** markers from a table header or lead cell."""
    s = cell.strip()
    if len(s) >= 4 and s.startswith("**") and s.endswith("**") and "**" not in s[2:-2]:
        return s[2:-2].strip()
    return s


def format_lead_cell(cell: str) -> str:
    """Format first cell of a converted table row cleanly without breaking inline math."""
    s = cell.strip()
    if not s:
        return "*(blank)*"
    if "$" in s or s.startswith("**"):
        return s
    return f"**{s}**"


def convert_pipe_tables_to_lists(markdown_text: str) -> str:
    """Convert GFM pipe tables into math-preserving structured bullet lists."""
    lines = markdown_text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    in_fence = False
    fence_char = "`"
    fence_len = 3

    while i < n:
        ln = lines[i]
        m_fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", ln)
        if not in_fence and m_fence:
            in_fence = True
            fence_char = m_fence.group(1)[0]
            fence_len = len(m_fence.group(1))
            out.append(ln)
            i += 1
            continue
        if in_fence:
            if re.match(rf"^\s{{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$", ln):
                in_fence = False
            out.append(ln)
            i += 1
            continue

        if "|" in ln and i + 1 < n and is_table_separator(lines[i + 1]):
            headers = [strip_outer_bold(h) for h in split_table_row(ln)]
            j = i + 2
            rows: list[list[str]] = []
            while j < n and lines[j].strip() and "|" in lines[j] and not re.match(r"^\s{0,3}(#{1,6}\s|```|>)", lines[j]):
                rows.append(split_table_row(lines[j]))
                j += 1

            # Ensure blank line separation before converted table block
            if out and out[-1].strip():
                out.append("")

            if len(headers) == 2:
                out.append(f"**{headers[0]} — {headers[1]}:**")
                out.append("")
                for r in rows:
                    c0 = format_lead_cell(r[0] if len(r) > 0 else "")
                    c1 = (r[1] if len(r) > 1 else "").strip()
                    if c1:
                        out.append(f"- {c0} — {c1}")
                    else:
                        out.append(f"- {c0}")
            else:
                hdr_summary = " · ".join(h for h in headers if h)
                out.append(f"**Table — {hdr_summary}:**")
                out.append("")
                for r in rows:
                    lead = format_lead_cell(r[0] if len(r) > 0 else "")
                    details: list[str] = []
                    for col_idx in range(1, len(headers)):
                        val = r[col_idx].strip() if col_idx < len(r) else ""
                        if not val:
                            continue
                        h_lbl = headers[col_idx] if headers[col_idx] else f"Col {col_idx + 1}"
                        details.append(f"{h_lbl}: {val}")
                    if details:
                        out.append(f"- {lead} — " + "; ".join(details))
                    else:
                        out.append(f"- {lead}")

            if j < n and lines[j].strip():
                out.append("")
            i = j
            continue

        out.append(ln)
        i += 1

    return "\n".join(out)


def convert_footnotes(markdown_text: str) -> str:
    """Convert any Markdown [^id] footnotes into inline notes or a trailing ## Notes section."""
    lines = markdown_text.splitlines()
    defs: dict[str, str] = {}
    kept_lines: list[str] = []
    i = 0
    n = len(lines)
    in_fence = False

    while i < n:
        ln = lines[i]
        if re.match(r"^\s{0,3}(`{3,}|~{3,})", ln):
            in_fence = not in_fence
            kept_lines.append(ln)
            i += 1
            continue
        if not in_fence:
            m_def = re.match(r"^\[\^([^\]]+)\]:\s*(.*)$", ln)
            if m_def:
                fid = m_def.group(1)
                parts = [m_def.group(2).strip()]
                i += 1
                while i < n and (lines[i].startswith("    ") or lines[i].startswith("\t") or not lines[i].strip()):
                    if lines[i].strip():
                        parts.append(lines[i].strip())
                    else:
                        if i + 1 < n and (lines[i + 1].startswith("    ") or lines[i + 1].startswith("\t")):
                            i += 1
                            continue
                        break
                    i += 1
                defs[fid] = " ".join(p for p in parts if p)
                continue
        kept_lines.append(ln)
        i += 1

    if not defs:
        return markdown_text

    body = "\n".join(kept_lines)
    notes_used: list[tuple[int, str]] = []

    def replace_ref_in_line(line: str) -> str:
        # Only replace outside inline code and math
        masked = mask_math_preserving_lines(strip_code_spans_and_blocks(line))
        matches = list(re.finditer(r"\[\^([^\]]+)\](?!:)", masked))
        if not matches:
            return line
        chars = list(line)
        for m in reversed(matches):
            fid = m.group(1)
            note_txt = defs.get(fid, fid)
            if len(note_txt) <= 140:
                repl = f" *(Note: {note_txt})*"
            else:
                notes_used.append((len(notes_used) + 1, note_txt))
                repl = f" *(Note {len(notes_used)})*"
            chars[m.start() : m.end()] = list(repl)
        return "".join(chars)

    out_lines: list[str] = []
    in_fence = False
    for ln in body.splitlines():
        if re.match(r"^\s{0,3}(`{3,}|~{3,})", ln):
            in_fence = not in_fence
            out_lines.append(ln)
            continue
        out_lines.append(ln if in_fence else replace_ref_in_line(ln))

    if notes_used:
        out_lines.extend(["", "## Notes", ""])
        for idx, ntxt in notes_used:
            out_lines.append(f"- **Note {idx}:** {ntxt}")

    return "\n".join(out_lines)


def normalize_headings_for_web(markdown_text: str) -> str:
    """Strip leading h1, convert body h1 -> h2, and convert h5/h6 -> bold lead-in paragraphs."""
    lines = markdown_text.splitlines()
    out: list[str] = []
    in_fence = False
    stripped_leading_h1 = False

    for idx, ln in enumerate(lines):
        if re.match(r"^\s{0,3}(`{3,}|~{3,})", ln):
            in_fence = not in_fence
            out.append(ln)
            continue
        if in_fence:
            out.append(ln)
            continue

        m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", ln)
        if not m:
            out.append(ln)
            continue

        lvl = len(m.group(1))
        text = m.group(2).strip()
        if lvl == 1:
            if not stripped_leading_h1 and idx <= 5:
                stripped_leading_h1 = True
                continue
            out.append(f"## {text}")
        elif lvl >= 5:
            clean = strip_outer_bold(text)
            if clean.endswith((".", ":", "!", "?")):
                out.append(f"**{clean}**")
            else:
                out.append(f"**{clean}.**")
        else:
            out.append(ln)

    return "\n".join(out).lstrip("\n")


def rewrite_links_for_web(markdown_text: str, manifest: dict[str, Any]) -> str:
    """Resolve internal article links via published_url or convert invalid schemes to plain-text citations."""
    # Map filename and topic IDs to records
    by_fn = {rec["source_filename"]: rec for rec in manifest.values()}
    lines = markdown_text.splitlines()
    out: list[str] = []
    in_fence = False

    def resolve_internal(label: str, href: str) -> str:
        # Check if href points to a known T## or source filename
        m_tid = re.search(r"\b(T\d{2})\b", href, re.IGNORECASE)
        m_fn = Path(href.split("#", 1)[0]).name
        target_rec = None
        if m_fn in by_fn:
            target_rec = by_fn[m_fn]
        elif m_tid and m_tid.group(1).upper() in manifest:
            target_rec = manifest[m_tid.group(1).upper()]

        if target_rec is not None:
            pub_url = target_rec["parts"][0].get("published_url")
            if pub_url:
                return f"[{label}]({pub_url})"
            return f"*{label} (see Article {target_rec['manuscript_id']}: {target_rec['title']})*"
        return f"*(see {label})*"

    for ln in lines:
        if re.match(r"^\s{0,3}(`{3,}|~{3,})", ln):
            in_fence = not in_fence
            out.append(ln)
            continue
        if in_fence:
            out.append(ln)
            continue

        masked = mask_math_preserving_lines(strip_code_spans_and_blocks(ln))
        matches = list(re.finditer(r"(?<!!)\[([^\[\]\n]*)\]\(([^)\s]+(?:\s+\"[^\"]*\")?)\)", masked))
        if not matches:
            out.append(ln)
            continue

        chars = list(ln)
        for m in reversed(matches):
            label = m.group(1)
            href = m.group(2).split()[0]
            if re.match(r"^(?:https?://|mailto:)", href, re.IGNORECASE):
                continue
            repl = resolve_internal(label, href)
            chars[m.start() : m.end()] = list(repl)
        out.append("".join(chars))

    return "\n".join(out)


def build_reading_context_blockquote(
    rec: dict[str, Any],
    part: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    """Build compact Prerequisites & Reading Context blockquote from knowledge_graph & manifest."""
    prereq_tokens: list[str] = []
    for pid in rec["prerequisite_ids"]:
        prec = manifest[pid]
        purl = prec["parts"][0].get("published_url")
        if purl:
            prereq_tokens.append(f"[{pid}: {prec['title']}]({purl})")
        else:
            prereq_tokens.append(f"**{pid}** ({prec['title']})")

    prereq_line = ", ".join(prereq_tokens) if prereq_tokens else "None (Foundational Layer 0 Entry)"
    lines = [
        f"> **Prerequisites & Reading Context:** Track: *{rec['discipline']}* (`{rec['academy_track']}`, Layer {rec['topological_layer']}).",
        f"> **Direct Prerequisites:** {prereq_line}.",
    ]

    if part["part_count"] > 1:
        nav_bits: list[str] = []
        for sib in rec["parts"]:
            if sib["part_id"] == part["part_id"]:
                nav_bits.append(f"**Part {sib['part_index']}** *(current)*")
            elif sib.get("published_url"):
                nav_bits.append(f"[Part {sib['part_index']}]({sib['published_url']})")
            else:
                nav_bits.append(f"Part {sib['part_index']}")
        lines.append(
            f"> **Series Navigation:** Part {part['part_index']} of {part['part_count']} for *{rec['title']}* ({' · '.join(nav_bits)})."
        )

    return "\n".join(lines)


def check_balanced_math(text: str) -> list[str]:
    """Verify balanced $$ blocks and single-line $ spans outside code blocks/spans."""
    issues: list[str] = []
    cleaned = strip_code_spans_and_blocks(text)
    dd_matches = list(re.finditer(r"(?<!\\)\$\$", cleaned))
    if len(dd_matches) % 2 != 0:
        issues.append(f"unbalanced $$ fence count={len(dd_matches)}")
        return issues

    no_dd = re.sub(r"(?<!\\)\$\$.*?(?<!\\)\$\$", " ", cleaned, flags=re.DOTALL)
    for lno, ln in enumerate(no_dd.splitlines(), 1):
        singles = re.findall(r"(?<!\\)\$", ln)
        if len(singles) % 2 != 0:
            issues.append(f"unbalanced single-$ on line {lno}: {ln[:100]!r}")
            break
    return issues


def export_web(manifest: dict[str, Any]) -> int:
    """Export all articles/parts to output/web_export/essays/ and validate 100% PASS."""
    WEB_ESSAYS_DIR.mkdir(parents=True, exist_ok=True)
    # Remove stale files inside WEB_ESSAYS_DIR before regenerating cleanly
    for old_f in WEB_ESSAYS_DIR.glob("*.md"):
        old_f.unlink()

    exported_results: list[dict[str, Any]] = []
    failures: list[str] = []

    for tid in sorted(manifest.keys(), key=lambda x: int(x[1:])):
        rec = manifest[tid]
        src_path = SET_2_DIR / rec["source_filename"]
        raw_text = src_path.read_text(encoding="utf-8")
        preamble, sections = split_top_level_h2(raw_text)
        sec_map: list[tuple[str, str]] = [(f"## {h}", txt) for h, txt in sections]

        # Build exact part slices aligned with publication_manifest.json
        cursor = 0
        for part in rec["parts"]:
            if len(rec["parts"]) == 1:
                part_body_raw = raw_text
            else:
                chunks: list[str] = []
                if part["part_index"] == 1 and preamble:
                    chunks.append(preamble)
                needed = list(part["section_headings"])
                matched_texts: list[str] = []
                while cursor < len(sec_map) and len(matched_texts) < len(needed):
                    h_key, s_txt = sec_map[cursor]
                    if h_key == needed[len(matched_texts)]:
                        matched_texts.append(s_txt)
                        cursor += 1
                    else:
                        break
                assert len(matched_texts) == len(needed), (
                    f"{part['part_id']} section alignment mismatch: expected {len(needed)}, got {len(matched_texts)}"
                )
                chunks.extend(matched_texts)
                part_body_raw = "\n\n".join(chunks)

            # Apply deterministic website compatibility transforms
            transformed = normalize_headings_for_web(part_body_raw)
            transformed = convert_pipe_tables_to_lists(transformed)
            transformed = convert_footnotes(transformed)
            transformed = rewrite_links_for_web(transformed, manifest)
            transformed = re.sub(r"\n{3,}", "\n\n", transformed).strip()

            context_bq = build_reading_context_blockquote(rec, part, manifest)
            final_md = f"{context_bq}\n\n{transformed}\n"

            out_name = (
                f"{tid}_{part['slug_preview']}.md"
                if part["part_count"] == 1
                else f"{part['part_id']}_{part['slug_preview']}.md"
            )
            out_path = WEB_ESSAYS_DIR / out_name
            out_path.write_text(final_md, encoding="utf-8")

            # Re-run synthetic ProseMirror budget validator + feature checks
            doc = markdown_to_prosemirror_doc(final_md)
            metrics = measure_prosemirror_ast(
                doc,
                title=part["part_title"],
                summary=part["full_summary"],
            )
            status, reasons = classify_budget(metrics)
            uf = scan_unsupported_features(final_md)
            math_issues = check_balanced_math(final_md)

            part_issues: list[str] = []
            if status != "PASS":
                part_issues.append(f"budget={status}: {'; '.join(reasons)}")
            if uf["leading_h1"] or uf["body_h1_violations"]:
                part_issues.append(f"h1_present={len(uf['leading_h1']) + len(uf['body_h1_violations'])}")
            if uf["deep_heading_violations"]:
                part_issues.append(f"h5_h6_present={len(uf['deep_heading_violations'])}")
            if uf["tables"]:
                part_issues.append(f"raw_pipe_tables={len(uf['tables'])}")
            if uf["footnotes"]:
                part_issues.append(f"raw_footnotes={len(uf['footnotes'])}")
            if uf["latex_cross_refs"]:
                part_issues.append(f"latex_refs={len(uf['latex_cross_refs'])}")
            if uf["invalid_links"]:
                part_issues.append(f"invalid_links={uf['invalid_links']}")
            if math_issues:
                part_issues.extend(math_issues)

            if part_issues:
                failures.append(f"{out_name}: {'; '.join(part_issues)}")

            exported_results.append({
                "part_id": part["part_id"],
                "file": out_name,
                "status": status,
                "pg_bytes": metrics["est_pg_jsonb_bytes"],
                "req_bytes": metrics["est_request_bytes"],
                "nodes": metrics["est_visited_nodes"],
                "depth": metrics["est_max_depth"],
                "equations": metrics["est_equation_count"],
                "issues": part_issues,
            })

        if len(rec["parts"]) > 1:
            assert cursor == len(sec_map), f"{tid} unexported trailing sections: {cursor}/{len(sec_map)}"

    # Write export summary log inside web_export/
    summary_lines = [
        "# Website Export Validation Report (`output/web_export/essays/`)",
        "",
        f"- **Total Exported Web Essays:** {len(exported_results)}",
        f"- **100% PASS Verification:** {'PASSED' if not failures else f'FAILED ({len(failures)} issues)'}",
        "",
        "| Part ID | Filename | Est PG Bytes | Est Request Bytes | Visited Nodes | Max Depth | Equations | Status |",
        "| :---: | :--- | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for er in exported_results:
        summary_lines.append(
            f"| **{er['part_id']}** | `{er['file']}` | {er['pg_bytes']:,} | {er['req_bytes']:,} | "
            f"{er['nodes']:,} | {er['depth']} | {er['equations']:,} | `{er['status']}` |"
        )
    summary_lines.append("")
    (WEB_ESSAYS_DIR.parent / "EXPORT_VALIDATION.md").write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"Exported {len(exported_results)} web essays to {WEB_ESSAYS_DIR}")
    if failures:
        for fl in failures:
            print(f"  [FAIL] {fl}")
        return 1

    max_bytes = max(r["pg_bytes"] for r in exported_results)
    max_nodes = max(r["nodes"] for r in exported_results)
    max_depth = max(r["depth"] for r in exported_results)
    print(f"ALL {len(exported_results)}/{len(exported_results)} EXPORTED ESSAYS PASSED (max_bytes={max_bytes:,}, max_nodes={max_nodes:,}, max_depth={max_depth})")
    return 0


def resolve_topic_filter(topic_arg: str | None, manifest: dict[str, Any]) -> list[str]:
    """Normalize --topic argument (e.g. T08, 08, T08,T12) into sorted topic IDs."""
    if not topic_arg:
        return sorted(manifest.keys(), key=lambda x: int(x[1:]))
    selected: list[str] = []
    for raw_tok in topic_arg.split(","):
        tok = raw_tok.strip().upper()
        if not tok:
            continue
        if not tok.startswith("T") and tok.isdigit():
            tok = f"T{int(tok):02d}"
        elif tok.startswith("T") and tok[1:].isdigit():
            tok = f"T{int(tok[1:]):02d}"
        if tok not in manifest:
            raise ValueError(f"Unknown topic ID: {raw_tok!r}")
        selected.append(tok)
    return selected


def strip_leading_h1(markdown_text: str) -> str:
    """Remove the single leading # Title line so Pandoc's title header and TOC do not duplicate H1."""
    lines = markdown_text.splitlines()
    for idx, ln in enumerate(lines[:5]):
        if re.match(r"^#\s+\S", ln):
            rest = lines[:idx] + lines[idx + 1 :]
            return "\n".join(rest).lstrip("\n") + ("\n" if markdown_text.endswith("\n") else "")
    return markdown_text


def export_local(manifest: dict[str, Any], topic_arg: str | None, dry_run: bool) -> int:
    """Compile standalone local HTML files using pandoc --katex and publication reading template into output/local_html/."""
    pandoc_bin = shutil.which("pandoc")
    if not pandoc_bin and not dry_run:
        print("ERROR: `pandoc` not found on PATH. Install Pandoc or run with --dry-run.")
        return 1
    if not TEMPLATE_HTML_PATH.exists() or not TEMPLATE_CSS_PATH.exists():
        print(f"ERROR: Missing local HTML template/CSS at {TEMPLATE_HTML_PATH.parent}")
        return 1

    selected_ids = resolve_topic_filter(topic_arg, manifest)
    if not dry_run:
        LOCAL_HTML_DIR.mkdir(parents=True, exist_ok=True)

    css_text = TEMPLATE_CSS_PATH.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="articles_local_html_") as tmpdir:
        tmp_root = Path(tmpdir)
        style_hdr = tmp_root / "inline_article_css.html"
        style_hdr.write_text(f"<style>\n{css_text}\n</style>\n", encoding="utf-8")

        for tid in selected_ids:
            rec = manifest[tid]
            src_path = SET_2_DIR / rec["source_filename"]
            out_path = LOCAL_HTML_DIR / (Path(rec["source_filename"]).stem + ".html")

            raw_text = src_path.read_text(encoding="utf-8")
            words = len(raw_text.split())
            read_mins = max(1, round(words / 200))
            prereq_ids = rec.get("prerequisite_ids", [])
            if prereq_ids:
                prereq_html = ", ".join(
                    f'<a href="{html.escape(Path(manifest[pid]["source_filename"]).stem + ".html")}">'
                    f"{html.escape(pid)}: {html.escape(manifest[pid]['title'])}</a>"
                    for pid in prereq_ids
                )
            else:
                prereq_html = "None (Foundational Entry)"

            md_for_pandoc = strip_leading_h1(raw_text)
            tmp_md = tmp_root / src_path.name
            tmp_md.write_text(md_for_pandoc, encoding="utf-8")

            cmd = [
                pandoc_bin or "pandoc",
                str(tmp_md),
                "--standalone",
                "--template",
                str(TEMPLATE_HTML_PATH),
                "--include-in-header",
                str(style_hdr),
                "--katex",
                "--toc",
                "--toc-depth=3",
                "--from",
                "markdown+tex_math_dollars+pipe_tables+footnotes+lists_without_preceding_blankline",
                "--to",
                "html5",
                "--metadata",
                f"title={rec['title']}",
                "--variable",
                f"prerequisites={prereq_html}",
                "--variable",
                f"topic-id={html.escape(tid)}",
                "--variable",
                f"discipline={html.escape(rec['discipline'])}",
                "--variable",
                f"layer={rec['topological_layer']}",
                "--variable",
                f"reading-time=~{read_mins} min read ({words:,} words)",
                "-o",
                str(out_path),
            ]
            if dry_run:
                print("[DRY-RUN]", " ".join(f'"{c}"' if " " in c else c for c in cmd))
                continue

            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                print(f"[ERROR] {tid} pandoc failed (rc={proc.returncode}): {proc.stderr.strip()}")
                return proc.returncode
            print(f"[OK] {tid} -> {out_path.name} ({out_path.stat().st_size:,} bytes)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage A5: Dual-target corpus exporter.")
    parser.add_argument("--target", choices=["web", "local", "all"], required=True, help="Export target: web, local, or all")
    parser.add_argument("--topic", help="Optional topic ID(s) for --target local (e.g. T08 or T01,T08)")
    parser.add_argument("--dry-run", action="store_true", help="Print local pandoc commands without executing")
    args = parser.parse_args()

    manifest = json.loads(PUB_MANIFEST_PATH.read_text(encoding="utf-8"))

    if args.target in ("web", "all"):
        rc = export_web(manifest)
        if rc != 0:
            return rc
    if args.target in ("local", "all"):
        rc = export_local(manifest, args.topic, args.dry_run)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
