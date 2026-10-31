# Codex token broker: offline feasibility spike (2026-10-31)

Queue item 8 (gate C18). Today repo-ai copies the Codex login's `auth.json` into the run's scratch `CODEX_HOME`.
Codex's model has a shell and the network, so a prompt-injected repository could read the token and send it out
(disclosed on the providers page; a separate, revocable login is the current mitigation).

**Question.** Can the token stay outside the sandbox, with Codex reaching the model only through a loopback proxy
("broker") that adds the credential, so that the sandbox can deny every non-loopback connection?

## What was run ($0, no credential, no external network)

- Codex CLI 0.165.0, scratch `HOME` and `CODEX_HOME` (no `auth.json`), `env -i` with a dummy
  `REPO_AI_BROKER_KEY=dummy-not-a-token`.
- `config.toml`: `model_provider = "broker"` and `[model_providers.broker]` with
  `base_url = "http://127.0.0.1:18765/v1"`, `env_key = "REPO_AI_BROKER_KEY"`, `wire_api = "responses"`, and retries off.
- Seatbelt profile: `(allow default) (deny network-outbound) (allow network-outbound (remote ip "localhost:*"))`.
- A fake server on 127.0.0.1:18765 that logs each request and answers 500.
- `codex exec --skip-git-repo-check --json "say hi"` with stdin closed. Without closing stdin, `codex exec` waits:
  it prints "Reading additional input from stdin...".

## Observed

- One request: `POST /v1/responses`, `Authorization: Bearer dummy-not-a-token`, `originator: codex_exec`, and a
  streaming Responses API body (`"model":"gpt-5-codex","stream":true,"input":[…]`).
- No other connection was attempted that the profile had to deny (Codex ended on the fake 500 with exit code 1).
- Codex printed "Model metadata for `gpt-5-codex` not found", a warning for custom providers, not an error.

## Conclusion

Feasible as far as Codex is concerned: it accepts a loopback provider and sends the dummy key as the bearer token.
A broker outside the sandbox can replace that header, and the Codex sandbox can then be loopback-only, like
OpenCode's. With no token inside the sandbox and no route out, prompt injection would have nothing to steal and no
way to send it.

## Not yet known (needs one live call, owner approval)

1. Whether the ChatGPT-login backend (`https://chatgpt.com/backend-api/codex/responses`, `chatgpt-account-id`)
   accepts the body Codex produces in custom-provider mode. An API-key login (`https://api.openai.com/v1`) is the
   standard Responses API and the lower-risk first target.
2. Token refresh. Codex refreshes ChatGPT tokens itself, but it would no longer hold them. The broker must refresh
   them or refuse an expired token with a clear message; it must never write a refreshed token back into the
   sandbox.
3. The model's shell can call the broker too. That spends quota but cannot read the token. The broker should accept
   only `POST /v1/responses` with the per-run dummy key, and only while the run lasts.

## Built from it (opt-in, still not live-verified)

`providers/codex_broker.py` and `REPO_AI_CODEX_BROKER=1` (macOS seatbelt only). With the flag set:
- No `auth.json` and no `OPENAI_API_KEY` are placed in the sandbox.
- Codex's `config.toml` points at the run's broker.
- Codex's sandbox network is loopback-only, the same rule as OpenCode.

`tests/test_codex_broker.py` checks, offline:
- reading the login: API key, ChatGPT tokens, expiry, links;
- every refusal: key, path, method, size, count, redirect, unreachable upstream;
- streaming the upstream's response back;
- an end-to-end seatbelt run with a fake `codex` and a fake upstream: inside, no token file, no key, no credential
  in the config, and 1.1.1.1 unreachable; the request reached the upstream with the real credential.

The live check (point 1 above) still needs owner approval.
