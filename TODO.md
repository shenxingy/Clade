# TODO — Clade

> **This file is the single source of open work.** An unchecked `- [ ]` here
> is the only thing that means "not done yet". `VISION.md` says why the system
> exists, `IMPLEMENTATION_PLAN.md` is a completed dated plan, and `PROGRESS.md`
> is a dated journal — none of them carries open items, and none of them
> overrides this file. Decided 2026-08-29.

> Vision and architecture: see [VISION.md](VISION.md)

Phases 1–13 complete.

---

## Completed Phases

Phases 3 through 14, the 2026-04-07 tech-debt list and the EVALUATION-STANDARD
research gaps are complete. Their full checked history moved to
[docs/archive/TODO-completed-phases.md](docs/archive/TODO-completed-phases.md)
on 2026-09-02, so this file holds open work and its immediate context rather
than a mostly-closed ledger. Nothing was ticked or unticked in the move: every
section archived carried zero open items, measured section by section.

---

## Active execution program — reconciled 2026-07-28

These are the only promoted execution-program items from the research inbox.
Checked entries here have landed; unchecked entries remain active or
conditional. Historical checkboxes below are completion evidence, not a second
backlog.

- [x] **P0 · completed 2026-07-28 · MCP v2:** both MCP servers use typed SDK v2
  `on_*` handlers, require `mcp>=2.0.0,<3`, and negotiate the v1-era
  `2024-11-05` protocol over stdio.
- [x] **P0 · completed 2026-07-28 · security:** structured runtime redaction
  now sanitizes event/session/trace JSONL, SQLite runtime text, and piped
  provider stdout/stderr before persistence, with secret-free metadata.
- [x] **P1 · completed 2026-07-28 · evidence:** `clade.evidence/v1` now
  persists redacted, append-only attempt revisions with validated lifecycle
  transitions, canonical SHA-256 predecessor chains, and SQLite immutability
  guards.
- [x] **P1 · completed 2026-07-28 · evidence wiring:** worker attempts now
  capture execution, timing, exact Git SHAs, tests, oracle verdicts, optional
  artifacts, usage/cost, and delivery candidates; delivery exposes an
  attempt-linked projection, and task detail API/UI show verified bundles.
- [x] **P1 · completed 2026-07-28 · eval candidates:** incidents, oracle
  rejection/unreviewed/disagreement, managed reverts, and explicit corrections
  now create deduplicated, sanitized quarantine records pinned to an exact
  EvidenceBundle revision/digest. Human promotion remains the separate item
  below.
- [x] **P1 · completed 2026-07-28 · eval review:** explicit CLI/API review
  requires reviewer, reason, target, and a corpus-specific human label;
  promotion atomically writes non-overwriting oracle/resolve fixtures with
  exact evidence provenance, and rejection writes no corpus data.
- [x] **P1 · completed 2026-07-28 · supply-chain:** `/equip audit` records the
  exact upstream commit; `/equip sync` refreshes and compares it, and
  `--apply` fails closed on legacy reports or drift until a new audit is
  accepted.
- [x] **P2 · completed 2026-07-28 · regression metrics:** API/dashboard report
  denominator-explicit evidence completeness, exact-source integrity,
  confirmed false approvals, human overrides, candidate states, and accepted
  corpus coverage; empty denominators are `null`, never fake zeroes.
- [x] **P2 · completed 2026-07-28 · routing data:** immutable attempt evidence
  now records parent-attempt lineage, queue/inference/verify milliseconds,
  resolved runtime/connection/model/effort/reason, final oracle, and outcome;
  preflight/spawn failures keep explicit empty phases instead of fake zeroes.
- [x] **P2 · completed 2026-07-28 · routing replay:** offline matched-arm
  fixtures pin task digest, base tree, and deterministic verifier, then compare
  strong-self, native-cheap, and cheap→strong with denominator-explicit
  pass@1/pass@k, efficiency, queue, variance, and sample metrics.
- [x] **P2 · completed 2026-07-28 · routing policy:** default-off,
  verifier-aware routing permits one cheap attempt only for bounded,
  non-critical, high-readiness task classes with an explicitly deterministic
  project verifier. No diff, verifier failure/unavailability, retryable runtime
  error, oracle disagreement/unavailability/rejection, or scope expansion
  creates exactly one strong fallback with preserved lineage and execution
  contract; another cascade retry is never created.
- [x] **P2 · completed 2026-07-28 · routing analysis:** a production-only,
  read-only EvidenceBundle report groups task class/runtime/model/effort and
  exposes denominator-explicit success rate, success/$, success/wall-hour,
  deterministic 95% intervals, and independent-attempt break-even projections.
  Constructed/eval sources and unverifiable attempts are excluded visibly;
  fewer than 30 samples suppresses comparison, and observational data never
  emits or applies a causal routing recommendation.
- [x] **P2 · completed 2026-07-28 · provider registry:** native Claude/Codex
  profiles now drive TTL model discovery for Anthropic, OpenAI, MiniMax,
  Moonshot, custom OpenAI-compatible, and native-static catalogs. Execution
  binds the real native connection, records catalog/capability provenance,
  rejects cross-account cache reuse, and permits stale continuation only for
  an explicit pinned model with a visible degradation.
- [x] **P2 · completed 2026-07-28 · conformance:** six secret-free fixtures
  exercise Claude/Codex runtimes, all registry adapters, native profile
  binding, and Claude/Codex/MCP/generic surface semantics. Deterministic
  fixture replay runs on every CI build; separate manual/weekly Anthropic and
  OpenAI jobs perform credential-gated read-only catalog smoke. Discovery
  rejects non-HTTPS endpoints and redirects to prevent credential forwarding.
- [x] **P2 · completed 2026-07-28 · compatibility retirement window:** runtime
  routing, workers, status, task responses, and UI now use only
  `agent_runtime`; settings and SQLite migrations are idempotent; new task rows
  no longer dual-write `provider`; and old API inputs emit standard deprecation
  headers plus secret-free aggregate counters. The final input-alias/schema
  deletion is correctly conditional on one stable zero-use window, documented
  in `docs/COMPATIBILITY-RETIREMENT.md`, rather than guessed from green tests.
- [x] **P3 · completed 2026-07-28 · product metrics:** VISION and the dashboard
  now define verified delivery rate as the strict North Star (complete terminal
  evidence + approved oracle + eligible delivery / every terminal attempt).
  Evidence completeness, confirmed false approvals, human overrides, accepted
  regression coverage, and exact source integrity remain denominator-explicit
  guardrails that throughput cannot offset.
