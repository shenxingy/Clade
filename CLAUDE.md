# Clade — Project Context

## Project Type
- Type: cli + skill-system
- Frontend: Vite + React + TypeScript UI under orchestrator/web/src/ (served from web/dist; not the primary interface)
- Backend: FastAPI (orchestrator/, port 8000) — optional, CLI layer works standalone
- Test command: cd orchestrator && .venv/bin/python -m pytest tests/ -v
- Verify command: cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 .venv/bin/python -m py_compile

## Features (Behavior Anchors)
- install.sh: running `./install.sh` copies skills/hooks/scripts/agents/output-styles to ~/.claude/ without errors, and activates no output style
- slt: running `slt` cycles the statusline mode (symbol → percent → number → off)
- /commit: creates repository-adaptive checkpoint commits and publishes when the active delivery or repository policy authorizes it
- /loop: given a goal file, runs supervisor+worker iterations until converged or max-iter
- committer: `committer "type: msg" file1 file2` stages only named files and commits
- loop-runner.sh: runs background loop — supervisor plans tasks, workers execute in parallel via worktrees

## What This Project Is

A multi-surface coding automation toolkit:

- **CLI layer** (`configs/`) — skills, hooks, scripts installed via `./install.sh`
- **Codex plugin** (`plugins/clade/`) — 25 generated native skills plus Codex hooks, distributed by `.agents/plugins/marketplace.json`
- **MCP package** (`mcp-package/`) — provider-selectable Claude/Codex execution for external MCP clients
- **Orchestrator layer** (`orchestrator/`) — FastAPI web server with worker pool, task queue, GitHub sync, iteration loops

## Key Commands

```bash
# Install CLI layer (skills, hooks, scripts, agents)
./install.sh

# slt — statusline-toggle (quota pace indicator). See /slt skill.

# Start orchestrator (from project root or orchestrator dir)
cd orchestrator && uvicorn server:app --reload

# Run tests
cd orchestrator && .venv/bin/python -m pytest tests/ -v

# Syntax check (all Python modules — same find-based sweep CI runs)
cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 .venv/bin/python -m py_compile

# Multi-machine usage tracking — see orchestrator/usage_tracker.py
#   Hub:  start orchestrator normally, optionally set usage_ingest_token in ~/.claude/orchestrator-settings.json
#   Node (no orchestrator): python3 configs/scripts/usage-agent.py --hub http://hub:8000 [--token X] [--once]
#   Dashboard: http://hub:8000/web/usage.html
# Per-machine ccusage data is stored in ~/.claude/orchestrator/usage.db.

# MCP server — exposes skills to external AI coding tools (Cursor, Cline, etc.)
# Inside Claude Code, skills are already native (/blog-write, /commit) — no MCP needed.
# The distributable mcp-package supports CLADE_RUNTIME=claude|codex. Do not add
# it inside Claude Code or Codex when native skills are installed: that duplicates
# every skill and spawns nested agent sessions. See mcp-package/README.md.

# Red-phase audit — run the tests a commit ADDS against its parent. One that
# already passes needed nothing from the change: it pins existing behaviour, or
# nothing. Covers the additive case judge_diversity.test_integrity is blind to
# (115 of the last 133 test-carrying commits here were purely additive).
# Measured on this repo: fires on ~17% of checked commits. Diagnostic, not a gate
# — a test that passes at base can be a deliberate characterization test.
# The interpreter is found automatically; RED_PHASE_PYTHON only overrides it.
# Pass an absolute path or a repo-relative one — a venv python is a symlink to
# the system python, so the script uses abspath rather than resolve() to avoid
# following that link out of the venv.
python3 configs/scripts/red-phase-audit.py 30

# Ask the instrument whether it can still go red. One positive and one negative
# control; CI runs this on every push. A harness that cannot fire reports a
# clean 0% exactly like a clean codebase — this one has done that before.
python3 configs/scripts/red-phase-audit.py --self-test

# Native Codex plugin — regenerate after changing a shipped canonical skill
python3 configs/scripts/regen-codex-plugin.py
python3 configs/scripts/regen-codex-plugin.py --check
```

## Architecture — Surfaces and Layers

