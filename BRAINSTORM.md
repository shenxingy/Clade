# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md/TODO.md, they're cleared.*

---

## Research Findings (2026-04-07) — Multi-Agent Coordination Patterns

See full doc: docs/research/2026-04-07-multi-agent-coordination.md

- [AI] ~~Multi-agent (Gap 1): No context versioning~~ — RESOLVED 2026-04-08: `context_version` INTEGER column added to tasks DB; `get_context_version()` counts completed tasks; `stamp_context_version()` called in `_build_task_file()`, injects staleness warning when codebase has changed since task was queued.
- [AI] ~~Multi-agent (Gap 2): No token budget per worker~~ — RESOLVED 2026-04-08: `token_budget` INTEGER column added to tasks DB; per-task and global (`worker_token_budget` setting) budgets enforced in reflection retry gate + post-run status check.
- [AI] Multi-agent (Gap 3): Prose handoffs, no validation — task description is unstructured. For swarm tasks, use JSON envelope with input/output contracts. Medium effort.
- [AI] ~~Multi-agent (Gap 4): No context archival after worker completion~~ — RESOLVED 2026-04-07: `_summarize_worker_completion()` added; `completion_summary` stored in tasks DB; injected into sibling workers via `get_recent_completions()` in `_build_task_file()`.
- [AI] ~~Multi-agent (Gap 5): SwarmManager sync barrier~~ — RESOLVED 2026-04-07: Code audit confirmed SwarmManager._refill_once() properly polls finished workers before claiming new tasks; barrier is implicit and correct.
- [AI] ~~Multi-agent (Gap 6): No circular dependency detection~~ — RESOLVED 2026-04-08: `_detect_dep_cycle()` (DFS cycle detection) added to `config.py`; wired into `TaskQueue.import_from_proposed()` (warns on import) and `SwarmManager._refill_once()` (sets `done_reason=blocked_cycle:...`).

---

## Research Findings (2026-04-07) — Claude Code Hooks Best Practices

See full doc: docs/research/2026-04-07-claude-hooks.md

- [AI] ~~Hooks (Gap 1): Mark PostToolUse hooks as `async: true`~~ — RESOLVED 2026-04-08: Audit found only `post-edit-check.sh`, `edit-shadow-detector.sh`, and `memory-sync.sh` are async; `post-tool-use-lint.sh` and `failure-detector.sh` must remain sync because they inject feedback Claude needs to act on (exit 2 / hookSpecificOutput).
- [AI] ~~Hooks (Gap 2): Extend `pre-tool-guardian.sh` to include `updatedInput` rewrites for safe alternatives~~ — RESOLVED 2026-04-08: `pre-tool-guardian.sh` now returns `updatedInput` rewriting `--force`/`-f` to `--force-with-lease` for non-main/master branches.
- [AI] Hooks (Gap 3): Add `Stop` hook that runs tests + checks TODO checklist before allowing session end. Highest value for overnight autonomous loops — prevents false-done sessions. Medium effort. See §Gap 3
- [AI] Hooks (Gap 4): Add `"if"` field to hook matchers (e.g. `"if": "Bash(rm *|git push*)"`) to skip hook invocation for safe commands. Small effort, reduces overhead. See §Gap 4
- [AI] Hooks (Gap 5): Use `updatedPermissions` in `PermissionRequest` handler to inject persistent allow rules into `.claude/settings.local.json` after first approval. Small effort. See §Gap 5
- [AI] ~~Hooks (Gap 6): Add `PostToolUseFailure` hook to inject diagnostic context~~ — RESOLVED 2026-04-08: `post-tool-use-failure.sh` created; injects tool-specific recovery hints (git status for Bash, re-read hint for Edit, Glob hint for Read); wired into `settings-hooks.json` + live `~/.claude/settings.json`.

---

## Gap Findings (2026-04-07)

- [AI] ~~Dead code found: Condenser — RESOLVED 2026-04-08~~ `ObservationMaskingCondenser` wired into `_build_task_file()` (context block + message size guard, 8KB/2KB limits). `EventStream.get_recent_events()` added with inline RecentEvents compression. `LLMSummarizingCondenser` still unused — needs async call site.

## Research Findings (2026-04-08) — Moatless Tools

See full doc: docs/research/2026-04-08-moatless-tools.md

- [AI] ~~Research (Moatless): Two-phase search-then-identify missing~~ — RESOLVED 2026-04-07: `_localize_tldr_for_task()` added to `worker_tldr.py`; wired in `worker.py` `_build_task_file()` when TLDR > 4KB.
- [AI] ~~Research (Moatless): StringReplace discipline in worker system prompt~~ — RESOLVED 2026-04-07: `_edit_discipline` block injected into every task file in `_build_task_file()` (commit 5f1fa30).
- [AI] Research (Moatless): Span-level FileContext with token budgeting missing — agent gets static context blob; no span eviction, no on-demand retrieval, no token accounting. Medium effort but highest long-term impact for multi-file tasks. See §Gap 3
- [AI] ~~Research (Moatless): Typed search action names~~ — RESOLVED 2026-04-08: `_search_conventions` block injected into every task file with FindClass/FindFunction/FindSnippet/FindFile prompt patterns backed by Bash.

