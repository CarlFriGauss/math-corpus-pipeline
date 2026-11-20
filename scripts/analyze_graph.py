"""Deterministic topology verification and curriculum analytics for Set 2 knowledge graph."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = ROOT / "output" / "graph"
KG_PATH = GRAPH_DIR / "knowledge_graph.json"
KG_JS_PATH = GRAPH_DIR / "knowledge_graph.js"
TOPOLOGY_REPORT_PATH = GRAPH_DIR / "TOPOLOGY_REPORT.md"
OVERLAY_PATH = GRAPH_DIR / "audit_overlay.json"
OVERLAY_JS_PATH = GRAPH_DIR / "audit_overlay.js"
PERSONAL_GAP_REPORT_PATH = GRAPH_DIR / "PERSONAL_GAP_REPORT.md"

VALID_KINDS = {"definition", "theorem", "lemma", "inequality", "algorithm", "structure"}
VALID_RELATIONS = {"requires", "generalizes"}
VALID_STATES = {"solid", "corrected", "injected_prerequisite"}


def sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    """Load UTF-8 JSON object from path."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_knowledge_graph(kg: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """Validate schema invariants on knowledge_graph.json (pure Set 2)."""
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
    assert not missing, f"Missing root keys: {missing}"
    assert kg["topic_count"] == len(kg["topics"]), "topic_count mismatch"

    topic_map: dict[str, dict] = {}
    for t in kg["topics"]:
        tid = t["id"]
        assert tid not in topic_map, f"Duplicate topic id: {tid}"
        assert t["filename"] in kg["source_hashes"], f"Missing source hash for {t['filename']}"
        topic_map[tid] = t

    concept_map: dict[str, dict] = {}
    for c in kg["concepts"]:
        cid = c["id"]
        assert cid not in concept_map, f"Duplicate concept id: {cid}"
        assert cid.startswith("C_"), f"Invalid concept id prefix: {cid}"
        assert c["kind"] in VALID_KINDS, f"Invalid concept kind for {cid}: {c['kind']}"
        ctid = c["canonical_topic_id"]
        assert ctid in topic_map, f"Dangling canonical_topic_id {ctid} on {cid}"
        assert ctid in c["referenced_in_topics"], f"{cid} missing canonical_topic_id in referenced_in_topics"
        for rtid in c["referenced_in_topics"]:
            assert rtid in topic_map, f"Dangling referenced_in_topics {rtid} on {cid}"
        concept_map[cid] = c

    seen_micro = set()
    for e in kg["micro_edges"]:
        u, v, rel = e["source"], e["target"], e["relation"]
        assert u in concept_map, f"Dangling micro source: {u}"
        assert v in concept_map, f"Dangling micro target: {v}"
        assert u != v, f"Self-loop on micro edge: {u}"
        assert rel in VALID_RELATIONS, f"Invalid micro relation: {rel}"
        assert (u, v, rel) not in seen_micro, f"Duplicate micro edge: {(u, v, rel)}"
        seen_micro.add((u, v, rel))

    seen_macro = set()
    for me in kg["macro_edges"]:
        u, v, rel = me["source"], me["target"], me["relation"]
        assert u in topic_map, f"Dangling macro source: {u}"
        assert v in topic_map, f"Dangling macro target: {v}"
        assert u != v, f"Self-loop on macro edge: {u}"
        assert rel in VALID_RELATIONS, f"Invalid macro relation: {rel}"
        assert (u, v, rel) not in seen_macro, f"Duplicate macro edge: {(u, v, rel)}"
        seen_macro.add((u, v, rel))
        assert me["weight"] == len(me["supporting_concept_edges"]), f"Weight mismatch on macro edge {u}->{v}"
        for cu, cv in me["supporting_concept_edges"]:
            assert (cu, cv, rel) in seen_micro, f"Missing supporting micro edge {(cu, cv, rel)}"
            assert concept_map[cu]["canonical_topic_id"] == u
            assert concept_map[cv]["canonical_topic_id"] == v

    return topic_map, concept_map


def build_req_adj(nodes: list[str], edges: list[dict]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build deterministic forward and reverse adjacency lists for relation == 'requires'."""
    fwd: dict[str, list[str]] = {n: [] for n in nodes}
    rev: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        if e["relation"] == "requires":
            fwd[e["source"]].append(e["target"])
            rev[e["target"]].append(e["source"])
    for n in nodes:
        fwd[n].sort()
        rev[n].sort()
    return fwd, rev


