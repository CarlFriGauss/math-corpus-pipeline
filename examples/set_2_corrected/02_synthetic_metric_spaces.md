# Synthetic Metric Spaces and Contractions

## 1. Metric Axioms

Metric spaces generalize Euclidean distance to arbitrary sets equipped with a nonnegative separation functional. Working in an abstract metric space $(X, d)$ allows convergence and fixed-point arguments to apply uniformly across vectors, sequences, and function spaces.

> **Definition 2.1 — Metric Space.** Let $X$ be a nonempty set. A function $d: X \times X \to [0, \infty)$ is a *metric* on $X$ if for all $x, y, z \in X$: (1) $d(x, y) = 0$ if and only if $x = y$, (2) $d(x, y) = d(y, x)$, and (3) $d(x, z) \le d(x, y) + d(y, z)$. The pair $(X, d)$ is called a *metric space*.

On $\mathbb{R}^n$, the Euclidean norm induces the canonical metric $d(\mathbf{x}, \mathbf{y}) = \lVert \mathbf{x} - \mathbf{y} \rVert_2$, where the triangle inequality follows directly from the Cauchy-Schwarz inequality. A sequence $(x_n)_{n \ge 1}$ in $(X, d)$ is *Cauchy* if for every $\varepsilon > 0$ there exists $N \in \mathbb{N}$ such that $d(x_m, x_n) < \varepsilon$ whenever $m, n \ge N$. The space $(X, d)$ is *complete* if every Cauchy sequence in $X$ converges to a limit inside $X$.

## 2. Cauchy Sequences and Banach Contractions

A mapping $T: X \to X$ on a metric space $(X, d)$ is a *contraction* with Lipschitz constant $q \in [0, 1)$ if $d(T(x), T(y)) \le q\,d(x, y)$ for all $x, y \in X$. Iterating any contraction produces geometrically shrinking step sizes, which forces iterates to be Cauchy.

> **Theorem 2.2 — Banach Contraction Principle.** Let $(X, d)$ be a nonempty complete metric space and let $T: X \to X$ be a contraction with constant $q \in [0, 1)$. Then $T$ admits a unique fixed point $x^* \in X$ satisfying $T(x^*) = x^*$. Moreover, for any initial point $x_0 \in X$, the sequence $x_{n+1} = T(x_n)$ converges to $x^*$ with explicit error bound:
> $$
> d(x_n, x^*) \le \frac{q^n}{1 - q}\,d(x_1, x_0).
> $$

**Proof.** Fix any $x_0 \in X$ and define $x_{n+1} = T(x_n)$ for $n \ge 0$. Repeated application of the contraction bound yields $d(x_{k+1}, x_k) \le q^k\,d(x_1, x_0)$ for every $k \ge 0$. For integers $m > n \ge 0$, the triangle inequality and geometric series sum imply:

$$
\begin{aligned}
d(x_m, x_n) &\le \sum_{k=n}^{m-1} d(x_{k+1}, x_k) \\[10pt]
&\le d(x_1, x_0) \sum_{k=n}^{m-1} q^k \\[10pt]
&\le \frac{q^n}{1 - q}\,d(x_1, x_0).
\end{aligned}
$$

Since $q \in [0, 1)$, the upper bound tends to zero as $n \to \infty$, so $(x_n)$ is Cauchy. By completeness of $(X, d)$, there exists $x^* \in X$ with $x_n \to x^*$. Because every contraction is continuous, $T(x^*) = \lim_{n \to \infty} T(x_n) = \lim_{n \to \infty} x_{n+1} = x^*$. Uniqueness holds because if $T(y^*) = y^*$, then $d(x^*, y^*) = d(T(x^*), T(y^*)) \le q\,d(x^*, y^*)$, forcing $(1 - q)\,d(x^*, y^*) \le 0$ and hence $x^* = y^*$. Letting $m \to \infty$ in the geometric tail bound yields $d(x_n, x^*) \le \frac{q^n}{1 - q}\,d(x_1, x_0)$. $\square$
