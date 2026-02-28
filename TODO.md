# TODO — Claude Code Kit

> Vision and architecture: see [VISION.md](VISION.md)

Phases 1–9 substantially complete. Phase 10 (Portfolio Mode) is next.

---

## Phase 3 — Autonomous Robustness

### Server-side (orchestrator/server.py)

- [x] **Oracle rejection → auto-requeue** — after oracle rejects + `git reset HEAD~1`, call `task_queue.add(original_desc + rejection_reason)` and start a new worker
  - Location: `verify_and_commit()` oracle rejection block
- [x] **Context budget auto-inject** — `context_warning` bool in worker to_dict() for UI badge; workers use `claude -p` (non-interactive) so stdin injection not possible without architecture change
  - File-based warning still written; `context_warning` field broadcast via WebSocket
- [x] **AGENTS.md auto-prepend** — in `start_worker()`, if `.claude/AGENTS.md` exists in project dir, prepend alongside CLAUDE.md injection
  - Endpoint already generates it (`GET /agents-md`); missing: auto-inject on worker spawn
- [x] **Worker handoff auto-trigger** — in `_on_worker_done()`, check for `.claude/handoff-{task_id}.md`; if exists, create continuation task with `/pickup` + original description

### CLI-side (configs/skills/, configs/scripts/)

- [x] **Two-phase orchestrate** (`/orchestrate --plan`) — Phase 1: codebase analysis → `IMPLEMENTATION_PLAN.md`, Phase 2: plan → `proposed-tasks.md` with `OWN_FILES`/`FORBIDDEN_FILES`
- [x] **Loop artifact marking** — instruct workers to mark `- [ ]` → `- [x]` in goal file on completion (enforce via supervisor prompt)
- [x] **Loop `--stop`** — write STOP sentinel to state file; loop-runner checks before each iteration
- [x] **Loop signal handling** — trap SIGTERM/SIGINT in loop-runner.sh for graceful shutdown

---

## Phase 4 — Swarm Intelligence

