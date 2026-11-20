"""Extract clean theoretical content from all non-infrastructure source files and included personal PDFs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import fitz
import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES_CONFIG_PATH = ROOT / "config" / "sources.json"
INVENTORY_PATH = ROOT / "extracted" / "inventory.json"
OUT_DOCS_DIR = ROOT / "extracted" / "docs"
OUT_INDEX_PATH = ROOT / "extracted" / "corpus_index.json"

SKIP_DIR_PARTS = {
    ".venv",
    "venv",
    "node_modules",
    "site-packages",
    ".ipynb_checkpoints",
    ".rproj.user",
    ".quarto",
    "__pycache__",
    ".git",
    ".virtual_documents",
}


def _load_sources_cfg() -> dict:
    if SOURCES_CONFIG_PATH.exists():
        return json.loads(SOURCES_CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


_CFG = _load_sources_cfg()
INCLUDED_PDFS: set[str] = {str(p) for p in (_CFG.get("included_pdfs") or [])}
EXCLUDED_SUBSTRINGS: tuple[str, ...] = tuple(str(s).lower() for s in (_CFG.get("excluded_substrings") or []))


def is_excluded_source_file(path_str: str) -> tuple[bool, str]:
    p = Path(path_str)
    parts_lower = {part.lower() for part in p.parts}
    if parts_lower & SKIP_DIR_PARTS:
        return True, "Infrastructure / virtualenv / package / checkpoint directory"

    low = path_str.lower()
    for sub in EXCLUDED_SUBSTRINGS:
        if sub in low:
            return True, f"Matched configured excluded pattern: {sub}"
    return False, ""


def extract_ipynb(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return ""
    dec = json.JSONDecoder()
    pos = 0
    objs = []
    while pos < len(raw):
        while pos < len(raw) and raw[pos].isspace():
            pos += 1
        if pos >= len(raw):
            break
        obj, end = dec.raw_decode(raw, pos)
        objs.append(obj)
        pos = end

    seen_md_lists = []
    md_blocks = []
    for obj in objs:
        cells = obj.get("cells", [])
        cur_mds = [
            "".join(c.get("source", [])) if isinstance(c.get("source"), list) else str(c.get("source", ""))
            for c in cells
            if c.get("cell_type") == "markdown"
        ]
        if cur_mds in seen_md_lists:
            continue
        seen_md_lists.append(cur_mds)
        md_blocks.extend(m.strip() for m in cur_mds if m.strip())

    return "\n\n".join(md_blocks)


def strip_rmd_qmd(text: str) -> tuple[dict, str]:
    meta: dict = {}
    body = text
    m = re.match(r"^\ufeff?---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if m:
        yaml_raw = m.group(1)
        body = text[m.end():]
        try:
            parsed = yaml.safe_load(yaml_raw)
            if isinstance(parsed, dict):
                meta = {
                    k: parsed[k]
                    for k in ("title", "subtitle", "author", "date")
                    if k in parsed and parsed[k] is not None
                }
        except Exception:
            for line in yaml_raw.splitlines():
                if line.strip().startswith(("title:", "subtitle:")):
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip('"\'')

    lines = body.splitlines()
    out_lines: list[str] = []
    in_fence = False
    fence_char = "`"
    fence_len = 0
    strip_current_fence = False

    for line in lines:
        m_fence = re.match(r"^(\s*)(`{3,}|~{3,})(.*)$", line)
        if not in_fence and m_fence:
            f_str = m_fence.group(2)
            info = m_fence.group(3).strip()
            is_exec = bool(
                re.match(r"^(\{\{?[a-zA-Z0-9_.-]+.*\}?\}?|r|python|bash|sh|sql|stan|ojs|julia)\b", info, re.IGNORECASE)
                or "```{" in info
            )
            in_fence = True
            fence_char = f_str[0]
            fence_len = len(f_str)
            strip_current_fence = is_exec
            if not strip_current_fence:
                out_lines.append(line)
            continue

        if in_fence:
            m_close = re.match(rf"^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$", line)
            if m_close:
                if not strip_current_fence:
                    out_lines.append(line)
                in_fence = False
                strip_current_fence = False
                continue
            if not strip_current_fence:
                out_lines.append(line)
            continue

        out_lines.append(line)

    cleaned = "\n".join(out_lines)
    cleaned = re.sub(r"`r\s+[^`\n]+`", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return meta, cleaned


def extract_pdf_text(path: Path) -> str:
    pages = []
    with fitz.open(str(path)) as doc:
        for i, page in enumerate(doc, 1):
            txt = page.get_text("text")
            pages.append(f"<!-- PAGE {i} -->\n{txt.strip()}")
    return "\n\n".join(pages)


def count_math_markers(text: str) -> int:
    return (
        len(re.findall(r"\$\$", text)) // 2
        + len(re.findall(r"\\\[", text))
        + len(re.findall(r"\\\(", text))
        + len(re.findall(r"(?<!\$)\$(?!\$)[^$\n]+?(?<!\$)\$(?!\$)", text))
    )


def extract_headings(text: str) -> list[str]:
    headings = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^#{1,4}\s+\S", s):
            headings.append(s[:120])
    return headings[:40]


def main() -> None:
    OUT_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    inv = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    corpus = []
    excluded_non_pdf = []

    doc_id = 0
    for rec in inv["records"]:
        if rec.get("is_checkpoint"):
            continue
        p = Path(rec["path"])
        ext = rec["ext"]

        if ext == ".pdf":
            if rec["path"] not in INCLUDED_PDFS:
                continue
            text = extract_pdf_text(p)
            meta = {"title": p.stem}
        else:
            excl, reason = is_excluded_source_file(rec["path"])
            if excl:
                excluded_non_pdf.append({"path": rec["path"], "reason": reason})
                continue

            if ext == ".md":
                text = p.read_text(encoding="utf-8", errors="replace").strip()
                meta = {}
            elif ext == ".ipynb":
                text = extract_ipynb(p)
                meta = {}
            elif ext in {".rmd", ".qmd"}:
                raw = p.read_text(encoding="utf-8", errors="replace")
                meta, text = strip_rmd_qmd(raw)
            else:
                continue

        doc_id += 1
        norm_text = re.sub(r"\s+", " ", text).strip()
        sha = hashlib.sha256(norm_text.encode("utf-8")).hexdigest() if norm_text else "EMPTY"
        words = len(text.split())
        math_cnt = count_math_markers(text)
        headings = extract_headings(text)

        out_fname = f"{doc_id:03d}_{re.sub(r'[^a-zA-Z0-9._-]+', '_', p.stem)}.md"
        header = f"<!-- SOURCE: {rec['path']} | EXT: {ext} | META: {json.dumps(meta, ensure_ascii=False)} -->\n\n"
        if meta.get("title") and not text.lstrip().startswith("#"):
            header += f"# {meta['title']}\n\n"
        (OUT_DOCS_DIR / out_fname).write_text(header + text, encoding="utf-8")

        corpus.append({
            "id": doc_id,
            "extracted_file": str((OUT_DOCS_DIR / out_fname).relative_to(ROOT)),
            "source_path": rec["path"],
            "source_root": rec["source_root"],
            "ext": ext,
            "meta": meta,
            "chars": len(text),
            "words": words,
            "math_markers": math_cnt,
            "sha256_norm": sha,
            "headings": headings,
            "preview": text[:280].replace("\n", " "),
        })

    out_data = {
        "total_extracted_docs": len(corpus),
        "excluded_non_pdf": excluded_non_pdf,
        "docs": corpus,
    }
    OUT_INDEX_PATH.write_text(
        json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Extracted {len(corpus)} documents; excluded {len(excluded_non_pdf)} non-PDF boilerplate/repo files.")

    by_hash = {}
    for d in corpus:
        by_hash.setdefault(d["sha256_norm"], []).append(d)
    dups = [v for v in by_hash.values() if len(v) > 1]
    print(f"Exact normalized duplicate groups: {len(dups)}")
    for grp in dups:
        print("  DUP GROUP:")
        for d in grp:
            print(f"    [{d['id']:03d}] {d['source_path']} (words={d['words']})")


if __name__ == "__main__":
    main()
