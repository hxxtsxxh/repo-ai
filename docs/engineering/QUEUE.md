# Work queue (living; top = next)

Updated 2026-10-30. Owner of integration: principal session. Specialists: skills/security (branch
`skills/safe-autopilot`), site/evidence (`site/release-facts`), provider research (read-only).

| # | Item | Gate | State |
|---|---|---|---|
| 1 | Claude isolated provider: auth plan, tool restriction, seatbelt, SETUP_REQUIRED, `agents setup claude` | C03 | **code + tests done**; live journey awaits spend authorization |
| 2 | Claude end-to-end journey (protocol in EXPERIMENTS.md) | C03 | blocked: owner authorization |
| 3 | Provider fabric: ProviderManifest schema + catalog + conformance kit; Tier-1 research results | C04, C05 | research running |
| 4 | Skill network: autonomy policy, five object kinds, CapabilityBundle + host translators, byte-exact rollback | C07–C09 | specialist running |
| 5 | Site: release-facts source of truth, Evidence Lab, provider matrix data file | C19, C01 | specialist running |
| 6 | Claude token refresh inside the sandbox: re-observe after the access token next expires | C03 | waiting on time |
| 7 | Linux bwrap Claude profile: podman check (no live call) | C03, C17 | todo |
| 8 | Verify speed profiling (C16) | C16 | todo |
| 9 | Windows: free public CI now available (public repo) | C17 | todo |
| 10 | Release 0.10.0 when C03 + fabric + skills land; re-verify PyPI/site after publish | C20, C24 | todo |
