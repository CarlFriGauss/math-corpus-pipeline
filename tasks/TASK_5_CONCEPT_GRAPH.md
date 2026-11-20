# TASK 5: Pure Set 2 Mathematical Concept Graph & Decoupled Private Audit Overlay

## Objective
Construct a canonical, mathematically pure dependency graph $G = (V, E)$ derived **exclusively** from `output/set_2_corrected/`, run deterministic graph-theoretic diagnostics on $G$, and then build a strictly separate, read-only private audit overlay $\phi$ from `output/AUDIT_REPORT.md` plus a local interactive viewer (`output/graph/explorer.html`).

---

## Stage 1: Blind Core Graph Extraction (STRICTLY SET 2 ONLY)

**CRITICAL ISOLATION INVARIANT:**
During Stage 1, you may read **ONLY** `output/set_2_corrected/*.md`. You are **STRICTLY FORBIDDEN** from reading `output/set_1_faithful/` or `output/AUDIT_REPORT.md` until Stage 1 and Stage 2 are completely finished and locked with a SHA-256 checksum.

Create `output/graph/knowledge_graph.json` with the following exact schema:

### 1. Metadata
- `schema_version`: `"1.0"`
- `generated_utc`: ISO-8601 timestamp
- `source_dir`: `"output/set_2_corrected"`
- `topic_count`: integer $K$
- `source_hashes`: dictionary mapping each Set 2 filename to its SHA-256 hash (enabling future incremental graph updates after Task 4 Mode B runs).

### 2. Vertices $V = V_{\text{topic}} \cup V_{\text{concept}}$
- **`topics` ($V_{\text{topic}}$):** One node per article in `output/set_2_corrected/`:
  - `id`: `"T01"`, `"T02"`, ..., `"T{K}"` (matching article index)
  - `filename`: exact filename in `output/set_2_corrected/`
  - `title`: clean human-readable title
  - `discipline`: primary track (e.g., `"Real Analysis"`, `"Linear Algebra"`, `"Probability & Stochastic Processes"`, `"Statistics & Inference"`, `"Machine Learning & Deep Learning"`, `"Signal Processing & Fourier Analysis"`)
  - `summary`: 1–2 sentence scope summary
- **`concepts` ($V_{\text{concept}}$):** Atomic mathematical objects extracted from Set 2 (definitions, theorems, lemmas, propositions, inequalities, algorithms, core structures). Avoid trivial vocabulary; extract substantive mathematical building blocks (target ~8–20 atomic concepts per article, deduplicated globally across all $K$ articles so each concept has **one** canonical ID):
  - `id`: `"C_<snake_case_slug>"` (globally unique)
  - `name`: canonical mathematical name (e.g., `"Cauchy Sequence"`, `"Jensen's Inequality"`, `"Singular Value Decomposition"`)
  - `kind`: one of `"definition" | "theorem" | "lemma" | "inequality" | "algorithm" | "structure"`
  - `canonical_topic_id`: the single topic ID `T##` where this concept is most thoroughly defined/derived
  - `referenced_in_topics`: list of all topic IDs `T##` that invoke or depend on this concept
  - `section_anchor`: exact Markdown heading in the canonical topic file
  - `short_statement`: 1-sentence rigorous summary of the concept

### 3. Typed Directed Edges $E = E_{\text{req}} \cup E_{\text{gen}}$
Use **strict Prerequisite Flow direction** for `requires`:
- **`requires` ($u \to v$):** Understanding, defining, or proving `target` ($v$) logically depends on `source` ($u$). *(Foundation $\to$ Dependent)*.
- **`generalizes` ($u \to v$):** `source` ($u$) is a strictly more general mathematical abstraction of `target` ($v$).
- Record two edge arrays:
  - `micro_edges`: directed edges between concept IDs (`source`, `target`, `relation`: `"requires" | "generalizes"`, `evidence`: brief justification citing the Set 2 section).
  - `macro_edges`: directed edges between distinct topic IDs (`source`, `target`, `relation`: `"requires" | "generalizes"`, `supporting_concept_edges`: list of micro-edge pairs justifying the topic dependency, `weight`: integer count of supporting concept dependencies).

---

## Stage 2: Deterministic Graph Verification & Topology Analytics (Pure Set 2)

