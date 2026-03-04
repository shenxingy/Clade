# TODO — Claude Code Kit

> Vision and architecture: see [VISION.md](VISION.md)

Phases 1–10 complete. Phase 11 (Autonomous Lifecycle) is next.

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
- [x] 🔵 Phase 10 (Portfolio Mode) — loop plan moved to `docs/plans/2026-03-01-portfolio-mode.md`; TODO items listed in Phase 10 section below
- [x] 🟡 VISION.md Phase 9 status stale — milestone table shows "🔄 IN PROGRESS" but all TODOs are checked off (`VISION.md:60`)
- [x] 🟡 `Worker.start()` god method — 216 lines mixing subprocess, log-tail, context inject, task lifecycle, handoff (`orchestrator/worker.py:461`)
- [x] 🟡 Webhook open by default — `_verify_signature()` returns `True` when no `webhook_secret` set; document risk in README (`orchestrator/routes/webhooks.py:24`)
- [x] 🟡 Zero test coverage for core modules — `server.py`, `worker.py`, `session.py` have no unit/integration tests
- [x] 🟡 `_MODEL_MAP` defined twice in `session.py` — identical to `_MODEL_ALIASES` in `config.py`; import and reuse instead (`session.py:169`, `session.py:411`)
- [x] 🟡 `@app.on_event("startup")` deprecated in FastAPI ≥0.93 — migrate to `lifespan` context manager (`orchestrator/server.py:67`)
- [x] 🟡 `asyncio.ensure_future()` used 28× across 4 files — deprecated since Python 3.10, replace with `asyncio.create_task()` (`server.py`, `session.py`, `worker.py`, `task_queue.py`)
- [x] 🟡 `priority_score` test is a phantom — column doesn't exist in `task_queue.py` or `config.py`; test accepts `None` so always passes silently (`orchestrator/tests/test_task_queue.py:89`)
- [x] 🟡 No pinned dependency versions in `requirements.txt` — builds are not reproducible; `pytest` should move to `requirements-dev.txt` (`orchestrator/requirements.txt`)
- [x] 🔴 Phantom columns `"mode"` and `"result"` in `_ALLOWED_TASK_COLS` — neither exists in tasks table; `POST /api/tasks/{task_id}` with these keys causes `OperationalError` at runtime (`orchestrator/config.py:23`)
- [x] 🔴 `str(e)` returned in `merge_all_done` API response — raw exception message leaks internal details; violates no-error-message rule (`orchestrator/server.py:796`)
- [x] 🟡 `web/index.html` at 2945 lines — violates 1500-line project limit; extract inline JS to `web/app.js` (`orchestrator/web/index.html`)
- [x] 🟡 `_decompose_horizontal` missing `--dangerously-skip-permissions` — haiku call will prompt interactively, timeout 30s, silently fail in production (`orchestrator/session.py:668`)
- [x] 🟡 `_last_autoscale`/`_ci_watcher_last`/`_coverage_scan_last`/`_dep_update_last` not declared in `ProjectSession.__init__` — accessed via `getattr` fallback, misleading class API (`orchestrator/session.py:107`)
- [x] 🟡 `import_from_proposed` INSERT bypasses `add()` — missing `source_ref` and `is_critical_path` columns; imported tasks can't be marked critical path (`orchestrator/task_queue.py:527`)
- [x] 🟡 `priority_score` column added but nothing writes to it — Phase 10 priority ranker is a schema-only stub with no scoring logic (`orchestrator/worker.py`)
- [x] 🟡 No CORS middleware on FastAPI app — mobile/remote access via Caddy HTTPS (stated in VISION) will fail with CORS errors (`orchestrator/server.py:72`)
- [x] 🔵 `schedule` endpoint error message incorrect — said "ISO 8601" but parser only accepts `HH:MM`; fixed to "Use HH:MM (24h), e.g. 09:00" (`orchestrator/server.py:471`)

---

## Phase 10 — Portfolio Mode (DONE)

Human role: set direction for N projects → system auto-allocates workers, auto-ranks tasks, surfaces blockers.

- [x] **Cross-project session overview** — single dashboard showing all active sessions + their queue depth + cost rate
- [x] **Task priority ranker** — haiku scores pending tasks by impact/urgency across sessions; reorders queues
- [x] **Worker pool router** — global `max_workers` budget shared across sessions; auto-rebalances based on queue depth
- [x] **Morning briefing skill** — `/brief` generates a summary of overnight run: commits made, cost, failures, suggested next goals
- [x] **Goal suggestion engine** — after each loop converges, suggest next 3 goals based on PROGRESS.md lessons + VISION.md gaps

