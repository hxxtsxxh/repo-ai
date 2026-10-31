---
name: b-skill-03
description: Write clear Python docstrings and module-level documentation.
license: Apache-2.0
---

# Python Docstrings

Produce consistent, useful docstrings in the Google style.

## Rules

- Every public function, class, and module gets a docstring.
- Summarize in one line, then describe args, returns, and raised exceptions.
- Document units and ranges for numeric parameters.
- Keep examples runnable and short.

## Template

```python
def fetch(url: str, timeout: float = 5.0) -> bytes:
    """Fetch bytes from a URL.

    Args:
        url: Absolute http(s) URL.
        timeout: Seconds before giving up.

    Returns:
        The response body as bytes.

    Raises:
        TimeoutError: If the request exceeds ``timeout``.
    """
```
