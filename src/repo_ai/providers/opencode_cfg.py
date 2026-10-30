"""OpenCode (`opencode run`) against a local, loopback-only model endpoint: account-free and network-confined.

Observed with OpenCode 2.2.1 on macOS (docs/engineering/INTEGRATIONS.md):

* Tool permissions are allow-by-default and new tools appear between versions (2.2.1 ships an ``execute``
  JavaScript tool absent from the docs). repo-ai therefore injects a deny-by-default policy (``"*": "deny"``) and
  allows only ``read, edit, glob, grep, list`` (only ``read, glob, grep, list`` for read-only roles);
  ``external_directory`` stays denied.
* The repository cannot override that policy: ``OPENCODE_DISABLE_PROJECT_CONFIG=1`` and the whole configuration is
  passed inline (``OPENCODE_CONFIG_CONTENT``); the provider runs with a scratch HOME, so no user config loads.
* Without ``--standalone`` the CLI starts a detached ``opencode serve --service`` that outlives the run; repo-ai
  always passes ``--standalone`` so the server is a child of the bounded process group.
* Only a loopback OpenAI-compatible endpoint is accepted (Ollama, LM Studio, llama.cpp). Code never leaves the
  machine, so the OS sandbox allows network traffic to loopback only. Cloud models (OpenCode's own catalogue or an
  API key) would change the privacy zone and are not supported by this adapter.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Mapping
from urllib.parse import urlsplit

MODEL_ENV = "REPO_AI_OPENCODE_MODEL"
BASE_URL_ENV = "REPO_AI_OPENCODE_BASE_URL"
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
PROVIDER_ID = "repoai-local"
EDIT_TOOLS = ("read", "edit", "glob", "grep", "list")
READ_TOOLS = ("read", "glob", "grep", "list")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def base_url(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    return environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL


def loopback_port(url: str) -> int | None:
    """The port of a loopback http(s) URL, or None if the URL is not loopback-only."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        return None
    if host == "localhost":
        return port
    try:
        return port if ipaddress.ip_address(host).is_loopback else None
    except ValueError:
        return None


def setup_problems(environ: Mapping[str, str] | None = None) -> list[str]:
    environ = os.environ if environ is None else environ
    problems = []
    model = environ.get(MODEL_ENV, "")
    if not model:
        problems.append(f"set {MODEL_ENV} to a model served by a local endpoint (e.g. qwen3:8b with `ollama pull "
                        f"qwen3:8b`); endpoint {base_url(environ)} (override with {BASE_URL_ENV})")
    elif not _MODEL_RE.match(model):
        problems.append(f"{MODEL_ENV} is not a plain model name")
    elif re.search(r"(^|[-:])cloud$", model):
        problems.append(f"{MODEL_ENV} names a cloud-hosted model; code would leave this machine")
    if loopback_port(base_url(environ)) is None:
        problems.append(f"{BASE_URL_ENV} must be a loopback http(s) URL; remote models would send code off this "
                        "machine and are not supported by repo-ai's OpenCode adapter")
    return problems


def config_content(model: str, url: str, *, read_only: bool) -> str:
    allowed = READ_TOOLS if read_only else EDIT_TOOLS
    permission: dict[str, str] = {"*": "deny", **{tool: "allow" for tool in allowed}, "external_directory": "deny"}
    return json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "provider": {PROVIDER_ID: {"npm": "@ai-sdk/openai-compatible", "name": "repo-ai local endpoint",
                                   "options": {"baseURL": url}, "models": {model: {"name": model}}}},
        "model": f"{PROVIDER_ID}/{model}",
        "permission": permission,
    }, sort_keys=True)


def environment(environ: Mapping[str, str] | None = None, *, read_only: bool) -> dict[str, str]:
    """Variables added to the provider's scratch environment. Holds no secret."""
    environ = os.environ if environ is None else environ
    model = environ.get(MODEL_ENV, "")
    return {"OPENCODE_CONFIG_CONTENT": config_content(model, base_url(environ), read_only=read_only),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1"}


def model_ref(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    return f"{PROVIDER_ID}/{environ.get(MODEL_ENV, '')}"


__all__ = ["BASE_URL_ENV", "DEFAULT_BASE_URL", "EDIT_TOOLS", "MODEL_ENV", "PROVIDER_ID", "READ_TOOLS", "base_url",
           "config_content", "environment", "loopback_port", "model_ref", "setup_problems"]
