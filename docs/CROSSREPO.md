# Cross-repository intelligence (opt-in, zoned)

Nothing in this document happens unless you register a repository. repo-ai
never discovers repositories by itself: it does not scan home directories,
cloud drives or company folders, and two repositories on the same machine
share nothing by default.

```sh
repo-ai registry add --zone personal          # in each repository you choose
repo-ai registry add --zone work --label billing
repo-ai registry list | inspect | remove | audit
repo-ai registry purge --zone work            # delete a zone and its patterns
repo-ai registry policy --zone personal --set llm=deny
repo-ai crossrepo context "where is the invoice total computed"
repo-ai crossrepo impact                      # who in this zone consumes my routes / package
repo-ai registry contribute                   # add this repo's sanitized pattern to its zone
repo-ai registry suggest                      # patterns from the same zone with a matching stack
```

## Zones

The registry lives in `$REPO_AI_HOME`, falling back to
`$XDG_DATA_HOME/repo-ai`, then `~/.local/share/repo-ai`, so it is outside
every repository.
- **One zone per repository:** moving one requires `--move`, and the audit
  flags a repository listed in two zones.
- **No reads across zones:** every `crossrepo` command reads only the
  current repository's zone.
- **Read-only access:** other repositories' indexes are opened read-only
  (`mode=ro`) and never written.

| Zone | Model drafting | Patterns |
|---|---|---|
| `personal` | allowed after opt-in | on |
| `work` | **denied** | on (stays in `work`) |
| any other name | **denied** | on |
| unregistered | **denied** | — |

## What crosses repositories

**`crossrepo context`** returns file paths and reasons from other
repositories in the same zone, and only when retrieval confidence there is
medium or high.

**`crossrepo impact`** reports:
- `consumes_api`: an API-path literal in another repository matches one of
  this repository's routes (heuristic, confidence 0.6, with `path:line`);
- `depends_on_package`: another repository's manifest declares this
  repository's package (proven by the manifest).

**Patterns** (`registry contribute`) are sanitized to:
- languages, frameworks and test frameworks;
- rule kinds and topics;
- generated-skill kinds;
- aggregate session-status counts;
- pinned **public** GitHub third-party skills from the portfolio
  (owner/repo, commit, content hash, stage, measured benefit). Skills
  vetted from a local path are never included;
- a hashed contributor id, under which the per-repository pattern is kept
  so Stack Packs can count support.

They never contain paths, repository names, URLs, command text, prompts or
source. `registry audit` fails on any path- or URL-like value, on unexpected
fields, and on a repository listed in two zones.

**Stack Packs** (`repo-ai pack list | show | plan`) are built from these
patterns. They use only the repository's own zone, need two or more
contributing repositories of the same stack, and change nothing when
planned (see docs/OPTIMIZATION.md).

These isolation properties are covered by `tests/test_skills_registry.py`
and `tests/test_stackpacks.py`, which try to break them.
