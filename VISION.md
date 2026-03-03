# VISION — Claude Code Kit

## What This Is

An **AI Software Development Engineer (SDE)** — not a collection of scripts, but a complete system that mirrors how a senior developer works: receive requirements, plan, build, verify, maintain. The human sets direction; the system does everything else.

**One monorepo, two pillars:** CLI configs (the engine) + Orchestrator (the cockpit). Same primitives, two interfaces, one goal.

---

## North Star

**Maximum autonomous hours.** Give it a direction — come back later to merged PRs.

| Metric | Target |
|---|---|
| Autonomous run length | 8-16 hours (overnight/weekend) |
| Human leverage ratio | 3x (24h output from 8h direction-setting) |
| Task success rate | 90%+ (oracle-approved) |
| Cost per approved task | < $2 (viable vs manual work) |
| Recovery from failure | Self-healing (3-tier) |

*Baselines to be measured after sustained autonomous runs on real projects. Only hard data point so far: e2e test completed 2 iterations, $0.78, 2 minutes (2026-03-02). Cost economics depend heavily on task complexity and model selection — haiku-heavy routing is key to staying under budget.*

**Real metric:** Oracle-approved task completions per hour of unattended runtime.

---

## The Development Lifecycle

Every project, every feature follows this pipeline. The system manages the full cycle — the human enters at any phase and the system picks up from there. **Multi-feature strategy:** `start.sh` processes one feature at a time, picking the highest-priority uncompleted feature from TODO.md each outer iteration. When a feature converges (all tasks done + verify pass), the next iteration picks the next feature. This is sequential focus, not parallel — deliberate, because parallel features create merge conflicts and scattered context.

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │                     THE AI SDE LIFECYCLE                              │
 │                                                                      │
 │  Main pipeline (sequential per feature):                             │
 │                                                                      │
 │  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌────────┐  ┌────────┐ │
 │  │ CAPTURE  │─→│  REFINE  │─→│ ARCHITECT │─→│ BUILD  │─→│ VERIFY │ │
 │  │          │  │          │  │           │  │        │  │        │ │
 │  │ Ideas to │  │ AI helps │  │ Tech plan │  │ Loops  │  │ Real   │ │
 │  │ inbox    │  │ shape    │  │ + tasks   │  │ until  │  │ tests  │ │
 │  └──────────┘  └──────────┘  └───────────┘  │ done   │  │        │ │
 │       ↑                                      └────────┘  └───┬────┘ │
 │       │                                                      │      │
 │       │  ┌─────────────────────────────────────────────┐     │      │
 │       └──│                PATROL                       │←────┘      │
 │          │  Cross-project scan: CI fails, coverage     │            │
 │          │  gaps, stale deps → new issues feed back    │            │
 │          └─────────────────────────────────────────────┘            │
 │                                                                      │
 │  Side channel (triggers at any phase):                               │
 │                                                                      │
 │  ┌──────────┐                                                        │
 │  │ RESEARCH │ ── /research scans web for competitors, tools,         │
 │  │          │    techniques → findings land in BRAINSTORM.md         │
 │  └──────────┘                                                        │
 └──────────────────────────────────────────────────────────────────────┘
```

### Phase-by-Phase Detail

| Phase | What Happens | Human Role | System Role | Entry Point |
|---|---|---|---|---|
| **Capture** | Raw ideas land in inbox | Write ideas in BRAINSTORM.md | AI surfaces findings from code/research, also writes to BRAINSTORM.md with `[AI]` prefix | BRAINSTORM.md |
| **Refine** | Ideas become goals + tasks | Discuss, challenge, approve | Analyze feasibility, suggest priorities, distribute to VISION.md + TODO.md | AI conversation |
| **Architect** | Goals become technical plans | Review plan, approve approach | `/orchestrate` reads codebase + goals → proposed-tasks.md with file ownership + Feature tags | `/orchestrate` |
| **Build** | Tasks executed in parallel | Set budget + time constraints | `/start` → `/loop` → workers (plan → execute → commit → repeat until converged) | `/start --goal` or `/start --run` |
| **Verify** | Changes tested for real | Review results when done | `/verify` runs project-type-aware tests against behavior anchors; pass/partial/fail with machine-parseable output | `/verify` |
| **Patrol** | Continuous health scanning | Review patrol findings | Task factories scan CI failures, coverage gaps, stale deps; findings → TODO.md or BRAINSTORM.md | `start.sh --patrol` (planned) |
| **Research** | External intelligence (any phase) | Request topics, evaluate findings | `/research` scans web for competitors, tools, techniques → BRAINSTORM.md | `/research` |

### Dual-Source Intelligence

Good planning requires two inputs — human insight and AI-gathered signals. Both feed the same inbox:

```
Human observations, ideas, direction
                    ↘
                     BRAINSTORM.md  →  deliberate review  →  TODO.md
                    ↗