## Research Findings (2026-04-07) — AutoCodeRover

See full doc: docs/research/2026-04-07-autocoderover.md

- [AI] Research (AutoCodeRover): On-demand AST query APIs missing — Clade injects a one-shot TLDR snapshot but the agent can't ask follow-up structural questions. AutoCodeRover exposes 7 search APIs (search_class, search_method_in_class, search_code, etc.) backed by an AST index. Adoption: MCP tool (`clade_search`) reusing existing `_parse_python_ast` in worker_tldr.py — large effort, high impact for bug-fix tasks. See docs/research/2026-04-07-autocoderover.md §Gap 1
- [AI] Research (AutoCodeRover): Two-phase separation (context retrieval → patch generation) missing — Clade uses single end-to-end pass. Two sequential workers with Worker 2 receiving Worker 1's structured bug location report would reduce hallucination and keep patch-phase context lean — medium effort. See docs/research/2026-04-07-autocoderover.md §Gap 2
- [AI] Research (AutoCodeRover): SBFL pre-pass before patch attempt missing — run pytest --cov before first attempt, compute Ochiai scores per method, inject top-5 suspects as ranked hints into task file. Pre-hydration step, no agent changes needed — large effort, highest impact for bug-fix tasks. See docs/research/2026-04-07-autocoderover.md §Gap 3
- [AI] ~~Research (AutoCodeRover): Inline patch retry without subprocess restart~~ — RESOLVED 2026-04-07: `_run_with_context(use_continue=True)` now uses `claude -p --continue` for lint reflection retries, falling back to full restart if --continue fails.

## Research Findings (2026-04-08) — Sweep AI

See full doc: docs/research/2026-04-08-sweep-ai.md

- [AI] ~~Sweep (Gap 3): Post-worker test runner missing~~ — RESOLVED 2026-04-08: `_run_project_tests()` added to `worker_utils.py`; reads `test_cmd` from `.claude/orchestrator.json`, auto-detects pytest; called in `_on_worker_done()` after successful commit; failures injected into reflection retry.
- [AI] ~~Sweep (Gap 2): Caller hints for signature changes missing~~ — RESOLVED 2026-04-08: `_find_caller_hints()` added to `worker_tldr.py`; greps for callers of suspect functions from fault localization output; injected as "Caller hints" block in task file for fix tasks.
- [AI] Sweep (Gap 1): Entity-level TLDR pruning missing — worker sees entire TLDR; filter to only show entities relevant to the task description. Reduces context noise 3-5×. Medium effort.
- [AI] Sweep (Gap 4): Hybrid context retrieval missing — combine keyword grep + structural haiku selection in `_localize_tldr_for_task`. Medium effort.

---

## Research Findings (2026-04-08) — Qodo Merge (PR-Agent)

See full doc: docs/research/2026-04-08-qodo-merge.md

- [AI] ~~Qodo (Gap 3): Diff chunking~~ — RESOLVED 2026-04-08: `_oracle_review` now chunks large diffs (>2500 chars) into 2000-char segments, reviews in parallel, returns first rejection reason.
- [AI] Qodo (Gap 2): Per-finding fix suggestions missing — oracle returns single `fix_guidance`; should return `findings: [{dimension, severity, fix_suggestion}]` list. Worker applies fixes in order. Medium effort.
- [AI] ~~Qodo (Gap 5): Confidence scoring~~ — RESOLVED 2026-04-08: `confidence` field (high/medium/low) added to oracle prompt and response parsing; included in rejection reason as `[high] fix_guidance`.
- [AI] Qodo (Gap 1): Two-pass oracle missing — single haiku call reviews both spec-adherence and quality simultaneously; splitting into sequential spec-check + quality-check catches more issues. Medium effort.

---

## Research Findings (2026-04-07) — Agentless (UIUC)

See full doc: docs/research/2026-04-07-agentless.md

- [AI] ~~Research (Agentless): Structured localization pre-pass missing~~ — RESOLVED 2026-04-08: `_localize_fault()` added to `worker_tldr.py`; wired in `worker.py` `_build_task_file()` for tasks with type="fix"; haiku predicts suspect_files + suspect_functions and injects as "Suspected Change Locations" block.
- [AI] Research (Agentless): Reproduction test generation missing — Agentless generates a failing test from the issue description and uses it as a patch filter and verification signal. Clade has `_run_lint_check()` but no dynamic reproduction test. Adding this to `_on_worker_done()` before verify-and-commit would significantly improve fix verification quality — see docs/research/2026-04-07-agentless.md §6B
- [AI] Research (Agentless): Sequential reflection vs parallel patch sampling — Clade retries sequentially (up to 3×). Agentless generates 10 patches in parallel at temperature 0.8 and picks best via test re-ranking. For high-priority tasks, spawning N=3 swarm workers with different seeds then oracle-picking winner would improve quality without increasing wall time — see docs/research/2026-04-07-agentless.md §6C