- [x] Swarm mode — N workers self-claim from shared queue (no central allocator)
- [x] File ownership enforcement — OWN_FILES/FORBIDDEN_FILES parsed from proposed-tasks.md, stored in DB, enforced in verify_and_commit, violation → requeue
- [x] GitHub Issues sync — Issues as persistent task database (survives machine restarts, editable from phone)
- [x] Agent Teams — expose `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- [x] Cross-worker messaging — mailbox pattern
- [x] Task hot-path / critical path indicator + model tier boost for critical-path tasks

---

## Phase 5 — Context Intelligence

- [x] Semantic code TLDR — AST function signatures + JS/TS regex extraction at ~750 tokens vs raw 5K+ file paths
- [x] Intervention recording — replay successful /message corrections on similar failures
- [x] Dual-condition exit gate — semantic diff hash + change count (not just counting)

---

## Phase 6 — Observability & Resilience (DONE)

- [x] **Task analytics** — success/failure rate, avg duration per model, distribution chart; new dashboard widget
  - Endpoint: `GET /api/sessions/{session_id}/analytics`
  - UI: collapsible stats card with donut chart (haiku/sonnet/opus colors)
- [x] **Token/cost tracking** — parse `claude -p` log for token usage, store in tasks table
  - New columns: `input_tokens`, `output_tokens`, `estimated_cost`
  - Parsed in `_on_worker_done()`, persisted in `poll_all()`
  - UI: cost per worker card, session total in footer
- [x] **Cost budget limit** — max spend per session; auto-pause workers when budget exceeded
  - New setting: `cost_budget` (default: 0 = unlimited)
  - Check in `status_loop()` before auto-start; manual "Run" bypasses
  - UI: budget input in settings, toast + red footer on exceed
- [x] **Stuck worker detection** — log file mtime unchanged for N minutes → kill + requeue
  - Check in `poll_all()`: `log_path.stat().st_mtime` vs threshold
  - New setting: `stuck_timeout_minutes` (default: 15)
  - One-shot retry with `[STUCK-RETRY]` prefix (no infinite loop)
- [x] **Session state persistence** — survive server restart
  - `_recover_orphaned_tasks()` marks running/starting → interrupted
  - Called on startup, create_session, switch_project
  - `POST /api/tasks/{task_id}/retry` resets to pending
  - UI: interrupted badge (orange) + retry button in history
- [x] **Completion notifications** — webhook when batch/loop finishes
  - New setting: `notification_webhook` (URL)
  - Fires on: run_complete, high_failure_rate, loop_converged
  - curl-based, fail-open, no new deps

---

## Phase 7 — Task Velocity Engine

---

### 7.1 Hook Layer — BOTH（代码级强制，任何 claude session 受益）

- [x] **Commit reminder hook** — `configs/hooks/post-edit-check.sh` ✓ (loop 2026-02-27)

- [x] **Commit granularity gate** — `configs/hooks/verify-task-completed.sh` ✓ (loop 2026-02-27)

- [x] **CLAUDE.md per-file rule** — `configs/templates/CLAUDE.md` ✓ (loop 2026-02-27)

---

### 7.2 CLI/TUI Velocity — configs/ 层（bash 实现）

- [x] **loop-runner.sh HORIZONTAL 模式** ✓ (loop 2026-02-27)

- [x] **TODO scanner CLI** — `configs/scripts/scan-todos.sh` ✓ (loop 2026-02-27)

- [x] **tmux dispatcher** — `configs/scripts/tmux-dispatch.sh` ✓ (loop 2026-02-27)

---

### 7.3 GUI Velocity — orchestrator/ 层（Python 实现）

- [x] **Task type 字段** — DB + 解析 + UI badge
  - `orchestrator/server.py`：`tasks` 表 ALTER 加 `task_type TEXT DEFAULT 'AUTO'`
  - 解析 `proposed-tasks.md` 中 `TYPE: HORIZONTAL|VERTICAL` 字段，写入 DB
  - 前端：worker card 显示 `H`（橙）/ `V`（蓝）/ `A`（灰）badge
  - `/orchestrate` skill 生成的 `proposed-tasks.md` 格式中加 `TYPE:` 字段（改 skill prompt）

- [x] **Horizontal auto-decomposition** — `orchestrator/server.py`
  - `start_worker()` 前：`if task.task_type == 'HORIZONTAL'` → 调用 `_decompose_horizontal(task)`
  - `_decompose_horizontal`：用 claude haiku 列出受影响文件列表 → 每个文件创建子任务
  - 子任务描述：`[file: {path}] {原始任务描述}`，`parent_task_id` 字段记录父任务
  - 父任务状态改为 `grouped`，所有子任务完成后父任务自动 complete

- [x] **Worker auto-scaling** — `orchestrator/server.py` + 前端设置
  - `status_loop()` 加逻辑：`pending_count > running_count * 2` → `_start_worker()`（最多到 `max_workers`）
  - 新 settings（`orchestrator/settings.json`）：
    - `auto_scale: bool = false`
    - `min_workers: int = 1`
    - `max_workers: int = 8`
  - 前端 Settings 面板：Auto-Scale 开关 + min/max 数字输入
  - 防止 spawn storm：每次 spawn 后冷却 30s 才检查下一次

---

## Phase 9 — Meta-Intelligence (TUI/CLI Layer)

Goal: maximize autonomous run hours. Minimize human intervention. System knows where it is, learns from patterns, notifies when done.

### 9.1 Smart Session Warm-up
- [x] **session-context.sh: loop-state + next TODO** ✓ (loop 2026-02-27)

### 9.2 Loop Intelligence
- [x] **loop-runner.sh: auto-PROGRESS on convergence** ✓ (loop 2026-02-27)
- [x] **loop-runner.sh: notify-telegram on convergence** ✓ (loop 2026-02-27)
- [x] **loop-runner.sh: HORIZONTAL mode** ✓ (loop 2026-02-27)
- [x] **loop-runner.sh: --exit-gate flag** ✓ (loop 2026-02-27)

### 9.3 Commit Quality
- [x] **verify-task-completed.sh: commit granularity stats** ✓ (loop 2026-02-27)

### 9.4 Kit Completeness
- [x] **Copy review-pr, merge-pr, worktree skills to configs/skills/** ✓ (loop 2026-02-27)

### 9.5 Research Skill
- [x] **`/research` skill** ✓ (loop 2026-02-27)

### 9.6 Pattern Intelligence & Self-Improvement
- [x] **`/map` skill** ✓ (loop 2026-02-27)
- [x] **Prompt fingerprint tracker** ✓ (loop 2026-02-27)
- [x] **`/incident` skill** ✓ (loop 2026-02-27)

- [x] **Value tracking** — extend `.claude/stats.jsonl` with revert detection
  - `configs/hooks/session-context.sh`: on startup, count `git log --oneline --grep="Revert"` in last 7 days
  - If revert rate > 10%: surface warning in session context: `"⚠ High revert rate this week ({N} reverts)"`
  - Pairs with existing commit granularity stats from `verify-task-completed.sh`

---

## Phase 8 — Closed-Loop Work Generation

---

### 8.1 Task Factories — BOTH（CLI 脚本 + GUI Python 模块双形态）

每个 factory 都有两种输出形态：CLI 版本输出 `===TASK===` 格式文件，GUI 版本写入 orchestrator DB。

- [x] **CI failure watcher — CLI** (`configs/scripts/scan-ci-failures.sh`) ✓
  - [x] GUI (`orchestrator/task_factory/ci_watcher.py`)：GitHub Actions API 轮询，`status_loop()` 集成
  - 去重 key：`source_ref = ci_run_{run_id}`（tasks 表新增 `source_ref TEXT` 列）

- [x] **Test coverage gap detector — CLI** (`configs/scripts/scan-coverage.sh`) ✓
  - [x] GUI (`orchestrator/task_factory/coverage_scan.py`)：同 CLI 逻辑，写 DB

- [x] **Dependency update bot — CLI** (`configs/scripts/scan-deps.sh`) ✓
  - [x] GUI (`orchestrator/task_factory/dep_update.py`)：同逻辑，写 DB

---

### 8.2 External Triggers — GUI only

- [x] **GitHub webhook endpoint** — `orchestrator/routes/webhooks.py`
  - `POST /api/webhooks/github`，注册到 FastAPI router
  - 触发条件：Issue 加 `claude-do-it` 标签 → 用 title+body 创建任务
  - 触发条件：Issue / PR 评论匹配 `/claude <instruction>` → 解析指令创建任务
  - 安全：验证 `X-Hub-Signature-256`（HMAC-SHA256）；新 setting `webhook_secret`
  - `source_ref = gh_issue_{number}` / `gh_pr_{number}` 去重

---

### 8.3 Specialist Presets — BOTH

- [x] **CLI task templates** — `configs/templates/` ✓
  - `task-test-writer.md`, `task-refactor-bot.md`, `task-security-scan.md` 已完成
  - 用法：`cat configs/templates/task-test-writer.md >> tasks.txt && bash batch-tasks tasks.txt`

- [x] **GUI preset cards** — Task 创建 UI 新增 "Quick Presets" 区域（4 个 card）
  - `test-writer` / `refactor-bot` / `docs-bot` / `security-scan`
  - 点击 → 预填 prompt + 自动设 `TYPE=HORIZONTAL` + 推荐 model
  - 前端：新增 `<PresetCards>` 组件，放在 TaskCreateForm 上方

- [x] **MCP integration** — `docs/mcp-setup.md` + worker 自动加载
  - 文档：推荐 servers（`brave-search`, `playwright-browser`, `filesystem`）+ 安装命令
  - `orchestrator/server.py`：`start_worker()` 时检测项目目录 `.claude/mcp.json` → 注入 worker 环境
  - `configs/templates/mcp.json.example`：可复制的示例配置

---

## Tech Debt

- [x] 🔴 `TaskQueue.add()` missing `task_type`/`source_ref`/`parent_task_id` params — `_decompose_horizontal()` and task factories will TypeError at runtime (`orchestrator/task_queue.py:234`)
- [x] 🔴 `httpx` not in requirements.txt but imported by ci_watcher — `ModuleNotFoundError` at import time (`orchestrator/task_factory/ci_watcher.py:9`)
- [x] 🔴 Task factories never called — ci_watcher/coverage_scan/dep_update created but never imported or wired into `status_loop()` (dead code)
- [x] 🔴 Webhook dedup uses wrong status `"completed"` instead of `"done"` — dedup silently always fails (`orchestrator/routes/webhooks.py:101`)
- [x] 🟡 `source_ref` never persisted in DB — webhook `add()` call drops it, dedup field always `None` (`orchestrator/routes/webhooks.py:106`)
- [x] 🟡 `worker.py` over 1500-line limit at 1513 lines — extract GitHub sync functions to `orchestrator/github_sync.py` (`orchestrator/worker.py`)
- [x] 🟡 TODO.md + VISION.md stale — Phase 7.3 + Phase 8 items still `[ ]` despite being implemented; VISION.md milestone table not updated
- [x] 🟡 `_decompose_horizontal` missing `cwd=project_dir` in subprocess — claude haiku runs in wrong directory (`orchestrator/session.py:678`)
- [x] 🟡 VISION.md Phase 7+8 detail sections still show `- [ ]` for all items despite being done (lines 83–119)
- [x] 🟡 `/orchestrate` skill prompt missing `TYPE:` field generation — proposed-tasks.md format should include `TYPE: HORIZONTAL|VERTICAL` (`configs/skills/orchestrate/prompt.md`)
- [x] 🟡 `docs/mcp-setup.md` missing — TODO item says create recommended MCP servers doc; only `mcp.json.example` template exists
- [x] 🟡 PROGRESS.md missing loop-fix-debt run entry (loop ran 2026-02-28, 3 iterations, CONVERGED)
- [ ] 🔵 Phase 10 (Portfolio Mode) — no TODO items yet; VISION.md describes cross-project task routing + system auto-ranks work

---

## Phase 10 — Portfolio Mode (FUTURE)

Human role: set direction for N projects → system auto-allocates workers, auto-ranks tasks, surfaces blockers.

- [ ] **Cross-project session overview** — single dashboard showing all active sessions + their queue depth + cost rate
- [ ] **Task priority ranker** — haiku scores pending tasks by impact/urgency across sessions; reorders queues
- [ ] **Worker pool router** — global `max_workers` budget shared across sessions; auto-rebalances based on queue depth
- [ ] **Morning briefing skill** — `/brief` generates a summary of overnight run: commits made, cost, failures, suggested next goals
- [ ] **Goal suggestion engine** — after each loop converges, suggest next 3 goals based on PROGRESS.md lessons + VISION.md gaps

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| DB | SQLite (aiosqlite) | Lightweight, no server, queryable history |
| Parallelism | Git worktrees | True isolation, no file conflicts |
| Push | Commit + push immediately | Code never lost, remote is backup |
| Merge | Auto-merge orchestrator branches; manual for external | Our tasks → ship fast; external → gate |
| Retry | With error context injected | Workers learn from failures |
| Oracle | Off by default | Opt-in quality gate, doesn't break existing flow |
| Model routing | Off by default | User may want explicit control |
| CLI loop | Pure bash (loop-runner.sh) | No Python dependency, safe for self-modification |
