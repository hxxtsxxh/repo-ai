# capability-fresh-v1: results (gates failed)

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md) (c3330b7) and the author inputs (8f554a1), committed before the
corpus; corpus (60 tasks, an independent author who reports reading only the protocol, the catalog without need weights
and the stack profiles: [AUTHOR-REPORT.md](AUTHOR-REPORT.md)) committed at e5ed9c5; scored once on 2026-11-01 with the matcher on `main` unchanged. Raw:
[results.json](results.json). $0, offline.

| id | measure | result | gate | verdict |
|---|---|---|---|---|
| R1 | top-3 recall over the 40 tasks that need a capability | **0.69** | ≥ 0.80 | **fail** |
| R2 | recommended items a stated constraint rules out | **2** | 0 | **fail** |
| R3 | correct abstention on the 20 tasks that need none | 19 of 20 | — | reported |
| R4 | top-3 precision | 0.68 | — | reported |

**C07 stays EXPERIMENTAL.** The last fresh measurement (corpus C, 120 tasks: recall 0.385, 5 forbidden items) is not
directly comparable: corpus C had two labellers and a judge and environment-state fixtures; this one has one model
author, scoring passes no environment state, and R2 counts only the author's own `forbidden` lists. Neither gate is met.

- **R2:** both are constraints stated in prose that the matcher did not detect: t21 "We can't add a language server
  plugin on this machine" → `ext.lsp-references`; t60 "don't spin up the app or a browser or run any tools" →
  `ext.browser-evidence`. This is the documented limit (constraints are detected only partly from task text);
  `--deny`, which is always enforced, was not part of this protocol.
- **R1:** 11 of the 40 tasks that need a capability got no correct recommendation (t12, t13, t17, t21, t33, t35, t37,
  t40, t45, t53, t54).
- Labelling caveat: for network constraints the author forbade only `adapter.dependency-audit`, although the catalog
  says Semgrep downloads rules unless local rules are used and the browser capability sends usage statistics by
  default; Semgrep is forbidden in t34 but not in t16, t28 or t56. Semgrep was not recommended for any of those, so
  R2 is unaffected here, but the `forbidden` labels are not uniformly strict.