---

---

## Phase 11 — Autonomous Lifecycle

Goal: one command starts everything, runs unattended for any duration (2h lunch / 8h overnight / full weekend) without stopping on minor issues, surfaces a clean session report when done. Human role shrinks to: set direction + approve proposals + resolve true blockers. The system self-plans, claims tasks, executes, verifies, loops — overnight is just one scenario, not the core constraint.

**Implementation order (dependency chain):**
```
① Phase 10 verification + cost-tracking investigation (11.6) — fix stubs + unblock session-report design
② CLAUDE.md template (11.4)              — Project Type + Features fields
③ /verify skill (11.2)                   — needs those fields to work
④ 3-tier rules in /loop (11.3)           — foundation for /start to rely on
⑤ loop-runner.sh bug fixes (11.8)        — autonomous mode relies on reliable loop behavior
⑥ Update /orchestrate Feature tag (11.1) — prerequisite for one-feature filtering
⑦ /start morning mode + start.sh (11.1)  — morning mode first, validate pattern
⑧ /start autonomous mode (11.1)          — full autonomous
⑨ Safety layer (11.7)                    — cost guard + budget settings + --resume
```

**Architecture decision: /start = pure shell script (not a Claude meta-skill)**
- /start is a shell script (like loop-runner.sh), NOT a Claude skill that runs in one session
- Rationale: a single-session skill calling /orchestrate + /loop + /verify would blow context in one iteration
- /start calls bottom-layer scripts directly: loop-runner.sh, batch-tasks, committer
- Each worker = independent Claude session; /start itself consumes zero context
- Does NOT require the GUI orchestrator to be running — TUI-native
- Works for any run duration: `start.sh` (autonomous until done/blocked/budget), `start.sh --hours 4`, `start.sh --morning` (briefing only)

---

### 11.6 — Phase 10 Verification ← start here (unblock dependencies)

- [x] **Verify Phase 10 features actually work end-to-end** — code-level trace confirmed:
  - ✓ Priority ranker: `_rank_tasks()` → 5min timer → haiku scores → DB write → `claim_next_pending()` ORDER BY priority_score DESC. Full chain wired.
  - ✓ Cross-project overview: `GET /api/sessions/overview` returns pending/running + cost_rate_per_hour across all sessions.
  - ✓ Model routing: score≥80→haiku, <50→sonnet+warning, critical_path→tier upgrade. Gated by `auto_model_routing` setting.
  - ✓ Global max_workers: enforced in status_loop + auto-scale + start-all-queued.
  - ⚠ Worker rebalancing NOT implemented (TODO said "auto-rebalances" but only global cap exists, no inter-session redistribution). Deferred — not needed for Phase 11 CLI layer.
- [x] **Investigate `claude -p --output-format json` for cost tracking** — CONFIRMED: JSON output includes `total_cost_usd` (float) + `modelUsage.{model}.costUSD` per-model breakdown + full token counts. Parse with `jq '.total_cost_usd'`. Not a blocker — cost tracking fully feasible.

---

### 11.4 — CLAUDE.md Template New Sections

- [x] **Dogfooding: add `## Project Type` + `## Features` to claude-code-kit's own CLAUDE.md** — added with 6 behavior anchors (install.sh, slt, /commit, /loop, committer, loop-runner.sh)
- [x] **Add `## Project Type` section to `configs/templates/CLAUDE.md`**
- [x] **Add `## Features` section to `configs/templates/CLAUDE.md`**

---

### 11.2 — `/verify` Skill

- [x] **Create `configs/skills/verify/prompt.md`** — project-type-aware testing with behavior anchors, machine-parseable VERIFY_RESULT/FAILED_ANCHORS/UNVERIFIABLE footer
  - `partial` vs `fail` distinction must be explicit in the prompt: `partial` = some anchors unverifiable (no test strategy, missing Playwright, insufficient coverage); `fail` = anchors that can be tested and are now regressing; start.sh uses this to decide skip-and-continue vs create-fix-tasks

---

### 11.3 — 3-Tier Issue Handling

- [x] **Add 3-tier rules to `loop-runner.sh` `INSTRUCTIONS` heredoc** — Tier 1 (decisions.md), Tier 2 (skipped.md), Tier 3 (blockers.md) + supervisor blocker detection
- [x] **Add `blockers.md` check to loop-runner.sh per-iteration guard** — placed alongside STOP sentinel; stops loop + notifies on Tier 3 blocker
- [x] **Add `decisions.md` / `skipped.md` cleanup to `/sync` skill** — archives tier files to `*-archive.md` and deletes originals
- [x] **blockers.md stale entry handling in start.sh** — TTY: 30s prompt (auto-clear); unattended: exit with `blocked-stale` report

