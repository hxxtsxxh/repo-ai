# c10-confirm-v2: author briefs

Three briefs, for three **separate, fresh** model sessions, dispatched in order: A, then B, then C. The designer of
the protocol wrote these briefs and no material. Each author receives **only its own brief** (one section below,
copied verbatim) plus the "Materials" section of `PREREGISTRATION.md`, nothing else.

## For the coordinator (not for the authors)

Staging, so that each author can only see its inputs (paths have no component starting with `-`):

| step | new directory | put in it before starting the session | take out of it afterwards | commit as |
|---|---|---|---|---|
| A | `~/c10v2-authoring/A/` | `BRIEF.md` (section "Brief A" below), `MATERIALS-SECTION.md` (the prereg's Materials section) | `fixture/`, `skill/`, `A_NOTES.md` | `c10-confirm-v2 materials: Author A (fixture, skill, notes)` |
| B | `~/c10v2-authoring/B/` | `BRIEF.md` (section "Brief B"), `MATERIALS-SECTION.md`, a copy of `fixture/`, a copy of `SKILL.md` only (not the LICENSE, not `A_NOTES.md`) | `tasks.json`, `oracle/` | `c10-confirm-v2 materials: Author B (tasks, oracles)` |
| C | `~/c10v2-authoring/C/` | `BRIEF.md` (section "Brief C"), `MATERIALS-SECTION.md`, copies of `fixture/`, `SKILL.md`, `tasks.json`, `oracle/` | `REVIEW.md` | `c10-confirm-v2 materials: Reviewer C (review)` |

- Start each session in its directory with no earlier conversation, and give it this first message: "Read
  `BRIEF.md` and `MATERIALS-SECTION.md` in this directory and do what the brief says. Work only in this
  directory." Record each session's model and date for `MATERIALS.md`.
- Copy outputs into `benchmarks/c10-confirm-v2/` unchanged. Delete `__pycache__/` and `.pytest_cache/` before
  copying. Then the freeze (prereg Materials, step 4): remove every DELETE and LEAK assertion from its oracle file
  and from `tasks.json`, drop a task left with no convention assertion, run `python run.py check --strict`, and send
  any failure back to the responsible session (A: fixture or skill; B: tasks or oracles; C re-reviews whatever B
  changes). Do not fix materials yourself.
- Repo-local git identity only; stage by path.

---

## Brief A: fixture project and conventions skill

You are Author A of a preregistered experiment. Your job: write a small, realistic Python **command-line
application** and a "conventions" document for it, as an experienced maintainer of that project would. Another
person, who never talks to you, will later write coding tasks against your project and check whether changes follow
your conventions. You will never see those tasks.

**Read only** `BRIEF.md` and `MATERIALS-SECTION.md` in your working directory. Do not read anything else on this
machine (no other repository, no `benchmarks/` directory, no earlier experiment, no repo-ai source), and do not use
the network. Write only inside your working directory.

**Write exactly these outputs:**

1. `fixture/`: the project.
   - One package (choose its name), standard library only, Python 3.11 or later (`pyproject.toml` with
     `requires-python = ">=3.11"`, no dependencies, and `[tool.pytest.ini_options]` with `pythonpath = ["."]` and
     `testpaths = ["tests"]`).
   - `<package>/cli.py` exposes `def main(argv=None) -> int` built on `argparse` with **at least 3 subcommands**;
     `<package>/__main__.py` calls it (`raise SystemExit(main())`). `main` returns the exit code; it does not call
     `sys.exit` itself.
   - The application reads input files (for example CSV, JSON Lines or plain text) and writes reports or output
     files, uses stdout and stderr, and may read an environment variable or a small config file. Choose a domain
     that has nothing to do with inventory, stock, money, accounting or prices (for example: a log-file summarizer,
     a contact-list cleaner, a playlist or bookmark organizer, a backup-rotation planner, a static-site manifest
     builder; or your own idea).
   - 7–12 modules in total, with a separation between the CLI layer and functions that do the work, so that a new
     feature can be added either as a subcommand or flag, or as a function.
   - `tests/` with **at least 20 tests that pass** with `cd fixture && python3 -m pytest -q`. Tests run in-process
     (`main([...])` with `capsys`, `tmp_path`, `monkeypatch`), deterministic, no network, writing only under
     `tmp_path`.
   - The code consistently follows the conventions that you mark as inferable (below) and contains **no hint** of
     the non-inferable ones: no comment, docstring, name, test or dead code that reveals them. Realistic, tidy,
     ordinary code.
2. `skill/<package>-conventions/SKILL.md`, beginning with exactly this frontmatter (fill in the name):

       ---
       name: <package>-conventions
       description: Holds the coding conventions of the <package> project; use it whenever changing or adding code to the <package> package.
       ---

   then a short heading and introduction, then **10–14 numbered conventions** (`1.`, `2.`, ... at the start of a
   line, one rule per number). Requirements for each rule:
   - It tells a contributor what to do when adding or changing code, precisely enough that **exactly one behaviour
     is correct**: name exact exit codes, message texts and formats, orderings, file and encoding behaviour,
     precedence orders, types, and so on. A rule that leaves a choice open is not usable.
   - Its effect can be observed from outside by an automated test (a return value, an exit code, stdout or stderr
     text, a file's bytes, an exception type and message, a log record).
   - At least 8 rules are **not inferable** from your code: the code has no case where the rule shows, so a
     newcomer reading the code could not guess it. The other rules are visible in the code (consistently
     followed).
   - At most 2 rules may be on these topics (they were used in an earlier experiment): integer-cent money, SKU or
     product-code formats, rounding of money or percentages, half-open time periods, generated sequential
     identifiers, all-or-nothing multi-line operations, returning tuples rather than lists, warning logs for stock
     removals.
   - Good areas for a command-line application (pick your own; these are only examples): which exit code means
     what; what goes to stdout and what to stderr, and the format of error messages; text encodings and newlines of
     files written; how output files are written (for example atomically, or refusing to overwrite without a flag);
     ordering and formatting of report output; machine-readable output shapes; precedence between flags,
     environment variables and config; naming of new flags; what a dry-run mode must do; handling of empty input;
     how timestamps or sizes are shown.
   - The body (everything after the frontmatter) must read correctly on its own as a project's `CLAUDE.md`, so do
     not write "this skill" or refer to the frontmatter. You may give a short example in a rule; keep examples few
     and specific.
3. `skill/<package>-conventions/LICENSE`: the MIT license text, copyright "2026 <package> contributors".
4. `A_NOTES.md`: the project's name and domain in one line; a table `| Rule | Inferable from code? | Why |` with
   one row per rule, saying for a "yes" where the code shows it and for a "no" why the code cannot reveal it;
   totals; and the command and output of the visible test run.

**Done when:** the visible tests pass, the rule count is 10–14 with at least 8 marked "no", and you have checked
every "no" rule against your code once more for hints. Reply with the list of files you wrote and the test output.
Do not write tasks, tests of the conventions, or any example change to the project beyond what the project itself
needs.

---

## Brief B: tasks and hidden oracles

You are Author B of a preregistered experiment. You get a small Python command-line project (`fixture/`) and its
conventions document (`SKILL.md`). Your job: write **8 realistic coding tasks** for this project, and for each a
**hidden test file (oracle)** that checks whether a change made for the task follows the conventions. The tasks will
be given to an AI coding assistant, sometimes with the conventions available and sometimes without; you do not need
to know more about that.

**Read only** `BRIEF.md`, `MATERIALS-SECTION.md`, `fixture/` and `SKILL.md` in your working directory. Do not read
anything else on this machine (no other repository, no `benchmarks/` directory, no earlier experiment, no repo-ai
source), and do not use the network. Write only inside your working directory.

**Write exactly these outputs:**

1. `tasks.json`, in this schema (ids `t1`..`t8`):

       {"tasks": [
         {"id": "t1",
          "request": "<one paragraph, as a maintainer would write it>",
          "assertions": [
            {"test": "test_t1_baseline_<slug>", "kind": "baseline", "rule": null,
             "why": "requested behaviour on an input no convention decides"},
            {"test": "test_t1_convention_<slug>", "kind": "convention", "rule": <rule number>,
             "why": "rule <n>: <what it requires here and the expected value>"}
          ]}
       ]}

2. `oracle/test_t1.py` ... `oracle/test_t8.py`: one pytest file per task whose test functions are **exactly** the
   assertions listed for that task in `tasks.json` (same names, nothing else named `test_*`).

**Requirements for the requests:**
- Each is one paragraph asking for a feature or change a real maintainer might want: a new subcommand, a new flag on
  an existing subcommand, a new function, or a change to existing behaviour. Name the exact public names the oracle
  will call (module, function, subcommand, flag) and the inputs and outputs that are not decided by a convention.
- **Never** mention conventions, rules, `SKILL.md`, skills, `CLAUDE.md`, or "the project's style". **Never reveal a
  detail that a convention assertion checks** (an exit code, a message text, an ordering, a format, a type, an
  encoding, a precedence, ...) unless the request genuinely has to supply it, and then do not write a convention
  assertion on that detail.
- At least 2 tasks are exercised through `main([...])` and at least 2 through package functions. Each request asks
  the assistant to add or update tests where that is natural.

**Requirements for the oracles:**
- Each task has **exactly one baseline assertion**: it checks the requested behaviour on an input where no
  convention decides the expected value, so any reasonable correct implementation passes it whether or not it
  follows the conventions (be lenient on anything a convention governs: e.g. compare parsed values, not exact
  formatting, when formatting is a convention).
- Each task has **1–4 convention assertions** (18–28 in total over the 8 tasks), each its own test function, each
  checking **one** rule, citing it in `tasks.json` (`rule`) and in a comment in the test (`# rule <n>`). The
  expected value must follow from that rule's text alone, with exactly one correct answer; if a rule could be read
  two ways for this case, do not test that case.
- Spread the convention assertions over as many rules as the tasks naturally allow; do not test the same rule in
  every task.
- **Do not reuse the example values that appear in `SKILL.md`** as inputs or expected values; use your own.
- Oracles import only the project package, the standard library and `pytest`; run in-process; are deterministic
  (no wall-clock time, no randomness, no dependence on test order); use no network; write only under `tmp_path`.
  A missing function or subcommand should make a test fail, not crash collection of the other tests in the file
  (import inside the test functions, or guard imports).
- Verify both directions: (a) on an untouched copy of `fixture/`, **every** oracle test fails; (b) write your own
  reference implementation of all 8 tasks in a separate scratch copy, following every convention, and check that
  **every** oracle test passes against it (copy the oracle file into the project root and run pytest there). Then
  **delete the scratch copy**; it must not be among your outputs.

**Done when:** both checks hold. Reply with the files you wrote, the number of assertions (baseline and convention),
which rules are exercised and how often, and the output of both checks. Do not edit `fixture/` or `SKILL.md`.

---

## Brief C: review of the oracle assertions

You are Reviewer C of a preregistered experiment. Another author wrote 8 coding tasks (`tasks.json`) for a small
Python project (`fixture/`) and, per task, hidden tests (`oracle/test_<id>.py`) that check whether a change follows
the project's conventions (`SKILL.md`). Each test function is one "assertion": `baseline` (the requested behaviour,
no convention involved) or `convention` (one numbered rule of `SKILL.md`, cited in `tasks.json`). Your job is to find
assertions that would score a correct change unfairly.

**Read only** `BRIEF.md`, `MATERIALS-SECTION.md`, `fixture/`, `SKILL.md`, `tasks.json` and `oracle/` in your
working directory. Do not read anything else on this machine and do not use the network. You may run the oracles
against the fixture or a scratch copy; delete any scratch copy. Write only `REVIEW.md`. Do not edit any other file.

For **every** test function, decide:

- **DELETE** a convention assertion if its expected value does not follow **unambiguously from the cited rule's text
  alone** (a second reasonable reading of the rule, or of the request, gives a different answer; or it checks
  something the rule does not say; or it also depends on a choice the request leaves open).
- **DELETE** a baseline assertion if a reasonable correct implementation could fail it because of a convention or
  of a choice the request leaves open.
- **KEEP** otherwise.

Separately, mark **LEAK** for every assertion whose task request reveals a detail that the assertion checks, when
the request did not have to supply it (for example, the request states the exit code or message format the
assertion then checks). A detail the request must supply (a name, an input, a requested output) is not a leak.

**Write `REVIEW.md` in exactly this format** (it is parsed by a script):

    # Reviewer C: assertion review

    test_t1_baseline_<slug> | KEEP | <one sentence: why>
    test_t1_convention_<slug> | DELETE | <one sentence: the second reading, or what the rule does not say>
    ... one line per test function, in task order ...

    ## Leaks

    LEAK | test_t3_convention_<slug> | <what the request reveals>
    (or the single line "none")

    ## Counts

    - Test functions reviewed: <n>
    - KEEP: <n> (baseline <n>, convention <n>)
    - DELETE: <n> (baseline <n>, convention <n>)
    - LEAK: <n>

Judge from the texts, not from whether you can make the test pass. When in doubt about ambiguity, DELETE: a deleted
assertion costs a little power, an ambiguous one makes the result wrong. Reply with the counts.
