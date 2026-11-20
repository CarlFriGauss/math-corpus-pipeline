#!/usr/bin/env python3
"""Stage A4: Generate 00_INDEX.md, 00_GLOSSARY.md, and publication_manifest.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_graph import build_req_adj, kahn_condensation_order, tarjan_scc  # noqa: E402
from audit_web_readiness import split_top_level_h2  # noqa: E402

KG_PATH = ROOT / "output" / "graph" / "knowledge_graph.json"
SET_2_DIR = ROOT / "output" / "set_2_corrected"
AUDIT_JSON_PATH = ROOT / "output" / "web_export" / "web_readiness_audit.json"
NAV_META_PATH = ROOT / "output" / "web_export" / "navigation_metadata.json"
INDEX_MD_PATH = ROOT / "output" / "00_INDEX.md"
GLOSSARY_MD_PATH = ROOT / "output" / "00_GLOSSARY.md"
PUB_MANIFEST_PATH = ROOT / "output" / "web_export" / "publication_manifest.json"

DEFAULT_DISCIPLINE_TO_TRACK = {
    "Real Analysis": "/academy/mathematics/",
    "Linear Algebra": "/academy/mathematics/",
    "Probability & Stochastic Processes": "/academy/probability/",
    "Statistics & Inference": "/academy/statistics/",
    "Signal Processing & Fourier Analysis": "/essays/",
    "Convex Optimization & Control": "/essays/",
    "Machine Learning & Deep Learning": "/essays/",
}


def make_slug(title: str) -> str:
    """Generate <= 65-char NFKD ASCII lowercase hyphenated slug."""
    norm = unicodedata.normalize("NFKD", title).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")[:65].strip("-")
    return slug or "essay"


def extract_clean_statement(text: str) -> str:
    """Clean whitespace/newlines in a single-line field."""
    return re.sub(r"\s+", " ", text).strip()


def make_card_summary(text: str, max_len: int = 120) -> str:
    """Generate a complete-sentence summary strictly <= max_len chars ending in '.'."""
    clean = extract_clean_statement(text)
    if not clean:
        return "Mathematical study module."
    if len(clean) <= max_len:
        return clean if clean.endswith((".", "!", "?")) else (clean[: max_len - 1].rstrip(".") + ".")
    cut = clean[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(".,;:- ")
    return (cut + ".") if cut else "Mathematical study module."


def load_navigation_metadata() -> tuple[dict[str, str], dict[str, tuple[str, str, str]], dict[str, str]]:
    """Load optional external metadata overrides from output/web_export/navigation_metadata.json."""
    if not NAV_META_PATH.exists():
        return {}, {}, dict(DEFAULT_DISCIPLINE_TO_TRACK)
    raw = json.loads(NAV_META_PATH.read_text(encoding="utf-8"))
    card_summaries = {str(k): str(v) for k, v in (raw.get("card_summaries") or {}).items()}
    split_parts: dict[str, tuple[str, str, str]] = {}
    for pid, vals in (raw.get("split_parts") or {}).items():
        if isinstance(vals, list) and len(vals) == 3:
            split_parts[str(pid)] = (str(vals[0]), str(vals[1]), str(vals[2]))
        elif isinstance(vals, dict):
            split_parts[str(pid)] = (
                str(vals.get("part_title", "")),
                str(vals.get("card_summary", "")),
                str(vals.get("full_summary", "")),
            )
    track_map = dict(DEFAULT_DISCIPLINE_TO_TRACK)
    track_map.update({str(k): str(v) for k, v in (raw.get("discipline_to_track") or {}).items()})
    return card_summaries, split_parts, track_map


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Enforce strict website character limits across all articles and all parts."""
    assert len(manifest) >= 1, "Expected at least 1 record in manifest"
    for tid, rec in manifest.items():
        assert rec["manuscript_id"] == tid
        assert 1 <= len(rec["title"]) <= 180, f"{tid} title len={len(rec['title'])}"
        assert 1 <= len(rec["slug_preview"]) <= 65, f"{tid} slug len={len(rec['slug_preview'])}"
        assert 1 <= len(rec["card_summary"]) <= 120, f"{tid} card_summary len={len(rec['card_summary'])}"
        assert rec["card_summary"].endswith("."), f"{tid} card_summary must end in '.'"
        assert 1 <= len(rec["full_summary"]) <= 500, f"{tid} full_summary len={len(rec['full_summary'])}"
        assert rec["budget_status"] in {"PASS", "WARN_SPLIT_RECOMMENDED", "OVER_LIMIT_SPLIT_REQUIRED"}
        assert rec["parts"], f"{tid} has empty parts"
        for p in rec["parts"]:
            assert 1 <= len(p["part_title"]) <= 180, f"{p['part_id']} part_title len={len(p['part_title'])}"
            assert 1 <= len(p["slug_preview"]) <= 65, f"{p['part_id']} slug len={len(p['slug_preview'])}"
            assert 1 <= len(p["card_summary"]) <= 120, f"{p['part_id']} card_summary len={len(p['card_summary'])}"
            assert p["card_summary"].endswith("."), f"{p['part_id']} card_summary must end in '.'"
            assert 1 <= len(p["full_summary"]) <= 500, f"{p['part_id']} full_summary len={len(p['full_summary'])}"
            assert p["site_uuid"] is None or isinstance(p["site_uuid"], str)
            assert p["published_url"] is None or isinstance(p["published_url"], str)


