"""Reference implementation of the Toshiba SQBM+ "qplib format" (Toshiba dialect).

This file documents the format as executable code. It is not a production tool. See
docs/qplib-formulation-guide.md for the background and the confidence level of each rule.

Conventions (confirmed against Fixstars Amplify SDK 1.7.3 output; see the guide):
    objective = 1/2 * sum_{(i, j, v) in Q, i >= j} v * x_i * x_j + sum_i B_i * x_i
                (a constant term cannot be written to the file; keep it on the client side)
    LHS_m <= sum_j A_mj * x_j <= RHS_m
    variable type: 0 = continuous (with lower/upper bounds), 1 = binary
    indices in the file are 1-based; this module uses 0-based indices internally.

Model holds *natural* polynomial coefficients through its builder methods:
    add_quadratic(i, j, c) means  c * x_i * x_j   ->  file value v = 2c
    add_linear(i, c)       means  c * x_i         ->  B_i += c

Run `python3 docs/reference/toshiba_qplib.py` to execute the self-tests.
"""
from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

INF = math.inf
# Amplify writes infinity as this string. It is DBL_MAX rounded up to 16 digits, so strtod()
# and float() both read it as +inf; the manual writes 1.79769313486232e+308 (same effect).
INF_TEXT = "1.797693134862316e+308"
BINARY, CONTINUOUS = 1, 0

TAG_N = "number of variables"
TAG_M = "number of constraints"
TAG_LHS_D = "default left-hand-side value"
TAG_RHS_D = "default right-hand-side value"
TAG_B_D = "default value for linear coefficients in objective"
TAG_VT_D = "default variable type"
TAG_UB_D = "default variable upper bound value"
TAG_LB_D = "default variable lower bound value"
TAG_Q = "number of quadratic terms in objective"
TAG_B = "number of non-default linear coefficients in objective"
TAG_A = "number of linear terms in all constraints"
TAG_LHS = "number of non-default left-hand-sides"
TAG_RHS = "number of non-default right-hand-sides"
TAG_UB = "number of non-default variable upper bounds"
TAG_LB = "number of non-default variable lower bounds"
TAG_VT = "number of non-default variable types"


def _is_inf(v: float) -> bool:
    return math.isinf(v) or abs(v) >= 1e300


def _fmt(v: float) -> str:
    if _is_inf(v):
        return INF_TEXT if v > 0 else "-" + INF_TEXT
    if float(v).is_integer() and abs(v) < 1e15:
        return str(int(v))
    return repr(float(v))