### CLI Layer (`configs/`)
- `skills/` — skill prompts invoked via `/skill-name` in Claude Code
- `hooks/` — pre/post hooks for Claude Code events (wired via `settings-hooks.json`)
- `scripts/` — shell utilities (e.g., `committer.sh`)
- `agents/` — subagent definitions for the Agent tool
- `output-styles/` — system-prompt register overrides selected via `/config`. The
  only primitive here that edits the *system* prompt rather than appending a user
  message, so it reaches turns `CLAUDE.md` cannot. All ship
  `keep-coding-instructions: true` (omitting it silently drops Claude Code's
  built-in engineering instructions) and none is activated by `install.sh` —
  selection stays the user's.

**Correction-pairing pipeline** (the learn-from-corrections loop — captures the "AI did X → it got rejected" pair so a rule is grounded in the real diff, not just words):
- `edit-shadow-detector.sh` (PostToolUse, async) logs files Claude writes → session-keyed shadow at `/tmp/claude-edit-shadows/session-<session_id>.jsonl`

**Per-attempt checkpoints** (separate from the correction pipeline above): `worker-checkpoint.sh` (PostToolUse Edit|Write, async) commits the whole worktree into a shadow repo OUTSIDE it, once per agent write. A worker commits exactly once — at the end of verification — and `stop()` force-removes the worktree, so "correct at call 14, wrong at 15" had no record. A separate `--git-dir` means a separate index, so checkpoints cannot contend with the worker's own commits (measured, see `tests/test-hooks.sh`). The final SHA and count land in the evidence bundle before cleanup deletes the repo. Setting: `worker_checkpoint_shadow`.
- `revert-detector.sh` (PreToolUse Bash, async) on `git revert/reset/restore` cross-refs that shadow → writes `reverted_files` + `repeat` into `~/.claude/corrections/history.jsonl`
- `correction-detector.sh` (UserPromptSubmit, **sync**) on an explicit "that's wrong" surfaces those rejected files into the rule-extraction context
- **The gate is the wiring, not code:** the two silent-signal hooks are `async` (output never fed back) → a bare revert stays data-only; only an explicit correction (sync hook) escalates to context. `repeat=true` is stored for auto-audit but never auto-writes a rule (avoids noise).
- Shared helpers: `hooks/lib/correction-pair.sh` (session key + shadow read). `history.jsonl`/shadow are compact JSONL (one object per line). Tests: `tests/test-correction-pairing.sh`.

### Orchestrator Layer (`orchestrator/`)
Key modules (import DAG — leaf → root):