---

### 11.1 — `/start` Skill

**Internal flow (autonomous/unattended mode):**
```
outer iteration start:
  check blockers.md + cost + wall-clock → stop if hit
  /orchestrate → fresh proposed-tasks.md  (orchestrate decides if /research needed — not start.sh)
  filter by top-priority feature → fresh filtered-tasks.md
  if grep -c "^\- \[ \]" filtered-tasks.md == 0 → CONVERGED (done)
  /loop [3-tier active] (goal = filtered-tasks.md)
    ↓
  /verify
    ├─ pass    → claude -p sync → committer "docs: sync" → outer iteration start
    ├─ partial → log gaps to skipped.md → claude -p sync → committer → outer iteration start
    └─ fail    → create fix tasks → back to /loop (max 3 retries → tier 2)
  ↓
write .claude/session-report-{timestamp}.md → stop
```

**Convergence = stop when ALL true:**
- Fresh `/orchestrate` output produces 0 open tasks for the current feature (checked at outer loop start)
- `/verify` returns pass or partial
- OR: iteration budget reached / cost cap hit / blocker written / max retries on verify-fail
- Note: convergence check is on freshly-generated filtered-tasks.md (not worker-mutated files); /start never targets itself (circular)

- [x] **Create `configs/skills/start/prompt.md` — morning briefing mode** — thin wrapper + `morning-brief.md` prompt template
- [x] **Create `configs/scripts/start.sh` — autonomous/unattended mode** (shell script, NOT prompt.md)
  - Shell orchestrator: self-plans, claims work, executes, verifies, loops — runs for any duration until done/blocked/budget hit
  - Stop conditions: all tasks done (convergence) / `session_budget_usd` hit / wall-clock `--hours N` / `.claude/blockers.md` written / manual `--stop`
  - **Calling /orchestrate from shell** (use heredoc to avoid `\n` issues):
    ```bash
    claude -p "$(printf '%s\n\n%s\n\n%s' \
      "$(cat ~/.claude/skills/orchestrate/prompt.md)" \
      "$(cat CLAUDE.md)" \
      "$(cat TODO.md)")" > proposed-tasks.md
    ```
  - **One-feature focus filtering**: after /orchestrate writes proposed-tasks.md, start.sh groups tasks by `Feature:` tag, selects tasks for top-priority incomplete feature (priority = order in TODO.md), writes filtered-tasks.md → loop-runner.sh receives filtered-tasks.md; **fallback if no Feature: tags found**: treat all tasks as one group (run everything in one loop) — prevents start.sh crash when /orchestrate hasn't been updated yet to emit tags
  - **Calling /verify from shell**: `claude -p "$(cat ~/.claude/skills/verify/prompt.md)" > .claude/verify-output.txt`; then `grep "VERIFY_RESULT:" .claude/verify-output.txt` to branch on pass/partial/fail
  - **Calling /commit + /sync from shell**: use `committer.sh` directly (not the /commit skill — skill requires interactive Claude session); committer.sh stages and commits changed files; /sync = update TODO.md + PROGRESS.md (done by a separate claude -p call)
  - Must re-read GOALS.md + VISION.md at start of every iteration (drift anchor, injected into loop-runner goal)
  - Must NOT modify GOALS.md or VISION.md directly — proposals go to BRAINSTORM.md with `[AI]` prefix
  - Max verify-fail retries: 3 per task before tier 2 escalation; retry counter tracked in session-progress.md
  - Writes `.claude/session-report-{timestamp}.md` on finish by parsing `.claude/loop-cost.log`; works whether run was 2h or 16h
  - verify-fail → fix task flow: `grep "FAILED_ANCHORS:" verify-output.txt` → write fix tasks → re-run loop-runner.sh
  - **Convergence detection**: at the TOP of each outer iteration, AFTER fresh /orchestrate runs, `grep -c "^\- \[ \]" filtered-tasks.md`; if 0 → truly converged (no more open tasks in current feature scope), write `session-report-{timestamp}.md` + stop; if >0 → run /loop; this replaces the old "re-read filtered-tasks.md after verify" pattern — workers never mutate filtered-tasks.md, /orchestrate regenerates it fresh each iteration

