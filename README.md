# Mathematical Knowledge Base & Dual-Target Publishing Pipeline

A deterministic verification, concept-graph tracking, and dual-target compilation pipeline for curating large-scale mathematical and technical Markdown manuscripts.

This system transforms heterogeneous personal study notes (Markdown, Jupyter notebooks, R Markdown, Quarto, and standalone PDFs) into a cross-checked, notation-uniform corpus compiled simultaneously for **offline local study** (standalone HTML5 via Pandoc + KaTeX) and **web publishing** (budget-checked Markdown chunks compatible with ProseMirror/Tiptap editors and relational JSONB storage limits).

---

## 1. Plain-English Overview

### What Problem This Solves
Maintaining dozens of long-form mathematical essays introduces four recurring failure modes:

1. **Notation Drift:** Vectors, matrices, expectations, norms, and proof markers slowly diverge across chapters (e.g., `^T` vs. `^\top`, `\mathbb{1}` vs. `\mathbf{1}`, `*Proof.*` vs. `**Proof.** ... $\square$`).
2. **Broken Math Layouts:** Wide multi-step derivations overflow narrow reading columns horizontally, while missing row spacing (`\\` instead of `\\[6pt]` or `\\[10pt]`) causes fractions and integrals to collide vertically.
3. **Silent Dependency Drift:** Editing a theorem or renaming a section heading in one chapter quietly invalidates prerequisite links and glossary anchors in downstream chapters.
4. **Web CMS Size & Feature Limits:** Long derivations exceed database JSONB payload caps, AST node limits, or unsupported Markdown features (pipe tables, `\label`/`\ref`, `h5`/`h6` headings, relative anchors).

### High-Level Flow

```text
  Raw Notes (.md, .ipynb, .Rmd, .qmd, verified .pdf)
         │
         ▼  [Extraction & Lossless Compilation]
  output/set_1_faithful/          (faithful deduplicated source synthesis)
         │
         ▼  [Rigorous Correction & Standalone Completion]
  output/set_2_corrected/         (canonical standalone mathematical chapters)
         │
         ├──▶ [Semantic Extraction] ──▶ output/graph/knowledge_graph.json
         │
         ├──▶ [4 Fail-Fast Gates]   ──▶ verify_set_2 + layout + notation + parity
         │
         ├──▶ [Local Study Build]   ──▶ output/local_html/*.html  (Pandoc + KaTeX)
         │
         └──▶ [Web Export]          ──▶ output/web_export/essays/*.md
```

For an in-depth academic engineering analysis and full graph-theoretic proofs, see [docs/ARCHITECTURE_REVIEW.md](docs/ARCHITECTURE_REVIEW.md). For the canonical mathematical typography and formatting contract, see [STYLE_GUIDE.md](STYLE_GUIDE.md).

---

## 2. Core Mental Model

### The Two-Ledger Architecture (Why Two State Files Exist)

The incremental build wrapper (`scripts/build_changed.py`) intentionally separates **HTML/web build state** from **semantic knowledge-graph state** into two independent ledgers:

| Ledger File | What It Tracks | Updated When |
| :--- | :--- | :--- |
| **`output/build_state.json`** | Per-file SHA-256 hash, word count, `h2`–`h4` headings, formal callouts (`> **Theorem ...**`), and build timestamp. | Automatically after every verified local HTML / web rebuild. |
| **`output/graph/knowledge_graph.json`** | Canonical concepts, `requires` / `generalizes` dependency edges, `section_anchor` headings, and `source_hashes`. | **Only** when you explicitly authorize `--sync-minor` (for safe minor edits) or `--confirm-graph-synced` (after reviewing/updating the graph). |

**Why keep them separate?**
If rebuilding HTML automatically overwrote `source_hashes` in `knowledge_graph.json`, adding a new theorem or renaming a section would make the knowledge graph look "up to date" when its concepts and edges had never actually been updated. Separating the ledgers guarantees **zero silent graph drift**: your reading HTML can always be rebuilt immediately, while the semantic graph refuses to advance its hash until structural changes are reviewed.

### `MINOR` vs. `SUBSTANTIVE` Edits (and Why Exit Code `2` Is a Safety Lock)

