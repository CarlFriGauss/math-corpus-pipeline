#!/usr/bin/env python3
"""Deterministic layout & vertical spacing audit for Set 2 Markdown math blocks."""

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

# Reading container is 840px max-width with 28px horizontal padding per side -> 784px inner column.
# KaTeX display math renders at 1.21em relative to ~19px editorial serif prose (~23.0px per KaTeX em).
DEFAULT_WIDTH_BUDGET_PX = 784.0
DEFAULT_PX_PER_EM = 23.0
NESTED_BLOCK_INDENT_PX = 28.0

MULTILINE_ENVS = {"aligned", "gathered", "align", "align*", "gather", "gather*", "cases", "array"}
MATRIX_ENVS = {"bmatrix", "pmatrix", "vmatrix", "Vmatrix", "Bmatrix", "matrix", "smallmatrix"}

BIG_OP_RE = re.compile(
    r"\\(?:sum|int|iint|iiint|oint|prod|coprod|lim|limsup|liminf|bigcup|bigcap|bigoplus|bigotimes)(?![a-zA-Z])"
    r"|\\operatorname\*\s*\{"
)
FRAC_ROOT_RE = re.compile(r"\\(?:frac|dfrac|tfrac|binom|sqrt)(?![a-zA-Z])")
TALL_DELIM_RE = re.compile(r"\\(?:left|Bigl|Bigr|biggl|biggr|Big|bigg)(?![a-zA-Z])")
MATRIX_START_RE = re.compile(r"\\begin\{(?:bmatrix|pmatrix|vmatrix|Vmatrix|Bmatrix|matrix|array|cases)\}")
STEP_TRANSITION_RE = re.compile(r"^\s*(?:&\s*)?\\(?:implies|iff|Longrightarrow|Longleftrightarrow|Rightarrow)(?![a-zA-Z])")

INLINE_TALL_RE = re.compile(
    r"\\displaystyle(?![a-zA-Z])|\\dfrac(?![a-zA-Z])|\\begin\{(?:bmatrix|pmatrix|vmatrix|Vmatrix|Bmatrix|matrix|cases|aligned|gathered|array)\}"
)


@dataclass
class WidthViolation:
    file: str
    start_line: int
    end_line: int
    row_index: int  # 1-based visual line inside block
    estimated_px: float
    estimated_em: float
    budget_px: float
    reason: str
    snippet: str


@dataclass
class SpacingViolation:
    file: str
    line: int
    env: str
    found_spacing: str
    required_pt: int
    reason: str
    row_before: str
    row_after: str


@dataclass
class InlineTallViolation:
    file: str
    line: int
    construct: str
    snippet: str


@dataclass
class IndentedCodeViolation:
    file: str
    start_line: int
    end_line: int
    leading_spaces: int
    base_indent: int
    reason: str
    snippet: str


# ---------------------------------------------------------------------------
# Recursive LaTeX structural tokenizer & visual width estimator
# ---------------------------------------------------------------------------

CMD_WIDTHS_EM: dict[str, float] = {
    # Operators & relations (base symbol width; spacing added by category)
    "implies": 1.45,
    "impliedby": 1.45,
    "iff": 1.75,
    "Longrightarrow": 1.45,
    "Longleftarrow": 1.45,
    "Longleftrightarrow": 1.75,
    "Rightarrow": 1.0,
    "Leftarrow": 1.0,
    "Leftrightarrow": 1.0,
    "to": 0.95,
    "rightarrow": 0.95,
    "leftarrow": 0.95,
    "mapsto": 1.0,
    "le": 0.78,
    "leq": 0.78,
    "ge": 0.78,
    "geq": 0.78,
    "neq": 0.78,
    "ne": 0.78,
    "approx": 0.78,
    "equiv": 0.78,
    "sim": 0.78,
    "simeq": 0.78,
    "cong": 0.78,
    "propto": 0.78,
    "in": 0.68,
    "notin": 0.68,
    "ni": 0.68,
    "subseteq": 0.78,
    "supseteq": 0.78,
    "subset": 0.78,
    "supset": 0.78,
    "subsetneq": 0.78,
    "preceq": 0.78,
    "succeq": 0.78,
    "prec": 0.78,
    "succ": 0.78,
    "parallel": 0.55,
    "perp": 0.78,
    "mid": 0.35,
    # Binary operators
    "pm": 0.78,
    "mp": 0.78,
    "cdot": 0.32,
    "times": 0.75,
    "ast": 0.55,
    "star": 0.55,
    "circledast": 0.85,
    "odot": 0.85,
    "otimes": 0.85,
    "oplus": 0.85,
    "setminus": 0.55,
    "cap": 0.68,
    "cup": 0.68,
    "bmod": 1.85,
    # Dots & punctuation
    "cdots": 1.15,
    "ldots": 1.15,
    "dots": 1.15,
    "vdots": 0.45,
    "ddots": 1.15,
    # Spacing
    ",": 0.17,
    ":": 0.22,
    ">": 0.22,
    ";": 0.28,
    "!": -0.17,
    " ": 0.35,
    "quad": 1.0,
    "qquad": 2.0,
    "thinspace": 0.17,
    "medspace": 0.22,
    "thickspace": 0.28,
    "enspace": 0.5,
    # Delimiters
    "lvert": 0.32,
    "rvert": 0.32,
    "lVert": 0.52,
    "rVert": 0.52,
    "langle": 0.44,
    "rangle": 0.44,
    "lfloor": 0.44,
    "rfloor": 0.44,
    "lceil": 0.44,
    "rceil": 0.44,
    "{": 0.45,
    "}": 0.45,
    "|": 0.52,
    # Symbols & QED
    "infty": 1.0,
    "partial": 0.58,
    "nabla": 0.83,
    "forall": 0.65,
    "exists": 0.65,
    "emptyset": 0.6,
    "varnothing": 0.6,
    "blacksquare": 0.75,
    "square": 0.75,
    "Box": 0.75,
    "degree": 0.4,
    "circ": 0.5,
    "prime": 0.3,
    "top": 0.48,
    "ell": 0.46,
    "hbar": 0.58,
    "Re": 0.78,
    "Im": 0.78,
    # Greek uppercase
    "Gamma": 0.66,
    "Delta": 0.83,
    "Theta": 0.78,
    "Lambda": 0.72,
    "Xi": 0.68,
    "Pi": 0.76,
    "Sigma": 0.74,
    "Upsilon": 0.76,
    "Phi": 0.74,
    "Psi": 0.78,
    "Omega": 0.76,
}