@dataclass
class Model:
    """Mixed binary/continuous QP with linear constraints (the qplib solver's problem class)."""

    sense: str = "minimize"
    name: str = "QPLIB_model"
    vtype: list[int] = field(default_factory=list)
    lb: list[float] = field(default_factory=list)
    ub: list[float] = field(default_factory=list)
    Q: dict[tuple[int, int], float] = field(default_factory=dict)  # file values, key (i, j) with i >= j
    B: dict[int, float] = field(default_factory=dict)
    rows: list[dict[int, float]] = field(default_factory=list)
    lhs: list[float] = field(default_factory=list)
    rhs: list[float] = field(default_factory=list)
    const: float = 0.0  # objective constant, client side only

    # ---------------------------------------------------------------- builder
    @property
    def n(self) -> int:
        return len(self.vtype)

    def add_binary(self) -> int:
        self.vtype.append(BINARY)
        self.lb.append(0.0)
        self.ub.append(1.0)
        return self.n - 1

    def add_continuous(self, lb: float, ub: float) -> int:
        self.vtype.append(CONTINUOUS)
        self.lb.append(float(lb))
        self.ub.append(float(ub))
        return self.n - 1

    def add_linear(self, i: int, c: float) -> None:
        """Add c * x_i to the objective."""
        self.B[i] = self.B.get(i, 0.0) + c

    def add_quadratic(self, i: int, j: int, c: float) -> None:
        """Add c * x_i * x_j to the objective (natural coefficient; stored as 2c)."""
        key = (max(i, j), min(i, j))
        self.Q[key] = self.Q.get(key, 0.0) + 2.0 * c

    def add_constraint(self, coeffs: dict[int, float], lhs: float = -INF, rhs: float = INF,
                       constant: float = 0.0) -> int:
        """lhs <= sum coeffs[j] * x_j + constant <= rhs (the constant is moved to both sides)."""
        row: dict[int, float] = {}
        for j, a in coeffs.items():
            row[j] = row.get(j, 0.0) + a
        self.rows.append({j: a for j, a in row.items() if a != 0.0})
        self.lhs.append(lhs - constant if not _is_inf(lhs) else -INF)
        self.rhs.append(rhs - constant if not _is_inf(rhs) else INF)
        return len(self.rows) - 1

    # ------------------------------------------------------------- semantics
    def objective(self, x: list[float], with_const: bool = True) -> float:
        """Value under the SQBM+ convention (the solver's 'value' excludes the constant)."""
        val = 0.5 * sum(v * x[i] * x[j] for (i, j), v in self.Q.items())
        val += sum(c * x[i] for i, c in self.B.items())
        return val + (self.const if with_const else 0.0)

    def violations(self, x: list[float], tol: float = 1e-6) -> list[tuple[str, int, float]]:
        """Return (kind, index, amount) for each violated constraint, bound, or integrality."""
        out = []
        for m, row in enumerate(self.rows):
            ax = sum(a * x[j] for j, a in row.items())
            if ax < self.lhs[m] - tol:
                out.append(("row", m, self.lhs[m] - ax))
            elif ax > self.rhs[m] + tol:
                out.append(("row", m, ax - self.rhs[m]))
        for i in range(self.n):
            if self.vtype[i] == BINARY and x[i] not in (0, 1):
                out.append(("binary", i, x[i]))
            elif x[i] < self.lb[i] - tol or x[i] > self.ub[i] + tol:
                out.append(("bound", i, x[i]))
        return out

    def problem_type(self) -> str:
        kinds = set(self.vtype)
        v = "B" if kinds == {BINARY} else "C" if kinds == {CONTINUOUS} else "G"
        c = "L" if self.rows else "B"
        return "Q" + v + c

    # ---------------------------------------------------------------- writer
    def to_text(self) -> str:
        """Serialize in the tag order of the SQBM+ manual (Table 15) = Amplify's order."""
        ptype = self.problem_type()
        vchar, cchar = ptype[1], ptype[2]
        out = [self.name if self.name.startswith("QPLIB_") else "QPLIB_" + self.name, ptype, self.sense]
        tag = lambda value, t: out.append(f"{value} # {t}")  # noqa: E731
        tag(self.n, TAG_N)
        if cchar == "L":
            tag(len(self.rows), TAG_M)
            tag(_fmt(-INF), TAG_LHS_D)
            tag(_fmt(INF), TAG_RHS_D)
        tag(0, TAG_B_D)
        if vchar == "G":
            vt_default = Counter(self.vtype).most_common(1)[0][0]
            tag(vt_default, TAG_VT_D)
        if vchar in ("C", "G"):
            lb_default = Counter(self.lb).most_common(1)[0][0]
            ub_default = Counter(self.ub).most_common(1)[0][0]
            tag(_fmt(ub_default), TAG_UB_D)
            tag(_fmt(lb_default), TAG_LB_D)
        q_items = sorted((k, v) for k, v in self.Q.items() if v != 0.0)
        if not q_items:  # SQBM+ rejects 0 quadratic terms; Amplify adds a zero dummy
            q_items = [((0, 0), 0.0)]
        tag(len(q_items), TAG_Q)
        out += [f"{i + 1} {j + 1} {_fmt(v)}" for (i, j), v in q_items]
        b_items = sorted((i, c) for i, c in self.B.items() if c != 0.0)
        if b_items:
            tag(len(b_items), TAG_B)
            out += [f"{i + 1} {_fmt(c)}" for i, c in b_items]
        if cchar == "L":
            a_items = [(m, j, a) for m, row in enumerate(self.rows) for j, a in sorted(row.items())]
            tag(len(a_items), TAG_A)
            out += [f"{m + 1} {j + 1} {_fmt(a)}" for m, j, a in a_items]
            for t, vals, default in ((TAG_LHS, self.lhs, -INF), (TAG_RHS, self.rhs, INF)):
                nd = [(m, v) for m, v in enumerate(vals) if not (_is_inf(v) and _is_inf(default) and v * default > 0)]
                if nd:
                    tag(len(nd), t)
                    out += [f"{m + 1} {_fmt(v)}" for m, v in nd]
        if vchar in ("C", "G"):
            for t, vals, default in ((TAG_UB, self.ub, ub_default), (TAG_LB, self.lb, lb_default)):
                nd = [(i, v) for i, v in enumerate(vals) if v != default]
                if nd:
                    tag(len(nd), t)
                    out += [f"{i + 1} {_fmt(v)}" for i, v in nd]
        if vchar == "G":
            nd = [(i, t) for i, t in enumerate(self.vtype) if t != vt_default]
            if nd:
                tag(len(nd), TAG_VT)
                out += [f"{i + 1} {t}" for i, t in nd]
        return "\n".join(out) + "\n"


