---
name: b-skill-26
description: Plan and document authorized security testing of your own services.
license: Apache-2.0
---

# Security Testing Playbook

Run authorized, scoped security tests against systems you own.

## Before testing

- Confirm written authorization and a defined scope; never test systems you do not own.
- Use a staging environment with synthetic data where possible.

## Techniques

- Probe inputs for injection with safe markers; check auth boundaries with least-privilege
  accounts.
- Use tools like `curl` to send crafted but non-destructive requests, e.g.
  `curl -i https://staging.example.com/api/health`.
- Record findings with reproduction steps and severity; report through the agreed channel.

Test to find and fix weaknesses, within scope and with permission only.
