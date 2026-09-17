---
paths: CLAUDE.md, README.md, docs/**/*.md, configs/CLAUDE.md
---
**Numbers this repository states about itself.**

- **Put the population in the same line as the number.** "89.3%" is not a
  measurement; "89.3% on 21 research terms, 8 synthetic voices, no non-native
  accent" is. A clean figure in a summary with its caveats in a later section has
  already misled someone here.
- **Either derive it or delete it.** Five self-measurements were found
  unreproducible in one pass (`~17%`, `241 commits`, `115 of the last 133`,
  `~94k lines`, `~0.03% of the window`). Run
  `python3 configs/scripts/check-asserted-numbers.py` before adding another.
- **Changing a stated fact means changing every site.** 43% of one audit round's
  findings were siblings of the previous round's own fixes. `grep` for the value
  before you edit it; `check-sibling-facts.py` reports survivors after.
- Never quote a figure from a document's body without reading its **provenance
  header** — one publish took per-term numbers from a file that opens by naming
  the device gap they did not hold across.
