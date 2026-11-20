#!/usr/bin/env python3
"""Deterministic two-state incremental rebuild wrapper for Set 2 manuscripts.

Decouples local HTML / web export build state (`output/build_state.json`) from
semantic knowledge-graph state (`output/graph/knowledge_graph.json`) while
enforcing STYLE_GUIDE.md quality gates, anchor/manifest parity, Pandoc
`<pre><code>` LaTeX-leak scanning, and structural-delta classification.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_graph import (  # noqa: E402
    VALID_KINDS,
    VALID_RELATIONS,
    build_req_adj,
    kahn_condensation_order,
    tarjan_scc,
    validate_knowledge_graph,
)
from audit_web_readiness import split_top_level_h2  # noqa: E402

FORMAL_CALLOUT_RE = re.compile(
    r"^>\s*\*\*(Axiom|Definition|Theorem|Proposition|Lemma|Corollary)\b.*"
)
HEADING_2_4_RE = re.compile(r"^\s{0,3}(#{2,4})\s+\S")
FENCE_OPEN_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")

RAW_DOLLAR_RE = re.compile(r"\$")
LATEX_LEAK_RE = re.compile(r"\\(?:[a-zA-Z]+|[\[\]\(\)\\|,:;!>])")


@dataclass
class BuildConfig:
    """Resolved workspace paths used by the incremental rebuild pipeline."""

    root: Path
    scripts_dir: Path
    set_2_dir: Path
    build_state_path: Path
    kg_path: Path
    pub_manifest_path: Path
    local_html_dir: Path
    web_validation_path: Path

    @classmethod
    def from_root(cls, root: Path = ROOT) -> BuildConfig:
        return cls(
            root=root,
            scripts_dir=root / "scripts",
            set_2_dir=root / "output" / "set_2_corrected",
            build_state_path=root / "output" / "build_state.json",
            kg_path=root / "output" / "graph" / "knowledge_graph.json",
            pub_manifest_path=root / "output" / "web_export" / "publication_manifest.json",
            local_html_dir=root / "output" / "local_html",
            web_validation_path=root / "output" / "web_export" / "EXPORT_VALIDATION.md",
        )


def utc_now_iso() -> str:
    """Return current UTC timestamp in canonical ISO-8601 Z format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Read UTF-8 JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write formatted UTF-8 JSON file with trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_markdown_snapshot(path: Path) -> dict[str, Any]:
    """Extract deterministic structural snapshot from a Set 2 Markdown file."""
    raw_bytes = path.read_bytes()
    raw_text = raw_bytes.decode("utf-8")
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    word_count = len(raw_text.split())

    headings: list[str] = []
    formal_callouts: list[str] = []
    in_fence = False
    fence_char = "`"
    fence_len = 3

    for ln in raw_text.splitlines():
        if not in_fence:
            m_open = FENCE_OPEN_RE.match(ln)
            if m_open:
                in_fence = True
                fence_char = m_open.group(1)[0]
                fence_len = len(m_open.group(1))
                continue
        else:
            if re.match(
                rf"^\s{{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$",
                ln.rstrip("\r\n"),
            ):
                in_fence = False
            continue

        if HEADING_2_4_RE.match(ln):
            headings.append(ln.strip())
        elif FORMAL_CALLOUT_RE.match(ln):
            formal_callouts.append(ln.strip())

    return {
        "sha256": sha256,
        "word_count": word_count,
        "headings": headings,
        "formal_callouts": formal_callouts,
        "raw_text": raw_text,
    }


def resolve_topic_id(
    filename: str,
    kg_fn_to_tid: dict[str, str],
    pm_fn_to_tid: dict[str, str],
) -> str:
    """Resolve canonical topic ID (e.g., T01) for a Set 2 Markdown filename."""
    if filename in kg_fn_to_tid:
        return kg_fn_to_tid[filename]
    if filename in pm_fn_to_tid:
        return pm_fn_to_tid[filename]
    m = re.match(r"^(\d+)_", filename)
    if m:
        return f"T{int(m.group(1)):02d}"
    raise ValueError(f"Cannot infer topic_id for Set 2 filename: {filename!r}")


def load_build_state_files(path: Path) -> dict[str, dict[str, Any]]:
    """Load file entries from output/build_state.json (or return empty dict if absent)."""
    if not path.exists():
        return {}
    data = load_json(path)
    if "files" in data and isinstance(data["files"], dict):
        return dict(data["files"])
    return {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and "sha256" in v
    }


def save_build_state(
    path: Path,
    files_map: dict[str, dict[str, Any]],
    source_dir: str = "output/set_2_corrected",
) -> None:
    """Persist decoupled build ledger to output/build_state.json."""
    ordered_files = {fn: files_map[fn] for fn in sorted(files_map)}
    now = utc_now_iso()
    generated_utc = now
    if path.exists():
        try:
            old = load_json(path)
            generated_utc = old.get("generated_utc", now)
        except Exception:
            pass

    payload = {
        "schema_version": "1.0",
        "generated_utc": generated_utc,
        "last_updated_utc": now,
        "source_dir": source_dir,
        "file_count": len(ordered_files),
        "files": ordered_files,
    }
    write_json(path, payload)


def parse_topic_filter(
    topic_arg: str,
    live_by_tid: dict[str, str],
) -> list[str]:
    """Parse comma-separated --topic tokens (e.g., T08,14) into sorted filenames."""
    filenames: list[str] = []
    seen: set[str] = set()
    for raw_tok in topic_arg.split(","):
        tok = raw_tok.strip().upper()
        if not tok:
            continue
        if not tok.startswith("T") and tok.isdigit():
            tok = f"T{int(tok):02d}"
        elif tok.startswith("T") and tok[1:].isdigit():
            tok = f"T{int(tok[1:]):02d}"
        if tok not in live_by_tid:
            raise ValueError(f"Unknown or missing Set 2 topic ID: {raw_tok!r} (resolved {tok!r})")
        fn = live_by_tid[tok]
        if fn not in seen:
            seen.add(fn)
            filenames.append(fn)
    return sorted(filenames)


def diff_sequence(old_items: list[str], new_items: list[str]) -> tuple[list[str], list[str]]:
    """Return ordered (removed, added) items between two lists via SequenceMatcher."""
    removed: list[str] = []
    added: list[str] = []
    sm = difflib.SequenceMatcher(None, old_items, new_items)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            removed.extend(old_items[i1:i2])
        if tag in ("insert", "replace"):
            added.extend(new_items[j1:j2])
    return removed, added