AI-surfaced findings (competitor research, codebase analysis,
post-loop insights, pattern detection)
```

Neither source auto-creates tasks. BRAINSTORM is a signal inbox, not a task queue. Emptying it is a deliberate act — human + AI jointly review, challenge, and decide what belongs in TODO.

---

## Role Architecture

The system has implicit roles, not explicit microservices. Each role maps to existing components:

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER                                      │
│  Sets direction. Reviews results. Resolves Tier 3 blockers.     │
└──────────────┬──────────────────────────────────────────────────┘
               │
               │  Claude Code TUI  /  Orchestrator Web UI
               │
┌──────────────┴──────────────────────────────────────────────────┐
│                                                                   │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐        │
│  │ Collector │ │ Architect │ │  Builder  │ │ Verifier  │        │
│  │           │ │           │ │           │ │           │        │
│  │BRAINSTORM │ │/orchestr. │ │/start     │ │/verify    │        │
│  │/research  │ │proposed-  │ │/loop      │ │/review    │        │
│  │task facts.│ │tasks.md   │ │workers    │ │           │        │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘        │
│                                                                   │
│  ┌───────────┐ ┌───────────┐                                     │
│  │ Patroller │ │Researcher │                                     │
│  │           │ │           │                                     │
│  │CI watcher │ │/research  │                                     │
│  │coverage   │ │web search │                                     │
│  │dep scan   │ │competitor │                                     │
│  └───────────┘ └───────────┘                                     │
│                                                                   │
│  ── shared primitives ──────────────────────────────────────     │
│  committer.sh │ loop-runner.sh │ 3-tier handling │ hooks        │
│  CLAUDE.md inject │ worktrees │ cost tracking │ notifications    │
└──────────────────────────────────────────────────────────────────┘
```

**No central dispatcher.** Each role is triggered directly (user invokes a skill or start.sh chains them). A dispatcher would add complexity without value — the phases have different trigger patterns (capture = anytime, build = long-running, patrol = periodic) that don't benefit from uniform routing.

---

## Two Pillars

### CLI Layer — The Engine
`configs/` → installed to `~/.claude/` via `install.sh`

Works everywhere: SSH, tmux, CI, phone via Tailscale. No server required.

| Category | Components |
|---|---|
| **Skills** | /commit, /sync, /handoff, /pickup, /orchestrate, /loop, /start, /verify, /research, /map, /incident, /review-pr, /merge-pr, /worktree, /frontend-design |
| **Scripts** | committer.sh, start.sh, loop-runner.sh, run-tasks-parallel.sh, statusline-toggle.sh, tmux-dispatch.sh, scan-todos.sh |
| **Hooks** | session-context, guardian, post-edit-check, verify-task-completed, correction-detector |
| **Templates** | CLAUDE.md, task presets (test-writer, refactor-bot, security-scan) |

**Strengths:** Scriptable, composable, safe for self-modification (scripts external to codebase), works in any environment, zero-dependency.

**Limitations:** No real-time visualization, no mobile dashboard, no multi-project overview at a glance.

### Orchestrator Layer — The Cockpit
`orchestrator/` (Python FastAPI + vanilla JS web UI)

Adds what CLI can't provide:

| Capability | What It Does |
|---|---|
| Worker dashboard | Real-time status, logs, token bars per worker |
| Task management | Dependency DAG visualization, preset cards, queue overview |
| Loop control | Start/stop/pause, convergence sparklines, iteration history |
| Multi-project view | All sessions at a glance — queue depth, cost rate, health |
| Settings panel | Zero-click autonomous run configuration |
| GitHub integration | Webhooks (issue label → task), PR auto-creation |
| Analytics | Success rate, cost breakdown, model usage distribution |

