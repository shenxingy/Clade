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

## Elite Workflows Study — claude-cookbooks + 5 profiles

**What it is:** Cross-study of [anthropics/claude-cookbooks](https://github.com/anthropics/claude-cookbooks) and five elite practitioners — [Mic92](https://github.com/Mic92) (Jörg Thalheim, NixOS infra), [felixrieseberg](https://github.com/felixrieseberg) (Claude Code Desktop lead), [domdomegg](https://github.com/domdomegg) (Adam Jones, ~172 repos at near-zero marginal cost), [lovesegfault](https://github.com/lovesegfault) (Bernardo Meurer, best public `.claude/` toolkit observed), [controversial](https://github.com/controversial) (Luke Deen Taylor, Claude-authored PRs merged into zed in <4h). Four of the five work at Anthropic.

**Studied:** 2026-06-12. Full ledger: 87 practices → 48 adopted (waves 1+2, ~50 commits `e038bc4..`), 31 parity-confirmed, 26 rejected with reasons (2 original rejections overturned on audit). Research entry + per-item dispositions in [BRAINSTORM.md](BRAINSTORM.md) (archived to `docs/archive/BRAINSTORM-resolved.md` on next cleanup).

**The meta-answer (凭什么又快又好):** quality made machine-checkable collapses review into verification; CI duration is the system's clock speed; default-allow with a surgical deny list; done = merged with green CI and failures route back into the gate, not a human inbox; setup paid once, amortized fleet-wide; small reversible units with evidence attached buy merge speed; every failure debugged at most once (3rd strike → structural fix); AI multiplies output — winners spend the multiplier on depth, not breadth.

| Source | Learning | Applied in Clade |
|------|----------|-----------------|
| cookbooks | Evidence-forcing rubrics, fresh-context graders, eval harnesses gate prompt changes | ✅ oracle rubric `20a6844`, eval harness `fd9d758` (found the fenced-JSON verdict misparse on day one: `6edbbe9`) |
| cookbooks | Search-then-load beats enumerating tool catalogs | ✅ MCP compact mode `82049ce` |
| cookbooks | Inbox piggybacked on tool results = mid-flight steering | ✅ mailbox-drain hook `1468516` |
| Mic92 | Evidence before verdict — reviewer executes the change first | ✅ tests pre-oracle/pre-push `5f17e09`, /review-pr Evidence section `ade1f92` |
| Mic92 | Failed-CI tasks carry the log tail + anti-downgrade guardrails | ✅ `7bd9c88` |
| Mic92 | Cross-vendor second opinions break same-model blind spots | ✅ second-opinion agents `363c65a` |
| felixrieseberg | Invariants compiled into the build, not trusted to prose | ✅ test_conventions.py `65f0515` (1500-line cap, import DAG, no error-text 500s), model-ID single source `53a4c7b` |
| felixrieseberg | Two-tier e2e: mock always, real API behind a key gate | ✅ `--real` tier `dac3c47` |
| felixrieseberg | History carries the payload (mechanism/hazard in bodies) | ✅ commit-body mandate `d79a7a5`, structured PR bodies `16da622` |
| domdomegg | Auto-merge behind the target repo's own CI; label = only human opt-in | ✅ `5eea9e2` (do-not-merge + `gh pr merge --auto`) |
| domdomegg | Repo invariants ensured idempotently at session start | ✅ `bf5ac68` |
| domdomegg | CI must execute what the installer ships | ✅ tests/test-install.sh `37bc47a` (caught a real fresh-install abort same day: `565249a`) |
| lovesegfault | A dead verifier must read as "unreviewed", never "approved" | ✅ oracle liveness `c8d98b5` |
| lovesegfault | Build output stays out of agent context (quiet wrapper) | ✅ quiet-run.sh `6f6770a` |
| lovesegfault | Path-scoped rules load only when touching matching files | ✅ rule-injector hook `c3662b3` |
| lovesegfault | 3rd strike on an invariant → structural close, retire the prose rule | ✅ /audit ESCALATE-TO-STRUCTURAL `f074689` |
| lovesegfault | Frozen schema behind a blessed-regeneration snapshot | ✅ test_schema_frozen.py `d1b8cfb` |
| controversial | Bug-fix without a covering test doesn't pass review | ✅ fix-intent oracle criterion `a8f34b6` |
| controversial | Dependency bugs: repro → upstream patch > pin-with-link, never silent | ✅ /investigate Phase 6b `042976e` |

**Key insight:** Fast AND good is the same multiplier spent twice — once on the artifact, once on the gates that keep it cheap to change. The configuration layer (CLAUDE.md, rules, skills) is the surface; the differentiator is what's NOT prompt files: machine gates, fast CI, templates, and the nerve to invert approval defaults because the gates are real.

---

*Add new entries here as Clade learns from additional sources.*
