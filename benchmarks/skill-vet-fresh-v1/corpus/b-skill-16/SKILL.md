---
name: b-skill-16
description: Add structured application logging that is useful and privacy-conscious.
license: MIT
---

# Logging Best Practices

Logs that help you debug without leaking sensitive data.

## Guidelines

- Use structured logs (key/value or JSON) with a consistent schema.
- Include a request/correlation ID to trace a request across services.
- Choose levels deliberately: DEBUG for diagnostics, INFO for lifecycle, WARN/ERROR for problems.
- Never log secrets, full tokens, or PII; redact before logging.
- Keep logs local or send them only to your own observability stack.

Good logs tell a story; noisy logs hide the one line that matters.
