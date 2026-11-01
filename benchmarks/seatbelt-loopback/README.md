# What seatbelt's loopback rule allows (queue 13)

`probe.py` runs harmless socket operations under candidate seatbelt profiles on a GitHub macOS runner
(`.github/workflows/diag-seatbelt.yml`, triggered only by `diag/seatbelt-**` pushes). Measurement with controls:
[run 41256165553](https://github.com/hxxtsxxh/repo-ai/actions/runs/41256165553),
[matrix-run-41256165553.json](matrix-run-41256165553.json) (an earlier run without controls:
[matrix-run-41255805325.json](matrix-run-41255805325.json)).

| rules after `(deny network*)` | bind 0.0.0.0 | bind 127.0.0.1 | connect 127.0.0.1 | connect own LAN address | connect gateway | connect 1.1.1.1 |
|---|---|---|---|---|---|---|
| none (control) | denied | denied | denied | denied | denied | denied |
| outbound `localhost` only | denied | denied | ok | ok | denied | denied |
| outbound, inbound and bind `localhost` (OpenCode's rule) | ok | ok | ok | ok | denied | denied |
| outbound and inbound `localhost`, no bind rule | ok | ok | ok | ok | denied | denied |
| as OpenCode's plus `deny bind *` then `allow bind localhost` | ok | ok | ok | ok | denied | denied |
| `127.0.0.1` literal | profile rejected: "host must be * or localhost" | | | | | |

"Denied" is `PermissionError` (EPERM), a sandbox denial, not a refused connection.

**What follows:**
- Filtering is active (the control denies everything), and OpenCode's rule reaches no other host: neither another
  machine on the local network (the gateway) nor the internet.
- `localhost` also matches the machine's own non-loopback address, even in an outbound-only rule: a sandboxed process
  can reach services bound to the host's own addresses. Seatbelt cannot express 127.0.0.1 alone.
- An inbound `localhost` rule permits a wildcard bind (listening on every interface); a deny followed by re-allowing
  `localhost` does not narrow it (other orderings were not tested).
- An outbound-only rule denies all listening. In a separate local check (not part of this CI matrix; 2026-10-31,
  OpenCode 2.2.1, model pointed at the closed port 127.0.0.1:9, no model call), `opencode run --standalone` under
  that rule failed with "Standalone server exited before reporting readiness", consistent with its server being
  unable to listen; its ACP mode likewise fails with all network denied (#45). So OpenCode's rule keeps its inbound
  part, and the residual risk stands.
- Not measured: whether another machine can reach a wildcard listener (the macOS firewall may apply); IPv6.
