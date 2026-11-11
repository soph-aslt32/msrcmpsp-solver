"""Generate the SQBM+ probe files listed in docs/qplib-formulation-guide.md, section 12.

Usage: python3 docs/reference/make_probes.py   (writes docs/reference/probes/*.qplib)
Send each file with e.g.
  curl -H "Content-Type: application/octet-stream" -X POST \
       "http://<server>:8000/solver/qplib?timeout=1&detail_level=1" --data-binary @<file>
"""
from pathlib import Path

from toshiba_qplib import INF_TEXT, Model

OUT = Path(__file__).with_name("probes")

U1 = """QPLIB_probe_offdiag
QBB
minimize
2 # number of variables
0 # default value for linear coefficients in objective
1 # number of quadratic terms in objective
2 1 -2
2 # number of non-default linear coefficients in objective
1 0.6
2 0.6
"""
# expected: [0,0] value 0 if (i,j,v) means v/2*x_i*x_j; [1,1] value -0.8 if it means v*x_i*x_j


def u2_unbounded_continuous() -> str:
    """min x1^2 - 2 x1  s.t. x1 + x2 = 3, both continuous without finite bounds. expected [1, 2], value -1."""
    m = Model(name="QPLIB_probe_unbounded")
    m.add_continuous(float("-inf"), float("inf"))
    m.add_continuous(float("-inf"), float("inf"))
    m.Q[(0, 0)] = 2.0
    m.add_linear(0, -2.0)
    m.add_constraint({0: 1, 1: 1}, lhs=3, rhs=3)
    return m.to_text()


def u3_manual_knapsack() -> str:
    """Knapsack of the manual. Optimum [1,1,1,0] value -41; the manual shows infeasible [1,1,1,1] -60."""
    m = Model(name="QPLIB_knapsack")
    for i, v in enumerate([11, 13, 17, 19]):
        m.add_binary()
        m.Q[(i, i)] = -2.0 * v
    m.add_constraint({0: 2, 1: 3, 2: 5, 3: 7}, lhs=0, rhs=10)
    return m.to_text()


U4_REORDERED = """QPLIB_probe_reordered
QBB
minimize
2 # number of variables
2 # number of non-default linear coefficients in objective
1 0.6
2 0.6
0 # default value for linear coefficients in objective
1 # number of quadratic terms in objective
2 1 -2
"""
# expected: same result as U1, or an error if the tag order matters

U5_ZERO_SECTION = """QPLIB_probe_zero_section
QBL
minimize
2 # number of variables
1 # number of constraints
-INF # default left-hand-side value
1 # default right-hand-side value
0 # default value for linear coefficients in objective
1 # number of quadratic terms in objective
2 1 -2
2 # number of non-default linear coefficients in objective
1 0.6
2 0.6
2 # number of linear terms in all constraints
1 1 1
1 2 1
0 # number of non-default left-hand-sides
0 # number of non-default right-hand-sides
""".replace("-INF", "-" + INF_TEXT)
# expected: accepted, result [0,0] (as U1); or an error if 0-count sections are rejected


def u6_equality_tolerance() -> str:
    """min x1^2 - 0.6 x1 + x2  s.t. x1 + x2 = 1, x1, x2 continuous in [0, 1].

    With x2 = 1 - x1 the objective is x1^2 - 1.6 x1 + 1, so the optimum is x1 = 0.8, x2 = 0.2,
    value 0.36. Check |x1 + x2 - 1| in the returned result.
    """
    m = Model(name="QPLIB_probe_eq_tol")
    m.add_continuous(0, 1)
    m.add_continuous(0, 1)
    m.add_quadratic(0, 0, 1.0)  # x1^2
    m.add_linear(0, -0.6)
    m.add_linear(1, 1.0)
    m.add_constraint({0: 1, 1: 1}, lhs=1, rhs=1)
    return m.to_text()


U7_MAXIMIZE = U1.replace("minimize", "maximize").replace("QPLIB_probe_offdiag", "QPLIB_probe_max")
# expected: v/2 convention -> max at [1,0] or [0,1] with 0.6 (and [1,1] 0.2); check the sign of "value"

U8_DUPLICATE = U1.replace("1 # number of quadratic terms in objective\n2 1 -2",
                          "2 # number of quadratic terms in objective\n2 1 -1\n2 1 -1")
# expected: same as U1 if duplicates are summed; otherwise an error or different result

U9_INF_LITERAL = U5_ZERO_SECTION.replace("-" + INF_TEXT, "-inf").replace(
    "0 # number of non-default left-hand-sides\n0 # number of non-default right-hand-sides\n", "")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    files = {
        "U1_offdiag.qplib": U1,
        "U2_unbounded_continuous.qplib": u2_unbounded_continuous(),
        "U3_manual_knapsack.qplib": u3_manual_knapsack(),
        "U4_reordered_tags.qplib": U4_REORDERED,
        "U5_zero_count_sections.qplib": U5_ZERO_SECTION,
        "U6_equality_tolerance.qplib": u6_equality_tolerance(),
        "U7_maximize.qplib": U7_MAXIMIZE,
        "U8_duplicate_entries.qplib": U8_DUPLICATE,
        "U9_inf_literal.qplib": U9_INF_LITERAL,
    }
    for name, text in files.items():
        (OUT / name).write_text(text)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