Write and run `scripts/analyze_graph.py` reading **ONLY** `output/graph/knowledge_graph.json`. The script must:
1. **Validate Schema Integrity:** Assert zero dangling node IDs, zero self-loops, unique IDs, and valid relation types.
2. **Audit Cycles (Tarjan's SCC):** Run Strongly Connected Component detection strictly on the `requires` subgraph $G_{\text{req}}$ (both micro-level and macro-level). Report whether $G_{\text{req}}$ is a true Directed Acyclic Graph (DAG); if any non-trivial SCC exists, list the exact cycles so circular dependencies across Set 2 articles are exposed.
3. **Compute Topological Curriculum Order:** Run Kahn's algorithm on the macro `requires` DAG (or its condensation DAG if any cycle exists) to produce a valid ground-up reading sequence across all $K$ topics, grouped by discipline/layer.
4. **Compute Mathematical Centrality (on $G_{\text{req}}$):**
   - Direct out-degree (immediate downstream dependents)
   - Transitive descendant count (total concepts/topics downstream that rely on $u$)
   - In-degree & transitive ancestor count (prerequisite depth/load)
5. **Compute Prerequisite Dependency Cones:** For every topic $T_J$, compute its minimal ordered ancestor subgraph (exact prerequisite reading path).
6. **Emit Clean Public Report:** Write `output/graph/TOPOLOGY_REPORT.md` containing the DAG verification result, global topological reading order, top keystone concepts/topics by transitive downstream impact, and per-topic prerequisite paths. *(Zero Set 1 or Audit data may appear in this file.)*
7. **Lock Checksum:** Print and record the SHA-256 checksum of `output/graph/knowledge_graph.json` and `output/graph/TOPOLOGY_REPORT.md`.

---

## Stage 3: Strictly Decoupled Private Audit Overlay ($\phi$)

Now—and only now—read `output/AUDIT_REPORT.md` (with `output/graph/knowledge_graph.json` open strictly read-only).

**NON-MUTATION LAW:** You MUST NOT modify `output/graph/knowledge_graph.json` or `output/graph/TOPOLOGY_REPORT.md` in any way. Verify that their SHA-256 checksums are byte-for-byte identical after Stage 3 completes.

1. Create `output/graph/audit_overlay.json` mapping **existing** IDs from `knowledge_graph.json` to private epistemic metadata:
   - `topic_overlays`: keyed by existing `T##` IDs:
     - `errors_fixed_count`: integer from `AUDIT_REPORT.md`
     - `additions_count`: integer from `AUDIT_REPORT.md`
     - `topic_level_notes`: list of audit items (including any flawed Set 1 claims removed in Set 2 that have no concept node in $V_{\text{concept}}$)
   - `concept_overlays`: keyed by existing `C_...` IDs:
     - `epistemic_state`: one of:
       - `"solid"` — appeared in Set 1 with no mathematical error corrected in `AUDIT_REPORT.md`
       - `"corrected"` — appeared in Set 1, but had flawed assumptions, errors, or invalid proof steps fixed in Set 2
       - `"injected_prerequisite"` — absent from Set 1 entirely and newly added in Set 2 as a missing prerequisite/foundation
     - `audit_refs`: list of `{type: "error" | "addition", ref_id, topic_id, summary}` referencing `AUDIT_REPORT.md`
   - `edge_overlays`: keyed by existing `"<source>-><target>"` `requires` edges in `knowledge_graph.json`:
     - `is_gap_bridge`: boolean (`true` if `AUDIT_REPORT.md` indicates Set 1 jumped to `target` without establishing `source`)
     - `audit_ref`: brief reference from `AUDIT_REPORT.md`
2. Extend `scripts/analyze_graph.py` with an `--overlay` mode that joins `knowledge_graph.json` + `audit_overlay.json` in memory and writes `output/graph/PERSONAL_GAP_REPORT.md`, ranking:
   - Highest-leverage **injected prerequisites** (ordered by transitive downstream impact in $G_{\text{req}}$)
   - Highest-leverage **corrected concepts** (ordered by transitive downstream impact)
   - Cross-article recurring gap patterns (prerequisites missing across multiple distinct topics).

---

## Stage 4: Local Interactive Explorer (`output/graph/explorer.html`)

1. Have `scripts/analyze_graph.py` export thin browser-compatible JS wrappers alongside the JSON files so the viewer works offline via `file://` without browser CORS errors:
   - `output/graph/knowledge_graph.js` (`window.KNOWLEDGE_GRAPH = ...;`)
   - `output/graph/audit_overlay.js` (`window.AUDIT_OVERLAY = ...;`)
2. Build `output/graph/explorer.html` (clean modern dark UI, self-contained HTML/CSS/JS using Cytoscape.js or D3 via CDN with graceful fallback):
   - **Default State:** `Private Audit Overlay` is **OFF** by default, rendering the pure Set 2 graph identically whether `audit_overlay.js` is present or absent.
   - **Controls:**
     - View switch: `Macro (Topics)` vs. `Micro (Concepts)`
     - Relation filter: toggle `requires` and `generalizes` edges
     - Discipline filter & live search bar
     - Click any node: highlight its **exact prerequisite cone** (ancestors) and **downstream dependents**, and display its details + canonical file/section in the side inspector.
     - Single toggle switch: **`Private Audit Overlay: OFF / ON`** (visible only when `window.AUDIT_OVERLAY` is loaded). Toggling ON paints epistemic colors onto the existing layout without moving, adding, or deleting any nodes or edges (`solid` = green, `corrected` = amber, `injected_prerequisite` = red, `gap_bridge` edges = dashed red) and shows the audit citations in the inspector panel.

---

## Stage 5: Incremental Sync Readiness
Add a `--check-stale` flag to `scripts/analyze_graph.py` that compares `source_hashes` in `knowledge_graph.json` against the current files in `output/set_2_corrected/` and prints which topics have changed since the graph was last built (so future Task 4 Mode B updates only require refreshing the affected topics).