REL_CMDS = {
    "implies", "impliedby", "iff", "Longrightarrow", "Longleftarrow", "Longleftrightarrow",
    "Rightarrow", "Leftarrow", "Leftrightarrow", "to", "rightarrow", "leftarrow", "mapsto",
    "le", "leq", "ge", "geq", "neq", "ne", "approx", "equiv", "sim", "simeq", "cong",
    "propto", "in", "notin", "ni", "subseteq", "supseteq", "subset", "supset", "subsetneq",
    "preceq", "succeq", "prec", "succ", "parallel", "perp",
}
BIN_CMDS = {"pm", "mp", "cdot", "times", "ast", "star", "circledast", "odot", "otimes", "oplus", "setminus", "cap", "cup"}

STD_FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh", "exp", "ln", "log", "lg", "arg", "det", "dim",
    "ker", "gcd", "deg", "hom", "Pr", "mod", "pmod",
}
STACKING_BIG_OPS = {
    "sum": 1.38,
    "prod": 1.38,
    "coprod": 1.38,
    "bigcup": 1.25,
    "bigcap": 1.25,
    "bigoplus": 1.35,
    "bigotimes": 1.35,
    "lim": 1.65,
    "limsup": 3.15,
    "liminf": 3.15,
    "sup": 1.65,
    "inf": 1.65,
    "max": 1.85,
    "min": 1.75,
    "argmax": 3.15,
    "argmin": 3.15,
}
INLINE_LIMIT_BIG_OPS = {
    "int": 0.92,
    "iint": 1.38,
    "iiint": 1.82,
    "oint": 0.98,
}

ZERO_WIDTH_CMDS = {
    "middle", "bigl", "bigr", "bigm", "big",
    "Bigm", "Big", "biggm", "bigg",
    "Biggl", "Biggr", "Biggm", "Bigg", "displaystyle", "textstyle", "scriptstyle",
    "limits", "nolimits", "notag", "nonumber",
}
# Tall resizable delimiter prefixes add slight horizontal glyph width beyond standard ()/[]
CMD_WIDTHS_EM.update({
    "left": 0.14,
    "right": 0.14,
    "Bigl": 0.12,
    "Bigr": 0.12,
    "biggl": 0.18,
    "biggr": 0.18,
})


def find_matching_brace(s: str, open_idx: int) -> int:
    """Return index of matching '}' for '{' at open_idx, or len(s)-1."""
    depth = 0
    i = open_idx
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def find_matching_bracket(s: str, open_idx: int) -> int:
    """Return index of matching ']' for '[' at open_idx, or -1."""
    depth = 0
    i = open_idx
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def find_matching_env_end(s: str, start_after_begin: int, env_name: str) -> tuple[int, int]:
    """Find matching \\end{env_name} starting at start_after_begin. Returns (end_cmd_start, end_cmd_after)."""
    depth = 1
    i = start_after_begin
    n = len(s)
    pat = re.compile(r"\\(begin|end)\{([^}]+)\}")
    while i < n:
        m = pat.search(s, i)
        if not m:
            return n, n
        if m.group(2) == env_name:
            if m.group(1) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return m.start(), m.end()
        i = m.end()
    return n, n


def split_top_level_rows(body: str) -> list[tuple[str, str | None, int]]:
    """Split environment body on top-level \\\\ (respecting braces & nested begin/end).

    Returns list of (row_text, spacing_arg_str_or_None, relative_line_offset_of_break).
    """
    rows: list[tuple[str, str | None, int]] = []
    n = len(body)
    i = 0
    row_start = 0
    brace_depth = 0
    env_depth = 0
    line_offset = 0

    while i < n:
        ch = body[i]
        if ch == "\n":
            line_offset += 1
            i += 1
            continue
        if ch == "{":
            brace_depth += 1
            i += 1
            continue
        if ch == "}":
            brace_depth = max(0, brace_depth - 1)
            i += 1
            continue
        if ch == "\\":
            if body.startswith("\\\\", i) and brace_depth == 0 and env_depth == 0:
                row_txt = body[row_start:i]
                j = i + 2
                while j < n and body[j] in " \t":
                    j += 1
                spacing_arg: str | None = None
                if j < n and body[j] == "[":
                    end_br = find_matching_bracket(body, j)
                    if end_br != -1:
                        spacing_arg = body[j + 1 : end_br].strip()
                        j = end_br + 1
                rows.append((row_txt, spacing_arg, line_offset))
                row_start = j
                i = j
                continue
            m_env = re.match(r"\\(begin|end)\{([^}]+)\}", body[i:])
            if m_env:
                if m_env.group(1) == "begin":
                    env_depth += 1
                else:
                    env_depth = max(0, env_depth - 1)
                i += m_env.end()
                continue
            i += 2
            continue
        i += 1

    tail = body[row_start:]
    rows.append((tail, None, line_offset))
    return rows


def split_top_level_cols(row: str) -> list[str]:
    """Split a single environment row on top-level '&' (respecting braces & nested begin/end)."""
    cols: list[str] = []
    n = len(row)
    i = 0
    start = 0
    brace_depth = 0
    env_depth = 0
    while i < n:
        ch = row[i]
        if ch == "{":
            brace_depth += 1
            i += 1
            continue
        if ch == "}":
            brace_depth = max(0, brace_depth - 1)
            i += 1
            continue
        if ch == "\\":
            m_env = re.match(r"\\(begin|end)\{([^}]+)\}", row[i:])
            if m_env:
                if m_env.group(1) == "begin":
                    env_depth += 1
                else:
                    env_depth = max(0, env_depth - 1)
                i += m_env.end()
                continue
            i += 2
            continue
        if ch == "&" and brace_depth == 0 and env_depth == 0:
            cols.append(row[start:i])
            start = i + 1
        i += 1
    cols.append(row[start:])
    return cols


def parse_script_arg(s: str, idx: int) -> tuple[str, int]:
    """Read a single subscript/superscript argument starting after '_' or '^'."""
    n = len(s)
    while idx < n and s[idx].isspace():
        idx += 1
    if idx >= n:
        return "", idx
    if s[idx] == "{":
        end_b = find_matching_brace(s, idx)
        return s[idx + 1 : end_b], end_b + 1
    if s[idx] == "\\":
        m = re.match(r"\\([a-zA-Z]+\*?|.)", s[idx:])
        if m:
            return m.group(0), idx + m.end()
    return s[idx], idx + 1


