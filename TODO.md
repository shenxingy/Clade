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
- [ ] 🟡 `priority_score` column added but nothing writes to it — Phase 10 priority ranker is a schema-only stub with no scoring logic (`orchestrator/worker.py`)
- [x] 🟡 No CORS middleware on FastAPI app — mobile/remote access via Caddy HTTPS (stated in VISION) will fail with CORS errors (`orchestrator/server.py:72`)
- [x] 🔵 `schedule` endpoint error message incorrect — said "ISO 8601" but parser only accepts `HH:MM`; fixed to "Use HH:MM (24h), e.g. 09:00" (`orchestrator/server.py:471`)

---

## Phase 10 — Portfolio Mode (FUTURE)

Human role: set direction for N projects → system auto-allocates workers, auto-ranks tasks, surfaces blockers.

- [x] **Cross-project session overview** — single dashboard showing all active sessions + their queue depth + cost rate
- [x] **Task priority ranker** — haiku scores pending tasks by impact/urgency across sessions; reorders queues
- [x] **Worker pool router** — global `max_workers` budget shared across sessions; auto-rebalances based on queue depth
- [x] **Morning briefing skill** — `/brief` generates a summary of overnight run: commits made, cost, failures, suggested next goals
- [x] **Goal suggestion engine** — after each loop converges, suggest next 3 goals based on PROGRESS.md lessons + VISION.md gaps

---

---

## Phase 11 — Autonomous Lifecycle

Goal: one command starts everything, runs overnight without stopping on minor issues, surfaces a clean morning review. Human role shrinks to: set direction + approve proposals + resolve true blockers.

**Implementation order (dependency chain):**
```
① Phase 10 verification (11.6)         — fix broken stubs before building on top
② CLAUDE.md template (11.4)            — Project Type + Features fields
③ /verify skill (11.2)                 — needs those fields to work
④ 3-tier rules in /loop (11.3)         — foundation for /start to rely on
⑤ Update /orchestrate Feature tag (11.1) — prerequisite for one-feature filtering
⑥ /start morning mode + start.sh (11.1) — morning mode first, validate pattern
⑦ /start overnight mode (11.1)         — full autonomous
⑧ Safety layer (11.7)                  — cost guard + budget settings
```

**Architecture decision: /start = pure shell script (not a Claude meta-skill)**
- /start is a shell script (like loop-runner.sh), NOT a Claude skill that runs in one session
- Rationale: a single-session skill calling /orchestrate + /loop + /verify would blow context in one iteration
- /start calls bottom-layer scripts directly: loop-runner.sh, batch-tasks, committer
- Each worker = independent Claude session; /start itself consumes zero context
- Does NOT require the GUI orchestrator to be running — TUI-native

---

### 11.6 — Phase 10 Verification ← start here (unblock dependencies)

- [ ] **Verify Phase 10 features actually work end-to-end** — cross-project session overview, priority ranker, worker pool router all marked `[x]` but need manual testing. Acceptance criteria:
  - `priority_score` ranker returns a non-zero numeric score for at least one task (currently pure stub, no scoring logic)
  - Cross-project session overview lists sessions from ≥2 projects
  - Worker pool router assigns haiku/sonnet/opus based on task complexity field
  - If any fail: add fix tasks here before proceeding to 11.4+

---

### 11.4 — CLAUDE.md Template New Sections

- [ ] **Dogfooding: add `## Project Type` + `## Features` to claude-code-kit's own CLAUDE.md** — required before /verify can work on this project; also serves as the first end-to-end test of the template design
  - Project Type: cli + skill-system
  - Features: install.sh installs skills/hooks/scripts, slt cycles modes, /commit splits and pushes, /loop runs until convergence
- [ ] **Add `## Project Type` section to `configs/templates/CLAUDE.md`**
  ```
  ## Project Type
  - Type: [web-fullstack | api-only | cli | ml-pipeline | library | skill-system | toolkit]
  - Frontend: [framework + port, or N/A]
  - Backend: [framework + port, or N/A]
  - Test command: [e.g. pytest tests/ -v]
  - Verify command: [e.g. ./scripts/smoke-test.sh, or N/A]
  ```
- [ ] **Add `## Features` section to `configs/templates/CLAUDE.md`**
  ```
  ## Features (Behavior Anchors)
  # Used by /verify to check that key behaviors still hold after each loop iteration.
  # Format: - [Feature name]: [what happens when user does X]
  ```

---

### 11.2 — `/verify` Skill

