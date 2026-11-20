# TASK 6: Corpus Normalization, Website Readiness Audit & Dual-Target Publication Pipeline

## Objective
Turn all $K$ pure Set 2 articles (`output/set_2_corrected/`) and the Task 5 concept graph (`output/graph/knowledge_graph.json`) into a notation-consistent, publication-ready corpus tailored to the target web CMS contract (Tiptap/ProseMirror JSON limits, math rendering rules, approved-demo/media workflows, and static Academy taxonomy), while preserving full-fidelity local Pandoc/KaTeX study builds.

## Global Privacy & Isolation Invariant
For ALL public/website deliverables (`STYLE_GUIDE.md`, `00_INDEX.md`, `00_GLOSSARY.md`, `output/web_export/*`, `output/local_html/*`), you are **STRICTLY FORBIDDEN** from reading or referencing `output/set_1_faithful/`, `output/AUDIT_REPORT.md`, or `output/graph/audit_overlay.json`. Every public deliverable must derive strictly from `output/set_2_corrected/` and `output/graph/knowledge_graph.json`.

---

## MODE A: Zero-Mutation Audit, Style Contract, Navigation & Dual-Target Exporter

**IMMUTABILITY INVARIANT (MODE A):**
During Mode A, `output/set_1_faithful/`, `output/set_2_corrected/`, `output/AUDIT_REPORT.md`, `output/00_ingestion_manifest.md`, `output/state_ledger.json`, and `output/graph/` are **STRICTLY READ-ONLY**. Compute a combined SHA-256 checksum over `output/set_2_corrected/*.md` and `output/graph/knowledge_graph.json` before Stage A1 and re-verify byte-for-byte identity after Stage A5.

### Stage A1: Deterministic Website Readiness & ProseMirror Budget Audit
Build and run `scripts/audit_web_readiness.py` scanning all $K$ articles in `output/set_2_corrected/` and emitting `output/web_export/WEB_READINESS_AUDIT.md` plus machine-readable `output/web_export/web_readiness_audit.json`.

