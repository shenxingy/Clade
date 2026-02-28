# TODO — Claude Code Kit

> Vision and architecture: see [VISION.md](VISION.md)

Phases 1–6 complete. Phase 7 (Task Velocity Engine) and Phase 8 (Closed-Loop Work Generation) in progress.

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

- [ ] **Commit granularity gate** — 扩展 `configs/hooks/verify-task-completed.sh`
  - 新增：统计 task 期间 commit 数 vs 变更文件数（`git log --oneline` 比对 session 开始 SHA）
  - `commit_count / changed_files < 0.5` → 追加警告到 stats，不阻断完成

- [x] **CLAUDE.md per-file rule** — `configs/templates/CLAUDE.md` ✓ (loop 2026-02-27)

---

### 7.2 CLI/TUI Velocity — configs/ 层（bash 实现）

- [ ] **loop-runner.sh HORIZONTAL 模式** — goal file 加 `MODE: HORIZONTAL` → supervisor 最多 20 micro-tasks

- [x] **TODO scanner CLI** — `configs/scripts/scan-todos.sh` ✓ (loop 2026-02-27)

- [x] **tmux dispatcher** — `configs/scripts/tmux-dispatch.sh` ✓ (loop 2026-02-27)

---

### 7.3 GUI Velocity — orchestrator/ 层（Python 实现）

- [ ] **Task type 字段** — DB + 解析 + UI badge
  - `orchestrator/server.py`：`tasks` 表 ALTER 加 `task_type TEXT DEFAULT 'AUTO'`
  - 解析 `proposed-tasks.md` 中 `TYPE: HORIZONTAL|VERTICAL` 字段，写入 DB
  - 前端：worker card 显示 `H`（橙）/ `V`（蓝）/ `A`（灰）badge
  - `/orchestrate` skill 生成的 `proposed-tasks.md` 格式中加 `TYPE:` 字段（改 skill prompt）

- [ ] **Horizontal auto-decomposition** — `orchestrator/server.py`
  - `start_worker()` 前：`if task.task_type == 'HORIZONTAL'` → 调用 `_decompose_horizontal(task)`
  - `_decompose_horizontal`：用 claude haiku 列出受影响文件列表 → 每个文件创建子任务
  - 子任务描述：`[file: {path}] {原始任务描述}`，`parent_task_id` 字段记录父任务
  - 父任务状态改为 `grouped`，所有子任务完成后父任务自动 complete

- [ ] **Worker auto-scaling** — `orchestrator/server.py` + 前端设置
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

- [ ] **session-context.sh: loop-state + next TODO** — extend existing hook
  - Add after git log block: read `.claude/loop-state` if exists → show CONVERGED/running/stopped
  - Add: find next unchecked `- [ ]` item in TODO.md → show as "Next: ..."
  - Files: `configs/hooks/session-context.sh`

### 9.2 Loop Intelligence

- [ ] **loop-runner.sh: auto-PROGRESS on convergence** — on CONVERGED, spawn haiku
  - Read `git log --oneline` since loop started (use STARTED timestamp from state file)
  - Write structured entry to PROGRESS.md: `### {date} — Loop: {goal_name}\n**Iterations:** N\n**Commits:** ...\n**Summary:** ...`
  - Files: `~/.claude/scripts/loop-runner.sh`

- [ ] **loop-runner.sh: notify-telegram on convergence** — if `notify-telegram.sh` exists + TELEGRAM_TOKEN set
  - Call `bash configs/hooks/notify-telegram.sh "Loop converged: {goal} in {N} iterations"` on CONVERGED and INTERRUPTED
  - Files: `~/.claude/scripts/loop-runner.sh`

- [ ] **loop-runner.sh: HORIZONTAL mode** — `MODE: HORIZONTAL` in goal file → supervisor outputs up to 20 micro-tasks
  - Parse `MODE:` from first 5 lines of goal file
  - Inject into supervisor prompt: `"Output up to 20 file-level micro-tasks. Each task must touch exactly 1 file."`
  - Files: `~/.claude/scripts/loop-runner.sh`, `configs/templates/loop-goal.md` (add MODE field example)

- [ ] **loop-runner.sh: --exit-gate flag** — hard convergence gate
  - `--exit-gate "bash typecheck.sh"` → run command before accepting CONVERGED
  - If gate fails: supervisor gets failure output as context, loop continues
  - If gate passes: accept CONVERGED
  - Files: `~/.claude/scripts/loop-runner.sh`