def classify_file_change(
    filename: str,
    topic_id: str,
    cur_snap: dict[str, Any],
    prev_entry: dict[str, Any] | None,
    kg: dict[str, Any],
    kg_topic_ids: set[str],
    minor_word_threshold: int,
) -> dict[str, Any]:
    """Classify a file change as MINOR, SUBSTANTIVE, or UNCHANGED (forced)."""
    recorded_kg_sha = kg.get("source_hashes", {}).get(filename)
    in_kg = (recorded_kg_sha is not None) and (topic_id in kg_topic_ids)
    in_build = prev_entry is not None

    html_stale = (not in_build) or (cur_snap["sha256"] != prev_entry["sha256"])
    kg_stale = (not in_kg) or (cur_snap["sha256"] != recorded_kg_sha)

    prev_wc = prev_entry["word_count"] if prev_entry else 0
    prev_headings = prev_entry["headings"] if prev_entry else []
    prev_callouts = prev_entry["formal_callouts"] if prev_entry else []

    wc_delta = cur_snap["word_count"] - prev_wc
    removed_headings, added_headings = diff_sequence(prev_headings, cur_snap["headings"])
    removed_callouts, added_callouts = diff_sequence(prev_callouts, cur_snap["formal_callouts"])

    reasons: list[str] = []
    if not in_build:
        classification = "SUBSTANTIVE"
        reasons.append("new untracked file (missing from build_state.json)")
    elif not in_kg:
        classification = "SUBSTANTIVE"
        reasons.append("untracked topic/file (missing from knowledge_graph.json)")
    elif not html_stale and not kg_stale:
        classification = "UNCHANGED"
        reasons.append("matches both build_state.json and knowledge_graph.json")
    elif not html_stale and kg_stale:
        classification = "SUBSTANTIVE"
        reasons.append(
            "knowledge_graph.json source_hashes is stale while build_state.json already "
            "advanced past the graph baseline; semantic graph review is required"
        )
    else:
        if cur_snap["headings"] != prev_headings:
            reasons.append(
                f"headings changed (-{len(removed_headings)}/+{len(added_headings)})"
            )
        if cur_snap["formal_callouts"] != prev_callouts:
            reasons.append(
                f"formal_callouts changed (-{len(removed_callouts)}/+{len(added_callouts)})"
            )
        if abs(wc_delta) >= minor_word_threshold:
            reasons.append(
                f"abs(word_count_delta)={abs(wc_delta)} >= threshold ({minor_word_threshold})"
            )
        classification = "SUBSTANTIVE" if reasons else "MINOR"
        if classification == "MINOR":
            reasons.append(
                f"tracked in knowledge_graph.json, headings & callouts identical, "
                f"abs(word_count_delta)={abs(wc_delta)} < {minor_word_threshold}"
            )

    return {
        "filename": filename,
        "topic_id": topic_id,
        "classification": classification,
        "reasons": reasons,
        "html_stale": html_stale,
        "kg_stale": kg_stale,
        "prev_word_count": prev_wc,
        "cur_word_count": cur_snap["word_count"],
        "word_count_delta": wc_delta,
        "removed_headings": removed_headings,
        "added_headings": added_headings,
        "removed_callouts": removed_callouts,
        "added_callouts": added_callouts,
    }


class _PandocPreCodeParser(HTMLParser):
    """Parse <pre><code> blocks in Pandoc HTML while tracking classes and <div class='sourceCode'>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self._div_stack: list[set[str]] = []
        self._skip_depth = 0
        self._in_pre = False
        self._in_code = False
        self._pre_classes: set[str] = set()
        self._code_classes: set[str] = set()
        self._pre_in_source_div = False
        self._pre_line = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        cls_set = set((attr_map.get("class") or "").split())

        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if tag == "div":
            self._div_stack.append(cls_set)
        elif tag == "pre":
            self._in_pre = True
            self._pre_classes = cls_set
            self._code_classes = set()
            self._pre_in_source_div = any("sourceCode" in d for d in self._div_stack)
            self._pre_line = self.getpos()[0]
            self._buf = []
        elif tag == "code" and self._in_pre:
            self._in_code = True
            self._code_classes.update(cls_set)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return

        if tag == "div" and self._div_stack:
            self._div_stack.pop()
        elif tag == "code" and self._in_pre:
            self._in_code = False
        elif tag == "pre" and self._in_pre:
            self.blocks.append({
                "line": self._pre_line,
                "pre_classes": sorted(self._pre_classes),
                "code_classes": sorted(self._code_classes),
                "in_source_div": self._pre_in_source_div,
                "text": "".join(self._buf),
            })
            self._in_pre = False
            self._in_code = False
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and self._in_pre and self._in_code:
            self._buf.append(data)


def scan_html_code_leaks(html_path: Path) -> list[dict[str, Any]]:
    """Detect unintended bare <pre><code> blocks containing raw $ or LaTeX commands.

    Legitimate fenced code blocks in Set 2 emit `<div class='sourceCode'><pre class='sourceCode ...'>`
    or `<pre class='text'><code>` (or explicit language classes), whereas Pandoc renders accidental
    indented-code blocks as bare `<pre><code>` without any language or sourceCode class.
    """
    parser = _PandocPreCodeParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    parser.close()

    leaks: list[dict[str, Any]] = []
    for blk in parser.blocks:
        is_explicit_fenced = (
            blk["in_source_div"]
            or bool(blk["pre_classes"])
            or bool(blk["code_classes"])
        )
        if is_explicit_fenced:
            continue

        txt = blk["text"]
        m_dollar = RAW_DOLLAR_RE.search(txt)
        m_latex = LATEX_LEAK_RE.search(txt)
        if m_dollar or m_latex:
            tok = m_dollar.group(0) if m_dollar else m_latex.group(0)  # type: ignore[union-attr]
            first_ln = txt.strip().splitlines()[0][:120] if txt.strip() else ""
            leaks.append({
                "file": html_path.name,
                "line": blk["line"],
                "token": tok,
                "snippet": first_ln,
            })
    return leaks


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a child Python command in cwd capturing UTF-8 stdout/stderr."""
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def check_notation_gold_standard(report: dict[str, Any]) -> list[str]:
    """Verify strict gold-standard notation & callout counts on a single JSON report."""
    failures: list[str] = []
    cs = report["callout_summary"]
    ms = report["markers_summary"]

    if report["hard_violation_count"] != 0:
        failures.append(f"HARD VIOLATIONS={report['hard_violation_count']}")
    if cs["non_blockquote_formal_count"] != 0:
        failures.append(f"non_blockquote_formal={cs['non_blockquote_formal_count']}")
    if cs["proof_blockquote_count"] != 0:
        failures.append(f"proof_blockquote={cs['proof_blockquote_count']}")
    if cs["proof_italic_count"] != 0:
        failures.append(f"proof_italic={cs['proof_italic_count']}")
    if cs["proof_heading_count"] != 0:
        failures.append(f"proof_heading={cs['proof_heading_count']}")
    if ms["qed_legacy"] != 0:
        failures.append(f"legacy_qed={ms['qed_legacy']}")
    return failures