- [x] **P3 · completed 2026-07-28 · positioning and merge semantics:** public
  docs now describe Clade as a provider-neutral delivery control plane around
  identity, immutable evidence, verifier calibration, human-grounded
  correction learning, exact-SHA delivery, and fleet truth. Orchestrator
  auto-merge no longer hard-codes squash: live children preserve topology,
  one coherent commit rebases, and ambiguous multi-commit history stops for an
  explicit semantic choice.
- [x] **P0 · completed 2026-07-28 · local rollout and cleanup:** installed
  merged `main` into this server's Claude/Codex config, migrated the
  Orchestrator settings to current canonical fields without exposing or
  replacing user values, refreshed the local Codex plugin cache, and removed
  completed local/remote branch state. Final delivery returns to synchronized
  `main`.
- [ ] **Conditional watch:** add Beads-style agent-filed note-to-self entries
  only when measured loop-runner cross-iteration context loss recurs.
  *Condition checked 2026-08-29: not triggered — no such loss has been measured
  since the watch was filed. Still waiting on evidence, not on work.*
- [ ] **Conditional watch:** after one stable release reports zero compatibility
  events, reject `worker_provider`/task `provider` inputs and rebuild SQLite
  without the historical `tasks.provider` column.
  *Condition checked 2026-08-29: **not evaluable as written.**
  `~/.claude/compatibility-telemetry.json` has never existed on this machine and
  `read_compatibility_telemetry()` returns an empty window without creating it,
  so "zero events" is indistinguishable from "never observed" — and the second
  is not grounds for dropping a compatibility path. Discharging this watch needs
  a window that demonstrably ran: a `window_started_at` at least one release old
  with the counters present and at zero. Until the file exists, waiting longer
  produces no evidence.*

### Open decisions — 2026-08-29 ecosystem audit

These are judgement calls, not defect fixes: each has a working mechanism and a
default someone has to choose. Full context and the rejected-candidate list:
[2026-08-29-ecosystem-audit.md](docs/research/2026-08-29-ecosystem-audit.md).

- [x] **`worker_env_deny` — decided 2026-08-29: match on SHAPE, not on names.**
  An enumeration goes stale the moment a new secret variable appears, and a
  stale denylist reads exactly like a working one — which is how `[]` survived
  as the default for its whole life. Now `*_API_KEY`, `*_SECRET`, `*_TOKEN`,
  `*_PASSWORD`, `*_CREDENTIALS`, `*_PRIVATE_KEY`, `AWS_*`, `GOOGLE_*`, `GCP_*`,
  `AZURE_*` as fnmatch patterns, with `worker_env_allow`
  (`GH_TOKEN`, `GITHUB_TOKEN`) winning over them so a machine that authenticates
  `gh` by env var keeps its push. `ANTHROPIC_API_KEY` is deliberately not
  allow-listed: `worker_provider.apply_connection_env` re-injects it from the
  selected profile *after* the filter, and a test pins that ordering.
  **Operators upgrading:** a live `~/.claude/orchestrator-settings.json` that
  pins `"worker_env_deny": []` overrides this and keeps the control off.
- [x] **Spawn sandbox — decided 2026-08-29: built, and shipped default off.**
  It was recorded here as "a project, not a patch" on the belief that Landlock
  could not express "`.git` writable, `.git/hooks` not" — it is allow-list only,
  and a rule covers a whole hierarchy. **That belief was wrong, and measuring it
  is what showed so:** the hole is cut by walking from `/` to the protected path
  and allowing every sibling at each level, which leaves the blast radius at
  exactly the named paths. `orchestrator/worker_sandbox.py` protects the shared
  `.git/hooks` *and* `.git/config` (`core.hooksPath` reaches the same outcome by
  another route), applied at the one spawn chokepoint via `preexec_fn`. The
  ruleset is compiled in the parent, so the forked child pays only a `prctl` and
  one `landlock_restrict_self`.
  **Default off, because the cost is real and measured:** `git gc` and
  `git pack-refs` fail on the shared repository (both create a lock file
  directly in `.git`, and granting that would grant `.git/hooks` too), and new
  files cannot be created directly in the main checkout's root. Ordinary
  commits from the worktree are unaffected — the tests pin all of it, costs
  included. `worker_sandbox_fail_closed` (default on) refuses the spawn rather
  than running unconfined when Landlock is unavailable.
  `worker_git_surface_guard` stays: it is the detection that still works when
  this is off, or on a kernel without Landlock.
- [x] **Roadmap authority — decided 2026-08-29: this file, and it is checked.**
  Measured before deciding: of the four, only `TODO.md` carries open items
  (4 open / 217 done; the other three have zero checkboxes between them), so
  the de-facto answer was already this file — it just was not written down, and
  `VISION.md`'s milestone table had silently stopped at Phase 13 while this file
  tracked a completed Phase 14. Each of the four now opens with a one-line role
  header, and `configs/scripts/check-roadmap-authority.py` fails if a root
  roadmap document other than `TODO.md` grows an unchecked `- [ ]`, or if
  `TODO.md` loses its header. A convention nobody can violate by accident beats
  a paragraph asking them not to — which is the same reason the doc-count and
  CI-checklist gates exist. `BRAINSTORM.md` is an inbox, not a roadmap: its two
  conditional-watch entries were duplicates of items already tracked here, and
  its own header says an idea is cleared once it lands in `TODO.md`.
### Open decisions — 2026-08-30 software-fundamentals review

Both came out of reading Ng's *AI Engineering Skills Map* against this repo
(journal entry in [PROGRESS.md](PROGRESS.md)). Neither is a defect; each is a
choice with a real tradeoff, which is why they are recorded instead of built.

- [ ] **Decide whether invariants deserve a declarative home.** The article's
  sharpest point for a tool that *runs* agents is that an agent makes tradeoff
  decisions silently and never reports having made one. This repo enforces
  plenty of invariants — `OWN_FILES`/`FORBIDDEN_FILES`, `worker_git_surface_guard`,
  `worker_sandbox`, `judge_diversity`'s test-integrity signals, the oracle — but
  they live scattered across settings, per-task files, and code.
  `run_contract.py` looks like the natural home and is not: every key on it is
  an operational knob (`max_concurrency`, `retry`, `backoff`, `oracle_posture`,
  `auto_merge`), none is a statement of what must remain true.
  **Not built, deliberately:** collecting them into one declared artifact is an
  architectural fork with a real cost (a second place for a rule to be wrong,
  and a migration for every existing control), not a gap with an obvious
  implementation.
- [ ] **Decide whether to add dependency/supply-chain scanning.** There is no
  Dependabot config and no `pip-audit` / `npm audit` / CodeQL step; `#88` closed
  the *action-pinning* hole but scanning dependencies is a different question.
  **Not added along with `#88` on purpose:** that PR fixed an inconsistency in a
  control the repo had already chosen, whereas this would be a new capability
  with ongoing noise costs, and it deserves its own decision.

