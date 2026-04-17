# BRAINSTORM — Resolved Items (archive)

Items originally collected in `BRAINSTORM.md` (the ideas inbox) that have been **RESOLVED**, **DEFERRED**, or superseded. Kept here for traceability — each RESOLVED line cites the file or hook that implemented it, so you can trace any current behavior back to the research that motivated it.

Research docs referenced below have all been moved into `docs/archive/` alongside this file.

---

## Last-Mile Quality Research (2026-04-10)

Source research: `docs/archive/2026-04-10-last-mile-quality.md`

- ~~Last-mile (Gap 1): Sprint contracts missing~~ — DEFERRED 2026-04-12: Task contracts exist (`acceptance_criteria` block in schema) but not a hard gate; promoting to hard gate is a larger worker.py refactor, deferring.
- ~~Last-mile (Gap 2): Self-evaluation failure~~ — DEFERRED 2026-04-12: Separate skeptical evaluator pass requires a second claude invocation per task; cost/latency tradeoff not yet justified.
- ~~Last-mile (Gap 3): No iteration cap~~ — RESOLVED 2026-04-12: `MAX_REFLECTION_RETRIES = 3` enforced in `worker.py:736` (gate: `self._reflection_retries < MAX_REFLECTION_RETRIES`).
- ~~Last-mile (Gap 4): No behavioral verification~~ — DEFERRED 2026-04-12: E2E smoke checks (curl/playwright) require per-project config; out of scope for generic orchestrator.
- ~~Last-mile (Gap 5): Context reset protocol~~ — DEFERRED 2026-04-12: ctx-checkpoint.md pattern (CAP) already in place; full harness-level reset requires Anthropic API changes.
- ~~Last-mile (Gap 6): No code health baseline gate~~ — DEFERRED 2026-04-12: `scan-health.sh` exists; wiring it as a worker spawn gate is a future enhancement.
- ~~Last-mile (Gap 7): Fix Rate metric missing~~ — DEFERRED 2026-04-12: `get_pass_at_k_metrics()` not yet in codebase; add when test infrastructure matures.

---

## OpenHands + SWE-bench 2025 Research (2026-04-08)

Source research: `docs/archive/2026-04-08-openhands-swebench-2025.md`

- ~~OpenHands (Gap 1): Shared TLDR cache across parallel workers~~ — ALREADY RESOLVED: `_tldr_cache` in `worker_tldr.py` is a module-level dict (process singleton). All workers in the same process share the cache via `_original_project_dir` key. mtime-based invalidation already handles freshness.
- ~~OpenHands (Gap 2): Agent-initiated context compression~~ — RESOLVED 2026-04-08 (prompt-level): Added "Context Checkpoint" instruction to all task files; workers instructed to write `.claude/ctx-checkpoint.md` summary before making edits (CAT pattern). Full tool-call-based compression remains future work.
- ~~OpenHands (Gap 3): Intramorphic testing~~ — RESOLVED 2026-04-08: `_capture_test_baseline()` + `_run_intramorphic_check()` added to `worker_utils.py`; baseline captured pre-edit for fix tasks, compared post-commit to detect newly-failing tests; regression warning injected into `failure_context`.

---

## Multi-Agent Coordination Research (2026-04-07)

Source research: `docs/archive/2026-04-07-multi-agent-coordination.md`