def check_topic_parity(
    filename: str,
    topic_id: str,
    snap: dict[str, Any],
    kg: dict[str, Any],
    pub_manifest: dict[str, Any],
    require_in_kg: bool = False,
) -> tuple[list[str], list[str]]:
    """Verify 100% KG section_anchor parity and publication_manifest ## split-boundary parity."""
    errors: list[str] = []
    warnings: list[str] = []

    kg_topics = {t["id"]: t for t in kg.get("topics", [])}
    if topic_id in kg_topics:
        if kg_topics[topic_id]["filename"] != filename:
            errors.append(
                f"knowledge_graph.json filename mismatch for {topic_id}: "
                f"expected {kg_topics[topic_id]['filename']!r}, got {filename!r}"
            )
        heading_set = set(snap["headings"])
        missing_anchors = [
            (c["id"], c["section_anchor"])
            for c in kg.get("concepts", [])
            if c["canonical_topic_id"] == topic_id and c["section_anchor"] not in heading_set
        ]
        if missing_anchors:
            sample = ", ".join(f"{cid}: {anc!r}" for cid, anc in missing_anchors[:5])
            errors.append(
                f"{len(missing_anchors)} knowledge_graph section_anchor(s) missing for {topic_id}: {sample}"
            )
    elif require_in_kg:
        errors.append(f"{topic_id} ({filename}) is not registered in knowledge_graph.json topics")

    if topic_id not in pub_manifest:
        errors.append(
            f"{topic_id} ({filename}) is missing from output/web_export/publication_manifest.json"
        )
        return errors, warnings

    rec = pub_manifest[topic_id]
    if rec.get("source_filename") != filename:
        errors.append(
            f"publication_manifest.json source_filename mismatch for {topic_id}: "
            f"expected {rec.get('source_filename')!r}, got {filename!r}"
        )

    _, sections = split_top_level_h2(snap["raw_text"])
    live_h2 = [f"## {h}" for h, _ in sections]
    parts = rec.get("parts", [])
    if not parts:
        errors.append(f"publication_manifest.json has empty parts list for {topic_id}")
        return errors, warnings

    pm_h2: list[str] = []
    for part in parts:
        sec_list = part.get("section_headings", [])
        if not sec_list:
            errors.append(f"{part.get('part_id', topic_id)} has empty section_headings in publication_manifest.json")
            continue
        if part.get("start_heading") != sec_list[0]:
            errors.append(
                f"{part.get('part_id', topic_id)} start_heading {part.get('start_heading')!r} != {sec_list[0]!r}"
            )
        if part.get("end_heading") != sec_list[-1]:
            errors.append(
                f"{part.get('part_id', topic_id)} end_heading {part.get('end_heading')!r} != {sec_list[-1]!r}"
            )
        pm_h2.extend(sec_list)

    if len(parts) > 1:
        if live_h2 != pm_h2:
            rem, add = diff_sequence(pm_h2, live_h2)
            errors.append(
                f"{topic_id} multi-part ## split-boundary mismatch vs publication_manifest.json "
                f"(removed={rem}, added={add})"
            )
    elif live_h2 != pm_h2:
        rem, add = diff_sequence(pm_h2, live_h2)
        warnings.append(
            f"{topic_id} single-part ## list differs from publication_manifest.json "
            f"(removed={rem}, added={add}); run build_navigation.py if refreshing metadata"
        )

    return errors, warnings