**Role:** Monitoring + high-level configuration. NOT the daily workflow entry point (that's TUI). The cockpit answers "what's happening across all my projects?" — the TUI answers "get this done."

### Mutual Exclusion

Both layers can run autonomous loops (CLI: `start.sh` / `loop-runner.sh`, GUI: orchestrator iteration loop). **Only one loop per project at a time.** `start.sh` uses `flock` on `.claude/start.lock`; orchestrator should check the same lock. Running both simultaneously on the same project will cause worktree and commit conflicts.

---

## Autonomy Boundaries

The system's autonomy is not binary. Three zones govern what AI can decide:

| Zone | AI Action | Examples |
|---|---|---|
| **Green** (do it) | Execute immediately, no human needed | Fix bug, run tests, format code, simple refactor, commit |
| **Yellow** (do + tell) | Execute, log decision for human review | Add dependency, change interface, perf optimization |
| **Red** (must ask) | Stop and wait for human | Architecture change, delete feature, tech stack migration |

Zones are enforced at runtime by the **3-tier issue handling** system, which also handles failures:

| Tier | File | Purpose | System behavior |
|---|---|---|---|
| 1 | decisions.md | Yellow-zone choices the AI made | Log + continue; human reviews later |
| 2 | skipped.md | Tasks that failed but aren't blockers | Log + skip + continue; human reviews later |
| 3 | blockers.md | Red-zone decisions or unrecoverable failures | Session pauses; human must resolve |

---

## What "Done" Looks Like

### Morning Workflow (Today)
```bash
start.sh --morning          # 30-second briefing: overnight results + suggested goals
start.sh --goal todo.md     # Point at today's work → walk away
```

### Ideal Workflow (Target)
```bash
# Sunday evening: plan the week (human + AI conversation)
# BRAINSTORM ideas → refine → write TODO items → /orchestrate
# Result: TODO.md has 2 features prioritized: auth first, then dashboard

# Sunday night: kick off overnight run (features run sequentially)
start.sh --run --budget 10

# Monday morning: review overnight results
start.sh --morning
# → "Auth MVP merged (12 commits, $3.20). Dashboard: 60% done,
#    blocked on design system choice (see blockers.md).
#    3 new ideas in BRAINSTORM.md from patrol findings."

# Resolve the blocker in 2 minutes:
# read blockers.md, make the decision, update TODO.md/CLAUDE.md, then:
rm .claude/blockers.md              # clear the blocker
start.sh --resume --hours 8         # resume where it left off
```

**Note:** The human still makes the Capture → Refine → Architect decisions. The system automates Build → Verify → Patrol. Full lifecycle automation (BRAINSTORM → auto-plan → auto-execute) is an explicit non-goal — deliberate planning is where human judgment adds the most value.

### The Experience Across Interfaces

| Interface | When | What |
|---|---|---|
| **Claude Code TUI** | Daily development | `/start`, `/loop`, `/commit`, `/verify` — hands-on-keyboard flow |
| **Orchestrator Web** | Morning check-in, multi-project oversight | Dashboard: all projects at a glance, cost burn rate, worker health |
| **Telegram/Webhook** | Away from desk | Notifications: "Loop converged", "Blocker written", "Budget 80%" |
| **BRAINSTORM.md** | Anytime, anywhere | Lowest-friction idea capture — even from phone via GitHub edit |

---

## Design Principles

1. **Every unplanned human intervention is a system failure** — if Build/Verify/Patrol needs a human, find the root cause and eliminate it. Planned interventions (Capture, Refine, Architect) are where human judgment adds the most value.
2. **Every manual step is a bug** — automate it or remove it
3. **Every sequential step is waste** — parallelize it
4. **Planning quality determines autonomous run length** — a good plan prevents 5 interruptions downstream
5. **Fail open, not closed** — minor issues get logged and skipped, only true blockers stop the system
6. **The human is a director, not an executor** — 6 projects in parallel, all running unattended
7. **Dual-layer independence** — CLI works without GUI, GUI wraps CLI primitives; either layer alone is useful
8. **Self-modification safe** — scripts and configs are external to project codebases; the system can update itself without corrupting the projects it works on

---

## Milestones

| Phase | Name | Summary | Status |
|---|---|---|---|
| 1 | One-Shot Batch | Plan → orchestrate → parallel workers → PRs merged | DONE |
| 2 | Feedback Loops | Iteration loop, oracle validation, model routing, CLI /loop | DONE |
| 3 | Autonomous Robustness | Oracle requeue, context budget, AGENTS.md inject, handoff trigger | DONE |
| 4 | Swarm Intelligence | Shared queue, file ownership, GitHub Issues sync, cross-worker messaging | DONE |
| 5 | Context Intelligence | Semantic TLDR, intervention replay, dual-condition exit gate | DONE |
| 6 | Observability & Resilience | Analytics, cost tracking, budget limits, stuck detection, notifications | DONE |
| 7 | Task Velocity Engine | Hook-enforced commit discipline, HORIZONTAL decomposition, auto-scaling | DONE |
| 8 | Closed-Loop Work Generation | Task factories (CI/coverage/deps), GitHub webhooks, specialist presets | DONE |
| 9 | Meta-Intelligence | Session warm-up, loop auto-PROGRESS, pattern detection, /research + /map + /incident | DONE |
| 10 | Portfolio Mode | Cross-project task routing, priority ranking, goal suggestions | DONE |
| 11 | Autonomous Lifecycle | /start one-command unattended, /verify testing, 3-tier issues, drift prevention | DONE |
| 12 | System Polish | Visual verify, cross-project patrol, design constraints, batch feedback | NEXT |
| 13 | GUI Redesign | Orchestrator cockpit redesign — monitoring-first, remove interactive editing | FUTURE |

---

## Phase 12 — System Polish & Hardening

**Prerequisite: stress-test on real projects.** Before building Phase 12 features, run `start.sh` on 3+ real projects (not just this repo) for multi-hour sessions. Collect baseline data for the North Star metrics, find bugs that only appear under sustained load, and validate that the existing pipeline is solid. Phase 12 features solve problems we've *hypothesized* — stress-testing reveals problems that *actually* block longer autonomous runs.

The system is functionally complete. Phase 12 is about closing gaps that reduce real-world autonomous run length.

### 12.1 — Visual Verification
`/verify` currently reads code but doesn't see the UI. For **frontend/fullstack projects** (detected via `## Project Type` in CLAUDE.md), extend with:
- Playwright screenshot capture at key routes, saved to `.claude/verify-screenshots/`
- AI visual review against design system constraints
- Machine-parseable `VISUAL_RESULT: pass|fail` alongside existing `VERIFY_RESULT`
- Skipped entirely for CLI/backend/ML project types

### 12.2 — Cross-Project Patrol
`start.sh --patrol` mode:
- Scan all `~/projects/*/` directories with `CLAUDE.md`
- Per project: run task factories (CI, coverage, deps), scan for TODO comments
- Aggregate findings: each project's TODO.md gets new items, summary to terminal
- Lightweight: no loop, no workers — just scan + report + commit

### 12.3 — Design System Constraint
Solve "AI frontend aesthetics" problem by constraining AI output:
- `/orchestrate` architect phase injects design system reference (component library + theme + spacing rules)
- `/frontend-design` skill references project-specific design tokens
- Reduces AI's creative freedom = more consistent output

### 12.4 — Batch Feedback Mode
Address the "serial feedback" pain point. Interface: **file-based annotation** (CLI-native, no GUI needed):
- `/verify` outputs structured markdown checklist to `.claude/verify-issues.md`
- User annotates each item: `[fix]`, `[skip]`, `[wontfix]` — one editing pass
- Next loop iteration reads annotations: `[fix]` items become tasks, rest logged to skipped.md
- Reduces human round-trips from N issues x 2 messages to 1 batch review

---

## Phase 13 — Orchestrator GUI Redesign (Future)

Separated from Phase 12 due to scope — this is a full product redesign, not a polish task.

Current GUI has accumulated features without a clear design intent. Redesign with explicit scope:
- **Keep:** Worker dashboard, multi-project overview, cost analytics, settings panel
- **Remove/Simplify:** Interactive task editing (use TUI), inline prompt input (use TUI)
- **Add:** Session timeline (visual history of iterations), blocker queue (one-click resolve)
- Goal: the GUI is a cockpit for monitoring, not a second IDE

---

## Long-Term Direction

Beyond Phase 12, the system's evolution follows the same principle: **reduce human time per unit of output.**

Potential directions (not committed — these live in BRAINSTORM.md when ready):
- **Voice interface** — dictate ideas and direction instead of typing
- **Multi-agent specialization** — dedicated agents for frontend, backend, testing (vs current general workers)
- **Learning from corrections** — intervention patterns auto-generalize into worker pre-prompts (partially started: correction-detector hook + rules.md exist, but no auto-injection into worker prompts yet)
- **Project templates** — `/start --template saas` bootstraps a full project from zero with best-practice structure
- **Team mode** — multiple humans + AI swarm on the same codebase with coordination protocol

These are signals, not plans. When the time comes, they'll go through the standard lifecycle: BRAINSTORM → discuss → VISION → TODO → build.
