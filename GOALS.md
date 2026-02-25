# GOALS — Claude Code Kit

**North star:** 1000+ commits/day. You describe what you want; AI delivers overnight. Wake up to merged PRs.

**Design principle:** Every step a human does manually is a bug. Every step a worker does sequentially instead of in parallel is waste.

---

## Two Pillars

This project has two complementary layers. CLI is the engine, GUI is the cockpit.

### CLI Layer — The Foundation
`configs/` → installed to `~/.claude/` (skills, scripts, hooks, templates)

Works everywhere: SSH, tmux, CI, phone via Tailscale. No server required.
- **Skills**: /commit, /sync, /handoff, /pickup, /orchestrate, /batch-tasks, /loop
- **Scripts**: committer.sh, run-tasks.sh, run-tasks-parallel.sh, loop-runner.sh
- **Hooks**: session-context, guardian, lint/verify, correction-detector
- **Templates**: CLAUDE.md, settings.json

CLI strengths: scriptable, composable, safe for self-modification (scripts are external to codebase), works in any environment.
CLI limitations: no real-time visualization, typing-heavy, no mobile dashboard, no one-click phase switching.

### GUI Layer — The Extension
`orchestrator/` (Python FastAPI + vanilla JS web UI)

Adds what CLI can't provide:
- Real-time worker dashboard with status, logs, token bars
- Visual task dependency DAG
- One-click plan/execute mode switching
- Mobile/remote access (Caddy HTTPS)
- Multi-project overview with progress bars
- Iteration loop control with convergence sparklines
- Settings panel for zero-click overnight mode

GUI wraps CLI primitives — workers use the same committer, same verify commands, same CLAUDE.md injection.

---

## Phase 1 — One-Shot Batch ✓ DONE

Plan → orchestrate → tasks auto-import → workers run in parallel → PRs created and merged.

- [x] Split Plan/Execute UI
- [x] Git worktree isolation per worker
- [x] Auto-push + auto-merge pipeline
- [x] SQLite persistence across restarts
- [x] Scheduler for overnight runs
- [x] Task dependency DAG
- [x] Retry with failure context injection
- [x] Scout readiness scoring
- [x] Granular commit injection (committer discipline)

---

## Phase 2 — Feedback Loops ✓ DONE

The output of one batch feeds the next planning step. Autonomous refinement cycles.

- [x] Iteration loop (Ralph-style supervisor) — review mode
- [x] Oracle validation — second model reviews before merge (gates push)
- [x] Model tier auto-routing — haiku/sonnet/opus by scout score
- [x] Broadcast to all workers — inject message into running workers
- [x] Plan/build two-phase loop — PLAN→IMPLEMENTATION_PLAN.md→BUILD
- [x] Multi-project dashboard + settings panel
- [x] Post-merge PROGRESS.md injection (lessons learned)
- [x] CLI loop skill (/loop) — autonomous loop without web UI
- [x] Context budget indicator (file-based, partial)

---

## Phase 3 — Autonomous Robustness ✓ DONE

Close remaining gaps so the system runs overnight without human intervention.

- [x] Oracle rejection → auto-requeue (task re-queued with rejection reason as context)
- [x] Context budget auto-inject (warning field broadcast via WebSocket)
- [x] AGENTS.md auto-prepend to workers (start_worker reads and injects)
- [x] Worker handoff auto-trigger (detect handoff file → create continuation task)
- [x] Two-phase orchestrate (/orchestrate --plan → IMPLEMENTATION_PLAN.md → proposed-tasks.md)
- [x] Loop artifact marking (workers mark goal file items as done)
- [x] Loop --stop + signal handling (SIGTERM/SIGINT graceful shutdown)

---

## Phase 4 — Swarm Intelligence ✓ DONE

N workers operating as a true swarm: shared task pool, self-claiming, no central allocator.

- [x] Swarm mode — workers pull from shared queue, self-schedule
- [x] File ownership enforcement — OWN_FILES/FORBIDDEN_FILES parsed, stored in DB, enforced in verify_and_commit
- [x] GitHub Issues sync — Issues as persistent multi-session task database
- [x] Agent Teams — expose `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- [x] Cross-worker messaging — mailbox pattern for inter-agent communication
- [x] Task hot-path indicator — critical path detection + model tier boost

---

## Phase 5 — Context Intelligence ✓ DONE

Reduce worker failure rate by giving them maximum relevant context at minimum token cost.

- [x] Semantic code TLDR — AST function signatures + JS/TS regex, ~750 tokens vs 5K+ raw
- [x] Intervention recording — replay successful corrections on similar failures
- [x] Dual-condition exit gate — semantic diff hash + change count convergence

---

## Phase 6 — Observability & Resilience ✓ DONE

The system works. Now make it trustworthy at scale: know what happened, what it cost, and recover from failures.

- [x] **Task analytics** — success/failure rate, avg duration, model distribution; collapsible dashboard widget with donut chart
- [x] **Token/cost tracking** — parse claude CLI log for token counts, estimate cost per task, cumulative cost per session
- [x] **Cost budget limit** — max spend per session; auto-pause auto-start when budget hit, manual Run bypasses
- [x] **Stuck worker detection** — log file mtime unchanged for N minutes → kill + requeue (one-shot, no infinite loop)
- [x] **Session state persistence** — survive server restart (mark orphaned tasks as interrupted, one-click retry)
- [x] **Completion notifications** — webhook on run_complete, high_failure_rate, loop_converged

---

## The OpenClaw Recipe (reference)

What made 600 commits/day possible:

1. **`committer "msg" file1 file2`** — scoped staging, anti-collision primitive ✓
2. **One worktree per task** — true isolation ✓
3. **AGENTS.md with file ownership** — parallel agents stay in lanes ✓
4. **Ralph loop** — autonomous iteration until goal is met ✓
5. **Self-organizing workers** — workers pull from queue ✓
6. **Oracle second-model review** — independent validation ✓
7. **Model tier routing** — haiku/sonnet/opus by complexity ✓
8. **Context compaction discipline** — workers /compact between subtasks ✓