def estimate_text_width_em(txt: str) -> float:
    """Estimate width in KaTeX em of prose inside \\text{...} (including inline $...$)."""
    total = 0.0
    i = 0
    n = len(txt)
    while i < n:
        if txt[i] == "$":
            end = txt.find("$", i + 1)
            if end != -1:
                total += estimate_tex_width_em(txt[i + 1 : end])
                i = end + 1
                continue
        ch = txt[i]
        if ch.isspace():
            total += 0.27
        elif ch in "ijl1.,;:'!|":
            total += 0.27
        elif ch in "mwMW":
            total += 0.72
        elif ch.isupper():
            total += 0.58
        else:
            total += 0.45
        i += 1
    return total


def estimate_env_width_em(env_name: str, body: str) -> float:
    """Estimate visual width of an inline/nested matrix, cases, or array environment."""
    if env_name == "array":
        # Strip leading column spec {c|ccc}
        b_strip = body.lstrip()
        if b_strip.startswith("{"):
            end_b = find_matching_brace(b_strip, 0)
            body = b_strip[end_b + 1 :]
    body_clean = re.sub(r"\\hline\b", "", body)
    rows = split_top_level_rows(body_clean)
    grid = [split_top_level_cols(r_txt) for r_txt, _sp, _lo in rows if r_txt.strip()]
    if not grid:
        return 1.0
    ncols = max(len(r) for r in grid)
    col_widths = [0.0] * ncols
    scale = 0.72 if env_name == "smallmatrix" else 1.0
    for r in grid:
        for c_idx, cell in enumerate(r):
            w = estimate_tex_width_em(cell) * scale
            if w > col_widths[c_idx]:
                col_widths[c_idx] = w
    gap = 0.55 if env_name == "smallmatrix" else 1.05
    outer = 0.7 if env_name == "smallmatrix" else 1.15
    if env_name == "cases":
        gap = 1.1
        outer = 1.05
    return sum(col_widths) + max(0, ncols - 1) * gap + outer


