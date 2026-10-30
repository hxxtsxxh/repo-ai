# handoff-demo-2

Constructed scenario (labelled as such): the request names only `wrap_words` (textutil.py); the frozen visible tests
also fail for `render_table` (table.py). Direction under test: Codex (A) -> agy (B).

PROMPT: "wrap_words(text, width) in textutil.py must greedily wrap text into lines of at most `width` characters,
placing a word longer than `width` alone on its own line unbroken, collapsing whitespace runs to one space, and
returning [] for blank input. The tests in test_textutil.py describe it."
