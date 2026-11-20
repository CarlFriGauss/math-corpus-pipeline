#!/usr/bin/env python3
"""Task 4 dynamic state manager: baseline freeze, incremental delta scan, and commit."""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from extract_corpus import (  # noqa: E402
    INCLUDED_PDFS,
    extract_ipynb,
    extract_pdf_text,
    is_excluded_source_file,
    strip_rmd_qmd,
)
from scan_inventory import SOURCE_DIRS, SOURCE_EQUIV_EXTS, TARGET_EXTS  # noqa: E402

SOURCES_CONFIG_PATH = ROOT / "config" / "sources.json"
BUILD_MANIFEST_PATH = SCRIPTS_DIR / "build_manifest.py"
OUTPUT_DIR = ROOT / "output"
MANIFEST_PATH = OUTPUT_DIR / "00_ingestion_manifest.md"
SET_1_DIR = OUTPUT_DIR / "set_1_faithful"
SET_2_DIR = OUTPUT_DIR / "set_2_corrected"
AUDIT_REPORT_PATH = OUTPUT_DIR / "AUDIT_REPORT.md"
LEDGER_PATH = OUTPUT_DIR / "state_ledger.json"
PENDING_DELTA_PATH = OUTPUT_DIR / "pending_delta.md"
CACHE_DIR = ROOT / "cache"
EXTRACTED_CACHE_DIR = CACHE_DIR / "extracted"
PENDING_SCAN_PATH = CACHE_DIR / "pending_scan.json"

_CFG_DATA = json.loads(SOURCES_CONFIG_PATH.read_text(encoding="utf-8")) if SOURCES_CONFIG_PATH.exists() else {}
PREFERRED_CANONICAL_ROOT = str(_CFG_DATA.get("preferred_canonical_root") or "")
PREFERRED_CANONICAL_ROOT_KEY = os.path.normcase(os.path.normpath(PREFERRED_CANONICAL_ROOT)) if PREFERRED_CANONICAL_ROOT else ""

CHECKPOINT_SKIP_DIRS = {".ipynb_checkpoints", ".rproj.user"}
KNOWN_INFRA_DIR_PARTS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".virtual_documents"}