For every article `T01`–`T{K}`, compute and report:
1. **Synthetic Tiptap/ProseMirror Budget Estimate:**
   - Parse the Markdown structure (headings, paragraphs, blockquotes, lists, fenced code, display math, inline math spans `$...$` / `\(...\)`, text marks `bold`/`italic`/`code`, links) into a realistic synthetic ProseMirror JSON tree rooted at `{"type": "doc", "content": [...]}` (modeling inline math as distinct child nodes that split parent paragraph text runs, and modeling realistic node attributes).
   - Measure:
     - `est_pg_jsonb_bytes`: UTF-8 byte length of `json.dumps(doc, ensure_ascii=False, separators=(", ", ": "))` (matching PostgreSQL's `octet_length(document::text)` spacing behavior).
     - `est_request_bytes`: `est_pg_jsonb_bytes` plus envelope (`title`, `summary`, `revision`).
     - `est_visited_nodes`: total recursive node count in the AST.
     - `est_max_depth`: maximum nesting depth in the AST.
   - Classify each article against the verified database/Worker limits (`500,000` bytes stored, `600,000` bytes save request, `10,000` visited nodes, depth `24`) using a **75% safety threshold**:
     - `PASS`: $\le 375{,}000$ bytes AND $\le 7{,}500$ nodes AND depth $\le 20$.
     - `WARN_SPLIT_RECOMMENDED`: between 75% and 95% of any limit.
     - `OVER_LIMIT_SPLIT_REQUIRED`: $> 95\%$ of any limit.
   - For every `WARN` or `OVER_LIMIT` article, propose clean multi-part split boundaries strictly at top-level `##` section headings so every resulting part satisfies `PASS`.
2. **Unsupported Website Feature Inventory (exact counts + file/line references):**
   - Cross-equation LaTeX references: `\label{...}`, `\ref{...}`, `\eqref{...}` (not supported by the target web CMS).
   - GFM pipe tables (row/column counts and whether cells contain math).
   - Markdown footnotes (`[^...]`).
   - Heading depth violations (`h1` inside body text, or `h5`/`h6` deeper than the supported `h2`–`h4`).
   - Invalid link schemes: any link not starting with `http://`, `https://`, or `mailto:` (including bare `#anchor` links and relative paths).
3. **LaTeX Macro & Environment Inventory:**
   - Catalog every distinct LaTeX environment (`\begin{...}`) and non-trivial command/macro (`\operatorname`, `\mathbbm`, `\bm`, `\xrightarrow`, `\substack`, `\tag`, custom macros, nested multiline structures, etc.) with usage counts across the corpus.
4. **Cross-Article Notation Drift Audit:**
   - Scan and tabulate inconsistent conventions across the corpus for vectors, matrices & transpose, random variables vs. realizations, expectation/variance/covariance/probability operators, norms, inner products, indicators, sets/differentials, and theorem/definition/proof callouts.

### Stage A2: Website LaTeX Stress-Test Battery
Generate `output/web_export/LATEX_TEST_BATTERY.md` containing one compact, deduplicated test case drawn from the Set 2 corpus for every nontrivial LaTeX construct discovered in Stage A1 (`aligned`, `cases`, `bmatrix`/`pmatrix`, `\operatorname`, `\tag`, nested subscripts/superscripts, multiline `\\` row breaks, piecewise definitions, etc.).

### Stage A3: Canonical Notation & Formatting Contract (`STYLE_GUIDE.md`)
Maintain `STYLE_GUIDE.md` at the repository root specifying:
1. Canonical mathematical notation across all disciplines.
2. Delimiter & LaTeX hygiene (`$...$` inline, `$$...$$` display, zero `\label`/`\ref`/`\eqref`, manual `\tag{...}` or prose references only).
3. Structural hierarchy (`h1` reserved for page title; body strictly `h2`–`h4`; formal statements in `>` blockquotes; proofs as regular body `**Proof.** ... $\square$` paragraphs).
4. Heading-stability rule: canonical `##`/`###`/`####` headings in `output/set_2_corrected/` remain aligned with `section_anchor` entries in `output/graph/knowledge_graph.json`.
5. Dual-target table rule: keep GFM pipe tables in canonical Set 2 for local Pandoc/KaTeX builds; convert tables cleanly to math-preserving structured lists during website export.
6. Media & demo placement marker syntax in staging manuscripts:
   - `<!-- MEDIA: <media_id> | kind=video|image | alt="..." | caption="..." -->` (`alt` and `caption` strictly $\le 500$ chars)
   - `<!-- DEMO: <demo_id> | title="..." -->`

### Stage A4: Corpus Navigation (`00_INDEX.md`, `00_GLOSSARY.md`) & `publication_manifest.json`
Run `scripts/build_navigation.py` reading strictly from `output/graph/knowledge_graph.json`, `output/set_2_corrected/`, and `output/web_export/web_readiness_audit.json` to generate:
1. **`output/00_INDEX.md`**: Master curriculum table sorted strictly by `(layer, topic_id)` and discipline reading tracks.
2. **`output/00_GLOSSARY.md`**: Alphabetical and discipline-indexed master glossary of all canonical concepts from `knowledge_graph.json`.
3. **`output/web_export/publication_manifest.json`**: Persistent registry keyed by `T01`–`T{K}`, enforcing `title <= 180`, `slug_preview <= 65`, `card_summary <= 120`, and `full_summary <= 500`.

### Stage A5: Dual-Target Export Pipeline (`scripts/export_corpus.py`)
Run `scripts/export_corpus.py` reading strictly from `output/set_2_corrected/`, `output/graph/knowledge_graph.json`, and `output/web_export/publication_manifest.json`:
1. **`--target web`** (writes to `output/web_export/essays/`): Exports all essays/parts, applies deterministic web-compatibility transforms, prepends `Prerequisites & Reading Context` blockquotes, re-validates 100% ProseMirror `PASS`, and writes `output/web_export/EXPORT_VALIDATION.md`.
2. **`--target local`** (writes to `output/local_html/`): Invokes `pandoc --katex` to compile standalone local HTML5 files preserving full tables, footnotes, and section anchors.
3. **Final Mode A Verification:** Re-verify pre-Stage-A1 SHA-256 checksums of `output/set_2_corrected/*.md` and `output/graph/knowledge_graph.json`, and confirm zero references to `set_1_faithful`, `AUDIT_REPORT.md`, or `audit_overlay.json` exist in any public deliverable.

---

## MODE B: Canonical Notation Harmonization on `output/set_2_corrected/` (WAIT FOR USER APPROVAL)

When instructed to run Mode B:
1. Harmonize cross-article mathematical notation across `output/set_2_corrected/*.md` strictly according to `STYLE_GUIDE.md`, and eliminate any `\label`/`\ref`/`\eqref` dependencies in favor of explicit manual `\tag{...}` or prose references.
2. **Mathematical & Structural Preservation Invariant:** Never drop derivations, assumptions, proofs, or tables from `output/set_2_corrected/`. Keep exact Markdown headings aligned with `section_anchor` values in `output/graph/knowledge_graph.json`.
3. Run full post-edit verification (`verify_set_2.py`, `audit_math_layout.py`, `audit_notation_protocol.py`, `analyze_graph.py --check-stale`, and `export_corpus.py`).