- [ ] **Create `configs/skills/verify/prompt.md`** — project-type-aware testing
  - Auto-detect project type from CLAUDE.md `## Project Type` section; fallback: scan repo structure
  - Strategy map: frontend → Playwright exploratory; API → httpx smoke tests; test suite exists → run it; CLI → run with sample inputs; no test strategy → report "unverifiable, skipped"
  - Playwright fallback: if Playwright MCP not available, skip UI tests and note the gap
  - Check behavior anchors in CLAUDE.md `## Features` section; flag any that no longer hold
  - **Output must end with machine-parseable footer** (for start.sh to grep):
    ```
    VERIFY_RESULT: pass|partial|fail
    FAILED_ANCHORS: anchor-name-1, anchor-name-2  (or "none" if no failures)
    UNVERIFIABLE: N
    ```
  - Human-readable summary above the footer; footer always last 3 lines; FAILED_ANCHORS must always be present (use "none" not blank line — blank breaks grep)
  - `partial` vs `fail` distinction must be explicit in the prompt: `partial` = some anchors unverifiable (no test strategy, missing Playwright, insufficient coverage); `fail` = anchors that can be tested and are now regressing; start.sh uses this to decide skip-and-continue vs create-fix-tasks

---

### 11.3 — 3-Tier Issue Handling

