"""Optional narrative summaries via `bob run`.

Everything else in repo-ai is deterministic and fully local. This module is
the one place a model is involved, and it is opt-in (`--summarize`).

It deliberately shells out to `bob run` rather than calling a model API:

  * no second API key to manage
  * no new egress path — the data goes exactly where Bob already sends it,
    under the same account, policies, and Bobalytics accounting
  * `--max-cost` and `--max-turns` bound the spend
  * if Bob is not installed, repo-ai degrades to deterministic output instead
    of failing

The prompt is built from `facts.json`, never from raw source. That keeps the
payload small and means no file contents leave the machine for this step.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .logging_setup import get_logger
from .models import RepoFacts

log = get_logger()


def bob_available(binary: str = "bob") -> bool:
    from shutil import which
    return which(binary) is not None


def _facts_digest(facts: RepoFacts, max_chars: int = 12_000) -> str:
    """A compact, source-free description of the repository."""
    payload = {
        "name": facts.name,
        "languages": dict(list(facts.languages.items())[:8]),
        "total_loc": facts.total_loc,
        "frameworks": facts.frameworks[:20],
        "package_managers": facts.package_managers,
        "external_services": facts.external_services,
        "components": [
            {"name": c.name, "root": c.root, "kind": c.kind,
             "languages": c.languages[:3], "loc": c.loc,
             "entrypoints": c.entrypoints[:2]}
            for c in facts.components[:12]
        ],
        "entrypoints": facts.entrypoints[:15],
        "routes_sample": [
            {"method": r.method, "path": r.path_pattern, "file": r.file}
            for r in facts.routes[:30]
        ],
        "route_count": len(facts.routes),
        "test_suites": [
            {"root": s.root, "framework": s.framework, "kind": s.kind,
             "files": s.file_count}
            for s in facts.test_suites[:10]
        ],
        "commands": facts.commands,
        "important_files": [
            {"path": i["path"], "why": i["why"]} for i in facts.important_files[:25]
        ],
        "doc_titles": [
            {"path": d["path"], "title": d.get("title", ""),
             "headings": d.get("headings", "")[:300]}
            for d in facts.docs[:12]
        ],
        "conventions": {
            k: v for k, v in facts.conventions.items()
            if k in {"function_naming", "type_naming", "file_naming",
                     "indentation", "tooling", "layers"}
        },
        "hotspots": [h.path for h in facts.hotspots[:15]],
    }
    return json.dumps(payload, indent=1)[:max_chars]


PROMPT_TEMPLATE = """You are writing an onboarding brief for another AI coding \
agent that is about to work in this repository. Below is a structured analysis \
of the repository. No source code is included.

Write 350-500 words of plain prose (no headings, no bullet lists) covering:
1. What this system most likely does and who uses it.
2. How the components relate at runtime — what calls what.
3. The two or three places a newcomer is most likely to get something wrong.
4. Where to start reading for a typical change.

Be concrete and reference real paths from the analysis. Where the analysis is \
ambiguous, say so explicitly rather than guessing. Do not invent features, \
endpoints, or file names that do not appear below.

ANALYSIS:
{digest}
"""


def summarize(
    facts: RepoFacts,
    root: Path,
    binary: str = "bob",
    max_cost: str = "0.50",
    timeout: int = 300,
) -> str:
    """Return narrative prose, or '' if Bob is unavailable or the call fails."""
    if not bob_available(binary):
        log.warning("`%s` not found on PATH; skipping narrative summary", binary)
        return ""

    prompt = PROMPT_TEMPLATE.format(digest=_facts_digest(facts))
    cmd = [
        binary, "run", "--format", "json", "--mode", "ask",
        "--max-cost", str(max_cost), "--max-turns", "3",
        "--disable-mcp", "--disable-subagents",
        "--workspace", str(root),
    ]
    log.info("requesting narrative summary via `%s run` (max cost %s)", binary, max_cost)
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout, check=False, cwd=root,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("bob run failed: %s", exc)
        return ""

    if proc.returncode != 0:
        log.warning("bob run exited %d: %s", proc.returncode, proc.stderr.strip()[:300])
        return ""

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        text = proc.stdout.strip()
        return text if len(text) > 200 else ""

    if data.get("status") != "success":
        log.warning("bob run reported status=%s", data.get("status"))
        return ""

    message = (data.get("last_message") or "").strip()
    stats = data.get("stats") or {}
    if stats:
        log.info("summary generated: %s tokens, %.2f cost",
                 stats.get("total_tokens", "?"), float(stats.get("session_costs", 0) or 0))
    return message


def render_summary_section(text: str) -> str:
    if not text:
        return ""
    return "\n".join([
        "## Narrative summary",
        "",
        "_Generated by `bob run` from the structured analysis. Treat as an "
        "informed reading, not verified fact._",
        "",
        text.strip(),
        "",
    ])