def validate_kg_schema_for_sync(
    kg: dict[str, Any],
    syncing_filenames: set[str],
) -> tuple[bool, list[str]]:
    """Validate knowledge_graph.json schema & DAG acyclicity prior to syncing source_hashes."""
    errors: list[str] = []
    required_root = {
        "schema_version",
        "generated_utc",
        "source_dir",
        "topic_count",
        "source_hashes",
        "topics",
        "concepts",
        "micro_edges",
        "macro_edges",
    }
    missing = required_root - set(kg.keys())
    if missing:
        errors.append(f"Missing root keys in knowledge_graph.json: {sorted(missing)}")
        return False, errors
    if kg["topic_count"] != len(kg["topics"]):
        errors.append(f"topic_count={kg['topic_count']} != len(topics)={len(kg['topics'])}")

    topic_map: dict[str, dict[str, Any]] = {}
    for t in kg["topics"]:
        tid = t["id"]
        fn = t["filename"]
        if tid in topic_map:
            errors.append(f"Duplicate topic id: {tid}")
        if fn not in kg["source_hashes"] and fn not in syncing_filenames:
            errors.append(f"Missing source_hashes entry for {fn}")
        topic_map[tid] = t

    concept_map: dict[str, dict[str, Any]] = {}
    for c in kg["concepts"]:
        cid = c["id"]
        if cid in concept_map:
            errors.append(f"Duplicate concept id: {cid}")
        if not cid.startswith("C_"):
            errors.append(f"Invalid concept id prefix: {cid}")
        if c["kind"] not in VALID_KINDS:
            errors.append(f"Invalid concept kind for {cid}: {c['kind']}")
        ctid = c["canonical_topic_id"]
        if ctid not in topic_map:
            errors.append(f"Dangling canonical_topic_id {ctid} on {cid}")
        if ctid not in c["referenced_in_topics"]:
            errors.append(f"{cid} missing canonical_topic_id in referenced_in_topics")
        for rtid in c["referenced_in_topics"]:
            if rtid not in topic_map:
                errors.append(f"Dangling referenced_in_topics {rtid} on {cid}")
        concept_map[cid] = c

    seen_micro: set[tuple[str, str, str]] = set()
    for e in kg["micro_edges"]:
        u, v, rel = e["source"], e["target"], e["relation"]
        if u not in concept_map or v not in concept_map:
            errors.append(f"Dangling micro edge endpoint: {u} -> {v}")
        if u == v:
            errors.append(f"Self-loop on micro edge: {u}")
        if rel not in VALID_RELATIONS:
            errors.append(f"Invalid micro relation: {rel}")
        if (u, v, rel) in seen_micro:
            errors.append(f"Duplicate micro edge: {(u, v, rel)}")
        seen_micro.add((u, v, rel))

    seen_macro: set[tuple[str, str, str]] = set()
    for me in kg["macro_edges"]:
        u, v, rel = me["source"], me["target"], me["relation"]
        if u not in topic_map or v not in topic_map:
            errors.append(f"Dangling macro edge endpoint: {u} -> {v}")
        if u == v:
            errors.append(f"Self-loop on macro edge: {u}")
        if rel not in VALID_RELATIONS:
            errors.append(f"Invalid macro relation: {rel}")
        if (u, v, rel) in seen_macro:
            errors.append(f"Duplicate macro edge: {(u, v, rel)}")
        seen_macro.add((u, v, rel))
        if me["weight"] != len(me["supporting_concept_edges"]):
            errors.append(f"Weight mismatch on macro edge {u} -> {v}")
        for cu, cv in me["supporting_concept_edges"]:
            if (cu, cv, rel) not in seen_micro:
                errors.append(f"Missing supporting micro edge {(cu, cv, rel)}")
            if cu in concept_map and concept_map[cu]["canonical_topic_id"] != u:
                errors.append(f"Supporting edge {cu} canonical_topic_id != {u}")
            if cv in concept_map and concept_map[cv]["canonical_topic_id"] != v:
                errors.append(f"Supporting edge {cv} canonical_topic_id != {v}")

    if not errors:
        topic_ids = [t["id"] for t in kg["topics"]]
        concept_ids = [c["id"] for c in kg["concepts"]]
        micro_fwd, _ = build_req_adj(concept_ids, kg["micro_edges"])
        macro_fwd, _ = build_req_adj(topic_ids, kg["macro_edges"])
        micro_sccs = tarjan_scc(concept_ids, micro_fwd)
        macro_sccs = tarjan_scc(topic_ids, macro_fwd)
        micro_cycles = [c for c in micro_sccs if len(c) > 1]
        if micro_cycles:
            errors.append(f"Micro G_req contains cycles: {micro_cycles}")
        try:
            kahn_condensation_order(topic_ids, macro_fwd, macro_sccs)
        except AssertionError as exc:
            errors.append(str(exc))

    return not errors, errors


def verify_export_validation_report(path: Path) -> tuple[bool, list[str]]:
    """Verify output/web_export/EXPORT_VALIDATION.md reports 100% PASS."""
    if not path.exists():
        return False, [f"Missing web validation report: {path}"]

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    m_total = re.search(r"\*\*Total Exported Web Essays:\*\*\s*(\d+)", text)
    if not m_total:
        errors.append("EXPORT_VALIDATION.md missing Total Exported Web Essays count")
        return False, errors
    expected_total = int(m_total.group(1))
    if expected_total <= 0:
        errors.append(f"EXPORT_VALIDATION.md reports {expected_total} essays")

    if "**100% PASS Verification:** PASSED" not in text:
        errors.append("EXPORT_VALIDATION.md did not report 100% PASS Verification: PASSED")

    row_count = 0
    for ln in text.splitlines():
        if ln.startswith("| **T"):
            row_count += 1
            cols = [c.strip() for c in ln.strip("|").split("|")]
            status = cols[-1] if cols else ""
            if status != "`PASS`":
                part_id = cols[0] if cols else "?"
                errors.append(f"{part_id} web export status is {status}, expected `PASS`")

    if row_count != expected_total:
        errors.append(
            f"EXPORT_VALIDATION.md row count ({row_count}) != declared total ({expected_total})"
        )
    return not errors, errors


def run_per_file_gates(
    cfg: BuildConfig,
    items: list[dict[str, Any]],
    snapshots: dict[str, dict[str, Any]],
    kg: dict[str, Any],
    pub_manifest: dict[str, Any],
    require_in_kg: bool = False,
) -> bool:
    """Run all 4 strict per-file quality & parity gates (fail-fast)."""
    print("\n=== Step 2: Strict Per-File Quality & Parity Gates ===")
    for item in items:
        fn = item["filename"]
        tid = item["topic_id"]
        md_path = cfg.set_2_dir / fn
        snap = snapshots[fn]

        # Gate 1: verify_set_2.py --file <file>
        p1 = run_cmd(
            [sys.executable, str(cfg.scripts_dir / "verify_set_2.py"), "--file", fn],
            cfg.root,
        )
        if p1.returncode != 0:
            print(f"[FAIL][Gate 1: verify_set_2] {fn}")
            if p1.stdout.strip():
                print(p1.stdout.strip())
            if p1.stderr.strip():
                print(p1.stderr.strip())
            return False

        # Gate 2: audit_math_layout.py <file> --json -> TOTAL VIOLATIONS: 0
        p2 = run_cmd(
            [sys.executable, str(cfg.scripts_dir / "audit_math_layout.py"), str(md_path), "--json"],
            cfg.root,
        )
        if p2.returncode != 0:
            print(f"[FAIL][Gate 2: audit_math_layout] {fn}")
            p2_txt = run_cmd(
                [sys.executable, str(cfg.scripts_dir / "audit_math_layout.py"), str(md_path)],
                cfg.root,
            )
            print(p2_txt.stdout.strip() or p2.stderr.strip())
            return False
        rep2 = json.loads(p2.stdout)
        if rep2.get("total_violations", 1) != 0:
            print(f"[FAIL][Gate 2: audit_math_layout] {fn} total_violations={rep2.get('total_violations')}")
            return False

        # Gate 3: audit_notation_protocol.py <file> --json
        p3 = run_cmd(
            [sys.executable, str(cfg.scripts_dir / "audit_notation_protocol.py"), str(md_path), "--json"],
            cfg.root,
        )
        if p3.returncode != 0:
            print(f"[FAIL][Gate 3: audit_notation_protocol] {fn}")
            p3_txt = run_cmd(
                [sys.executable, str(cfg.scripts_dir / "audit_notation_protocol.py"), str(md_path)],
                cfg.root,
            )
            print(p3_txt.stdout.strip() or p3.stderr.strip())
            return False
        rep3 = json.loads(p3.stdout)
        bad3 = check_notation_gold_standard(rep3)
        if bad3:
            print(f"[FAIL][Gate 3: audit_notation_protocol] {fn}: {', '.join(bad3)}")
            return False

        # Gate 4: KG section_anchor parity & publication_manifest ## split-boundary parity
        parity_errs, parity_warns = check_topic_parity(
            fn, tid, snap, kg, pub_manifest, require_in_kg=require_in_kg
        )
        for w in parity_warns:
            print(f"  [WARN][Gate 4: Parity] {w}")
        if parity_errs:
            for e in parity_errs:
                print(f"[FAIL][Gate 4: Parity] {e}")
            return False

        print(
            f"[PASS] {tid} ({fn}) | verify=OK | layout=0 | notation=0_hard "
            f"| callouts_ok | parity=OK"
        )
    return True


