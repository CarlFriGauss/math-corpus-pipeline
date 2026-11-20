# Canonical Style, Notation & Publishing Contract (`STYLE_GUIDE.md`)

This contract governs both **canonical Set 2 manuscripts** (`output/set_2_corrected/*.md`, compiled locally via Pandoc + KaTeX) and **website-staging essays** (`output/web_export/essays/*.md`). Every convention below aligns with the ProseMirror/Tiptap, KaTeX, and database JSONB/worker validation rules verified by `scripts/audit_web_readiness.py`, `scripts/audit_math_layout.py`, and `scripts/audit_notation_protocol.py`.

---

## 1. Canonical Mathematical Notation Across All Disciplines

To ensure cross-chapter consistency and 100% KaTeX HTML+MathML fidelity, adopt these single canonical forms:

### 1.1 Global Mathematical Object & Symbol Hierarchy

| Object / Concept | Canonical Form | Disallowed / Legacy Variants | Rules & Context Gates |
| :--- | :--- | :--- | :--- |
| **Deterministic scalar / RV realization** | Lowercase italic (`x, y, c, \alpha`) | Bold scalars | Standard scalar typography (scalar constants such as integer size $N$ or period $T$ remain italic when unambiguous) |
| **Scalar random variable** | Uppercase italic (`X, Y, Z`) | Lowercase `x` for RVs | Distinct from realizations $x, y, z$ |
| **Deterministic column vector** ($\mathbb{R}^d, \mathbb{C}^d$) | Lowercase bold (`\mathbf{x}, \mathbf{v}, \boldsymbol{\theta}, \boldsymbol{\mu}`) | `\vec{x}`, `\bm{x}`, `\mathbf{\theta}`, `\underline{x}` | Use `\boldsymbol{...}` for Greek vectors; never `\mathbf{\theta}` or `\bm` |
| **Matrix** | Uppercase bold (`\mathbf{A}, \mathbf{X}, \mathbf{F}, \boldsymbol{\Sigma}`), transpose `^\top` | Unbolded `A`, `^T`, `^{T}`, `^{\mathsf{T}}`, `'` | Transpose `^\top` is **context-gated**: never alter scalar/time/horizon exponents like `e^{-sT}`, `\gamma^T`, `2^T`; inverse `\mathbf{A}^{-1}`, adjoint `\mathbf{A}^*` |
| **Random vector** | Uppercase bold (`\mathbf{X}, \mathbf{Y}, \mathbf{Z} \in \mathbb{R}^d`), realization `\mathbf{x}` | Unbolded `\mathbf{x}` for RVs or colliding letters | Always state space/dimension on first appearance; **never reuse the same letter for a matrix and a random vector in the same section** |
| **Vector / matrix entries** | Scalar italic (`x_j`, `x_{ij}`, `A_{ij}` or `(\mathbf{A})_{ij}`) | Bold entries `\mathbf{x}_j` | The $i$-th data vector is `\mathbf{x}_i` with $j$-th entry `x_{ij}` |
| **Spaces, domains & $\sigma$-algebras** | Calligraphic (`\mathcal{X}, \mathcal{H}, \mathcal{F}`) | Plain italic `X, H, F` near RVs | Mandatory calligraphic spaces whenever RVs appear in the same track; events `A, B, E \in \mathcal{F}` |
| **Functions & abstract space elements** | Italic (`f, g \in L^2`) | Bold functions `\mathbf{f} \in L^2` | Applies to continuous functions, kernels, sequences in $\ell^p$, and Hilbert-space vectors |

### 1.2 Domain-Specific Rules (Parameters, Signal Processing & Analysis)