- [x] **Webhook authorisation — decided 2026-08-29: fail closed, and check the
  actor.** An unsigned event is now refused rather than warned about
  (`webhook_allow_unauthenticated` opts back in, deliberately), and
  `webhook_trust.is_trusted_actor` requires repo write access or an explicit
  vouch before any event can queue work. Bots are refused however they present.
  It fails CLOSED where `configs/scripts/vouch_check.py` fails OPEN — that
  script decides whether to close an issue; this one decides whether to hand
  someone an agent — and a test pins that their shared `TRUSTED_ASSOCIATIONS`
  has not drifted.

### Follow-on delivery hardening — 2026-07-29

Landed after the 2026-07-28 reconciliation above; not sourced from the
research inbox, so tracked separately rather than folded into the count above.

- [x] **delivery: safe abandonment transition** — added an `abandon`
  transition for superseded, unpublished delivery work: exact-head lease,
  non-empty reason, idempotent only for the same head+reason; published
  GitHub PR work may abandon only after a live forge check proves the PR is
  CLOSED (not OPEN/MERGED) at the recorded head (`9975895`). Abandonment now
  also discovers PRs by branch instead of trusting a possibly-stale
  `published` flag — an unrecorded OPEN PR blocks abandonment, and an
  unrecorded MERGED PR at the recorded head is flagged for reconciliation
  instead of mislabeled abandoned (`26e88ec`).
- [x] **task connection revalidation:** `PATCH /api/tasks/{id}` now
  re-validates the effective persisted connection against the effective
  runtime whenever either `connection` or `agent_runtime` changes (previously
  only a freshly supplied `connection` was checked) — an invalid
  connection/runtime pairing is now rejected at mutation time instead of
  first failing at execution (`c5a5c92`).
- [x] **Loop checkpoint recovery:** `loop-runner.sh` checkpoint recovery is
  now crash-safe and explicit — only an identity-matched `--resume` restores
  a checkpoint; a normal launch ignores a stale one, and `--help` has no side
  effects (`25949fe`).
- [x] **Codex plugin cache refresh:** bumped the installed Codex plugin cache
  version to pick up the delivery workflow changes that preceded Loop recovery
  (`8d93e1e`). Loop is a Claude/MCP skill and was installed separately from
  merged `main`.
- [x] **P0 · completed 2026-07-29 · Loop completion reconciliation:**
  supervisors bind tasks to exact goal line/text evidence; workers remain
  prohibited from editing the shared goal; and the coordinator marks items
  only after worker, syntax, test, and final verification gates pass.
  Iteration progress now counts commits created directly by workers as well as
  the leftover sweep. Deterministic regressions cover fail-closed stale
  evidence, idempotence, failure propagation, worker commit accounting, and
  same-iteration `converged`.

## Tech Debt

