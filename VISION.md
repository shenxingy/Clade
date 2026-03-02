# VISION — Claude Code Kit

**North star:** Maximum autonomous hours. Give it a direction — come back later to merged PRs. Human role: define goals + review results. Everything else is automated.

**Core capability:** The system autonomously manages long-running work end-to-end — self-plans, claims tasks, executes, verifies, loops. Overnight is one scenario; the primitive is an unattended session of any length: 2 hours during lunch, 8 hours overnight, a full weekend. The human sets direction and returns when ready — not when the system needs them.

**Works on any project, any phase:** The same primitives apply whether starting from zero or iterating on an existing codebase. Phase 0 (greenfield): /orchestrate reads an empty repo + a brief → plans bootstrap tasks → builds the skeleton. Phase N (ongoing): reads existing code + TODO + PROGRESS → plans the next increment. The system doesn't distinguish — it just reads context and drives forward.

**Dual-source intelligence model:** Good planning requires two inputs — human insight and AI-gathered signals. Both feed the same inbox:
```
Human observations, ideas, direction
                    ↘
                     BRAINSTORM.md  →  deliberate review  →  TODO.md
                    ↗
AI-surfaced findings (competitor research, codebase analysis,
post-loop insights, pattern detection)
```
Neither source auto-creates tasks. BRAINSTORM is a signal inbox, not a task queue. Emptying it is a deliberate act — human + AI jointly review, challenge, and decide what belongs in TODO. Competitive research is one AI signal source: run periodically, findings go to BRAINSTORM, human decides what's worth building.

**Real metric:** Oracle-approved task completions per hour of unattended runtime. Commits measure activity; oracle-approved tasks measure verified progress. Human leverage ratio = effective output / human time invested. Today: ~1.5x. Target: 3x (24h output from 8h human direction-setting).

**Autonomous run length:** How many hours can the system run unattended before needing human input? Today: ~2 hours. Target: sustained (8-16 hours, any time of day).

**Design principles:**
- Every human intervention is a system failure — find the root cause and eliminate it
- Every step a human does manually is a bug — automate it or remove it
- Every step a worker does sequentially instead of in parallel is waste — parallelize it
- Planning quality determines autonomous run length — a good plan prevents 5 interruptions downstream
- The human is a director, not an executor — 6 projects in parallel, all running unattended

---

## Two Pillars

This project has two complementary layers. CLI is the engine, GUI is the cockpit.

### CLI Layer — The Foundation
`configs/` → installed to `~/.claude/` (skills, scripts, hooks, templates)

Works everywhere: SSH, tmux, CI, phone via Tailscale. No server required.
- **Skills**: /commit, /sync, /handoff, /pickup, /orchestrate, /batch-tasks, /loop, /research, /map, /incident, /brief, /review-pr, /merge-pr, /worktree
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
- Settings panel for zero-click autonomous run configuration

GUI wraps CLI primitives — workers use the same committer, same verify commands, same CLAUDE.md injection.

---

## Milestones

| Phase | Name | Summary | Status |
|---|---|---|---|
| 1 | One-Shot Batch | Plan → orchestrate → parallel workers → PRs merged | ✓ DONE |
| 2 | Feedback Loops | Iteration loop, oracle validation, model routing, CLI /loop | ✓ DONE |
| 3 | Autonomous Robustness | Oracle requeue, context budget, AGENTS.md inject, handoff trigger | ✓ DONE |
| 4 | Swarm Intelligence | Shared queue, file ownership, GitHub Issues sync, cross-worker messaging | ✓ DONE |
| 5 | Context Intelligence | Semantic TLDR, intervention replay, dual-condition exit gate | ✓ DONE |
| 6 | Observability & Resilience | Analytics, cost tracking, budget limits, stuck detection, notifications | ✓ DONE |
| 7 | Task Velocity Engine | Hook-enforced commit discipline, HORIZONTAL task decomposition, auto-scaling | ✓ DONE |
| 8 | Closed-Loop Work Generation | Task factories (CI/coverage/deps), GitHub webhooks, specialist presets | ✓ DONE |
| 9 | Meta-Intelligence | Session warm-up, loop auto-PROGRESS, pattern detection, /research + /map + /incident skills | ✓ DONE |
| 10 | Portfolio Mode | Cross-project task routing, system auto-ranks work, human approves not generates | ✓ DONE |
| 11 | Autonomous Lifecycle | /start one-command unattended run (any duration), /verify project-aware testing, 3-tier issue handling, drift prevention | 🔄 NEXT |

See `TODO.md` for detailed task breakdown.

---

## Phase 7 — Task Velocity Engine

打破 1000+ commits/day 的两个根本瓶颈。两个层（CLI/TUI 和 GUI）各自有对应实现。

**The math:**
```
目标: 1000 commits/day ÷ 16小时 = 62 commits/hour
现状: ~5 workers × 2 commits/task × 1 task/hour ≈ 160 commits/day
路径: 10 workers × 6 commits/task × 1 task/hour = 960 ≈ 目标
      ↑ worker数量     ↑ 提交粒度（关键杠杆）
```

**核心洞察：** HORIZONTAL 任务（同一操作 × N 文件）应自动拆成 file-level micro-tasks，每个 micro-task 1 commit。VERTICAL 任务（功能开发/bugfix）保持原粒度，但 hook 层强制 per-step commit。

### 7.1 — Hook Layer（BOTH: CLI & GUI 共享）

- [x] Commit reminder hook — 扩展 `post-edit-check.sh`，≥2 文件未提交时注入提醒
- [x] Commit granularity gate — `verify-task-completed.sh` 统计 commit/file 比率
- [x] CLAUDE.md per-file rule — 全局规则：每改一文件立即提交

### 7.2 — CLI/TUI Velocity（configs/ 层）

- [x] loop-runner.sh HORIZONTAL 模式 — supervisor 上限 20 micro-tasks
- [x] TODO scanner CLI — `scan-todos.sh` 扫描注释 → task file
- [x] tmux dispatcher — `tmux-dispatch.sh` 多 pane 自动分发任务

### 7.3 — GUI Velocity（orchestrator/ 层）

- [x] Task type 字段（HORIZONTAL / VERTICAL / AUTO）+ UI badge
- [x] Horizontal auto-decomposition — haiku 拆文件 → 子任务
- [x] Worker auto-scaling — queue depth 驱动自动扩缩容

---

## Phase 8 — Closed-Loop Work Generation

当前所有任务都靠人工写入。这一 phase 让系统从外部信号自主生成工作议程。**人类角色变为：设定方向 + 验收结果。**

### 8.1 — Task Factories（BOTH: CLI 脚本 + GUI 模块）

- [x] CI failure watcher — 轮询 GitHub Actions，失败时生成 fix task
- [x] Test coverage gap detector — 为低覆盖模块生成测试任务
- [x] Dependency update bot — 检测过期依赖，每包一个 haiku 级任务

### 8.2 — External Triggers（GUI only）

- [x] GitHub webhook endpoint — Issue 标签 / PR 评论 → 自动创建任务

### 8.3 — Specialist Presets（BOTH）

- [x] CLI task templates — `configs/templates/` 专项模板（test-writer, refactor-bot, security-scan）
- [x] GUI preset cards — Task 创建 UI "Quick Presets" 区域
- [x] MCP integration — worker 启动时自动加载项目 `.claude/mcp.json`

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