```
# Leaves (no project imports)
config.py            ← constants, settings, utilities
agent_runtime.py     ← agent-runtime ids + fail-closed validation
cascade_policy.py    ← pure verifier-aware cheap→strong eligibility, lineage, and signal helpers
fault_localize.py    ← multi-language SBFL: test-runner detection, go/js failure parsers, cross-lang symbol index (stdlib-only leaf; worker_tldr imports it)
agent_output.py      ← stdlib-only contract for reading a spawned agent's own usage report (stream-json/json → cost, tokens, per-model usage, prose projection)
pytest_report.py     ← stdlib-only pytest-output contract: colour-proof result parsing, verbosity normalization, colour-free subprocess env (shared by worker_utils, worker_tldr, evals/)
ideas.py             ← IdeasManager, async idea CRUD
process_manager.py   ← ProcessPool, start.sh lifecycle
worker_tldr.py       ← TLDR generation, localization, fault location, scoring (imports fault_localize)
worker_review.py     ← oracle + PR review
worker_utils.py      ← output helpers, lint reflection, LoopDetectionService, worker-state helpers
worker_hydrate.py    ← _pre_hydrate (GitHub issue/PR pre-hydration)
condensers.py        ← Condenser ABC + implementations
runtime_redaction.py ← stdlib-only secret/path redaction before persistence
evidence_bundle.py   ← versioned immutable attempt evidence + digest-chain contract
event_stream.py      ← crash-safe JSONL event logging
tracing.py           ← TracingService, task spans
reactions.py         ← ReactionExecutor
error_classifier.py  ← error classify/summarize + retry decisions
session_tree.py      ← SessionTree
usage_tracker.py     ← multi-machine ccusage ingestion (used by routes/usage.py)
compression_feedback.py ← compression UX feedback (consumed by /handoff skill)
execution_envelope.py ← versioned immutable execution contract (runtime/provider/protocol/model split)
worker_envelope.py   ← versioned terminal contract emitted by workers
handoff_registry.py  ← typed worker-handoff schemas + prompt-safe projections
reset_handoff.py     ← compact typed context seeds for clean loop resets
run_contract.py      ← repository-owned autonomous-run policy (optional CLADE_WORKFLOW.md)
run_budget.py        ← pure run-budget policy + trace attribution
merge_policy.py      ← truthful pull-request history selection
judge_diversity.py   ← deterministic review checks independent of the LLM oracle, plus 8 test-integrity signals (counted from the diff, fed to the oracle, never an auto-fail); scored by evals/run_hack_eval.py — 100% recall / 7.1% false alarms on a 30-case adversarial corpus
status_snapshot.py   ← provider-neutral status truth rendered by surface adapters
worker_phase_graph.py ← declared worker/task/loop lifecycle graph (additive observability)
compatibility_telemetry.py ← secret-free compatibility-window counters
eval_candidates.py   ← validated identifiers + digests for quarantined eval candidates
eval_metrics.py      ← read-only, denominator-explicit evidence/eval quality metrics
    ↑
# Mid-tier
github_sync.py       ← gh CLI wrappers (issues, push, sync)
task_schema.py       ← tasks.db DDL: table creation + additive ALTER migrations (leaf; task_queue imports it)
task_queue.py        ← SQLite tasks + append-only evidence persistence
routing_break_even.py ← production-only observational routing analytics
swarm.py             ← SwarmManager (extracted from worker.py)
worker_pool.py       ← WorkerPool: which workers exist and polling them (extracted from worker.py; re-exported there, bound to that module's Worker)
worker_taskfile.py   ← build_task_file: task file construction + context injection
worker_runtime.py    ← runtime-route resolution + durable selection failure
worker_evidence.py   ← attempt lifecycle + worker/verifier/delivery evidence projection
attempt_telemetry.py ← pure attempt-level routing/phase telemetry builders (imports cascade_policy)
provider_registry.py ← secret-safe live model discovery, TTL cache, pinned fallback
worker_routing.py    ← pure route decision: runtime, model, effort, audit reason
worker_provider.py   ← WHICH agent CLI a worker runs (claude vs codex command + env)
execution_backend.py ← HOW a worker process is spawned/torn down (lazy config import)
execution_resolver.py ← route + provider → immutable execution envelope
worker_status.py     ← worker status serialization kept out of the execution engine
eval_review.py       ← human review + atomic corpus promotion for eval candidates
eval_review_cli.py   ← standalone CLI to promote/reject quarantined eval candidates
    ↑
worker.py            ← Worker, WorkerPool — core execution engine
session.py           ← ProjectSession, registry, status_loop (lazy-imports task_factory/)
    ↑
# Roots
server.py            ← FastAPI app, remaining routes, mounts all routes/* routers
mcp_server.py        ← standalone MCP entrypoint exposing skills (stdio transport)
oracle_cli.py        ← standalone oracle gate CLI (strangler extraction; shim configs/scripts/oracle-review.sh)
routes/tasks.py      ← Task CRUD + bulk-action routes
routes/workers.py    ← Worker control + inspection routes
routes/webhooks.py   ← GitHub webhook handler
routes/ideas.py      ← Ideas API routes (CRUD, evaluate, execute, promote)
routes/process.py    ← Process manager API routes
routes/usage.py      ← Usage dashboard API routes
routes/evals.py      ← Human-review routes for quarantined eval candidates
routes/providers.py  ← Secret-safe provider/model registry inspection + refresh
```

Every `orchestrator/*.py` and `orchestrator/routes/*.py` must appear above —
CI's "Architecture map coverage" gate fails on any module missing from this file.