- ~~Multi-agent (Gap 1): No context versioning~~ — RESOLVED 2026-04-08: `context_version` INTEGER column added to tasks DB; `get_context_version()` counts completed tasks; `stamp_context_version()` called in `_build_task_file()`, injects staleness warning when codebase has changed since task was queued.
- ~~Multi-agent (Gap 2): No token budget per worker~~ — RESOLVED 2026-04-08: `token_budget` INTEGER column added to tasks DB; per-task and global (`worker_token_budget` setting) budgets enforced in reflection retry gate + post-run status check.
- ~~Multi-agent (Gap 3): Prose handoffs, no validation~~ — RESOLVED 2026-04-08: `_parse_task_schema()` + `_format_task_schema_block()` added to `config.py`; tasks can embed ```json envelope with acceptance_criteria/input_files/provides/requires; injected as "Task Contracts" block in task file; 7 tests added.
- ~~Multi-agent (Gap 4): No context archival after worker completion~~ — RESOLVED 2026-04-07: `_summarize_worker_completion()` added; `completion_summary` stored in tasks DB; injected into sibling workers via `get_recent_completions()` in `_build_task_file()`.
- ~~Multi-agent (Gap 5): SwarmManager sync barrier~~ — RESOLVED 2026-04-07: Code audit confirmed SwarmManager._refill_once() properly polls finished workers before claiming new tasks; barrier is implicit and correct.
- ~~Multi-agent (Gap 6): No circular dependency detection~~ — RESOLVED 2026-04-08: `_detect_dep_cycle()` (DFS cycle detection) added to `config.py`; wired into `TaskQueue.import_from_proposed()` (warns on import) and `SwarmManager._refill_once()` (sets `done_reason=blocked_cycle:...`).

---

## Claude Code Hooks Best Practices Research (2026-04-07)

Source research: `docs/research/2026-04-07-claude-hooks.md`

- ~~Hooks (Gap 1): Mark PostToolUse hooks as `async: true`~~ — RESOLVED 2026-04-08: Audit found only `post-edit-check.sh`, `edit-shadow-detector.sh`, and `memory-sync.sh` are async; `post-tool-use-lint.sh` and `failure-detector.sh` must remain sync because they inject feedback Claude needs to act on (exit 2 / hookSpecificOutput).
- ~~Hooks (Gap 2): Extend `pre-tool-guardian.sh` to include `updatedInput` rewrites for safe alternatives~~ — RESOLVED 2026-04-08: `pre-tool-guardian.sh` now returns `updatedInput` rewriting `--force`/`-f` to `--force-with-lease` for non-main/master branches.
- ~~Hooks (Gap 3): Add `Stop` hook for false-done prevention~~ — RESOLVED 2026-04-08: `stop-check.sh` added; blocks (exit 2) when uncommitted staged/unstaged files exist or `.claude/blockers.md` has entries; wired into `settings-hooks.json` + live `~/.claude/settings.json`.
- ~~Hooks (Gap 4): Add `"if"` field to hook matchers~~ — RESOLVED 2026-04-08: `revert-detector.sh` now has `"if": "Bash(git *)"` — skips process spawn entirely for non-git Bash commands. Applied to both `settings-hooks.json` and live `~/.claude/settings.json`.
- ~~Hooks (Gap 5): `updatedPermissions` in PermissionRequest handler~~ — RESOLVED 2026-04-08: `permission-request.sh` created; auto-allows read-only git/file/pytest patterns, injects `updatedPermissions` to persist rule in `localSettings`.
- ~~Hooks (Gap 6): Add `PostToolUseFailure` hook to inject diagnostic context~~ — RESOLVED 2026-04-08: `post-tool-use-failure.sh` created; injects tool-specific recovery hints (git status for Bash, re-read hint for Edit, Glob hint for Read).

---

## Ad-hoc Gap Findings (2026-04-07)

- ~~Dead code found: Condenser — RESOLVED 2026-04-08~~ `ObservationMaskingCondenser` wired into `_build_task_file()` (context block + message size guard, 8KB/2KB limits). `EventStream.get_recent_events()` added with inline RecentEvents compression. `LLMSummarizingCondenser` still unused — needs async call site.

---

## Moatless Tools Research (2026-04-08)

Source research: `docs/research/2026-04-08-moatless-tools.md`

- ~~Moatless: Two-phase search-then-identify missing~~ — RESOLVED 2026-04-07: `_localize_tldr_for_task()` added to `worker_tldr.py`; wired in `worker.py` `_build_task_file()` when TLDR > 4KB.
- ~~Moatless: StringReplace discipline in worker system prompt~~ — RESOLVED 2026-04-07: `_edit_discipline` block injected into every task file in `_build_task_file()` (commit 5f1fa30).
- ~~Moatless: Span-level FileContext with token budgeting~~ — RESOLVED 2026-04-08: `_span_evict_tldr()` added to `worker_tldr.py`; always preserves fault-localized files, evicts other spans until within `context_span_budget` (default 6000 chars); injects "Context Retrieval" hint when eviction happens.
- ~~Moatless: Typed search action names~~ — RESOLVED 2026-04-08: `_search_conventions` block injected into every task file with FindClass/FindFunction/FindSnippet/FindFile prompt patterns backed by Bash.

---

## AutoCodeRover Research (2026-04-07)

Source research: `docs/research/2026-04-07-autocoderover.md`

- ~~AutoCodeRover: On-demand AST query APIs missing~~ — RESOLVED 2026-04-08: `clade_search_class`, `clade_search_method`, `clade_search_code` added to `mcp_server.py`; AST-backed class/method search + grep code search; exposed as MCP tools.
- ~~AutoCodeRover: Two-phase separation missing~~ — RESOLVED 2026-04-08 (prompt-level): Injected explicit two-phase directive into fix task files ("Phase 1: explore, make NO changes → Phase 2: minimal targeted patch"). Full two-worker separation remains future work.
- ~~AutoCodeRover: SBFL pre-pass missing~~ — RESOLVED 2026-04-08 (simplified): `_sbfl_prepass()` added to `worker_tldr.py`; runs pytest --tb=short, parses failing test tracebacks for frequency-scored suspect functions; injects as "SBFL Pre-pass" block.
- ~~AutoCodeRover: Inline patch retry without subprocess restart~~ — RESOLVED 2026-04-07: `_run_with_context(use_continue=True)` now uses `claude -p --continue` for lint reflection retries.

---

## Sweep AI Research (2026-04-08)

Source research: `docs/research/2026-04-08-sweep-ai.md`

- ~~Sweep (Gap 1): Entity-level TLDR pruning missing~~ — RESOLVED 2026-04-08: `_prune_tldr_to_entities()` + `_extract_entity_name()` + `_parse_fault_entity_names()` added to `worker_tldr.py`.
- ~~Sweep (Gap 2): Caller hints for signature changes missing~~ — RESOLVED 2026-04-08: `_find_caller_hints()` added to `worker_tldr.py`; greps for callers of suspect functions; injected as "Caller hints" block.
- ~~Sweep (Gap 3): Post-worker test runner missing~~ — RESOLVED 2026-04-08: `_run_project_tests()` added to `worker_utils.py`; reads `test_cmd` from `.claude/orchestrator.json`, auto-detects pytest; called in `_on_worker_done()`.
- ~~Sweep (Gap 4): Hybrid context retrieval missing~~ — RESOLVED 2026-04-08: `_keyword_filter_tldr()` added to `worker_tldr.py`; pre-filters by code identifier keywords before haiku structural selection.

---

## Qodo Merge (PR-Agent) Research (2026-04-08)

Source research: `docs/research/2026-04-08-qodo-merge.md`

- ~~Qodo (Gap 1): Two-pass oracle missing~~ — RESOLVED 2026-04-08: `_oracle_pass()` helper added; `_oracle_review()` now runs spec-check first, then quality-check; short-circuits on spec failure.
- ~~Qodo (Gap 2): Per-finding fix suggestions missing~~ — RESOLVED 2026-04-08: `_format_oracle_rejection()` added; oracle prompt updated to request `findings: [{dimension, severity, fix_suggestion}]`; rejection reason now ordered numbered list.
- ~~Qodo (Gap 3): Diff chunking~~ — RESOLVED 2026-04-08: `_oracle_review` now chunks large diffs (>2500 chars) into 2000-char segments, reviews in parallel.
- ~~Qodo (Gap 5): Confidence scoring~~ — RESOLVED 2026-04-08: `confidence` field (high/medium/low) added to oracle prompt and response parsing; included in rejection reason as `[high] fix_guidance`.

---

## Community Harness Repos Research (2026-04-08)

Source research: `docs/research/2026-04-08-community-harness-repos.md`

- ~~Community: Linter config protection hook~~ — RESOLVED 2026-04-08: `linter-config-guard.sh` created; blocks `Edit|Write` to `.ruff.toml`, `biome.json`, `.eslintrc*`, `pyrightconfig.json`, `mypy.ini`, `.flake8`, etc.
- ~~Community: Structured observation contract~~ — RESOLVED 2026-04-08: `COMPLETION_CONTRACT_BLOCK` added to all task files; `_parse_observation_contract()` added to `worker_utils.py`; parsed in `_on_worker_done()` to extract `completion_summary` directly.
- ~~Community: Explicit `transition_reason` in worker state~~ — RESOLVED 2026-04-08: `transition_reason` field added to `Worker.__init__` and `to_dict()`; set at 4 key transitions.
- ~~Community: Two-level tool output compaction~~ — RESOLVED 2026-04-08: `micro_compact()` and `persist_large_output()` added to `worker_utils.py`.
- ~~Community: Identity re-injection after compaction~~ — RESOLVED 2026-04-08: PreCompact prompt updated to include `## Identity` section in compact-state.md; session-context.sh already re-loads at startup.
- ~~Community: EventBus JSONL lifecycle observability~~ — RESOLVED 2026-04-08: `EventStream.set_global_bus_path()` class method added; all `state_change` events aggregated to `.claude/events.jsonl`.
- ~~Community: Phase-boundary compact trigger~~ — RESOLVED 2026-04-08: Phase 1 exploration instructions updated to include explicit checkpoint step (write `.claude/ctx-checkpoint.md` before edits).
- ~~Community: Hook `id` + `description` fields~~ — RESOLVED 2026-04-08: All 21 hook entries in `settings-hooks.json` now have `"id"` and `"description"` fields.
- ~~Community: Pass@k metrics tracking~~ — RESOLVED 2026-04-08: `attempt_count` INTEGER column added to tasks DB; `TaskQueue.get_pass_at_k_metrics()` computes pass_rate, pass_at_1, pass_at_2; exposed at `GET /api/metrics/pass-at-k`.
- ~~Community: DreamConsolidator memory pruning~~ — RESOLVED 2026-04-10: `memory-sync.sh` now applies 5-gate check for memory paths.
- ~~Community: Bidirectional dep clearing~~ — RESOLVED 2026-04-08: `TaskQueue.clear_completed_dep()` added; called in `Worker._on_worker_done()` after auto-commit; atomically removes completed task ID from `depends_on` lists of siblings.

---

## Agentless (UIUC) Research (2026-04-07)

Source research: `docs/research/2026-04-07-agentless.md`

- ~~Agentless: Structured localization pre-pass missing~~ — RESOLVED 2026-04-08: `_localize_fault()` added to `worker_tldr.py`; wired for `type="fix"` tasks; haiku predicts suspect_files + suspect_functions and injects as "Suspected Change Locations" block.
- ~~Agentless: Reproduction test generation missing~~ — RESOLVED 2026-04-08: `_generate_repro_test()` added; asks haiku to write a failing pytest test; runs test to confirm it fails; injects as "Reproduction Test" block for fix tasks.
- ~~Agentless: Sequential reflection vs parallel patch sampling~~ — RESOLVED 2026-04-08: `parallel_fix_samples` setting added; when set >1 and task is critical-path, oracle-rejected tasks spawn N copies with diverse exploration hints.