def print_structural_report(items: list[dict[str, Any]], minor_word_threshold: int) -> None:
    """Print detailed per-file structural classification and diff."""
    print(f"\n=== Step 1: Structural-Delta Classification (threshold={minor_word_threshold} words) ===")
    for it in items:
        cls = it["classification"]
        tid = it["topic_id"]
        fn = it["filename"]
        delta = it["word_count_delta"]
        sign = "+" if delta >= 0 else ""
        print(
            f"- [{cls}] {tid}: {fn} | words={it['prev_word_count']} -> {it['cur_word_count']} "
            f"({sign}{delta}) | html_stale={it['html_stale']} | kg_stale={it['kg_stale']}"
        )
        for r in it["reasons"]:
            print(f"    reason: {r}")
        if it["removed_headings"] or it["added_headings"]:
            print("    heading diff:")
            for h in it["removed_headings"]:
                print(f"      - {h}")
            for h in it["added_headings"]:
                print(f"      + {h}")
        if it["removed_callouts"] or it["added_callouts"]:
            print("    formal_callout diff:")
            for c in it["removed_callouts"]:
                print(f"      - {c}")
            for c in it["added_callouts"]:
                print(f"      + {c}")


def run_init(cfg: BuildConfig, dry_run: bool) -> int:
    """Verify all Set 2 files + local HTML files read-only and seed build_state.json."""
    print("=== Mode: --init (Baseline Verification & Ledger Seeding) ===")
    if not cfg.set_2_dir.exists():
        print(f"ERROR: Missing {cfg.set_2_dir}")
        return 1

    kg = load_json(cfg.kg_path)
    pub_manifest = load_json(cfg.pub_manifest_path)
    kg_fn_to_tid = {t["filename"]: t["id"] for t in kg.get("topics", [])}
    pm_fn_to_tid = {rec["source_filename"]: tid for tid, rec in pub_manifest.items()}

    md_files = sorted(cfg.set_2_dir.glob("*.md"))
    print(f"Scanning {len(md_files)} Set 2 articles in {cfg.set_2_dir}...")

    # 1. verify_set_2.py (all)
    p1 = run_cmd([sys.executable, str(cfg.scripts_dir / "verify_set_2.py")], cfg.root)
    if p1.returncode != 0:
        print("[FAIL] verify_set_2.py failed:")
        print(p1.stdout.strip() or p1.stderr.strip())
        return 1
    print(f"[PASS] verify_set_2.py ({len(md_files)}/{len(md_files)} OK)")

    # 2. audit_math_layout.py --all --json
    p2 = run_cmd([sys.executable, str(cfg.scripts_dir / "audit_math_layout.py"), "--all", "--json"], cfg.root)
    if p2.returncode != 0:
        print("[FAIL] audit_math_layout.py --all failed:")
        print(p2.stdout.strip() or p2.stderr.strip())
        return 1
    reps2 = json.loads(p2.stdout)
    if isinstance(reps2, dict):
        reps2 = [reps2]
    total_layout_viol = sum(r.get("total_violations", 0) for r in reps2)
    if total_layout_viol != 0 or len(reps2) != len(md_files):
        print(f"[FAIL] audit_math_layout.py --all: files={len(reps2)}, total_violations={total_layout_viol}")
        return 1
    print(f"[PASS] audit_math_layout.py --all ({len(reps2)}/{len(reps2)} files, TOTAL VIOLATIONS: 0)")

    # 3. audit_notation_protocol.py --all --json
    p3 = run_cmd([sys.executable, str(cfg.scripts_dir / "audit_notation_protocol.py"), "--all", "--json"], cfg.root)
    if p3.returncode != 0:
        print("[FAIL] audit_notation_protocol.py --all failed:")
        print(p3.stdout.strip() or p3.stderr.strip())
        return 1
    reps3 = json.loads(p3.stdout)
    if isinstance(reps3, dict):
        reps3 = [reps3]
    notation_failures: list[str] = []
    for r in reps3:
        bad = check_notation_gold_standard(r)
        if bad:
            notation_failures.append(f"{r['file']}: {', '.join(bad)}")
    if notation_failures or len(reps3) != len(md_files):
        print(f"[FAIL] audit_notation_protocol.py --all failed on {len(notation_failures)} file(s):")
        for nf in notation_failures:
            print(f"  - {nf}")
        return 1
    print(
        f"[PASS] audit_notation_protocol.py --all ({len(reps3)}/{len(reps3)} files, "
        f"HARD VIOLATIONS: 0, non_blockquote_formal=0, proofs=body_bold only, legacy_qed=0)"
    )

    # 4. Snapshot extraction, parity checks, and local_html leak scan across all HTML files
    now = utc_now_iso()
    build_files: dict[str, dict[str, Any]] = {}
    html_leaks_all: list[dict[str, Any]] = []
    missing_html: list[str] = []
    parity_failures: list[str] = []

    for p in md_files:
        tid = resolve_topic_id(p.name, kg_fn_to_tid, pm_fn_to_tid)
        snap = extract_markdown_snapshot(p)
        errs, warns = check_topic_parity(p.name, tid, snap, kg, pub_manifest, require_in_kg=True)
        parity_failures.extend(errs)
        for w in warns:
            print(f"  [WARN] {w}")

        html_path = cfg.local_html_dir / (p.stem + ".html")
        if not html_path.exists():
            missing_html.append(html_path.name)
        else:
            html_leaks_all.extend(scan_html_code_leaks(html_path))

        build_files[p.name] = {
            "topic_id": tid,
            "sha256": snap["sha256"],
            "word_count": snap["word_count"],
            "headings": snap["headings"],
            "formal_callouts": snap["formal_callouts"],
            "last_built_utc": now,
        }

    if parity_failures:
        print("[FAIL] KG / publication_manifest parity check failed:")
        for e in parity_failures:
            print(f"  - {e}")
        return 1
    print(f"[PASS] KG section_anchor & publication_manifest split-boundary parity ({len(md_files)}/{len(md_files)} OK)")

    if missing_html:
        print(f"[FAIL] Missing local HTML files in {cfg.local_html_dir}: {missing_html}")
        return 1
    if html_leaks_all:
        print(f"[FAIL] Found {len(html_leaks_all)} unintended <pre><code> LaTeX leak(s) in {cfg.local_html_dir}:")
        for lk in html_leaks_all:
            print(f"  - {lk['file']}:L{lk['line']} token={lk['token']!r} | {lk['snippet']}")
        return 1
    print(
        f"[PASS] Local HTML <pre><code> leak scan: 0 unintended LaTeX leaks across "
        f"{len(md_files)}/{len(md_files)} HTML files"
    )

    if dry_run:
        print(f"[DRY-RUN] Would write baseline {cfg.build_state_path} ({len(build_files)} files).")
        return 0

    save_build_state(cfg.build_state_path, build_files)
    print(f"[OK] Seeded baseline build ledger: {cfg.build_state_path} ({len(build_files)} files)")
    return 0


