# Equip Audit: maxsoweski/claude-design-skills

- **Audited:** 2026-08-11 18:33 UTC
- **Ref:** `9e1328c`
- **Audited commit:** `9e1328cf99181710e58a4e73291eb3c34d2552a2`
- **Skills evaluated:** 3
- **Decisions:** 3 ADOPT · 0 NEEDS-REVIEW · 0 SKIP

## How to use this report

Each skill below has a checkbox. **`[x]` = approve for sync, `[ ]` = skip.**
Edit this file to change any decision, then run:
  `/equip sync claude-design-skills --apply`

## ADOPT (safe, or adopt with auto-remediation) (3)

### [x] `muller-brockmann-grid-systems`  — score 10.0/10

**Flags:**
  - ℹ️  **QLT-01**: No references/ dir — less RAG coverage

### [ ] `nyt-data-viz`  — score 10.0/10

**Decision: SKIP (lead review, not the automated score).** Its trigger space
("chart", "dashboard", "data viz", "visualize data") is identical to the
built-in `dataviz` skill already available in every session. Adopting it would
put two skills in competition for the same invocation rather than adding a
capability. Revisit only if the built-in is retired or proves deficient.

**Flags:**
  - ℹ️  **QLT-01**: No references/ dir — less RAG coverage

### [x] `vignelli-canon-design-system`  — score 10.0/10

**Flags:**
  - ℹ️  **QLT-01**: No references/ dir — less RAG coverage

