# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md/TODO.md, they're cleared.*

---

## Go-To-Market Strategy (2026-04-11)

See full doc: docs/research/2026-04-11-go-to-market-strategy.md

**Platform priority:** HN Show HN (主攻) → r/ClaudeAI (核心社区) → Twitter/X (持续运营) → Product Hunt (背书) → DEV.to (SEO)

**Recommended HN title:** "Show HN: I built a correction-learning framework on Claude Code – Claude now learns from its own mistakes"

**One-liner:** "Claude Code is powerful. Clade makes it autonomous."

**Unique angles to exploit:**
- 过夜自主运行（overnight autonomous loops）— 无人做过此角度
- Correction Learning Loop — 技术新颖，HN 受众会买单
- `pip install clade-mcp` — Cursor/Windsurf 用户的独立入口
- Safety Guardian — "Claude 做了什么糟糕的事？" 是天然的故事钩子

**30天时间线:**
- Week 1: Twitter 预热 + r/ClaudeAI 首帖 + DEV.to 文章
- Week 2: **Show HN 主攻**（周二 PT 上午）→ Product Hunt 跟进
- Week 3-4: 持续内容运营，收集数据，迭代

---

## Research Findings (2026-04-10) — Last-Mile Quality / "烂尾" Problem

See full doc: docs/research/2026-04-10-last-mile-quality.md