def build_publication_manifest(
    kg: dict[str, Any],
    audit: dict[str, Any],
    topic_layer: dict[str, int],
    macro_rev: dict[str, list[str]],
) -> dict[str, Any]:
    """Build publication_manifest.json keyed by T01..T{K}."""
    topic_by_id = {t["id"]: t for t in kg["topics"]}
    audit_by_id = {a["topic_id"]: a for a in audit["articles"]}
    card_overrides, split_overrides, track_map = load_navigation_metadata()

    manifest: dict[str, Any] = {}
    for tid in sorted(topic_by_id.keys(), key=lambda x: int(x[1:])):
        tm = topic_by_id[tid]
        au = audit_by_id[tid]
        title = au["title"][:180]
        full_summary = extract_clean_statement(tm["summary"])[:500]
        card_summary = card_overrides.get(tid) or make_card_summary(full_summary)
        prereq_ids = sorted(macro_rev[tid], key=lambda x: int(x[1:]))

        parts: list[dict[str, Any]] = []
        if au["proposed_splits"]:
            n_parts = len(au["proposed_splits"])
            for p in au["proposed_splits"]:
                pid = f"{tid}_p{p['part_index']}"
                if pid in split_overrides:
                    part_title, part_card, part_full = split_overrides[pid]
                else:
                    part_title = f"{title} (Part {p['part_index']} of {n_parts})"[:180]
                    sec_desc = f"Covers {p['start_heading'].lstrip('# ').strip()} through {p['end_heading'].lstrip('# ').strip()}."
                    part_card = make_card_summary(sec_desc)
                    part_full = extract_clean_statement(f"{sec_desc} {full_summary}")[:500]
                parts.append({
                    "part_id": pid,
                    "part_index": p["part_index"],
                    "part_count": n_parts,
                    "part_title": part_title,
                    "slug_preview": make_slug(part_title),
                    "card_summary": part_card,
                    "full_summary": part_full,
                    "start_heading": p["start_heading"],
                    "end_heading": p["end_heading"],
                    "section_headings": p["section_headings"],
                    "est_pg_jsonb_bytes": p["est_pg_jsonb_bytes"],
                    "est_visited_nodes": p["est_visited_nodes"],
                    "site_uuid": None,
                    "published_url": None,
                })
        else:
            raw_text = (SET_2_DIR / tm["filename"]).read_text(encoding="utf-8")
            _pre, sections = split_top_level_h2(raw_text)
            start_h = f"## {sections[0][0]}" if sections else ""
            end_h = f"## {sections[-1][0]}" if sections else ""
            parts.append({
                "part_id": f"{tid}_p1",
                "part_index": 1,
                "part_count": 1,
                "part_title": title,
                "slug_preview": make_slug(title),
                "card_summary": card_summary,
                "full_summary": full_summary,
                "start_heading": start_h,
                "end_heading": end_h,
                "section_headings": [f"## {h}" for h, _ in sections],
                "est_pg_jsonb_bytes": au["metrics"]["est_pg_jsonb_bytes"],
                "est_visited_nodes": au["metrics"]["est_visited_nodes"],
                "site_uuid": None,
                "published_url": None,
            })

        manifest[tid] = {
            "manuscript_id": tid,
            "source_filename": tm["filename"],
            "discipline": tm["discipline"],
            "academy_track": track_map.get(tm["discipline"], "/essays/"),
            "topological_layer": topic_layer[tid],
            "prerequisite_ids": prereq_ids,
            "title": title,
            "slug_preview": make_slug(title),
            "card_summary": card_summary,
            "full_summary": full_summary,
            "budget_status": au["budget_status"],
            "parts": parts,
            "planned_demos": [],
            "planned_media": [],
        }

    validate_manifest(manifest)
    return manifest


