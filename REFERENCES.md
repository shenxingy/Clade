# References & Inspirations

Resources Clade has learned from — design patterns, architectural decisions, and philosophy adopted or adapted from these sources.

---

## [gstack](https://github.com/garrytan/gstack) — Garry Tan / YC

**What it is:** A skill + workflow toolkit that turns Claude Code into a virtual engineering team (ship, qa, review, cso, investigate, retro, and more). Created by the CEO of Y Combinator. MIT licensed.

**Studied:** 2026-03-30

**What we learned:**

| Area | Learning | Applied in Clade |
|------|----------|-----------------|
| Skill structure | Completion Status Protocol — every skill ends with DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT | ✅ DONE — all 26 workflow skills have footer (SK10 verified 2026-04-10) |
| Skill structure | 3-strike rule — after 3 failed attempts, stop and surface to user; don't retry indefinitely | ✅ DONE — `/loop`, `/batch-tasks`, `/investigate` |
| Skill structure | AskUserQuestion 4-part format — re-ground + simplify + recommend (with completeness score) + lettered options with dual effort estimates | `/loop`, `/commit` |
| Debugging | Iron Law — form a root cause hypothesis before writing any fix; scope-lock edits after hypothesis | ✅ DONE — `/investigate` skill (SK5 verified 2026-04-10) |
| Debugging | Blast radius gate — AskUserQuestion if a fix touches >5 files | ✅ DONE — `/investigate` skill |
| Release | `/ship` full pipeline — tests → coverage audit → review → version bump → changelog → PR creation | ⬜ TODO — `/ship` skill not yet built |
| Security | 14-phase security audit: attack surface → secrets → supply chain → OWASP Top 10 → STRIDE → false-positive filter | ✅ DONE — `/cso` skill (SK6 verified 2026-04-10) |
| Observability | `/retro` — weekly engineering retrospective with git metrics, velocity trends, streak tracking | ✅ DONE — `/retro` skill (SK7 verified 2026-04-10) |
| Documentation | `/document-release` — post-ship doc sync: README, CHANGELOG polish, TODOS cleanup | ✅ DONE — `/document-release` skill (SK8 verified 2026-04-10) |
| Learnings | `learnings.jsonl` per project — typed (pattern/pitfall/preference/architecture/tool), confidence-scored, searchable, prunable | ⬜ TODO — `/learn` skill not yet built |
| Routing | Routing rules in CLAUDE.md — natural language phrases auto-route to the right skill | ✅ DONE — Added to global CLAUDE.md |
| Philosophy | "Boil the Lake" — AI compression makes completeness near-free; don't do 70% solutions | ✅ Adopted in skill guidance |
| Philosophy | "Search Before Building" — three layers: tried-and-true → new-and-popular → first principles | ✅ Adopted in skill guidance |
| Philosophy | "User Sovereignty" — AI recommends, user decides; two models agreeing ≠ mandate | ✅ Adopted in skill guidance |
| Browser testing | Persistent Chromium daemon (3s cold start → 100ms warm); accessibility tree refs over CSS selectors; bearer token auth per startup | ⚠ DEFERRED — future phase; use gstack's browse binary in the meantime |

**Key insight:** gstack treats skill prompts as production software — precise step numbering, explicit gate conditions, concrete output formats, enumerated failure modes. Our skills work but are under-specified relative to this standard.

**Detailed research notes:** [`docs/plans/2026-03-30-gstack-learnings.md`](docs/plans/2026-03-30-gstack-learnings.md)

---

## [Claude Code](https://claude.ai/code) — Anthropic

**What it is:** The CLI tool Clade is built on top of. Skills, hooks, slash commands, and the agent framework are all Claude Code primitives.

**Key patterns we use:**
- `PreToolUse` / `PostToolUse` hooks for safety and learning
- `claude -p` subprocess for background worker execution
- `--dangerously-skip-permissions` for unattended autonomous runs
- Session hooks (`SessionStart`) for context injection
- Skills (`.claude/skills/`) for slash command dispatch

---

*Add new entries here as Clade learns from additional sources.*