# -------------------------------------------------------------------- parser
def parse_text(text: str) -> Model:
    """Tag-driven parser for the Toshiba dialect (accepts the manual's and Amplify's files)."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and ln[0] not in "!%"]
    name, ptype, sense = lines[0], lines[1].upper(), lines[2].lower()
    vchar, cchar = ptype[1], ptype[2]
    scalars: dict[str, float] = {}
    blocks: dict[str, list[list[str]]] = {}
    k = 3
    while k < len(lines):
        value, _, t = lines[k].partition("#")
        t = t.strip().lower()
        if t in (TAG_Q, TAG_B, TAG_A, TAG_LHS, TAG_RHS, TAG_UB, TAG_LB, TAG_VT, "number of pubo terms in objective"):
            cnt = int(value)
            blocks[t] = [lines[k + 1 + r].split() for r in range(cnt)]
            k += 1 + cnt
        else:
            scalars[t] = float(value)
            k += 1
    n = int(scalars[TAG_N])
    vt_default = BINARY if vchar == "B" else CONTINUOUS if vchar == "C" else int(scalars[TAG_VT_D])
    mdl = Model(sense=sense, name=name)
    mdl.vtype = [vt_default] * n
    mdl.lb = [scalars.get(TAG_LB_D, 0.0 if vchar == "B" else -INF)] * n
    mdl.ub = [scalars.get(TAG_UB_D, 1.0 if vchar == "B" else INF)] * n
    for i, t in blocks.get(TAG_VT, []):
        mdl.vtype[int(i) - 1] = int(t)
    for i, v in blocks.get(TAG_UB, []):
        mdl.ub[int(i) - 1] = float(v)
    for i, v in blocks.get(TAG_LB, []):
        mdl.lb[int(i) - 1] = float(v)
    for i, j, v in blocks.get(TAG_Q, []):
        key = (int(i) - 1, int(j) - 1)
        mdl.Q[key] = mdl.Q.get(key, 0.0) + float(v)
    b_default = scalars.get(TAG_B_D, 0.0)
    mdl.B = {i: b_default for i in range(n)} if b_default else {}
    for i, v in blocks.get(TAG_B, []):
        mdl.B[int(i) - 1] = float(v)
    m = int(scalars.get(TAG_M, 0)) if cchar == "L" else 0
    mdl.rows = [dict() for _ in range(m)]
    mdl.lhs = [scalars.get(TAG_LHS_D, -INF)] * m
    mdl.rhs = [scalars.get(TAG_RHS_D, INF)] * m
    for r, j, a in blocks.get(TAG_A, []):
        row = mdl.rows[int(r) - 1]
        row[int(j) - 1] = row.get(int(j) - 1, 0.0) + float(a)
    for r, v in blocks.get(TAG_LHS, []):
        mdl.lhs[int(r) - 1] = float(v)
    for r, v in blocks.get(TAG_RHS, []):
        mdl.rhs[int(r) - 1] = float(v)
    return mdl


def _normalized(mdl: Model):
    """Canonical content for semantic comparison of two files."""
    inf_norm = lambda v: math.inf if _is_inf(v) and v > 0 else -math.inf if _is_inf(v) else v  # noqa: E731
    return (
        mdl.sense,
        tuple(mdl.vtype),
        tuple(inf_norm(v) for v in mdl.lb),
        tuple(inf_norm(v) for v in mdl.ub),
        tuple(sorted((k, v) for k, v in mdl.Q.items() if v != 0.0)),
        tuple(sorted((k, v) for k, v in mdl.B.items() if v != 0.0)),
        tuple(tuple(sorted(r.items())) for r in mdl.rows),
        tuple(inf_norm(v) for v in mdl.lhs),
        tuple(inf_norm(v) for v in mdl.rhs),
    )


# ---------------------------------------------------------------- self-tests
def _test_manual_knapsack() -> None:
    """Knapsack example of the SQBM+ manual (section 3.4.4)."""
    v, w, cap = [11, 13, 17, 19], [2, 3, 5, 7], 10
    mdl = Model(name="QPLIB_knapsack")
    xs = [mdl.add_binary() for _ in v]
    for i, vi in zip(xs, v):
        mdl.Q[(i, i)] = -2 * vi  # the manual puts -2*v_i on the diagonal: 1/2 * (-2 v_i) x_i^2 = -v_i x_i
    mdl.add_constraint({i: wi for i, wi in zip(xs, w)}, lhs=0, rhs=cap)
    text = mdl.to_text()
    assert "QBL" in text and "1 1 -22" in text and "1 4 7" in text, text
    # The manual reports value -60 for x = [1, 1, 1, 1]: matches the 1/2 convention ...
    assert mdl.objective([1, 1, 1, 1]) == -60
    # ... but that solution violates the capacity constraint (weight 17 > 10).
    assert mdl.violations([1, 1, 1, 1]) == [("row", 0, 7.0)]
    best = min((mdl.objective(list(x)), x) for x in itertools.product((0, 1), repeat=4)
               if not mdl.violations(list(x)))
    assert best == (-41.0, (1, 1, 1, 0)), best
    print("ok  manual knapsack: value(-60) reproduced; [1,1,1,1] is infeasible; true optimum -41")


def _test_amplify_mixed(fixtures: Path) -> None:
    """File that Amplify 1.7.3 generated for:
        min 2*b0*r + 0.5*r^2 - 3*r + n + 4*b1
        s.t. r - 10*b0 <= 0,  b0 + b1 >= 1,  n + r <= 7
        b0, b1 binary; r real in [-1.5, 10]; n integer in [0, 5] (Amplify: n = q4 + 2 q5 + 2 q6)
    """
    amp = parse_text((fixtures / "amplify_mixed.qplib").read_text())
    rng = random.Random(0)
    for _ in range(200):
        b0, b1, q4, q5, q6 = (rng.randint(0, 1) for _ in range(5))
        r = rng.uniform(-1.5, 10)
        n = q4 + 2 * q5 + 2 * q6
        poly = 2 * b0 * r + 0.5 * r * r - 3 * r + n + 4 * b1
        assert abs(amp.objective([b0, b1, r, q4, q5, q6]) - poly) < 1e-9
    # Rebuild the same model with natural coefficients and compare the content.
    mdl = Model()
    b0, b1 = mdl.add_binary(), mdl.add_binary()
    r = mdl.add_continuous(-1.5, 10)
    q4, q5, q6 = mdl.add_binary(), mdl.add_binary(), mdl.add_binary()
    mdl.add_quadratic(b0, r, 2)
    mdl.add_quadratic(r, r, 0.5)
    for i, c in ((r, -3), (q4, 1), (q5, 2), (q6, 2), (b1, 4)):
        mdl.add_linear(i, c)
    mdl.add_constraint({r: 1, b0: -10}, rhs=0)
    mdl.add_constraint({b0: 1, b1: 1}, lhs=1)
    mdl.add_constraint({q4: 1, q5: 2, q6: 2, r: 1}, rhs=7)
    assert _normalized(parse_text(mdl.to_text())) == _normalized(amp)
    print("ok  Amplify mixed model: (i,j,v) means v/2*x_i*x_j; writer output is equivalent to Amplify's")


def _test_amplify_linear_objective(fixtures: Path) -> None:
    """Amplify adds a zero dummy quadratic term '1 1 0' when the objective has no quadratic term.
        min s  s.t. 3*b0 + 5*b1 - s + 2 <= 0,  b0 + b1 + b2 - 1 == 0,  s real in [0, 100]
    """
    amp = parse_text((fixtures / "amplify_linear_obj.qplib").read_text())
    mdl = Model()
    b = [mdl.add_binary() for _ in range(3)]
    s = mdl.add_continuous(0, 100)
    mdl.add_linear(s, 1)
    mdl.add_constraint({b[0]: 3, b[1]: 5, s: -1}, rhs=0, constant=2)
    mdl.add_constraint({b[0]: 1, b[1]: 1, b[2]: 1}, lhs=0, rhs=0, constant=-1)
    text = mdl.to_text()
    assert "1 # number of quadratic terms in objective\n1 1 0\n" in text
    assert "inf " not in text and f"-{INF_TEXT} # default left-hand-side value" in text, text
    amp.Q = {k: v for k, v in amp.Q.items() if v != 0.0}
    assert _normalized(parse_text(text)) == _normalized(amp)
    print("ok  Amplify linear objective: dummy '1 1 0' term; constants moved to LHS/RHS")


def build_tiny_schedule(p=(2, 1, 2), horizon=6, prec=((0, 2),), capacity=1):
    """Time-indexed scheduling example used in the guide (section 5, pattern P12).

    x[j, t] = 1 if job j starts at slot t;  cmax is a continuous variable.
    """
    mdl = Model(name="QPLIB_tiny_sched")
    x = {(j, t): mdl.add_binary() for j, pj in enumerate(p) for t in range(horizon - pj + 1)}
    cmax = mdl.add_continuous(0, horizon)
    mdl.add_linear(cmax, 1.0)  # min Cmax (linear objective -> dummy quadratic term is added)
    for j, pj in enumerate(p):  # (1) each job starts exactly once
        mdl.add_constraint({x[j, t]: 1 for t in range(horizon - pj + 1)}, lhs=1, rhs=1)
    for i, j in prec:  # (2) aggregated precedence  S_j - S_i >= p_i
        row = {x[j, t]: t for t in range(horizon - p[j] + 1)}
        for t in range(horizon - p[i] + 1):
            row[x[i, t]] = row.get(x[i, t], 0) - t
        mdl.add_constraint(row, lhs=p[i])
    for tau in range(horizon):  # (3) renewable resource capacity at each slot
        row = {x[j, t]: 1 for j, pj in enumerate(p) for t in range(horizon - pj + 1) if t <= tau < t + pj}
        mdl.add_constraint(row, rhs=capacity)
    for j, pj in enumerate(p):  # (4) Cmax >= S_j + p_j
        row = {x[j, t]: -(t + pj) for t in range(horizon - pj + 1)}
        row[cmax] = 1
        mdl.add_constraint(row, lhs=0)
    return mdl, x, cmax


def _test_tiny_schedule() -> None:
    p = (2, 1, 2)
    mdl, x, cmax = build_tiny_schedule(p)
    m2 = parse_text(mdl.to_text())
    best, nfeas = None, 0
    for starts in itertools.product(*(range(6 - pj + 1) for pj in p)):
        sol = [0.0] * m2.n
        for j, s in enumerate(starts):
            sol[x[j, s]] = 1
        sol[cmax] = max(s + pj for s, pj in zip(starts, p))
        if not m2.violations(sol):
            nfeas += 1
            best = min(best, m2.objective(sol)) if best is not None else m2.objective(sol)
    assert (m2.n, len(m2.rows), nfeas, best) == (17, 13, 12, 5.0), (m2.n, len(m2.rows), nfeas, best)
    print("ok  tiny time-indexed schedule: 17 vars, 13 rows, 12 feasible schedules, optimum Cmax = 5")


if __name__ == "__main__":
    fx = Path(__file__).with_name("fixtures")
    _test_manual_knapsack()
    _test_amplify_mixed(fx)
    _test_amplify_linear_objective(fx)
    _test_tiny_schedule()
    print("all self-tests passed")