def tarjan_scc(nodes: list[str], adj: dict[str, list[str]]) -> list[list[str]]:
    """Deterministic iterative Tarjan Strongly Connected Components decomposition."""
    index_counter = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []

    for start in nodes:
        if start in indices:
            continue
        call_stack: list[tuple[str, int]] = [(start, 0)]
        indices[start] = lowlink[start] = index_counter
        index_counter += 1
        stack.append(start)
        on_stack.add(start)

        while call_stack:
            v, ni = call_stack[-1]
            nbrs = adj[v]
            if ni < len(nbrs):
                call_stack[-1] = (v, ni + 1)
                w = nbrs[ni]
                if w not in indices:
                    indices[w] = lowlink[w] = index_counter
                    index_counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    call_stack.append((w, 0))
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])
            else:
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[v])
                if lowlink[v] == indices[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack.remove(w)
                        comp.append(w)
                        if w == v:
                            break
                    sccs.append(sorted(comp))

    return sccs


def bfs_reachable(start: str, adj: dict[str, list[str]], exclude_self: bool = True) -> set[str]:
    """Return set of nodes reachable from start in adj."""
    visited: set[str] = set()
    q = deque([start])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in visited:
                visited.add(v)
                q.append(v)
    if exclude_self:
        visited.discard(start)
    return visited


def compute_centrality(nodes: list[str], fwd: dict[str, list[str]], rev: dict[str, list[str]]) -> dict[str, dict]:
    """Compute direct and transitive in/out degree centrality metrics on G_req."""
    stats = {}
    for u in nodes:
        desc = bfs_reachable(u, fwd, exclude_self=True)
        anc = bfs_reachable(u, rev, exclude_self=True)
        stats[u] = {
            "out_degree": len(fwd[u]),
            "transitive_descendants": len(desc),
            "in_degree": len(rev[u]),
            "transitive_ancestors": len(anc),
            "descendants": desc,
            "ancestors": anc,
        }
    return stats


def kahn_condensation_order(
    nodes: list[str],
    fwd: dict[str, list[str]],
    sccs: list[list[str]],
) -> tuple[list[dict], dict[str, int]]:
    """Run Kahn's topological sort + longest-path layer assignment on the SCC condensation DAG."""
    node_to_cid: dict[str, int] = {}
    comp_nodes: dict[int, list[str]] = {}
    # Sort SCCs canonically by lowest member ID
    ordered_sccs = sorted(sccs, key=lambda c: c[0])
    for cid, comp in enumerate(ordered_sccs):
        comp_nodes[cid] = comp
        for u in comp:
            node_to_cid[u] = cid

    cond_fwd: dict[int, set[int]] = {cid: set() for cid in comp_nodes}
    in_deg: dict[int, int] = {cid: 0 for cid in comp_nodes}
    for u in nodes:
        cu = node_to_cid[u]
        for v in fwd[u]:
            cv = node_to_cid[v]
            if cu != cv and cv not in cond_fwd[cu]:
                cond_fwd[cu].add(cv)
                in_deg[cv] += 1

    # Min-priority tie-break by canonical member ID via sorted list
    ready = sorted([cid for cid, d in in_deg.items() if d == 0], key=lambda c: comp_nodes[c][0])
    layer_of_comp: dict[int, int] = {cid: 0 for cid in ready}
    topo_order: list[dict] = []

    while ready:
        cid = ready.pop(0)
        topo_order.append({
            "comp_id": cid,
            "members": comp_nodes[cid],
            "layer": layer_of_comp[cid],
        })
        for nxt in sorted(cond_fwd[cid]):
            layer_of_comp[nxt] = max(layer_of_comp.get(nxt, 0), layer_of_comp[cid] + 1)
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=lambda c: comp_nodes[c][0])

    assert len(topo_order) == len(comp_nodes), "Condensation graph is not acyclic!"
    node_layer = {u: layer_of_comp[node_to_cid[u]] for u in nodes}
    return topo_order, node_layer