- [x] **Shell invocation checklist** — all `claude -p` calls use `--dangerously-skip-permissions`; orchestrate injects CLAUDE.md + TODO.md + GOALS.md + PROGRESS.md + skipped.md; optional docs guarded; sync before committer; unset CLAUDECODE at top
- [x] **Add cost logging to loop-runner.sh** — supervisor uses `--output-format json` + python3 JSON parsing; worker costs parsed from `logs/claude-tasks/` stream-json logs via marker-file-based discovery; per-iteration + cumulative totals logged to `.claude/loop-cost.log`
- [x] **Session report format** — `_write_session_report()` in start.sh writes timestamped `.claude/session-report-{id}.md`
- [x] **Update `/orchestrate` skill to tag tasks with `Feature: <name>`** — added Feature: line to task block format + documentation
- [x] **Targeted mode** (`/start --goal "X"`) — implemented: skips orchestrate, copies goal file directly to filtered-tasks.md
- [x] **One-feature focus strategy** — `_filter_by_feature()` groups by Feature: tag, picks first feature, filters tasks; skipped.md injected into /orchestrate context for next iteration
- [x] **30s plan approval window** — TTY detection + `read -t 30` auto-continue; `--confirm` forces window in non-TTY mode
- [x] **Session progress file** — `_write_progress()` writes key=value to `.claude/session-progress.md`; `--resume` reads it back

---

### 11.5 — Drift Prevention Conventions

- [x] **Add `# FROZEN` convention to CLAUDE.md template** — documented with ~90% effectiveness caveat
- [x] **Add BRAINSTORM proposal rule to `loop-runner.sh` `INSTRUCTIONS` heredoc** — "write to BRAINSTORM.md with [AI] prefix, never modify GOALS.md/VISION.md"
- [x] **Inject BRAINSTORM rule into start.sh goal string** — appended to loop-goal.md before each loop-runner.sh call

---

### 11.8 — loop-runner.sh Known Bugs

- [x] **Bug: workers race-condition on goal file marking** — removed `- [ ]` → `- [x]` instructions from both INSTRUCTIONS heredoc and fallback wrapper; replaced with "Do NOT modify the goal file"
- [x] **Bug: auto-deploy + git_recent_diff both use wrong commit range** — added `STARTED_COMMIT` to state file at loop start; both git_recent_diff and auto-deploy now use `$(state_read STARTED_COMMIT)..HEAD`
- [x] **Bug: non-code task silent failure** — added `ITER_START_SHA` capture before workers + `git rev-list` count after; zero commits → injects context for supervisor to decide CONVERGED vs re-plan
- [x] **Cost logging to loop-cost.log** — supervisor `--output-format json` + worker stream-json parsing; marker-file discovery for worker logs; cumulative tracking; start.sh `_accumulate_cost()` reads CUMULATIVE value

---

### 11.7 — Safety Layer

- [x] **Cost guard in `start.sh`** — reads `~/.claude/start-settings.json`, `--budget N` flag, defaults to $5 with warning; checked every iteration via `_check_stop_conditions()`
- [x] **Context management** — start.sh is zero-context (pure shell); workers manage their own via handoff/pickup; start.sh only tracks wall-clock and cost
- [x] **Entry point unification** — `start.sh` supports: `--morning`, `--run` (default), `--hours N`, `--goal "X"`, `--budget N`, `--resume`, `--stop`; skill wrapper delegates to start.sh
- [x] **Mode auto-detection** — TTY → show plan + 30s approval window; no TTY → run immediately; `--confirm` forces window

---

## Phase 12 — From Code-Centric to Product-Centric

Goal: the system must not only build code, but also USE what it builds — interact with the UI, evaluate UX, and continuously discover new work without hand-written TODOs.

### 12.0 — Stress-Test Prerequisite

- [x] **Run `start.sh` on owlcast** — 66min, $10.48, 21 commits, 6 tasks, CONVERGED at iter 4 (see PROGRESS.md 2026-03-03)
- [x] **Run `start.sh` on ai-ap-manager** — 22min, $4.21, 7 commits, 5 tasks, CONVERGED at iter 2 (see PROGRESS.md 2026-03-03)
- [x] **Run `start.sh` on deepfake-platform** — 32min, $12.79, 41 commits, 5 goals → 14 tasks, 5 iterations (see PROGRESS.md 2026-03-03)
- [x] **Record baselines in PROGRESS.md** — owlcast vs ai-ap-manager comparison table added

#### Bugs found in stress test (fix before more runs)

