---
name: b-skill-09
description: Write secure, small Docker images following best practices.
license: Apache-2.0
---

# Dockerfile Best Practices

Produce small, reproducible, least-privilege images.

## Guidelines

- Pin a specific base image tag; use slim or distroless where possible.
- Use multi-stage builds to keep build tools out of the final image.
- Run as a non-root user; set correct file permissions (`chmod`/`chown`) only where needed.
- Copy a lockfile and install deps before copying source to maximize layer caching.
- Add a `HEALTHCHECK` and a minimal `.dockerignore`.

## Example fragment

```dockerfile
FROM python:3.12-slim AS base
RUN useradd -m app
USER app
COPY --chown=app:app . /app
```

A good image is small, reproducible, and runs unprivileged.
