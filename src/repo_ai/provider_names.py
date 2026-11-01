"""The execution providers repo-ai knows by name, importable without loading the provider runtime.

Argument parsing needs these names on every command (including agent hooks); `repo_ai.providers` re-exports them
from `providers.discovery`, which also loads every adapter."""
from __future__ import annotations

PROVIDERS = ("codex", "claude", "gemini", "bob", "agy", "opencode", "opencode-acp")