- [x] 🔴 **Parallel execution broken** — replaced `extract_file_refs()` (prose regex) with `extract_own_files()` (OWN_FILES: only) + `get_task_depends_on()`. Default: parallel. Serialize only on explicit `depends_on:` or `OWN_FILES:` overlap.
- [x] 🟡 **Default timeout too short for large tasks** — model-aware defaults: haiku=900s (15m), sonnet=1800s (30m), opus=3600s (60m). Explicit `timeout:` still overrides.
- [x] 🟡 **Disk pressure warning missing** — `_check_startup_health()` in start.sh: ≥95% abort, ≥90% warn+prompt, low memory (<512MB) warn.
- [x] 🟡 **/orchestrate conversational fallback** — retry once with "CRITICAL: output ONLY ===TASK=== blocks" prepended; check for explicit `STATUS: CONVERGED` before giving up.
- [x] 🔵 **Cost log delay** — `touch` cost log at loop-runner.sh startup; `_accumulate_cost()` skips python3 when cumulative is 0/empty.

#### Bugs found in stress test #2 (ai-ap-manager)

- [x] 🔴 **Stale installed scripts** — `install.sh` writes `.kit-source-dir` + `.kit-checksum`; `session-context.sh` warns on mismatch; `start.sh` auto-reinstalls (TTY) or aborts (unattended).
- [x] 🟡 **Orphaned watchdog sleeps block start.sh** — watchdog/heartbeat trap handlers now kill inner `sleep` PID before exit. Validated in stress test #2b (zero orphaned processes).

#### Bugs found in stress test #3 (deepfake-platform)

- [x] 🔵 **Budget not enforced by inner loop** — loop-runner.sh now accepts `--budget` flag; start.sh passes `--budget-remaining` each iteration; loop breaks when cumulative cost exceeds budget
- [x] 🟡 **`head -N` pipe kills start.sh** — added `trap '' PIPE` after signal handlers; SIGPIPE is now ignored

---

### 12.1 — UI Interaction Testing (frontend/fullstack only)

- [x] **Playwright user flow walker** — launch app, click buttons, fill forms, navigate pages (not just screenshots)
- [x] **AI UX evaluation** — for each flow: does it work? Is it intuitive? Unnecessary steps? Better placement?
- [x] **Findings classification** — bugs → fix tasks for next loop; UX improvements → BRAINSTORM.md with `[AI]` prefix
- [x] **Machine-parseable output** — `INTERACTION_RESULT: pass|partial|fail` + structured issue list
- [x] **Integration with `/verify`** — triggered automatically for frontend projects; skipped for CLI/backend/ML

---

### 12.2 — Autonomous Work Discovery

- [x] **Extract task factories to CLI** — CI watcher, coverage scanner, dep updater already exist as `configs/scripts/scan-{ci-failures,coverage,deps}.sh` from Phase 8.1
- [x] **Post-convergence scan in start.sh** — `_post_convergence_scan()` runs all scan scripts after convergence; findings → injected as next iteration tasks (once per session to prevent infinite loops)
- [x] **UX audit as work source** — already implemented in Phase 12.1: `INTERACTION_RESULT` parsing in start.sh; `[BUG]` → fix tasks, `[UX]` → BRAINSTORM.md
- [x] **Code health scan** — `configs/scripts/scan-health.sh`: TODO/FIXME comments, mypy/tsc type errors, ruff/eslint lint, large files (>1500 lines); integrated into post-convergence scan

---

### 12.3 — Design System Constraint

- [x] **Design token injection in `/orchestrate`** — architect phase references component library + theme
- [x] **`/frontend-design` design system awareness** — reads project `.design-system.md` for constraints

---

### 12.4 — Batch Feedback + Cross-Project Patrol

- [ ] **Structured issue checklist from `/verify`** — output to `.claude/verify-issues.md`, not one-by-one
- [ ] **File-based annotation** — user marks `[fix]` / `[skip]` / `[wontfix]` per item in one editing pass
- [ ] **Auto-task creation** — next loop reads annotations, `[fix]` → tasks, rest → skipped.md
- [ ] **`start.sh --patrol`** — scan all `~/projects/*/` with `CLAUDE.md`, run task factories per project, aggregate report

---

## Phase 13 — Orchestrator GUI Redesign (Future)

Separated from Phase 12 due to scope — this is a full product redesign.

- [ ] **Audit current GUI** — catalog all features, classify as keep/remove/redesign
- [ ] **Monitoring-first redesign** — worker dashboard, session timeline, blocker queue
- [ ] **Remove interactive editing** — task editing and prompt input belong in TUI, not GUI

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
