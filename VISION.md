# VISION — Claude Code Kit

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

## Milestones

| Phase | Name | Summary |
|---|---|---|
| 1 | One-Shot Batch | Plan → orchestrate → parallel workers → PRs merged |
| 2 | Feedback Loops | Iteration loop, oracle validation, model routing, CLI /loop |
| 3 | Autonomous Robustness | Oracle requeue, context budget, AGENTS.md inject, handoff trigger |
| 4 | Swarm Intelligence | Shared queue, file ownership, GitHub Issues sync, cross-worker messaging |
| 5 | Context Intelligence | Semantic TLDR, intervention replay, dual-condition exit gate |
| 6 | Observability & Resilience | Analytics, cost tracking, budget limits, stuck detection, notifications |

All phases 1–6 complete. See `TODO.md` for detailed implementation status and upcoming work.

---

## The OpenClaw Recipe (reference)

What made 600 commits/day possible:

1. **`committer "msg" file1 file2`** — scoped staging, anti-collision primitive
2. **One worktree per task** — true isolation
3. **AGENTS.md with file ownership** — parallel agents stay in lanes
4. **Ralph loop** — autonomous iteration until goal is met
5. **Self-organizing workers** — workers pull from queue
6. **Oracle second-model review** — independent validation
7. **Model tier routing** — haiku/sonnet/opus by complexity
8. **Context compaction discipline** — workers /compact between subtasks