### Key File Map
| File | Purpose |
|------|---------|
| `config.py` | `GLOBAL_SETTINGS`, `_ALLOWED_TASK_COLS`, model aliases, cost utils |
| `agent_runtime.py` | Agent-runtime identity and fail-closed selection shared by routing/settings/factory |
| `cascade_policy.py` | Pure default-off verifier-cascade policy, escalation signals, and retry contract projection |
| `evidence_bundle.py` | Immutable `clade.evidence/v1` snapshots, lifecycle validation, and digest-chain verification |
| `task_schema.py` | `ensure_schema` — every CREATE TABLE and additive migration for tasks.db, split out of `task_queue._ensure_db` |
| `task_queue.py` | SQLite CRUD for tasks, loops, messages, interventions, and append-only attempt evidence |
| `routing_break_even.py` | Read-only production EvidenceBundle aggregation for observational routing break-even metrics |
| `worker.py` | `Worker`, `WorkerPool` — core execution engine |
| `swarm.py` | `SwarmManager` (extracted from worker.py; re-exported there) |
| `worker_pool.py` | `WorkerPool` — worker scheduling and polling. `worker.py` subclasses it to bind its own `Worker`, which keeps privately-loaded test copies private |
| `worker_taskfile.py` | `build_task_file` — task file construction + context injection |
| `worker_runtime.py` | Runtime route resolution and fail-closed task outcome persistence |
| `worker_evidence.py` | Evidence attempt lifecycle, Git/test/oracle/cost/artifact projection, and terminal delivery candidate |
| `worker_tldr.py` | `_generate_code_tldr`, `_score_task` — TLDR + scoring (leaf) |
| `agent_output.py` | `parse_agent_output` / `absorb_agent_result` — the agent's self-reported `total_cost_usd` and usage, and the prose projection every log consumer reads (leaf) |
| `pytest_report.py` | `parse_results` / `force_verbose` / `color_free_env` — the one definition of how pytest output is read back (leaf) |
| `worker_review.py` | `_write_pr_review`, `_oracle_review`, `_write_progress_entry` (leaf) |
| `oracle_cli.py` | Standalone oracle gate — same judge as the orchestrator, no server needed (`oracle-review.sh` shim; opt-in `/commit` gate via `CLADE_ORACLE_GATE=1`) |
| `worker_utils.py` | Output helpers, lint reflection, `LoopDetectionService`, worker-state helpers (leaf) |
| `session.py` | `ProjectSession`, `SessionRegistry`, `status_loop()` |
| `server.py` | FastAPI app, session/loop/swarm/usage/settings routes, WebSocket |
| `github_sync.py` | GitHub issue create/update/pull/push via `gh` CLI |
| `ideas.py` | `IdeasManager` — async idea CRUD, AI evaluation, promotion |
| `process_manager.py` | `ProcessPool`, `StartProcess` — start.sh lifecycle control |
| `usage_tracker.py` | Multi-machine ccusage ingestion (`~/.claude/orchestrator/usage.db`) |
| `routes/tasks.py` | Task CRUD, bulk actions, and on-demand verified evidence attempts |
| `routes/workers.py` | Worker control + inspection routes (9 handlers) |
| `routes/ideas.py` | Ideas API routes (CRUD, evaluate, execute, promote) |
| `routes/usage.py` | Usage dashboard API routes |
| `web/src/` | Vite + React + TypeScript UI source (App.tsx, components/, stores/, hooks/, lib/) |
| `web/index.html` | Vite shell (`<div id="root">` + main.tsx); server serves `web/dist` build when present |
| `web/usage.html` | Standalone usage dashboard (served at `/web/usage.html`) |

## Settings

Global settings stored at `~/.claude/orchestrator-settings.json`. Defaults defined in `config.py:_SETTINGS_DEFAULTS`. To add a new setting: add to `_SETTINGS_DEFAULTS`, NOT task_queue.py.

## DB Migrations

Add try/except `ALTER TABLE` blocks in `task_schema.py:ensure_schema()`. New columns added to `_ALLOWED_TASK_COLS` in `config.py`.

## Commits

```bash
# Always use committer script — NEVER git add .
committer "type: message" file1 file2 file3
```

Conventional commit types: `feat` / `fix` / `refactor` / `test` / `chore` / `docs` / `perf`

## CI (GitHub Actions)

