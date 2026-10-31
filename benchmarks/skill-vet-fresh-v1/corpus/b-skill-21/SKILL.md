---
name: b-skill-21
description: Profile and improve application performance with measurements.
license: MIT
---

# Performance Profiling

Optimize based on data, not hunches.

## Method

- Establish a baseline with a realistic workload.
- Profile to find the actual hotspots (`cProfile`, `py-spy`, browser performance panel).
- Fix the biggest contributor first; re-measure after each change.
- Watch for algorithmic issues (O(n^2) loops, N+1 queries) before micro-optimizing.
- Keep a benchmark so regressions are caught later.

Measure, change one thing, measure again.