# Heuristics for evaluating unseen standalone PDFs during incremental Mode B scans
EXTERNAL_PDF_MARKERS = (
    "isbn",
    "doi:",
    "arxiv:",
    "springer",
    "cambridge university press",
    "mit press",
    "elsevier",
    "wiley",
    "mcgraw-hill",
    "pearson",
    "addison-wesley",
    "problem set",
    "homework",
    "syllabus",
)
PERSONAL_CREATOR_MARKERS = (
    "pandoc",
    "latex",
    "tex",
    "xelatex",
    "lualatex",
    "pdflatex",
    "rstudio",
    "quarto",
    "wkhtmltopdf",
    "chromium",
    "chrome",
    "edge",
    "obsidian",
    "typora",
    "typst",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_key(path_str: str) -> str:
    return os.path.normcase(os.path.normpath(path_str))


def sanitize_filename(stem: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._")
    return cleaned or "document"


def normalize_whitespace_for_hash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_multiline_snapshot(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()]
    joined = "\n".join(lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return (joined + "\n") if joined else ""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest_definitions() -> tuple[
    list[tuple[str, str, list[tuple[int, str]]]],
    dict[int, str],
    dict[str, set[str]],
    dict[str, tuple[str, str]],
]:
    """Safely inspect scripts/build_manifest.py via AST if present (returns empty structures otherwise)."""
    if not BUILD_MANIFEST_PATH.exists():
        return [], {}, {}, {}
    src = BUILD_MANIFEST_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    topics: list[tuple[str, str, list[tuple[int, str]]]] = []
    non_theor: dict[int, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [getattr(t, "id", "") for t in node.targets]
            if "TOPICS" in targets:
                topics = ast.literal_eval(node.value)
            elif "NON_THEOR_REASONS" in targets:
                non_theor = ast.literal_eval(node.value)

    corpus_index_path = ROOT / "extracted" / "corpus_index.json"
    id_to_path: dict[int, str] = {}
    if corpus_index_path.exists():
        corp = json.loads(corpus_index_path.read_text(encoding="utf-8"))
        id_to_path = {d["id"]: d["source_path"] for d in corp.get("docs", [])}

    path_to_topics: dict[str, set[str]] = {}
    for slug, _title, items in topics:
        for doc_id, _scope in items:
            sp = id_to_path.get(doc_id)
            if sp:
                path_to_topics.setdefault(norm_key(sp), set()).add(slug)

    path_to_non_theor: dict[str, tuple[str, str]] = {}
    for doc_id, reason in non_theor.items():
        sp = id_to_path.get(doc_id)
        if sp:
            kind = "PARTIAL" if doc_id == 96 else "FULL"
            path_to_non_theor[norm_key(sp)] = (kind, reason)

    return topics, non_theor, path_to_topics, path_to_non_theor


def is_preferred_canonical_path(path_str: str, source_root: str = "") -> bool:
    """Prefer configured preferred_canonical_root when breaking duplicate ties."""
    if not PREFERRED_CANONICAL_ROOT_KEY:
        return False
    if source_root and norm_key(source_root) == PREFERRED_CANONICAL_ROOT_KEY:
        return True
    pk = norm_key(path_str)
    return pk == PREFERRED_CANONICAL_ROOT_KEY or pk.startswith(PREFERRED_CANONICAL_ROOT_KEY + os.sep)


def canonical_tiebreak_key(item: dict[str, Any]) -> tuple[int, int, str]:
    """Sort key placing preferred canonical root paths first, then SOURCE_DIRS order, then normalized path."""
    in_preferred = is_preferred_canonical_path(item["path"], item.get("source_root", ""))
    src_idx = next(
        (i for i, sr in enumerate(SOURCE_DIRS) if norm_key(sr) == norm_key(item.get("source_root", ""))),
        len(SOURCE_DIRS),
    )
    return (0 if in_preferred else 1, src_idx, norm_key(item["path"]))


def classify_pdf_for_scan(
    rec: dict[str, Any],
    prev: dict[str, Any] | None,
    known_included_keys: set[str],
) -> tuple[str, str]:
    """Dynamic Mode B PDF classification: never auto-exclude unseen standalone PDFs."""
    path = rec["path"]
    pkey = norm_key(path)

    # Preserve already-approved personal PDFs across incremental edits
    if pkey in known_included_keys or (prev and prev.get("status") == "INCLUDED - Personal PDF"):
        return (
            "INCLUDED - Personal PDF",
            "Previously approved personal PDF tracked in state_ledger.json",
        )
    if prev and prev.get("status") == "INCLUDED":
        return (
            "INCLUDED",
            "Previously approved PDF tracked in state_ledger.json",
        )

    if rec.get("same_name_source_exists"):
        matches = ", ".join(rec.get("matching_sources", []))
        return (
            "SKIPPED - Markdown Source Exists",
            f"Same-name source file exists in folder ({matches}); ingested source directly",
        )

    # Any unseen (or newly modified non-approved) standalone PDF without a same-name source sibling
    # must be surfaced as UNCLASSIFIED_PDF for dynamic GEMINI.md authorship verification.
    return (
        "UNCLASSIFIED_PDF",
        "Unseen standalone PDF without same-name .md/.Rmd/.qmd/.ipynb sibling; inspect metadata, page count, and first-2-page text per GEMINI.md",
    )


def classify_pdf_record(rec: dict[str, Any], known_included_keys: set[str]) -> tuple[str, str]:
    """Mirror exact Task 1 / GEMINI.md PDF classification plus heuristics for unseen PDFs."""
    path = rec["path"]
    low = path.lower()
    if norm_key(path) in known_included_keys:
        return (
            "INCLUDED - Personal PDF",
            "Personal standalone theoretical monograph/textbook with no source markdown/notebook; extracted for synthesis",
        )
    if rec.get("same_name_source_exists"):
        matches = ", ".join(rec.get("matching_sources", []))
        return (
            "SKIPPED - Markdown Source Exists",
            f"Same-name source file exists in folder ({matches}); ingested source directly",
        )
    if "_site\\documents\\" in low or "_site/documents/" in low:
        return (
            "SKIPPED - Markdown Source Exists",
            "Quarto-rendered PDF of `.qmd` source in `_site` output directory",
        )
    meta = rec.get("metadata", {}) or {}
    if meta.get("creator") == "R" and meta.get("title") == "R Graphics Output":
        return (
            "SKIPPED - Markdown Source Exists",
            "Auto-generated 1-page R plot figure belonging to Quarto `.qmd` document",
        )
    if "\\site-packages\\" in low or "/site-packages/" in low:
        return (
            "EXCLUDED - External Publication",
            "Third-party Python library UI icon asset inside virtual environment",
        )

    # Heuristic fallback for newly discovered standalone PDFs in Mode B
    meta_blob = " ".join(str(meta.get(k, "") or "") for k in ("author", "creator", "producer", "subject", "title")).lower()
    preview = " ".join(rec.get("first_pages_preview", [])).lower()
    combined = meta_blob + "\n" + preview
    if any(tok in combined for tok in EXTERNAL_PDF_MARKERS):
        return (
            "EXCLUDED - External Publication",
            "Unseen PDF matched external publication / textbook / syllabus markers (verify if personal)",
        )
    if any(tok in meta_blob for tok in PERSONAL_CREATOR_MARKERS):
        return (
            "PDF_REVIEW_NEEDED",
            "New standalone PDF created via personal export toolchain (Pandoc/LaTeX/RStudio/Quarto/Browser); inspect authorship",
        )
    return (
        "PDF_REVIEW_NEEDED",
        "New standalone PDF without matching Markdown source; inspect first 2 pages/metadata before ingestion",
    )


def discover_source_files() -> list[dict[str, Any]]:
    """Read-only walk across all configured SOURCE_DIRS mirroring scan_inventory.py rules."""
    records: list[dict[str, Any]] = []
    for src in SOURCE_DIRS:
        src_path = Path(src)
        if not src_path.exists():
            continue
        for root, _dirs, files in os.walk(src_path):
            root_path = Path(root)
            parts_lower = {p.lower() for p in root_path.parts}
            if parts_lower & CHECKPOINT_SKIP_DIRS:
                continue

            stems_with_source = {
                Path(f).stem.lower()
                for f in files
                if Path(f).suffix.lower() in SOURCE_EQUIV_EXTS
            }

            for fname in sorted(files):
                p = root_path / fname
                ext = p.suffix.lower()
                if ext not in TARGET_EXTS:
                    continue

                stat = p.stat()
                rec: dict[str, Any] = {
                    "source_root": src,
                    "path": str(p),
                    "ext": ext,
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
                if ext == ".pdf":
                    same_name = p.stem.lower() in stems_with_source
                    rec["same_name_source_exists"] = same_name
                    rec["matching_sources"] = [
                        str(root_path / f)
                        for f in sorted(files)
                        if Path(f).stem.lower() == p.stem.lower()
                        and Path(f).suffix.lower() in SOURCE_EQUIV_EXTS
                    ]
                    if not same_name:
                        try:
                            with fitz.open(str(p)) as doc:
                                rec["page_count"] = len(doc)
                                rec["metadata"] = doc.metadata or {}
                                rec["first_pages_preview"] = [
                                    doc[i].get_text("text")[:3000]
                                    for i in range(min(2, len(doc)))
                                ]
                        except Exception as exc:
                            rec["pdf_error"] = repr(exc)
                records.append(rec)
    return records


def extract_theoretical_text(path: Path, ext: str) -> tuple[dict[str, Any], str]:
    """Extract clean theoretical prose/math with all executable code cells/chunks stripped."""
    if ext == ".md":
        return {}, path.read_text(encoding="utf-8", errors="replace").strip()
    if ext == ".ipynb":
        return {}, extract_ipynb(path)
    if ext in {".rmd", ".qmd"}:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return strip_rmd_qmd(raw)
    if ext == ".pdf":
        return {"title": path.stem}, extract_pdf_text(path)
    raise ValueError(f"Unsupported extension: {ext}")


def write_snapshot(
    sha256_hex: str,
    source_path: str,
    meta: dict[str, Any],
    ext: str,
    raw_extracted_text: str,
) -> str:
    """Persist clean extracted snapshot under cache/extracted/ and return workspace-relative path."""
    EXTRACTED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = Path(source_path)
    sanitized = sanitize_filename(p.stem)
    prefix = sha256_hex[:12]
    body = normalize_multiline_snapshot(raw_extracted_text)
    if meta.get("title") and not body.lstrip().startswith("#"):
        body = f"# {meta['title']}\n\n{body}"

    candidate = EXTRACTED_CACHE_DIR / f"{prefix}_{sanitized}.md"
    suffix_idx = 2
    while candidate.exists():
        existing_body = candidate.read_text(encoding="utf-8", errors="replace")
        # Strip optional leading SNAPSHOT header when comparing bodies
        existing_clean = re.sub(r"^<!--\s*SNAPSHOT:.*?-->\s*\n*", "", existing_body, flags=re.DOTALL)
        if existing_clean == body:
            break
        candidate = EXTRACTED_CACHE_DIR / f"{prefix}_{sanitized}_{suffix_idx}.md"
        suffix_idx += 1

    header = f"<!-- SNAPSHOT: sha256={sha256_hex} | ext={ext} | source={source_path} -->\n\n"
    candidate.write_text(header + body, encoding="utf-8")
    return candidate.relative_to(ROOT).as_posix()


def strip_snapshot_header(snapshot_text: str) -> str:
    return re.sub(r"^<!--\s*SNAPSHOT:.*?-->\s*\n*", "", snapshot_text, flags=re.DOTALL)


def build_topics_registry(
    topics: list[tuple[str, str, list[tuple[int, str]]]]
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for idx, (slug, title, _items) in enumerate(topics, 1):
        registry[slug] = {
            "index": idx,
            "title": title,
            "set_1_file": f"output/set_1_faithful/{slug}.md",
            "set_2_file": f"output/set_2_corrected/{slug}.md",
        }
    return registry


def recover_baseline_text(doc_entry: dict[str, Any]) -> str:
    """Recover exact pre-header theoretical text corresponding to Task 1 corpus_index.json."""
    expected_sha = doc_entry.get("sha256_norm", "")
    snap_path = ROOT / doc_entry["extracted_file"]
    raw = snap_path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^<!-- SOURCE:.*?-->\n\n(.*)", raw, flags=re.DOTALL)
    body = m.group(1) if m else raw

    if expected_sha == "EMPTY":
        return ""

    if sha256_text(normalize_whitespace_for_hash(body)) == expected_sha:
        return body

    title = (doc_entry.get("meta") or {}).get("title")
    if title and body.startswith(f"# {title}\n\n"):
        trimmed = body[len(f"# {title}\n\n"):]
        if sha256_text(normalize_whitespace_for_hash(trimmed)) == expected_sha:
            return trimmed

    # Fallback: re-extract from source path ONLY if its normalized hash still equals Task 1 baseline
    src = Path(doc_entry["source_path"])
    if src.exists():
        _meta, live_txt = extract_theoretical_text(src, doc_entry["ext"])
        if sha256_text(normalize_whitespace_for_hash(live_txt)) == expected_sha:
            return live_txt

    raise RuntimeError(f"Could not recover exact Task 1 text matching sha256 for {doc_entry['source_path']}")


def run_baseline(force: bool = False) -> int:
    """Mode A: Freeze baseline state strictly from Task 1 processed manifest & extracted docs."""
    if LEDGER_PATH.exists() and not force:
        print(f"Ledger already exists at {LEDGER_PATH}. Re-run with --force to overwrite baseline.")
        return 1

    inv_path = ROOT / "extracted" / "inventory.json"
    pdf_path = ROOT / "extracted" / "pdf_inspection.json"
    corp_path = ROOT / "extracted" / "corpus_index.json"
    if not (inv_path.exists() and pdf_path.exists() and corp_path.exists()):
        print("ERROR: Missing extracted/ baseline cache files (`inventory.json`, `pdf_inspection.json`, `corpus_index.json`).")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(EXTRACTED_CACHE_DIR, ignore_errors=True)
    EXTRACTED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    topics, _non_theor, path_to_topics, path_to_non_theor = load_manifest_definitions()
    known_included_pdfs = {norm_key(p) for p in INCLUDED_PDFS}
    now_utc = utc_now_iso()

    inv_records = [
        r for r in json.loads(inv_path.read_text(encoding="utf-8"))["records"]
        if not r.get("is_checkpoint")
    ]
    pdf_by_key = {norm_key(p["path"]): p for p in json.loads(pdf_path.read_text(encoding="utf-8"))}
    corp_by_key = {norm_key(d["source_path"]): d for d in json.loads(corp_path.read_text(encoding="utf-8"))["docs"]}

    # Build canonical hash -> mapped topics map exclusively from Task 1 processed corpus
    hash_to_topics: dict[str, set[str]] = {}
    for pkey, doc_entry in corp_by_key.items():
        mapped = path_to_topics.get(pkey, set())
        if mapped and doc_entry["words"] > 0:
            hash_to_topics.setdefault(doc_entry["sha256_norm"], set()).update(mapped)

    ledger_files: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, int] = {}

    for rec in inv_records:
        path = rec["path"]
        ext = rec["ext"]
        pkey = norm_key(path)
        p = Path(path)

        doc_entry = corp_by_key.get(pkey)
        if doc_entry is not None:
            raw_text = recover_baseline_text(doc_entry)
            norm_text = normalize_whitespace_for_hash(raw_text)
            t_sha = sha256_text(norm_text)
            w_cnt = len(raw_text.split())
            direct_topics = sorted(path_to_topics.get(pkey, set()))
            non_theor_hit = path_to_non_theor.get(pkey)
            meta = doc_entry.get("meta") or {}

            if doc_entry["words"] == 0:
                status = "EXCLUDED - Empty / Code-Only"
                reason = "0 extracted theoretical markdown words"
                snap = None
                mapped_topics: list[str] = []
            elif direct_topics:
                snap = write_snapshot(t_sha, path, meta, ext, raw_text)
                mapped_topics = direct_topics
                if ext == ".pdf":
                    status = "INCLUDED - Personal PDF"
                    reason = "Included personal monograph/textbook mapped to Topic(s)"
                elif non_theor_hit and non_theor_hit[0] == "PARTIAL":
                    status = "INCLUDED"
                    reason = f"Partial scope included ({non_theor_hit[1]})"
                else:
                    status = "INCLUDED"
                    reason = f"Mapped to {len(mapped_topics)} topic(s)"
            elif non_theor_hit:
                snap = write_snapshot(t_sha, path, meta, ext, raw_text)
                status = "EXCLUDED - Non-Theoretical"
                reason = non_theor_hit[1]
                mapped_topics = []
            else:
                snap = write_snapshot(t_sha, path, meta, ext, raw_text)
                status = "DUPLICATE"
                mapped_topics = sorted(hash_to_topics.get(doc_entry["sha256_norm"], set()))
                reason = "Exact normalized-SHA256 duplicate copy of mapped source"

            size_bytes = rec.get("size", 0)
            stat = p.stat() if p.exists() else None
            # Only trust live raw_sha/mtime if file wasn't edited after Task 1
            live_matches_t1 = False
            if stat is not None:
                _m, live_txt = extract_theoretical_text(p, ext)
                live_matches_t1 = (
                    (sha256_text(normalize_whitespace_for_hash(live_txt)) == t_sha)
                    if w_cnt > 0
                    else (len(live_txt.split()) == 0)
                )
            raw_sha = sha256_bytes(p) if live_matches_t1 else None
            mtime_ns = stat.st_mtime_ns if live_matches_t1 else None
        else:
            # Excluded infrastructure or skipped/excluded PDF from Task 1 inventory
            if ext == ".pdf":
                pdf_rec = dict(pdf_by_key.get(pkey, {}))
                pdf_rec.setdefault("path", path)
                pdf_rec.setdefault("same_name_source_exists", rec.get("same_name_source_exists", False))
                status, reason = classify_pdf_record(pdf_rec, known_included_pdfs)
            else:
                excl, excl_reason = is_excluded_source_file(path)
                status = "EXCLUDED - Infrastructure" if excl else "EXCLUDED - Other"
                reason = excl_reason or "Excluded pre-extraction in Task 1"
            t_sha = None
            w_cnt = 0
            snap = None
            mapped_topics = []
            size_bytes = rec.get("size", 0)
            stat = p.stat() if p.exists() else None
            raw_sha = sha256_bytes(p) if (stat is not None and stat.st_size == size_bytes) else None
            mtime_ns = stat.st_mtime_ns if (stat is not None and stat.st_size == size_bytes) else None

        status_counts[status] = status_counts.get(status, 0) + 1
        ledger_files[path] = {
            "path": path,
            "source_root": rec["source_root"],
            "file_type": ext,
            "status": status,
            "reason": reason,
            "theory_sha256": t_sha,
            "raw_sha256": raw_sha,
            "size_bytes": size_bytes,
            "mtime_ns": mtime_ns,
            "word_count": w_cnt,
            "snapshot_file": snap,
            "mapped_topics": mapped_topics,
            "last_ingested_utc": now_utc,
        }

    ledger = {
        "schema_version": 1,
        "baseline_initialized_utc": now_utc,
        "last_commit_utc": now_utc,
        "source_roots": SOURCE_DIRS,
        "topics_registry": build_topics_registry(topics),
        "summary_counts": {
            "total_tracked_files": len(ledger_files),
            "by_status": dict(sorted(status_counts.items())),
        },
        "files": ledger_files,
    }
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")

    snap_files = list(EXTRACTED_CACHE_DIR.glob("*.md"))
    print(f"Baseline frozen into {LEDGER_PATH}")
    print(f"Total tracked files: {len(ledger_files)} | Snapshots saved in {EXTRACTED_CACHE_DIR}: {len(snap_files)}")
    for st, cnt in sorted(status_counts.items()):
        print(f"  {st:36s}: {cnt}")
    return 0


def run_scan(dry_run: bool = False) -> int:
    if not LEDGER_PATH.exists():
        print(f"ERROR: Ledger not found at {LEDGER_PATH}. Run `baseline` first.")
        return 1

    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    tracked_files: dict[str, dict[str, Any]] = ledger.get("files", {})
    by_key = {norm_key(k): v for k, v in tracked_files.items()}
    known_included_pdfs = {
        norm_key(p)
        for p, ent in tracked_files.items()
        if ent.get("status") == "INCLUDED - Personal PDF"
    }
    # Map non-empty theory hashes to existing tracked entries (for rename/move detection)
    sha_to_entries: dict[str, list[dict[str, Any]]] = {}
    for ent in tracked_files.values():
        tsha = ent.get("theory_sha256")
        if tsha and ent.get("word_count", 0) > 0:
            sha_to_entries.setdefault(tsha, []).append(ent)

    live_records = discover_source_files()
    live_keys = {norm_key(r["path"]) for r in live_records}

    missing_keys = set(by_key.keys()) - live_keys
    matched_missing_keys: set[str] = set()

    unchanged: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    new_candidates: list[dict[str, Any]] = []
    new_files: list[dict[str, Any]] = []
    modified_files: list[dict[str, Any]] = []
    ignored_or_excluded: list[dict[str, Any]] = []

    for rec in live_records:
        path = rec["path"]
        ext = rec["ext"]
        pkey = norm_key(path)
        p = Path(path)

        prev = by_key.get(pkey)

        # Fast-path skip for known excluded infrastructure / skipped or external PDFs if bytes & mtime unchanged
        if prev is not None and prev.get("status") in {
            "EXCLUDED - Infrastructure",
            "SKIPPED - Markdown Source Exists",
            "EXCLUDED - External Publication",
        }:
            if (
                prev.get("size_bytes") == rec["size_bytes"]
                and prev.get("mtime_ns") == rec["mtime_ns"]
            ):
                unchanged.append({"path": path, "status": prev["status"]})
                continue
            raw_sha = sha256_bytes(p)
            if prev.get("raw_sha256") == raw_sha:
                unchanged.append({"path": path, "status": prev["status"]})
                continue

        if ext == ".pdf":
            pdf_status, pdf_reason = classify_pdf_for_scan(rec, prev, known_included_pdfs)
            if pdf_status == "SKIPPED - Markdown Source Exists":
                ignored_or_excluded.append({
                    "path": path,
                    "source_root": rec["source_root"],
                    "status": pdf_status,
                    "reason": pdf_reason,
                    "raw_sha256": sha256_bytes(p),
                    "size_bytes": rec["size_bytes"],
                    "mtime_ns": rec["mtime_ns"],
                    "word_count": 0,
                })
                continue
        else:
            excl, reason = is_excluded_source_file(path)
            if excl:
                ignored_or_excluded.append({
                    "path": path,
                    "source_root": rec["source_root"],
                    "status": "EXCLUDED - Infrastructure",
                    "reason": reason,
                    "raw_sha256": sha256_bytes(p),
                    "size_bytes": rec["size_bytes"],
                    "mtime_ns": rec["mtime_ns"],
                    "word_count": 0,
                })
                continue
            pdf_status, pdf_reason = "PARSED", ""

        # Extract live theoretical content
        meta, raw_text = extract_theoretical_text(p, ext)
        norm_text = normalize_whitespace_for_hash(raw_text)
        t_sha = sha256_text(norm_text)
        raw_sha = sha256_bytes(p)
        w_cnt = len(raw_text.split())

        if prev is not None:
            if prev.get("theory_sha256") == t_sha and prev.get("status") != "DELETED":
                unchanged.append({"path": path, "status": prev["status"]})
                continue
            # Existing tracked file whose normalized theoretical text changed
            old_snap_rel = prev.get("snapshot_file")
            old_body = ""
            if old_snap_rel and (ROOT / old_snap_rel).exists():
                old_body = strip_snapshot_header((ROOT / old_snap_rel).read_text(encoding="utf-8", errors="replace"))
            new_body = normalize_multiline_snapshot(raw_text)
            if meta.get("title") and not new_body.lstrip().startswith("#"):
                new_body = f"# {meta['title']}\n\n{new_body}"
            diff_lines = list(
                difflib.unified_diff(
                    old_body.splitlines(keepends=True),
                    new_body.splitlines(keepends=True),
                    fromfile=f"cached/{Path(old_snap_rel).name if old_snap_rel else p.name}",
                    tofile=f"live/{p.name}",
                    n=3,
                )
            )
            mod_item: dict[str, Any] = {
                "path": path,
                "source_root": rec["source_root"],
                "file_type": ext,
                "previous_status": prev.get("status"),
                "mapped_topics": prev.get("mapped_topics", []),
                "old_theory_sha256": prev.get("theory_sha256"),
                "new_theory_sha256": t_sha,
                "raw_sha256": raw_sha,
                "size_bytes": rec["size_bytes"],
                "mtime_ns": rec["mtime_ns"],
                "word_count": w_cnt,
                "meta": meta,
                "extracted_text": new_body,
                "unified_diff": "".join(diff_lines),
            }
            if ext == ".pdf":
                mod_item.update({
                    "pdf_classification": pdf_status,
                    "pdf_reason": pdf_reason,
                    "pdf_page_count": rec.get("page_count"),
                    "pdf_metadata": rec.get("metadata"),
                    "first_pages_preview": rec.get("first_pages_preview", []),
                    "pdf_error": rec.get("pdf_error"),
                })
            modified_files.append(mod_item)
        else:
            # New path: check rename/move via matching non-empty theory_sha256 against a missing ledger entry
            if w_cnt > 0 and t_sha in sha_to_entries:
                missing_matches = [
                    e for e in sha_to_entries[t_sha]
                    if norm_key(e["path"]) in (missing_keys - matched_missing_keys)
                ]
                if missing_matches:
                    old_ent = missing_matches[0]
                    matched_missing_keys.add(norm_key(old_ent["path"]))
                    renamed.append({
                        "old_path": old_ent["path"],
                        "new_path": path,
                        "source_root": rec["source_root"],
                        "file_type": ext,
                        "status": old_ent["status"],
                        "theory_sha256": t_sha,
                        "raw_sha256": raw_sha,
                        "size_bytes": rec["size_bytes"],
                        "mtime_ns": rec["mtime_ns"],
                        "snapshot_file": old_ent.get("snapshot_file"),
                        "mapped_topics": old_ent.get("mapped_topics", []),
                    })
                    continue
                # Non-missing exact hash match -> new duplicate copy of already ingested theory
                existing_ent = sha_to_entries[t_sha][0]
                ignored_or_excluded.append({
                    "path": path,
                    "source_root": rec["source_root"],
                    "status": "DUPLICATE",
                    "reason": f"Exact match of existing `{existing_ent['path']}` (`{t_sha[:12]}`)",
                    "duplicate_of": existing_ent["path"],
                    "theory_sha256": t_sha,
                    "raw_sha256": raw_sha,
                    "size_bytes": rec["size_bytes"],
                    "mtime_ns": rec["mtime_ns"],
                    "word_count": w_cnt,
                    "snapshot_file": existing_ent.get("snapshot_file"),
                    "mapped_topics": existing_ent.get("mapped_topics", []),
                })
                continue

            if w_cnt == 0 and pdf_status != "UNCLASSIFIED_PDF":
                ignored_or_excluded.append({
                    "path": path,
                    "source_root": rec["source_root"],
                    "status": "EXCLUDED - Empty / Code-Only",
                    "reason": "New file has 0 theoretical markdown words",
                    "theory_sha256": t_sha,
                    "raw_sha256": raw_sha,
                    "size_bytes": rec["size_bytes"],
                    "mtime_ns": rec["mtime_ns"],
                    "word_count": 0,
                })
                continue

            body = normalize_multiline_snapshot(raw_text)
            if meta.get("title") and not body.lstrip().startswith("#"):
                body = f"# {meta['title']}\n\n{body}"
            cand: dict[str, Any] = {
                "path": path,
                "source_root": rec["source_root"],
                "file_type": ext,
                "pdf_classification": pdf_status if ext == ".pdf" else None,
                "pdf_reason": pdf_reason if ext == ".pdf" else None,
                "pdf_page_count": rec.get("page_count") if ext == ".pdf" else None,
                "pdf_metadata": rec.get("metadata") if ext == ".pdf" else None,
                "first_pages_preview": rec.get("first_pages_preview", []) if ext == ".pdf" else None,
                "pdf_error": rec.get("pdf_error") if ext == ".pdf" else None,
                "theory_sha256": t_sha,
                "raw_sha256": raw_sha,
                "size_bytes": rec["size_bytes"],
                "mtime_ns": rec["mtime_ns"],
                "word_count": w_cnt,
                "meta": meta,
                "extracted_text": body,
            }
            new_candidates.append(cand)

    # Intra-batch deduplication across newly discovered candidates (preferring configured canonical root)
    by_batch_sha: dict[str, list[dict[str, Any]]] = {}
    for cand in new_candidates:
        if cand["word_count"] == 0:
            new_files.append(cand)
        else:
            by_batch_sha.setdefault(cand["theory_sha256"], []).append(cand)

    for t_sha, group in by_batch_sha.items():
        if len(group) == 1:
            new_files.append(group[0])
            continue
        sorted_grp = sorted(group, key=canonical_tiebreak_key)
        canonical = sorted_grp[0]
        dups = sorted_grp[1:]
        canonical["intra_batch_duplicates"] = [d["path"] for d in dups]
        new_files.append(canonical)
        for dup in dups:
            ignored_or_excluded.append({
                "path": dup["path"],
                "source_root": dup["source_root"],
                "status": "DUPLICATE",
                "reason": f"Intra-batch duplicate of canonical `{canonical['path']}` (`{t_sha[:12]}`)",
                "duplicate_of": canonical["path"],
                "theory_sha256": dup["theory_sha256"],
                "raw_sha256": dup["raw_sha256"],
                "size_bytes": dup["size_bytes"],
                "mtime_ns": dup["mtime_ns"],
                "word_count": dup["word_count"],
                "snapshot_file": None,
                "mapped_topics": [],
            })

    for mkey in sorted(missing_keys - matched_missing_keys):
        ent = by_key[mkey]
        deleted.append({
            "path": ent["path"],
            "status": ent.get("status"),
            "mapped_topics": ent.get("mapped_topics", []),
        })

    unclassified_pdf_count = sum(1 for nf in new_files if nf.get("pdf_classification") == "UNCLASSIFIED_PDF") + sum(
        1 for mf in modified_files if mf.get("pdf_classification") == "UNCLASSIFIED_PDF"
    )
    dup_items = [ig for ig in ignored_or_excluded if ig.get("status") == "DUPLICATE"]
    other_ignored = [ig for ig in ignored_or_excluded if ig.get("status") != "DUPLICATE"]

    print(
        f"Delta scan summary: unchanged={len(unchanged)}, renamed={len(renamed)}, "
        f"deleted={len(deleted)}, new={len(new_files)} (unclassified_pdfs={unclassified_pdf_count}), "
        f"modified={len(modified_files)}, duplicates={len(dup_items)}, other_excluded={len(other_ignored)}"
    )

    if not new_files and not modified_files and not renamed and not deleted and not dup_items:
        print("Knowledge base is already up to date")

    if dry_run:
        return 0

    # Persist pending_delta.md & pending_scan.json for Mode B workflow
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    scan_payload = {
        "scanned_utc": utc_now_iso(),
        "unchanged_count": len(unchanged),
        "renamed": renamed,
        "deleted": deleted,
        "new_files": new_files,
        "modified_files": modified_files,
        "ignored_or_excluded": ignored_or_excluded,
    }
    PENDING_SCAN_PATH.write_text(json.dumps(scan_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# Pending Incremental Delta Report",
        "",
        f"- **Scanned (UTC):** `{scan_payload['scanned_utc']}`",
        f"- **Unchanged Files:** {len(unchanged)}",
        f"- **Renamed / Moved Files:** {len(renamed)}",
        f"- **Deleted Source Files:** {len(deleted)}",
        f"- **New Theoretical Files:** {len(new_files)} (including `{unclassified_pdf_count}` `UNCLASSIFIED_PDF`)",
        f"- **Modified Theoretical Files:** {len(modified_files)}",
        f"- **Duplicates Detected (Existing + Intra-Batch):** {len(dup_items)}",
        f"- **Other Excluded / Skipped Files:** {len(other_ignored)}",
        "",
    ]
    if not new_files and not modified_files:
        md.append("**Knowledge base is already up to date** (zero new or modified theoretical blocks).")
        md.append("")
    if renamed:
        md.extend(["## Renamed / Moved Files", ""])
        for r in renamed:
            md.append(f"- `{r['old_path']}` -> `{r['new_path']}` (topics: {r['mapped_topics']})")
        md.append("")
    if deleted:
        md.extend(["## Deleted Files (Preserved in Compiled Articles)", ""])
        for d in deleted:
            md.append(f"- `{d['path']}` (previous status: `{d['status']}`, topics: {d['mapped_topics']})")
        md.append("")
    if dup_items:
        md.extend(["## Duplicate Copies Detected (`DUPLICATE`)", ""])
        for dp in dup_items:
            md.append(f"- `{dp['path']}` — {dp['reason']}")
        md.append("")
    if new_files:
        md.extend(["## New Theoretical Files", ""])
        for idx, nf in enumerate(new_files, 1):
            pdf_tag = " (`UNCLASSIFIED_PDF`)" if nf.get("pdf_classification") == "UNCLASSIFIED_PDF" else ""
            md.append(f"### New File #{idx}: `{nf['path']}`{pdf_tag}")
            md.append(f"- **Words:** {nf['word_count']} | **Type:** `{nf['file_type']}` | **SHA-256:** `{nf['theory_sha256']}`")
            if nf.get("intra_batch_duplicates"):
                dups_fmt = ", ".join(f"`{p}`" for p in nf["intra_batch_duplicates"])
                md.append(f"- **Canonical Copy For Intra-Batch Duplicates:** {dups_fmt}")
            if nf.get("pdf_classification"):
                md.append(f"- **PDF Status:** `{nf['pdf_classification']}` ({nf['pdf_reason']})")
            if nf.get("pdf_classification") == "UNCLASSIFIED_PDF":
                md.append(f"- **Page Count:** {nf.get('pdf_page_count', '?')}")
                md.append(f"- **PDF Metadata:** `{json.dumps(nf.get('pdf_metadata') or {}, ensure_ascii=False)}`")
                if nf.get("pdf_error"):
                    md.append(f"- **PDF Read Error:** `{nf['pdf_error']}`")
                previews = nf.get("first_pages_preview") or []
                preview_chunks = [
                    f"--- Page {pi} ---\n{ptxt.strip()}"
                    for pi, ptxt in enumerate(previews, 1)
                ]
                preview_text = "\n\n".join(preview_chunks) if preview_chunks else "(empty / no extractable text)"
                md.extend(["", "#### First 2 Pages Text", "", "```text", preview_text, "```"])
                md.extend(["", "#### Extracted Text", "", "```markdown", nf["extracted_text"].rstrip(), "```", ""])
            else:
                md.extend(["", "```markdown", nf["extracted_text"].rstrip(), "```", ""])
    if modified_files:
        md.extend(["## Modified Theoretical Files", ""])
        for idx, mf in enumerate(modified_files, 1):
            pdf_tag = " (`UNCLASSIFIED_PDF`)" if mf.get("pdf_classification") == "UNCLASSIFIED_PDF" else ""
            md.append(f"### Modified File #{idx}: `{mf['path']}`{pdf_tag}")
            md.append(
                f"- **Mapped Topics:** {mf['mapped_topics']} | **Words:** {mf['word_count']} | "
                f"**New SHA-256:** `{mf['new_theory_sha256']}`"
            )
            if mf.get("pdf_classification") == "UNCLASSIFIED_PDF":
                md.append(f"- **PDF Status:** `{mf['pdf_classification']}` ({mf['pdf_reason']})")
                md.append(f"- **Page Count:** {mf.get('pdf_page_count', '?')}")
                md.append(f"- **PDF Metadata:** `{json.dumps(mf.get('pdf_metadata') or {}, ensure_ascii=False)}`")
                previews = mf.get("first_pages_preview") or []
                preview_chunks = [
                    f"--- Page {pi} ---\n{ptxt.strip()}"
                    for pi, ptxt in enumerate(previews, 1)
                ]
                preview_text = "\n\n".join(preview_chunks) if preview_chunks else "(empty / no extractable text)"
                md.extend(["", "#### First 2 Pages Text", "", "```text", preview_text, "```"])
            md.extend(["", "```diff", mf["unified_diff"].rstrip(), "```", ""])

    PENDING_DELTA_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {PENDING_DELTA_PATH}")
    return 0


def run_commit(topic_map_path: str | None = None) -> int:
    """Commit staged scan changes into output/state_ledger.json and cache/extracted/."""
    if not LEDGER_PATH.exists():
        print(f"ERROR: Ledger not found at {LEDGER_PATH}. Run `baseline` first.")
        return 1
    if not PENDING_SCAN_PATH.exists():
        print("No staged scan found in cache/pending_scan.json. Run `scan` first.")
        return 1

    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    files = ledger.setdefault("files", {})
    by_key = {norm_key(k): k for k in files}
    scan_data = json.loads(PENDING_SCAN_PATH.read_text(encoding="utf-8"))
    now_utc = utc_now_iso()

    topic_overrides: dict[str, Any] = {}
    if topic_map_path:
        topic_overrides = json.loads(Path(topic_map_path).read_text(encoding="utf-8"))
    overrides_by_norm = {norm_key(k): v for k, v in topic_overrides.items()}

    # Validate that every UNCLASSIFIED_PDF has an explicit authorship decision in --topic-map
    valid_pdf_decisions = {
        "INCLUDED - Personal PDF",
        "EXCLUDED - External Publication",
        "EXCLUDED - Non-Theoretical",
        "EXCLUDED - Empty / Code-Only",
        "SKIPPED - Markdown Source Exists",
        "DUPLICATE",
    }
    unclassified_pending: list[str] = []
    for item in scan_data.get("new_files", []) + scan_data.get("modified_files", []):
        if item.get("pdf_classification") == "UNCLASSIFIED_PDF":
            ov = overrides_by_norm.get(norm_key(item["path"]), {})
            decided_status = ov.get("status")
            if not decided_status or decided_status not in valid_pdf_decisions:
                unclassified_pending.append(f"{item['path']} (got status={decided_status!r})")
    if unclassified_pending:
        print("ERROR: Unclassified standalone PDF(s) require explicit authorship classification via --topic-map:")
        for u in unclassified_pending:
            print(f"  - {u}")
        print(f"Allowed statuses: {sorted(valid_pdf_decisions)}")
        return 1

    # Refresh topic registry from Set 1 filenames on disk
    set_1_files = sorted(SET_1_DIR.glob("*.md"))
    for idx, p1 in enumerate(set_1_files, 1):
        slug = p1.stem
        if slug not in ledger["topics_registry"]:
            h1_m = re.match(r"^#\s+(.+)$", p1.read_text(encoding="utf-8").splitlines()[0])
            num_m = re.match(r"^(\d+)_", slug)
            ledger["topics_registry"][slug] = {
                "index": int(num_m.group(1)) if num_m else idx,
                "title": h1_m.group(1).strip() if h1_m else slug,
                "set_1_file": f"output/set_1_faithful/{p1.name}",
                "set_2_file": f"output/set_2_corrected/{p1.name}",
            }

    for r in scan_data.get("renamed", []):
        old_real = by_key.pop(norm_key(r["old_path"]), None)
        if old_real and old_real in files:
            ent = files.pop(old_real)
        else:
            ent = {}
        ent.update({
            "path": r["new_path"],
            "source_root": r["source_root"],
            "file_type": r["file_type"],
            "status": r["status"],
            "theory_sha256": r["theory_sha256"],
            "raw_sha256": r["raw_sha256"],
            "size_bytes": r["size_bytes"],
            "mtime_ns": r["mtime_ns"],
            "snapshot_file": r.get("snapshot_file"),
            "mapped_topics": r.get("mapped_topics", []),
            "last_ingested_utc": now_utc,
        })
        files[r["new_path"]] = ent
        by_key[norm_key(r["new_path"])] = r["new_path"]

    for d in scan_data.get("deleted", []):
        k_real = by_key.get(norm_key(d["path"]))
        if k_real and k_real in files:
            files[k_real]["status"] = "DELETED"
            files[k_real]["last_ingested_utc"] = now_utc

    for mf in scan_data.get("modified_files", []):
        override = overrides_by_norm.get(norm_key(mf["path"]), {})
        k_real = by_key.get(norm_key(mf["path"]), mf["path"])
        ent = files.get(k_real, {})
        status = override.get("status", ent.get("status", "INCLUDED"))
        snap = (
            override.get("snapshot_file")
            if (status.startswith("EXCLUDED") or status.startswith("SKIPPED") or status == "DUPLICATE")
            else write_snapshot(
                mf["new_theory_sha256"], mf["path"], mf.get("meta", {}), mf["file_type"], mf["extracted_text"]
            )
        )
        ent.update({
            "path": mf["path"],
            "source_root": mf["source_root"],
            "file_type": mf["file_type"],
            "status": status,
            "reason": override.get("reason", ent.get("reason", "Modified theoretical source committed")),
            "theory_sha256": mf["new_theory_sha256"],
            "raw_sha256": mf["raw_sha256"],
            "size_bytes": mf["size_bytes"],
            "mtime_ns": mf["mtime_ns"],
            "word_count": mf["word_count"],
            "snapshot_file": snap,
            "mapped_topics": override.get("mapped_topics", mf.get("mapped_topics", [])),
            "last_ingested_utc": now_utc,
        })
        files[k_real] = ent
        by_key[norm_key(k_real)] = k_real

    for nf in scan_data.get("new_files", []):
        override = overrides_by_norm.get(norm_key(nf["path"]), {})
        status = override.get("status")
        if not status:
            status = "INCLUDED"
        snap = (
            override.get("snapshot_file")
            if (status.startswith("EXCLUDED") or status.startswith("SKIPPED") or status == "DUPLICATE")
            else write_snapshot(
                nf["theory_sha256"], nf["path"], nf.get("meta", {}), nf["file_type"], nf["extracted_text"]
            )
        )
        files[nf["path"]] = {
            "path": nf["path"],
            "source_root": nf["source_root"],
            "file_type": nf["file_type"],
            "status": status,
            "reason": override.get("reason", nf.get("pdf_reason") or "Newly ingested theoretical source"),
            "theory_sha256": nf["theory_sha256"],
            "raw_sha256": nf["raw_sha256"],
            "size_bytes": nf["size_bytes"],
            "mtime_ns": nf["mtime_ns"],
            "word_count": nf["word_count"],
            "snapshot_file": snap,
            "mapped_topics": override.get("mapped_topics", []),
            "last_ingested_utc": now_utc,
        }
        by_key[norm_key(nf["path"])] = nf["path"]

    for ig in scan_data.get("ignored_or_excluded", []):
        snap_file = ig.get("snapshot_file")
        mapped_topics = ig.get("mapped_topics", [])
        if ig.get("status") == "DUPLICATE" and ig.get("duplicate_of"):
            canon_real = by_key.get(norm_key(ig["duplicate_of"]))
            if canon_real and canon_real in files:
                canon_ent = files[canon_real]
                snap_file = canon_ent.get("snapshot_file")
                mapped_topics = canon_ent.get("mapped_topics", [])

        existing_real = by_key.get(norm_key(ig["path"]))
        target_key = existing_real or ig["path"]
        files[target_key] = {
            "path": ig["path"],
            "source_root": ig.get("source_root", ""),
            "file_type": Path(ig["path"]).suffix.lower(),
            "status": ig["status"],
            "reason": ig.get("reason", ""),
            "theory_sha256": ig.get("theory_sha256"),
            "raw_sha256": ig.get("raw_sha256"),
            "size_bytes": ig.get("size_bytes", 0),
            "mtime_ns": ig.get("mtime_ns", 0),
            "word_count": ig.get("word_count", 0),
            "snapshot_file": snap_file,
            "mapped_topics": mapped_topics,
            "last_ingested_utc": now_utc,
        }
        by_key[norm_key(ig["path"])] = target_key

    # Remove orphaned snapshot files (e.g., superseded snapshots of modified files)
    referenced_snaps = {
        (ROOT / ent["snapshot_file"]).resolve()
        for ent in files.values()
        if ent.get("snapshot_file")
    }
    if EXTRACTED_CACHE_DIR.exists():
        for snap_p in EXTRACTED_CACHE_DIR.glob("*.md"):
            if snap_p.resolve() not in referenced_snaps:
                snap_p.unlink()

    # Recompute counts
    counts: dict[str, int] = {}
    for ent in files.values():
        counts[ent["status"]] = counts.get(ent["status"], 0) + 1
    ledger["last_commit_utc"] = now_utc
    ledger["summary_counts"] = {"total_tracked_files": len(files), "by_status": dict(sorted(counts.items()))}
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")

    PENDING_SCAN_PATH.unlink(missing_ok=True)
    if PENDING_DELTA_PATH.exists():
        PENDING_DELTA_PATH.unlink()
    print(f"Committed changes to {LEDGER_PATH} ({len(files)} total tracked entries).")
    return 0


def run_verify() -> int:
    if not LEDGER_PATH.exists():
        print(f"ERROR: {LEDGER_PATH} does not exist")
        return 1

    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    files = ledger.get("files", {})
    registry = ledger.get("topics_registry", {})
    issues: list[str] = []

    req_fields = {
        "path",
        "file_type",
        "status",
        "theory_sha256",
        "snapshot_file",
        "mapped_topics",
        "last_ingested_utc",
    }

    referenced_snapshots: set[Path] = set()
    for path, ent in files.items():
        missing_keys = req_fields - set(ent.keys())
        if missing_keys:
            issues.append(f"{path}: missing required fields {missing_keys}")
        snap = ent.get("snapshot_file")
        if snap:
            sp = ROOT / snap
            referenced_snapshots.add(sp.resolve())
            if not sp.exists():
                issues.append(f"{path}: missing snapshot file {snap}")
        elif ent.get("status") in {"INCLUDED", "INCLUDED - Personal PDF"}:
            issues.append(f"{path}: status `{ent.get('status')}` has null snapshot_file")

        for slug in ent.get("mapped_topics", []):
            if slug not in registry:
                issues.append(f"{path}: unknown mapped topic slug {slug}")

    for slug, tinfo in registry.items():
        for k in ("set_1_file", "set_2_file"):
            tp = ROOT / tinfo[k]
            if not tp.exists():
                issues.append(f"topic {slug}: missing {tinfo[k]}")

    actual_snaps = {p.resolve() for p in EXTRACTED_CACHE_DIR.glob("*.md")} if EXTRACTED_CACHE_DIR.exists() else set()
    orphan_snaps = actual_snaps - referenced_snapshots
    if orphan_snaps:
        issues.append(f"{len(orphan_snaps)} orphaned snapshot files in {EXTRACTED_CACHE_DIR}")

    print(
        f"Verified state_ledger.json: tracked_files={len(files)} | unique_snapshots={len(actual_snaps)} | "
        f"topics={len(registry)} | issues={len(issues)}"
    )
    for iss in issues[:30]:
        print(f"  ISSUE: {iss}")
    return 1 if issues else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Task 4 incremental ingestion ledger and snapshots.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_base = sub.add_parser("baseline", aliases=["freeze", "init"], help="Mode A: initialize baseline state ledger & cache")
    p_base.add_argument("--force", action="store_true", help="Overwrite existing output/state_ledger.json cleanly")

    p_scan = sub.add_parser("scan", help="Mode B Step 1: scan source directories for delta vs ledger")
    p_scan.add_argument("--dry-run", action="store_true", help="Report delta counts without writing pending_delta.md")

    p_commit = sub.add_parser("commit", help="Mode B Step 5: commit staged scan results to ledger & cache")
    p_commit.add_argument("--topic-map", help="Optional JSON file overriding status/mapped_topics by path")

    sub.add_parser("verify", help="Verify state_ledger.json and cache/extracted/ integrity")

    args = parser.parse_args()
    if args.cmd in {"baseline", "freeze", "init"}:
        return run_baseline(force=args.force)
    if args.cmd == "scan":
        return run_scan(dry_run=args.dry_run)
    if args.cmd == "commit":
        return run_commit(topic_map_path=args.topic_map)
    if args.cmd == "verify":
        return run_verify()
    return 1


if __name__ == "__main__":
    sys.exit(main())