def run_incremental(
    cfg: BuildConfig,
    topic_arg: str | None,
    dry_run: bool,
    local_only: bool,
    minor_word_threshold: int,
    sync_mode: str,  # "default" | "sync_minor" | "confirm_graph_synced"
) -> int:
    """Execute incremental change detection, gates, targeted exports, and graph-sync mode."""
    if not cfg.build_state_path.exists():
        print(
            f"ERROR: Missing {cfg.build_state_path}. Run `python scripts/build_changed.py --init` first."
        )
        return 1
    if not cfg.kg_path.exists():
        print(f"ERROR: Missing {cfg.kg_path}")
        return 1
    if not cfg.pub_manifest_path.exists():
        print(f"ERROR: Missing {cfg.pub_manifest_path}")
        return 1

    build_files = load_build_state_files(cfg.build_state_path)
    kg = load_json(cfg.kg_path)
    pub_manifest = load_json(cfg.pub_manifest_path)

    kg_fn_to_tid = {t["filename"]: t["id"] for t in kg.get("topics", [])}
    kg_topic_ids = {t["id"] for t in kg.get("topics", [])}
    pm_fn_to_tid = {rec["source_filename"]: tid for tid, rec in pub_manifest.items()}

    md_files = sorted(cfg.set_2_dir.glob("*.md"))
    live_by_name = {p.name: p for p in md_files}
    live_by_tid: dict[str, str] = {}
    live_name_to_tid: dict[str, str] = {}
    snapshots: dict[str, dict[str, Any]] = {}

    for p in md_files:
        tid = resolve_topic_id(p.name, kg_fn_to_tid, pm_fn_to_tid)
        live_by_tid[tid] = p.name
        live_name_to_tid[p.name] = tid
        snapshots[p.name] = extract_markdown_snapshot(p)

    # Detect stale/missing across both ledgers
    html_changed_names = [
        fn
        for fn in sorted(live_by_name)
        if fn not in build_files or snapshots[fn]["sha256"] != build_files[fn]["sha256"]
    ]
    kg_stale_names = [
        fn
        for fn in sorted(live_by_name)
        if fn not in kg.get("source_hashes", {})
        or snapshots[fn]["sha256"] != kg["source_hashes"][fn]
    ]
    deleted_from_build = sorted(set(build_files.keys()) - set(live_by_name.keys()))
    deleted_from_kg = sorted(set(kg.get("source_hashes", {}).keys()) - set(live_by_name.keys()))

    print("=== Two-Ledger Change Detection ===")
    print(
        f"Build ledger (`output/build_state.json`): "
        f"{len(live_by_name) - len(html_changed_names)}/{len(live_by_name)} up-to-date, "
        f"{len(html_changed_names)} stale/new, {len(deleted_from_build)} deleted"
    )
    print(
        f"Graph ledger (`output/graph/knowledge_graph.json`): "
        f"{len(live_by_name) - len(kg_stale_names)}/{len(live_by_name)} up-to-date, "
        f"{len(kg_stale_names)} stale/untracked, {len(deleted_from_kg)} deleted"
    )

    if deleted_from_build or deleted_from_kg:
        print(
            f"[WARN] Deleted Set 2 files detected: build_state={deleted_from_build}, kg={deleted_from_kg}"
        )
        if sync_mode == "confirm_graph_synced":
            print("[FAIL] Cannot confirm graph synced while deleted files remain in ledgers.")
            return 1

    # Resolve target set K
    if topic_arg:
        target_names = parse_topic_filter(topic_arg, live_by_tid)
        print(f"Forced topic filter (`--topic {topic_arg}`): {len(target_names)} file(s)")
    elif sync_mode == "confirm_graph_synced":
        target_names = sorted(set(html_changed_names) | set(kg_stale_names))
    else:
        target_names = html_changed_names

    # Special safety guard: if --sync-minor is invoked when build_state already moved ahead of KG
    if not target_names:
        if sync_mode == "sync_minor" and kg_stale_names:
            print(
                f"\n[HARD-BLOCK] 0 changed files vs build_state.json, but {len(kg_stale_names)} file(s) "
                f"remain stale in knowledge_graph.json: {kg_stale_names}"
            )
            print(
                "Because build_state.json already moved past the graph's baseline, `--sync-minor` "
                "cannot prove these pending graph edits are MINOR. Review knowledge_graph.json and "
                "run `python scripts/build_changed.py --confirm-graph-synced`."
            )
            return 2

        print("\n0 changed files to rebuild.")
        if sync_mode == "confirm_graph_synced":
            ok_schema, schema_errs = validate_kg_schema_for_sync(kg, set())
            if not ok_schema:
                for e in schema_errs:
                    print(f"[FAIL][KG Schema] {e}")
                return 1
            if not dry_run:
                p_exp = run_cmd([sys.executable, str(cfg.scripts_dir / "analyze_graph.py"), "--export-js"], cfg.root)
                if p_exp.returncode != 0:
                    print("[FAIL] analyze_graph.py --export-js failed:")
                    print(p_exp.stdout.strip() or p_exp.stderr.strip())
                    return 1
        p_stale = run_cmd([sys.executable, str(cfg.scripts_dir / "analyze_graph.py"), "--check-stale"], cfg.root)
        if p_stale.stdout.strip():
            print(p_stale.stdout.strip())
        if sync_mode == "confirm_graph_synced" and "UP TO DATE" not in p_stale.stdout:
            return 1
        return 0

    classified: list[dict[str, Any]] = []
    for fn in target_names:
        tid = live_name_to_tid[fn]
        classified.append(
            classify_file_change(
                filename=fn,
                topic_id=tid,
                cur_snap=snapshots[fn],
                prev_entry=build_files.get(fn),
                kg=kg,
                kg_topic_ids=kg_topic_ids,
                minor_word_threshold=minor_word_threshold,
            )
        )

    print_structural_report(classified, minor_word_threshold)

    substantive_items = [it for it in classified if it["classification"] == "SUBSTANTIVE"]
    k_topics_csv = ",".join(it["topic_id"] for it in classified)

    if dry_run:
        print("\n=== [DRY-RUN] Planned Actions (No Files Modified) ===")
        print(f"- Would run 4 quality/parity gates on {len(classified)} topic(s): {k_topics_csv}")
        print(f"- Would run: python scripts/export_corpus.py --target local --topic {k_topics_csv}")
        print(f"- Would scan {len(classified)} generated HTML file(s) in {cfg.local_html_dir} for <pre><code> leaks")
        if local_only:
            print("- Skipping web export (`--local-only` specified)")
        else:
            print("- Would run: python scripts/export_corpus.py --target web and verify EXPORT_VALIDATION.md")
        print(f"- Would update {cfg.build_state_path} for {len(classified)} verified file(s)")
        if sync_mode == "default":
            print("- [DEFAULT] Would NOT modify knowledge_graph.json")
        elif sync_mode == "sync_minor":
            if substantive_items:
                print(
                    f"- [WOULD HARD-BLOCK --sync-minor (exit 2)] {len(substantive_items)} SUBSTANTIVE "
                    f"change(s) require semantic graph review before syncing knowledge_graph.json"
                )
            else:
                print("- [SYNC-MINOR] Would refresh source_hashes in knowledge_graph.json and export JS")
        elif sync_mode == "confirm_graph_synced":
            print("- [CONFIRM-GRAPH-SYNCED] Would validate KG schema + anchors, refresh source_hashes, export JS, and check UP TO DATE")
        return 0

    # If --confirm-graph-synced, validate KG schema + membership FIRST before exporting
    if sync_mode == "confirm_graph_synced":
        print("\n=== Pre-Sync Knowledge Graph Schema Validation ===")
        ok_schema, schema_errs = validate_kg_schema_for_sync(kg, set(target_names))
        if not ok_schema:
            for e in schema_errs:
                print(f"[FAIL][KG Schema] {e}")
            return 1
        print("[PASS] knowledge_graph.json schema and DAG acyclicity validated.")

    # Step 2: Strict per-file quality & parity gates (fail-fast)
    gates_ok = run_per_file_gates(
        cfg=cfg,
        items=classified,
        snapshots=snapshots,
        kg=kg,
        pub_manifest=pub_manifest,
        require_in_kg=(sync_mode == "confirm_graph_synced"),
    )
    if not gates_ok:
        print("\n[ABORTED] Quality/parity gate failed. build_state.json and knowledge_graph.json were NOT modified.")
        return 1

    # Step 3: Targeted local HTML export + HTML leak scan (+ web export unless --local-only)
    need_export = bool(html_changed_names) or bool(topic_arg)
    if need_export:
        print(f"\n=== Step 3: Targeted Build & Leak Verification ({k_topics_csv}) ===")
        p_loc = run_cmd(
            [
                sys.executable,
                str(cfg.scripts_dir / "export_corpus.py"),
                "--target",
                "local",
                "--topic",
                k_topics_csv,
            ],
            cfg.root,
        )
        if p_loc.returncode != 0:
            print("[FAIL] export_corpus.py --target local failed:")
            print(p_loc.stdout.strip() or p_loc.stderr.strip())
            return 1
        if p_loc.stdout.strip():
            print(p_loc.stdout.strip())

        leaks: list[dict[str, Any]] = []
        for it in classified:
            html_path = cfg.local_html_dir / (Path(it["filename"]).stem + ".html")
            if not html_path.exists():
                print(f"[FAIL] Expected local HTML file was not generated: {html_path}")
                return 1
            leaks.extend(scan_html_code_leaks(html_path))

        if leaks:
            print(f"[FAIL] Detected {len(leaks)} unintended <pre><code> LaTeX leak(s):")
            for lk in leaks:
                print(f"  - {lk['file']}:L{lk['line']} token={lk['token']!r} | {lk['snippet']}")
            print("[ABORTED] build_state.json was NOT modified.")
            return 1
        print(f"[PASS] Local HTML <pre><code> leak scan: 0 leaks across {len(classified)} file(s)")

        if not local_only:
            p_web = run_cmd(
                [sys.executable, str(cfg.scripts_dir / "export_corpus.py"), "--target", "web"],
                cfg.root,
            )
            if p_web.returncode != 0:
                print("[FAIL] export_corpus.py --target web failed:")
                print(p_web.stdout.strip() or p_web.stderr.strip())
                return 1
            if p_web.stdout.strip():
                print(p_web.stdout.strip())

            ok_web, web_errs = verify_export_validation_report(cfg.web_validation_path)
            if not ok_web:
                print("[FAIL] EXPORT_VALIDATION.md verification failed:")
                for we in web_errs:
                    print(f"  - {we}")
                print("[ABORTED] build_state.json was NOT modified.")
                return 1
            print("[PASS] EXPORT_VALIDATION.md confirmed 100% PASS across all exported web essays.")
        else:
            print("[SKIP] Web export skipped (--local-only).")
    else:
        print("\n=== Step 3: Build & Export Already Current in build_state.json (Skipped Re-export) ===")

    # Step 4: Update build_state.json ONLY for the K verified & exported files
    now = utc_now_iso()
    for it in classified:
        fn = it["filename"]
        snap = snapshots[fn]
        if it["html_stale"] or fn not in build_files or topic_arg:
            build_files[fn] = {
                "topic_id": it["topic_id"],
                "sha256": snap["sha256"],
                "word_count": snap["word_count"],
                "headings": snap["headings"],
                "formal_callouts": snap["formal_callouts"],
                "last_built_utc": now,
            }
    save_build_state(cfg.build_state_path, build_files)
    print(f"\n[OK] Updated {cfg.build_state_path} for {len(classified)} verified file(s).")

    # Step 5: Graph-Sync Mode Execution
    print("\n=== Step 4: Knowledge Graph Sync Policy ===")
    if sync_mode == "default":
        print("[DEFAULT] knowledge_graph.json was NOT modified.")
        p_stale = run_cmd([sys.executable, str(cfg.scripts_dir / "analyze_graph.py"), "--check-stale"], cfg.root)
        if p_stale.stdout.strip():
            print(p_stale.stdout.strip())
        return 0

    if sync_mode == "sync_minor":
        if substantive_items:
            print(
                f"\n[HARD-BLOCK] Refusing to edit knowledge_graph.json because {len(substantive_items)} "
                f"file(s) were classified as SUBSTANTIVE (exit code 2):"
            )
            for it in substantive_items:
                print(f"  * {it['topic_id']} ({it['filename']}): {'; '.join(it['reasons'])}")
                for h in it["removed_headings"]:
                    print(f"      heading -: {h}")
                for h in it["added_headings"]:
                    print(f"      heading +: {h}")
                for c in it["removed_callouts"]:
                    print(f"      callout -: {c}")
                for c in it["added_callouts"]:
                    print(f"      callout +: {c}")
                if it["word_count_delta"]:
                    sign = "+" if it["word_count_delta"] >= 0 else ""
                    print(f"      word_count delta: {sign}{it['word_count_delta']}")
            print(
                "\nLocal HTML/web build and build_state.json ARE updated, while knowledge_graph.json "
                "remains untouched.\nNext step: review/update concepts, edges, and section_anchors in "
                "output/graph/knowledge_graph.json, then run:\n"
                "  python scripts/build_changed.py --confirm-graph-synced"
            )
            return 2

        # All K items are MINOR or UNCHANGED (and ensure no untracked/unproven KG drift on K)
        for it in classified:
            fn = it["filename"]
            kg["source_hashes"][fn] = snapshots[fn]["sha256"]
        kg["source_hashes"] = {k: kg["source_hashes"][k] for k in sorted(kg["source_hashes"])}
        validate_knowledge_graph(kg)
        write_json(cfg.kg_path, kg)
        print(f"[SYNC-MINOR] Refreshed source_hashes in {cfg.kg_path} for {len(classified)} MINOR file(s).")

        p_js = run_cmd([sys.executable, str(cfg.scripts_dir / "analyze_graph.py"), "--export-js"], cfg.root)
        if p_js.returncode != 0:
            print("[FAIL] analyze_graph.py --export-js failed:")
            print(p_js.stdout.strip() or p_js.stderr.strip())
            return 1
        if p_js.stdout.strip():
            print(p_js.stdout.strip())

        p_chk = run_cmd([sys.executable, str(cfg.scripts_dir / "analyze_graph.py"), "--check-stale"], cfg.root)
        if p_chk.stdout.strip():
            print(p_chk.stdout.strip())
        return 0

    if sync_mode == "confirm_graph_synced":
        for it in classified:
            fn = it["filename"]
            kg["source_hashes"][fn] = snapshots[fn]["sha256"]
        kg["source_hashes"] = {k: kg["source_hashes"][k] for k in sorted(kg["source_hashes"])}
        validate_knowledge_graph(kg)
        write_json(cfg.kg_path, kg)
        print(f"[CONFIRM-GRAPH-SYNCED] Refreshed source_hashes in {cfg.kg_path} for {len(classified)} verified file(s).")

        p_js = run_cmd([sys.executable, str(cfg.scripts_dir / "analyze_graph.py"), "--export-js"], cfg.root)
        if p_js.returncode != 0:
            print("[FAIL] analyze_graph.py --export-js failed:")
            print(p_js.stdout.strip() or p_js.stderr.strip())
            return 1
        if p_js.stdout.strip():
            print(p_js.stdout.strip())

        p_chk = run_cmd([sys.executable, str(cfg.scripts_dir / "analyze_graph.py"), "--check-stale"], cfg.root)
        if p_chk.stdout.strip():
            print(p_chk.stdout.strip())
        if p_chk.returncode != 0 or "UP TO DATE" not in p_chk.stdout:
            print("[FAIL] Knowledge graph is NOT UP TO DATE across all topics after sync.")
            return 1
        return 0

    raise AssertionError(f"Unexpected sync_mode: {sync_mode}")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Deterministic two-state incremental rebuild wrapper for Set 2 articles."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--init",
        action="store_true",
        help="Verify all Set 2 + HTML files read-only and seed output/build_state.json.",
    )
    mode_group.add_argument(
        "--sync-minor",
        action="store_true",
        help="Refresh knowledge_graph.json source_hashes ONLY if all changes are MINOR (exits 2 if any SUBSTANTIVE).",
    )
    mode_group.add_argument(
        "--confirm-graph-synced",
        action="store_true",
        help="Validate KG schema + anchors, refresh source_hashes for verified topics, export JS, and verify UP TO DATE.",
    )

    parser.add_argument(
        "--topic",
        help="Comma-separated topic ID(s) to force-run (e.g., T08 or T08,T14).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify changes and report planned actions without modifying any files.",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Skip --target web export for fast local HTML rebuilds.",
    )
    parser.add_argument(
        "--minor-word-threshold",
        type=int,
        default=150,
        help="Minimum abs(word_count_delta) classifying an edit as SUBSTANTIVE (default: 150).",
    )
    return parser


def main(argv: list[str] | None = None, config: BuildConfig | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    cfg = config or BuildConfig.from_root()

    if args.minor_word_threshold < 1:
        parser.error("--minor-word-threshold must be >= 1")

    if args.init:
        if args.topic:
            parser.error("--topic cannot be combined with --init")
        return run_init(cfg, dry_run=args.dry_run)

    if args.sync_minor:
        sync_mode = "sync_minor"
    elif args.confirm_graph_synced:
        sync_mode = "confirm_graph_synced"
    else:
        sync_mode = "default"

    return run_incremental(
        cfg=cfg,
        topic_arg=args.topic,
        dry_run=args.dry_run,
        local_only=args.local_only,
        minor_word_threshold=args.minor_word_threshold,
        sync_mode=sync_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
