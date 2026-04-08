# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md/TODO.md, they're cleared.*

---

## Research Findings (2026-04-07) — Multi-Agent Coordination Patterns

See full doc: docs/research/2026-04-07-multi-agent-coordination.md

- [AI] Multi-agent (Gap 1): No context versioning — workers share state without version checks; stale context propagates silently. Fix: add `context_version` to task DB, increment after each worker batch. Medium effort.
- [AI] Multi-agent (Gap 2): No token budget per worker — unlimited token consumption possible. Fix: add `token_budget` field, enforce via existing `_parse_token_usage()`. Small effort.
- [AI] Multi-agent (Gap 3): Prose handoffs, no validation — task description is unstructured. For swarm tasks, use JSON envelope with input/output contracts. Medium effort.
- [AI] ~~Multi-agent (Gap 4): No context archival after worker completion~~ — RESOLVED 2026-04-07: `_summarize_worker_completion()` added; `completion_summary` stored in tasks DB; injected into sibling workers via `get_recent_completions()` in `_build_task_file()`.
- [AI] ~~Multi-agent (Gap 5): SwarmManager sync barrier~~ — RESOLVED 2026-04-07: Code audit confirmed SwarmManager._refill_once() properly polls finished workers before claiming new tasks; barrier is implicit and correct.
- [AI] Multi-agent (Gap 6): No circular dependency detection — no DAG validation at task decomposition. Add graph check before spawning batch. Small effort.

---

## Research Findings (2026-04-07) — Claude Code Hooks Best Practices

See full doc: docs/research/2026-04-07-claude-hooks.md

- [AI] Hooks (Gap 1): Mark PostToolUse hooks (`post-tool-use-lint.sh`, notification hooks) as `async: true` — currently they block Claude during verify_cmd. Small effort, immediate latency win. See §Gap 1
- [AI] Hooks (Gap 2): Extend `pre-tool-guardian.sh` to include `updatedInput` rewrites for safe alternatives (e.g. `git push -f` → `--force-with-lease`) instead of only blocking. Small effort. See §Gap 2
- [AI] Hooks (Gap 3): Add `Stop` hook that runs tests + checks TODO checklist before allowing session end. Highest value for overnight autonomous loops — prevents false-done sessions. Medium effort. See §Gap 3
- [AI] Hooks (Gap 4): Add `"if"` field to hook matchers (e.g. `"if": "Bash(rm *|git push*)"`) to skip hook invocation for safe commands. Small effort, reduces overhead. See §Gap 4
- [AI] Hooks (Gap 5): Use `updatedPermissions` in `PermissionRequest` handler to inject persistent allow rules into `.claude/settings.local.json` after first approval. Small effort. See §Gap 5
- [AI] Hooks (Gap 6): Add `PostToolUseFailure` hook to inject diagnostic context (recent changes, common fixes) when a tool fails. Reduces recovery turns. Small effort. See §Gap 6

---

## Gap Findings (2026-04-07)

- [AI] ~~Dead code found: Condenser — RESOLVED 2026-04-08~~ `ObservationMaskingCondenser` wired into `_build_task_file()` (context block + message size guard, 8KB/2KB limits). `EventStream.get_recent_events()` added with inline RecentEvents compression. `LLMSummarizingCondenser` still unused — needs async call site.

## Research Findings (2026-04-08) — Moatless Tools

See full doc: docs/research/2026-04-08-moatless-tools.md

- [AI] ~~Research (Moatless): Two-phase search-then-identify missing~~ — RESOLVED 2026-04-07: `_localize_tldr_for_task()` added to `worker_tldr.py`; wired in `worker.py` `_build_task_file()` when TLDR > 4KB.
- [AI] ~~Research (Moatless): StringReplace discipline in worker system prompt~~ — RESOLVED 2026-04-07: `_edit_discipline` block injected into every task file in `_build_task_file()` (commit 5f1fa30).
- [AI] Research (Moatless): Span-level FileContext with token budgeting missing — agent gets static context blob; no span eviction, no on-demand retrieval, no token accounting. Medium effort but highest long-term impact for multi-file tasks. See §Gap 3
- [AI] Research (Moatless): Typed search action names (FindClass, FindFunction, FindSnippet) as prompt conventions backed by Bash — improves search discipline without real index. Medium effort. See §Gap 4

## Research Findings (2026-04-07) — AutoCodeRover

See full doc: docs/research/2026-04-07-autocoderover.md

- [AI] Research (AutoCodeRover): On-demand AST query APIs missing — Clade injects a one-shot TLDR snapshot but the agent can't ask follow-up structural questions. AutoCodeRover exposes 7 search APIs (search_class, search_method_in_class, search_code, etc.) backed by an AST index. Adoption: MCP tool (`clade_search`) reusing existing `_parse_python_ast` in worker_tldr.py — large effort, high impact for bug-fix tasks. See docs/research/2026-04-07-autocoderover.md §Gap 1
- [AI] Research (AutoCodeRover): Two-phase separation (context retrieval → patch generation) missing — Clade uses single end-to-end pass. Two sequential workers with Worker 2 receiving Worker 1's structured bug location report would reduce hallucination and keep patch-phase context lean — medium effort. See docs/research/2026-04-07-autocoderover.md §Gap 2
- [AI] Research (AutoCodeRover): SBFL pre-pass before patch attempt missing — run pytest --cov before first attempt, compute Ochiai scores per method, inject top-5 suspects as ranked hints into task file. Pre-hydration step, no agent changes needed — large effort, highest impact for bug-fix tasks. See docs/research/2026-04-07-autocoderover.md §Gap 3
- [AI] ~~Research (AutoCodeRover): Inline patch retry without subprocess restart~~ — RESOLVED 2026-04-07: `_run_with_context(use_continue=True)` now uses `claude -p --continue` for lint reflection retries, falling back to full restart if --continue fails.

## Research Findings (2026-04-07) — Agentless (UIUC)

See full doc: docs/research/2026-04-07-agentless.md

- [AI] Research (Agentless): Structured localization pre-pass missing — Agentless runs three nested LLM calls (repo→files→functions→lines) before repair, producing JSON of suspected locations that constrains the repair prompt. Clade injects TLDR but doesn't structurally narrow to specific files/lines before the worker starts. Adding a haiku-based `_localize_fault()` call in `_build_task_file()` would tighten worker focus — see docs/research/2026-04-07-agentless.md §6A
- [AI] Research (Agentless): Reproduction test generation missing — Agentless generates a failing test from the issue description and uses it as a patch filter and verification signal. Clade has `_run_lint_check()` but no dynamic reproduction test. Adding this to `_on_worker_done()` before verify-and-commit would significantly improve fix verification quality — see docs/research/2026-04-07-agentless.md §6B
- [AI] Research (Agentless): Sequential reflection vs parallel patch sampling — Clade retries sequentially (up to 3×). Agentless generates 10 patches in parallel at temperature 0.8 and picks best via test re-ranking. For high-priority tasks, spawning N=3 swarm workers with different seeds then oracle-picking winner would improve quality without increasing wall time — see docs/research/2026-04-07-agentless.md §6C