def write_index_md(
    manifest: dict[str, Any],
    audit: dict[str, Any],
    topic_layer: dict[str, int],
) -> None:
    """Generate output/00_INDEX.md sorted strictly by (layer, topic_id)."""
    audit_by_id = {a["topic_id"]: a for a in audit["articles"]}
    ordered_ids = sorted(manifest.keys(), key=lambda t: (topic_layer[t], int(t[1:])))

    total_words = sum(audit_by_id[t]["word_count"] for t in ordered_ids)
    total_parts = sum(len(manifest[t]["parts"]) for t in ordered_ids)
    max_layer = max((topic_layer[t] for t in ordered_ids), default=0)

    lines: list[str] = [
        "# Master Curriculum Index (`output/set_2_corrected/`)",
        "",
        f"Complete navigable index across all **{len(ordered_ids)} standalone articles** ({total_words:,} total words; **{total_parts}** website-ready essay parts) ordered strictly by condensation topological layer `(layer, topic_id)` from `output/graph/knowledge_graph.json`.",
        "",
        f"## 1. Master Curriculum Order (Sorted by Layer `0 -> {max_layer}`)",
        "",
        "| Layer | ID | Title & Source File | Discipline Track | Website Section | Words | Direct Prerequisites | ProseMirror Budget |",
        "| :---: | :---: | :--- | :--- | :--- | ---: | :--- | :--- |",
    ]

    for tid in ordered_ids:
        rec = manifest[tid]
        au = audit_by_id[tid]
        prereqs = ", ".join(rec["prerequisite_ids"]) if rec["prerequisite_ids"] else "*(root)*"
        n_parts = len(rec["parts"])
        budget_col = "`PASS`" if rec["budget_status"] == "PASS" else f"`SPLIT ({n_parts} parts)` — `{rec['budget_status']}`"
        file_link = f"[{rec['title']}](set_2_corrected/{rec['source_filename']})"
        lines.append(
            f"| {rec['topological_layer']} | **{tid}** | {file_link} | {rec['discipline']} | `{rec['academy_track']}` | "
            f"{au['word_count']:,} | {prereqs} | {budget_col} |"
        )

    lines.extend([
        "",
        "## 2. Website Academy & Essay Reading Tracks",
        "",
        "Topics grouped by discipline and mapped to their target taxonomy routes:",
        "",
    ])

    by_track: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for tid in ordered_ids:
        rec = manifest[tid]
        by_track[rec["academy_track"]][rec["discipline"]].append(tid)

    for track in sorted(by_track.keys()):
        lines.append(f"### `{track}`")
        lines.append("")
        for disc in sorted(by_track[track].keys()):
            tids = by_track[track][disc]
            lines.append(f"- **{disc}:** " + " -> ".join(f"**{t}**" for t in tids))
            for t in tids:
                rec = manifest[t]
                split_tag = f" *(split into {len(rec['parts'])} web parts)*" if len(rec["parts"]) > 1 else ""
                lines.append(f"  - **{t} (L{rec['topological_layer']}):** [{rec['title']}](set_2_corrected/{rec['source_filename']}){split_tag} — {rec['card_summary']}")
        lines.append("")

    INDEX_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def clean_sort_key(name: str) -> str:
    """Sort key stripping LaTeX markers so math symbols alphabetize cleanly."""
    stripped = re.sub(r"[$\\{}^_]", "", name)
    return stripped.strip().casefold()