- **Bayesian & frequentist parameters:** Bayesian random parameters use lowercase Greek (`\theta, \boldsymbol{\theta}`) with parameter space `\Theta`; frequentist truth `\theta^*`, estimator `\hat{\theta}` (distinguishing random estimator `\hat{\theta}(\mathbf{X})` from realized estimate `\hat{\theta}(\mathbf{x})`).
- **Signal processing:** Scalar signals `x(t), x[n]` and scalar frequency transforms `X(\omega), X[k]` / `\hat{f}(\omega)` stay italic; finite-dimensional signal vectors in the linear-algebra DFT view use lowercase bold (`\mathbf{x}, \hat{\mathbf{x}} \in \mathbb{C}^N`) with uppercase bold DFT/unitary matrices (`\mathbf{F}, \mathbf{W}, \mathbf{U}`).
- **Number systems & sets:** `\mathbb{N}, \mathbb{N}_0, \mathbb{Z}, \mathbb{Q}, \mathbb{R}, \mathbb{C}` ($\mathbb{N}=\{1,2,3,\dots\}$, $\mathbb{N}_0=\{0,1,2,\dots\}$); never `\mathbf{R}` or `\Re` for $\mathbb{R}$.
- **Bounds, limits & subsets:** `\sup S`, `\inf S`, `\limsup_{n\to\infty} x_n`, `\liminf_{n\to\infty} x_n` (never custom macros). Distinguish `\subseteq` (subset) from `\subsetneq` (proper subset); avoid bare `\subset`.
- **Differentials & complex quantities:** Thin-spaced italic `\,dx`, `\,dt`, `\,d\tau` (e.g., `\int_a^b f(x)\,dx`), and `\mu(dx)` or `\,dW_t` in measure-theoretic / Itô integrals. Imaginary unit $i$ ($i^2 = -1$), complex conjugate `\overline{z}`, Dirac delta `\delta(t)`.

### 1.3 Canonical Operators, Delimiters & Markers

| Concept | Canonical Form | Disallowed / Legacy Variants | Context Gate / Notes |
| :--- | :--- | :--- | :--- |
| **Indicator function** | `\mathbf{1}` (e.g., `\mathbf{1}_A`, `\mathbf{1}\{x > 0\}`) | `\mathbb{1}`, `\mathbbm{1}`, `I(\cdot)` | KaTeX-safe (`\mathbbm` unsupported) |
| **Norms** | `\lVert \cdot \rVert` (e.g., `\lVert \mathbf{x} \rVert_2`, `\lVert g \rVert_\infty`) | `\| \cdot \|`, `||x||` | Pipe-table safe; never use `\|` inside math |
| **Absolute value / cardinality** | `\lvert x \rvert`, `\lvert A \rvert` | Bare `|x|` inside GFM tables | Mandatory inside tables; preferred in prose |
| **Inner product** | `\langle \cdot, \cdot \rangle` | `(\mathbf{u}, \mathbf{v})` | Avoids ambiguity with ordered pairs and open intervals |
| **Expectation** | `\mathbb{E}[\cdot]` (e.g., `\mathbb{E}[X]`, `\mathbb{E}[Y \mid X]`) | `E[X]`, `E(X)`, `\mathbb{E}(X)` | Square brackets exclusively |
| **Probability measure** | `\mathbb{P}(\cdot)` (e.g., `\mathbb{P}(A)`, `\mathbb{P}_\theta(X \in A)`) | Bare `P(A)`, `\Pr(A)` | **Context-gated:** never touch polynomials $P(s), P_N(t)$, projections, or transition matrices |
| **Named operators** | `\operatorname{Var}`, `\operatorname{Cov}`, `\operatorname{tr}`, `\operatorname{span}`, `\operatorname{rank}`, `\operatorname{diag}` | `\text{Var}`, `\mathrm{Var}`, `\text{Cov}`, `\mathrm{Cov}`, `\mathbb{V}` | Uniform KaTeX HTML + MathML spacing (also `\operatorname{im}`, `\operatorname{dom}`) |
| **Optimization operators** | `\operatorname*{argmin}`, `\operatorname*{argmax}` | `\arg\min`, `\argmin`, `\argmax` | Places subscript cleanly under operator in display mode |
| **Divergences & Loewner order** | `D_{\mathrm{KL}}(\mathbb{P} \parallel \mathbb{Q})`, `\mathbf{A} \succeq \mathbf{B}`, `\mathbf{A} \succ \mathbf{B}` | `\ge` for PSD matrices | Distinguish matrix Loewner order from scalar inequality |
| **Logarithm** | `\ln x` (base $e$); `\log` where base-agnostic or `\log_2` | Ambiguous `\log x` in base-$e$ calculus | Preserve `\log` where intentionally base-agnostic or base-2 (e.g., $\log_2 N$, $O(N\log_2 N)$) |
| **QED marker** | `\square` | `\blacksquare`, `\Box` | Single uniform QED marker across all proofs |