Before committing, ensure CI will pass by running locally:
```bash
# 1. Python syntax check (all modules — same find-based sweep CI runs)
cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 .venv/bin/python -m py_compile

# 2. Tests, plus the two offline evals the same `pytest` job runs
cd orchestrator && .venv/bin/python -m pytest tests/ -v
cd orchestrator && .venv/bin/python evals/run_provider_conformance.py
cd orchestrator && .venv/bin/python evals/run_hack_eval.py

# 2b. Can the red-phase instrument still go red? One positive and one negative
#     control. A harness that cannot fire reports a clean 0% exactly like a
#     clean codebase — this one has shipped that failure before.
python3 configs/scripts/red-phase-audit.py --self-test

# 3. Shell syntax check (hooks, scripts, installer)
bash -n configs/hooks/*.sh configs/scripts/*.sh install.sh

# 4. mcp-package derived-copy drift gate — mcp-package/skills/ is generated
#    from configs/skills/ via the mcp-package/skills.list manifest. After
#    editing any skill shipped in the package, regenerate and commit:
configs/scripts/regen-mcp-package.sh

# 5. Codex plugin drift gate — same story, second generated surface
python3 configs/scripts/regen-codex-plugin.py --check   # regenerate without --check

# 6. Claude Code plugin manifest drift gate — third generated surface
python3 configs/scripts/regen-cc-plugin.py --check      # regenerate without --check

# 7. Doc facts drift gate — README/docs carry counts derived from the tree
#    (how many scripts, skills, hooks). ADDING A FILE MAKES THEM STALE and
#    fails CI, which is how this list grew: red-phase-audit.py moved the
#    Python-script count 21 → 22 while the READMEs still said 21.
python3 configs/scripts/doc-align.py verify             # doc-align.py sync to fix

# 8. Skill registry validation
python3 configs/scripts/validate-skills.py configs/skills

# 8b. Settings reference drift gate — templates/orchestrator-settings.example.json
#     is GENERATED from config.py:_SETTINGS_DEFAULTS. Adding a setting without
#     regenerating leaves docs/configuration.md's "every supported key" promise
#     false; it had drifted to 33 of 75 keys, one of them no longer a setting.
python3 configs/scripts/regen-settings-example.py --check   # regenerate without --check

# 9. Architecture map coverage — every orchestrator module listed in this file
python3 configs/scripts/check-arch-map.py

# 10. Reference resolution — every markdown link, anchor, and path resolves
python3 configs/scripts/check-references.py

# 11. Shellcheck (CI installs shellcheck; local may not). The `bash` prefix is
#     required — checks.sh is mode 100644, so invoking it directly exits 126 —
#     and the file list must match CI's, which is every hook and script plus
#     the installer. The line here used to be neither: it ran one file, and
#     did not run at all.
bash configs/scripts/checks.sh shellcheck configs/hooks/*.sh configs/scripts/*.sh install.sh

# 12. Every suite the `shell-tests` job runs — all 18, not a convenient subset
for t in loop checks skill-routing pr-scope-policy audit worktree-env \
         rule-injector mailbox-drain correction-pairing hooks \
         post-compact-reinject context-warning-drain ensure-dev-server \
         quiet-run scan-health pre-tool-guardian loop-args memory-watchdog; do
  bash "tests/test-$t.sh" >/dev/null || echo "FAILED: $t"
done

# 13. The install-test job (its own CI job, not part of shell-tests)
bash tests/test-install.sh

# 14. Plugin manifest validator + component resolution (separate workflow;
#     both need the claude CLI). --strict checks the manifest against a schema
#     and is blind to a schema-valid manifest that resolves nothing, which is
#     what this repo shipped: 37 agent paths loading as Agents (0).
claude plugin validate . --strict
bash configs/scripts/check-cc-plugin-components.sh

# 15. This list is a superset of CI — enforced, not merely asserted. It had
#     drifted twice (df802c3, then again by 2026-08-29) because the only thing
#     holding it was the sentence below telling you to keep it in sync.
python3 configs/scripts/check-ci-checklist.py
```

**Anything under `configs/scripts/` that CI runs in `syntax-check` must be
stdlib-only.** That job installs no project dependencies — it sets up Python and
goes straight to the gates. A gate that imports `orchestrator/config.py` pulls in
`aiosqlite` and dies there while passing on a developer machine that happens to
have it installed system-wide, which is exactly how the settings-reference gate
failed its first CI run after a clean local sweep. Parse what you need
(`ast.literal_eval`) rather than importing the module.

