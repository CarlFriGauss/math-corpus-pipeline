# TASK 4: Dynamic Incremental Ingestion, Holistic Integration & Selective Audit

## Objective
Maintain the knowledge base dynamically over time without reprocessing unchanged files or untouched topics. Detect strictly new or modified theoretical material across all configured source paths, integrate only genuine new information holistically into the appropriate topic articles, and propagate updates selectively to Set 2 and `output/AUDIT_REPORT.md`.

## Mode A: Baseline Freeze (One-Time Initialization)
When instructed to **bootstrap / freeze the baseline**:
1. Create `scripts/state_manager.py`, reusing the exact file-discovery, checkpoint-exclusion, code-stripping, and PDF-filtering logic already established in `scripts/`.
2. For every currently ingested source file from `output/00_ingestion_manifest.md`:
   - Extract its theoretical text (stripping all code cells/chunks) and normalize whitespace.
   - Compute `theory_sha256` (SHA-256 of the normalized theoretical text).
   - Save the extracted text snapshot to `cache/extracted/<sha256_prefix>_<sanitized_name>.md`.
   - Record `{path, file_type, status, theory_sha256, snapshot_file, mapped_topics, last_ingested_utc}` in `output/state_ledger.json`.
3. Do **NOT** modify any existing files in `output/set_1_faithful/`, `output/set_2_corrected/`, or `output/AUDIT_REPORT.md` during baseline freeze.

## Mode B: Incremental Dynamic Update
When instructed to **run an incremental update**:

### Step 1: Deterministic Delta Scan
Run `python scripts/state_manager.py scan` to generate `output/pending_delta.md`, classifying all files across the source directories in `GEMINI.md` into:
- **UNCHANGED:** Path exists and `theory_sha256` matches `state_ledger.json` -> **Ignore completely**.
- **RENAMED/MOVED:** New path has a `theory_sha256` already in `state_ledger.json` -> Update path in ledger, **no LLM work**.
- **DELETED:** Previously tracked path missing -> Log in manifest/ledger, **do NOT delete knowledge** from Set 1 or Set 2 unless explicitly instructed.
- **NEW FILE:** Unseen path and unseen `theory_sha256` (passing PDF authorship filter if `.pdf`) -> Full extracted theory goes into `pending_delta.md`.
- **MODIFIED FILE:** Existing path with a changed `theory_sha256` -> Compute unified text diff against its cached snapshot in `cache/extracted/` and place the exact new/modified theoretical blocks into `pending_delta.md`.

If `pending_delta.md` contains zero new or modified theoretical blocks, report *"Knowledge base is already up to date"* and stop.

### Step 2: Topic Classification & Novelty Check
Read the topic index (`output/00_ingestion_manifest.md` and current filenames in `output/set_1_faithful/`). For each delta block $\Delta$ in `output/pending_delta.md`:
1. **Route $\Delta$** to an existing Topic $J \in \{1, \dots, K\}$, or declare a **New Topic $K+1$** only if $\Delta$ represents a genuinely distinct mathematical/statistical subject not covered by Topics $1 \dots K$.
2. **Novelty Check (for existing Topic $J$):** Read `output/set_1_faithful/J_...md`. Determine whether $\Delta$ introduces any genuinely new definitions, theorems, proof steps, nuances, intuitions, or examples not already present in Article $J$.
   - If $\Delta$ is **pure duplication**, log it as `DUPLICATE_SKIPPED` and leave Article $J$ untouched across Set 1, Set 2, and the Audit Report.

### Step 3: Holistic Set 1 Integration (Affected Topics Only)
For every existing Topic $J$ with genuine new information $\Delta$:
- **DO NOT append $\Delta$ mechanically to the bottom of the file.**
- Rewrite `output/set_1_faithful/J_...md` holistically so that $\Delta$ is seamlessly woven into the proper pedagogical position, strictly preserving **100% of prior Set 1 content + 100% of $\Delta$**, deduplicating overlap, and preserving the **Task 1 Zero-Critique Law** (faithfully keeping any mistakes in $\Delta$).
For any **New Topic $K+1$**, follow `tasks/TASK_1_SYNTHESIS.md` to create `output/set_1_faithful/(K+1)_<slug>.md`.

### Step 4: Selective Set 2 Propagation (Affected Topics Only)
For each modified Topic $J$, compare $\Delta$ against `output/set_2_corrected/J_...md` and apply the exact matching rule:
- **Already Covered in Set 2:** If $\Delta$ is mathematically valid and already fully covered in Set 2 Article $J$, leave Set 2 Article $J$ **unchanged**.
- **Correct & Self-Contained, Missing from Set 2:** Integrate $\Delta$ holistically into `output/set_2_corrected/J_...md` without re-auditing unrelated sections, keeping Set 2 a complete standalone superset of Set 1.
- **Contains Errors or Introduces Incompleteness/Missing Prerequisites:** Follow `tasks/TASK_2_CORRECTION.md` to holistically update `output/set_2_corrected/J_...md` with the corrected formulation, full derivations, and any needed prerequisite background.
For any **New Topic $K+1$**, follow `tasks/TASK_2_CORRECTION.md` to create `output/set_2_corrected/(K+1)_<slug>.md`.

### Step 5: Selective Audit Report Update & Ledger Commit
1. Update `output/AUDIT_REPORT.md` **only** for modified topics $J$ and newly created topics $K+1$ (updating the Executive Summary Table, modifying `# Article J` to reflect resolved gaps or newly corrected errors, and appending a brief dated `## Update Log` entry at the bottom).
2. Run `python scripts/state_manager.py commit` to update `output/state_ledger.json`, refresh `cache/extracted/`, and update `output/00_ingestion_manifest.md`.