- [AI] Last-mile (Gap 1): Sprint contracts missing — task files have no pre-negotiated acceptance criteria; worker decides "done" unilaterally. Need `acceptance_criteria` block as a hard gate, not just a hint.
- [AI] Last-mile (Gap 2): Self-evaluation failure — oracle is same model that generated code. Need a *separate* skeptical evaluator pass (different model or different prompt persona with no access to worker's reasoning).
- [AI] Last-mile (Gap 3): No iteration cap — workers can loop indefinitely on reflection retries. Research shows quality degrades after 3 iterations. Need `max_reflection_retries` hard cap (currently `MAX_REFLECTION_RETRIES` exists in worker_utils.py — verify it's enforced).
- [AI] Last-mile (Gap 4): No behavioral verification — tests pass ≠ feature correct. For web tasks, need E2E smoke check (curl / playwright). For orchestrator tasks: need "does the API endpoint return expected shape?" check post-deploy.
- [AI] Last-mile (Gap 5): Context reset protocol — `/compact` compresses but doesn't reset. Anthropic harness shows clean-context + progress file outperforms compaction. Relevant for long loop runs.
- [AI] Last-mile (Gap 6): No code health baseline gate — workers spawn on any codebase state. CodeScene research: defect risk 30%+ higher on structurally unhealthy code. Gate: run `scan-health.sh` before spawning worker, warn if health below threshold.
- [AI] Last-mile (Gap 7): Fix Rate metric missing — only binary pass/fail tracked. SWE-EVO: Fix Rate (% of failing tests repaired) reveals systematic progress. Add to `get_pass_at_k_metrics()`.

---

## Research Findings (2026-04-08) — OpenHands + SWE-bench 2025

See full doc: docs/research/2026-04-08-openhands-swebench-2025.md

- [AI] ~~OpenHands (Gap 1): Shared TLDR cache across parallel workers~~ — ALREADY RESOLVED: `_tldr_cache` in `worker_tldr.py` is a module-level dict (process singleton). All workers in the same process share the cache via `_original_project_dir` key. mtime-based invalidation already handles freshness.
- [AI] ~~OpenHands (Gap 2): Agent-initiated context compression~~ — RESOLVED 2026-04-08 (prompt-level): Added "Context Checkpoint" instruction to all task files; workers instructed to write `.claude/ctx-checkpoint.md` summary before making edits (CAT pattern). Full tool-call-based compression remains future work.
- [AI] ~~OpenHands (Gap 3): Intramorphic testing~~ — RESOLVED 2026-04-08: `_capture_test_baseline()` + `_run_intramorphic_check()` added to `worker_utils.py`; baseline captured pre-edit for fix tasks, compared post-commit to detect newly-failing tests; regression warning injected into `failure_context`.

---

## Research Findings (2026-04-07) — Multi-Agent Coordination Patterns

See full doc: docs/research/2026-04-07-multi-agent-coordination.md

- [AI] ~~Multi-agent (Gap 1): No context versioning~~ — RESOLVED 2026-04-08: `context_version` INTEGER column added to tasks DB; `get_context_version()` counts completed tasks; `stamp_context_version()` called in `_build_task_file()`, injects staleness warning when codebase has changed since task was queued.
- [AI] ~~Multi-agent (Gap 2): No token budget per worker~~ — RESOLVED 2026-04-08: `token_budget` INTEGER column added to tasks DB; per-task and global (`worker_token_budget` setting) budgets enforced in reflection retry gate + post-run status check.
- [AI] ~~Multi-agent (Gap 3): Prose handoffs, no validation~~ — RESOLVED 2026-04-08: `_parse_task_schema()` + `_format_task_schema_block()` added to `config.py`; tasks can embed ```json envelope with acceptance_criteria/input_files/provides/requires; injected as "Task Contracts" block in task file; 7 tests added.
- [AI] ~~Multi-agent (Gap 4): No context archival after worker completion~~ — RESOLVED 2026-04-07: `_summarize_worker_completion()` added; `completion_summary` stored in tasks DB; injected into sibling workers via `get_recent_completions()` in `_build_task_file()`.
- [AI] ~~Multi-agent (Gap 5): SwarmManager sync barrier~~ — RESOLVED 2026-04-07: Code audit confirmed SwarmManager._refill_once() properly polls finished workers before claiming new tasks; barrier is implicit and correct.
- [AI] ~~Multi-agent (Gap 6): No circular dependency detection~~ — RESOLVED 2026-04-08: `_detect_dep_cycle()` (DFS cycle detection) added to `config.py`; wired into `TaskQueue.import_from_proposed()` (warns on import) and `SwarmManager._refill_once()` (sets `done_reason=blocked_cycle:...`).

---

## Research Findings (2026-04-07) — Claude Code Hooks Best Practices

See full doc: docs/research/2026-04-07-claude-hooks.md

- [AI] ~~Hooks (Gap 1): Mark PostToolUse hooks as `async: true`~~ — RESOLVED 2026-04-08: Audit found only `post-edit-check.sh`, `edit-shadow-detector.sh`, and `memory-sync.sh` are async; `post-tool-use-lint.sh` and `failure-detector.sh` must remain sync because they inject feedback Claude needs to act on (exit 2 / hookSpecificOutput).
- [AI] ~~Hooks (Gap 2): Extend `pre-tool-guardian.sh` to include `updatedInput` rewrites for safe alternatives~~ — RESOLVED 2026-04-08: `pre-tool-guardian.sh` now returns `updatedInput` rewriting `--force`/`-f` to `--force-with-lease` for non-main/master branches.
- [AI] ~~Hooks (Gap 3): Add `Stop` hook for false-done prevention~~ — RESOLVED 2026-04-08: `stop-check.sh` added; blocks (exit 2) when uncommitted staged/unstaged files exist or `.claude/blockers.md` has entries; wired into `settings-hooks.json` + live `~/.claude/settings.json`.
- [AI] ~~Hooks (Gap 4): Add `"if"` field to hook matchers~~ — RESOLVED 2026-04-08: `revert-detector.sh` now has `"if": "Bash(git *)"` — skips process spawn entirely for non-git Bash commands. Claude Code's `"if"` field uses permission rule syntax; applied to both `settings-hooks.json` and live `~/.claude/settings.json`.
- [AI] ~~Hooks (Gap 5): `updatedPermissions` in PermissionRequest handler~~ — RESOLVED 2026-04-08: `permission-request.sh` created; auto-allows read-only git/file/pytest patterns, injects `updatedPermissions` to persist rule in `localSettings`; wired into `settings-hooks.json` + live `~/.claude/settings.json`.
- [AI] ~~Hooks (Gap 6): Add `PostToolUseFailure` hook to inject diagnostic context~~ — RESOLVED 2026-04-08: `post-tool-use-failure.sh` created; injects tool-specific recovery hints (git status for Bash, re-read hint for Edit, Glob hint for Read); wired into `settings-hooks.json` + live `~/.claude/settings.json`.

---

## Gap Findings (2026-04-07)

- [AI] ~~Dead code found: Condenser — RESOLVED 2026-04-08~~ `ObservationMaskingCondenser` wired into `_build_task_file()` (context block + message size guard, 8KB/2KB limits). `EventStream.get_recent_events()` added with inline RecentEvents compression. `LLMSummarizingCondenser` still unused — needs async call site.

## Research Findings (2026-04-08) — Moatless Tools

See full doc: docs/research/2026-04-08-moatless-tools.md

- [AI] ~~Research (Moatless): Two-phase search-then-identify missing~~ — RESOLVED 2026-04-07: `_localize_tldr_for_task()` added to `worker_tldr.py`; wired in `worker.py` `_build_task_file()` when TLDR > 4KB.
- [AI] ~~Research (Moatless): StringReplace discipline in worker system prompt~~ — RESOLVED 2026-04-07: `_edit_discipline` block injected into every task file in `_build_task_file()` (commit 5f1fa30).
- [AI] ~~Research (Moatless): Span-level FileContext with token budgeting~~ — RESOLVED 2026-04-08: `_span_evict_tldr(tldr, budget_chars, priority_files)` added to `worker_tldr.py`; always preserves fault-localized files (priority_files), evicts other spans greedily until within `context_span_budget` (default 6000 chars); when n_evicted>0 injects "Context Retrieval" hint instructing workers to use `clade_search_*` MCP tools for on-demand retrieval. Setting added to `config.py:_SETTINGS_DEFAULTS`.
- [AI] ~~Research (Moatless): Typed search action names~~ — RESOLVED 2026-04-08: `_search_conventions` block injected into every task file with FindClass/FindFunction/FindSnippet/FindFile prompt patterns backed by Bash.

## Research Findings (2026-04-07) — AutoCodeRover

See full doc: docs/research/2026-04-07-autocoderover.md

- [AI] ~~Research (AutoCodeRover): On-demand AST query APIs missing~~ — RESOLVED 2026-04-08: `clade_search_class`, `clade_search_method`, `clade_search_code` added to `mcp_server.py`; AST-backed class/method search + grep code search; exposed as MCP tools for interactive sessions.
- [AI] ~~Research (AutoCodeRover): Two-phase separation missing~~ — RESOLVED 2026-04-08 (prompt-level): Injected explicit two-phase directive into fix task files ("Phase 1: explore, make NO changes → Phase 2: minimal targeted patch"). Full two-worker separation remains as future work.
- [AI] ~~Research (AutoCodeRover): SBFL pre-pass missing~~ — RESOLVED 2026-04-08 (simplified): `_sbfl_prepass()` added to `worker_tldr.py`; runs pytest --tb=short, parses failing test tracebacks for frequency-scored suspect functions; injects as "SBFL Pre-pass" block; runs concurrently with repro test generation for fix tasks.
- [AI] ~~Research (AutoCodeRover): Inline patch retry without subprocess restart~~ — RESOLVED 2026-04-07: `_run_with_context(use_continue=True)` now uses `claude -p --continue` for lint reflection retries, falling back to full restart if --continue fails.

## Research Findings (2026-04-08) — Sweep AI

See full doc: docs/research/2026-04-08-sweep-ai.md

- [AI] ~~Sweep (Gap 3): Post-worker test runner missing~~ — RESOLVED 2026-04-08: `_run_project_tests()` added to `worker_utils.py`; reads `test_cmd` from `.claude/orchestrator.json`, auto-detects pytest; called in `_on_worker_done()` after successful commit; failures injected into reflection retry.
- [AI] ~~Sweep (Gap 2): Caller hints for signature changes missing~~ — RESOLVED 2026-04-08: `_find_caller_hints()` added to `worker_tldr.py`; greps for callers of suspect functions from fault localization output; injected as "Caller hints" block in task file for fix tasks.
- [AI] ~~Sweep (Gap 1): Entity-level TLDR pruning missing~~ — RESOLVED 2026-04-08: `_prune_tldr_to_entities()` + `_extract_entity_name()` + `_parse_fault_entity_names()` added to `worker_tldr.py`; wired in `_build_task_file()` after fault localization extracts suspect functions; 15 tests added.
- [AI] ~~Sweep (Gap 4): Hybrid context retrieval missing~~ — RESOLVED 2026-04-08: `_keyword_filter_tldr()` added to `worker_tldr.py`; `_localize_tldr_for_task()` now pre-filters by code identifier keywords before haiku structural selection; 4 tests added.

---

## Research Findings (2026-04-08) — Qodo Merge (PR-Agent)

See full doc: docs/research/2026-04-08-qodo-merge.md

- [AI] ~~Qodo (Gap 3): Diff chunking~~ — RESOLVED 2026-04-08: `_oracle_review` now chunks large diffs (>2500 chars) into 2000-char segments, reviews in parallel, returns first rejection reason.
- [AI] ~~Qodo (Gap 2): Per-finding fix suggestions missing~~ — RESOLVED 2026-04-08: `_format_oracle_rejection()` added to `worker_review.py`; oracle prompt updated to request `findings: [{dimension, severity, fix_suggestion}]`; rejection reason now ordered numbered list; 5 tests added.
- [AI] ~~Qodo (Gap 5): Confidence scoring~~ — RESOLVED 2026-04-08: `confidence` field (high/medium/low) added to oracle prompt and response parsing; included in rejection reason as `[high] fix_guidance`.
- [AI] ~~Qodo (Gap 1): Two-pass oracle missing~~ — RESOLVED 2026-04-08: `_oracle_pass()` helper added; `_oracle_review()` now runs spec-check first (does code match task?), then quality-check (bugs/security?); short-circuits on spec failure; chunked path unchanged.

---

## Research Findings (2026-04-08) — Community Harness Repos (learn-cc, claude-code-best, everything-cc)

See full doc: docs/research/2026-04-08-community-harness-repos.md

- [AI] ~~Research (community): Linter config protection hook~~ — RESOLVED 2026-04-08: `linter-config-guard.sh` created; blocks `Edit|Write` to `.ruff.toml`, `biome.json`, `.eslintrc*`, `pyrightconfig.json`, `mypy.ini`, `.flake8`, etc.; also detects `[tool.ruff/mypy/pylint]` sections in `pyproject.toml`; wired into `settings-hooks.json` PreToolUse `Edit|Write` + live `~/.claude/settings.json`
- [AI] ~~Research (community): Structured observation contract~~ — RESOLVED 2026-04-08: `COMPLETION_CONTRACT_BLOCK` added to all task files; workers instructed to end with `{"status","summary","next_actions","artifacts"}` JSON block; `_parse_observation_contract()` added to `worker_utils.py`; parsed in `_on_worker_done()` to extract `completion_summary` directly (skips haiku summarization call when contract present); blocked status surfaced in `failure_context`
- [AI] ~~Research (community): Explicit `transition_reason` in worker state~~ — RESOLVED 2026-04-08: `transition_reason` field added to `Worker.__init__` and `to_dict()`; set at 4 key transitions: `process_started`, `process_exited_rc_{n}`, `lint_retry_success`, `token_budget_exceeded`; exposed in worker API response for UI/tracing visibility
- [AI] ~~Research (community): Two-level tool output compaction~~ — RESOLVED 2026-04-08: `micro_compact(text, max_chars)` (head+tail window with omission marker) and `persist_large_output(text, output_dir, prefix)` (saves to file + returns compact reference) added to `worker_utils.py` (learn-cc s06); available for callers needing synchronous truncation without LLM; complements existing `_distill_output` (LLM-based) and `ObservationMaskingCondenser` (8KB gate)
- [AI] ~~Research (community): Identity re-injection after compaction~~ — RESOLVED 2026-04-08: PreCompact prompt updated to include `## Identity` section in compact-state.md format (learn-cc s17); agent saves role+project+task in one line before compaction; session-context.sh already re-loads compact-state.md at startup, so identity is restored automatically post-compact
- [AI] ~~Research (community): EventBus JSONL lifecycle observability~~ — RESOLVED 2026-04-08: `EventStream.set_global_bus_path()` class method added; all `state_change` events from all workers aggregated to `.claude/events.jsonl` in `{event, ts, worker_id, data}` format (learn-cc s18); called once in `WorkerPool.start_worker()` with `claude_dir / "events.jsonl"`
- [AI] ~~Research (community): Phase-boundary compact trigger~~ — RESOLVED 2026-04-08: Phase 1 exploration instructions updated to include explicit checkpoint step (step 4: write `.claude/ctx-checkpoint.md` before making edits); Phase 2 now begins "after checkpoint written" — semantically equivalent to `/compact` for non-interactive CLI workers (ECC strategic-compact pattern)
- [AI] ~~Research (community): Hook `id` + `description` fields~~ — RESOLVED 2026-04-08: All 21 hook entries in `settings-hooks.json` and live `~/.claude/settings.json` now have `"id"` (snake_case unique identifier) and `"description"` (human-readable purpose) fields; enables selective disabling and better hook debugging (ECC pattern)
- [AI] ~~Research (community): Pass@k metrics tracking~~ — RESOLVED 2026-04-08: `attempt_count` INTEGER column added to tasks DB (migrated); incremented in `WorkerPool.start_worker()`; `TaskQueue.get_pass_at_k_metrics()` computes pass_rate, pass_at_1, pass_at_2; exposed at `GET /api/metrics/pass-at-k` (ECC eval-harness pattern)
- [AI] ~~Research (community): DreamConsolidator memory pruning~~ — RESOLVED 2026-04-10: `memory-sync.sh` now applies 5-gate check for memory paths (specificity ≥80 chars, scope not draft/tmp, recency 5-60s skip, confidence <3 hedges, 24h per-topic cooldown via `~/.claude/memory/.sync-cooldown.json`)
- [AI] ~~Research (community): Bidirectional dep clearing~~ — RESOLVED 2026-04-08: `TaskQueue.clear_completed_dep(completed_task_id)` added; called in `Worker._on_worker_done()` after auto-commit; atomically removes the completed task ID from `depends_on` lists of all pending/queued sibling tasks (learn-cc s12)

---

## Research Findings (2026-04-07) — Agentless (UIUC)

See full doc: docs/research/2026-04-07-agentless.md

- [AI] ~~Research (Agentless): Structured localization pre-pass missing~~ — RESOLVED 2026-04-08: `_localize_fault()` added to `worker_tldr.py`; wired in `worker.py` `_build_task_file()` for tasks with type="fix"; haiku predicts suspect_files + suspect_functions and injects as "Suspected Change Locations" block.
- [AI] ~~Research (Agentless): Reproduction test generation missing~~ — RESOLVED 2026-04-08: `_generate_repro_test()` added to `worker_tldr.py`; asks haiku to write a failing pytest test; runs test to confirm it fails; injects as "Reproduction Test" block in task file for fix tasks; wired in `_build_task_file()`.
- [AI] ~~Research (Agentless): Sequential reflection vs parallel patch sampling~~ — RESOLVED 2026-04-08: `parallel_fix_samples` setting added to `config.py:_SETTINGS_DEFAULTS` (default=1); when set >1 and task is critical-path, oracle-rejected tasks spawn N copies with diverse exploration hints (`_DIVERSE_HINTS`) to encourage different solution paths; first to pass oracle wins. Cost-gated: non-critical tasks always use N=1.
