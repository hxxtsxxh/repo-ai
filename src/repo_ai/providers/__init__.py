"""Provider capability discovery, CLI contracts, and bounded adapter runtime."""

from .adapters import (
    PROVIDER_CONTRACTS,
    STAGES,
    ProviderContract,
    build_invocation,
    contract_for,
    parse_event_stream,
    run_provider,
    validate_workspace_edits,
)
from .discovery import discover

__all__ = [
    "PROVIDER_CONTRACTS",
    "STAGES",
    "ProviderContract",
    "build_invocation",
    "contract_for",
    "discover",
    "parse_event_stream",
    "run_provider",
    "validate_workspace_edits",
]