- [ ] **Add 3-tier rules to `loop-runner.sh` `INSTRUCTIONS` heredoc** (lines 285-318 in loop-runner.sh — that's where the supervisor prompt is built; the loop skill's prompt.md only launches loop-runner, it doesn't contain the supervisor instructions)
  - Tier 1 (uncertainty): pick reversible default → log to `.claude/decisions.md` → continue
  - Tier 2 (task failure): skip task → log to `.claude/skipped.md` → continue
  - Tier 3 (true blocker): write to `.claude/blockers.md` → stop loop
  - True blocker criteria: destructive/irreversible ops, needs secrets/permissions, mutually exclusive directions with high rollback cost
  - **Supervisor needs blocker detection**: add to INSTRUCTIONS heredoc — "If `.claude/blockers.md` appears in the recent diff (was written this loop run), output STATUS: CONVERGED — a Tier 3 blocker requires human input before proceeding"
- [ ] **Add `blockers.md` check to loop-runner.sh per-iteration guard** — loop-runner.sh currently only checks STOP sentinel (line 200) between iterations; workers write blockers.md to their worktree which gets merged back after the iteration; at the top of each new iteration, add: `if [[ -f ".claude/blockers.md" ]]; then echo "⚠ Blocker detected"; exit 1; fi` — prevents wasted iterations after a Tier 3 blocker is committed; place alongside STOP sentinel check (line 200)
- [ ] **Add `decisions.md` / `skipped.md` cleanup to `/sync` skill** — all three tier files (decisions, skipped, blockers) must include ISO timestamp per entry; /sync archives to `.claude/*-archive.md` at session end
- [ ] **blockers.md stale entry handling in start.sh** — on launch, check entry timestamps; interactive mode: prompt "still blocked? (y/N)" for entries older than 24h; overnight mode (no TTY): auto-stop and log stale blocker to morning-review.md with note "review .claude/blockers.md"; use `[ -t 0 ]` to detect TTY

---

### 11.1 — `/start` Skill

**Internal flow (overnight mode):**
```
read GOALS/TODO/PROGRESS/BRAINSTORM
/orchestrate → proposed-tasks.md  (orchestrate decides if /research needed — not start.sh)
  ↓
/loop  [3-tier active]
  ↓
/verify
  ├─ pass    → committer.sh → claude -p sync → re-read filtered-tasks.md: unchecked items? → back to /loop
  ├─ partial → log gaps to skipped.md → committer.sh → next iteration (treat as pass for loop purposes)
  └─ fail    → create fix tasks → back to /loop (max 3 retries → tier 2)
  ↓
each iteration: check cost / wall-clock time / blockers.md  (no context% — shell has none)
  ↓
write .claude/morning-review.md → stop
```

**Convergence = stop when ALL true:**
- `grep -c "^\- \[ \]" filtered-tasks.md` returns 0 (all tasks in current feature scope done)
- `/verify` returns pass or partial
- OR: iteration budget reached / cost cap hit / blocker written
- Note: checks filtered-tasks.md (scoped), NOT all of TODO.md (too broad); /start never targets itself (circular)

- [ ] **Create `configs/skills/start/prompt.md` — morning mode** (thin wrapper only; no workers launched)
  - Skill just calls `bash ~/.claude/scripts/start.sh --morning` via Bash tool and displays output
  - start.sh --morning: invokes `claude -p "$(printf '%s\n\n%s\n\n%s\n\n%s\n\n%s' "$(cat ~/.claude/skills/start/morning-brief.md)" "$(cat GOALS.md)" "$(cat TODO.md)" "$(cat PROGRESS.md)" "$(cat BRAINSTORM.md)")"`; `morning-brief.md` lives in `configs/skills/start/` alongside prompt.md; it instructs Claude to summarize state + list top 3 next steps; output to stdout, then exit

- [ ] **Create `configs/scripts/start.sh` — overnight mode** (shell script, NOT prompt.md)
  - Shell orchestrator: reads TODO → calls loop-runner.sh → calls /verify → parses output → creates fix tasks if needed → loops
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
  - Writes `.claude/morning-review.md` on finish by parsing `.claude/loop-cost.log`
  - verify-fail → fix task flow: `grep "FAILED_ANCHORS:" verify-output.txt` → write fix tasks → re-run loop-runner.sh
  - **"more work?" detection**: after committer.sh + claude -p sync, `grep -c "^\- \[ \]" filtered-tasks.md` to count remaining scoped tasks; if 0 → converged; if >0 → loop back (uses filtered-tasks.md, NOT full TODO.md)

- [ ] **Design gap: filtered-tasks.md convergence detection breaks after Bug 1 fix** — if workers no longer mark `- [ ]` → `- [x]` in the goal file (Bug 1 fix removes this), nobody updates filtered-tasks.md during the loop, so the "more work?" grep always returns the original unchecked count → start.sh loops forever; fix: start.sh should re-run `/orchestrate` at the start of EACH outer iteration to produce a fresh proposed-tasks.md → re-filter to filtered-tasks.md; convergence detection uses the freshly generated filtered-tasks.md count (based on /orchestrate's assessment of remaining work), NOT on worker-modified file mutations; this also means workers never need to touch the goal file → Bug 1 race condition is eliminated cleanly

- [ ] **Shell invocation gaps in start.sh patterns** — several shell call patterns in the plan are missing flags or have wrong ordering:
  - `/verify` call missing `--dangerously-skip-permissions` — /verify reads CLAUDE.md and test files via Claude tools; without this flag, `claude -p` prompts interactively for permissions in overnight mode → hangs forever
  - `/orchestrate` call missing `GOALS.md` + `PROGRESS.md` — only CLAUDE.md + TODO.md injected; orchestrate needs north star context to make good decisions; also needs PROGRESS.md to avoid regenerating already-done tasks; add both to the `printf` arg list
  - Optional docs not guarded: `cat BRAINSTORM.md` crashes if file doesn't exist (common after it's been processed and emptied) → the entire `printf` substitution fails; use `$(cat BRAINSTORM.md 2>/dev/null || echo "")` pattern for all docs that may be absent
  - `committer.sh` called BEFORE `claude -p sync` in the pass flow — `sync` modifies TODO.md + PROGRESS.md; commit must come AFTER sync; correct order: run `claude -p sync` first, then `committer "docs: sync" TODO.md PROGRESS.md`
  - `claude -p sync` call also needs `--dangerously-skip-permissions` — sync skill reads project files via Claude tools
  - `start.sh` needs `unset CLAUDECODE` at the top — when invoked via the /start skill's Bash tool call, `CLAUDECODE` is set by the parent session; without unset, any `claude -p` call inside start.sh fails with "nested sessions not supported"; same fix as loop-runner.sh line 41 to update docs

- [ ] **Add cost logging to loop-runner.sh** — after each run, append `COST: $X.XX DURATION: Xmin TASKS: N` to `.claude/loop-cost.log`; start.sh reads this to populate morning-review.md; without this, morning-review Cost field will be blank

- [ ] **Morning review format** (`.claude/morning-review.md`):
  ```
  ## Completed (N tasks, oracle approved)
  ## Skipped (N tasks — see .claude/skipped.md)
  ## Blockers (see .claude/blockers.md)
  ## Cost: $X.XX
  ## Suggested next step
  ```

- [ ] **Update `/orchestrate` skill to tag tasks with `Feature: <name>`** — each task block in proposed-tasks.md must include a `Feature:` line mapping to a phase/goal name in TODO.md; prerequisite for one-feature focus filtering in start.sh

- [ ] **Targeted mode** (`/start --goal "X"`) — skip orchestrate, run loop with specific goal, stop when done or failed

- [ ] **One-feature focus strategy** — each /start iteration locks ALL workers onto the same single highest-priority incomplete feature; workers still run in parallel (multiple workers, one goal), but no two features progress simultaneously; prevents cross-feature test pollution (borrowed from Anthropic long-running agent research)

- [ ] **30s plan approval window** — interactive mode only (default ON); overnight mode default OFF, enable with `--confirm`; after /orchestrate writes proposed-tasks.md, print plan + wait 30s; Ctrl+C aborts, timeout auto-continues

- [ ] **Session progress file** (`.claude/session-progress.md`) — written/updated by start.sh at the start of each iteration: current goal, tasks in flight, last completed, iteration count, cost so far; machine-readable for start.sh itself to resume after crash (not for /pickup — /pickup is for Claude context, start.sh is a shell process); format: simple key=value for easy shell parsing

---

### 11.5 — Drift Prevention Conventions

- [ ] **Add `# FROZEN` convention to CLAUDE.md template** — sections marked `# FROZEN` are strong-convention immutable for AI agents (not a hard filesystem lock — relies on prompt compliance)
  - Document the limitation clearly: prevents ~90% of accidental modifications, not 100%
- [ ] **Add BRAINSTORM proposal rule to `loop-runner.sh` `INSTRUCTIONS` heredoc** — inject into the same block as 3-tier rules: "If you discover a new approach or direction change, write it to BRAINSTORM.md with `[AI]` prefix. Never modify GOALS.md or VISION.md directly."
- [ ] **Inject BRAINSTORM rule into start.sh goal string** — since start.sh is a shell script (no supervisor prompt), the rule must be appended to the goal text passed to loop-runner.sh each iteration

---

### 11.8 — loop-runner.sh Known Bugs

- [ ] **Bug: workers race-condition on goal file marking** — loop-runner.sh lines 305 + 427 instruct every worker to change `- [ ]` to `- [x]` in the goal file; parallel workers editing the same file cause merge conflicts or silent overwrites; fix: remove goal-file marking from worker instructions; supervisor marks items done at the start of each iteration based on git log, not workers
  - Location: `INSTRUCTIONS` heredoc line 305, fallback wrapper line 427

- [ ] **Bug: auto-deploy checks only last commit, not full loop run** — loop-runner.sh line 461: `git diff --name-only HEAD~1 HEAD` misses configs/ changes from earlier iterations; fix: record start commit to state file at loop start (`state_write STARTED_COMMIT "$(git rev-parse HEAD)"`), then check `git diff --name-only $(state_read STARTED_COMMIT)..HEAD` at the end

- [ ] **Bug: non-code task silent failure** — worker runs doc/research task → no commit → supervisor sees no git change → may loop forever or declare false CONVERGED; fix: capture `ITER_START_SHA=$(git rev-parse HEAD)` before workers run each iteration, then check `git rev-list $ITER_START_SHA..HEAD --count` after run-tasks-parallel.sh returns; if 0 → inject into supervisor context: "Workers produced no commits this iteration. If this is expected (doc task), declare CONVERGED. If unexpected, treat as Tier 2 failure."; use SHA not timestamp (`--since`) to avoid clock drift / same-second precision issues

- [ ] **Bug + prerequisite: cost tracking requires `claude -p` JSON output** — Phase 11 plan requires `loop-cost.log`, but `claude -p` doesn't expose cost in plain-text output; verify: does `claude -p --output-format json` include token usage? If yes: parse and append to `.claude/loop-cost.log` after each supervisor call; if no: cost tracking requires a different approach (estimate from model + token count heuristic)

- [ ] **Bug: `git_recent_diff` uses wrong commit range** — loop-runner.sh line 226: `git diff HEAD~"$((iteration-1))"..HEAD` is incorrect — on iteration 1 this is `HEAD~0..HEAD` = empty diff; on iteration 3 it shows only last 2 commits by position, NOT the commits from this loop run specifically (if each iteration produces multiple commits, the count is off); this can mislead the supervisor into thinking less work was done; fix: same root cause as Bug 2 — record `STARTED_COMMIT` at loop start (`state_write STARTED_COMMIT "$(git rev-parse HEAD)"`), then use `git diff $(state_read STARTED_COMMIT)..HEAD --stat` here; the label "Files changed since loop started" becomes accurate; fix is shared with Bug 2 (same `STARTED_COMMIT` state key handles both)
  - Location: `line 226`, shares fix with auto-deploy Bug 2

---

### 11.7 — Safety Layer

- [ ] **Cost guard in `start.sh`** — read budget from `~/.claude/start-settings.json` (separate from orchestrator settings — start.sh is CLI-only and doesn't load the orchestrator); key: `overnight_budget_usd`; refuse to launch overnight mode if key missing and no `--budget N` flag; print estimated cost per iteration based on last run's cost log
- [ ] **Context management** — /start (shell) has no context of its own; workers manage their own context via existing handoff/pickup mechanism; /start only monitors wall-clock time and cost, not context %; remove context check from /start responsibilities
- [ ] **Entry point unification** — `start.sh` is the single entry point for both modes; morning mode: `start.sh --morning` (calls `claude -p` with morning skill prompt, exits after output); overnight mode: `start.sh` or `start.sh --overnight`; the skill `configs/skills/start/prompt.md` becomes a thin wrapper that calls `start.sh --morning` via Bash tool — avoids two separate things both called "/start"
- [ ] **Mode auto-detection** — `--goal "X"` → targeted (skip orchestrate); `--morning` → morning briefing; default (no flags) → overnight; TTY detection: if interactive terminal and no flags → default to morning (safer); if no TTY → overnight

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