- [x] 🟡 Migrate the orchestrator MCP servers to the Python SDK v2 API, then
  remove the `mcp<2` compatibility bound — **SUPERSEDED 2026-07-28** by the
  dependency-labelled P0 item above
  ([upstream v2 breaking-change context](https://github.com/modelcontextprotocol/python-sdk/issues/1068))
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
- [x] 🟡 `priority_score` column added but nothing writes to it — Phase 10 priority ranker is a schema-only stub with no scoring logic (`orchestrator/worker.py`)
- [x] 🟡 No CORS middleware on FastAPI app — mobile/remote access via Caddy HTTPS (stated in VISION) will fail with CORS errors (`orchestrator/server.py:72`)
- [x] 🔵 `schedule` endpoint error message incorrect — said "ISO 8601" but parser only accepts `HH:MM`; fixed to "Use HH:MM (24h), e.g. 09:00" (`orchestrator/server.py:471`)
- [x] 🟡 Skill name collision with Claude Code built-ins — spike run 2026-07-10, **VERDICT: keep the shared names permanently (won't-rename)**. Full sweep of 584 raw matches showed the old "~37+34 refs" estimate conflated infra paths (`logs/loop`, `.claude/loop-state`, REST routes `/api/sessions/{id}/loop/*`, `verify_backlinks.py`) with skill-name refs — orchestrator .py + tests/test-loop.sh contain **zero** Clade-skill refs. But the true rename cost is *larger*: /loop 123 + /review 66 + /verify 83 refs ≈ **~193 manual edits** after excluding regenerated mcp-package mirrors and append-only history, plus four classes of un-greppable breakage: (1) MCP tool names derive from skill dir names — external Cursor/Cline configs break silently; (2) `configs/templates/VERIFY-*.md` already stamped `Managed by /review skill` into downstream projects; (3) `start.sh:895` hard-cats `~/.claude/skills/verify/prompt.md` on installed machines; (4) muscle memory. Collision risk is already neutralized: `/verify` is `user_invocable: false` (typed always hits built-in — now locked by VERIFY.md SC23), built-in `/loop` is TUI-level with a different arg shape and doesn't co-appear in the model's skill list, `/review` is the only true dual listing but both descriptions cross-route — **zero misroute incidents since disambiguation shipped (2026-04-17 / 2026-06-04)**. Both proposed target names rejected: `/verify-all` would newly prefix-collide with `/verify`; `/converge` orphans the `/loop`↔`/iloop` pair. Contingency: if a real `/review` misroute pattern ever emerges, rename only `/review → /coverage`.
- [x] 🔴 `redact.py` had no pattern for underscore-style API keys — DONE 2026-09-02. `generic_secret_key` added after `stripe_key`, and `stripe_key` widened to cover test keys. `checks.sh`'s inline fallback carries the same shape now, with an explicit leading boundary because POSIX ERE has no portable `\b` and the prefix sits inside the ordinary word `task_`; `tests/test-checks.sh` pins both directions. **The provenance sentence in the original item was withdrawn:** the claim that such a key sat in `history.jsonl` until the radar run removed it could not be substantiated on disk. The pattern gap was real and is demonstrated; the incident was not.
- [x] 🔴 Correction capture wrote raw user prompts to disk — DONE 2026-09-02. Redaction runs once, after the correction gate (so python3 does not spawn on prompts that write nothing) and before `cp_bound_prompt` (clipping first can cut a token below its detection threshold). The filed item missed a **third** write: the lib-missing fallback branch leaked the same prompt. The prescribed sed fallback turned out unsafe — fixed-count patterns mask only a token's prefix, measured leaving 16 of 48 characters on disk — so the degraded path detects and withholds the whole prompt instead.
- [x] 🟡 `reverted_files` is not a revert set — DONE 2026-09-02. Now the intersection with the command's own pathspec; the loose session list survives as `session_files`. `git revert` and `git reset --hard` genuinely cannot yield a file set and the hook is async, so those record `revert_scope` and leave `repeat` null rather than substituting a guess. `correction-detector.sh` unions `session_files` back in so the injected signal keeps its breadth.
- [x] 🔵 `session-scorecard.sh` awk parsed one JSONL style — DONE 2026-09-02, and it was **not** latent. The three-argument `match()` errors on mawk, the default `awk` here, and a trailing `|| echo 0` turned that into a plausible zero: both correction counters had been structurally 0 for the life of the file. Rewritten on `jq`, which the script already hard-depends on. `tests/test-session-scorecard.sh` is new and runs in CI.

---

### Full-project audit — 2026-09-02

Filed after a two-pass audit, then **verified finding by finding against the
code before any of it was implemented**. That verification pass is the most
useful thing in this section: roughly half the original specifics were wrong
while the symptoms were mostly right, and four items turned out to be
non-defects. Each entry below records the correction, because an item closed on
a false premise is a trap for the next reader.

Every enforced gate was green at audit time — 13 syntax-check gates, pytest,
both offline evals, all shell suites, shellcheck, `tsc`, `npm audit`, zero
import cycles, zero CI failures in 30 runs. Nothing here was findable by
re-running the gates.

- [x] 🔴 **The orchestrator control plane had no authentication** — DONE 2026-09-02, and it was worse than filed. `orchestrator/start.sh` binds `0.0.0.0` whenever it detects Tailscale, and that is the documented way to run the server, so the exposure was the whole tailnet rather than 40 local accounts; the port is 8765, not 8000. `GET /api/settings` returned `webhook_secret` and the usage tokens in plaintext. Worst: `/ws/chat` **starts** a `claude --dangerously-skip-permissions` PTY if none is alive and forwards keystrokes into it, so it was unauthenticated remote code execution, not merely an open control plane. Closed with default-deny ASGI middleware (not per-route `Depends`: `BaseHTTPMiddleware` never sees a websocket scope, and a dependency on 93 decorators is one the 94th forgets), a token minted on first start into a 0600 file, secret masking on the way out, and a test that walks the real route table. `caddy-setup.sh` does add Basic Auth but only in front of a public domain, never the socket.
- [x] 🟡 `goal-cc-codex-adaptation.md` leaked ten open items past the roadmap gate — DONE 2026-09-02. All **ten** were delivered, not eight; the file was archived with a per-requirement outcome table rather than deleted. The gate now checks **location**, not checkbox state: gating on state would have broken `/loop`, which reads `- [ ]` out of a goal file as its work queue. It judges tracked files only — the first version globbed the directory and immediately false-positived on `tests/test-loop.sh`'s throwaway fixture.
- [x] 🟡 The 2026-08-31 radar run's output was uncommitted — DONE 2026-09-02. Three cross-project rules moved to the global instruction file; four that name this repo's own tooling stayed.
- [x] 🟡 **`worker.py` is a 30-import hub — the finding was wrong.** Verification measured the topology: `worker_routing` is not imported by `worker.py` at all, and five siblings have consumers besides it, so it is not the star the item described. The by-responsibility split it demanded is unavailable for a 60-attribute stateful class without mixins, which contradict this file's own cohesion rule. What was real: four dead import lines, now removed (28, not 30). The "15 modules per component" count also treated a shared name prefix as a component boundary; those 15 serve five different consumers.
- [x] 🟡 Two files sat within 100 lines of the 1500-line gate — DONE 2026-09-02. `worker_tldr.py` 1459 → 735 with a new `repo_map.py` (762): the split is by responsibility, not one more leaf — repository-structure analysis is pure and synchronous, the half that stays spends money. `loop-runner.sh` 1407 → 1143 with a new `loop_verify.sh` (286). The census in the original item was wrong three ways: **two** files were within 100 lines, not three; the third-closest was `tests/test-loop.sh` at 1434, which the item never mentioned and which this very split pushes closer; and "eight above 1100" was fifteen, three of them generated copies whose split would cost a regen cycle. No rule actually says a file within 100 lines of the ceiling is blocked — the rule is a hard 1500, and the case for acting early rests on this repo's two recorded ceiling collisions.

- [x] 🟡 Nothing built the web UI — DONE 2026-09-02, with three corrections. The dist-absent fallback did **not** serve the legacy `app-*.js` UI: `index.html` became the Vite shell in `7d5603b`, so the fallback served a page no browser can boot, and those 2705 lines had been unreachable since. eslint is absent from the lockfile entirely, so `npm run lint` was never runnable and an eslint config would not have fixed it. Two defects the audit missed and the fix covers: `GET /` served the un-built shell even where `dist` existed, and `/web/usage.html` 404'd once `dist` existed because vite copies no `publicDir`. Committing `dist` was never an option — already ruled out in `docs/goals/align-elites.md`.
- [x] 🟡 Settings keys published and read by nothing — DONE 2026-09-02. **Four, not five.** `replay_interrupted_on_startup` was a false positive: it is read in `config.py` and called from `lifespan` on every startup, and the audit's detector excluded all of `config.py` rather than just the defaults literal. `reactions_enabled` and `min_workers` are wired; `reaction_configs` and `patrol_auto_ideas` are deleted. Wiring `reaction_configs` as published would have been harmful — its copy carries three of five rules and the executor replaces rather than merges, so anyone using the generated reference file would silently lose two. `test_every_setting_has_a_backend_reader` now enforces the invariant.
- [x] 🟡 `mcp_server.py` blocked its event loop for five minutes — DONE 2026-09-02. `asyncio.create_subprocess_exec` + `wait_for`, with the timeout path SIGKILLing the process group and draining pipes. Recorded as an invariant in CLAUDE.md, because the same shape exists on the second MCP surface.
- [x] 🟡 Release drift — DONE 2026-09-02. v0.3.1 cut across every surface. The mcp-package half needed **five** sites, not one, including `SERVER_VERSION`, which is what the MCP server tells connecting clients. **No tag created — publishing is an operator decision.**
- [x] 🟡 No Python lint gate — DONE 2026-09-02, and it earned its keep on the first run: two live `NameError`s that had shipped green for months. `Worker.stop()` awaited an unimported `preserve_worktree_wip`, so every worker stop path raised before cleanup. Both fixed, both suppressions deleted in the same commit. `BLE001` is deliberately not selected: 435 blind excepts is a body of work, not a gate.
- [x] 🟡 Fixed `/tmp` paths on a shared host — DONE 2026-09-02. All seven sites go through `configs/hooks/lib/runtime-dir.sh`, which fails closed on a squatted path.
- [x] 🟡 Shell portability — PARTIALLY DONE 2026-09-02, and **half the finding was false**. All eight `stat -c` sites already had a `stat -f` fallback; the `mapfile` hit was a comment saying mapfile is deliberately avoided; the `awk match(` hits were Python `re.match` in a heredoc. Six real gaps fixed. The proposed shared `portable.sh` was rejected on inspection: it would put a hard sourcing dependency inside a synchronous SessionStart hook, and `configs/scripts/` must run from a bare checkout.
- [x] 🔵 `compression_feedback.py` was dead — DONE 2026-09-02, deleted. `check-arch-map.py` only walks modules to the doc and never back, so nothing in CI would ever have flagged the stale map line. `task_factory/`'s four modules are now listed in CLAUDE.md with the exclusion stated.
- [x] 🔵 `ci_watcher.py` subprocess without a timeout — DONE. The finding's mechanism was wrong (`git remote get-url` reads local config and touches no network) but the defect was broader: a blocking call inside a `create_task`'d coroutine stalls the whole event loop.
- [x] 🔵 Two tree-sitter tests had never run — DONE. Only the Go grammar gates them, so `requirements-dev.txt` takes tree-sitter plus that one grammar rather than all eleven packages.
- [x] 🔵 Docs parity — DONE. `README.md` gained the Supported Languages section the Chinese edition already had. `structural-close-ladder.md` was **reshaped, not extended**: it already carried a back link fused onto one line, and a future audit reading line counts would add a duplicate. Two sub-items were withdrawn: the 300-line README threshold is not actually enforced by `/sync`, and `BRAINSTORM.md` is deliberately exempt per `check-roadmap-authority.py`'s own docstring.
- [x] 🔵 swebench hard-coded an absolute path — DONE.
- [x] 🔵 `TODO.md` was 96% history — DONE. 874 lines to 361, all open items retained, closed phases archived. **Not** to `PROGRESS.md` as the item proposed: that file is a dated journal with zero checkboxes and is itself twelve times over the 100-line cap its own owning skill sets.
- [x] 🔵 The two batch runners were copies — DONE. 176 shared lines, extracted flat rather than to `lib/` because CI's shellcheck glob is non-recursive. The extraction exposed a live bug: `grep -c` where `grep -n` was meant fed worker 1 the literal string "2" and worker 2 an empty prompt on legacy-format task files.
- [x] 🔵 `install.sh` never prunes — DONE, orphan report only, print and never delete. **Most of the item's specifics were false:** `configs/models.env` exists, is tracked and is sourced by `loop-runner.sh`; `mcp_server.py` is installed by `install.sh` itself; the `compgen` guard was deliberate. Only the mechanism claim held.
- [x] 🔵 Session-start context cost — DONE. `session-context.sh` byte-budgets every unbounded input, whole rules only, newest first, with a dropped-count notice. A measured injection was 24,057 characters, 82.7% of it correction rules.
- [x] 🔵 The CORS default could never match — DONE, plus a defect the audit missed: the regex admitted all of `100.0.0.0/8` while Tailscale uses only `100.64.0.0/10`, so publicly routable hosts held a CORS grant. Pinned to the real CGNAT range.
- [x] 🔵 No dependency scan — DONE, weekly rather than per-push. It surfaced something the audit had backwards: `npm audit` was **not** clean (that reading came from `--omit=dev`), and `fastapi==0.131.0`'s `starlette<1.0.0` cap locked the app to the last 0.x starlette, carrying two HIGH advisories with no in-range remedy. Bumped and verified end to end against a live server, not just the suite.
- [x] 🔵 `task_schema.py` had no direct test — DONE, but **not** the test the item asked for: that one already existed in `test_schema_frozen.py`. The real gap was the upgrade path — five migrations that only ever run against a pre-existing old database and which no test had executed.
- [~] 🔵 Orphan agents — **WON'T FIX.** "Referenced by no skill" is the wrong liveness test: agents are invocable directly, `paper-reviewer` is documented in `docs/how-it-works.md`, and `second-opinion-gemini` has contract tests. The same criterion would condemn `code-reviewer` and `type-checker`.

**Opened by the same wave** — found while fixing the above, none of it in the original audit:

- [x] 🔴 **Scrubbed what was already written — and the item understated it by an
      order of magnitude.** DONE 2026-09-02 via `configs/scripts/scrub-corrections.py`
      (default dry-run, `--apply` to rewrite, named files or a directory sweep;
      10 tests in `orchestrator/tests/test_scrub_corrections.py`).

      Three corrections to the filed item, all found by measuring rather than
      by trusting it:

      1. **"Both files" was three.** The credential was also in two `.bak-*`
         copies made by earlier maintenance passes, sitting in the same
         directory at the same mode. A scrub that walks only the files someone
         remembered leaves the key in a snapshot of itself. That is why this is
         a script that sweeps a directory, not a command.
      2. **"On a shared mount" was wrong.** It is local ext4, and the group is
         single-member, so 0664 exposed the file to any local account rather
         than to a set of collaborators. The corrections files were 0664; the
         session transcripts are 0600.
      3. **A raw scan of a JSONL file misses credentials.** A newline is stored
         as the two characters `\` and `n`, so a key that began a line inside a
         captured prompt sits on disk right after the letter `n` — a word
         character, so `\b` does not match. Measured: the same 44-character key
         appeared twice on one line and the raw scan reported one. Exactly the
         CJK bypass from earlier today, one encoding layer up. The scrub decodes
         each record and then replaces every literal occurrence. The live hook
         path is unaffected — it redacts before encoding.

      A read-only census of all 1,039 `.jsonl` files under `~/.claude` then
      found **158 credential occurrences, 37 distinct**, far outside the
      corrections directory. Cleaned: the corrections directory, the prompt
      history (17 across 5 kinds), and one world-readable file-history snapshot.
      **Deliberately not cleaned**: two session transcripts, 0600 and owner-only.
      They are the harness's own resumable state, the remedy for a leaked key is
      rotation rather than masking, and that is the owner's call. The command is
      in the report.

- [ ] 🔴 **Rotate the live credentials found in the census.** Masking removed
      them from disk; it does not un-expose them. Live Stripe secret keys
      (`sk_live_…SefN`, `…liem`, `…s2V7`), an Anthropic key (`sk-ant-a…90XX`), a
      Sentry token (`sntryu_6…c6c0`), three third-party OpenAI-shaped keys
      (`sk-cp-X4…XxMM`, `sk-tinyf…_5N2`, `…_5n2`), two 67-character generic keys
      and two JWTs. The `pk_live_` publishable keys and everything matching
      `_test_` need nothing. Owner action; nothing in this repo can do it.

- [x] 🔴 **`prompt-tracker.sh` was writing the first 100 characters of every
      long prompt to disk, and a pasted key is very often in the first 100
      characters.** Found by the census above, in code written earlier the same
      day: the rewrite replaced the old format's raw `prompt` field with a
      `preview`, which is the same leak through a smaller window. Nothing ever
      read a stored preview back — the repeat check greps the `exact`
      fingerprint and the LSH bands, and the message quotes the prompt already
      in memory — so the record now carries fingerprints and nothing else.
      Pinned in `tests/test-hooks.sh` §7, which also asserts the record is still
      written and that repeat detection survives storing no text.

- [x] 🟡 **`session-scorecard.sh` read a field that had never been written.**
      DONE 2026-09-02. It selects `.domain` from `history.jsonl` to find which
      rules had a correction in their area this session. The field was in 0 of
      983 records, so every record classified as `unknown`, the domain match
      never fired, and `record_rule_hit` credited every rule on every run —
      rule-effectiveness counts measured nothing.
      Two causes, both in `correction-detector.sh`: domain detection ran *after*
      the record was appended, and it was nested inside the `stats.json` branch,
      so a machine without that file computed no domain at all. Detection is now
      unconditional and happens before the write, and both write paths carry the
      field. The test asserts the resolved value rather than merely non-null,
      because `unknown` is what a missing field produces downstream too — and it
      needed a real git repository to do that, since the shared fixture has only
      a `.git` directory and `detect_domain` classifies `git diff` output.

- [x] 🟡 **`revert-detector.sh` filed every revert under the wrong repository.**
      DONE 2026-09-02. It recorded `project` from `$CLAUDE_PROJECT_DIR` — the
      session's repo — while the command usually operated on another: 68 of 92
      informative records began `cd <other repo> && git …`. `repeat` keys on
      `.project`, so it compared a file against reverts in a repository it had
      never been in, and could neither detect recurrence in the right repo nor
      be trusted when it fired. `rd_revert_base` already computed the right
      directory for shadow matching; only the record kept using the wrong one,
      so the fix is to assign `PROJECT` from it and let the shadow match reuse
      that single value.
      **The first version of the test was itself the bug it was testing.** It
      called `assert_eq`, which this suite never defined, so both assertions ran
      as an undefined command: bash wrote to stderr, the suite counted nothing,
      and the run stayed green at exactly 39 tests. Defining the helper took it
      to 41, and red-phase confirms the attribution assertion fails without the
      fix.

- [x] 🟡 **`PROGRESS.md` was 1,209 lines against the 100-line cap its own
      skill sets.** DONE 2026-09-02. The `/sync` skill says keep it under 100
      lines and move older entries to `docs/progress-archive/YYYY-MM.md`. It
      said so in prose only, so the file grew to twelve times the cap and the
      archive directory was never created — the same shape as every other drift
      in this audit, a rule with nothing checking it.
      `configs/scripts/archive-progress.py` now splits the file by dated entry,
      keeps the newest that fit plus anything marked `[ACTIVE]`, and writes the
      rest to the month file the skill names. 65 entries in, 5 kept, 60
      archived across three months, 65 entries out — nothing lost. `--check`
      runs in CI as syntax-check gate 18, and adding it immediately caught
      `CLAUDE.md` still claiming 17.

- [x] 🟡 **`ReactionConfig.action` was decorative.** DONE 2026-09-02. Both
      consumers in `worker.py` swallowed every triggered reaction into a flat
      `logger.warning`, so `abort`, `escalate` and `warn` were the same event
      with different spelling — and one shipped default carried the message
      *"Behavioral loop detected — aborting task"* while nothing aborted
      anything. The field decides the reported level now, through an explicit
      `ACTION_LEVELS` table, and an action the module cannot dispatch raises
      `UnknownReactionAction` when the executor is built rather than being
      ignored when it fires. A silent no-op is what made it decorative.
      The `loop_detected` default no longer claims an abort; it escalates and
      says the worker continues. Eleven tests, three of which fail against the
      old module: the two levels are distinguishable, an unknown action is
      refused, and no shipped message promises an abort.

- [ ] 🔵 **Decide whether a reaction should be able to stop a worker.** The
      `abort` action maps to CRITICAL and dispatches no kill path, which is
      honest but not the original intent. Wiring one needs a worker-side
      contract first: what the task's status becomes, whether it is retried,
      what the evidence bundle records, and whether a regex match on a poll
      string is enough evidence to end a run. Referenced from the comment at the
      top of `orchestrator/reactions.py`.

- [x] 🟡 **The version-alignment gate required the hand-sync it exists to
      prevent.** DONE 2026-09-02. The expected version was a literal in the
      test, so cutting a release meant editing the gate that catches a missed
      edit — the same failure it guards against, one level up. It is derived
      from `mcp-package/pyproject.toml` now.
      It also covered four surfaces where there are six: `.claude-plugin/plugin.json`
      and the generated `plugins/clade/.codex-plugin/plugin.json` each carry a
      version and neither was checked, so either could have shipped stale with
      the suite green. The Codex manifest is compared on the part before the
      semver build metadata it is regenerated with. Red-phase confirmed on each
      surface separately, and on a bumped `pyproject.toml`.

- [ ] 🔵 Patrol reports are written and never read. `start.sh` writes `~/.claude/patrol-report-DATE.md` and nothing parses it back; `patrol_auto_ideas` was the flag for that missing ingestion and was deleted rather than left as a published lie. Re-propose with a real design.
- [ ] 🔵 `reactions.create_executor_from_config` has zero production callers and reads a settings key that no longer exists. Removing it means dropping three tests in `test_leaf_modules.py`.
- [ ] 🔵 Nothing enforces the top-level `docs/*.md` header convention; two of fourteen files had drifted off it and no gate noticed. Cheapest control: assert in `check-references.py` that every top-level `docs/*.md` links `../README.md` in its first three lines.
- [ ] 🔵 The global agent rules assert that `/sync` flags a README over 300 lines. The shipped skill has no such logic — its only line-count rule caps `PROGRESS.md` at 100. Implement the check or correct the claim.
- [ ] 🔵 Web lint has no home. The `npm run lint` script was deleted because eslint was never installed; re-adding it properly needs a `web` job in `ci.yml` and the coupled CLAUDE.md checklist line, which `check-ci-checklist.py` enforces.
### Standing-brief configuration — 2026-09-02

- [x] 🔴 **The repeat-brief detector had never spoken.** `prompt-tracker.sh` was
      async and reported through `systemMessage`, which an async hook cannot
      deliver — across 386,760 logged prompts and nine patterns past its own
      threshold it produced nothing, ever. That silence is the direct cause of
      the owner hand-typing the same long brief: nothing told them it had become
      a pattern. Now sync via `additionalContext`, bounded log, min-hash + LSH
      fingerprint so a changed opening sentence no longer hides the repeat, and
      it speaks once per pattern. Six tests.
- [x] 🟡 **Fan-out is now available by default and was being suppressed.**
      `ultracode: true` makes Claude Code plan a workflow per substantive task;
      it was set nowhere. `install.sh --ultracode[=small|medium|large]` is the
      opt-in. Two things in this repo fought it: `configs/CLAUDE.md`'s blanket
      "use at most three agents", installed globally and read every turn — it
      sat in context while a 166-agent review ran — and the absent
      `workflowSizeGuideline`. Both fixed; the recursion cap stays because a
      Workflow orchestrates from the lead and never needs to nest.
- [x] 🟡 **`/landscape` skill added.** Encodes the whole-system report brief the
      owner kept retyping: the 18-section spine (stakeholder framing, testable
      goal, parts inventory with repo and owner, surfaces including dormant
      ones, one traced task, decisions, abandoned attempts, a capability-ladder
      gap, exactly one next step, declared omissions), the ranked archaeology
      for recovering failed attempts, and the two-step org survey.
- [x] 🔴 **`frontend-design` was empty and is now filled.** The owner's standing
      design brief — measured at fifteen appearances in `history.jsonl` over five
      months, the canonical one 9,181 characters — said *"请调用 frontend-design
      skill，并严格遵循它的设计规范与最佳实践"*, and the skill contained **none** of
      what it was pointing at: zero hits across the whole directory for
      scroll-jack, Framer Motion, prefers-reduced-motion, bento, Linear, Vercel,
      Poppins or BRAND.md. The brief had a home and the home was empty, so it
      got re-typed. Recovered from the logged instances into
      `references/brand-differentiation.md` and wired into phase 4 and the
      handoff contract.
      **The most valuable part is that the brief has two versions that
      disagree.** The first told Claude to follow Linear, Vercel, Stripe and
      Anthropic's restrained palettes; that produced three sibling sites that
      looked alike, so the second forbids exactly what the first recommended.
      The reference records the ban list *as the correction to its own earlier
      version*, which is the only form in which it makes sense. Client
      specifics — the brand names and internal domains — are deliberately not
      in the public repo; only the reusable method is.
- [x] 🟡 **The correction taxonomy had no class for a standing preference, so
      the most expensive failure in the log was invisible to it.** All nine
      classes describe something wrong with an answer. A repeated brief has no
      wrong answer — each instance was answered correctly, which is exactly why
      no correction was ever recorded and nothing ever escalated. Measured at
      the time: 386,760 prompts, 2,990 fingerprints, nine past the repeat
      threshold, and one 9,181-character brief typed fifteen times over five
      months. Added `standing-preference` to `correction-detector.sh` and made
      it promotable in `rule-utils.sh`, since persisting into every session is
      the whole remedy rather than a side effect. It routes differently too: a
      repeated brief needs a home, not a reminder, so step 3b sends a procedure
      to a skill and a rule to CLAUDE.md and checks the home is not already
      there and empty. Red-phase checked in `test-audit.sh`.
- [ ] 🔵 `install.sh --ultracode` has no test. `tests/test-install.sh` covers the
      spawn-depth merge next to it; the same shape applies — assert the two keys
      land, that an existing `settings.json` key survives the merge, and that an
      invalid size falls back to medium rather than writing garbage.

### Review of the review — 2026-09-02, second pass

- [x] 🔴 **The orchestrator has never run — and that is deliberate.** The
      measurement stands: no `tasks.db` on this host carries the current schema
      (three exist, two hold zero rows, the third holds 12 and predates
      `agent_runtime`, `provider` and the evidence bundle), and no evidence store
      exists at all. **DECIDED 2026-09-02 by the owner: the GUI is dormant —
      effectively fully disabled — and all work happens in the terminal. It may
      be rebuilt later, so nothing is deleted.** So this was never a defect; it
      is the expected consequence of a decision that had not been written down
      anywhere. What follows from it is a scope rule, below.
- [ ] 🟡 **Scope rule not yet enforced anywhere: the orchestrator is not
      load-bearing.** `worker_pool.py`, `worker_routing.py`, `cascade_policy.py`,
      `evidence_bundle.py`, `routing_break_even.py` and `attempt_telemetry.py`
      are dormant-path code. This audit spent most of its effort there while every
      measured parallelism number in the repository came from Claude Code's
      Workflow/subagent layer, which the orchestrator does not control. Keep the
      layer building and green — CI covers it — but weigh findings there below
      terminal-path findings, and treat new orchestrator work as opt-in rather
      than as debt. Auditing an unrun system is how effort gets spent on a
      control that never applies. Nothing in the repo says this yet except
      `CLAUDE.md`'s new note; a mechanical version would be a marker the audit
      skills read.
- [x] 🟡 **`subagents` was declared for both providers, read by nothing, and
      wrong.** DONE 2026-09-02. The routing machinery already existed:
      `resolve_capabilities` enforces a task's `execution_requirements` against
      the runtime's capabilities, raising on a REQUIRED capability that is not
      SUPPORTED and recording a `Degradation` for a PREFERRED one. Nothing had
      ever declared this requirement, and Codex's state would have answered
      wrongly if anything had — `CONDITIONAL` with no condition expressed reads
      as "sometimes, depending", when `codex exec` spawns no sub-agent at all.
      Corrected to `UNSUPPORTED`, and the `sources` map now carries each
      condition instead of repeating the adapter name for every key, which is
      what made it as unreadable as the state it was meant to explain.
      Seven tests are the missing consumer: a run that must subdivide is refused
      on Codex and admitted on Claude, a preferred one degrades rather than
      failing, and no CONDITIONAL is allowed to ship without a stated condition.

- [ ] 🟡 **Codex cannot fan out, and that is why it is slower.** `codex exec`
      exposes 15 flags and not one concerns agents, delegation or concurrency.
      The CLI's own `features list` shows `multi_agent stable true` — but only
      the interactive TUI reaches it — `multi_agent_v2 stable false`, and
      `enable_fanout removed`. So a Codex worker is one linear agent, while a
      Claude worker can spawn its own subagents. Comparing their wall-clock as
      if they were peers is comparing a fan-out against a single thread. The
      only parallelism available to Codex is Clade spawning N `codex exec`
      processes from outside, which the worker pool can already do and which
      nothing measures.
- [ ] 🟡 The polling rule ("one Monitor, then yield") lives only as prose in the
      global instructions. Nothing enforces it and nothing counts violations,
      which is the same shape as every gate this audit found broken. The
      measurable version: `workflow-scorecard.py` could read the lead session's
      own transcript and report poll-calls-per-background-job alongside the
      straggler numbers.
- [ ] 🟡 The learning system does not measurably learn. The rework rate has been
      flat at 9-15% for six months while `corrections/` accumulated rules, and
      nothing closes the loop from "rule written" to "defect not repeated".
      There is no measurement of whether any individual rule ever prevented
      anything. Before adding more capture, measure the existing rules'
      effect — `rule-effectiveness.sh` exists and its hit counts are known noise
      (see the `.domain` item above).

### Adversarial review of the audit branch — 2026-09-02

166 agents reviewed the branch across seven dimensions; each finding was then
put to three independent refuters and kept only if fewer than two could refute
it. 28 survived. The critical one and eight real defects are fixed on the
branch; what follows is the residue, all of it prose that is now wrong rather
than code that is broken.

The review's own most useful output was structural: **three separate gates in
this branch existed, were documented as working, and did not check what they
claimed** — the CI-checklist gate was blind to the gate just added to it, the
"walks the real route table" test reached 37 of 93 routes after the FastAPI
bump, and the checklist's own suite and gate counts had drifted. A control whose
failure mode is silence needs a test that proves it can fail.

- [ ] 🔵 `orchestrator/ruff.toml`'s "Known live bugs" block still describes two
      parked per-file-ignores in the present tense. Both bugs were fixed and both
      entries deleted in the same commit, so a maintainer triaging a
      worktree-cleanup failure is told `Worker.stop()` currently raises. Rewrite
      as a past-tense note about what the gate's first run found.
- [ ] 🔵 `docs/MIGRATE_FROM_HERMES.md` still lists `compression_feedback.py` as
      "present in Clade today"; the module was deleted by this branch.
      `check-references.py` does not resolve backticked `orchestrator/*.py`
      paths, which is why nothing caught it — teaching it to would also have
      caught the stale CLAUDE.md map line.
- [ ] 🔵 The 0.3.1 CHANGELOG section omits the release's own security work — the
      two HIGH starlette advisories, prompt redaction, per-user runtime paths,
      the MCP event-loop fix — and the two compatibility notes an upgrader needs
      (`/web` now 503s until built, `reaction_configs` and `patrol_auto_ideas`
      removed). Its `[0.3.1]` compare link also points at a tag the release
      deliberately did not create.
- [ ] 🔵 `configs/skills/brief/prompt.md` probes the orchestrator with an
      unauthenticated curl and now reports it offline. Add the bearer header the
      way `docs/configuration.md` documents, then regenerate the mcp-package
      mirror.
- [ ] 🔵 `configs/scripts/usage-agent.py`'s docstring and `CLAUDE.md`'s usage line
      still say "leave empty for open ingest". Ingest is exempt from the control
      plane only while `usage_ingest_token` is set, so an empty token now means
      the node must send the hub's `api_token` instead.
- [ ] 🔵 `session-context.sh`'s dropped-rules notice counts header and blank lines
      as rules, so it reports more dropped than exist.
- [ ] 🔵 `CLAUDE.md`'s redaction paragraph justifies withhold-don't-substitute with
      "those patterns are fixed-count", which stopped being the reason when the
      pattern gained `{n,}` quantifiers. The reason that survives inspection is
      that a line-oriented sed cannot reach a PEM body and any partial mask still
      persists part of a credential.
- [x] 🟡 **The weekly `dependency-audit` job would have been red on its first
      scheduled run.** DONE 2026-09-02, and the filed claim checked out:
      `npm audit --audit-level=high` reported 4 high and 1 low against the
      unchanged lockfile — four PostCSS advisories including two arbitrary
      `.map` file reads, and four vite ones including the dev-server WebSocket
      arbitrary file read the job's own comment was written about.
      Fixed with `npm audit fix`, not `--force`: every bump is patch-level
      inside the existing range (vite 6.4.1 → 6.4.3, postcss 8.5.8 → 8.5.26,
      nanoid 3.3.11 → 3.3.18) and `package.json` is untouched. Verified the way
      CI will run it — `npm ci` from the new lockfile, then audit, then build —
      all three clean.

- [ ] 🟡 Anthropic's documented fix for the other half of the prompt-cache miss —
      stagger a fan-out so the first response primes the shared prefix before
      the rest are sent — is not implemented. Only the system-prompt half is.
      Claude Code already does this inside its own Workflow runtime.
- [ ] 🟡 Adversarial verification with N skeptics is measurably overspent:
      Terminal-Bench V2 puts pairwise verification at 73.1% with one judge and
      77.5% with sixteen. This session ran three refuters per finding. One
      better-calibrated verifier returning a score plus its evidence belongs in
      `worker_review.py` instead.
- [ ] 🔵 Three tests in `test_static_serving.py` use `with TestClient(...)`, which
      runs the FastAPI lifespan and therefore mints a control-plane token into
      the developer's real settings file. They exercise routing only and do not
      need it.

- [ ] 🔵 `orchestrator/tests/test_worker_modules.py` is 1446 lines, 54 under the ceiling. The natural split lifts the autoscale and fan-out sections into their own file.
- [ ] 🔵 `tests/test-loop.sh` is 1442 lines, 58 under the ceiling, and the loop-runner split just pushed it there by adding deploy-parity entries. It is now the closest first-party file to the gate after `test_worker_modules.py`.
- [x] 🟡 **`--model` did not reach every node, in three places rather than one.**
      DONE 2026-09-02. `loop_verify.sh`'s verify node and `loop-runner.sh`'s
      fix-task planner both ran a literal `--model sonnet` while every other LLM
      node used `$SUPERVISOR_MODEL`, and the planner's prompt separately told it
      in prose to "use sonnet model" regardless of `--worker-model`. The default
      is unchanged either way — `SUPERVISOR_MODEL` defaults to `MODEL_SONNET` —
      which is exactly why it went unnoticed: the flag looked like it worked
      until you asked which node ran what.
      `tests/test-loop-args.sh` now fails on any `--model <literal>` in the loop
      script group and on any prompt naming a model in prose. Both guards were
      red-phase checked separately.

- [ ] 🔵 `node_test_sample` and `node_health_check` communicate through three bare globals (`LAST_TEST_OUTPUT`, `LAST_TEST_RESULT`, `PREV_FAILED`) that are now a cross-file coupling between `loop_verify.sh` and `loop-runner.sh`. Sourced shell makes it work; the `# Writes:` header is the only thing recording it.

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

---
