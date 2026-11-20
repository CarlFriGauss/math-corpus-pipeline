#!/usr/bin/env python3
"""Verify Set 1 faithful compilation articles in output/set_1_faithful/."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SET_1_DIR = ROOT / "output" / "set_1_faithful"
DEFAULT_MANIFEST = ROOT / "output" / "topic_manifest.json"


def strip_code_blocks_and_inline_code(text: str) -> str:
    """Remove fenced code blocks and inline backticks so delimiter checks ignore code."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def check_file(path: Path, expected_title: str = "") -> dict:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    words = len(raw.split())
    headings = [ln for ln in lines if re.match(r"^#{1,6}\s+\S", ln)]
    h1_titles = [ln for ln in lines if re.match(r"^#\s+\S", ln)]

    cleaned = strip_code_blocks_and_inline_code(raw)

    # Check LaTeX delimiter standardization: flag \(, \), \[, \] (excluding \\[ row break)
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
    if words < 100:
        issues.append(f"suspiciously short ({words} words)")
    if legacy_delims:
        issues.append(f"legacy math delimiters count={len(legacy_delims)}: {legacy_delims[:5]}")
    if unbalanced_dd:
        issues.append(f"unbalanced $$ count={len(dollar2_positions)}")
    if bad_single_dollar_lines:
        issues.append(
            f"unbalanced single-$ on {len(bad_single_dollar_lines)} lines (e.g. L{bad_single_dollar_lines[0][0]}: {bad_single_dollar_lines[0][1]!r})"
        )
    if re.search(r"<style\b|</style>", raw, re.IGNORECASE):
        issues.append("contains <style> tag")
    if re.search(r"```\{(?:r|python|bash|ojs)\b", raw, re.IGNORECASE):
        issues.append("contains Quarto/Rmd executable code chunk")
    if re.search(r"^\s*format:\s*(?:html|pdf|revealjs)", raw, re.MULTILINE):
        issues.append("contains YAML format boilerplate")
    if re.search(r"^\s*\d+\s*/\s*(?:48|60)\s*$", raw, re.MULTILINE):
        issues.append("contains PDF page footer artifact")
    if "bpA" in raw:
        issues.append("contains raw fitz artifact 'bpA'")
    if re.search(r"\[(?:sic|note|warning)\b|compiler\s+note|extracted/docs/", raw, re.IGNORECASE):
        issues.append("possible Law 4 / raw-ID phrase (inspect)")

    return {
        "name": path.name,
        "lines": len(lines),
        "words": words,
        "headings": len(headings),
        "h1": h1_titles[0] if h1_titles else "",
        "expected_title": expected_title,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Set 1 faithful compilation articles.")
    parser.add_argument("--manifest", help="Optional JSON mapping filenames to expected titles.")
    args = parser.parse_args()

    if not SET_1_DIR.exists():
        print(f"ERROR: {SET_1_DIR} does not exist")
        return 1

    manifest_path = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST
    expected_map: dict[str, str] = {}
    if manifest_path.exists():
        raw_m = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(raw_m, dict):
            expected_map = {str(k): str(v) for k, v in raw_m.items()}

    actual_files = sorted(p.name for p in SET_1_DIR.glob("*.md"))
    if expected_map:
        missing = sorted(set(expected_map) - set(actual_files))
        extra = sorted(set(actual_files) - set(expected_map))
        target_names = sorted(expected_map)
        print(f"Expected articles: {len(expected_map)} | Found articles: {len(actual_files)}")
    else:
        missing = []
        extra = []
        target_names = actual_files
        print(f"Found Set 1 articles: {len(actual_files)}")

    if missing:
        print(f"MISSING ({len(missing)}): {missing}")
    if extra:
        print(f"EXTRA ({len(extra)}): {extra}")

    total_words = 0
    files_with_issues = 0
    for fname in target_names:
        fpath = SET_1_DIR / fname
        if not fpath.exists():
            continue
        res = check_file(fpath, expected_map.get(fname, ""))
        total_words += res["words"]
        status = "OK" if not res["issues"] else "WARN"
        if res["issues"]:
            files_with_issues += 1
        print(
            f"[{status}] {res['name']:62s} | lines={res['lines']:4d} | words={res['words']:5d} | h={res['headings']:2d}"
        )
        for iss in res["issues"]:
            print(f"       -> {iss}")

    print(f"\nTotal Set 1 words across present files: {total_words}")
    print(f"Missing={len(missing)}, Extra={len(extra)}, Files with warnings={files_with_issues}")
    return 1 if (missing or extra or files_with_issues or not actual_files) else 0


if __name__ == "__main__":
    sys.exit(main())
