# Shell script pre-flight checklist

- [ ] `set -euo pipefail` at the top
- [ ] All variables quoted
- [ ] External commands checked for existence
- [ ] Downloads verified against a checksum, never piped to `sh`
- [ ] Temp files created with `mktemp` and cleaned up via `trap`
- [ ] Usage/`--help` text present
