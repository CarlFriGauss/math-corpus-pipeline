# Knowledge Base Distillation & Pedagogical Synthesis Engine

You are operating inside a dedicated workspace designed to extract, classify, synthesize, and rigorously refine theoretical notes across Mathematics, Statistics, Probability, and Machine Learning.

## 1. Source Directories (Read-Only, Full Tree Traversal)
Configure source paths in `config/sources.json` (see `examples/sources.example.json`) or place raw notes under `./raw_notes/`. Traverse the **entire directory tree** (using `os.walk` or `Path.rglob` to unlimited nesting depth) within all configured root paths.

**Tree Traversal & Exclusion Rules:**
- **Unlimited Depth:** Do not stop at the top-level directory; inspect every nested subdirectory at every level of the tree.
- **Ignore System/Cache Branches:** When walking the tree, automatically skip hidden/cache directories such as `.ipynb_checkpoints`, `.Rproj.user`, `.quarto`, `__pycache__`, `.git`, `.venv`, and `node_modules` so outdated auto-save checkpoints are never ingested.
- **CRITICAL SAFETY RULE:** Treat all source paths as **strictly READ-ONLY**. Never modify, move, rename, or delete any file in the source directories. All generated files and helper scripts must be written exclusively inside the current project workspace.

---

## 2. File Ingestion & Extraction Protocol

When scanning the directory trees, process only the following file types using these exact rules:

### A. Plain Markdown (`.md`)
- Extract 100% of the textual and mathematical content (including all LaTeX equations, definitions, theorems, proofs, and notes).

### B. Jupyter Notebooks (`.ipynb`)
- Parse the notebook JSON structure.
- Extract **ONLY** cells where `"cell_type": "markdown"`.
- **Strictly ignore** `"cell_type": "code"` cells, source code blocks, and execution outputs/tracebacks.

### C. R Markdown (`.Rmd`) and Quarto (`.qmd`)
- Extract **ONLY** the theoretical prose, Markdown sections, and LaTeX math blocks.
- **Strip out** all executable code chunks (e.g., ` ```{r ...} `, ` ```{python ...} `, etc.) and inline code execution blocks, retaining only document titles from YAML frontmatter if relevant to topic identification.

### D. PDF Files (`.pdf`) — Authorship & Orphan Check
Sometimes an `.md`, `.Rmd`, or `.qmd` note was rendered to `.pdf` (e.g., via Pandoc/LaTeX) and the original source file was deleted. Handle `.pdf` files with this three-step filter:
1. **Same-Name Check:** If `filename.pdf` exists alongside `filename.md`, `filename.Rmd`, `filename.qmd`, or `filename.ipynb` in the same folder, **skip the PDF** and read the Markdown/Notebook source directly.
2. **Authorship Verification (Personal Notes vs. External Publications):** For any standalone `.pdf`, inspect its metadata (Author, Creator, Producer such as Pandoc, LaTeX, RStudio, Quarto, wkhtmltopdf, Edge/Chrome print), page count, and first 2 pages:
   - **INCLUDE** if it is a personal note/article written by the author (e.g., Pandoc/LaTeX/RStudio/Obsidian export, personal proof/lecture notes, no commercial ISBN/DOI).
   - **EXCLUDE** if it is an external commercial textbook, third-party published journal paper, course syllabus/problem set authored by university staff, arXiv preprint by external authors, or software manual.
   - **Strip Code:** If an included personal PDF was rendered from R Markdown/Quarto/Jupyter and contains printed code blocks, extract only the theoretical prose and mathematical equations, ignoring the code blocks.
3. **Audit Logging:** Log every scanned PDF in `output/00_ingestion_manifest.md` with its path, status (`INCLUDED - Personal PDF`, `SKIPPED - Markdown Source Exists`, or `EXCLUDED - External Publication`), and reason.

---

## 3. Workspace Output Structure
Create and maintain the following directory structure inside this project workspace:
- `scripts/` — Python verification, graph analytics, incremental build, and export scripts.
- `output/00_ingestion_manifest.md` — Complete inventory of scanned files across all subfolder depths, PDF classification decisions, and the master Topic Classification Map.
- `output/set_1_faithful/` — Output directory for **Task 1** ($N$ faithful, lossless, deduplicated educational articles).
- `output/set_2_corrected/` — Output directory for **Task 2** ($N$ standalone, corrected, zero-prerequisite educational articles with exact 1-to-1 filename parity with Set 1).
- `output/AUDIT_REPORT.md` — Output file for **Task 3** (Comprehensive discrepancy, error correction, and prerequisite expansion report comparing Set 1 and Set 2).

---

## 4. Modular Task Routing
This project is divided into sequential tasks. Depending on the user's prompt, read and strictly follow the corresponding task specification file:
- **Task 1 (Classification & Faithful Lossless Compilation):** Read `tasks/TASK_1_SYNTHESIS.md`
- **Task 2 (Rigorous Standalone Correction & Completion):** Read `tasks/TASK_2_CORRECTION.md`
- **Task 3 (Comparative Discrepancy & Audit Report):** Read `tasks/TASK_3_AUDIT_REPORT.md`
- **Task 4 (Dynamic Incremental Updates & Baseline State Ledger):** Read `tasks/TASK_4_DYNAMIC_UPDATE.md`
- **Task 5 (Set 2 Concept Graph, Topology Analytics & Decoupled Audit Overlay):** Read `tasks/TASK_5_CONCEPT_GRAPH.md`
- **Task 6 (Corpus Normalization, Website Readiness Audit & Dual-Target Export):** Read `tasks/TASK_6_CORPUS_NORMALIZATION.md`