def write_glossary_md(kg: dict[str, Any]) -> None:
    """Generate output/00_GLOSSARY.md covering all canonical concepts."""
    topic_by_id = {t["id"]: t for t in kg["topics"]}
    concept_by_id = {c["id"]: c for c in kg["concepts"]}

    downstream_map: dict[str, set[str]] = {c["id"]: set(c["referenced_in_topics"]) for c in kg["concepts"]}
    for e in kg["micro_edges"]:
        if e["relation"] == "requires":
            src, dst = e["source"], e["target"]
            downstream_map[src].add(concept_by_id[dst]["canonical_topic_id"])
    for cid, c in concept_by_id.items():
        downstream_map[cid].discard(c["canonical_topic_id"])

    lines: list[str] = [
        f"# Master Mathematical Glossary ({len(kg['concepts'])} Canonical Concepts)",
        "",
        "Derived strictly from `output/graph/knowledge_graph.json` and `output/set_2_corrected/`. Every concept lists its canonical kind, rigorous 1-sentence statement, canonical home article (`T##`), and downstream articles that depend on it.",
        "",
        "## 1. Discipline-Indexed Concept Directory",
        "",
    ]

    by_disc_topic: defaultdict[str, defaultdict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for c in kg["concepts"]:
        home = topic_by_id[c["canonical_topic_id"]]
        by_disc_topic[home["discipline"]][home["id"]].append(c)

    for disc in sorted(by_disc_topic.keys()):
        lines.append(f"### {disc}")
        lines.append("")
        for tid in sorted(by_disc_topic[disc].keys(), key=lambda x: int(x[1:])):
            tm = topic_by_id[tid]
            concepts = sorted(by_disc_topic[disc][tid], key=lambda x: clean_sort_key(x["name"]))
            lines.append(f"#### {tid}: [{tm['title']}](set_2_corrected/{tm['filename']}) ({len(concepts)} concepts)")
            lines.append("")
            for c in concepts:
                ds = sorted(downstream_map[c["id"]], key=lambda x: int(x[1:]))
                ds_str = ", ".join(ds) if ds else "*(leaf / local)*"
                lines.append(
                    f"- **{c['name']}** (`{c['kind']}`, `{c['id']}`) — {c['short_statement']} "
                    f"*Home:* `{tid}` (`{c['section_anchor']}`) | *Downstream:* {ds_str}"
                )
            lines.append("")

    lines.extend([
        f"## 2. Alphabetical Master Glossary (All {len(kg['concepts'])} Concepts)",
        "",
        "| Concept | Kind | Canonical Home | Downstream Articles | Rigorous Statement |",
        "| :--- | :---: | :---: | :--- | :--- |",
    ])

    for c in sorted(kg["concepts"], key=lambda x: (clean_sort_key(x["name"]), x["id"])):
        tid = c["canonical_topic_id"]
        tm = topic_by_id[tid]
        ds = sorted(downstream_map[c["id"]], key=lambda x: int(x[1:]))
        ds_str = ", ".join(ds) if ds else "—"
        stmt = c["short_statement"].replace("|", "\\lvert ")
        name_safe = c["name"].replace("|", "\\lvert ")
        home_link = f"[{tid}](set_2_corrected/{tm['filename']})"
        lines.append(f"| **{name_safe}** | `{c['kind']}` | {home_link} | {ds_str} | {stmt} |")
    lines.append("")

    GLOSSARY_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage A4: Build 00_INDEX.md, 00_GLOSSARY.md, and publication_manifest.json.")
    parser.parse_args()

    kg = json.loads(KG_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_JSON_PATH.read_text(encoding="utf-8"))

    topic_ids = [t["id"] for t in kg["topics"]]
    macro_fwd, macro_rev = build_req_adj(topic_ids, kg["macro_edges"])
    macro_sccs = tarjan_scc(topic_ids, macro_fwd)
    _topo_comps, topic_layer = kahn_condensation_order(topic_ids, macro_fwd, macro_sccs)

    manifest = build_publication_manifest(kg, audit, topic_layer, macro_rev)
    PUB_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUB_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    write_index_md(manifest, audit, topic_layer)
    write_glossary_md(kg)

    total_parts = sum(len(r["parts"]) for r in manifest.values())
    print(f"Wrote {PUB_MANIFEST_PATH} ({len(manifest)} articles, {total_parts} web parts)")
    print(f"Wrote {INDEX_MD_PATH}")
    print(f"Wrote {GLOSSARY_MD_PATH} ({len(kg['concepts'])} concepts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
