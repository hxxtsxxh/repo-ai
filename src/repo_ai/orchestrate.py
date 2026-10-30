"""`repo-ai orchestrate plan "<task>"`: zero, one, or a few specialists.

Most tasks need no subagent. This recommends delegation only when the
packet shows a reason to:

- context isolation for a wide search;
- an independent impact or security pass;
- a separate verifier.

Each recommendation has its trigger and an *estimated* cost. The plan is a
typed DAG: subagents are read-only and run in parallel, and the main session
is the only writer and the merge point. That keeps edits out of conflict
without worktrees. If a step has to write, it is assigned to the main
session, or to an explicit worktree under one merge owner.

Off by default (`orchestration = "off"`): nothing calls this automatically,
and the command is advice only. It never spawns agents. Claude decides, under
the user's permissions. Subagents cannot widen their parent's permissions:
their tool lists are fixed in `.claude/agents/*.md`, and Bash, where
present, is limited to read-only commands by their instructions. A user's
deny rules still apply.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_FANOUT = 3
# Rough, labelled estimates (tokens) of what one delegated pass costs.
AGENT_COST_EST = {"repo-explorer": 6000, "repo-impact-analyst": 5000, "repo-verifier": 4000,
                  "repo-security-reviewer": 5000, "repo-skeptic": 6000}
SECURITY_INTENTS = {"auth", "security", "payments", "secrets", "crypto"}
TRIVIAL_RE = re.compile(r"\b(typo|spelling|wording|copy ?edit|comment|docstring|log message|"
                        r"error message text|rename (a )?(local )?variable|whitespace|formatting)\b",
                        re.I)
RISK_WORDS = ("migration", "migrate", "schema", "auth", "token", "password", "payment",
              "permission", "delete", "drop", "encrypt", "secret")


@dataclass(slots=True)
class Node:
    id: str
    agent: str          # a subagent name, or "main" (the session itself)
    purpose: str
    trigger: str
    mode: str           # read-only | write
    depends_on: list[str] = field(default_factory=list)
    outputs: str = ""
    cost_tokens_est: int = 0


@dataclass(slots=True)
class Plan:
    task: str
    complexity: str     # trivial | moderate | broad | risky
    signals: dict[str, Any]
    nodes: list[Node]
    merge_owner: str = "main"
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"task": self.task, "complexity": self.complexity, "signals": self.signals,
                "nodes": [asdict(n) for n in self.nodes], "merge_owner": self.merge_owner,
                "notes": self.notes,
                "delegated_cost_tokens_est": sum(n.cost_tokens_est for n in self.nodes
                                                 if n.agent != "main")}


def plan(packet, skeptic_enabled: bool = False, agents_enabled: bool = True) -> Plan:
    blast = packet.blast or {}
    components = blast.get("components") or []
    importers = int(blast.get("transitive_importers") or 0)
    routes = blast.get("routes") or []
    task_lower = packet.task.lower()
    risky = bool(set(packet.intents) & SECURITY_INTENTS) or any(w in task_lower for w in RISK_WORDS)
    trivial = bool(TRIVIAL_RE.search(packet.task)) and not risky
    api_work = "api" in packet.intents
    signals = {"confidence": packet.confidence, "locations": len(packet.locations),
               "components": len(components), "transitive_importers": importers,
               "routes": len(routes), "linked_tests": len(packet.tests), "risky": risky,
               "uncertain": len(packet.uncertainty), "trivial": trivial}
    nodes: list[Node] = []
    if packet.confidence in {"low", "none"} and not trivial:
        nodes.append(Node("explore", "repo-explorer", "find where the change belongs",
                          f"retrieval confidence is {packet.confidence}", "read-only",
                          outputs="file:line shortlist with reasons",
                          cost_tokens_est=AGENT_COST_EST["repo-explorer"]))
    wide = importers >= 8 or len(components) >= 2 or (api_work and len(routes) >= 3)
    if wide and not trivial:
        nodes.append(Node("impact", "repo-impact-analyst", "independent blast-radius pass",
                          f"{importers} transitive importers, {len(components)} components, "
                          f"{len(routes)} routes", "read-only",
                          outputs="affected code, tests to run, risks",
                          cost_tokens_est=AGENT_COST_EST["repo-impact-analyst"]))
    if risky:
        nodes.append(Node("security", "repo-security-reviewer", "review the change for "
                          "security issues", "task touches auth, payments, data deletion or "
                          "schema", "read-only", depends_on=["implement"],
                          outputs="findings with file:line",
                          cost_tokens_est=AGENT_COST_EST["repo-security-reviewer"]))
        if skeptic_enabled:
            nodes.append(Node("skeptic", "repo-skeptic", "attack the implementation's "
                              "assumptions", "risky change and skeptic_reviewer = true",
                              "read-only", depends_on=["implement"],
                              outputs="untested failure modes with file:line",
                              cost_tokens_est=AGENT_COST_EST["repo-skeptic"]))
    delegated = [n for n in nodes if n.agent != "main"]
    notes = []
    if len(delegated) > MAX_FANOUT:
        notes.append(f"fan-out capped at {MAX_FANOUT}; dropped "
                     + ", ".join(n.agent for n in delegated[MAX_FANOUT:]))
        keep = {id(n) for n in delegated[:MAX_FANOUT]}
        nodes = [n for n in nodes if n.agent == "main" or id(n) in keep]
    before = [n.id for n in nodes if not n.depends_on]
    nodes.append(Node("implement", "main", "make the change (the only writer)", "always",
                      "write", depends_on=before, outputs="the diff"))
    verify_trigger = "linked tests exist" if packet.tests else "no linked test found"
    if packet.tests and (importers >= 8 or risky):
        nodes.append(Node("verify", "repo-verifier", "run focused tests and report failures",
                          f"{verify_trigger}; wide or risky change", "read-only",
                          depends_on=["implement"], outputs="pass/fail with evidence",
                          cost_tokens_est=AGENT_COST_EST["repo-verifier"]))
    else:
        nodes.append(Node("verify", "main", "run the focused tests, then the full suite, yourself",
                          verify_trigger, "read-only", depends_on=["implement"],
                          outputs=", ".join(packet.commands[:1]) or "the test suite"))
    if not agents_enabled:
        # subagents are not installed (feature_set = "core"): same steps, main session
        for n in nodes:
            if n.agent != "main":
                n.agent, n.cost_tokens_est = "main", 0
        notes.append("subagents are off (feature_set = \"core\"): the main session does every "
                     "step; set feature_set = \"full\" to delegate read-only reviews")
    delegated = [n for n in nodes if n.agent != "main"]
    complexity = ("risky" if risky else "broad" if any(n.id == "impact" for n in nodes)
                  else "moderate" if delegated else "trivial")
    if not delegated:
        notes.append("no subagent recommended: the task is local enough for the main session")
    notes.append("subagents here are read-only; the main session is the only writer and merges "
                 "their summaries. Nothing is spawned by repo-ai.")
    return Plan(packet.task, complexity, signals, nodes, notes=notes)


def render(p: Plan) -> str:
    data = p.to_json()
    lines = [f"orchestration plan ({p.complexity}) — advice only; repo-ai spawns nothing",
             "  signals: " + ", ".join(f"{k}={v}" for k, v in p.signals.items())]
    for n in p.nodes:
        dep = f" after {', '.join(n.depends_on)}" if n.depends_on else ""
        cost = f" (~{n.cost_tokens_est} tokens, estimate)" if n.cost_tokens_est else ""
        lines.append(f"  {n.id:9s} {n.agent:24s} [{n.mode}]{dep} — {n.purpose}{cost}")
        lines.append(f"            because: {n.trigger}")
    lines.append(f"  merge owner: {p.merge_owner}; delegated cost ~{data['delegated_cost_tokens_est']}"
                 " tokens (estimate)")
    lines += [f"  note: {n}" for n in p.notes]
    return "\n".join(lines)
