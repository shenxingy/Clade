# Goal: Align-with-elites refactor — thin execution, read-only UI, round-2 sweep

Approved plan (2026-06-12, elite-workflows round-2 conclusion): durable value =
gates + context + learning loop; execution layers get commoditized by the
harness (background tasks, agent teams, Workflow) and platform (CMA). Clade
pivots: CLI layer = product center; orchestrator keeps observability + gates;
execution becomes an adapter; web UI becomes a read-only observation window.

Reference: BRAINSTORM.md round-2 entry, REFERENCES.md Elite Workflows Study.

## Workstream 1 — Execution backend adapter (worker.py seam)

Extract the worker spawn path behind an `ExecutionBackend` interface so the
local subprocess pool becomes ONE backend, not THE architecture:

- New leaf module `orchestrator/execution_backend.py`: `ExecutionBackend` ABC
  with `spawn(shell_cmd, env, cwd, log_path) -> handle`, `kill(handle)`,
  `is_alive(handle)`; `LocalSubprocessBackend` = exactly today's
  `create_subprocess_shell` semantics (setsid, log fd redirection, pid
  exposure). Byte-identical behavior with default settings.
- `worker.py` `Worker.start()` / kill path route through the backend; backend
  chosen via new `_SETTINGS_DEFAULTS` key `execution_backend` (default
  `"local"`). Settings rule: config.py only.
- Document (comments/docstring only, NOT implemented) the planned second
  backend: `claude-native` — Claude Code background tasks / remote tasks /
  agent teams as the execution surface, Clade supplies task file + gates.
- All existing tests stay green; add tests for backend selection + local
  backend contract (spawn produces live pid, kill terminates process group).

## Workstream 2 — Web UI → read-only observation window

- `orchestrator/web/src/`: remove task-creation / start / stop / retry /
  merge / bulk-action mutation controls from the React UI. KEEP all read-only
  views: sessions overview, worker logs, loop history, oracle verdicts, usage
  dashboard.
- Do NOT delete any HTTP API endpoints — scripts and tests consume them; only
  the UI surface goes read-only. Do NOT touch usage_tracker.py or
  routes/usage.py.
- Verify the UI still builds: `cd orchestrator/web && npm run build` (or
  `npx vite build`). dist/ is gitignored — do not commit build output.
- If a component becomes dead after control removal, delete the component
  file (dead-code sweep per fix discipline).

## Workstream 3 — Round-2 candidate sweep (from BRAINSTORM round-2 entry)

1. Judge hardening: pure judges (`PURE_JUDGE_FLAGS` in loop-runner.sh /
   start.sh / run-tasks*.sh, and `SETTING_SOURCES_NONE` claude -p call sites
   in orchestrator leaves) additionally pass `--disallowed-tools` for
   Edit/Write/Bash-class tools — a judge must not be able to mutate state
   (cookbooks: allowed gates prompting, disallowed gates availability).
   Mock-claude tests assert the flag split.
2. Friction log: workers get a standing instruction (worker_taskfile block +
   loop worker prompt) to append harness/tooling friction one-liners to
   BRAINSTORM.md under `[AI]` when a tool fights them; keep it to ≤2 lines per
   incident.
3. `input_examples` on mcp_server.py tool definitions (advanced-tool-use:
   72%→90% complex-param accuracy) — at minimum for run_skill/search tools in
   compact mode.
4. Strike-ladder reference doc `docs/structural-close-ladder.md` (lovesegfault
   N=4..7 templates: delete-reimplementation, make-function-total,
   single-emit-chokepoint, newtype split, precondition→postcondition) and link
   it from /audit ESCALATE-TO-STRUCTURAL.
5. Flake-verdict policy note in tests/test-loop-real.sh header: one SUCCESS =
   image good; three identical failures = content must change; never chase a
   single flake.

## Workstream 4 — Repositioning docs

- README + VISION (or CLAUDE.md "What This Project Is"): orchestrator
  described as "observability + gates + execution adapter", web UI as
  read-only observation; CLI layer is the product center. Keep README ≤300
  lines.

## Constraints (hard)

- `committer "type: msg" files...` for all commits — NEVER git add .
- Tests baseline 531 passed must not drop: `cd orchestrator &&
  .venv/bin/python -m pytest tests/ -q`
- `bash -n` every touched shell script; py_compile sweep for touched .py
- Shipped-skill edits → run `configs/scripts/regen-mcp-package.sh` and commit
  the derived copy (CI drift gate)
- Files < 1500 lines; import DAG stays acyclic (execution_backend.py is a
  leaf; worker.py may import it, never the reverse)
- Never return error text in 500 responses

## Convergence criteria (ALL must hold)

- [ ] `execution_backend.py` exists; worker spawn/kill routes through it;
      `execution_backend` setting in `_SETTINGS_DEFAULTS`; backend tests pass
- [ ] Web UI has no mutation controls and `npm run build` succeeds
- [ ] All 5 round-2 candidates landed (judge --disallowed-tools asserted by a
      mock test; friction-log block present in task files; input_examples in
      mcp_server; ladder doc linked from /audit; flake note in test-loop-real)
- [ ] README/VISION repositioned; README ≤300 lines
- [ ] Full local CI passes: pytest, py_compile sweep, bash -n, mcp-package
      drift gate clean