### 9.3 Commit Quality

- [ ] **verify-task-completed.sh: commit granularity stats** — non-blocking tracking
  - Count commits made since task started vs files changed
  - If ratio < 0.5: append warning to `.claude/stats.jsonl`: `{"date":..., "task":..., "commits":N, "files":M, "ratio":R}`
  - Files: `configs/hooks/verify-task-completed.sh`

### 9.4 Kit Completeness

- [ ] **Copy review-pr, merge-pr, worktree skills to configs/skills/**
  - Copy from `~/.claude/skills/{review-pr,merge-pr,worktree}/` → `configs/skills/`
  - Update `install.sh` if needed to install these skills
  - Files: `configs/skills/review-pr/`, `configs/skills/merge-pr/`, `configs/skills/worktree/`

### 9.5 Research Skill

- [x] **`/research` skill** ✓ — `configs/skills/research/prompt.md` (loop 2026-02-27)

### 9.6 Pattern Intelligence & Self-Improvement

- [ ] **`/map` skill** — codebase structure visualization
  - Scan `configs/` + `orchestrator/` → generate Mermaid diagram of modules + responsibilities
  - Output to `ARCHITECTURE.md` in project root
  - File: `configs/skills/map/prompt.md`

- [ ] **Prompt fingerprint tracker** — detect recurring user prompts
  - In `configs/hooks/session-context.sh` (or a new PostToolUse hook): log prompt hash + first 60 chars to `.claude/prompt-log.jsonl`
  - After 3+ identical hashes: append suggestion to session context: `"You've run this prompt 3x — consider making it a skill"`
  - File: `configs/hooks/session-context.sh` or new `configs/hooks/prompt-tracker.sh`

- [ ] **`/incident` skill** — operational incident → learning
  - User describes what went wrong → skill writes structured incident to `.claude/incidents.md`
  - Format: date, what happened, root cause, corrective action, suggested hook/rule
  - Optionally appends a new rule to `corrections/rules.md`
  - File: `configs/skills/incident/prompt.md`

- [ ] **Value tracking** — extend `.claude/stats.jsonl` with revert detection
  - `configs/hooks/session-context.sh`: on startup, count `git log --oneline --grep="Revert"` in last 7 days
  - If revert rate > 10%: surface warning in session context: `"⚠ High revert rate this week ({N} reverts)"`
  - Pairs with existing commit granularity stats from `verify-task-completed.sh`

---

## Phase 8 — Closed-Loop Work Generation

---

### 8.1 Task Factories — BOTH（CLI 脚本 + GUI Python 模块双形态）

每个 factory 都有两种输出形态：CLI 版本输出 `===TASK===` 格式文件，GUI 版本写入 orchestrator DB。

- [x] **CI failure watcher — CLI** (`configs/scripts/scan-ci-failures.sh`) ✓
  - [ ] GUI (`orchestrator/task_factory/ci_watcher.py`)：GitHub Actions API 轮询，`status_loop()` 集成
  - 去重 key：`source_ref = ci_run_{run_id}`（tasks 表新增 `source_ref TEXT` 列）

- [x] **Test coverage gap detector — CLI** (`configs/scripts/scan-coverage.sh`) ✓
  - [ ] GUI (`orchestrator/task_factory/coverage_scan.py`)：同 CLI 逻辑，写 DB

- [x] **Dependency update bot — CLI** (`configs/scripts/scan-deps.sh`) ✓
  - [ ] GUI (`orchestrator/task_factory/dep_update.py`)：同逻辑，写 DB

---

### 8.2 External Triggers — GUI only

- [ ] **GitHub webhook endpoint** — `orchestrator/routes/webhooks.py`
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

- [ ] **GUI preset cards** — Task 创建 UI 新增 "Quick Presets" 区域（4 个 card）
  - `test-writer` / `refactor-bot` / `docs-bot` / `security-scan`
  - 点击 → 预填 prompt + 自动设 `TYPE=HORIZONTAL` + 推荐 model
  - 前端：新增 `<PresetCards>` 组件，放在 TaskCreateForm 上方

- [ ] **MCP integration** — `docs/mcp-setup.md` + worker 自动加载
  - 文档：推荐 servers（`brave-search`, `playwright-browser`, `filesystem`）+ 安装命令
  - `orchestrator/server.py`：`start_worker()` 时检测项目目录 `.claude/mcp.json` → 注入 worker 环境
  - `configs/templates/mcp.json.example`：可复制的示例配置

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
