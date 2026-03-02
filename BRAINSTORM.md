# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into VISION.md/TODO.md, they're cleared.*

---

## [AI] Session 2026-03-01 — /start, autonomous lifecycle, drift prevention

---

### 1. `/start` — Full Development Lifecycle Skill

**What it is:** A single command that orchestrates the entire dev cycle — find work → plan → execute → verify → commit → document. Replaces the current "manually chain 6 skills" workflow.

**Scenarios:**
- Morning: reads overnight progress, summarizes what happened, suggests next direction, waits for human confirmation
- Overnight (`--overnight`): decides what to do from project state, runs autonomously until convergence or blocker, leaves morning summary
- Targeted (`--goal "X"`): runs for a specific objective, stops when done

**Internal flow:**
```
Read GOALS.md + TODO.md + PROGRESS.md + BRAINSTORM.md
  ├── BRAINSTORM has content? → process it first
  ├── TODO has clear pending items? → plan + execute
  ├── No clear next steps? → /research to find gaps
  └── Current code has issues? → /review first

Loop:
  execute (/loop logic) → /verify → pass? → /commit → /sync
                                   ↓ fail?
                              add fix tasks → continue loop

Stop: converged / iteration budget hit / true blocker
```

**Key design rules:**
- Does NOT run indefinitely — must have exit conditions
- Does NOT change direction autonomously — proposes to BRAINSTORM.md, human decides
- Does NOT stop on recoverable issues (see 3-tier issue handling)
- Reads anchor files (GOALS.md, VISION.md) at the start of every supervisor iteration

---

### 2. `/verify` — Project-Type-Aware Testing Skill

**What it is:** Replaces the narrower "UI testing" idea. Detects project type and applies the right verification strategy. Called by `/start` after each loop convergence.

**Type detection → strategy:**
- Has frontend (`.html` / `.tsx`) → Playwright exploratory testing
- Has API (FastAPI / Express) → httpx/curl smoke test key endpoints
- Has test suite (`tests/` / `*.test.ts`) → run pytest / jest
- CLI tool → run with test inputs, check exit codes + output
- ML pipeline → small-batch sanity run, check output format
- Has `verify command` in CLAUDE.md → just run that

**Exploratory UI testing approach (not fixed selectors):**
- AI reads git diff to know what changed → focuses testing on changed areas
- Tests against behavior descriptions in CLAUDE.md `## Features` section
- Reports: "these behaviors work / these broke / these couldn't verify"

**Behavior anchors:** When a feature first ships, store a description:
```
# Feature: Add Task
- Click Add → input box appears
- Type + Enter → task appears at top of list
- Empty input → no task added
```
`/verify` checks these each run. Behavior changed → flag it.

---

### 3. 3-Tier Issue Handling (Overnight Robustness)

**Problem:** Current "stop on any blocker" is too fragile for 8-hour overnight runs.

| Tier | When | Action | File |
|------|------|--------|------|
| 1 — Uncertainty | Unsure which approach | Pick reversible default, log reasoning | `.claude/decisions.md` |
| 2 — Task failure | Task failed after retries | Skip, log reason | `.claude/skipped.md` |
| 3 — True blocker | Destructive / needs human decision | Stop | `.claude/blockers.md` |

**True blocker = stop:** deleting data, changing core architecture affecting all modules, needs secrets/permissions, mutually exclusive directions with high rollback cost.

**Not a blocker = continue:** uncertain implementation choice, test failure, unclear UI detail, discovered potential issue not affecting current task.

**Morning review flow:** blockers.md (must act) → skipped.md (retry?) → decisions.md (confirm or correct).

---

### 4. File Permission Model (Prevent Direction Drift)

| File | AI Permission | Notes |
|------|--------------|-------|
| `VISION.md` | Read-only | Human only |
| `GOALS.md` | Read-only | Human only |
| `BRAINSTORM.md` | Read + Write | AI proposal inbox |
| `TODO.md` | Read + Write | AI adds/checks tasks |
| `PROGRESS.md` | Read + Write | AI writes lessons |
| `CLAUDE.md` | Conditional | `# FROZEN` sections = immutable |

**Proposal flow:** AI discovers new approach → writes to BRAINSTORM.md with `[AI]` prefix → does NOT edit GOALS.md → human decides in morning review.

**`# FROZEN` in CLAUDE.md:** Marks sections AI cannot modify during autonomous runs (core architecture decisions, security rules, deliberate non-obvious choices).

---

### 5. North Star Clarification

**Real north star:** Human leverage = (effective output) / (human time invested). Target: 3x (24h output from 8h human input). Ultimate: N projects running in parallel while human sleeps.

**Right proxy metric:** Oracle-approved task completions per hour — not commits (measure activity), not tokens (measure cost), not TODO completion (AI-written items, not always touched).

**Human's irreplaceable role:**
1. Setting taste/judgment ("this feels right vs off")
2. Morning direction calibration (10 min: "is this still right?")
3. Resolving true blockers
4. Approving BRAINSTORM proposals before they enter GOALS.md

---

### 6. GUI — Workspace Scheduler (Cross-Project)

**Gap:** Portfolio view shows multiple projects but they're fully independent. No cross-project priority routing or unified morning review.

**Needed:** Workspace-level supervisor that allocates workers across projects by priority + morning summary "here's what happened across all projects, here's what needs your attention." This is a GUI feature — CLI can't hold persistent cross-project state.

---

### 7. CLAUDE.md Template — New Sections

```markdown
## Project Type
- Type: [web-fullstack | api-only | cli | ml-pipeline | library]
- Frontend: [framework + port, or N/A]
- Backend: [framework + port, or N/A]
- Test command: [e.g. pytest tests/ -v]
- Verify command: [e.g. ./scripts/smoke-test.sh, or N/A]

## Features (Behavior Anchors for /verify)
- [Feature]: [expected behavior — what happens when user does X]
```

---

*Process these into VISION.md (new phases) and TODO.md (tasks) when ready.*
