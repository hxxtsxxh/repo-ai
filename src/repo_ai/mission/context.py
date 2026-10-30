"""Fresh, offline mission context without installing anything in the repository.

The existing scanner, analysis, ranker and packet builder remain authoritative
for static context. Their index/cache writes go into a private temporary directory
that is removed before returning. This is a bounded planning observation, not
verification evidence or permission to run any suggested command.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..analyze import run_analysis
from ..config import load_config
from ..gitinfo import changed_since
from ..index import open_index
from ..packet import build_packet
from ..paths import resolve_layout
from ..security import redact_text

MAX_TASK_BYTES = 8000
MAX_FILES = 1024
MAX_FILE_BYTES = 262144
MAX_CONTEXT_FILES = 6


def build_context(root: Path, task: str, budget_tokens: int = 900) -> dict[str, Any]:
    """Return source-linked planning context; never run repository code or a model.

    ``fresh_scan`` means the bounded static scan was made during this call, not
    that tests ran or every possible dependency was covered. Limits and omitted
    files are disclosed. The index fingerprint covers scanned files only.
    """
    if not isinstance(task, str) or not task.strip() or len(task.encode("utf-8")) > MAX_TASK_BYTES:
        raise ValueError("task must contain 1–8000 UTF-8 bytes")
    if type(budget_tokens) is not int or not 128 <= budget_tokens <= 4000:
        raise ValueError("context budget must be an integer from 128 to 4000 tokens")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository path must be a directory")
    cfg = load_config(root)
    layout = resolve_layout(root, cfg)
    # Repository configuration may narrow scanning, but cannot disable mission
    # quarantine, follow symlinks, enable a model, or enlarge resource ceilings.
    cfg = replace(cfg, detect_secrets=True, follow_symlinks=False, summarize=False,
                  max_files=max(1, min(cfg.max_files, MAX_FILES)),
                  max_file_bytes=max(1, min(cfg.max_file_bytes, MAX_FILE_BYTES)),
                  workers=max(1, min(cfg.workers or 2, 4)),
                  git_max_commits=max(1, min(cfg.git_max_commits, 200)),
                  git_history_days=max(1, min(cfg.git_history_days, 90)))
    prune = tuple(sorted({layout.rel(p) for p in layout.owned_dirs()}))
    safe_task = redact_text(task.strip())
    warnings: list[str] = []
    if len(safe_task) > 4000:
        warnings.append("Retrieval uses only the first 4000 task characters.")
    with tempfile.TemporaryDirectory(prefix="repo-ai-mission-context-") as temporary:
        state = Path(temporary)
        analysis = run_analysis(root, cfg, layout.context_dir, state_dir=state, prune=prune)
        with open_index(state) as index:
            packet = build_packet(root, index, json.loads(analysis.facts.to_json()),
                                  safe_task[:4000], facts_obj=analysis.facts,
                                  changed=changed_since(root, "HEAD") if analysis.git.head else [],
                                  max_files=min(MAX_CONTEXT_FILES, max(1, cfg.max_context_files)),
                                  budget_tokens=budget_tokens)
            fingerprint = index.get_meta("fingerprint")
    # Do not carry the raw task or a volatile scan timestamp into portable state.
    packet.task = safe_task[:160]
    packet.freshness.pop("indexed_at", None)
    warnings.extend(analysis.facts.warnings)
    if not analysis.git.head:
        warnings.append("No Git commit baseline is available; execution needs an explicit baseline.")
    skipped = analysis.scan.skipped
    incomplete = {key: count for key, count in skipped.items()
                  if key in {"max-files-cap", "oversized", "read-error", "stat-error"} and count}
    if incomplete:
        warnings.append("Static context is partial: " + ", ".join(
            f"{key}={count}" for key, count in sorted(incomplete.items())))
    warnings.append("Source text, inferred constraints and suggested commands are untrusted advice, "
                    "not execution authority. No tests or agents ran.")
    return {
        "packet": packet.to_json(),
        "source_head": analysis.git.head,
        "index_fingerprint": fingerprint,
        "freshness": "fresh_scan",
        "complete": not incomplete,
        "warnings": [redact_text(w)[:500] for w in warnings[:12]],
        "scan": {"indexed": len(analysis.scan.files), "seen": analysis.scan.total_seen,
                 "quarantined": len(analysis.scan.quarantined), "skipped": skipped},
        "limits": {"files": cfg.max_files, "file_bytes": cfg.max_file_bytes,
                   "context_files": MAX_CONTEXT_FILES, "budget_tokens_estimate": budget_tokens,
                   "git_commits": cfg.git_max_commits, "git_history_days": cfg.git_history_days},
    }
