# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md/TODO.md, they're cleared.*

---

## Gap Findings (2026-04-07)

- [AI] Dead code found: `Condenser` ABC + 4 implementations (`NoOpCondenser`, `RecentEventsCondenser`, `LLMSummarizingCondenser`, `ObservationMaskingCondenser`) defined in `worker.py` lines 297–415 but never instantiated or invoked anywhere. The context window threshold check is missing — no condenser is created or called during worker execution. Fix: wire `ObservationMaskingCondenser` into `_build_task_file()` to truncate large tool outputs, and `RecentEventsCondenser` into the EventStream when log size exceeds threshold.