Whenever a file in `output/set_2_corrected/` changes, `scripts/build_changed.py` compares the live file against its last verified snapshot in `output/build_state.json` and classifies the change:

- **`MINOR` Edit (Safe Cosmetic/Local Change):**
  All four conditions hold:
  1. The file is already tracked in both `output/build_state.json` and `output/graph/knowledge_graph.json` (and `knowledge_graph.json` has not fallen behind an earlier `build_state.json` update).
  2. The ordered list of `h2`–`h4` headings is **identical**.
  3. The ordered list of formal callouts (`Axiom`, `Definition`, `Theorem`, `Proposition`, `Lemma`, `Corollary`) is **identical**.
  4. The net word count change is strictly small: `abs(word_count_delta) < 150` (configurable via `--minor-word-threshold`).
  - *Concrete examples:* Fixing a typo, clarifying two sentences, breaking a wide equation across lines inside `\begin{aligned}`, adding `\\[6pt]`/`\\[10pt]` row spacing, replacing `\vec{x}` with `\mathbf{x}`.

- **`SUBSTANTIVE` Edit (Structural or Conceptual Change):**
  Any of the following is true:
  1. A new topic/file is not yet tracked in `build_state.json` or `knowledge_graph.json`.
  2. Any `h2`–`h4` heading was added, removed, or renamed.
  3. Any formal statement callout (`> **Theorem ...**`, `> **Definition ...**`, etc.) was added, removed, or reworded on its header line.
  4. `abs(word_count_delta) >= 150` words.
  5. `build_state.json` already moved past `knowledge_graph.json`'s `source_hashes` in an earlier default run (so the two ledgers are out of sync and `--sync-minor` can no longer prove the pending graph delta is cosmetic).
  - *Concrete examples:* Adding a new `##` section, adding or modifying a `> **Lemma ...**` statement, expanding a proof by 200+ words, or adding a brand-new chapter.

**Why Exit Code `2` Is a Safety Lock (Not a Crash):**
When you run `python scripts/build_changed.py --sync-minor`, the script first validates all quality gates, rebuilds your local HTML and web essays, and updates `output/build_state.json`. Only *after* your build succeeds does it check whether any changed file was `SUBSTANTIVE`. If any edit was `SUBSTANTIVE` (or if `knowledge_graph.json` was already behind `build_state.json`), `--sync-minor` exits with **code `2`**, leaving `knowledge_graph.json` untouched and printing the exact heading/callout/word diffs so you review the graph and close with `--confirm-graph-synced`.

### Division of Labor: Deterministic Scripts vs. Human / AI Judgment

| Task | Handled By | Why |
| :--- | :--- | :--- |
| Detecting changed files, hashing, and counting words/headings | Deterministic Python (`build_changed.py`, `state_manager.py`) | Exact byte-level reproducibility; zero guesswork. |
| Checking LaTeX delimiters, line widths, vertical row spacing, and notation rules | Deterministic Python (`verify_set_2.py`, `audit_math_layout.py`, `audit_notation_protocol.py`) | Mathematical typesetting constraints are mechanically verifiable. |
| Checking AST JSONB size, splitting `##` sections, converting pipe tables, compiling HTML | Deterministic Python + Pandoc (`audit_web_readiness.py`, `export_corpus.py`) | Repeatable format translation with strict pass/fail budgets. |
| Verifying Tarjan SCC acyclicity, computing condensation layers, checking `section_anchor` parity | Deterministic Python (`analyze_graph.py`, `build_changed.py`) | Graph topology invariants must never rely on intuition. |
| Writing new proofs, fixing subtle mathematical errors, authoring concepts and `requires` edges | **Human Author / AI Collaborator** | Semantic validity and pedagogical structure require mathematical reasoning. |

---

## 3. Prerequisites & Setup

All commands below assume your working directory is the repository root and use **relative paths only**.

