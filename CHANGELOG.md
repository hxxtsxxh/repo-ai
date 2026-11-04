# Changelog

## Unreleased

- Live provider runs on real projects (found by the first real-project Claude sessions, journey-live-v1, C21):
  - A project whose build writes a version file (hatch-vcs / setuptools-scm `version-file`, which git ignores):
    repo-ai copies that file into the candidate itself, then refused the provider's result for "creating" it. A
    copied version file still holding the bytes repo-ai copied in is no longer blamed on the provider; one changed,
    removed or replaced is refused ("provider modified a generated version file").
  - The event capture no longer kills a run that has already spent. It keeps 256 KB (for every provider run,
    simulated ones included); an event line over 32 KB, and once the capture nears its limit any ordinary event (a
    tool result), is replaced by a `repo_ai_truncated` placeholder (counted in the record as `truncated_events`),
    while init, terminal, error and rate-limit events are kept whole, so the result and its cost still arrive.
    Reading stops after 64 x the kept limit. Before, one 150 KB file read, or a dozen medium ones, killed the run
    and lost its cost.
  - Once a started live run's cost is UNKNOWN under a USD ceiling, no budget is left for a further run in that
    mission, and the refusal says why; a run refused before its process started leaves no UNKNOWN cost.
- `repo-ai coverage` lists, per requirement, the changed lines that ran while its own tests ran (pytest missions run
  with a frozen `--requirements` declaration), plus the changed lines run only during undeclared tests and those run
  outside any test (import, collection). The mission's change-exercise measurement records this in a second, slower
  run in the time left (line events re-armed at each test); the first run and its assurance are unchanged, and a
  timeout only leaves the record out (coverage then says why). Each run of a shared (session-, package-, module- or
  class-scoped) fixture's setup is credited to the tests whose call ran with it active (the definitions they
  actually used, what those depend on, and `getfixturevalue`); parametrized and per-class runs stay separate, a
  skipped test gets nothing, and a run no test claimed counts as outside any test. Teardown, threads and child
  processes are not credited to the test they serve, so the mapping is informational: it never changes a row,
  obligation, headline or exit code; a child process (subprocess, multiprocessing, fork) or an early stop (`-x`,
  `--maxfail`) marks it incomplete.
- `verify`'s runtime record now also treats `os.fork`/`os.forkpty` as starting a child process, so a test file whose
  tests fork is never pruned by its recorded runtime evidence (safer, possibly slower). Spawned multiprocessing
  children are detected only in the coverage per-test mode.
- Security (Linux, opt-in): with `REPO_AI_LINUX_EGRESS_PROXY=1`, a live Claude, Codex or Bob run gets its own
  network namespace, so host abstract unix sockets (X11/Xwayland, D-Bus) and services on the host's own network
  namespace, loopback included, are out of reach. Its network goes through a proxy in the repo-ai process: `CONNECT`
  to port 443 by host name, only when every resolved address is public (no loopback, private, link-local,
  site-local, CGNAT or cloud-metadata address, judged on the IPv4 address an IPv6 form embeds), to an address it
  checked and never to an address on this host's interfaces. A forwarder inside the sandbox bridges the sandbox's own
  loopback to the proxy and sets HTTPS_PROXY (NO_PROXY for the sandbox's loopback); the Claude isolation probe goes
  through it too. It needs a system python3 (`/usr/bin/python3` or `/usr/local/bin/python3`): without one, routing
  marks these providers not ready and a run is refused. The record gains `egress_proxy` (connections, hosts,
  refusals). Not closed: any TCP to port 443 of a public host (TLS is not inspected), unix sockets on the filesystem
  outside the hidden directories (e.g. a Nix daemon socket), port-443 services on other public addresses (every
  device on an IPv6 LAN has one), this host's own public address reached through 1:1 NAT (a cloud VM), and a private
  IPv4 address behind an operator-specific NAT64 prefix. A provider that ignores HTTPS_PROXY has no network (fails
  closed; the record says it made no connection); a network that needs an outbound proxy is not supported.
  Verified in CI with curl as the provider; not live-verified with the real CLIs, so it is off by default.

## Unreleased — local 0.9.0.dev0 finalization

- Separate provider JSONL from bounded stderr diagnostics; preserve unknown cost,
  extract Codex agent messages and reject inconsistent live terminal protocols.
- Replace handoff imports with local-store-bound /2 integrity receipts; enforce
  freshness, remaining budget, execution authority and single continuation attempts.
- Validate patches before source writes; journal existing-file apply and provide
  conflict-aware undo. Separate tested candidate assurance from applied assurance.
- Grade the actual selected evaluation patch; correct intentional-edit accounting.
- Disclose provider transmission/host-read surfaces and retained exports; add local
  mission listing and elapsed/provider/observed-cost display.
- Add exact-source validation and upstream replay journey scripts. No comparative
  benefit, production qualification, portable partial handoff or model-team claim.