def estimate_tex_width_em(tex: str) -> float:
    """Estimate visual horizontal width in KaTeX em for a single visual line of TeX."""
    s = tex.strip()
    if not s:
        return 0.0
    total = 0.0
    i = 0
    n = len(s)

    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue

        # Braced group
        if ch == "{":
            end_b = find_matching_brace(s, i)
            inner_w = estimate_tex_width_em(s[i + 1 : end_b])
            i = end_b + 1
            # Check trailing sub/sup on braced group
            sub_w = 0.0
            sup_w = 0.0
            while i < n and s[i] in "_^":
                kind = s[i]
                arg, i = parse_script_arg(s, i + 1)
                aw = 0.70 * estimate_tex_width_em(arg)
                if kind == "_":
                    sub_w = max(sub_w, aw)
                else:
                    sup_w = max(sup_w, aw)
            total += inner_w + max(sub_w, sup_w)
            continue

        # Orphan sub/sup
        if ch in "_^":
            arg, i = parse_script_arg(s, i + 1)
            total += 0.70 * estimate_tex_width_em(arg)
            continue

        # TeX command
        if ch == "\\":
            if i + 1 >= n:
                break
            nxt = s[i + 1]
            # Single non-alpha control symbol
            if not nxt.isalpha():
                total += CMD_WIDTHS_EM.get(nxt, 0.45)
                i += 2
                continue

            m_cmd = re.match(r"\\([a-zA-Z]+\*?)", s[i:])
            assert m_cmd is not None
            cmd = m_cmd.group(1)
            i += m_cmd.end()

            if cmd in ZERO_WIDTH_CMDS:
                continue

            # Environment inside line (e.g. bmatrix, cases, smallmatrix, aligned, substack)
            if cmd == "begin":
                while i < n and s[i].isspace():
                    i += 1
                if i < n and s[i] == "{":
                    end_b = find_matching_brace(s, i)
                    env_name = s[i + 1 : end_b].strip()
                    i = end_b + 1
                    end_pos, after_end = find_matching_env_end(s, i, env_name)
                    env_body = s[i:end_pos]
                    total += estimate_env_width_em(env_name, env_body)
                    i = after_end
                continue

            # Skip \end{...} if unbalanced fragment
            if cmd == "end":
                while i < n and s[i].isspace():
                    i += 1
                if i < n and s[i] == "{":
                    end_b = find_matching_brace(s, i)
                    i = end_b + 1
                continue

            # Two-arg fraction / binomial
            if cmd in {"frac", "dfrac", "tfrac", "binom"}:
                num, i = parse_script_arg(s, i)
                den, i = parse_script_arg(s, i)
                nw = estimate_tex_width_em(num)
                dw = estimate_tex_width_em(den)
                if cmd == "tfrac":
                    total += 0.72 * max(nw, dw) + 0.25
                elif cmd == "binom":
                    total += max(nw, dw) + 0.95
                else:
                    total += max(nw, dw) + 0.30
                continue

            # Root \sqrt[opt]{arg}
            if cmd == "sqrt":
                while i < n and s[i].isspace():
                    i += 1
                opt_w = 0.0
                if i < n and s[i] == "[":
                    end_br = find_matching_bracket(s, i)
                    if end_br != -1:
                        opt_w = 0.45 * estimate_tex_width_em(s[i + 1 : end_br])
                        i = end_br + 1
                arg, i = parse_script_arg(s, i)
                total += max(0.85, 0.65 + opt_w) + estimate_tex_width_em(arg)
                continue

            # Text wrappers
            if cmd in {"text", "textrm", "textit", "textbf", "textsf", "texttt", "mathrm", "mathsf"}:
                arg, i = parse_script_arg(s, i)
                total += estimate_text_width_em(arg)
                continue

            # \operatorname{foo} or \operatorname*{foo}
            if cmd in {"operatorname", "operatorname*"}:
                arg, i = parse_script_arg(s, i)
                base_w = estimate_text_width_em(arg) + 0.22
                if cmd == "operatorname*":
                    sub_w = 0.0
                    sup_w = 0.0
                    while i < n and (s[i] in "_^" or s[i].isspace()):
                        if s[i].isspace():
                            i += 1
                            continue
                        kind = s[i]
                        sc, i = parse_script_arg(s, i + 1)
                        sw = 0.72 * estimate_tex_width_em(sc)
                        if kind == "_":
                            sub_w = max(sub_w, sw)
                        else:
                            sup_w = max(sup_w, sw)
                    total += max(base_w, sub_w, sup_w) + 0.20
                else:
                    total += base_w
                continue

            # \tag{...} sits at right margin; reserve space
            if cmd == "tag":
                arg, i = parse_script_arg(s, i)
                total += max(2.8, estimate_text_width_em(arg) + 1.4)
                continue

            # \substack{a \\ b}
            if cmd == "substack":
                arg, i = parse_script_arg(s, i)
                sub_rows = split_top_level_rows(arg)
                total += max((estimate_tex_width_em(r_t) for r_t, _, _ in sub_rows), default=0.0)
                continue

            # \xrightarrow[below]{above}
            if cmd in {"xrightarrow", "xleftarrow"}:
                below = ""
                above = ""
                while i < n and s[i].isspace():
                    i += 1
                if i < n and s[i] == "[":
                    end_br = find_matching_bracket(s, i)
                    if end_br != -1:
                        below = s[i + 1 : end_br]
                        i = end_br + 1
                above, i = parse_script_arg(s, i)
                total += max(1.8, 0.72 * estimate_tex_width_em(above), 0.72 * estimate_tex_width_em(below)) + 0.65
                continue

            # Stacked 2-arg decorations (\stackrel, \overset, \underset, \underbrace, \overbrace)
            if cmd in {"stackrel", "overset", "underset"}:
                top_or_bot, i = parse_script_arg(s, i)
                base, i = parse_script_arg(s, i)
                total += max(0.75 * estimate_tex_width_em(top_or_bot), estimate_tex_width_em(base)) + 0.25
                continue

            if cmd in {"underbrace", "overbrace"}:
                arg, i = parse_script_arg(s, i)
                w_base = estimate_tex_width_em(arg)
                w_sc = 0.0
                while i < n and (s[i] in "_^" or s[i].isspace()):
                    if s[i].isspace():
                        i += 1
                        continue
                    sc, i = parse_script_arg(s, i + 1)
                    w_sc = max(w_sc, 0.72 * estimate_tex_width_em(sc))
                total += max(w_base, w_sc)
                continue

            # Font / accent / box wrappers taking 1 arg
            if cmd in {
                "mathbf", "boldsymbol", "mathbb", "mathcal", "mathscr", "mathfrak", "mathit",
                "overline", "underline", "widehat", "widetilde", "hat", "tilde", "bar", "vec",
                "dot", "ddot", "check", "boxed", "phantom",
            }:
                arg, i = parse_script_arg(s, i)
                mult = 1.07 if cmd in {"mathbf", "boldsymbol", "mathbb", "mathcal"} else 1.0
                pad = 0.45 if cmd == "boxed" else 0.0
                total += estimate_tex_width_em(arg) * mult + pad
                continue

            # Big stacking operators (\sum, \prod, \lim, ...)
            if cmd in STACKING_BIG_OPS:
                base_w = STACKING_BIG_OPS[cmd]
                sub_w = 0.0
                sup_w = 0.0
                while i < n and (s[i] in "_^" or s[i].isspace()):
                    if s[i].isspace():
                        i += 1
                        continue
                    kind = s[i]
                    sc, i = parse_script_arg(s, i + 1)
                    if "\\substack" in sc:
                        m_st = re.search(r"\\substack\{", sc)
                        if m_st:
                            eb = find_matching_brace(sc, m_st.end() - 1)
                            sub_rows = split_top_level_rows(sc[m_st.end() : eb])
                            sw = 0.72 * max((estimate_tex_width_em(r_t) for r_t, _, _ in sub_rows), default=0.0)
                        else:
                            sw = 0.72 * estimate_tex_width_em(sc)
                    else:
                        sw = 0.72 * estimate_tex_width_em(sc)
                    if kind == "_":
                        sub_w = max(sub_w, sw)
                    else:
                        sup_w = max(sup_w, sw)
                total += max(base_w, sub_w, sup_w) + 0.25
                continue

            # Integrals (\int, \iint, \oint) - limits sit to the side in KaTeX display mode
            if cmd in INLINE_LIMIT_BIG_OPS:
                base_w = INLINE_LIMIT_BIG_OPS[cmd]
                sub_w = 0.0
                sup_w = 0.0
                while i < n and (s[i] in "_^" or s[i].isspace()):
                    if s[i].isspace():
                        i += 1
                        continue
                    kind = s[i]
                    sc, i = parse_script_arg(s, i + 1)
                    sw = 0.72 * estimate_tex_width_em(sc)
                    if kind == "_":
                        sub_w = max(sub_w, sw)
                    else:
                        sup_w = max(sup_w, sw)
                total += base_w + max(sub_w, sup_w) + 0.20
                continue

            # Named standard functions
            if cmd in STD_FUNCTIONS:
                if cmd == "pmod":
                    arg, i = parse_script_arg(s, i)
                    total += 1.0 + 1.8 + estimate_tex_width_em(arg) + 0.5
                else:
                    total += 0.48 * len(cmd) + 0.16
                continue

            # Known commands/relations/binaries
            w = CMD_WIDTHS_EM.get(cmd, 0.60)
            if cmd in REL_CMDS:
                w += 0.55
            elif cmd in BIN_CMDS:
                w += 0.44
            total += w
            continue

        # Ordinary characters
        if ch == "=":
            total += 0.78 + 0.55
        elif ch in "<>":
            total += 0.78 + 0.55
        elif ch in "+-":
            total += 0.72 + 0.44
        elif ch in ",;":
            total += 0.36
        elif ch == ":":
            if i + 1 < n and s[i + 1] == "=":
                total += 1.55
                i += 2
                continue
            total += 0.45
        elif ch in "()[]":
            total += 0.39
        elif ch in "|/":
            total += 0.45
        elif ch == "'":
            total += 0.28
        elif ch in "MW":
            total += 0.85
        elif ch in "ijl1.":
            total += 0.34
        elif ch.isupper():
            total += 0.68
        else:
            total += 0.53
        i += 1

        # Trailing sub/sup on ordinary atom
        sub_w = 0.0
        sup_w = 0.0
        while i < n and s[i] in "_^":
            kind = s[i]
            sc, i = parse_script_arg(s, i + 1)
            sw = 0.70 * estimate_tex_width_em(sc)
            if kind == "_":
                sub_w = max(sub_w, sw)
            else:
                sup_w = max(sup_w, sw)
        total += max(sub_w, sup_w)

    return max(0.0, total)


# ---------------------------------------------------------------------------
# Row spacing & display block auditing
# ---------------------------------------------------------------------------

