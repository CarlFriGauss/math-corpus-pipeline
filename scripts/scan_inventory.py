"""Inventory and inspect all target files across configured read-only source directories."""

from __future__ import annotations

import json
import os
from pathlib import Path
import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
SOURCES_CONFIG_PATH = ROOT / "config" / "sources.json"


def load_source_dirs() -> list[str]:
    """Load configured source directories from config/sources.json, falling back to ./raw_notes."""
    if SOURCES_CONFIG_PATH.exists():
        cfg = json.loads(SOURCES_CONFIG_PATH.read_text(encoding="utf-8"))
        dirs = cfg.get("source_dirs") or []
        return [str(d) for d in dirs]
    return [str(ROOT / "raw_notes")]


SOURCE_DIRS: list[str] = load_source_dirs()
TARGET_EXTS = {".md", ".ipynb", ".rmd", ".qmd", ".pdf"}
SOURCE_EQUIV_EXTS = {".md", ".rmd", ".qmd", ".ipynb"}


def main() -> None:
    out_dir = ROOT / "extracted"
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    pdf_details = []
    dir_stats = {}

    for src in load_source_dirs():
        src_path = Path(src)
        if not src_path.exists():
            dir_stats[src] = {"exists": False, "counts": {}}
            continue

        counts = {ext: 0 for ext in sorted(TARGET_EXTS)}
        counts["checkpoint_skipped"] = 0

        for root, _dirs, files in os.walk(src_path):
            root_path = Path(root)
            parts_lower = [p.lower() for p in root_path.parts]
            is_checkpoint = ".ipynb_checkpoints" in parts_lower or ".rproj.user" in parts_lower

            stems_with_source = set()
            for fname in files:
                p = root_path / fname
                ext = p.suffix.lower()
                if ext in SOURCE_EQUIV_EXTS and not is_checkpoint:
                    stems_with_source.add(p.stem.lower())

            for fname in sorted(files):
                p = root_path / fname
                ext = p.suffix.lower()
                if ext not in TARGET_EXTS:
                    continue

                if is_checkpoint:
                    counts["checkpoint_skipped"] += 1
                    records.append({
                        "source_root": src,
                        "path": str(p),
                        "ext": ext,
                        "size": p.stat().st_size,
                        "is_checkpoint": True,
                    })
                    continue

                counts[ext] += 1
                rec = {
                    "source_root": src,
                    "path": str(p),
                    "ext": ext,
                    "size": p.stat().st_size,
                    "is_checkpoint": False,
                }

                if ext == ".pdf":
                    same_name_source = p.stem.lower() in stems_with_source
                    matching_sources = [
                        str(root_path / f)
                        for f in files
                        if Path(f).stem.lower() == p.stem.lower()
                        and Path(f).suffix.lower() in SOURCE_EQUIV_EXTS
                    ]
                    pdf_info = {
                        "path": str(p),
                        "source_root": src,
                        "size": p.stat().st_size,
                        "same_name_source_exists": same_name_source,
                        "matching_sources": matching_sources,
                    }
                    try:
                        with fitz.open(str(p)) as doc:
                            pdf_info["page_count"] = len(doc)
                            pdf_info["metadata"] = doc.metadata or {}
                            first_pages = []
                            for idx in range(min(2, len(doc))):
                                first_pages.append(doc[idx].get_text("text")[:3000])
                            pdf_info["first_pages_preview"] = first_pages
                    except Exception as exc:
                        pdf_info["error"] = repr(exc)
                    pdf_details.append(pdf_info)
                    rec["same_name_source_exists"] = same_name_source

                records.append(rec)

        dir_stats[src] = {"exists": True, "counts": counts}

    summary = {
        "dir_stats": dir_stats,
        "total_non_checkpoint_files": sum(1 for r in records if not r["is_checkpoint"]),
        "total_checkpoint_files": sum(1 for r in records if r["is_checkpoint"]),
        "total_pdfs": len(pdf_details),
        "records": records,
    }

    (out_dir / "inventory.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "pdf_inspection.json").write_text(
        json.dumps(pdf_details, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("Directory Statistics:")
    for d, st in dir_stats.items():
        print(f"  {d}: {st}")
    print(f"Total non-checkpoint files: {summary['total_non_checkpoint_files']}")
    print(f"Total checkpoint files: {summary['total_checkpoint_files']}")
    print(f"Total PDFs (non-checkpoint): {summary['total_pdfs']}")


if __name__ == "__main__":
    main()