### Required Tools
1. **Python 3.10+** (standard library powers all Set 2 verification, layout/notation auditing, knowledge-graph analytics, incremental builds, and web export).
2. **Pandoc** (required only for compiling local standalone HTML files via `export_corpus.py --target local`). Install from [pandoc.org](https://pandoc.org/installing.html) and ensure `pandoc` is on your system `PATH`.
3. **KaTeX** (loaded automatically in local HTML output via the CDN link in `scripts/templates/article.html`; an internet connection is needed when viewing rendered math in a browser unless you swap in a local KaTeX bundle).
4. **Optional Python Packages** (required only if running raw source ingestion / PDF extraction scripts: `scan_inventory.py`, `extract_corpus.py`, `state_manager.py`): listed in `requirements.txt`.

### Environment Setup

**Using `venv` (Linux / macOS):**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # optional: only needed for raw note/PDF ingestion
```

**Using `venv` (Windows PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt   # optional: only needed for raw note/PDF ingestion
```

**Using Conda (Cross-Platform):**
```bash
conda create -n math-corpus python=3.12 -y
conda activate math-corpus
pip install -r requirements.txt   # optional: only needed for raw note/PDF ingestion
```

Verify your toolchain before starting:
```bash
python --version
pandoc --version
```

---

## 4. Complete Command Cheat Sheet

### Incremental Build Wrapper (`scripts/build_changed.py`)

| Command | Mode / Flag | Behavior & Side Effects | Touches `knowledge_graph.json`? | Possible Exit Codes |
| :--- | :--- | :--- | :---: | :--- |
| `python scripts/build_changed.py --init` | Baseline initialization | Runs corpus-wide checks (`verify_set_2.py`, `audit_math_layout.py --all`, `audit_notation_protocol.py --all`, parity checks, HTML `<pre><code>` leak scan) and seeds `output/build_state.json`. Cannot combine with `--topic`. | No | `0` OK, `1` Gate/HTML error, `2` Invalid CLI args |
| `python scripts/build_changed.py --dry-run` | Preview only | Classifies every changed file (`MINOR` / `SUBSTANTIVE` / `UNCHANGED`), prints heading/callout/word diffs and planned actions. Modifies **zero** files. | No | `0` Preview complete, `1` Missing ledger |
| `python scripts/build_changed.py` | Default incremental build | Runs all 4 fail-fast gates on changed files, builds local HTML + scans `<pre><code>` leaks, exports web essays + checks `EXPORT_VALIDATION.md`, updates `output/build_state.json`. | No (runs `--check-stale` report only) | `0` OK, `1` Gate/Build/Leak failure |
| `python scripts/build_changed.py --local-only` | Fast local HTML build | Same quality gates, local HTML compile, `<pre><code>` leak scan, and `build_state.json` update, but **skips** `export_corpus.py --target web`. | No | `0` OK, `1` Gate/Build/Leak failure |
| `python scripts/build_changed.py --sync-minor` | Safe minor sync | Runs gates + local/web exports + updates `build_state.json`. If **all** changed files are `MINOR`, refreshes `knowledge_graph.json` `source_hashes` and exports `knowledge_graph.js`. If **any** change is `SUBSTANTIVE` (or KG already lagged behind `build_state.json`), **hard-blocks** graph mutation. | Yes, **only** if 100% `MINOR` | `0` Synced, `1` Gate/Build failure, **`2` Safety lock (`SUBSTANTIVE`)** |
| `python scripts/build_changed.py --confirm-graph-synced` | Post-review graph sync | Validates `knowledge_graph.json` schema + micro DAG acyclicity + condensation DAG + `section_anchor` parity, runs all 4 gates (`require_in_kg=True`), rebuilds stale exports, updates `build_state.json`, refreshes `source_hashes`, exports JS wrappers, and asserts `analyze_graph.py --check-stale` prints `UP TO DATE`. | Yes (`source_hashes` + JS export) | `0` Fully synced (`UP TO DATE`), `1` Schema/Anchor/Gate/Stale failure |
| `python scripts/build_changed.py --topic T08` (or `T08,T14`) | Topic filter | Forces the target set to the specified topic ID(s) (accepts `T08`, `8`, `08`). Combine with `--dry-run`, `--local-only`, `--sync-minor`, or `--confirm-graph-synced`. | Depends on mode flag | Same as selected mode |
| `python scripts/build_changed.py --minor-word-threshold 200` | Threshold override | Sets the minimum `abs(word_count_delta)` that triggers `SUBSTANTIVE` classification (default: `150`, must be `>= 1`). | Depends on mode flag | Same as selected mode (`2` if `< 1`) |

### Direct Individual Script Invocations

| Script | Typical Invocation | Purpose |
| :--- | :--- | :--- |
| **`verify_set_2.py`** | `python scripts/verify_set_2.py`<br>`python scripts/verify_set_2.py --file <filename.md>` | Checks H1 uniqueness, minimum length, 80% Set 1 parity ratio, balanced `$`/`$$` delimiters, `\begin`/`\end` matching, pipe-table `\|` escapes, and zero meta-commentary leaks. |
| **`audit_math_layout.py`** | `python scripts/audit_math_layout.py output/set_2_corrected/<file.md>`<br>`python scripts/audit_math_layout.py --topic T08`<br>`python scripts/audit_math_layout.py --all --json`<br>*Options:* `--width-budget 784`, `--px-per-em 23` | Audits display math horizontal pixel width (`784px` prose / `756px` blockquote), three-tier vertical row spacing (`\\`, `\\[6pt]`, `\\[10pt]`), inline tall constructs, and list-indented code math leaks. Returns exit `1` if `total_violations > 0`. |
| **`audit_notation_protocol.py`** | `python scripts/audit_notation_protocol.py output/set_2_corrected/<file.md>`<br>`python scripts/audit_notation_protocol.py --topic T08`<br>`python scripts/audit_notation_protocol.py --all --json` | Audits hard notation violations (`\vec`, `\bm`, `\mathbb{1}`, `\mathbbm`, `\text{Var}`, `\|`, `\blacksquare`, `\mathbf{\theta}`, `h5`/`h6`, `*Proof.*`, `> **Proof.**`), non-blockquote formal statements, and context-gated unbolded matrix warnings. |
| **`analyze_graph.py`** | `python scripts/analyze_graph.py`<br>`python scripts/analyze_graph.py --check-stale`<br>`python scripts/analyze_graph.py --export-js`<br>`python scripts/analyze_graph.py --overlay` | Validates `knowledge_graph.json`, runs Tarjan SCC + Kahn condensation DAG layering + centrality + dependency cones, emits `output/graph/TOPOLOGY_REPORT.md` and JS wrappers (`knowledge_graph.js`). `--overlay` validates `audit_overlay.json` and emits `PERSONAL_GAP_REPORT.md`. |
| **`audit_web_readiness.py`** | `python scripts/audit_web_readiness.py` | Models each Set 2 article as a synthetic ProseMirror JSON AST, classifies against DB/Worker limits (`75%`/`95%`), proposes balanced `##` splits, and writes `output/web_export/web_readiness_audit.json` + `WEB_READINESS_AUDIT.md`. |
| **`build_navigation.py`** | `python scripts/build_navigation.py` | Reads `knowledge_graph.json` and `web_readiness_audit.json` to emit `output/00_INDEX.md`, `output/00_GLOSSARY.md`, and `output/web_export/publication_manifest.json`. |
| **`export_corpus.py`** | `python scripts/export_corpus.py --target web`<br>`python scripts/export_corpus.py --target local --topic T08`<br>`python scripts/export_corpus.py --target local --dry-run`<br>`python scripts/export_corpus.py --target all` | Exports web-staging Markdown (`output/web_export/essays/` + `EXPORT_VALIDATION.md`) and/or standalone local HTML5 (`output/local_html/*.html` via `pandoc --katex`). |
| **`state_manager.py`** | `python scripts/state_manager.py scan`<br>`python scripts/state_manager.py scan --dry-run`<br>`python scripts/state_manager.py commit`<br>`python scripts/state_manager.py verify` | Task 4 upstream source watcher: tracks normalized `theory_sha256` across raw input directories in `output/state_ledger.json`, writes `output/pending_delta.md`, and verifies `cache/extracted/` snapshots. |

---

## 5. Step-by-Step Operational Playbooks

### Playbook A: Making a Quick Manual Edit (Typo, Wording, Minor Formula Tweak)

Use this workflow when fixing spelling, clarifying an existing paragraph, wrapping a long equation across lines, or fixing row spacing without altering headings, formal theorem callouts, or core concepts.

1. **Edit** the target file inside `output/set_2_corrected/`.
2. **Preview** what the pipeline detected (zero files changed yet):
   ```bash
   python scripts/build_changed.py --dry-run
   ```
   Confirm the file is classified as `[MINOR]`.
3. **Rebuild, verify all gates, and sync both ledgers:**
   ```bash
   python scripts/build_changed.py --sync-minor
   ```
   - If every check passes and the edit is `MINOR`, your local HTML (`output/local_html/`), web export (`output/web_export/essays/`), `output/build_state.json`, `output/graph/knowledge_graph.json` (`source_hashes`), and `knowledge_graph.js` are all updated automatically (`exit 0`).
   - If you accidentally crossed the 150-word threshold or modified a heading/callout line, `--sync-minor` will exit with code `2`. See **Playbook B** or **Troubleshooting** below.

### Playbook B: Adding Substantial New Math, a New Section, or a Brand-New Topic

Use this workflow whenever adding a new theorem/definition, inserting or renaming `##`/`###`/`####` headings, expanding a derivation by $\ge 150$ words, or introducing a brand-new chapter.

1. **Author to `STYLE_GUIDE.md` from the start:**
   - Use `$...$` and `$$...$$` delimiters only; zero `\label`/`\ref`/`\eqref`.
   - Wrap formal statements (`Axiom`, `Definition`, `Theorem`, `Proposition`, `Lemma`, `Corollary`) in `>` blockquotes (`> **Theorem — Name.**`).
   - Keep `**Proof.** ... $\square$` as regular body paragraphs (never inside blockquotes, never `*Proof.*`).
   - Stay within the `784px` width budget (`756px` inside blockquotes) and follow the three-tier `\\` / `\\[6pt]` / `\\[10pt]` spacing rules.
2. **Preview & build local/web artifacts first (keeping the graph locked):**
   ```bash
   python scripts/build_changed.py --dry-run
   python scripts/build_changed.py
   ```
   Fix any gate failures (`verify_set_2`, `audit_math_layout`, `audit_notation_protocol`, or `<pre><code>` leaks) before proceeding. Note that `output/build_state.json` updates, while `knowledge_graph.json` intentionally reports stale.
3. **Update metadata if structural boundaries changed:**
   - **New topic or changed `##` boundaries on a multi-part essay:** Re-run `python scripts/audit_web_readiness.py` and `python scripts/build_navigation.py` (or update the topic's entry in `output/web_export/publication_manifest.json`) so `publication_manifest.json`, `output/00_INDEX.md`, and `output/00_GLOSSARY.md` stay aligned.
   - **Graph update (Human + AI Collaborator):** In `output/graph/knowledge_graph.json`, add/update:
     * `topics` entry (if brand-new topic),
     * `concepts` entries (ensuring every `section_anchor` matches an exact `##`–`####` heading string in the Set 2 Markdown file),
     * `micro_edges` (strictly acyclic on `relation: "requires"`), and
     * `macro_edges` (aggregated `supporting_concept_edges` and matching integer `weight`).
4. **Confirm and lock graph synchronization:**
   ```bash
   python scripts/build_changed.py --confirm-graph-synced
   ```
   This validates the entire graph schema, micro DAG acyclicity, condensation DAG, `section_anchor` parity, refreshes `source_hashes`, exports `knowledge_graph.js`, and verifies `analyze_graph.py --check-stale` reports `UP TO DATE`.
5. **Optionally regenerate reports:**
   ```bash
   python scripts/analyze_graph.py
   ```
   to refresh `output/graph/TOPOLOGY_REPORT.md` with updated centrality and layer statistics.

### Playbook C: Inspecting Local HTML & Exporting Web Staging Bundles

- **Fast local HTML rebuild for one or two topics (skipping web export):**
  ```bash
  python scripts/build_changed.py --local-only --topic T08,T14
  ```
  Open the resulting `.html` file inside `output/local_html/` in any web browser. The local template includes a sticky collapsible table of contents, dark/light theme toggle, prerequisite navigation links, and KaTeX math rendering.
- **Inspecting the interactive Concept Graph Explorer:**
  Open `output/graph/explorer.html` directly in a browser (it loads `output/graph/knowledge_graph.js` cleanly over `file://` without CORS errors). Whenever `knowledge_graph.json` changes, refresh the JS wrapper via `python scripts/analyze_graph.py --export-js` (or `--confirm-graph-synced`).
- **Full web-staging export and verification:**
  ```bash
  python scripts/export_corpus.py --target web
  ```
  Inspect `output/web_export/EXPORT_VALIDATION.md` to confirm `100% PASS Verification: PASSED` across all exported essays in `output/web_export/essays/`.

### Playbook D: Git Checkpointing & Safe Rollback Workflow

Because `output/build_state.json`, `output/graph/knowledge_graph.json`, and `output/set_2_corrected/` work together as a synchronized state machine, always checkpoint before major edits:

1. **Before editing:** Verify clean state and create a Git checkpoint commit:
   ```bash
   python scripts/analyze_graph.py --check-stale
   git status
   git add -A
   git commit -m "Checkpoint before editing topic T08"
   ```
2. **If an edit fails verification or you want to revert cleanly:**
   ```bash
   git diff output/set_2_corrected/
   git checkout -- output/set_2_corrected/<file.md>
   ```
   Or restore both manuscripts and ledgers together to the last clean checkpoint:
   ```bash
   git restore output/set_2_corrected/ output/build_state.json output/graph/knowledge_graph.json
   python scripts/build_changed.py --local-only --topic T08
   python scripts/analyze_graph.py --check-stale
   ```

---

## 6. Troubleshooting Guide

### 1. Wide Display Equations (`WidthViolation` in `audit_math_layout.py`)
- **Symptom:** `exceeds 784px` (or `exceeds 756px` inside a blockquote callout).
- **Cause:** A long equality chain (`A = B = C = D`), inline side note `\text{(for all ...)}`, or trailing `\implies ...` exceeds the horizontal reading column.
- **Fix:** Wrap the derivation in `\begin{aligned} ... \end{aligned}` inside `$$...$$`, put each step on its own row aligned at `&=`, wrap long right-hand sides onto a continuation row starting with `&\quad +` or `&\quad -`, and move prose commentary out of the equation into surrounding text.

### 2. Missing Row Spacing (`SpacingViolation` in `audit_math_layout.py`)
- **Symptom:** `missing [6pt] spacing` or `spacing [6pt] < [10pt]`.
- **Cause:** Inside `aligned`, `gathered`, `cases`, or `array`, two adjacent rows share a plain `\\` (or `[6pt]`) when tall math is present.
- **Fix (Three-Tier Rule):**
  - Plain `\\`: **only** when both adjacent rows are compact single-line terms.
  - `\\[6pt]`: whenever either adjacent row contains `\frac`, `\dfrac`, `\tfrac`, `\binom`, `\sqrt`, `\left`/`\Bigl`/`\biggl` tall delimiters, or any row inside `\begin{cases}...\end{cases}`.
  - `\\[10pt]` (or `\\[12pt]`): whenever either adjacent row contains big operators (`\sum`, `\int`, `\prod`, `\lim`, `\limsup`, `\liminf`, `\bigcup`, `\bigcap`, `\operatorname*{...}`), nested fractions, embedded matrices/cases/arrays, or a logical step transition (`&\implies`, `&\iff`).

### 3. Notation & Callout Violations (`audit_notation_protocol.py` / Gate 3)
- **Symptom:** `HARD VIOLATIONS` or Gate 3 rejects `non_blockquote_formal`, `proof_blockquote`, `proof_italic`, `proof_heading`, or `legacy_qed`.
- **Fixes:**
  - Replace `\vec{x}` / `\bm{x}` with `\mathbf{x}` (or `\boldsymbol{\theta}` for Greek lowercase; never `\mathbf{\theta}`).
  - Replace `\mathbb{1}` / `\mathbbm{1}` with `\mathbf{1}`.
  - Replace `\text{Var}` / `\mathrm{Var}` / `\text{Cov}` / `\mathrm{Cov}` with `\operatorname{Var}` / `\operatorname{Cov}`.
  - Replace `\| x \|` inside math with `\lVert x \rVert` (and pipe-table `|x|` with `\lvert x \rvert`).
  - Replace `\blacksquare` / `\Box` with `\square`.
  - Wrap formal statements (`Axiom`, `Definition`, `Theorem`, `Proposition`, `Lemma`, `Corollary`) in `> **Theorem — Name.**` blockquotes.
  - Keep proofs as regular body paragraphs starting with `**Proof.**` (never `*Proof.*`, never `> **Proof.**`, never `### Proof`).
  - Eliminate `#####` / `######` (`h5`/`h6`) headings by promoting to `####` or bold lead-in text.
  - Review `[HEURISTIC WARNINGS: unbolded_matrix_indicator]` manually: bold matrix bases like `A^\top` $\to$ `\mathbf{A}^\top`, but ignore true scalar/set exponents like `2^T` or `e^{-sT}`.

### 4. `<pre><code>` List-Indentation Leaks (`IndentedCodeViolation` or `scan_html_code_leaks`)
- **Symptom:** Raw `$x^2$` or `\frac{a}{b}` renders inside a monospace `<pre><code>` code box in HTML.
- **Cause:** CommonMark/Pandoc interprets any non-fenced block indented $\ge 4$ spaces past the active list content column (or a list item whose text begins $\ge 5$ spaces after the bullet/number marker) as an indented code block.
- **Fix:** Align continuation paragraphs and `$$...$$` blocks strictly to the list item's content column (typically 2 or 3 spaces for `- item` or `1. item`), use single spaces after list markers (`- text`, `1. text`), or exit the list with an unindented paragraph/heading before placing unindented display math.

### 5. Broken `section_anchor`s or `publication_manifest.json` Split Mismatches (Gate 4)
- **Symptom:** `knowledge_graph section_anchor(s) missing` or `multi-part ## split-boundary mismatch`.
- **Fix:**
  - If you accidentally edited a heading referenced by a concept in `output/graph/knowledge_graph.json`, either restore the exact Markdown heading or update the matching `section_anchor` string(s) in `knowledge_graph.json`.
  - If you added, removed, or renamed a top-level `##` heading in a multi-part article, update `section_headings` / `start_heading` / `end_heading` in `output/web_export/publication_manifest.json` (or re-run `audit_web_readiness.py` + `build_navigation.py`).

### 6. Web Budget Breaches (`WARN_SPLIT_RECOMMENDED` / `OVER_LIMIT_SPLIT_REQUIRED`)
- **Symptom:** `export_corpus.py --target web` fails with `budget=OVER_LIMIT_SPLIT_REQUIRED` or `budget=WARN_SPLIT_RECOMMENDED`.
- **Cause:** Single essay exceeds 75% of ProseMirror/PostgreSQL/Worker safety budgets (`375,000` JSONB bytes, `450,000` request bytes, `7,500` AST nodes, or AST depth `20`).
- **Fix:** Run `python scripts/audit_web_readiness.py` to compute balanced `##` split boundaries, then run `python scripts/build_navigation.py` (updating split part metadata if needed) and re-run `python scripts/export_corpus.py --target web`.

### 7. Exit Code `2` on `python scripts/build_changed.py --sync-minor`
- **Symptom:** `[HARD-BLOCK] Refusing to edit knowledge_graph.json ... (exit code 2)`.
- **What actually happened:** Your quality gates passed, your local HTML and web essays rebuilt cleanly, and `output/build_state.json` was updated. Only `knowledge_graph.json` was held back because at least one file had structural changes (headings, formal callouts, $\ge 150$ words, or prior graph lag).
- **Fix:**
  1. Review the printed heading, callout, and word-count diff.
  2. Update concepts, edges, and `section_anchor`s in `output/graph/knowledge_graph.json` if needed (or confirm no semantic concept changes are required).
  3. Run:
     ```bash
     python scripts/build_changed.py --confirm-graph-synced
     ```
  (If the edit really was cosmetic except for exceeding 150 words, you can inspect the diff and still confirm via `--confirm-graph-synced`.)