---

## 5. Standing Project-Wide Notation & Typesetting Invariant

All new articles, edits to `output/set_2_corrected/`, concept graph updates, and dual-target exports (`--target local` and `--target web`) MUST strictly conform to `STYLE_GUIDE.md` as the authoritative workspace contract:
1. **Global Mathematical Notation Protocol (`STYLE_GUIDE.md` §1):** Enforce consistent typography across scalars, scalar random variables, deterministic vectors (`\mathbf{x}, \boldsymbol{\theta}`), matrices (`\mathbf{A}, \mathbf{F}, \boldsymbol{\Sigma}`, context-gated `^\top`), random vectors (`\mathbf{X}` with dimension stated on first appearance and no letter reuse with matrices in the same section), vector/matrix entries (`x_j, x_{ij}, A_{ij}`), calligraphic spaces (`\mathcal{X}, \mathcal{H}, \mathcal{F}`), functions (`f, g \in L^2`), Bayesian/frequentist parameters (`\theta, \boldsymbol{\theta}, \Theta, \theta^*, \hat{\theta}`), signal-processing vectors/transforms (italic `x(t), x[n], X(\omega), X[k], \hat{f}(\omega)` vs lowercase bold `\mathbf{x}, \hat{\mathbf{x}} \in \mathbb{C}^N` and uppercase bold `\mathbf{F}, \mathbf{W}, \mathbf{U}`), and canonical operators/markers (`\mathbf{1}`, `\lVert \cdot \rVert`, `\langle \cdot, \cdot \rangle`, `\mathbb{E}[\cdot]`, context-gated `\mathbb{P}(\cdot)`, `\operatorname{Var}/\operatorname{Cov}/\operatorname{tr}/\operatorname{span}/\operatorname{rank}/\operatorname{diag}`, `\operatorname*{argmin}`, `\square`, preserving `\log` where intentionally base-agnostic or base-2).
2. **Delimiter Hygiene & Display Math Layout (`STYLE_GUIDE.md` §§2, 8):** Use `$...$` / `$$...$$` delimiters only with zero `\label`/`\ref`/`\eqref`, respect the `784px` inner reading width (`756px` inside blockquotes), enforce explicit three-tier vertical row spacing (`\\`, `\\[6pt]`, `\\[10pt]`), and keep tall constructs out of inline prose.
3. **Structural Hierarchy, Callouts & Knowledge Graph Parity (`STYLE_GUIDE.md` §§3, 4):** Restrict body headings to `h2`–`h4` (zero `h5`/`h6`), wrap formal statements (`Axiom`, `Definition`, `Theorem`, `Proposition`, `Lemma`, `Corollary`) in `>` blockquotes (`> **Theorem — Name.**`), keep `**Proof.** ... $\square$` as regular body paragraphs (never inside blockquotes and never italic `*Proof.*`), and preserve exact `output/graph/knowledge_graph.json` `section_anchor` headings (refreshing `source_hashes` and checking via `scripts/analyze_graph.py --check-stale` after any Set 2 modification).
4. **Mandatory Verification Gates:** Every modified Set 2 article must pass `scripts/verify_set_2.py`, `scripts/audit_math_layout.py` (0 violations), and `scripts/audit_notation_protocol.py` (0 hard violations) before re-exporting via `scripts/export_corpus.py`.

### Incremental Rebuild & Two-Ledger Maintenance Workflow

To decouple local HTML / web-export build state from semantic knowledge-graph state and prevent silent graph drift:

- **Two-Ledger Split:**
  - **`output/build_state.json`** tracks HTML/web build artifacts (`topic_id`, `sha256`, `word_count`, `headings`, `formal_callouts`, `last_built_utc` keyed by filename).
  - **`output/graph/knowledge_graph.json`** tracks semantic concepts, edges, `section_anchor`s, and `source_hashes` independently.
- **Maintenance CLI (`scripts/build_changed.py`):**
  - `python scripts/build_changed.py --dry-run` — Preview changed files, `MINOR`/`SUBSTANTIVE` classification, structural diffs, and planned actions without modifying any files.
  - `python scripts/build_changed.py` — Run quality/parity gates, rebuild local HTML (`output/local_html/`) + `<pre><code>` leak scan + web export (`output/web_export/`) for changed files, and update `output/build_state.json` without touching `knowledge_graph.json`.
  - `python scripts/build_changed.py --local-only` — Fast local reading rebuild (skips `--target web`); combines with `--topic T01,T02` to force-run specific topics.
  - `python scripts/build_changed.py --sync-minor` — Same build/gates, plus refreshes `knowledge_graph.json` `source_hashes` and exports JS **only** when every change is `MINOR` (identical headings/callouts and `abs(word_count_delta) < 150`); hard-blocks (`exit 2`) on any `SUBSTANTIVE` edit while keeping HTML builds current.
  - `python scripts/build_changed.py --confirm-graph-synced` — Run after updating concepts, edges, and `section_anchor`s in `knowledge_graph.json`; validates schema/DAG/anchors, refreshes `source_hashes` for verified files, exports JS, and asserts `analyze_graph.py --check-stale` reports `UP TO DATE`.
- **Standing "Ingest & Update" Contract:** In future sessions that add or revise Set 2 material, author all new math directly to `STYLE_GUIDE.md` from the first draft, update `output/graph/knowledge_graph.json` (and `output/web_export/publication_manifest.json` if an essay approaches ProseMirror/worker limits), and close by running `python scripts/build_changed.py --confirm-graph-synced` as the final pass/fail gate.