---

## 2. Delimiter & LaTeX Hygiene (Web CMS Contract)

1. **Delimiters only:**
   - **Inline math:** `$...$` strictly on a single line. Never place whitespace immediately after opening `$` or immediately before closing `$` (e.g., `$x + 1$`, not `$ x + 1 $`), and never follow closing `$` immediately with a digit `\d`. Escape literal dollar signs in prose as `\$`.
   - **Display math:** `$$...$$` on dedicated delimiter lines with **no blank lines** inside multiline blocks.
   - Never use legacy `\( ... \)`, `\[ ... \]`, or bare `\begin{align}` / `\begin{gather}` outside `$$...$$`.
2. **KaTeX-safe environments & commands:**
   - Approved environments: `aligned`, `gathered`, `cases`, `bmatrix`, `pmatrix`, `array`, `smallmatrix`.
   - **Zero cross-equation LaTeX references:** Never use `\label{...}`, `\ref{...}`, or `\eqref{...}` (unsupported by target web parser). Use explicit manual `\tag{...}` (e.g., `\tag{2.1}`) or prose references (*"by Equation (2.1)"*, *"by Theorem 1.3"*).
   - **Zero custom macro definitions:** Never emit `\newcommand`, `\renewcommand`, `\def`, or `\DeclareMathOperator` (KaTeX resets its macro dictionary per equation).
   - **Preserve raw TeX syntax inside math:** Keep `_`, `*`, and `\\` literal inside `$...$` and `$$...$$`; never escape them as `\_` or `\*`.
3. **Per-equation & per-article size budgets:**
   - Individual equations must remain `<= 4,096` LaTeX characters (`<= 250` macro expansions, `<= 150,000` rendered HTML characters).
   - Website essays must satisfy the ProseMirror/PostgreSQL/Worker `PASS` budget: `est_pg_jsonb_bytes <= 375,000` (75% of 500,000), `est_request_bytes <= 450,000` (75% of 600,000), `est_visited_nodes <= 7,500` (75% of 10,000), and `est_max_depth <= 20` (limit 24).
   - Articles exceeding 75% (`WARN_SPLIT_RECOMMENDED` or `OVER_LIMIT_SPLIT_REQUIRED`) must be split cleanly at top-level `##` headings during website export.

---

## 3. Structural Hierarchy & Semantic Callouts

1. **Heading levels:**
   - `h1` (`# Title`) is **strictly reserved** for line 1 of canonical Set 2 files (page title). Zero `h1` headings may appear inside body prose. During `--target web` export, the leading `# Title` line is stripped because the target site renders `article.title` (`<= 180` chars) as the page `<h1>`.
   - Body sections strictly use `h2` (`##`), `h3` (`###`), and `h4` (`####`).
   - **Zero `h5`/`h6` headings:** Target document validators reject heading levels outside `{2, 3, 4}`. Canonical Set 2 manuscripts must eliminate all `h5`/`h6` headings, and `--target web` automatically converts any `h5`/`h6` into bold lead-in paragraphs (`**Heading.**`).
2. **Standardized semantic callouts:**
   - Wrap **formal statements** (`Axiom`, `Definition`, `Theorem`, `Proposition`, `Lemma`, `Corollary`) in `>` blockquotes with bold headers (`> **Theorem — Name.**` or `> **Theorem 1.3 — Name.**`).
   - Keep **proofs** (`**Proof.** ... $\square$`, `**Proof Sketch.** ... $\square$`, `**Proof Idea.** ... $\square$`) as **regular body paragraphs** immediately following the theorem/lemma/proposition (**NOT** inside blockquotes, never italic `*Proof.*`, and never `\blacksquare` or `\Box`):
     ```markdown
     > **Definition 1.2 — Cauchy Sequence.** A sequence $(a_n)$ in $\mathbb{R}$ is *Cauchy* if ...

     > **Theorem 1.3 — Completeness Equivalence.** Every Cauchy sequence in $\mathbb{R}$ converges.

     **Proof.** Let $(a_n)$ be Cauchy... $\square$
     ```
   - Supported formal statement labels: `Axiom`, `Definition`, `Theorem`, `Proposition`, `Lemma`, `Corollary`. (Advisory `Remark`, `Example`, or warning callouts may use `>` blockquotes or standard body paragraphs, while proofs always remain regular body paragraphs.)

