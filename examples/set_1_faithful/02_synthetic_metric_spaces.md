# Synthetic Metric Spaces and Contractions

## 1. Metric Axioms

A metric $d: X \times X \to [0, \infty)$ measures distances on $X$ via nonnegativity, identity of indiscernibles, symmetry, and the triangle inequality. On $\mathbb{R}^n$, Euclidean distance $d(\mathbf{x}, \mathbf{y}) = \lVert \mathbf{x} - \mathbf{y} \rVert_2$ is a standard example.

## 2. Cauchy Sequences and Banach Contractions

A sequence $(x_n)$ is Cauchy if distances between late terms vanish. A space is complete if all Cauchy sequences converge inside it. A contraction $T: X \to X$ with constant $q \in [0, 1)$ satisfies $d(T(x), T(y)) \le q\,d(x, y)$ and therefore possesses a unique fixed point $x^*$ in a nonempty complete metric space, approached geometrically by iterating $x_{n+1} = T(x_n)$ from any starting point $x_0 \in X$.