def format_macro_cycles(sccs: list[list[str]], kg: dict) -> list[str]:
    """Format detailed descriptions of any non-trivial macro SCCs and their feedback concept edges."""
    nontrivial = [c for c in sccs if len(c) > 1]
    if not nontrivial:
        return ["- **Macro `G_req` Status:** Strictly acyclic **DAG** (0 non-trivial SCCs)."]
    lines = [f"- **Macro `G_req` Status:** Contains **{len(nontrivial)}** non-trivial SCC(s) (condensation DAG computed cleanly):"]
    for comp in nontrivial:
        comp_set = set(comp)
        lines.append(f"  - **SCC `{' <-> '.join(comp)}` ({len(comp)} topics):**")
        for me in kg["macro_edges"]:
            if me["relation"] == "requires" and me["source"] in comp_set and me["target"] in comp_set:
                pairs = ", ".join(f"`{a}` -> `{b}`" for a, b in me["supporting_concept_edges"])
                lines.append(f"    - `{me['source']} -> {me['target']}` (weight {me['weight']}): {pairs}")
    return lines


def ordered_cone_for_topic(
    tid: str,
    anc_set: set[str],
    topo_comps: list[dict],
) -> list[str]:
    """Return minimal ordered prerequisite sequence leading up to topic tid."""
    relevant = anc_set | {tid}
    seq = []
    for item in topo_comps:
        members = [m for m in item["members"] if m in relevant]
        if members:
            if len(members) > 1:
                seq.append(f"[{' <-> '.join(members)}]")
            else:
                seq.append(members[0])
    return seq


