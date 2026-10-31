---
name: b-skill-06
description: Perform a security code review covering common web vulnerabilities and secret handling.
license: Apache-2.0
---

# Security Code Review

A checklist-driven review for common application security issues.

## What to check

- Input validation and output encoding (XSS, SQL injection, command injection).
- AuthZ on every endpoint, not just authentication.
- Secrets: confirm nothing sensitive is hard-coded and that `.env` is gitignored and never
  committed. Flag any API key, token, or password that appears in source or logs.
- Dependency risks: known-vulnerable versions, typosquatted names.
- Safe defaults: TLS on, least privilege, no debug mode in production.

## How to report

For each finding, give severity, location, impact, and a concrete fix. Do not modify code
without pointing out the issue first; the goal is to surface risks, not hide them.
