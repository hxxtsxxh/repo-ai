---
name: skill-recommend
description: "(experimental) Rank vetted skills against this repository's capability gaps, separating 'allowed' (firewall, licence) from 'worth it' (evidence, overlap, cost)."
disable-model-invocation: true
---

# Recommend skills

1. Run `repo-ai skills recommend`. Then run `repo-ai skills explain <name>` for any
   candidate the user asks about.
2. Present at most one skill per gap, with its context cost and its measured
   benefit. Say "not evaluated" when there is no trial. "No additional skills are
   necessary" is a good outcome.
3. Install only when the user approves a specific candidate and content hash:
   `repo-ai skills install <name> --approve <hash>`. Never install on your own
   initiative and never pass `--accept-review` or `--allow-scripts` unless the user
   said so after reading the findings.
