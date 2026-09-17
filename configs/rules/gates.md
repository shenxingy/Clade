---
paths: configs/scripts/check-*.py, .github/workflows/*.yml, .claude/pre-commit.sh
---
**Before adding a gate, answer the two questions this repo's own research asks.**

1. **Can it be surprised?** A gate informs only when `P(pass|defect) < P(pass|no
   defect)`. If the artifact and the gate come from the same intent-model, an
   error appears in both. Gate value is proportional to **provenance independence
   from the generator**, not to gate count.
2. **What is its measured fire rate on honest work?** A gate that fires on
   double-digit percentages of honest changes trains people to route around it,
   and a gate with a one-flag escape hatch is not a gate.

Mechanics that have actually bitten here:
- The `syntax-check` job **installs no project dependencies**. A gate that imports
  anything from `orchestrator/` dies there while passing locally. Parse with
  `ast.literal_eval`; put anything needing deps in the `pytest` job.
- A new KIND of gate needs its pattern added to `check-ci-checklist.py`'s
  `ARTEFACT_PATTERNS` **and** its entry in CLAUDE.md, in the same commit —
  otherwise the checklist gate is blind to it and reports full coverage.
- Prefer **report-only** with a shrink-only baseline over blocking.