---

## 4. Heading-Stability Rule (Knowledge Graph Alignment)

`output/graph/knowledge_graph.json` anchors canonical mathematical concepts via exact `section_anchor` heading strings inside `output/set_2_corrected/`.
- In canonical Set 2 (`output/set_2_corrected/`), existing `##`, `###`, and `####` headings referenced by `section_anchor` **must remain intact** (do not casually rename or renumber section headings).
- When converting heading-style theorems/proofs (`### Theorem...`, `##### Proof`) into blockquote callouts, check against `knowledge_graph.json`: if a heading is a `section_anchor`, either retain the `###`/`####` structural section heading above the blockquote callout or deterministically update the matching `section_anchor` in `knowledge_graph.json`.

---

## 5. Dual-Target Table, Footnote & Link Rules

1. **Tables (Dual-Target):**
   - **Local Pandoc/KaTeX builds (`output/set_2_corrected/` & `output/local_html/`):** Retain GFM pipe tables. Always use `\lvert`, `\rvert`, `\lVert`, `\rVert` inside table cells instead of `|` or `\|`.
   - **Website export (`output/web_export/essays/`):** When targeting ProseMirror schemas without `table` nodes, `scripts/export_corpus.py --target web` deterministically converts every GFM pipe table into a readable, math-preserving structured bullet list (`- **Column1:** val1 — **Column2:** val2; ...`), keeping 100% of mathematical formulas intact.
2. **Footnotes:**
   - Avoid `[^1]` Markdown footnotes in canonical Set 2. If any are introduced, `--target web` converts them into inline parenthetical notes or a trailing `## Notes` bullet list.
3. **Links:**
   - Every Markdown hyperlink `[text](url)` on the website must validate against `http://`, `https://`, or `mailto:`. Bare `#anchor` links and relative paths are forbidden in exported essays; `scripts/export_corpus.py --target web` resolves internal cross-article links to `published_url` from `publication_manifest.json` when populated, or renders unresolved internal links as plain-text citations (`*(see Article T##: Title)*`).

---

## 6. Media & Interactive Demo Placement Markers (Staging Manuscripts)

To prepare staging essays (`output/web_export/essays/`) and canonical Set 2 manuscripts for visual media and interactive demonstrations without embedding raw HTML or unverified URLs, use standardized HTML comment placeholders:

- **Uploaded Media Placeholder:**
  ```markdown
  <!-- MEDIA: <media_id> | kind=video|image | alt="..." | caption="..." -->
  ```
  - `kind` must be `image` (exported as `image/webp`) or `video` (`video/mp4` / `video/webm`).
  - `alt` and `caption` strings must each be strictly `<= 500` characters.
- **Approved Interactive Demo Placeholder:**
  ```markdown
  <!-- DEMO: <demo_id> | title="..." -->
  ```
  - `<demo_id>` must match an approved entry in the target site's demo registry.
  - During Pandoc local builds (`--target local`), HTML comments are silently ignored; during Tiptap JSON conversion, they map cleanly to `media` and `interactiveDemo` atom nodes.

---

## 7. Publication Metadata Limits (`publication_manifest.json`)

Every essay (and every split part) registered in `publication_manifest.json` must satisfy CMS database and edge worker limits:
- `title` / `part_title`: `<= 180` characters
- `slug_preview`: `<= 65` characters (`NFKD` ASCII lowercase alphanumeric hyphenated slug)
- `card_summary`: `<= 120` characters (complete sentence that will not clip mid-word in essay cards)
- `full_summary`: `<= 500` characters

---

## 8. Display Math Line-Breaking & Vertical Spacing

All display equations (`$$...$$`) in canonical Set 2 manuscripts and exported builds must fit comfortably within the live website and local study reading column without horizontal overflow, clipping, or vertical collision between tall operators.

