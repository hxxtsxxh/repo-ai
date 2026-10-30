"""Bounded provider CLI contracts, JSONL event parsers, and sandboxed execution.

Distinguishes lifecycle stages:
  NOT_INSTALLED -> DISCOVERED -> PROBED -> READY / SIMULATED / BLOCKED / FAILED -> VERIFIED (or LIVE_VERIFIED)

A provider adapter run never certifies itself: even when the CLI exits 0 and emits
valid JSONL events, the stage remains SIMULATED (or READY) until independent
sandbox test observations and whole-change regression verification pass.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..security import redact_text, source_contains_secret
from . import claude_auth, opencode_cfg
from .discovery import MAX_OUTPUT, PROVIDERS, _capture, _identity, _inside, _probe_env, _repo_owned, _sandbox_prefix

STAGES = (
    "NOT_INSTALLED",
    "DISCOVERED",
    "PROBED",
    "READY",
    "SIMULATED",
    "BLOCKED",
    "FAILED",
    "VERIFIED",
)


@dataclass(frozen=True)
class ProviderContract:
    provider: str
    headless_argv: tuple[str, ...]
    event_format: str
    event_flag: str
    workspace_flag: str | None
    sandbox_flags: tuple[str, ...]
    cost_limit_flag: str | None
    turn_limit_flag: str | None
    enforces_hard_usd_budget: bool

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["headless_argv"] = list(self.headless_argv)
        data["sandbox_flags"] = list(self.sandbox_flags)
        return data


PROVIDER_CONTRACTS: dict[str, ProviderContract] = {
    "codex": ProviderContract(
        provider="codex",
        headless_argv=("exec", "--json", "--ephemeral", "--sandbox", "workspace-write"),
        event_format="codex-jsonl",
        event_flag="--json",
        workspace_flag="-C",
        sandbox_flags=("--sandbox", "workspace-write"),
        cost_limit_flag=None,
        turn_limit_flag=None,
        enforces_hard_usd_budget=False,
    ),
    "claude": ProviderContract(
        provider="claude",
        headless_argv=(
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--no-session-persistence",
            *claude_auth.invocation_flags(read_only=False),
        ),
        event_format="claude-stream-json",
        event_flag="--output-format",
        workspace_flag=None,
        sandbox_flags=tuple(claude_auth.invocation_flags(read_only=False)),
        cost_limit_flag="--max-budget-usd",
        turn_limit_flag=None,
        enforces_hard_usd_budget=True,
    ),
    "gemini": ProviderContract(
        provider="gemini",
        headless_argv=(
            "--prompt",
            "--output-format",
            "stream-json",
            "--approval-mode",
            "auto_edit",
            "--skip-trust",
        ),
        event_format="gemini-stream-json",
        event_flag="--output-format",
        workspace_flag=None,
        sandbox_flags=("--approval-mode", "auto_edit", "--skip-trust"),
        cost_limit_flag=None,
        turn_limit_flag=None,
        enforces_hard_usd_budget=False,
    ),
    # Antigravity CLI 1.4.9. Headless: `agy --print PROMPT --output-format stream-json --mode accept-edits`
    # (flags taken from the installed `agy --help`). No USD flag exists; its stream reports tokens only.
    "agy": ProviderContract(
        provider="agy",
        headless_argv=("--print", "--output-format", "stream-json", "--mode", "accept-edits"),
        event_format="agy-stream-json",
        event_flag="--output-format",
        workspace_flag=None,
        sandbox_flags=("--mode", "accept-edits"),
        cost_limit_flag=None,
        turn_limit_flag=None,
        enforces_hard_usd_budget=False,
    ),
    # OpenCode 2.2.1 against a loopback model endpoint (see opencode_cfg): `opencode run --standalone --format json`.
    # Cost is what the stream reports per step (0 for a local model); there is no USD flag.
    "opencode": ProviderContract(
        provider="opencode",
        headless_argv=("run", "--standalone", "--format", "json"),
        event_format="opencode-json",
        event_flag="--format",
        workspace_flag=None,
        sandbox_flags=("OPENCODE_CONFIG_CONTENT permission *=deny", "OPENCODE_DISABLE_PROJECT_CONFIG=1"),
        cost_limit_flag=None,
        turn_limit_flag=None,
        enforces_hard_usd_budget=False,
    ),
    "bob": ProviderContract(
        provider="bob",
        headless_argv=(
            "run",
            "--format",
            "json",
            "--trust",
            "--disable-mcp",
            "--disable-subagents",
            "--max-turns",
            "8",
        ),
        event_format="bob-json",
        event_flag="--format",
        workspace_flag="--workspace",
        sandbox_flags=("--trust", "--disable-mcp", "--disable-subagents"),
        cost_limit_flag="--max-cost",
        turn_limit_flag="--max-turns",
        enforces_hard_usd_budget=True,
    ),
}


def contract_for(provider: str) -> ProviderContract:
    if provider not in PROVIDER_CONTRACTS:
        raise ValueError(f"unsupported provider adapter: {provider}")
    return PROVIDER_CONTRACTS[provider]


def build_invocation(
    provider: str,
    executable: str | Path,
    prompt: str,
    workspace: Path,
    *,
    max_cost_usd: float = 0.0,
    max_turns: int = 8,
    simulated: bool = False,
    externally_sandboxed: bool = False,
    log_file: Path | str | None = None,
    read_only: bool = False,
) -> list[str]:
    """Build an explicit non-interactive argv list without invoking a shell.

    ``externally_sandboxed`` states that the caller wraps the process in repo-ai's own OS write boundary
    (seatbelt/bwrap). Codex cannot apply its inner sandbox from inside another sandbox, so only then is its
    own sandbox disabled; it is never disabled otherwise.

    ``read_only`` (Claude) removes the edit tools for advisory roles that must not change files."""
    contract = contract_for(provider)
    if max_cost_usd < 0 or max_turns < 1 or max_turns > 32:
        raise ValueError("invalid provider budget or turn bounds")
    if max_cost_usd > 0 and not contract.enforces_hard_usd_budget and not simulated:
        raise ValueError(f"{provider} does not enforce a hard USD CLI budget flag; execution blocked")
    exe = str(executable)
    ws = str(workspace.resolve())
    safe_prompt = redact_text(prompt)[:8000]
    if provider == "codex":
        guard = (["--dangerously-bypass-approvals-and-sandbox"] if externally_sandboxed
                 else ["--sandbox", "workspace-write"])
        return [exe, "exec", "--json", "--ephemeral", *guard, "-C", ws, safe_prompt]
    if provider == "claude":
        argv = [
            exe,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--no-session-persistence",
            *claude_auth.invocation_flags(read_only=read_only),
        ]
        if max_cost_usd > 0:
            argv.extend(["--max-budget-usd", f"{max_cost_usd:.4f}"])
        argv.extend(["--", safe_prompt])
        return argv
    if provider == "agy":
        # accept-edits auto-approves file edits only; shell commands stay denied in headless mode
        # (they are reported as `denied_actions`). `--dangerously-skip-permissions` is never used.
        argv = [exe, "--print", safe_prompt, "--output-format", "stream-json", "--mode", "accept-edits",
                "--print-timeout", "900s"]
        if log_file is not None:
            argv.extend(["--log-file", str(log_file)])
        return argv
    if provider == "opencode":
        # the tool policy and model endpoint travel in the environment (opencode_cfg.environment)
        return [exe, "run", "--standalone", "--format", "json", "--model", opencode_cfg.model_ref(), "--", safe_prompt]
    if provider == "gemini":
        return [
            exe,
            "--prompt",
            safe_prompt,
            "--output-format",
            "stream-json",
            "--approval-mode",
            "auto_edit",
            "--skip-trust",
        ]
    # bob 2.0.6+
    argv = [
        exe,
        "run",
        "--format",
        "json",
        "--trust",
        "--disable-mcp",
        "--disable-subagents",
        "--max-turns",
        str(max_turns),
        "--workspace",
        ws,
    ]
    if max_cost_usd > 0:
        argv.extend(["--max-cost", f"{max_cost_usd:.4f}"])
    argv.append(safe_prompt)
    return argv


def parse_event_stream(provider: str, output: bytes) -> dict[str, Any]:
    """Parse structured JSONL events from a provider run with strict redaction.

    Never derives dollar amounts from token prices: if a provider does not report
    explicit dollar cost in its structured stream, `cost_status` is `"UNKNOWN"`.
    """
    contract = contract_for(provider)
    lines = [line.strip() for line in output.decode("utf-8", "replace").splitlines() if line.strip()]
    events_count = 0
    non_json_lines = 0
    session_id: str | None = None
    turns = 0
    cost_usd = 0.0
    cost_reported = False
    input_tokens = 0
    output_tokens = 0
    tool_calls: list[str] = []
    tool_errors: list[str] = []
    denied_actions: list[str] = []
    errors: list[str] = []
    rate_limited = False
    summary = ""
    report = ""
    terminal = False
    protocol_errors: list[str] = []
    try:
        output.decode("utf-8", "strict")
    except UnicodeDecodeError:
        protocol_errors.append("event stream is not valid UTF-8")

    max_lines = 4000 if provider == "opencode" else 500
    if len(lines) > max_lines:
        non_json_lines += 1
        errors.append(f"provider event stream exceeded {max_lines}-line bound")

    for line in lines[:max_lines]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            non_json_lines += 1
            if any(k in line.lower() for k in ("rate limit", "usage limit", "spend limit", "ineligibletiererror", "not logged in")):
                errors.append(redact_text(line)[:200])
                if any(k in line.lower() for k in ("rate limit", "usage limit", "spend limit")):
                    rate_limited = True
            continue
        if not isinstance(obj, dict):
            non_json_lines += 1
            continue
        events_count += 1
        raw_stats = obj.get("stats")
        stats: dict[str, Any] = raw_stats if isinstance(raw_stats, dict) else {}
        sid = (
            obj.get("session_id")
            or obj.get("sessionID")
            or obj.get("thread_id")
            or obj.get("conversation_id")
            or stats.get("task_id")
        )
        if isinstance(sid, str) and sid and session_id is None:
            session_id = redact_text(sid)[:80]
        if isinstance(sid, str) and session_id != redact_text(sid)[:80]:
            protocol_errors.append("conflicting provider run identities")
        etype = str(obj.get("type") or obj.get("event") or "")
        expected_terminal = {
            "codex": {"turn.completed", "turn.failed"},
            "claude": {"result"}, "gemini": {"result"}, "bob": {"result"}, "agy": {"result"},
            "opencode": {"text"},
        }[provider]
        if etype in expected_terminal:
            terminal = True
        if not etype:
            protocol_errors.append("event type is missing")
        if etype in {"turn.completed", "assistant", "result", "step", "turn"}:
            turns += 1
        if etype == "rate_limit_event":
            rinfo = obj.get("rate_limit_info")
            if isinstance(rinfo, dict) and rinfo.get("status") == "rejected":
                rate_limited = True
                errors.append(f"rate_limit_event rejected ({rinfo.get('rateLimitType', 'limit')})")
        if etype == "turn.failed" or obj.get("status") in {"error", "failed"} or obj.get("is_error") is True:
            err_msg = (
                (obj.get("error") or {}).get("message")
                if isinstance(obj.get("error"), dict)
                else (obj.get("error") or obj.get("api_error") or obj.get("result") or "provider turn failed")
            )
            if isinstance(err_msg, str) and err_msg:
                errors.append(redact_text(err_msg)[:200])
                if any(k in err_msg.lower() for k in ("usage limit", "spend limit", "rate_limit", "usage_limit")):
                    rate_limited = True
        if obj.get("api_error_status") == 429 or obj.get("api_error") == "usage_limit_reached":
            rate_limited = True

        tool = (
            obj.get("tool")
            or obj.get("tool_name")
            or ((obj.get("item") or {}).get("tool") if isinstance(obj.get("item"), dict) else None)
        )
        if isinstance(tool, str) and tool:
            tool_calls.append(redact_text(tool)[:80])
        elif isinstance(stats.get("tool_calls"), int) and stats["tool_calls"] > 0 and not tool_calls:
            tool_calls.extend([f"bob_tool_{i+1}" for i in range(min(stats["tool_calls"], 16))])

        usage = obj.get("usage")
        if isinstance(usage, dict):
            in_tok = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            out_tok = usage.get("output_tokens") or usage.get("completion_tokens") or 0
            if isinstance(in_tok, int) and not isinstance(in_tok, bool) and in_tok >= 0:
                input_tokens += in_tok
            if isinstance(out_tok, int) and not isinstance(out_tok, bool) and out_tok >= 0:
                output_tokens += out_tok

        raw_cost = None
        if "cost_usd" in obj:
            raw_cost = obj.get("cost_usd")
        elif "total_cost_usd" in obj:
            raw_cost = obj.get("total_cost_usd")
        elif "session_costs" in stats:
            raw_cost = stats.get("session_costs")
        if isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool) and math.isfinite(raw_cost) and raw_cost >= 0:
            cost_reported = True
            cost_usd = max(cost_usd, float(raw_cost))

        err = obj.get("error")
        if isinstance(err, str) and err:
            clean_err = redact_text(err)[:200]
            if clean_err not in errors:
                errors.append(clean_err)
            if any(k in clean_err.lower() for k in ("usage limit", "spend limit", "rate_limit")):
                rate_limited = True
        elif isinstance(err, dict) and isinstance(err.get("message"), str):
            clean_err = redact_text(err["message"])[:200]
            if clean_err not in errors:
                errors.append(clean_err)
            if any(k in clean_err.lower() for k in ("usage limit", "spend limit", "rate_limit")):
                rate_limited = True

        if provider == "agy":
            raw_body = obj.get(etype)
            body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}
            cid = body.get("conversation_id")
            if isinstance(cid, str) and cid and session_id is None:
                session_id = redact_text(cid)[:80]
            if etype == "step_update" and body.get("step_type") == "tool":
                name = redact_text(str(body.get("tool_name", "")))[:80]
                if body.get("state") == "ERROR":
                    tool_errors.append(name)
                elif body.get("state") == "DONE" and name:
                    tool_calls.append(name)
            elif etype == "result":
                agy_status = str(body.get("status", ""))
                if agy_status != "SUCCESS":
                    errors.append(redact_text(str(body.get("error") or f"agy result status {agy_status or 'missing'}"))[:200])
                err_low = str(body.get("error", "")).lower()
                if any(k in err_low for k in ("quota", "rate limit", "usage limit", "resource exhausted", "billing")):
                    rate_limited = True
                for d in body.get("denied_actions") or []:
                    if isinstance(d, dict):
                        denied_actions.append(redact_text(str(d.get("display_name") or d.get("action") or "action"))[:80])
                usage_body = body.get("usage")
                if isinstance(usage_body, dict):
                    for key, name in (("input_tokens", "in"), ("output_tokens", "out")):
                        v = usage_body.get(key)
                        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                            if name == "in":
                                input_tokens += v
                            else:
                                output_tokens += v
                txt = body.get("response")
                if isinstance(txt, str) and txt:
                    summary = redact_text(txt)[:240]
                    report = redact_text(txt)[:6000]

        if provider == "claude":
            message = obj.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if etype == "assistant" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                        tool_calls.append(redact_text(block["name"])[:80])
            if etype == "result":
                for d in obj.get("permission_denials") or []:
                    if isinstance(d, dict):
                        denied_actions.append(redact_text(str(d.get("tool_name") or "tool"))[:80])

        if provider == "opencode":
            raw_part = obj.get("part")
            part: dict[str, Any] = raw_part if isinstance(raw_part, dict) else {}
            if etype == "step_finish":
                turns += 1
                step_cost = part.get("cost")
                if isinstance(step_cost, (int, float)) and not isinstance(step_cost, bool) and math.isfinite(step_cost) \
                        and step_cost >= 0:
                    cost_reported = True
                    cost_usd += float(step_cost)
                toks = part.get("tokens")
                if isinstance(toks, dict):
                    for key, name in (("input", "in"), ("output", "out")):
                        v = toks.get(key)
                        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                            if name == "in":
                                input_tokens += v
                            else:
                                output_tokens += v
            elif etype == "tool_use":
                name = redact_text(str(part.get("tool") or "tool"))[:80]
                state_raw = part.get("state")
                state: dict[str, Any] = state_raw if isinstance(state_raw, dict) else {}
                if state.get("status") == "error":
                    tool_errors.append(name)
                    if "permission denied" in str(state.get("error", "")).lower():
                        denied_actions.append(name)
                else:
                    tool_calls.append(name)
            elif etype == "text" and isinstance(part.get("text"), str) and part["text"]:
                summary = redact_text(part["text"])[:240]
                report = redact_text(part["text"])[:6000]
            elif etype == "error":
                raw_err = obj.get("error")
                msg_text = raw_err.get("message") if isinstance(raw_err, dict) else raw_err
                if isinstance(msg_text, str) and msg_text:
                    errors.append(redact_text(msg_text)[:200])
                    if any(k in msg_text.lower() for k in ("rate limit", "quota", "usage limit")):
                        rate_limited = True

        item = obj.get("item")
        if provider == "codex" and etype == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                summary = redact_text(item["text"])[:240]
            elif item.get("type") in {"command_execution", "file_change", "mcp_tool_call"}:
                tool_calls.append(str(item["type"]))

        msg = obj.get("result") or obj.get("summary") or obj.get("last_message") or obj.get("message")
        if isinstance(msg, str) and msg and provider != "opencode":
            summary = redact_text(msg)[:240]
            report = redact_text(msg)[:6000]

    return {
        "provider": provider,
        "event_format": contract.event_format,
        "valid_jsonl": events_count > 0 and non_json_lines == 0,
        "terminal_observed": terminal,
        "protocol_valid": events_count > 0 and non_json_lines == 0 and terminal and not protocol_errors,
        "protocol_errors": protocol_errors[:10],
        "events_count": events_count,
        "non_json_lines": non_json_lines,
        "session_id": session_id,
        "turns": max(turns, 1 if events_count > 0 else 0),
        "tool_calls": tool_calls[:32],
        "tool_errors": tool_errors[:32],
        "denied_actions": denied_actions[:32],
        "tokens": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": round(cost_usd, 6),
        "cost_reported": cost_reported,
        "cost_status": "OBSERVED" if cost_reported else "UNKNOWN",
        "rate_limited": rate_limited,
        "errors": errors[:10],
        "summary": summary,
        "report": report,
        "output_sha256": hashlib.sha256(output).hexdigest(),
    }


AGY_STATE_DIR = ".gemini/antigravity-cli"
# Per-user history the provider does not need to authenticate or edit; unreadable inside the sandbox.
AGY_PRIVATE_STATE = ("conversations", "brain", "knowledge", "annotations", "implicit", "log", "crashes")
AGY_PRIVATE_FILES = ("history.jsonl", "conversation_summaries.db", "jetbox_summaries_proto.pb")


def _agy_live_read_rules(workspace: Path, scratch: Path) -> str:
    """Seatbelt read policy for a live `agy` run (it must run with the real HOME: its login lives there).

    Everything under HOME is unreadable except what the CLI demonstrably needs to start and authenticate
    (verified by probe, see docs): its own state dir minus per-user history, ~/.gemini/config, ~/.local (the
    binary) and the login keychain database file. The last is a real exposure: the provider process can read
    that (encrypted) file. Writes under HOME stay denied by the global `(deny file-write*)`.
    """
    home = Path.home().resolve()
    state = home / AGY_STATE_DIR
    q = json.dumps
    rules = [f"(deny file-read* (subpath {q(str(home))}))", f"(allow file-read* (literal {q(str(home))}))",
             f"(allow file-read-metadata (subpath {q(str(home))}))",
             f"(allow file-read* (subpath {q(str(workspace.resolve()))}))", f"(allow file-read* (subpath {q(str(scratch.resolve()))}))",
             f"(allow file-read* (subpath {q(str(state))}))",
             f"(allow file-read* (subpath {q(str(home / '.gemini' / 'config'))}))",
             f"(allow file-read* (subpath {q(str(home / '.local'))}))",
             f"(allow file-read* (literal {q(str(home / 'Library' / 'Keychains'))}))"]
    rules += [f"(allow file-read* (literal {q(str(home / 'Library' / 'Keychains' / n))}))"
              for n in ("login.keychain-db", "metadata.keychain-db")]
    rules += [f"(deny file-read* (subpath {q(str(state / d))}))" for d in AGY_PRIVATE_STATE]
    rules += [f"(deny file-read* (literal {q(str(state / f))}))" for f in AGY_PRIVATE_FILES]
    return "".join(rules)


def _execution_sandbox_prefix(workspace: Path, scratch: Path, *, allow_network: bool = False,
                              provider: str | None = None, live: bool = False,
                              executable: Path | None = None,
                              claude_plan: claude_auth.ClaudeAuthPlan | None = None,
                              run_marker: str | None = None) -> list[str] | None:
    """Restrict writes strictly to the disposable candidate workspace and scratch dir (plus, for a live Claude
    run with a dedicated login, that login's own state; see ``claude_auth``)."""
    claude_live = provider == "claude" and live
    if claude_live:
        claude_plan = claude_plan or claude_auth.plan()
        located = shutil.which("claude")
        executable = executable or (Path(located) if located else None)
    ws_str = str(workspace.resolve())
    sc_str = str(scratch.resolve())
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        net_rule = "" if allow_network else "(deny network*)"
        if provider == "opencode" and live:
            # a local model only: the provider may reach loopback (its own server and the model endpoint), nothing else
            # (`(allow network* (local ip "localhost:*"))` would also admit outbound connections to any host: observed)
            net_rule = ('(deny network*)(allow network-outbound (remote ip "localhost:*"))'
                        '(allow network-inbound (local ip "localhost:*"))(allow network-bind (local ip "localhost:*"))'
                        f"(allow network-outbound (remote unix-socket (subpath {json.dumps(str(scratch.resolve()))})))")
        home = Path.home().resolve()
        # A live provider has network access, so the host's credential stores are unreadable to it.
        secret_dirs = ("/.ssh", "/.aws", "/.gnupg", "/.config/gh", "/.netrc", "/Library/Keychains")
        read_rule = "".join(f"(deny file-read* (subpath {json.dumps(str(home) + d)}))" for d in secret_dirs)
        extra_write = ""
        if provider == "agy" and live:
            read_rule = _agy_live_read_rules(workspace, scratch)
        elif provider == "opencode" and live:
            read_rule = _home_read_only_rules([workspace, scratch, *([executable] if executable else [])])
        elif provider == "codex" and live:
            # Codex's token is copied into scratch (CODEX_HOME); ~/.codex itself, other agents' state and every other
            # file under HOME stay unreadable to a model that has a shell and the network
            read_rule = _home_read_only_rules([workspace, scratch, *_codex_install_roots(executable), *_node_roots()])
            net_rule += _unix_socket_rule(sc_str)
        elif claude_live:
            assert claude_plan is not None
            read_rule, extra_write = claude_auth.seatbelt_rules(workspace, scratch, executable, claude_plan,
                                                                extra_read=_node_roots())
            # the API needs the network, but no local service does: unix sockets only for DNS and the scratch dir
            # (otherwise e.g. a container engine socket or ssh-agent would be reachable)
            net_rule += _unix_socket_rule(sc_str)
        # `open` (LaunchServices) and Apple events would start programs outside this sandbox and outside the sweep
        profile = (
            f"(version 1)(allow default)(deny lsopen)(deny appleevent-send){net_rule}{read_rule}(deny file-write*)"
            f"(allow file-write* (subpath {json.dumps(ws_str)}))"
            f"(allow file-write* (subpath {json.dumps(sc_str)}))"
            '(allow file-write* (literal "/dev/null"))'
            f"{extra_write}"
        )
        if run_marker:
            # identity for the post-run sweep (`_seatbelt_procs`): every descendant inherits this profile, even after
            # setsid or a double fork, and is found by "this preference domain allowed, other run domains denied"
            profile += ('(deny user-preference-read (preference-domain-regex #"^com\\.repo-ai\\.run\\."))'
                        f'(allow user-preference-read (preference-domain "{run_marker}"))')
        return ["/usr/bin/sandbox-exec", "-p", profile]
    if provider in {"agy", "opencode"} and live:
        return None  # no tested read/network restriction for these outside macOS seatbelt: refuse, do not weaken
    if sys.platform.startswith("linux"):
        bwrap = shutil.which("bwrap", path=os.defpath)
        if bwrap:
            cmd = [bwrap]
            if not allow_network:
                cmd.append("--unshare-net")
            cmd.extend([
                "--die-with-parent",
                "--new-session",
                "--unshare-pid",  # descendants (even setsid'd ones) die with the namespace when the run ends
                "--ro-bind",
                "/",
                "/",
            ])
            if provider == "codex" and live:
                home = str(Path.home().resolve())
                cmd.extend(["--tmpfs", home])
                for root_dir in [*_codex_install_roots(executable), *_node_roots()]:
                    cmd.extend(["--ro-bind", str(root_dir), str(root_dir)])
            if claude_live:
                # hide the whole HOME (credentials, other projects) and re-expose only what Claude needs
                assert claude_plan is not None
                home = str(Path.home().resolve())
                cmd.extend(["--tmpfs", home])
                if executable is not None:
                    for root_dir in claude_auth._install_roots(executable):
                        cmd.extend(["--ro-bind", str(root_dir), str(root_dir)])
                for node_root in _node_roots():
                    cmd.extend(["--ro-bind", str(node_root), str(node_root)])
                if claude_plan.mode == "dedicated_config" and claude_plan.config_dir is not None:
                    cfg = str(claude_plan.config_dir.resolve())
                    cmd.extend(["--bind", cfg, cfg])
            cmd.extend([
                "--bind",
                ws_str,
                ws_str,
                "--bind",
                sc_str,
                sc_str,
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--",
            ])
            return cmd
    return None


def _unix_socket_rule(scratch: str) -> str:
    """Networked providers need DNS, but no local service: unix sockets only for mDNSResponder and the scratch dir
    (otherwise a container-engine socket or ssh-agent would be reachable)."""
    return ('(deny network-outbound (remote unix-socket))'
            '(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))'
            f"(allow network-outbound (remote unix-socket (subpath {json.dumps(scratch)})))")


def _codex_install_roots(executable: Path | None) -> list[Path]:
    """The Codex release directory (`…/releases/<version>/` for the standalone install, which lives inside ~/.codex
    next to the token) or the binary's own directory — never ~/.codex itself or anything broader."""
    if executable is None:
        located = shutil.which("codex")
        if not located:
            return []
        executable = Path(located)
    exe = executable.resolve()
    roots = [exe.parent.parent if exe.parent.name == "bin" else exe.parent]
    personal = (Path.home() / ".codex").resolve()
    return [r for r in roots if r != personal and r not in personal.parents and not claude_auth.too_broad(r)] or [exe]


def _home_read_only_rules(allowed: list[Path]) -> str:
    """Deny every read under HOME except the given paths (and, for an executable, its installation directory)."""
    home = Path.home().resolve()
    q = json.dumps
    rules = [f"(deny file-read* (subpath {q(str(home))}))", f"(allow file-read* (literal {q(str(home))}))",
             f"(allow file-read-metadata (subpath {q(str(home))}))"]
    for path in allowed:
        target = path.resolve()
        if target.is_file():
            kind, target = ("literal", target) if claude_auth.too_broad(target.parent) else ("subpath", target.parent)
        else:
            kind = "subpath"
            if claude_auth.too_broad(target):
                raise ValueError(f"refusing to expose {target} to a provider")
        rules.append(f"(allow file-read* ({kind} {q(str(target))}))")
    return "".join(rules)


def _node_roots() -> list[Path]:
    """The installation prefix of the `node` runtime on PATH when it lives under HOME (nvm, volta): an npm-installed
    CLI cannot start without it. Never a repository directory (callers also check executables)."""
    node = shutil.which("node", path=os.environ.get("PATH", os.defpath))
    if not node:
        return []
    binary = Path(node).resolve()
    home = Path.home().resolve()
    return [binary] if home in binary.parents else []


def _seed_live_provider_auth(provider: str, scratch_home: Path) -> None:
    """Copy minimal provider auth configuration into isolated scratch HOME so real $HOME stays read-only."""
    real_home = Path.home()
    try:
        if provider == "bob":
            src = real_home / ".bob" / "settings"
            dst = scratch_home / ".bob" / "settings"
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
        elif provider == "codex":
            # Codex needs its token file, and its shell tool can read it (disclosed). A dedicated repo-ai login
            # (`CODEX_HOME=<dir> codex login`) makes that a separate, revocable session; otherwise ~/.codex is used.
            source = codex_login_source()
            if source in {"none", "invalid"}:
                return  # an explicit dedicated login that is missing or unsafe never falls back to ~/.codex
            src_dir = codex_home() if source == "dedicated" else real_home / ".codex"
            dst_dir = scratch_home / ".codex"
            dst_dir.mkdir(parents=True, exist_ok=True)
            auth = src_dir / "auth.json"
            if auth.is_file() and not auth.is_symlink():
                shutil.copyfile(auth, dst_dir / "auth.json", follow_symlinks=False)
            sanitized = _codex_config_subset(src_dir / "config.toml")
            if sanitized:
                (dst_dir / "config.toml").write_text(sanitized, encoding="utf-8")
        elif provider == "claude":
            pass  # nothing is copied: see claude_auth (token in the environment, or a dedicated repo-ai login)
        elif provider == "agy":
            pass  # nothing is copied: agy authenticates from the real HOME under a read-restricted sandbox
        elif provider == "gemini":
            # nothing is copied: ~/.gemini holds OAuth tokens, account lists and other agents' state (agy's
            # conversation history lives under ~/.gemini/antigravity-cli). Live Gemini needs an API key variable.
            pass
    except OSError:
        pass


SIMULATED_TIMEOUT_CAP = 30.0
LIVE_TIMEOUT_CAP = 900.0


def provider_timeout(timeout: float, simulated: bool) -> float:
    """Bound a provider call. Simulated contract checks stay short; a real model
    repair legitimately needs minutes, so live calls are bounded by the mission's
    remaining time budget and a hard ceiling."""
    cap = SIMULATED_TIMEOUT_CAP if simulated else LIVE_TIMEOUT_CAP
    return max(0.05, min(float(timeout), cap))


def live_constraint_prompt(provider: str, prompt: str, allowed: str, workspace: Path | str) -> str:
    """Constraint text for a live implementer. Enforcement is the sandbox plus the post-run scope check;
    the text only has to be usable. Codex has no file-read tool other than its shell, so it may inspect
    read-only there; a "no shell" rule makes it decline the task (observed)."""
    base = (f"{prompt}\n\nCONSTRAINTS: Edit ONLY {allowed} inside {workspace}. "
            "Do not modify test files, configuration files, or create untracked files. ")
    if provider in {"agy", "opencode"}:
        return base + ("Use only your file view and edit tools. Shell commands are not available and will be denied; "
                       "do not try to run tests.")
    if provider in {"codex", "claude", "gemini"}:
        return base + ("Read files with read-only commands (cat, ls, grep) if you need to; do not run the tests "
                       "or any command that writes files other than your edit.")
    return base + "Do not run shell commands; inspect and edit the source file directly."


def run_provider(
    provider: str,
    root: Path,
    workspace: Path,
    prompt: str,
    *,
    write_paths: list[str],
    executable: Path | str | None = None,
    timeout: float = 25.0,
    max_cost_usd: float = 0.0,
    simulated: bool = True,
    allow_live: bool = False,
    constraints: str | None = None,
) -> dict[str, Any]:
    """Run a bounded provider adapter inside the disposable candidate workspace.

    Live billable execution is blocked unless `simulated=False` and `allow_live=True`
    are explicitly passed; `simulated=True` runs a local non-billable provider
    executable under network-denied sandboxing.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    root = root.resolve()
    workspace = workspace.resolve()
    if _inside(workspace, root):
        raise ValueError("provider workspace must be an isolated disposable directory outside root")
    if not simulated and not allow_live:
        raise ValueError("live provider execution is blocked without paid_actions_authorized and explicit network approval")
    if max_cost_usd != 0.0 and simulated:
        raise ValueError("simulated provider execution requires zero USD cost ceiling")
    contract = contract_for(provider)
    if not simulated and max_cost_usd > 0 and not contract.enforces_hard_usd_budget:
        raise ValueError(f"{provider} does not enforce a hard USD CLI budget flag; execution blocked")

    exe_str = str(executable) if executable is not None else shutil.which(provider)
    if not exe_str:
        return {
            "provider": provider,
            "stage": "NOT_INSTALLED",
            "simulated": simulated,
            "verification_label": "SIMULATED" if simulated else "NOT_RUN",
            "returncode": -1,
            "capture_status": "not_installed",
            "identity_sha256": None,
            "cost_usd": 0.0,
            "cost_status": "UNKNOWN",
            "events": {},
            "reasons": [f"{provider} executable is not installed"],
        }

    raw = Path(os.path.abspath(exe_str))
    try:
        resolved = raw.resolve(strict=True)
        if _repo_owned(raw, root):
            return {
                "provider": provider,
                "stage": "BLOCKED",
                "simulated": simulated,
                "verification_label": "SIMULATED" if simulated else "BLOCKED",
                "returncode": -1,
                "capture_status": "untrusted_executable",
                "identity_sha256": None,
                "cost_usd": 0.0,
                "cost_status": "UNKNOWN",
                "events": {},
                "reasons": ["repository-owned executable or symlink alias refused"],
            }
        identity_before = _identity(resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "provider": provider,
            "stage": "FAILED",
            "simulated": simulated,
            "verification_label": "SIMULATED" if simulated else "FAILED",
            "returncode": -1,
            "capture_status": "identity_failed",
            "identity_sha256": None,
            "cost_usd": 0.0,
            "cost_status": "UNKNOWN",
            "events": {},
            "reasons": [redact_text(str(exc))[:200]],
        }

    live_run = not simulated and allow_live
    if provider in {"opencode", "gemini"} and live_run:
        problems = setup_problems(provider)
        if problems:
            return {
                "provider": provider, "stage": "BLOCKED", "simulated": False, "verification_label": "BLOCKED",
                "returncode": -1, "capture_status": "not_configured", "identity_sha256": identity_before,
                "cost_usd": 0.0, "cost_status": "UNKNOWN", "events": {},
                "reasons": [f"{provider} not configured for isolated execution: {p}" for p in problems],
            }
    claude_plan = claude_auth.plan() if provider == "claude" and live_run else None
    if claude_plan is not None:
        blocked = _claude_preflight(resolved, claude_plan)
        if blocked:
            return {
                "provider": provider,
                "stage": "BLOCKED",
                "simulated": False,
                "verification_label": "BLOCKED",
                "returncode": -1,
                "capture_status": blocked[0],
                "identity_sha256": identity_before,
                "cost_usd": 0.0,
                "cost_status": "UNKNOWN",
                "auth_mode": claude_plan.mode,
                "events": {},
                "reasons": blocked[1],
            }

    bounded_timeout = provider_timeout(timeout, simulated)
    with tempfile.TemporaryDirectory(prefix=f"repo-ai-provider-run-{provider}-") as directory:
        scratch = Path(directory).resolve()
        for name in ("home", "tmp", "home/.codex", "home/.gemini", "home/.claude", "home/.bob"):
            (scratch / name).mkdir(exist_ok=True)
        if not simulated and allow_live:
            _seed_live_provider_auth(provider, scratch / "home")
        from .. import sandbox as _sandbox
        run_marker = _sandbox._procs.PREFIX + uuid.uuid4().hex if sys.platform == "darwin" else None
        prefix = _execution_sandbox_prefix(workspace, scratch, allow_network=live_run, provider=provider, live=live_run,
                                           executable=resolved, claude_plan=claude_plan, run_marker=run_marker)
        if prefix is None:
            return {
                "provider": provider,
                "stage": "BLOCKED",
                "simulated": simulated,
                "verification_label": "SIMULATED" if simulated else "BLOCKED",
                "returncode": -1,
                "capture_status": "no_sandbox",
                "identity_sha256": identity_before,
                "cost_usd": 0.0,
                "cost_status": "UNKNOWN",
                "events": {},
                "reasons": ["no supported execution sandbox on this host" if not (provider == "agy" and live_run) else
                            "agy live execution needs the macOS seatbelt read policy (not available here); refused"],
            }
        env = _probe_env(scratch)
        if provider == "agy" and live_run:
            # agy's login is in the real HOME (no supported scratch-HOME auth). Run with the real HOME, but
            # read-restricted and write-denied by the seatbelt profile above; no credential is copied.
            env["HOME"] = env["USERPROFILE"] = str(Path.home())
        if claude_plan is not None and claude_plan.mode == "dedicated_config":
            # the login lives in the user's keychain under this config dir and $USER; HOME stays read-restricted
            assert claude_plan.config_dir is not None
            env["HOME"] = env["USERPROFILE"] = str(Path.home())
            env["CLAUDE_CONFIG_DIR"] = str(claude_plan.config_dir)
        if provider == "opencode":
            env.update(opencode_cfg.environment(read_only=not write_paths))
        env["REPO_AI_WORKSPACE"] = str(workspace)
        env["REPO_AI_WRITE_PATHS"] = ",".join(write_paths)
        if not simulated and allow_live:
            auth_vars = {
                "bob": ("BOB_API_KEY", "USER"),
                "claude": (*claude_auth.TOKEN_ENV_VARS, "USER", "ANTHROPIC_MODEL"),
                "codex": ("OPENAI_API_KEY", "USER"),
                "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "USER"),
            }.get(provider, ())
            for var_name in auth_vars:
                val = os.environ.get(var_name)
                if val:
                    env[var_name] = val
        path_parts = [str(Path(sys.executable).resolve().parent)]
        node_bin = shutil.which("node", path=os.environ.get("PATH", os.defpath))
        if node_bin:
            node_resolved = Path(node_bin).resolve()
            if not _inside(node_resolved, root):
                path_parts.append(str(node_resolved.parent))
        path_parts.append(env.get("PATH", os.defpath))
        env["PATH"] = os.pathsep.join(path_parts)

        effective_prompt = prompt
        if not simulated and allow_live and constraints is not None:
            effective_prompt = f"{prompt}\n\nCONSTRAINTS: {constraints}"
        elif not simulated and allow_live and write_paths:
            allowed_str = ", ".join(write_paths)
            effective_prompt = live_constraint_prompt(provider, prompt, allowed_str, workspace)
        argv = build_invocation(
            provider,
            resolved,
            effective_prompt,
            workspace,
            max_cost_usd=max_cost_usd,
            simulated=simulated,
            externally_sandboxed=True,  # prefix is non-None here: the outer sandbox is the write boundary
            log_file=scratch / "agy.log",
            read_only=not write_paths,
        )
        is_seatbelt = prefix[:1] == ["/usr/bin/sandbox-exec"]
        if claude_plan is not None:
            try:
                unexpected = _claude_isolation_probe(prefix, argv, workspace, env, read_only=not write_paths)
            finally:  # the probe runs under the same profile and marker: nothing it started may outlive it
                probe_cleanup = _reap_provider_run(run_marker) if is_seatbelt else []
            unexpected += probe_cleanup
            if unexpected:
                return {
                    "provider": provider, "stage": "BLOCKED", "simulated": False, "verification_label": "BLOCKED",
                    "returncode": -1, "capture_status": "isolation_probe_failed", "identity_sha256": identity_before,
                    "cost_usd": 0.0, "cost_status": "UNKNOWN", "auth_mode": claude_plan.mode, "events": {},
                    "reasons": unexpected,
                }
        # OpenCode's events embed whole tool inputs/outputs (observed 68 KB for a 28-edit local run)
        limit = MAX_OUTPUT * 4 if provider == "opencode" else MAX_OUTPUT
        try:
            result = _capture([*prefix, *argv], workspace, env, timeout=bounded_timeout, output_limit=limit,
                              separate_stderr=True,
                              max_timeout=LIVE_TIMEOUT_CAP if not simulated else SIMULATED_TIMEOUT_CAP)
        finally:  # also on an exception or Ctrl-C: setsid'd descendants are not in the process group
            cleanup_problems = _reap_provider_run(run_marker) if is_seatbelt else []
        try:
            unchanged = raw.resolve(strict=True) == resolved and _identity(resolved) == identity_before
        except (OSError, RuntimeError, ValueError):
            unchanged = False

    if not unchanged:
        return {
            "provider": provider,
            "stage": "FAILED",
            "simulated": simulated,
            "verification_label": "SIMULATED" if simulated else "FAILED",
            "returncode": result.returncode,
            "capture_status": "executable_changed",
            "identity_sha256": identity_before,
            "cost_usd": 0.0,
            "cost_status": "UNKNOWN",
            "events": {},
            "reasons": ["provider executable changed during execution; output discarded"],
        }

    events = parse_event_stream(provider, result.output)
    # Diagnostics are never parsed as events, usage or monetary observations.
    diagnostic = result.stderr.decode("utf-8", "replace")
    diagnostic_lower = diagnostic.lower()
    diagnostic_rate_limit = any(term in diagnostic_lower for term in
                                ("rate limit", "usage limit", "spend limit", "rate_limit", "usage_limit"))
    events["rate_limited"] = events["rate_limited"] or diagnostic_rate_limit
    reasons: list[str] = []
    if result.status != "complete":
        reasons.append(f"provider process capture terminated early: {result.status}")
    if cleanup_problems and not simulated:
        reasons.extend(cleanup_problems)
    if claude_plan is not None:
        # the same checks on the real session's own init event (account state could change after the probe)
        init = _claude_init_event(result.output)
        reasons.extend(f"live session: {r}" for r in
                       (_claude_init_problems(init, read_only=not write_paths) if init else
                        ["no init event; what the session loaded is unknown"]))
    if result.returncode != 0:
        reasons.append(f"provider process exited with code {result.returncode}")
    if provider == "gemini" and result.returncode == 41:  # Gemini CLI's documented authentication-failure exit code
        reasons.append("gemini not authenticated for isolated execution (exit 41): check GEMINI_API_KEY / GOOGLE_API_KEY")
    if not events["valid_jsonl"]:
        reasons.append("provider output did not conform to structured JSONL event contract")
    if not simulated and not events["protocol_valid"]:
        reasons.append("live provider stream lacks a consistent terminal event protocol")
    if events.get("rate_limited"):
        reasons.append(f"provider rate/usage limit reached ({provider})")
    if events["errors"]:
        reasons.extend(f"provider error event: {e}" for e in events["errors"])
    if max_cost_usd > 0 and not simulated:
        if not events.get("cost_reported"):
            reasons.append("provider did not report cost; unknown cost cannot satisfy hard USD budget")
        elif events["cost_usd"] > max_cost_usd:
            reasons.append("provider reported cost exceeding approved contract ceiling")
    elif events["cost_usd"] > max_cost_usd:
        reasons.append("provider reported cost exceeding approved contract ceiling")

    stage = "SIMULATED" if not reasons and simulated else ("READY" if not reasons else "FAILED")
    return {
        "provider": provider,
        "stage": stage,
        "simulated": simulated,
        "verification_label": "SIMULATED" if simulated else ("LIVE_READY" if not reasons else "LIVE_FAILED"),
        **({"auth_mode": claude_plan.mode} if claude_plan is not None else {}),
        "executable": resolved.name,
        "identity_sha256": identity_before,
        "returncode": result.returncode,
        "capture_status": result.status,
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
        "stderr_bytes": len(result.stderr),
        "diagnostic_summary": redact_text(diagnostic)[:240],
        "cost_usd": events["cost_usd"],
        "cost_status": events.get("cost_status", "UNKNOWN"),
        "rate_limited": bool(events.get("rate_limited")),
        "events": events,
        "reasons": reasons,
    }


GEMINI_KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
CODEX_HOME_ENV = "REPO_AI_CODEX_HOME"


CODEX_CONFIG_KEYS = ("model", "model_reasoning_effort", "model_provider", "preferred_auth_method", "model_verbosity")
_CODEX_VALUE = re.compile(r"[A-Za-z0-9._:/@+-]{1,128}")


def _codex_config_subset(path: Path) -> str:
    """Only plain model-selection keys of the user's Codex config. Never tables or commands: `mcp_servers` would start
    servers inside the sandbox, `notify` runs a program, `projects` carries trust decisions."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    lines = []
    for key in CODEX_CONFIG_KEYS:
        value = data.get(key)
        if isinstance(value, str) and _CODEX_VALUE.fullmatch(value):  # also valid TOML: no escapes needed at all
            lines.append(f'{key} = "{value}"')
    return "\n".join(lines) + ("\n" if lines else "")


def codex_home() -> Path:
    """The dedicated repo-ai Codex login directory (may not exist)."""
    override = os.environ.get(CODEX_HOME_ENV)
    if override:
        return Path(override).expanduser()
    from ..registry import registry_home
    return registry_home() / "codex-provider"


def codex_login_source() -> str:
    """`dedicated` (a separate repo-ai Codex login), `personal` (~/.codex), `none`, or `invalid` (an explicit override
    that is relative, is ~/.codex itself, or whose auth.json is not a regular file). An explicit override never falls
    back to the personal login."""
    explicit = bool(os.environ.get(CODEX_HOME_ENV))
    home = codex_home()
    personal = Path.home() / ".codex"
    if explicit and (not home.is_absolute() or home.resolve() == personal.resolve()):
        return "invalid"
    auth = home / "auth.json"
    if auth.is_symlink():
        return "invalid"
    if auth.is_file():
        return "dedicated"
    if explicit:
        return "none"
    return "personal" if (personal / "auth.json").is_file() and not (personal / "auth.json").is_symlink() else "none"


def setup_problems(provider: str) -> list[str]:
    """Offline: what stops repo-ai's isolation from authenticating this provider at all. Reads no secret value."""
    if provider == "claude":
        return list(claude_auth.plan().problems)
    if provider == "opencode":
        return opencode_cfg.setup_problems()
    if provider == "gemini" and not any(os.environ.get(v) for v in GEMINI_KEY_VARS):
        return ["set GEMINI_API_KEY (or GOOGLE_API_KEY) in repo-ai's environment; repo-ai no longer copies ~/.gemini "
                "(OAuth tokens and other agents' state) into the sandbox"]
    return []


ISOLATION_PROBE_MODEL = "repo-ai-isolation-probe-not-a-model"
BUILTIN_AGENTS = frozenset({"claude", "Explore", "general-purpose", "Plan"})


def _claude_init_event(output: bytes) -> dict[str, Any]:
    for line in output.decode("utf-8", "replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "system" and obj.get("subtype") == "init":
            return obj
    return {}


def _claude_init_problems(init: dict[str, Any], *, read_only: bool) -> list[str]:
    """What a Claude session loaded beyond repo-ai's request. Missing or renamed fields are problems, not passes."""
    problems = []
    for key in ("tools", "mcp_servers", "plugins", "skills", "slash_commands", "agents"):
        if not isinstance(init.get(key), list):
            problems.append(f"init event has no `{key}` list; cannot confirm isolation")
    if problems:
        return problems
    wanted = set((claude_auth.READ_TOOLS if read_only else claude_auth.EDIT_TOOLS).split(","))
    tools = {str(t) for t in init["tools"]}
    if tools != wanted:
        problems.append(f"tools {sorted(tools)} differ from the requested {sorted(wanted)}")
    if init["mcp_servers"]:
        problems.append("MCP servers: " + ", ".join(str(m.get("name", m)) if isinstance(m, dict) else str(m)
                                                     for m in init["mcp_servers"][:8]))
    foreign = [str(p.get("name", p)) if isinstance(p, dict) else str(p) for p in init["plugins"]
               if not (isinstance(p, dict) and str(p.get("name", "")).startswith("cc-plugin-")
                       and p.get("path") == "builtin")]
    if foreign:
        problems.append("plugins: " + ", ".join(foreign[:8]))
    if init["skills"] or init["slash_commands"]:
        problems.append("skills or commands: " + ", ".join(str(x) for x in [*init["skills"], *init["slash_commands"]][:8]))
    agents = {str(a.get("name", a)) if isinstance(a, dict) else str(a) for a in init["agents"]}
    if agents - BUILTIN_AGENTS:
        problems.append("custom agents: " + ", ".join(sorted(agents - BUILTIN_AGENTS)[:8]))
    if init.get("output_style", "default") != "default":
        problems.append(f"output style {init.get('output_style')!r}")
    return problems


def _workspace_snapshot(workspace: Path) -> list[tuple[str, int, int]]:
    out = []
    for path in sorted(workspace.rglob("*")):
        try:
            st = path.lstat()
        except OSError:
            continue
        out.append((path.relative_to(workspace).as_posix(), st.st_size, st.st_mtime_ns))
    return out


def _claude_isolation_probe(prefix: list[str], argv: list[str], workspace: Path, env: dict[str, str], *,
                            read_only: bool) -> list[str]:
    """Start the exact live invocation with a model name Claude Code rejects before any API request, and read what the
    session loaded from its init event. A login's account can sync plugins, MCP connectors and skills into every
    session (observed: a dedicated login carrying shell and mail connectors); the flags should remove them, and this
    checks that they did before the model ever runs. The probe must also provably stop before inference (error result,
    zero cost, no model turn, workspace untouched). Returns reasons to refuse (empty means as requested)."""
    probe = [*prefix, argv[0], "--model", ISOLATION_PROBE_MODEL, *argv[1:]]  # right after the executable
    before = _workspace_snapshot(workspace)
    result = _capture(probe, workspace, env, timeout=60.0, max_timeout=60.0, separate_stderr=True)
    problems: list[str] = []
    if _workspace_snapshot(workspace) != before:
        problems.append("the probe changed the workspace")
    events = []
    for line in result.output.decode("utf-8", "replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    inferred = any(e.get("type") == "assistant" and isinstance(e.get("message"), dict)
                   and e["message"].get("model") != "<synthetic>" for e in events)
    if inferred or final.get("is_error") is not True or final.get("total_cost_usd") not in (0, 0.0):
        problems.append("the probe did not stop before inference (its model name was accepted?)")
    problems += _claude_init_problems(init, read_only=read_only) if init else ["the probe produced no init event"]
    return [f"isolation probe refused the run: {r}" for r in problems]


def _reap_provider_run(run_marker: str | None) -> list[str]:
    """Kill every process the provider run left behind (setsid, double fork, reparented to launchd) before anything
    is verified, so nothing can change the workspace afterwards. Returns why that could not be confirmed."""
    if not run_marker:
        return ["provider run was not tagged for cleanup; its descendants could not be confirmed stopped"]
    from .. import sandbox as _sandbox
    why_not = _sandbox._identification_problem()
    if why_not:
        return [f"provider descendants could not be enumerated ({why_not}); cleanup not confirmed"]
    _, problems = _sandbox._procs.sweep({run_marker}, _sandbox._CONTROL)
    return [f"provider cleanup not confirmed: {p}" for p in problems]


def _claude_preflight(executable: Path, plan: claude_auth.ClaudeAuthPlan) -> tuple[str, list[str]] | None:
    """Refuse a live Claude run that could not authenticate, or whose CLI lacks an isolation flag. No model call:
    only `claude --help`, network-denied, in a scratch HOME."""
    if not plan.usable:
        return "not_authenticated", [f"claude not authenticated for isolated execution: {p}" for p in plan.problems] or [
            "claude not authenticated for isolated execution: set CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) or "
            f"run once: {claude_auth.login_command(claude_auth.default_config_dir())}"]
    with tempfile.TemporaryDirectory(prefix="repo-ai-claude-help-") as directory:
        scratch = Path(directory).resolve()
        for name in ("home", "tmp", "home/.claude"):
            (scratch / name).mkdir()
        prefix = _sandbox_prefix(scratch)
        if prefix is None:
            return "no_sandbox", ["no supported execution sandbox on this host"]
        env = _probe_env(scratch)
        env["PATH"] = os.pathsep.join([*(str(r.parent) for r in _node_roots()), env["PATH"]])
        result = _capture([*prefix, str(executable), "--help"], scratch, env, timeout=20.0, max_timeout=30.0)
    if result.status != "complete" or result.returncode != 0:
        return "help_probe_failed", ["claude --help failed; isolation flags could not be confirmed"]
    missing = claude_auth.missing_flags(result.output.decode("utf-8", "replace"))
    if missing:
        return "unsupported_version", [
            "this Claude Code lacks flags repo-ai's isolated mode requires (" + ", ".join(missing) + "); update Claude Code"]
    return None


def validate_workspace_edits(
    root: Path,
    workspace: Path,
    write_paths: list[str],
    test_files: set[str],
    tracked_files: set[str],
    max_patch: int = 256_000,
) -> list[str]:
    """Validate that a provider adapter modified only approved non-test tracked files without secrets."""
    from ..mission.verification import test_support
    from ..verify import isolate
    from .discovery import _inside as inside_dir

    reasons: list[str] = []
    if inside_dir(workspace.resolve(), root.resolve()):
        return ["candidate workspace is inside root"]

    # Ensure candidate .git/hooks and .repo-ai config were not tampered with
    ws_hooks = workspace / ".git" / "hooks"
    if ws_hooks.exists():
        for hp in ws_hooks.iterdir():
            if not hp.name.endswith(".sample"):
                reasons.append(f"provider installed git hook in workspace: {hp.name}")
    if (workspace / ".repo-ai").exists():
        reasons.append("provider created or modified .repo-ai directory in workspace")

    changed_files: list[str] = []
    for rel in sorted(tracked_files):
        root_target = root / rel
        ws_target = workspace / rel
        if root_target.is_symlink() or ws_target.is_symlink():
            if root_target.is_symlink() != ws_target.is_symlink() or (
                root_target.is_symlink() and os.readlink(root_target) != os.readlink(ws_target)
            ):
                changed_files.append(rel)
                reasons.append(f"provider modified or created symlink at tracked path: {rel}")
            continue
        # a file too large to compare must never read as "unchanged" (None == None): compare digests of full reads
        from ..mission.contracts import MAX_SOURCE_FILE
        try:
            orig = isolate.read_inside(root, rel, MAX_SOURCE_FILE)
        except Exception:
            orig = b"\0unreadable-original\0"
        try:
            cand = isolate.read_inside(workspace, rel, MAX_SOURCE_FILE)
        except Exception:
            cand = b"\0unreadable-candidate\0"
        # `repo-ai init` added its managed block to the working copy only; the workspace holds the committed bytes,
        # so the candidate is held to those (a candidate that copies the working copy has edited the file)
        from ..mission.runtime import committed_if_only_managed_blocks
        committed = committed_if_only_managed_blocks(root, rel)
        if committed is not None:
            orig = committed
        if orig != cand:
            changed_files.append(rel)
            if rel not in write_paths:
                reasons.append(f"provider modified unapproved path: {rel}")
            if rel in test_files or test_support(rel) or Path(rel).suffix not in {".py", ".js", ".mjs", ".cjs", ".ts"}:
                reasons.append(f"provider modified frozen test or support input: {rel}")
            if cand is None or len(cand) > max_patch or b"\x00" in cand:
                reasons.append(f"provider produced nonregular, deleted, binary, or oversized file: {rel}")
            else:
                text = cand.decode("utf-8", "replace")
                if "mission-observation" in text or "rai_result" in text or "rai_reporter" in text:
                    reasons.append(f"provider edit references internal verification reporter in {rel}; refused")
                if source_contains_secret(rel, text):
                    reasons.append(f"provider edit contains secret-shaped material in {rel}; withheld")

    # Also check for any newly created untracked files or symlinks in workspace (excluding .git and .repo-ai-workspace)
    for path in workspace.rglob("*"):
        rel_parts = path.relative_to(workspace).parts
        if rel_parts and (rel_parts[0] in {".git", ".repo-ai"} or rel_parts[0].startswith(".repo-ai")):
            continue
        if path.is_symlink():
            reasons.append(f"provider created symlink in workspace: {path.relative_to(workspace).as_posix()}")
            continue
        if path.is_dir():
            continue
        rel_posix = path.relative_to(workspace).as_posix()
        if rel_posix not in tracked_files:
            reasons.append(f"provider created untracked file outside frozen tracked set: {rel_posix}")

    if not changed_files:
        reasons.append("provider produced a no-op diff; cannot establish a repair")
    return reasons