`tests/test-loop.sh` additionally asserts that the deployed
`~/.claude/scripts/loop-runner.sh` matches source. A stale local install fails
it with no repository defect — the fix is `./install.sh`, not a code change.

This checklist has now drifted twice. It covered 4 of 7 gates until 2026-08-22
(`df802c3`), then 7 of 11 `syntax-check` gates and 0 of 17 shell suites until
2026-08-29. **If you add a CI step, add it here in the same commit** — nothing
enforces that yet, which is precisely why it keeps recurring.

On push/PR to `main`, four workflow files fire:

- `ci.yml` — `syntax-check` (11 gates), `pytest` (suite + 2 offline evals),
  `shell-tests` (18 suites), `install-test`. `run_hack_eval.py` scores
  `judge_diversity.test_integrity` against the labelled reward-hack corpus in
  `evals/hack_cases/` — read its README before changing either, because that
  gate's floor and ceiling are measured, not chosen.
- `validate-plugin.yml` — `claude plugin validate . --strict` against the real
  plugin loader rather than a hand-rolled schema that would drift from it.
- `pr-honeypot-check.yml` — flags a PR body that echoes the `AGENTS.md`
  compliance token verbatim. An informational comment, never a block.
- `vouch-gate.yml` — closes issues and PRs opened by untrusted authors.

Three `ci.yml` jobs are key-gated and skip cleanly without credentials:
`real-api-loop` (workflow_dispatch or the weekly schedule — one live claude CLI
loop scenario, roughly $0.05, via `bash tests/test-loop.sh --real`),
`provider-live-anthropic`, and `provider-live-openai` (read-only catalog
smokes).

### Stacked PRs get no CI

Both `ci.yml` and `validate-plugin.yml` filter on `pull_request: branches:
[main]`, so a PR whose base is another feature branch runs only the honeypot
and vouch gates — the two that trigger on `pull_request_target` with no branch
filter. Retargeting such a PR to `main` does not help on its own either: a base
change emits `edited`, which is not one of `pull_request`'s default trigger
types. Close and reopen the PR (or push to its head) to get a real run, and
confirm the check list actually grew before reading green as evidence.

## Code Rules

- Keep all files < 1500 lines (Read tool default = 2000 lines)
- No circular imports — module deps must form a strict DAG
- Settings → `config.py:_SETTINGS_DEFAULTS` only
- DB migrations → try/except ALTER TABLE in `task_schema.ensure_schema()`
- Never return `error.message` in 500 responses
- If you fan out your own Task-tool subagents within one task: **serialize any
  subagent that writes/builds/runs tests** (they race on the same worktree's
  build artifacts and test state); reads (grep/analysis/research) may run in
  parallel freely. Geoffrey Huntley: uncoordinated parallel writers to shared
  build/test state is a real race, not a hypothetical one.

## Auto-Promoted Rules
<!-- Promoted from .claude/corrections/rules.md via /audit. Each rule lists its original recording date. -->

- **Explain mechanisms when summarizing** `[auto-promoted 2026-04-15 from 2026-03-30 summary-vs-explanation]`: When wrapping up a completed task, explain where the feature lives, how it's triggered, and what it produces — not just bullet-point outcomes. The user needs the "how" to trust and actually use the feature.

- **Processing external research into Clade** `[auto-promoted 2026-04-15 from 2026-03-31 research cluster × 5]`: When evaluating research on other tools/patterns (landscape docs, competitor analysis), don't mark anything `needs_work` without first: (1) verifying Clade's existing approach is demonstrably *deficient*, not just *different*; (2) comparing actual capabilities, not names (Ralph ≈ /loop — same supervisor-loop pattern, not a gap); (3) confirming the pattern applies to Clade's single-tool scope (Universal Hook Injection targets multi-tool orchestration — N/A here); (4) checking mechanism equivalence before claiming parity (`session-context.sh` ≠ Pi's `before_agent_start` hook — one is a shell script, the other fires between user message and agent `prompt()`). Once a gap IS confirmed, immediately modify code and verify — "plan changes" means "modify code, then verify", not "write TODO".