1. **Target Visual Reading Width (`784px` Budget):**
   - The reading container is capped at `840px` max width with `28px` horizontal padding per side, yielding a **`784px` inner reading width** (`756px` inside single-level blockquotes).
   - Never leave long multi-step equality/inequality chains (e.g., `A = B = C = D`) or wide expressions on a single horizontal line that exceeds the `784px` budget.
   - Break multi-step derivations across lines inside `\begin{aligned}...\end{aligned}`:
     - Align primary step operators on the left margin (`&=`, `&\le`, `&\ge`, `&\approx`, `&\equiv`, `&\implies`, `&\iff`).
     - When a single right-hand side is too wide for `784px`, wrap continuation terms onto a subsequent line and indent with `&\quad +` / `&\quad -` / `&\qquad`.
     - Do **not** let trailing `\text{(...)}` annotations, domain qualifiers (`\qquad (x \in \mathbb{R})`), or `\implies ...` conclusions push an equation past the `784px` margin: move commentary into surrounding prose, place the `\implies` step on its own aligned row, or wrap side conditions onto a dedicated `&\quad` line.
     - Note: `overflow-x: auto` in CSS is strictly a non-clipping safety net for unavoidable wide matrices, never a substitute for proper line breaking.

2. **Explicit Vertical Row Spacing (`\\`, `\\[6pt]`, `\\[10pt]` / `\\[12pt]`):**
   Inside multiline environments (`aligned`, `gathered`, `cases`, `array`), default `\\` spacing is too tight whenever fractions, roots, or big operators appear. Follow this three-tier spacing rule based on the contents of the two **adjacent** rows (the row before `\\` and the row immediately after `\\`):
   - **Plain `\\`:** Allowed **only** when both adjacent rows are compact single-height lines (no `\frac`, `\dfrac`, `\tfrac`, `\sqrt`, tall `\left(...\right)` delimiters, `cases`, `\sum`, `\int`, `\prod`, `\lim`, or nested matrices).
   - **`\\[6pt]`:** Mandatory whenever either adjacent row contains fractions (`\frac`, `\dfrac`, `\tfrac`), roots (`\sqrt`), tall auto-sized delimiters (`\left(...\right)`, `\left[...\right]`, `\left\lvert...\right\rvert`, `\Bigl`/`\Bigr`), or between rows inside `\begin{cases}...\end{cases}` (unless upgraded to `\\[10pt]` by big operators below).
   - **`\\[10pt]` (or `\\[12pt]`):** Mandatory whenever either adjacent row contains large stacked/limit operators (`\sum`, `\int`, `\iint`, `\oint`, `\prod`, `\lim`, `\limsup`, `\liminf`, `\sup`, `\inf` with subscripts, `\bigcup`, `\bigcap`), nested/compound fractions (`\frac` containing `\frac` or `\sum`/`\int`), embedded matrices (`bmatrix`/`pmatrix`), or a **logical step transition** (such as stepping from an algebraic expansion to `&\implies` / `&\iff`, or separating two distinct equations stacked in `aligned`/`gathered`).

   *Canonical Example:*
   ```latex
   $$
   \begin{aligned}
   \hat{f}(\omega) &= \int_{-\infty}^{\infty} f(t) e^{-i\omega t}\,dt \\[10pt]
   &= -\frac{1}{i\omega} \left[f(t) e^{-i\omega t}\right]_{-\infty}^{\infty} \\[10pt]
   &\quad + \frac{1}{i\omega} \int_{-\infty}^{\infty} f'(t) e^{-i\omega t}\,dt \\[10pt]
   &\implies \mathcal{F}\{f'\}(\omega) = i\omega\,\hat{f}(\omega)
   \end{aligned}
   $$
   ```

3. **Inline Prose Hygiene (Keep Tall Constructs in Display Blocks):**
   - Keep tall display constructs out of inline prose `$...$` where they distort paragraph line height (`line-height`) and collide with adjacent lines of text.
   - Avoid `\displaystyle`, `\dfrac`, multi-story fractions, `\begin{bmatrix}` / `\begin{pmatrix}` / `\begin{cases}`, and tall stacked `\sum_{...}^{...}` / `\int_{...}^{...}` inside running prose paragraphs—either write compact inline notation (`a/b`, `\sum_{k=0}^{N-1} x_k`) or promote the formula to a dedicated `$$...$$` display block.
