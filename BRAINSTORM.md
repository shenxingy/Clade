# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md/TODO.md, they're cleared.*

---

## Gap Findings (2026-04-07)

- [AI] ~~Dead code found: Condenser — RESOLVED 2026-04-08~~ `ObservationMaskingCondenser` wired into `_build_task_file()` (context block + message size guard, 8KB/2KB limits). `EventStream.get_recent_events()` added with inline RecentEvents compression. `LLMSummarizingCondenser` still unused — needs async call site.

## Research Findings (2026-04-08) — Moatless Tools

See full doc: docs/research/2026-04-08-moatless-tools.md

- [AI] Research (Moatless): Two-phase search-then-identify missing — when TLDR is large, add a haiku distillation call to pick top-5 relevant files before injecting. No index needed. Small effort, immediate value. See docs/research/2026-04-08-moatless-tools.md §Gap 1
- [AI] Research (Moatless): StringReplace discipline in worker system prompt — add uniqueness requirement + line-number strip instruction to task boilerplate. Prompt-only change, no code. See §Gap 2
- [AI] Research (Moatless): Span-level FileContext with token budgeting missing — agent gets static context blob; no span eviction, no on-demand retrieval, no token accounting. Medium effort but highest long-term impact for multi-file tasks. See §Gap 3
- [AI] Research (Moatless): Typed search action names (FindClass, FindFunction, FindSnippet) as prompt conventions backed by Bash — improves search discipline without real index. Medium effort. See §Gap 4

## Research Findings (2026-04-07) — AutoCodeRover

See full doc: docs/research/2026-04-07-autocoderover.md

- [AI] Research (AutoCodeRover): On-demand AST query APIs missing — Clade injects a one-shot TLDR snapshot but the agent can't ask follow-up structural questions. AutoCodeRover exposes 7 search APIs (search_class, search_method_in_class, search_code, etc.) backed by an AST index. Adoption: MCP tool (`clade_search`) reusing existing `_parse_python_ast` in worker_tldr.py — large effort, high impact for bug-fix tasks. See docs/research/2026-04-07-autocoderover.md §Gap 1
- [AI] Research (AutoCodeRover): Two-phase separation (context retrieval → patch generation) missing — Clade uses single end-to-end pass. Two sequential workers with Worker 2 receiving Worker 1's structured bug location report would reduce hallucination and keep patch-phase context lean — medium effort. See docs/research/2026-04-07-autocoderover.md §Gap 2
- [AI] Research (AutoCodeRover): SBFL pre-pass before patch attempt missing — run pytest --cov before first attempt, compute Ochiai scores per method, inject top-5 suspects as ranked hints into task file. Pre-hydration step, no agent changes needed — large effort, highest impact for bug-fix tasks. See docs/research/2026-04-07-autocoderover.md §Gap 3
- [AI] Research (AutoCodeRover): Inline patch retry without subprocess restart — reflection loop currently re-runs full claude -p subprocess on lint failure. Could use --continue instead for syntax-only failures, preserving agent context. Small effort. See docs/research/2026-04-07-autocoderover.md §Gap 5

## Research Findings (2026-04-07) — Agentless (UIUC)

See full doc: docs/research/2026-04-07-agentless.md

- [AI] Research (Agentless): Structured localization pre-pass missing — Agentless runs three nested LLM calls (repo→files→functions→lines) before repair, producing JSON of suspected locations that constrains the repair prompt. Clade injects TLDR but doesn't structurally narrow to specific files/lines before the worker starts. Adding a haiku-based `_localize_fault()` call in `_build_task_file()` would tighten worker focus — see docs/research/2026-04-07-agentless.md §6A
- [AI] Research (Agentless): Reproduction test generation missing — Agentless generates a failing test from the issue description and uses it as a patch filter and verification signal. Clade has `_run_lint_check()` but no dynamic reproduction test. Adding this to `_on_worker_done()` before verify-and-commit would significantly improve fix verification quality — see docs/research/2026-04-07-agentless.md §6B
- [AI] Research (Agentless): Sequential reflection vs parallel patch sampling — Clade retries sequentially (up to 3×). Agentless generates 10 patches in parallel at temperature 0.8 and picks best via test re-ranking. For high-priority tasks, spawning N=3 swarm workers with different seeds then oracle-picking winner would improve quality without increasing wall time — see docs/research/2026-04-07-agentless.md §6C