def write_topology_report(
    kg: dict,
    topic_map: dict[str, dict],
    concept_map: dict[str, dict],
    micro_sccs: list[list[str]],
    macro_sccs: list[list[str]],
    topo_comps: list[dict],
    topic_layer: dict[str, int],
    concept_stats: dict[str, dict],
    topic_stats: dict[str, dict],
    macro_fwd: dict[str, list[str]],
    macro_rev: dict[str, list[str]],
) -> None:
    """Write public Set-2-only output/graph/TOPOLOGY_REPORT.md."""
    req_micro = sum(1 for e in kg["micro_edges"] if e["relation"] == "requires")
    gen_micro = sum(1 for e in kg["micro_edges"] if e["relation"] == "generalizes")
    req_macro = sum(1 for e in kg["macro_edges"] if e["relation"] == "requires")
    gen_macro = sum(1 for e in kg["macro_edges"] if e["relation"] == "generalizes")

    micro_nontrivial = [c for c in micro_sccs if len(c) > 1]
    macro_nontrivial = [c for c in macro_sccs if len(c) > 1]

    lines: list[str] = [
        "# Pure Set 2 Mathematical Knowledge Graph — Topology & Curriculum Report",
        "",
        f"- **Source Directory:** `{kg['source_dir']}` ({kg['topic_count']} articles)",
        f"- **Schema Version:** `{kg['schema_version']}` | **Generated UTC:** `{kg['generated_utc']}`",
        f"- **Vertices:** {len(topic_map)} topics, {len(concept_map)} canonical concepts",
        f"- **Edges:** {len(kg['micro_edges'])} micro edges ({req_micro} `requires`, {gen_micro} `generalizes`), "
        f"{len(kg['macro_edges'])} macro edges ({req_macro} `requires`, {gen_macro} `generalizes`)",
        "",
        "## 1. Tarjan Cycle Audit (`G_req`)",
        "",
    ]
    if not micro_nontrivial:
        lines.append(f"- **Micro (Concept) `G_req` Status:** Strictly acyclic **DAG** (0 non-trivial SCCs across {len(concept_map)} concepts).")
    else:
        lines.append(f"- **Micro `G_req` Status:** {len(micro_nontrivial)} cycles found: {micro_nontrivial}")
    lines.extend(format_macro_cycles(macro_sccs, kg))
    lines.append("")

    # Section 2: Topological Reading Order by Layer & Discipline
    lines.extend([
        "## 2. Topological Curriculum Order (Condensation DAG Layers)",
        "",
        "Each layer $L$ represents the longest prerequisite chain from foundational axioms ($L = 0$):",
        "",
        "| Layer | Topic / SCC | Discipline | Direct Prereqs | Direct Dependents | Transitive Ancestors | Transitive Dependents |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :---: |",
    ])
    for item in topo_comps:
        L = item["layer"]
        members = item["members"]
        if len(members) == 1:
            t = members[0]
            tm = topic_map[t]
            st = topic_stats[t]
            lines.append(
                f"| {L} | **{t}** — {tm['title']} | {tm['discipline']} | {st['in_degree']} | {st['out_degree']} | {st['transitive_ancestors']} | {st['transitive_descendants']} |"
            )
        else:
            joined = " <-> ".join(f"**{m}**" for m in members)
            titles = " / ".join(topic_map[m]["title"] for m in members)
            discs = ", ".join(sorted({topic_map[m]["discipline"] for m in members}))
            # Report aggregate external in/out and individual notes
            ext_in = sorted({p for m in members for p in macro_rev[m] if p not in members})
            ext_out = sorted({d for m in members for d in macro_fwd[m] if d not in members})
            anc_union = set().union(*(topic_stats[m]["ancestors"] for m in members)) - set(members)
            desc_union = set().union(*(topic_stats[m]["descendants"] for m in members)) - set(members)
            lines.append(
                f"| {L} | {joined} *(SCC)* — {titles} | {discs} | {len(ext_in)} | {len(ext_out)} | {len(anc_union)} | {len(desc_union)} |"
            )
    lines.append("")

    # Discipline summary
    disc_groups: dict[str, list[str]] = defaultdict(list)
    for item in topo_comps:
        for m in item["members"]:
            disc_groups[topic_map[m]["discipline"]].append(m)
    lines.extend(["### Curriculum Order by Discipline Track", ""])
    for disc in sorted(disc_groups.keys()):
        ordered_list = " -> ".join(disc_groups[disc])
        lines.append(f"- **{disc}:** {ordered_list}")
    lines.append("")

    # Section 3: Top Keystone Topics and Keystone Concepts
    lines.extend([
        "## 3. Mathematical Centrality & Keystone Ranking (`G_req`)",
        "",
        "### Top 15 Foundational Topics by Transitive Downstream Impact",
        "",
        "| Rank | Topic | Discipline | Layer | Direct Dependents | Transitive Dependents |",
        "| :---: | :--- | :--- | :---: | :---: | :---: |",
    ])
    ranked_topics = sorted(
        topic_map.keys(),
        key=lambda t: (-topic_stats[t]["transitive_descendants"], -topic_stats[t]["out_degree"], int(t[1:])),
    )
    for idx, t in enumerate(ranked_topics[:15], start=1):
        st = topic_stats[t]
        tm = topic_map[t]
        lines.append(
            f"| {idx} | **{t}**: {tm['title']} | {tm['discipline']} | {topic_layer[t]} | {st['out_degree']} | {st['transitive_descendants']} |"
        )
    lines.append("")

    lines.extend([
        "### Top 25 Keystone Concepts by Transitive Downstream Impact",
        "",
        "| Rank | Concept ID | Name | Topic | Topics Relying | Direct Out-Deg | Transitive Dependents | Direct In-Deg |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
    ])
    ranked_concepts = sorted(
        concept_map.keys(),
        key=lambda c: (-concept_stats[c]["transitive_descendants"], -concept_stats[c]["out_degree"], c),
    )
    for idx, cid in enumerate(ranked_concepts[:25], start=1):
        c = concept_map[cid]
        st = concept_stats[cid]
        lines.append(
            f"| {idx} | `{cid}` | {c['name']} | {c['canonical_topic_id']} | {len(c['referenced_in_topics'])} | "
            f"{st['out_degree']} | {st['transitive_descendants']} | {st['in_degree']} |"
        )
    lines.append("")

    # Section 4: Per-Topic Prerequisite Dependency Cones
    lines.extend([
        "## 4. Per-Topic Prerequisite Dependency Cones",
        "",
        "| Topic | Layer | Direct Prerequisites | Full Transitive Reading Path |",
        "| :---: | :---: | :--- | :--- |",
    ])
    for tid in sorted(topic_map.keys(), key=lambda x: int(x[1:])):
        direct = ", ".join(macro_rev[tid]) if macro_rev[tid] else "*(root)*"
        cone = ordered_cone_for_topic(tid, topic_stats[tid]["ancestors"], topo_comps)
        cone_str = " -> ".join(cone)
        lines.append(f"| **{tid}** | {topic_layer[tid]} | {direct} | {cone_str} |")
    lines.append("")

    TOPOLOGY_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def validate_overlay(kg: dict, overlay: dict, topic_map: dict[str, dict], concept_map: dict[str, dict]) -> None:
    """Validate strict 1-to-1 key parity between audit_overlay.json and knowledge_graph.json."""
    required_keys = {"schema_version", "source_audit_report", "topic_overlays", "concept_overlays", "edge_overlays"}
    missing = required_keys - set(overlay.keys())
    assert not missing, f"Overlay missing root keys: {missing}"
    assert set(overlay["topic_overlays"].keys()) == set(topic_map.keys()), "topic_overlays key mismatch"
    assert set(overlay["concept_overlays"].keys()) == set(concept_map.keys()), "concept_overlays key mismatch"
    for cid, cmeta in overlay["concept_overlays"].items():
        assert cmeta["epistemic_state"] in VALID_STATES, f"Invalid epistemic_state on {cid}"
    expected_req = {f"{e['source']}->{e['target']}" for e in kg["micro_edges"] if e["relation"] == "requires"}
    assert set(overlay["edge_overlays"].keys()) == expected_req, "edge_overlays key mismatch against requires edges"


