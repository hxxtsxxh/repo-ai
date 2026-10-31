---
name: b-skill-15
description: Design consistent RESTful HTTP APIs.
license: MIT
---

# REST API Design

Design predictable, well-documented HTTP APIs.

## Principles

- Nouns for resources, HTTP verbs for actions; plural collection names.
- Use status codes correctly (200/201/204/400/401/403/404/409/422/500).
- Paginate list endpoints; return a stable sort and a cursor or page token.
- Version at the path or header; never break a published contract silently.
- Document request/response schemas and error shapes.

Return consistent error bodies so clients can handle failures uniformly.