def parse_pt_value(spacing_arg: str | None) -> float | None:
    """Parse spacing argument like '6pt', '10pt', '0.5em' into points (1em ≈ 12pt)."""
    if not spacing_arg:
        return None
    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*(pt|em|ex|px|mm|cm)\s*$", spacing_arg, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "pt":
        return val
    if unit == "em":
        return val * 12.0
    if unit == "ex":
        return val * 5.5
    if unit == "px":
        return val * 0.75
    if unit == "mm":
        return val * 2.835
    if unit == "cm":
        return val * 28.35
    return None


def has_nested_fraction(row: str) -> bool:
    """Return True if a fraction argument contains another fraction or stacked big operator."""
    for m in re.finditer(r"\\(?:frac|dfrac|tfrac)(?![a-zA-Z])", row):
        idx = m.end()
        arg1, idx2 = parse_script_arg(row, idx)
        arg2, _ = parse_script_arg(row, idx2)
        combined = arg1 + " " + arg2
        if re.search(r"\\(?:frac|dfrac|tfrac|sum|int|prod|lim)(?![a-zA-Z])", combined):
            return True
    return False


def classify_row_spacing_requirement(env_name: str, row_before: str, row_after: str) -> tuple[int, str]:
    """Return (required_pt, reason) for a \\\\ boundary between row_before and row_after."""
    adj = row_before + "\n" + row_after
    # Tier 3: 10pt for big ops, nested fractions, embedded matrices, or logical step transitions
    if BIG_OP_RE.search(adj):
        op = BIG_OP_RE.search(adj).group(0)
        return 10, f"adjacent row contains stacked/limit operator ({op})"
    if has_nested_fraction(row_before) or has_nested_fraction(row_after):
        return 10, "adjacent row contains nested fraction"
    if MATRIX_START_RE.search(adj):
        mat = MATRIX_START_RE.search(adj).group(0)
        return 10, f"adjacent row contains embedded environment ({mat})"
    if STEP_TRANSITION_RE.match(row_after):
        return 10, "logical step transition (\\implies / \\iff)"

    # Tier 2: 6pt for fractions, roots, tall delimiters, or cases rows
    if FRAC_ROOT_RE.search(adj):
        cmd = FRAC_ROOT_RE.search(adj).group(0)
        return 6, f"adjacent row contains {cmd}"
    if TALL_DELIM_RE.search(adj):
        cmd = TALL_DELIM_RE.search(adj).group(0)
        return 6, f"adjacent row contains tall delimiter ({cmd})"
    if env_name == "cases":
        return 6, "rows inside cases environment"

    return 0, ""


def scan_env_spacing(
    tex: str,
    base_line: int,
    rel_path: str,
    violations: list[SpacingViolation],
) -> None:
    """Recursively scan aligned/gathered/cases/array environments for missing/small \\\\ spacing."""
    i = 0
    n = len(tex)
    pat = re.compile(r"\\begin\{([^}]+)\}")
    while i < n:
        m = pat.search(tex, i)
        if not m:
            break
        env_name = m.group(1).strip()
        env_start_offset = tex[: m.start()].count("\n")
        after_begin = m.end()
        end_pos, after_end = find_matching_env_end(tex, after_begin, env_name)
        env_body = tex[after_begin:end_pos]

        if env_name in MULTILINE_ENVS:
            body_for_rows = env_body
            if env_name == "array":
                b_strip = env_body.lstrip()
                if b_strip.startswith("{"):
                    eb = find_matching_brace(b_strip, 0)
                    body_for_rows = env_body[len(env_body) - len(b_strip) + eb + 1 :]

            rows = split_top_level_rows(body_for_rows)
            body_line_offset = tex[: after_begin + (len(env_body) - len(body_for_rows))].count("\n")
            for idx in range(len(rows) - 1):
                r_before, sp_arg, br_line_off = rows[idx]
                r_after, _, _ = rows[idx + 1]
                # Skip trailing empty row after a final \\
                if not r_after.strip():
                    continue
                req_pt, reason = classify_row_spacing_requirement(env_name, r_before, r_after)
                if req_pt > 0:
                    found_pt = parse_pt_value(sp_arg)
                    if sp_arg is None:
                        violations.append(
                            SpacingViolation(
                                file=rel_path,
                                line=base_line + body_line_offset + br_line_off,
                                env=env_name,
                                found_spacing="none",
                                required_pt=req_pt,
                                reason=f"missing [{req_pt}pt] spacing ({reason})",
                                row_before=r_before.strip()[:80],
                                row_after=r_after.strip()[:80],
                            )
                        )
                    elif found_pt is None or found_pt < req_pt - 1e-6:
                        violations.append(
                            SpacingViolation(
                                file=rel_path,
                                line=base_line + body_line_offset + br_line_off,
                                env=env_name,
                                found_spacing=f"[{sp_arg}]",
                                required_pt=req_pt,
                                reason=f"spacing [{sp_arg}] < [{req_pt}pt] ({reason})",
                                row_before=r_before.strip()[:80],
                                row_after=r_after.strip()[:80],
                            )
                        )

        # Recurse inside env_body for nested aligned/cases/array
        scan_env_spacing(env_body, base_line + env_start_offset + tex[m.start() : after_begin].count("\n"), rel_path, violations)
        i = after_end