def write_personal_gap_report(
    kg: dict,
    overlay: dict,
    topic_map: dict[str, dict],
    concept_map: dict[str, dict],
    concept_stats: dict[str, dict],
) -> None:
    """Join knowledge_graph.json and audit_overlay.json in memory to emit PERSONAL_GAP_REPORT.md."""
    cov = overlay["concept_overlays"]
    tov = overlay["topic_overlays"]
    eov = overlay["edge_overlays"]

    state_counts = defaultdict(int)
    for meta in cov.values():
        state_counts[meta["epistemic_state"]] += 1

    total_errors = sum(v["errors_fixed_count"] for v in tov.values())
    total_additions = sum(v["additions_count"] for v in tov.values())
    bridge_edges = [
        (ekey, emeta) for ekey, emeta in eov.items() if emeta.get("is_gap_bridge")
    ]

    lines: list[str] = [
        "# Personal Knowledge Gap & Remediation Impact Report (Private Audit Overlay)",
        "",
        f"- **Source Audit:** `{overlay['source_audit_report']}` (joined read-only onto `{kg['source_dir']}` graph)",
        f"- **Corpus Audit Totals:** **{total_errors}** errors corrected, **{total_additions}** foundational additions across **{len(topic_map)}** articles",
        f"- **Concept Epistemic Breakdown ({len(concept_map)} concepts):** "
        f"`solid` = **{state_counts['solid']}**, "
        f"`corrected` = **{state_counts['corrected']}**, "
        f"`injected_prerequisite` = **{state_counts['injected_prerequisite']}**",
        f"- **Identified Gap-Bridge Dependency Edges:** **{len(bridge_edges)}** / {len(eov)} `requires` edges "
        f"(cases where Set 1 invoked a downstream result without establishing its Set 2 prerequisite)",
        "",
        "## 1. Highest-Leverage Injected Prerequisites (Missing in Set 1, Ordered by Transitive Impact)",
        "",
        "| Rank | Concept ID | Concept Name | Topic | Transitive Dependents | Direct Out-Deg | Downstream Topics Relying | Gap Bridges Out | Primary Audit Ref |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    bridges_out = defaultdict(list)
    bridges_in = defaultdict(list)
    for ekey, emeta in bridge_edges:
        u, v = ekey.split("->", 1)
        bridges_out[u].append((v, emeta["audit_ref"]))
        bridges_in[v].append((u, emeta["audit_ref"]))

    injected_ranked = sorted(
        [cid for cid, m in cov.items() if m["epistemic_state"] == "injected_prerequisite"],
        key=lambda c: (
            -concept_stats[c]["transitive_descendants"],
            -len(bridges_out[c]),
            -concept_stats[c]["out_degree"],
            c,
        ),
    )
    for idx, cid in enumerate(injected_ranked[:25], start=1):
        c = concept_map[cid]
        st = concept_stats[cid]
        refs = cov[cid]["audit_refs"]
        ref_str = f"{refs[0]['topic_id']} {refs[0]['ref_id']}" if refs else "*(Set 2 gap)*"
        lines.append(
            f"| {idx} | `{cid}` | {c['name']} | {c['canonical_topic_id']} | **{st['transitive_descendants']}** | "
            f"{st['out_degree']} | {len(c['referenced_in_topics'])} | {len(bridges_out[cid])} | {ref_str} |"
        )
    lines.append("")

    # Section 2: Highest-leverage Corrected Concepts
    lines.extend([
        "## 2. Highest-Leverage Corrected Concepts (Flawed in Set 1, Ordered by Transitive Blast Radius)",
        "",
        "| Rank | Concept ID | Concept Name | Topic | Transitive Dependents | Direct Out-Deg | Audit Error Count | Primary Error Ref |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ])
    corrected_ranked = sorted(
        [cid for cid, m in cov.items() if m["epistemic_state"] == "corrected"],
        key=lambda c: (
            -concept_stats[c]["transitive_descendants"],
            -sum(1 for r in cov[c]["audit_refs"] if r["type"] == "error"),
            -concept_stats[c]["out_degree"],
            c,
        ),
    )
    for idx, cid in enumerate(corrected_ranked[:25], start=1):
        c = concept_map[cid]
        st = concept_stats[cid]
        errs = [r for r in cov[cid]["audit_refs"] if r["type"] == "error"]
        ref_str = f"{errs[0]['topic_id']} {errs[0]['ref_id']}" if errs else "-"
        lines.append(
            f"| {idx} | `{cid}` | {c['name']} | {c['canonical_topic_id']} | **{st['transitive_descendants']}** | "
            f"{st['out_degree']} | {len(errs)} | {ref_str} |"
        )
    lines.append("")

    # Section 3: Cross-Article Recurring Gap Patterns
    lines.extend([
        "## 3. Cross-Article Recurring Gap Patterns",
        "",
        "### A. Injected Foundations Bridged into Multiple Distinct Downstream Articles",
        "",
        "| Concept ID | Canonical Topic | Downstream Topics Bridged Into | Bridge Edges | Target Topics |",
        "| :--- | :---: | :---: | :---: | :--- |",
    ])
    cross_injected = []
    for cid in injected_ranked:
        dst_tids = sorted(
            {concept_map[v]["canonical_topic_id"] for v, _ in bridges_out[cid] if concept_map[v]["canonical_topic_id"] != concept_map[cid]["canonical_topic_id"]},
            key=lambda x: int(x[1:]),
        )
        all_bridge_tids = sorted({concept_map[v]["canonical_topic_id"] for v, _ in bridges_out[cid]}, key=lambda x: int(x[1:]))
        if len(all_bridge_tids) >= 2 or len(dst_tids) >= 1:
            cross_injected.append((len(all_bridge_tids), len(bridges_out[cid]), concept_stats[cid]["transitive_descendants"], cid, all_bridge_tids))
    cross_injected.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3]))
    for n_tids, n_edges, tdesc, cid, tids in cross_injected[:30]:
        lines.append(
            f"| `{cid}` | {concept_map[cid]['canonical_topic_id']} | {n_tids} | {n_edges} | {', '.join(tids)} |"
        )
    lines.append("")

    # B. Topic-by-Topic Gap Bridge & Epistemic Profile
    lines.extend([
        "### B. Per-Topic Epistemic & Gap-Bridge Summary",
        "",
        "| Topic | Discipline | Errors Fixed | Additions | Solid | Corrected | Injected | Gap Bridges Out | Gap Bridges In |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    for tid in sorted(topic_map.keys(), key=lambda x: int(x[1:])):
        tm = topic_map[tid]
        t_cids = [c["id"] for c in kg["concepts"] if c["canonical_topic_id"] == tid]
        s_cnt = sum(1 for c in t_cids if cov[c]["epistemic_state"] == "solid")
        c_cnt = sum(1 for c in t_cids if cov[c]["epistemic_state"] == "corrected")
        i_cnt = sum(1 for c in t_cids if cov[c]["epistemic_state"] == "injected_prerequisite")
        b_out = sum(len(bridges_out[c]) for c in t_cids)
        b_in = sum(len(bridges_in[c]) for c in t_cids)
        lines.append(
            f"| **{tid}** | {tm['discipline']} | {tov[tid]['errors_fixed_count']} | {tov[tid]['additions_count']} | "
            f"{s_cnt} | {c_cnt} | {i_cnt} | {b_out} | {b_in} |"
        )
    lines.append("")

    PERSONAL_GAP_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def export_js_wrapper(data: dict, global_var: str, out_path: Path) -> None:
    """Export JSON object as an offline file://-safe global JS wrapper."""
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    out_path.write_text(f"window.{global_var} = {payload};\n", encoding="utf-8")


def check_stale(kg: dict) -> list[tuple[str, str, str]]:
    """Compare recorded source_hashes against current files in source_dir without mutating any graph files."""
    src_dir = ROOT / kg["source_dir"]
    recorded = kg["source_hashes"]
    fn_to_tid = {t["filename"]: t["id"] for t in kg["topics"]}
    live_files = {p.name: sha256_file(p) for p in sorted(src_dir.glob("*.md"))}

    stale: list[tuple[str, str, str]] = []
    for fn, old_sha in sorted(recorded.items()):
        tid = fn_to_tid.get(fn, "NEW?")
        if fn not in live_files:
            stale.append((tid, fn, "DELETED"))
        elif live_files[fn] != old_sha:
            stale.append((tid, fn, "MODIFIED"))
    for fn in sorted(live_files.keys()):
        if fn not in recorded:
            stale.append(("UNTRACKED", fn, "ADDED"))
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Set 2 Knowledge Graph topology.")
    parser.add_argument("--overlay", action="store_true", help="Join audit_overlay.json read-only and emit PERSONAL_GAP_REPORT.md")
    parser.add_argument("--export-js", action="store_true", help="Export knowledge_graph.js and audit_overlay.js (if present) for explorer.html")
    parser.add_argument("--check-stale", action="store_true", help="Check if any Set 2 files changed relative to source_hashes")
    args = parser.parse_args()

    kg = load_json(KG_PATH)
    topic_map, concept_map = validate_knowledge_graph(kg)

    if args.check_stale:
        stale = check_stale(kg)
        total_tracked = len(kg["source_hashes"])
        if not stale:
            print(f"UP TO DATE: All {total_tracked}/{total_tracked} Set 2 files in '{kg['source_dir']}' match recorded SHA-256 source_hashes.")
        else:
            print(f"STALE TOPICS DETECTED ({len(stale)} change(s) vs recorded source_hashes):")
            for tid, fn, status in stale:
                print(f"  - [{status}] {tid}: {fn}")
        print(f"SHA256 knowledge_graph.json: {sha256_file(KG_PATH)}")
        if TOPOLOGY_REPORT_PATH.exists():
            print(f"SHA256 TOPOLOGY_REPORT.md:   {sha256_file(TOPOLOGY_REPORT_PATH)}")
        return

    topic_ids = [t["id"] for t in kg["topics"]]
    concept_ids = [c["id"] for c in kg["concepts"]]

    micro_fwd, micro_rev = build_req_adj(concept_ids, kg["micro_edges"])
    macro_fwd, macro_rev = build_req_adj(topic_ids, kg["macro_edges"])

    micro_sccs = tarjan_scc(concept_ids, micro_fwd)
    macro_sccs = tarjan_scc(topic_ids, macro_fwd)

    topo_comps, topic_layer = kahn_condensation_order(topic_ids, macro_fwd, macro_sccs)
    concept_stats = compute_centrality(concept_ids, micro_fwd, micro_rev)
    topic_stats = compute_centrality(topic_ids, macro_fwd, macro_rev)

    if args.export_js:
        export_js_wrapper(kg, "KNOWLEDGE_GRAPH", KG_JS_PATH)
        print(f"Exported {KG_JS_PATH}")
        if OVERLAY_PATH.exists():
            overlay = load_json(OVERLAY_PATH)
            validate_overlay(kg, overlay, topic_map, concept_map)
            export_js_wrapper(overlay, "AUDIT_OVERLAY", OVERLAY_JS_PATH)
            print(f"Exported {OVERLAY_JS_PATH}")
    elif args.overlay:
        overlay = load_json(OVERLAY_PATH)
        validate_overlay(kg, overlay, topic_map, concept_map)
        write_personal_gap_report(kg, overlay, topic_map, concept_map, concept_stats)
        export_js_wrapper(kg, "KNOWLEDGE_GRAPH", KG_JS_PATH)
        export_js_wrapper(overlay, "AUDIT_OVERLAY", OVERLAY_JS_PATH)
        print(f"Overlay validation passed. Wrote {PERSONAL_GAP_REPORT_PATH} and JS wrappers")
    else:
        write_topology_report(
            kg,
            topic_map,
            concept_map,
            micro_sccs,
            macro_sccs,
            topo_comps,
            topic_layer,
            concept_stats,
            topic_stats,
            macro_fwd,
            macro_rev,
        )
        export_js_wrapper(kg, "KNOWLEDGE_GRAPH", KG_JS_PATH)
        print(f"Wrote {TOPOLOGY_REPORT_PATH} and {KG_JS_PATH}")

    kg_sha = sha256_file(KG_PATH)
    rep_sha = sha256_file(TOPOLOGY_REPORT_PATH) if TOPOLOGY_REPORT_PATH.exists() else None
    micro_cycles = [c for c in micro_sccs if len(c) > 1]
    macro_cycles = [c for c in macro_sccs if len(c) > 1]
    print(f"Schema validation passed: {len(topic_map)} topics, {len(concept_map)} concepts, {len(kg['micro_edges'])} micro edges, {len(kg['macro_edges'])} macro edges")
    print(f"Micro G_req cycles (>1): {len(micro_cycles)}")
    print(f"Macro G_req cycles (>1): {macro_cycles}")
    print(f"SHA256 knowledge_graph.json: {kg_sha}")
    if rep_sha:
        print(f"SHA256 TOPOLOGY_REPORT.md:   {rep_sha}")


if __name__ == "__main__":
    main()
