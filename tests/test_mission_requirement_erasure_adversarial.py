"""Adversarial probes for claims.removed_requirement_text (PR #7). Tests asserting desired behaviour FAIL on review."""

import time
import pytest
from repo_ai.mission import claims

R = claims.removed_requirement_text


def _diff(*body, path="m.py", hunk="@@ -10,8 +10,6 @@"):
    return "\n".join([f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}", hunk, *body]) + "\n"


# ---------- robustness (should all pass: never raises, linear) ----------
@pytest.mark.parametrize(
    "d",
    [
        "",
        "\n",
        "@@",
        "+++ ",
        "+++",
        "--- ",
        "diff --git ",
        "+",
        "-",
        "\\ No newline at end of file",
        "+++ /dev/null\n-# must raise\n",
        "\x00\x01\xff",
        "+++ b/a.py\r\n@@ -1 +1 @@\r\n-# must raise\r\n+x\r\n",
        "+++ b/a.py\n- # must \x85\x0c\x0b",
        "+++ b/\udcff.py\n-# must\n",
        "Binary files a/x.py and b/x.py differ",
        "diff --git a/x b/y\nrename from x.py\nrename to y.py\ncopy from z.py\n",
        "GIT binary patch\nliteral 5\nzcmV\n",
    ],
)
def test_never_raises(d):
    R(d)
    claims.assess(
        "must return sorted", {"t.py": "sorted"}, verdict="PASS", freshness="fresh", exercise=None, diff=d
    )


def test_linear_on_huge_diff():
    body = ["-    # must raise if invalid " + "x" * 50] * 200_000 + ['     """'] * 100_000
    d = _diff(*body)
    t = time.perf_counter()
    R(d)
    dt = time.perf_counter() - t
    assert dt < 5, dt


def test_long_single_line():
    t = time.perf_counter()
    R(_diff("-# " + "if " * 2_000_000))
    assert time.perf_counter() - t < 5


# ---------- CONFIRMED false positives ----------
def test_FP_hunk_starting_inside_docstring_inverts_state_and_flags_code():
    # very common: the 3 context lines start inside a docstring; closing quotes toggle in_doc ON for the code below
    d = _diff(
        "     Returns the clamped value.",
        '     """',
        "-    if lo > hi:",
        '-        raise ValueError("bad")',
        "+    lo, hi = sorted((lo, hi))",
    )
    assert R(d) == [], R(d)  # code lines reported as "removed documentation"


def test_FP_docstring_reflow_is_flagged():
    _diff(
        '     """Clamp x. Raise ValueError if lo is greater',
        '-    than hi."""',
        '+    than hi, or if x is None."""',
    )
    # (this one is genuinely changed; the reflow case is below)
    reflow = _diff(
        " def f(x):",
        '-    """Raise ValueError if the input',
        '-    list is empty or unsorted."""',
        '+    """Raise ValueError if the input list is',
        '+    empty or unsorted."""',
    )
    assert R(reflow) == [], R(reflow)


def test_FP_quote_style_change_is_flagged():
    d = _diff(
        " def f(x):",
        "-    '''Raise ValueError if x is empty.'''",
        '+    """Raise ValueError if x is empty."""',
    )
    assert R(d) == [], R(d)


def test_FP_docstring_opening_line_split():
    d = _diff(
        " def f(x):",
        '-    """Raise ValueError if x is empty."""',
        '+    """',
        "+    Raise ValueError if x is empty.",
        '+    """',
    )
    assert R(d) == [], R(d)


def test_FP_comment_moved_into_docstring():
    d = _diff(" def f(x):", "-    # x must be positive", '+    """x must be positive."""')
    assert R(d) == [], R(d)


def test_FP_code_inside_non_doc_triple_quoted_string():
    d = _diff(
        ' SCRIPT = textwrap.dedent("""',
        "     for x in xs:",
        "-        if x:",
        "-            print(x)",
        "+        print(x)",
        '     """)',
    )
    assert R(d) == [], R(d)


def test_FP_code_line_containing_triple_quote_literal_toggles_state():
    d = _diff('     n = text.count(\'"""\')', "-    if n % 2:", "-        flip()", "+    flip_if(n)")
    assert R(d) == [], R(d)


def test_FP_black_style_operator_continuation_is_a_comment():
    d = _diff(
        "     total = (", "         base", "-        * (2 if valid else 1)", "+        * factor", "     )"
    )
    assert R(d) == [], R(d)


def test_FP_routine_todo_and_ordinary_if_comments():
    # "if"/"should"/"error" make almost every removed comment a "requirement"
    for c in (
        "# TODO: should refactor this later",
        "# handle errors from the old api",
        "# see if this is still needed",
        "# only used by the legacy importer",
    ):
        assert R(_diff(f"-    {c}", "+    pass")) == [], c


def test_FP_added_line_starting_with_plus_plus_space_hijacks_path():
    # JS content line "++ i;" becomes diff line "+++ i;" and is parsed as a file header
    d = _diff("+++ i;", "-  // must reject invalid input", path="a.js")
    assert R(d) and R(d)[0]["file"] == "a.js", R(d)


def test_FP_unicode_line_separator_in_content_creates_fake_diff_line():
    d = _diff('+    s = "x -    # must never be empty"')
    assert R(d) == [], R(d)  # an ADDED line is reported as a removed requirement


# ---------- false negatives (documented) ----------
@pytest.mark.xfail(strict=True, reason="documented blind spot: a docstring opened before the hunk's context")
def test_FN_docstring_opened_before_hunk():
    d = _diff("     Compute the total.", "-    Raise ValueError if empty.", '     """')
    assert R(d), "documented blind spot"


def test_FN_whole_file_deletion():
    d = "diff --git a/m.py b/m.py\ndeleted file mode 100644\n--- a/m.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-# must raise if x\n"
    assert R(d)


def test_FN_quoted_path_with_space_or_unicode():
    d = 'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n@@ -1 +1 @@\n-# must raise\n+x\n'
    assert R(d)


@pytest.mark.xfail(strict=True, reason="documented blind spot: JSDoc body lines without a leading *")
def test_FN_jsdoc_without_star_prefix():
    d = _diff(" /**", "-   Throws if the list is empty; must be sorted.", " */", path="a.ts")
    assert R(d)


# ---------- security / output ----------
def test_file_field_is_unbounded_and_uncleaned():
    path = "b/" + "\x1b[31m" + "a" * 5000 + ".py"
    d = f"diff --git a/x b/x\n--- a/x\n+++ {path}\n@@ -1 +1 @@\n-# must raise\n+x\n"
    f = R(d)[0]["file"]
    assert len(f) <= 200 and "\x1b" not in f, (len(f), f[:20])


def test_text_bidi_controls_survive_in_structured_field():
    t = R(_diff("-    # must ‮esrever‬ raise"))[0]["text"]
    assert "‮" not in t


def test_duplicates_not_collapsed():
    d = _diff(*["-    # must raise if empty"] * 8, "-    # never negative")
    texts = [x["text"] for x in R(d)]
    assert "never negative" in texts, texts


def test_backward_compat_keys():
    out = claims.assess(
        "must return sorted",
        {"t.py": "def test(): assert sorted"},
        verdict="PASS",
        freshness="fresh",
        exercise=None,
    )
    assert {"schema", "headline", "task_correct", "unechoed_qualifiers", "requirements", "notes"} <= set(out)
