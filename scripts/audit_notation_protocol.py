#!/usr/bin/env python3
"""Deterministic Global Mathematical Notation & Callout Protocol auditor for Set 2 Markdown files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SET_2_DIR = ROOT / "output" / "set_2_corrected"

FORMAL_LABELS = ("Axiom", "Definition", "Theorem", "Proposition", "Lemma", "Corollary")
FORMAL_LABELS_RE = "|".join(FORMAL_LABELS)

GREEK_LOWER = (
    "alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|"
    "lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|phi|varphi|chi|psi|omega"
)

UNBOLDED_MATRIX_BASE_RE = re.compile(
    r"(?:"
    r"\\overline\{\s*([A-Z])\s*\}"
    r"|(?<![\\A-Za-z_^])([A-Z])"
    r")"
    r"(?:\s*_(?:\{[^}\n]+\}|[a-zA-Z0-9]))*"
    r"\s*\^"
    r"(\s*(?:\\top(?![a-zA-Z])|\{\s*\\top\s*\}|T(?![a-zA-Z])|\{\s*T\s*\}|\\mathsf\{T\}|\{\s*\\mathsf\{T\}\s*\}|\{\s*-1\s*\}|\*|\{\s*\*+\s*\}|\\ast(?![a-zA-Z])|\{\s*\\ast\s*\}))"
)


def is_in_script_or_formatted_group(tex: str, pos: int) -> bool:
    """Return True if pos lies immediately inside a subscript/superscript or font-command brace group."""
    depth = 0
    i = pos - 1
    while i >= 0:
        ch = tex[i]
        if ch == "}" and not is_escaped(tex, i):
            depth += 1
        elif ch == "{" and not is_escaped(tex, i):
            if depth == 0:
                before = tex[:i].rstrip()
                if before.endswith(("_", "^")):
                    return True
                if re.search(
                    r"\\(?:mathbf|boldsymbol|mathcal|mathbb|mathrm|text|operatorname|mathsf|mathfrak|mathscr)\s*$",
                    before,
                ):
                    return True
                return False
            depth -= 1
        i -= 1
    return False


@dataclass
class Violation:
    file: str
    line: int
    rule: str
    token: str
    snippet: str


@dataclass
class WarningItem:
    file: str
    line: int
    rule: str
    token: str
    snippet: str


@dataclass
class MathSpan:
    kind: str  # "display" or "inline"
    start_line: int
    latex: str


def is_escaped(text: str, idx: int) -> bool:
    """Return True if index idx is preceded by an odd number of backslashes."""
    slashes = 0
    j = idx - 1
    while j >= 0 and text[j] == "\\":
        slashes += 1
        j -= 1
    return (slashes % 2) == 1


def mask_code_preserving_lines(raw_text: str) -> str:
    """Replace fenced code blocks and inline code spans with spaces while preserving line numbers."""
    lines = raw_text.splitlines(keepends=True)
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

        # Mask inline `...` code spans preserving line offsets
        chars = list(ln)
        i = 0
        n = len(chars)
        while i < n:
            if chars[i] == "`" and not is_escaped(ln, i):
                j = i
                while j < n and chars[j] == "`":
                    j += 1
                tick_len = j - i
                # Find matching closing backtick run of exact length tick_len
                k = j
                close_pos = -1
                while k < n:
                    if chars[k] == "`":
                        k2 = k
                        while k2 < n and chars[k2] == "`":
                            k2 += 1
                        if (k2 - k) == tick_len:
                            close_pos = k
                            break
                        k = k2
                    else:
                        k += 1
                if close_pos != -1:
                    for p in range(i, close_pos + tick_len):
                        if chars[p] != "\n":
                            chars[p] = " "
                    i = close_pos + tick_len
                    continue
                i = j
                continue
            i += 1
        out.append("".join(chars))
    return "".join(out)


def extract_math_spans(no_code: str) -> list[MathSpan]:
    """Extract $$...$$ display and $...$ inline math spans with 1-based start lines, ignoring escaped \\$."""
    spans: list[MathSpan] = []
    n = len(no_code)
    i = 0
    line_num = 1

    while i < n:
        ch = no_code[i]
        if ch == "\n":
            line_num += 1
            i += 1
            continue

        # Display math $$...$$
        if ch == "$" and i + 1 < n and no_code[i + 1] == "$" and not is_escaped(no_code, i):
            start_line = line_num
            j = i + 2
            end_pos = -1
            while j < n - 1:
                if no_code[j] == "$" and no_code[j + 1] == "$" and not is_escaped(no_code, j):
                    end_pos = j
                    break
                j += 1
            if end_pos != -1:
                latex = no_code[i + 2 : end_pos]
                spans.append(MathSpan(kind="display", start_line=start_line, latex=latex))
                line_num += no_code[i : end_pos + 2].count("\n")
                i = end_pos + 2
                continue

        # Inline math $...$ (single line, non-empty, no unescaped $ inside)
        if ch == "$" and not is_escaped(no_code, i):
            if i + 1 < n and no_code[i + 1] == "$":
                i += 2
                continue
            start_line = line_num
            j = i + 1
            end_pos = -1
            while j < n and no_code[j] != "\n":
                if no_code[j] == "$" and not is_escaped(no_code, j):
                    if j + 1 < n and no_code[j + 1] == "$":
                        j += 2
                        continue
                    end_pos = j
                    break
                j += 1
            if end_pos != -1:
                latex = no_code[i + 1 : end_pos]
                if latex.strip():
                    spans.append(MathSpan(kind="inline", start_line=start_line, latex=latex))
                i = end_pos + 1
                continue

        i += 1

    return spans


def find_escaped_norm_bars(latex: str) -> list[int]:
    """Return character indices of genuine \\| inside math (skipping \\\\| line-break + abs-bar)."""
    hits: list[int] = []
    i = 0
    n = len(latex)
    while i < n - 1:
        if latex[i] == "\\" and latex[i + 1] == "|":
            if not is_escaped(latex, i):
                hits.append(i)
            i += 2
        else:
            i += 1
    return hits


def offset_to_line_and_snippet(span: MathSpan, char_offset: int) -> tuple[int, str]:
    """Map a character offset within span.latex to (1-based file line, trimmed line snippet)."""
    line = span.start_line + span.latex[:char_offset].count("\n")
    ls = span.latex.rfind("\n", 0, char_offset) + 1
    le = span.latex.find("\n", char_offset)
    if le == -1:
        le = len(span.latex)
    snip = span.latex[ls:le].strip()
    if len(snip) > 120:
        rel = char_offset - ls
        start = max(0, rel - 45)
        end = min(len(snip), rel + 65)
        snip = ("..." if start > 0 else "") + snip[start:end] + ("..." if end < len(snip) else "")
    return line, snip


def audit_file(path: Path) -> dict[str, Any]:
    """Audit a single Set 2 Markdown file against the Global Mathematical Notation & Callout Protocol."""
    rel_path = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    raw_text = path.read_text(encoding="utf-8")
    no_code = mask_code_preserving_lines(raw_text)
    raw_lines = raw_text.splitlines()
    no_code_lines = no_code.splitlines()
    spans = extract_math_spans(no_code)

    hard_violations: list[Violation] = []
    heuristic_warnings: list[WarningItem] = []

    # ------------------------------------------------------------------
    # 1. Math-span hard violations & heuristic unbolded matrix warnings
    # ------------------------------------------------------------------
    math_hard_patterns: list[tuple[str, re.Pattern[str]]] = [
        ("vec_command", re.compile(r"\\vec(?:\{|(?![a-zA-Z]))")),
        ("bm_command", re.compile(r"\\bm(?:\{|(?![a-zA-Z]))")),
        ("mathbb_1", re.compile(r"\\mathbb\{\s*1\s*\}")),
        ("mathbbm_command", re.compile(r"\\mathbbm(?:\{|(?![a-zA-Z]))")),
        ("text_or_rm_Var_Cov", re.compile(r"\\(?:text|mathrm)\{\s*(?:Var|Cov)\s*\}")),
        ("legacy_qed", re.compile(r"\\(?:blacksquare|Box)(?![a-zA-Z])")),
        ("mathbf_greek_lowercase", re.compile(rf"\\mathbf\{{\s*\\(?:{GREEK_LOWER})(?![a-zA-Z])\s*\}}")),
    ]

    qed_square_count = 0
    qed_legacy_count = 0
    caret_top_count = 0
    caret_legacy_t_count = 0

    for span in spans:
        tex = span.latex
        qed_square_count += len(re.findall(r"\\square(?![a-zA-Z])", tex))
        qed_legacy_count += len(re.findall(r"\\(?:blacksquare|Box)(?![a-zA-Z])", tex))
        caret_top_count += len(re.findall(r"\^(?:\\top(?![a-zA-Z])|\{\s*\\top\s*\})", tex))
        caret_legacy_t_count += len(re.findall(r"\^(?:T(?![a-zA-Z])|\{\s*T\s*\}|\\mathsf\{T\}|\{\s*\\mathsf\{T\}\s*\})", tex))

        for rule, pat in math_hard_patterns:
            for m in pat.finditer(tex):
                ln, snip = offset_to_line_and_snippet(span, m.start())
                hard_violations.append(
                    Violation(file=rel_path, line=ln, rule=rule, token=m.group(0), snippet=snip)
                )

        for idx in find_escaped_norm_bars(tex):
            ln, snip = offset_to_line_and_snippet(span, idx)
            hard_violations.append(
                Violation(file=rel_path, line=ln, rule="norm_backslash_bar", token="\\|", snippet=snip)
            )

        # Heuristic warning list for unbolded matrix indicators
        for m in UNBOLDED_MATRIX_BASE_RE.finditer(tex):
            if is_in_script_or_formatted_group(tex, m.start()):
                continue
            ln, snip = offset_to_line_and_snippet(span, m.start())
            heuristic_warnings.append(
                WarningItem(
                    file=rel_path,
                    line=ln,
                    rule="unbolded_matrix_indicator",
                    token=m.group(0).strip(),
                    snippet=snip,
                )
            )

    # ------------------------------------------------------------------
    # 2. Structural & callout checks across non-code Markdown lines
    # ------------------------------------------------------------------
    bq_formal_lines: list[dict[str, Any]] = []
    non_bq_formal_leadin_lines: list[dict[str, Any]] = []
    proof_body_bold_lines: list[int] = []
    proof_blockquote_lines: list[int] = []
    proof_italic_lines: list[int] = []
    proof_heading_lines: list[int] = []

    re_h5_h6 = re.compile(r"^\s{0,3}(#{5,6})\s+(\S.*)$")
    re_bq_formal = re.compile(rf"^\s*>\s*\*\*({FORMAL_LABELS_RE})\b([^*]*)\*\*")
    re_para_formal = re.compile(rf"^\s*\*\*({FORMAL_LABELS_RE})\b([^*]*)\*\*")
    re_hdr_formal = re.compile(rf"^\s*(#{1,6})\s+(?:\*\*)?({FORMAL_LABELS_RE})\b")

    re_proof_italic = re.compile(r"^\s*(?:>\s*)*(?:(?<!\*)\*(?!\*)Proof\b[^*\n]*\*|(?<!_)_(?!_)Proof\b[^_\n]*_)")
    re_proof_bq = re.compile(r"^\s*>\s*\*\*Proof\b")
    re_proof_body_bold = re.compile(r"^\s*\*\*Proof\b")
    re_proof_hdr = re.compile(r"^\s*(#{2,6})\s+(?:\*\*)?Proof\b")

    for lno, (raw_ln, nc_ln) in enumerate(zip(raw_lines, no_code_lines), 1):
        if not nc_ln.strip():
            continue

        m_h56 = re_h5_h6.match(nc_ln)
        if m_h56:
            hard_violations.append(
                Violation(
                    file=rel_path,
                    line=lno,
                    rule=f"deep_heading_h{len(m_h56.group(1))}",
                    token=m_h56.group(1),
                    snippet=raw_ln.strip()[:120],
                )
            )

        if re_proof_italic.match(nc_ln):
            proof_italic_lines.append(lno)
            hard_violations.append(
                Violation(
                    file=rel_path,
                    line=lno,
                    rule="italic_proof",
                    token="*Proof...*",
                    snippet=raw_ln.strip()[:120],
                )
            )
        elif re_proof_bq.match(nc_ln):
            proof_blockquote_lines.append(lno)
            hard_violations.append(
                Violation(
                    file=rel_path,
                    line=lno,
                    rule="proof_inside_blockquote",
                    token="> **Proof",
                    snippet=raw_ln.strip()[:120],
                )
            )
        elif re_proof_hdr.match(nc_ln):
            proof_heading_lines.append(lno)
            if not m_h56:  # h2-h4 Proof heading
                hard_violations.append(
                    Violation(
                        file=rel_path,
                        line=lno,
                        rule="heading_proof",
                        token=re_proof_hdr.match(nc_ln).group(1) + " Proof",
                        snippet=raw_ln.strip()[:120],
                    )
                )
        elif re_proof_body_bold.match(nc_ln):
            proof_body_bold_lines.append(lno)

        m_bq = re_bq_formal.match(nc_ln)
        if m_bq:
            bq_formal_lines.append({
                "line": lno,
                "label": m_bq.group(1),
                "header": f"{m_bq.group(1)}{m_bq.group(2)}".strip()[:80],
            })
            continue

        m_pf = re_para_formal.match(nc_ln)
        if m_pf:
            non_bq_formal_leadin_lines.append({
                "line": lno,
                "kind": "paragraph_bold",
                "label": m_pf.group(1),
                "header": f"{m_pf.group(1)}{m_pf.group(2)}".strip()[:80],
            })
            continue

        m_hf = re_hdr_formal.match(nc_ln)
        if m_hf:
            non_bq_formal_leadin_lines.append({
                "line": lno,
                "kind": f"heading_h{len(m_hf.group(1))}",
                "label": m_hf.group(2),
                "header": raw_ln.strip()[:80],
            })

    return {
        "file": rel_path,
        "math_spans": len(spans),
        "hard_violations": [asdict(v) for v in hard_violations],
        "hard_violation_count": len(hard_violations),
        "heuristic_warnings": [asdict(w) for w in heuristic_warnings],
        "heuristic_warning_count": len(heuristic_warnings),
        "callout_summary": {
            "blockquote_formal_count": len(bq_formal_lines),
            "non_blockquote_formal_count": len(non_bq_formal_leadin_lines),
            "blockquote_formal_items": bq_formal_lines,
            "non_blockquote_formal_items": non_bq_formal_leadin_lines,
            "proof_body_bold_count": len(proof_body_bold_lines),
            "proof_blockquote_count": len(proof_blockquote_lines),
            "proof_italic_count": len(proof_italic_lines),
            "proof_heading_count": len(proof_heading_lines),
        },
        "markers_summary": {
            "qed_square": qed_square_count,
            "qed_legacy": qed_legacy_count,
            "caret_top": caret_top_count,
            "caret_legacy_T_or_mathsf": caret_legacy_t_count,
        },
    }


def resolve_targets(files_arg: list[str], topic_arg: str | None, scan_all: bool) -> list[Path]:
    """Resolve CLI file paths, --topic IDs, or --all into sorted Markdown Paths."""
    paths: list[Path] = []
    if files_arg:
        for f in files_arg:
            p = Path(f)
            if not p.is_absolute():
                p = ROOT / f
            if not p.exists():
                raise FileNotFoundError(f"File not found: {p}")
            paths.append(p)
    if topic_arg:
        for raw_tok in topic_arg.split(","):
            tok = raw_tok.strip().upper()
            if not tok:
                continue
            num = int(tok[1:]) if tok.startswith("T") else int(tok)
            matches = sorted(SET_2_DIR.glob(f"{num:02d}_*.md"))
            if not matches:
                raise FileNotFoundError(f"No Set 2 article found for topic {raw_tok!r}")
            paths.extend(matches)
    if scan_all:
        paths.extend(sorted(SET_2_DIR.glob("*.md")))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Set 2 articles against the Global Mathematical Notation & Callout Protocol."
    )
    parser.add_argument("files", nargs="*", help="Markdown file path(s) to audit")
    parser.add_argument("--topic", help="Optional Set 2 topic ID(s) (e.g. T08 or T01,T08)")
    parser.add_argument("--all", action="store_true", help="Scan all Set 2 articles")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    targets = resolve_targets(args.files, args.topic, args.all)
    if not targets:
        parser.error("Provide at least one Markdown path, --topic, or --all.")

    reports = [audit_file(p) for p in targets]

    if args.json:
        print(json.dumps(reports[0] if len(reports) == 1 else reports, indent=2, ensure_ascii=False))
    else:
        for rep in reports:
            cs = rep["callout_summary"]
            ms = rep["markers_summary"]
            hv = rep["hard_violations"]
            hw = rep["heuristic_warnings"]
            print(f"=== Notation Protocol Audit: {rep['file']} ===")
            print(
                f"Math spans: {rep['math_spans']} | "
                f"HARD VIOLATIONS: {rep['hard_violation_count']} | "
                f"Heuristic warnings: {rep['heuristic_warning_count']}"
            )
            print(
                f"Callouts: blockquote_formal={cs['blockquote_formal_count']} vs "
                f"non_blockquote_formal={cs['non_blockquote_formal_count']} | "
                f"Proofs: body_bold={cs['proof_body_bold_count']}, "
                f"blockquote={cs['proof_blockquote_count']}, "
                f"italic={cs['proof_italic_count']}, "
                f"heading={cs['proof_heading_count']}"
            )
            print(
                f"Markers: \\square={ms['qed_square']}, legacy_qed={ms['qed_legacy']}, "
                f"^\\top={ms['caret_top']}, ^T/^\\mathsf{{T}}={ms['caret_legacy_T_or_mathsf']}"
            )

            if hv:
                print("\n[HARD VIOLATIONS]")
                for v in hv:
                    print(f"  L{v['line']} [{v['rule']}] token={v['token']!r} | {v['snippet']}")

            if cs["non_blockquote_formal_items"]:
                print("\n[NON-BLOCKQUOTE FORMAL STATEMENT LEAD-INS]")
                for item in cs["non_blockquote_formal_items"]:
                    print(f"  L{item['line']} [{item['kind']}] {item['header']}")

            if hw:
                print("\n[HEURISTIC WARNINGS: UNBOLDED MATRIX INDICATORS (VERIFY IN CONTEXT)]")
                for w in hw:
                    print(f"  L{w['line']} [{w['rule']}] token={w['token']!r} | {w['snippet']}")
            print()

    total_hard = sum(r["hard_violation_count"] for r in reports)
    return 1 if total_hard > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