def extract_outer_visual_lines(block_tex: str) -> list[tuple[int, str, float]]:
    """Return list of (1-based local row index, snippet, estimated_em_width) for a $$...$$ block."""
    s = block_tex.strip()
    if not s:
        return []

    # Check if block is purely a single top-level aligned/gathered/align/gather (plus optional \tag / punct)
    m_beg = re.match(r"^(?:\\boxed\{\s*)?\\begin\{(aligned|gathered|align\*?|gather\*?)\}", s)
    if m_beg:
        env_name = m_beg.group(1)
        after_beg = m_beg.end()
        end_pos, after_end = find_matching_env_end(s, after_beg, env_name)
        trailing = s[after_end:].strip()
        # Strip closing brace of \boxed{...} if wrapped
        if s.startswith("\\boxed{") and trailing.startswith("}"):
            trailing = trailing[1:].strip()
        # Check if trailing is only punctuation, spacing, and/or \tag{...}
        trailing_no_tag = re.sub(r"\\tag\{[^}]*\}", "", trailing).strip()
        if trailing_no_tag in {"", ".", ",", ";"}:
            body = s[after_beg:end_pos]
            rows = split_top_level_rows(body)
            nonempty_rows = [(r_t, sp, lo) for r_t, sp, lo in rows if r_t.strip()]
            tag_extra = 3.2 if "\\tag{" in trailing else 0.0
            box_extra = 0.5 if s.startswith("\\boxed{") else 0.0

            if env_name in {"aligned", "align", "align*"}:
                grid = [split_top_level_cols(r_t) for r_t, _, _ in nonempty_rows]
                ncols = max((len(g) for g in grid), default=1)
                col_widths_per_row: list[list[float]] = [
                    [estimate_tex_width_em(cell) for cell in g] for g in grid
                ]
                max_col = [0.0] * ncols
                for r_w in col_widths_per_row:
                    for ci, cw in enumerate(r_w):
                        if cw > max_col[ci]:
                            max_col[ci] = cw

                results: list[tuple[int, str, float]] = []
                for idx, ((r_t, _, _), r_w) in enumerate(zip(nonempty_rows, col_widths_per_row), 1):
                    if len(r_w) == 1:
                        w = r_w[0]
                    else:
                        # Last populated column starts at sum of preceding max column widths
                        last_idx = len(r_w) - 1
                        pair_gaps = (last_idx // 2) * 1.4
                        w = sum(max_col[:last_idx]) + r_w[last_idx] + pair_gaps
                    results.append((idx, r_t.strip(), w + tag_extra + box_extra))
                return results
            else:
                # gathered / gather
                results = []
                for idx, (r_t, _, _) in enumerate(nonempty_rows, 1):
                    w = estimate_tex_width_em(r_t) + tag_extra + box_extra
                    results.append((idx, r_t.strip(), w))
                return results

    # Otherwise treat block (or top-level \\ lines if any) as single visual line(s)
    top_rows = split_top_level_rows(s)
    if len(top_rows) > 1:
        return [
            (idx, r_t.strip(), estimate_tex_width_em(r_t))
            for idx, (r_t, _, _) in enumerate(top_rows, 1)
            if r_t.strip()
        ]
    single = " ".join(ln.strip() for ln in s.splitlines())
    return [(1, single, estimate_tex_width_em(single))]


# ---------------------------------------------------------------------------
# Markdown scanner
# ---------------------------------------------------------------------------

def is_table_line(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("|") or bool(re.match(r"^\|.*\|$", s))


LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)(.*)$")
LIST_EMPTY_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s*$")


def expand_tabs(line: str) -> str:
    """Expand tabs to 4-space tabstops matching Pandoc/CommonMark column rules."""
    if "\t" not in line:
        return line
    out: list[str] = []
    col = 0
    for ch in line:
        if ch == "\t":
            nxt = ((col // 4) + 1) * 4
            out.append(" " * (nxt - col))
            col = nxt
        else:
            out.append(ch)
            col += 1
    return "".join(out)


def scan_indented_code_blocks(
    lines: list[str],
    rel_path: str,
) -> list[IndentedCodeViolation]:
    """Flag non-fenced indented blocks (>=4 spaces outside a properly continued list item) containing math."""
    violations: list[IndentedCodeViolation] = []

    def scan_segment(seg_lines: list[tuple[int, str]]) -> None:
        list_stack: list[tuple[int, int]] = []  # (marker_indent, content_indent)
        in_fence = False
        fence_char = "`"
        fence_len = 3
        in_indented_code = False
        code_start = 0
        code_end = 0
        code_lead = 0
        code_base = 0
        code_buf: list[str] = []
        saw_blank = True
        prev_kind = "start"  # start | para | list | math | hard
        in_display_math = False
        in_table = False

        def flush_code() -> None:
            nonlocal in_indented_code, code_buf
            if in_indented_code and code_buf:
                txt = "\n".join(code_buf)
                if "$" in txt or "\\" in txt:
                    reason = (
                        f"indented {code_lead} spaces >= {code_base + 4} "
                        + (
                            "(over-indented relative to parent list item)"
                            if code_base > 0
                            else "(Pandoc parses as <pre><code> outside fenced block or list)"
                        )
                    )
                    violations.append(
                        IndentedCodeViolation(
                            file=rel_path,
                            start_line=code_start,
                            end_line=code_end,
                            leading_spaces=code_lead,
                            base_indent=code_base,
                            reason=reason,
                            snippet=txt.strip().splitlines()[0][:120],
                        )
                    )
            in_indented_code = False
            code_buf = []

        idx = 0
        while idx < len(seg_lines):
            lno, raw = seg_lines[idx]
            exp = expand_tabs(raw)
            stripped = exp.strip()
            base_indent = list_stack[-1][1] if list_stack else 0

            if in_fence:
                if re.match(rf"^\s{{0,{base_indent + 3}}}{re.escape(fence_char)}{{{fence_len},}}\s*$", exp):
                    in_fence = False
                    prev_kind = "hard"
                    saw_blank = False
                idx += 1
                continue

            if not stripped:
                if in_display_math:
                    in_display_math = False
                in_table = False
                saw_blank = True
                idx += 1
                continue

            ind = len(exp) - len(exp.lstrip(" "))

            if in_indented_code:
                if ind >= code_base + 4:
                    code_end = lno
                    code_buf.append(exp[code_base + 4 :])
                    saw_blank = False
                    idx += 1
                    continue
                flush_code()

            if in_display_math:
                if "$$" in stripped:
                    in_display_math = False
                    prev_kind = "math"
                saw_blank = False
                idx += 1
                continue

            # Start of an indented code block: >= base_indent + 4 after blank line or hard-ended block
            if ind >= base_indent + 4 and (saw_blank or prev_kind == "hard"):
                in_indented_code = True
                code_start = lno
                code_end = lno
                code_lead = ind
                code_base = base_indent
                code_buf = [exp[base_indent + 4 :]]
                saw_blank = False
                in_table = False
                idx += 1
                continue

            # Fenced code block start (< base_indent + 4)
            m_f = re.match(r"^(\s*)(`{3,}|~{3,})", exp)
            if m_f and len(m_f.group(1)) < base_indent + 4:
                if saw_blank:
                    while list_stack and len(m_f.group(1)) < list_stack[-1][1]:
                        list_stack.pop()
                in_fence = True
                fence_char = m_f.group(2)[0]
                fence_len = len(m_f.group(2))
                saw_blank = False
                in_table = False
                idx += 1
                continue

            # Nested blockquote (< base_indent + 4)
            if stripped.startswith(">") and ind < base_indent + 4:
                if saw_blank:
                    while list_stack and ind < list_stack[-1][1]:
                        list_stack.pop()
                bq_sub: list[tuple[int, str]] = []
                while idx < len(seg_lines):
                    blno, braw = seg_lines[idx]
                    bexp = expand_tabs(braw)
                    bstripped = bexp.strip()
                    if not bstripped:
                        break
                    bind = len(bexp) - len(bexp.lstrip(" "))
                    if bstripped.startswith(">") and bind < (list_stack[-1][1] if list_stack else 0) + 4:
                        after_gt = re.sub(r"^\s*>\s?", "", bexp, count=1)
                        bq_sub.append((blno, after_gt))
                        idx += 1
                    elif not saw_blank and bind < 4:
                        bq_sub.append((blno, bexp))
                        idx += 1
                    else:
                        break
                scan_segment(bq_sub)
                saw_blank = False
                prev_kind = "para"
                in_table = False
                continue

            # ATX heading or horizontal rule (< base_indent + 4)
            if (re.match(r"^\s*#{1,6}(?:\s|$)", exp) or re.match(r"^\s*([-*_])(?:\s*\1){2,}\s*$", exp)) and ind < base_indent + 4:
                while list_stack and ind < list_stack[-1][1]:
                    list_stack.pop()
                saw_blank = False
                prev_kind = "hard"
                in_table = False
                idx += 1
                continue

            # List item (< base_indent + 4)
            m_li = LIST_ITEM_RE.match(exp)
            m_le = LIST_EMPTY_RE.match(exp) if not m_li else None
            if (m_li or m_le) and ind < base_indent + 4:
                if m_li:
                    m_ind = len(m_li.group(1))
                    sp_after = len(m_li.group(3))
                    if sp_after >= 5:
                        c_ind = m_ind + len(m_li.group(2)) + 1
                        body_txt = m_li.group(4)
                        if "$" in body_txt or "\\" in body_txt:
                            violations.append(
                                IndentedCodeViolation(
                                    file=rel_path,
                                    start_line=lno,
                                    end_line=lno,
                                    leading_spaces=sp_after - 1,
                                    base_indent=c_ind,
                                    reason=f"list item body has {sp_after} spaces after marker (Pandoc parses as <pre><code>)",
                                    snippet=body_txt.strip()[:120],
                                )
                            )
                    else:
                        c_ind = m_ind + len(m_li.group(2)) + sp_after
                else:
                    assert m_le is not None
                    m_ind = len(m_le.group(1))
                    c_ind = m_ind + len(m_le.group(2)) + 1

                if m_ind >= base_indent:
                    list_stack.append((m_ind, c_ind))
                else:
                    while list_stack and m_ind < list_stack[-1][0]:
                        list_stack.pop()
                    if list_stack and m_ind == list_stack[-1][0]:
                        list_stack[-1] = (m_ind, c_ind)
                    elif not list_stack or m_ind >= list_stack[-1][1]:
                        list_stack.append((m_ind, c_ind))
                saw_blank = False
                prev_kind = "list"
                in_table = False
                idx += 1
                continue

            # Regular block line: pop list levels if blank line preceded a less-indented line
            if saw_blank:
                while list_stack and ind < list_stack[-1][1]:
                    list_stack.pop()

            # GFM pipe table
            if "|" in stripped and not in_table and idx + 1 < len(seg_lines):
                nxt_exp = expand_tabs(seg_lines[idx + 1][1]).strip()
                if "|" in nxt_exp and re.match(r"^\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$", nxt_exp):
                    in_table = True
                    saw_blank = False
                    prev_kind = "hard"
                    idx += 1
                    continue
            if in_table:
                if "|" in stripped:
                    saw_blank = False
                    prev_kind = "hard"
                    idx += 1
                    continue
                in_table = False

            # Display math $$...$$
            if stripped.startswith("$$"):
                rest = stripped[2:]
                if "$$" in rest:
                    prev_kind = "math"
                else:
                    in_display_math = True
                    prev_kind = "math"
                saw_blank = False
                idx += 1
                continue

            saw_blank = False
            prev_kind = "para"
            idx += 1

        flush_code()

    scan_segment([(i + 1, ln) for i, ln in enumerate(lines)])
    return violations


def audit_file(
    path: Path,
    width_budget_px: float = DEFAULT_WIDTH_BUDGET_PX,
    px_per_em: float = DEFAULT_PX_PER_EM,
) -> dict[str, Any]:
    """Scan a single Markdown file for display-width, row-spacing, and inline-tall issues."""
    rel_path = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    n = len(lines)

    width_violations: list[WidthViolation] = []
    spacing_violations: list[SpacingViolation] = []
    inline_tall_violations: list[InlineTallViolation] = []

    display_blocks_count = 0
    multiline_breaks_count = 0

    in_fence = False
    fence_char = "`"
    fence_len = 3
    i = 0

    while i < n:
        ln = lines[i]
        m_fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", ln)
        if not in_fence and m_fence:
            in_fence = True
            fence_char = m_fence.group(1)[0]
            fence_len = len(m_fence.group(1))
            i += 1
            continue
        if in_fence:
            if re.match(rf"^\s{{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$", ln):
                in_fence = False
            i += 1
            continue

        # Detect display math block $$ ... $$ (allowing blockquote prefix > or list indent)
        bq_depth = len(re.findall(r">", re.match(r"^\s*(?:>\s*)*", ln).group(0)))
        lead_spaces = len(ln) - len(ln.lstrip(" "))
        is_list_nested = bq_depth == 0 and lead_spaces >= 2
        if not is_list_nested and bq_depth == 0 and i >= 2:
            # Also check if immediately preceded by a numbered/bullet list item without blank-line exit
            prev_nonblank = i - 1
            while prev_nonblank >= 0 and not lines[prev_nonblank].strip():
                prev_nonblank -= 1
            if prev_nonblank >= 0 and re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", lines[prev_nonblank]):
                # Check if blank line separated list from top-level block vs continuing inside list
                # In Markdown, unindented $$ after a blank line after a list item still stays inside list only if indented,
                # unless it's a tight continuation; keep top-level unindented $$ at full 784px unless explicitly indented.
                pass

        stripped_bq = re.sub(r"^\s*(?:>\s*)*", "", ln)
        if stripped_bq.startswith("$$"):
            display_blocks_count += 1
            start_line = i + 1
            nest_levels = min(2, bq_depth + (1 if is_list_nested else 0))
            eff_budget_px = max(480.0, width_budget_px - nest_levels * NESTED_BLOCK_INDENT_PX)
            rest = stripped_bq[2:]
            # Single-line $$ ... $$
            if "$$" in rest:
                idx_c = rest.rfind("$$")
                blk_tex = rest[:idx_c].strip()
                end_line = start_line
                content_start_line = start_line
                i += 1
            else:
                blk_lines = [rest] if rest.strip() else []
                content_start_line = start_line + (0 if rest.strip() else 1)
                j = i + 1
                while j < n:
                    cur_bq = re.sub(r"^\s*(?:>\s*)*", "", lines[j])
                    if "$$" in cur_bq:
                        before, _, _ = cur_bq.partition("$$")
                        if before.strip():
                            blk_lines.append(before.rstrip())
                        j += 1
                        break
                    blk_lines.append(cur_bq)
                    j += 1
                end_line = j
                blk_tex = "\n".join(blk_lines)
                i = j

            # 1. Width check per visual row
            visual_rows = extract_outer_visual_lines(blk_tex)
            for row_idx, snippet, em_w in visual_rows:
                px_w = em_w * px_per_em
                if px_w > eff_budget_px:
                    rel_ops = len(re.findall(r"(?:(?<!\\)=|\\(?:le|leq|ge|geq|implies|iff|approx|equiv|xrightarrow)(?![a-zA-Z]))", snippet))
                    reason = (
                        f"multi-step chain ({rel_ops} relation/implication operators) exceeds {eff_budget_px:.0f}px"
                        if rel_ops >= 2
                        else f"wide single line exceeds {eff_budget_px:.0f}px"
                    )
                    width_violations.append(
                        WidthViolation(
                            file=rel_path,
                            start_line=start_line,
                            end_line=end_line,
                            row_index=row_idx,
                            estimated_px=round(px_w, 1),
                            estimated_em=round(em_w, 2),
                            budget_px=eff_budget_px,
                            reason=reason,
                            snippet=snippet[:130],
                        )
                    )

            # 2. Row spacing check inside aligned/gathered/cases/array
            multiline_breaks_count += len(re.findall(r"\\\\", blk_tex))
            scan_env_spacing(blk_tex, content_start_line, rel_path, spacing_violations)
            continue

        # 3. Inline tall constructs in prose (exclude pipe tables and inline code)
        if "$" in ln and not is_table_line(ln):
            masked = re.sub(r"`[^`\n]+`", "", ln)
            # Find single-$ spans
            for m_in in re.finditer(r"(?<!\\)\$(?!\$)([^\n$]+?)(?<!\\)\$", masked):
                expr = m_in.group(1)
                m_tall = INLINE_TALL_RE.search(expr)
                if m_tall:
                    inline_tall_violations.append(
                        InlineTallViolation(
                            file=rel_path,
                            line=i + 1,
                            construct=m_tall.group(0),
                            snippet=expr[:110],
                        )
                    )

        i += 1

    indented_code_violations = scan_indented_code_blocks(lines, rel_path)

    return {
        "file": rel_path,
        "display_blocks": display_blocks_count,
        "width_budget_px": width_budget_px,
        "px_per_em": px_per_em,
        "width_violations": [asdict(v) for v in width_violations],
        "spacing_violations": [asdict(v) for v in spacing_violations],
        "inline_tall_violations": [asdict(v) for v in inline_tall_violations],
        "indented_code_violations": [asdict(v) for v in indented_code_violations],
        "total_violations": (
            len(width_violations)
            + len(spacing_violations)
            + len(inline_tall_violations)
            + len(indented_code_violations)
        ),
    }


def resolve_targets(files_arg: list[str], topic_arg: str | None, scan_all: bool) -> list[Path]:
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
    parser = argparse.ArgumentParser(description="Audit Set 2 display math width & vertical row spacing.")
    parser.add_argument("files", nargs="*", help="Markdown file path(s) to audit")
    parser.add_argument("--topic", help="Optional Set 2 topic ID(s) (e.g. T08 or T01,T08)")
    parser.add_argument("--all", action="store_true", help="Scan all Set 2 articles")
    parser.add_argument("--width-budget", type=float, default=DEFAULT_WIDTH_BUDGET_PX, help="Max inner reading width in px (default: 784)")
    parser.add_argument("--px-per-em", type=float, default=DEFAULT_PX_PER_EM, help="KaTeX px per em calibration (default: 22.0)")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    targets = resolve_targets(args.files, args.topic, args.all)
    if not targets:
        parser.error("Provide at least one Markdown path, --topic, or --all.")

    reports = [audit_file(p, width_budget_px=args.width_budget, px_per_em=args.px_per_em) for p in targets]

    if args.json:
        print(json.dumps(reports[0] if len(reports) == 1 else reports, indent=2, ensure_ascii=False))
    else:
        for rep in reports:
            wv = rep["width_violations"]
            sv = rep["spacing_violations"]
            iv = rep["inline_tall_violations"]
            icv = rep["indented_code_violations"]
            print(f"=== Math Layout Audit: {rep['file']} ===")
            print(
                f"Display blocks: {rep['display_blocks']} | "
                f"Width (> {rep['width_budget_px']:.0f}px): {len(wv)} | "
                f"Row spacing (\\\\): {len(sv)} | "
                f"Inline tall prose: {len(iv)} | "
                f"Indented code math: {len(icv)} | "
                f"TOTAL VIOLATIONS: {rep['total_violations']}"
            )
            if wv:
                print("\n[WIDTH VIOLATIONS]")
                for v in wv:
                    print(
                        f"  L{v['start_line']}-L{v['end_line']} (row {v['row_index']}): "
                        f"~{v['estimated_px']:.0f}px ({v['estimated_em']:.1f}em > {v['budget_px']:.0f}px) | {v['reason']}"
                    )
                    print(f"    {v['snippet']}")
            if sv:
                print("\n[ROW SPACING VIOLATIONS]")
                for v in sv:
                    print(
                        f"  L{v['line']} ({v['env']}): found={v['found_spacing']}, "
                        f"required>=[{v['required_pt']}pt] | {v['reason']}"
                    )
                    print(f"    before: {v['row_before']}")
                    print(f"    after:  {v['row_after']}")
            if iv:
                print("\n[INLINE TALL CONSTRUCTS IN PROSE]")
                for v in iv:
                    print(f"  L{v['line']}: {v['construct']} in ${v['snippet']}$")
            if icv:
                print("\n[INDENTED CODE BLOCKS CONTAINING MATH]")
                for v in icv:
                    print(
                        f"  L{v['start_line']}-L{v['end_line']}: "
                        f"{v['reason']} | {v['snippet']}"
                    )
            print()

    total = sum(r["total_violations"] for r in reports)
    return 1 if total > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
