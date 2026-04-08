# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md/TODO.md, they're cleared.*

---

## Gap Findings (2026-04-07)

- [AI] Dead code found: `Condenser` ABC + 4 implementations (`NoOpCondenser`, `RecentEventsCondenser`, `LLMSummarizingCondenser`, `ObservationMaskingCondenser`) defined in `worker.py` lines 297–415 but never instantiated or invoked anywhere. The context window threshold check is missing — no condenser is created or called during worker execution. Fix: wire `ObservationMaskingCondenser` into `_build_task_file()` to truncate large tool outputs, and `RecentEventsCondenser` into the EventStream when log size exceeds threshold.

## Research Findings (2026-04-07) — Agentless (UIUC)

See full doc: docs/research/2026-04-07-agentless.md

- [AI] Research (Agentless): Structured localization pre-pass missing — Agentless runs three nested LLM calls (repo→files→functions→lines) before repair, producing JSON of suspected locations that constrains the repair prompt. Clade injects TLDR but doesn't structurally narrow to specific files/lines before the worker starts. Adding a haiku-based `_localize_fault()` call in `_build_task_file()` would tighten worker focus — see docs/research/2026-04-07-agentless.md §6A
- [AI] Research (Agentless): Reproduction test generation missing — Agentless generates a failing test from the issue description and uses it as a patch filter and verification signal. Clade has `_run_lint_check()` but no dynamic reproduction test. Adding this to `_on_worker_done()` before verify-and-commit would significantly improve fix verification quality — see docs/research/2026-04-07-agentless.md §6B
- [AI] Research (Agentless): Sequential reflection vs parallel patch sampling — Clade retries sequentially (up to 3×). Agentless generates 10 patches in parallel at temperature 0.8 and picks best via test re-ranking. For high-priority tasks, spawning N=3 swarm workers with different seeds then oracle-picking winner would improve quality without increasing wall time — see docs/research/2026-04-07-agentless.md §6C
