# Seatbelt cannot keep a process to 127.0.0.1 only (queue 13)

`probe.py` runs harmless socket operations under candidate seatbelt profiles on a GitHub macOS runner
(`.github/workflows/diag-seatbelt.yml`, triggered only by `diag/seatbelt-**` pushes). Result,
[run 41255805325](https://github.com/hxxtsxxh/repo-ai/actions/runs/41255805325),
[matrix-run-41255805325.json](matrix-run-41255805325.json):

| rules after `(deny network*)` | bind 0.0.0.0 | bind 127.0.0.1 | connect 127.0.0.1 | connect own LAN address |
|---|---|---|---|---|
| `localhost` outbound, inbound and bind (OpenCode's rule) | ok | ok | ok | ok |
| `127.0.0.1` literal | profile rejected: "host must be * or localhost" | | | |
| `localhost` outbound and inbound, no bind rule | ok | ok | ok | ok |
| as above plus `deny network-bind *` then `allow … localhost` | ok | ok | ok | ok |

Seatbelt accepts only `*` or `localhost` as a host, and `localhost` also matches the machine's own interface
addresses; a wildcard bind is not prevented. So the OpenCode provider's "loopback only" network on macOS means: no
other host can be **reached**, but the agent can **listen on every interface** (reachable from the local network) and
connect to services bound to the host's own non-loopback addresses. This is disclosed as a residual risk; it is not
fixable inside seatbelt.
