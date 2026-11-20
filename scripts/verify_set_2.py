#!/usr/bin/env python3
"""Verify Set 2 standalone corrected articles in output/set_2_corrected/."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SET_1_DIR = ROOT / "output" / "set_1_faithful"
SET_2_DIR = ROOT / "output" / "set_2_corrected"

FORBIDDEN_META_PATTERNS = [
    (r"\bset\s*[12]\b", "explicit Set 1 / Set 2 reference"),
    (r"\b(?:in|from)\s+the\s+(?:previous|earlier|original)\s+(?:version|draft|article|notes?)\b", "meta-reference to earlier draft/notes"),
    (r"\buser(?:'s|s')\s+notes?\b", "meta-reference to user's notes"),
    (r"\bto\s+correct\s+the\s+(?:misconception|mistake|error|flaw)\b", "critique meta-language"),
    (r"\b(?:was|were)\s+(?:omitted|wrong|incorrect|flawed)\s+(?:earlier|before|previously)\b", "critique meta-language"),
    (r"\bnote\s*:\s*we\s+added\b", "editorial addition note"),
    (r"\[(?:sic|note|warning|editor|correction)\b", "editorial bracket tag"),
    (r"\bcompiler\s+note\b", "compiler note leak"),
    (r"extracted/docs/", "raw extraction path leak"),
]


def strip_code_blocks_and_inline_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def check_table_math_pipes(lines: list[str]) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, 1):
        if not (line.lstrip().startswith("|") and "$" in line):
            continue
        in_math = False
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line):
                if in_math and line[i + 1] == "|":
                    bad.append((idx, line[:120]))
                    break
                i += 2
                continue
            if line[i] == "$":
                in_math = not in_math
            elif line[i] == "|" and in_math:
                bad.append((idx, line[:120]))
                break
            i += 1
    return bad


def check_display_blocks(cleaned: str) -> list[str]:
    issues: list[str] = []
    blocks = re.findall(r"(?<!\\)\$\$(.*?)(?<!\\)\$\$", cleaned, flags=re.DOTALL)
    for bidx, blk in enumerate(blocks, 1):
        if not blk.strip():
            issues.append(f"empty $$ block #{bidx}")
            continue
        if "\n" in blk and re.search(r"\n[ \t]*\n", blk):
            issues.append(f"blank line inside multiline $$ block #{bidx}")
        # Check balanced \begin{...} / \end{...}
        stack: list[str] = []
        tokens = re.findall(r"\\(begin|end)\{([^}]+)\}", blk)
        for kind, env in tokens:
            if kind == "begin":
                stack.append(env)
            else:
                if not stack or stack[-1] != env:
                    issues.append(f"mismatched \\end{{{env}}} in $$ block #{bidx}")
                    stack = []
                    break
                stack.pop()
        if stack:
            issues.append(f"unclosed \\begin{{{stack[-1]}}} in $$ block #{bidx}")
    return issues


def check_file(s2_path: Path, s1_path: Path | None) -> dict:
    raw = s2_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    words = len(raw.split())
    s1_words = len(s1_path.read_text(encoding="utf-8").split()) if (s1_path and s1_path.exists()) else 0
    headings = [ln for ln in lines if re.match(r"^#{1,6}\s+\S", ln)]
    h1_titles = [ln for ln in lines if re.match(r"^#\s+\S", ln)]

    cleaned = strip_code_blocks_and_inline_code(raw)
    legacy_delims = re.findall(r"(?<!\\)\\[\[\]\(\)]", cleaned)
    dollar2_positions = [m.start() for m in re.finditer(r"(?<!\\)\$\$", cleaned)]
    unbalanced_dd = len(dollar2_positions) % 2 != 0

    no_dd = re.sub(r"(?<!\\)\$\$.*?(?<!\\)\$\$", "", cleaned, flags=re.DOTALL)
    bad_single_dollar_lines: list[tuple[int, str]] = []
    for idx, ln in enumerate(no_dd.splitlines(), 1):
        singles = re.findall(r"(?<!\\)\$", ln)
        if len(singles) % 2 != 0:
            bad_single_dollar_lines.append((idx, ln[:120]))

    issues: list[str] = []
    if not h1_titles:
        issues.append("missing H1 heading")
    if len(h1_titles) > 1:
        issues.append(f"multiple H1 headings ({len(h1_titles)}) — use H2+ for sections")
    if words < 300:
        issues.append(f"suspiciously short ({words} words)")
    if s1_words and words < 0.80 * s1_words:
        issues.append(f"shorter than 80% of Set 1 ({words} vs {s1_words} words — verify nothing valid was dropped)")
    if legacy_delims:
        issues.append(f"legacy math delimiters count={len(legacy_delims)}: {legacy_delims[:5]}")
    if unbalanced_dd:
        issues.append(f"unbalanced $$ count={len(dollar2_positions)}")
    else:
        issues.extend(check_display_blocks(cleaned))
    if bad_single_dollar_lines:
        issues.append(
            f"unbalanced single-$ on {len(bad_single_dollar_lines)} lines (e.g. L{bad_single_dollar_lines[0][0]}: {bad_single_dollar_lines[0][1]!r})"
        )
    table_pipes = check_table_math_pipes(lines)
    if table_pipes:
        issues.append(
            f"table math pipe | or \\| on {len(table_pipes)} lines (use \\lvert/\\rvert/\\lVert/\\rVert, e.g. L{table_pipes[0][0]})"
        )
    if "\ufffd" in raw or "\u200b" in raw:
        issues.append("contains replacement glyph U+FFFD or zero-width space U+200B")
    if re.search(r"<style\b|</style>", raw, re.IGNORECASE):
        issues.append("contains <style> tag")
    if re.search(r"```\{(?:r|python|bash|ojs)\b", raw, re.IGNORECASE):
        issues.append("contains Quarto/Rmd executable code chunk")
    if re.search(r"^\s*format:\s*(?:html|pdf|revealjs)", raw, re.MULTILINE):
        issues.append("contains YAML format boilerplate")
    if re.search(r"^\s*\d+\s*/\s*(?:48|60)\s*$", raw, re.MULTILINE) or "<!-- PAGE" in raw or "bpA" in raw:
        issues.append("contains PDF extraction artifact")

    for pat, desc in FORBIDDEN_META_PATTERNS:
        m = re.search(pat, cleaned, flags=re.IGNORECASE)
        if m:
            issues.append(f"forbidden Rule 2 phrase ({desc}): {m.group(0)!r}")

    return {
        "name": s2_path.name,
        "lines": len(lines),
        "words": words,
        "s1_words": s1_words,
        "headings": len(headings),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Verify a single filename inside output/set_2_corrected/")
    args = parser.parse_args()

    if not SET_1_DIR.exists():
        print(f"ERROR: {SET_1_DIR} does not exist")
        return 1
    if not SET_2_DIR.exists():
        print(f"ERROR: {SET_2_DIR} does not exist")
        return 1

    s1_files = {p.name: p for p in sorted(SET_1_DIR.glob("*.md"))}

    if args.file:
        target = SET_2_DIR / args.file
        if not target.exists():
            print(f"ERROR: {target} does not exist")
            return 1
        if args.file not in s1_files:
            print(f"ERROR: {args.file} has no parity match in {SET_1_DIR}")
            return 1
        res = check_file(target, s1_files[args.file])
        status = "OK" if not res["issues"] else "WARN"
        ratio = f"{res['words']/res['s1_words']:.2f}x" if res["s1_words"] else "n/a"
        print(f"[{status}] {res['name']} | lines={res['lines']} | words={res['words']} (Set1={res['s1_words']}, {ratio}) | h={res['headings']}")
        for iss in res["issues"]:
            print(f"       -> {iss}")
        return 1 if res["issues"] else 0

    s2_files = {p.name: p for p in sorted(SET_2_DIR.glob("*.md"))}
    missing = sorted(set(s1_files) - set(s2_files))
    extra = sorted(set(s2_files) - set(s1_files))

    print(f"Expected Set 2 articles: {len(s1_files)} | Found: {len(s2_files)}")
    if missing:
        print(f"MISSING ({len(missing)}): {missing}")
    if extra:
        print(f"EXTRA ({len(extra)}): {extra}")

    total_words = 0
    total_s1_words = 0
    files_with_issues = 0
    for fname in sorted(s1_files):
        if fname not in s2_files:
            continue
        res = check_file(s2_files[fname], s1_files[fname])
        total_words += res["words"]
        total_s1_words += res["s1_words"]
        status = "OK" if not res["issues"] else "WARN"
        if res["issues"]:
            files_with_issues += 1
        ratio = f"{res['words']/res['s1_words']:.2f}x" if res["s1_words"] else "n/a"
        print(
            f"[{status}] {res['name']:62s} | lines={res['lines']:4d} | words={res['words']:5d} ({ratio}) | h={res['headings']:2d}"
        )
        for iss in res["issues"]:
            print(f"       -> {iss}")

    print(f"\nTotal Set 2 words: {total_words} (vs Set 1: {total_s1_words})")
    print(f"Missing={len(missing)}, Extra={len(extra)}, Files with warnings={files_with_issues}")
    return 1 if (missing or extra or files_with_issues) else 0


if __name__ == "__main__":
    sys.exit(main())
