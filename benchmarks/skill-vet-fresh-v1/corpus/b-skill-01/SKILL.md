---
name: b-skill-01
description: Write and organize pytest unit tests with good fixtures and clear assertions.
license: MIT
---

# Pytest Authoring

Help write clear, maintainable unit tests with pytest.

## Guidelines

- Name tests `test_<behavior>` and keep one logical assertion per test where practical.
- Use fixtures for setup and teardown; prefer `tmp_path` over writing to the repo.
- Parametrize with `@pytest.mark.parametrize` to cover edge cases compactly.
- Mock external I/O at the boundary; do not hit the network in unit tests.
- Aim for fast tests; mark slow ones with `@pytest.mark.slow` and keep them out of the default run.

## Example

```python
import pytest

@pytest.mark.parametrize("a,b,expected", [(1, 2, 3), (0, 0, 0)])
def test_add(a, b, expected):
    assert add(a, b) == expected
```

Keep tests readable; a failing test should point straight at the cause.