- **SVG → PNG export** `[auto-promoted 2026-04-15 from 2026-04-01 svg-rendering]`: Use `rsvg-convert`, not ImageMagick — ImageMagick mangles gradients, filters, and low-opacity elements. Also: strip unused `<defs>`, use Linux-available fonts (Helvetica/Arial, not `-apple-system`), and keep opacity ≥ 0.15 for visibility.

- **Domain-specific diagram conventions** `[auto-promoted 2026-04-15 from 2026-04-01 svg-diagram-accuracy]`: Before drawing a domain-specific diagram (cladogram, flowchart, architecture), research the type's established visual conventions. A cladogram uses right-angle bifurcating branches (horizontal + vertical lines), NOT radial/diagonal lines from a center point. Match the established visual language of the diagram type.
- [2026-04-11] config-tracking (deploy-gap): When adding a new ~/.claude/ config file, immediately check if configs/ tracks it and install.sh deploys it — not end with "want me to add it?". Should have run `diff ~/.claude/CLAUDE.md configs/CLAUDE.md` before asking. [auto-promoted 2026-05-11]
- [2026-04-12] prompt-hook-verbosity (settings-disconnect): Always add statusMessage to type:prompt hooks — without it Claude Code displays the full prompt text in the UI, blocking content. Should have noticed the missing statusMessage when writing the hook. [auto-promoted 2026-05-11]
- [2026-04-15] stop-hook-scope (edge-case): Stop-hook cleanliness checks must be session-scoped (baseline at SessionStart, diff at Stop), not repo-global — parallel CC sessions on the same repo cause deadlock when one session's dirt blocks another session's stop. Always pair a blocking Stop hook with an `stop_hook_active`+attempt-counter circuit breaker to escape LLM loops. [auto-promoted 2026-05-11]
- [2026-04-19] stop-hook-ack-loop (async-race): When a Stop hook blocks awaiting user input and the user hasn't replied yet, STOP GENERATING after ONE acknowledgment — every subsequent "等待授权"/"waiting" reply counts as a new turn, re-fires the Stop hook, and creates a response→hook→response cycle that burns tokens until ctrl-C. Circuit-breaker in the hook is defense #1 (see 2026-04-15), my own silence is defense #2 — if the same hook reason fires twice in a row with no user message in between, the next message MUST be the last until the user speaks. [auto-promoted 2026-05-11]
- [2026-04-20] upstream-design (edge-case): When designing an "absorb from external" system, scope the input space BEFORE the mechanics — (a) one upstream owner often ships many repos/clusters, so enumerate the full set, not just the one you first noticed; (b) the trust/review model (blind-sync vs curate-first) is the architectural spine, not a detail. Ask the user "what's your trust level per upstream?" before proposing file-diff logic. Should have fetched AgriciDaniel's profile on first mention of claude-seo instead of treating it as one isolated repo. [auto-promoted 2026-05-11]
- [2026-05-06] design-scope (edge-case): When designing a learning/automation/observability feature, default to ~/.claude/ universal scope unless the value is genuinely repo-local — not bake it into the project you happen to be sitting in. Cross-project applicability is the input dimension I keep missing: dotfiles deploy is global, memory-sync is global, hooks are global, so "learn from commits" should be too. Should have asked "does this live in ~/.claude/ or in <project>/?" before drafting architecture. [auto-promoted 2026-05-25]
- [2026-05-06] topic-pivot (edge-case): When the user's next message is in a domain with zero overlap with current conversation (e.g. commit-archeology → trial pricing strategy in a project with no pricing), ONE-line confirm scope before investing in investigation — wrong-session / mis-pasted prompts are a real failure mode. The 5-second "wait, is this for this repo?" check saves a 10-minute scan of a project that doesn't have the topic at all. [auto-promoted 2026-05-25]
- [2026-05-07] reduction-recommendation (deploy-gap): Before recommending "remove/disable X" to fix bloat, verify (a) X is actually running, (b) what value X provides beyond the immediate context, (c) whether the bloat is from X itself or from X-being-loaded-in-the-wrong-place. Recommended killing the clade MCP server to fix "95 skill descriptions dropped" without checking it was actively running, what external tools depend on it, or that the real issue was Claude-Code-as-MCP-client double-loading skills. Should have run `ps aux | grep mcp` and read the .mcp.json before proposing the cut. [auto-promoted 2026-05-25]
