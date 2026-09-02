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
- [ ] 🔴 `redact.py` has no pattern for underscore-style API keys (`sk_<40+ hex>`) — the Scam.ai key form. `openai_key` requires `sk-` (hyphen), `stripe_key` requires the literal `sk_live_`, and `env_secret` requires the value to be quoted; a bare `sk_d69…` pasted in prose matches none of them. One such key sat in `corrections/history.jsonl` from 2026-08-19 until the 2026-08-31 radar run removed it. Add to `_PATTERNS` in `configs/scripts/redact.py:56`: `("generic_secret_key", re.compile(r"\b(?:sk|rk|ak)_[A-Za-z0-9]{32,}\b"), 0),` placed **after** `stripe_key` so `sk_live_…` keeps its specific label. Not landed by the radar run: that session had no `python3`, so the regex could not be executed even once, and a malformed pattern raises at import in every hook that calls `redact` (`configs/hooks/secret-scanner.sh`).
- [ ] 🔴 Correction capture writes raw user prompts to disk with no redaction call — `configs/hooks/correction-detector.sh:58` (via `cp_bound_prompt`) into `history.jsonl`, and `:180` (`RULE_TEXT_PREVIEW`) into `cross-project-rules.jsonl`. Both land on the shared NFS mount (`~/.claude/corrections` → `shared-nfs/claude-dotfiles/corrections`, mode 0664). `redact.py` already exists and is never called on this path; `secret-scanner.sh` only warns in-context and runs after the record is written. Fix: redact `$PROMPT` once near the top and use the masked value for both writes.
- [ ] 🟡 `reverted_files` is not a revert set, so `repeat` is not a recurrence signal — `configs/hooks/revert-detector.sh:57` fills it from `cp_recent_files(session_key, 20)`, the last 20 files touched *in the session*, never intersected with the paths the git command actually names. `repeat` (`:66`) then intersects those session lists, so it largely measures session length and overlap. Any analysis treating a `repeat:true` cluster as "the same mistake recurred" is reading noise. Real fix is to parse the revert command's own pathspec and intersect. Documented as a caveat in `configs/skills/radar/SKILL.md` 2026-08-31; the code is unchanged.
- [ ] 🔵 `configs/scripts/session-scorecard.sh` awk parses only the compact JSONL style — `match(line, /"timestamp":"([^"]+)"/, ts)` and `/"type":"implicit/` miss the spaced form (`{"timestamp": "…"`) used by every `history.jsonl` record written before 2026-08-15 (853 of 963 at the 2026-08-31 sweep). Latent today because the scorecard windows on recent records only. Same line uses gawk's 3-argument `match()`, which is not in BSD awk — unverified, but this repo deploys to macOS via `shared-nfs/claude-dotfiles`.

### Full-project audit — 2026-09-02

Every enforced gate was green at audit time: 13 `syntax-check` gates, pytest
(1515 passed, 2 skipped), both offline evals, all 22 shell suites, shellcheck,
web `tsc`, `npm audit`, 0 import cycles across 74 modules, 0 CI failures in the
last 30 runs, no secrets on HEAD by pattern. The items below are what the gates
cannot see: claims that are stale rather than absent, keys that exist but are
read by nothing, and deployment paths that only work on the machine that built
them. Context, not a task: 90-day commit mix is 148 feat / 145 fix, and the
session-start lesson feed shows three "mass-fix-day" clusters (24, 15, 15
commits), so features land and get repaired in batches — the review gate at
feature time is weaker than the audit machinery after it.

- [ ] 🔴 The orchestrator control plane has no authentication, and loopback is not a trust boundary on the host it runs on. 93 routes, 51 of them mutating, carry no auth dependency (`Depends(_resolve_session)` is the only one and it resolves a session, not a caller); the one guarded endpoint, `/api/usage/ingest`, checks `usage_ingest_token` (`orchestrator/routes/usage.py:51`), and that key is itself writable through unauthenticated `POST /api/settings` (`orchestrator/server.py:1089` accepts every `_SETTINGS_DEFAULTS` key). `POST /api/sessions` (`orchestrator/server.py:199`) opens a session on any path and its workers run `--dangerously-skip-permissions` with full env passthrough as the orchestrator's user (`orchestrator/config.py:180`). aries has 40 human accounts (3 logged in at audit time), all of which can reach 127.0.0.1:8000; the Caddy remote path VISION describes widens that to the tailnet. Not exploitable at audit time only because the orchestrator was not running (the :8000 listener on aries belongs to another account). Fix: one bearer-token dependency on every non-GET route and both websockets, token generated on first start into `~/.claude/orchestrator-settings.json`, `usage_ingest_token` folded into it, UI reads it from `localStorage`; keep GET `/api/status` open if the statusline needs it.
- [ ] 🟡 `goal-cc-codex-adaptation.md` is a tracked root-level goal file carrying 10 unchecked `- [ ]` that the roadmap-authority gate does not scan (`configs/scripts/check-roadmap-authority.py:44` covers four named files), and `.claude/loop-state.json` (mtime 2026-08-10) still says iteration 1 is running with no `loop-runner.sh` process alive, so `session-context.sh` reports "Loop: ⟳ running" at every session start. Eight of the ten are landed and never ticked: plugin component resolution + CI gate (`validate-plugin.yml`, `check-cc-plugin-components.sh`, commit `4436588`), version canon (`regen-cc-plugin.py` `canonical_version`), shadow cleanup (`session-end-cleanup.sh` on `SessionEnd`), `post-edit-check.sh` asyncRewake, `skill-suggest.sh` sync `additionalContext`, subagent spawn depth (`install.sh:419`), doc-align/prompt-tracker left as-is. Unverified: the `claude plugin marketplace add shenxingy/Clade` install path, and per-change test coverage. Fix: tick the eight, move the two open ones here, delete the goal file and the stale loop-state, and add `goal-*.md` to the roadmap-authority file set so the next loop goal cannot leak the same way.
- [ ] 🟡 The 2026-08-31 radar run left its output uncommitted on `main`: `CLAUDE.md` (+7 auto-promoted rules), `TODO.md` (+4 items above), `configs/skills/radar/SKILL.md`. Three of the seven rules — file-delivery (alexm is a Mac), upstream-pr (openai/codex collaborator gate), security-audit (mnemo data-catalog bind) — contain no Clade content; the 2026-05-06 design-scope rule in the same file says cross-project lessons default to `~/.claude/CLAUDE.md`. Fix: branch + PR for the three files, relocate those three rules to the global file.
- [ ] 🟡 `orchestrator/worker.py` is a 30-import hub. It top-level-imports 30 project modules (next: `server.py` 19, `worker_pool.py` 11), is the most-churned file in the repo (61 commits in 90 days), and the `worker_*` family is now 15 modules against this file's own "4–6 modules per component, NOT 15+ fragments" rule. Leaf extraction kept `worker.py` under the ceiling but every extracted leaf still routes through it, so reading one worker behaviour means `worker.py` plus N leaves. The next split must be by responsibility (spawn/lifecycle, evidence/reporting, hydration/taskfile) rather than one more leaf.
- [ ] 🟡 Three source files sit within 100 lines of the 1500-line gate and eight are above 1100: `orchestrator/worker_tldr.py` 1459, `configs/scripts/loop-runner.sh` 1407 (33 commits in 90 days), `orchestrator/worker.py` 1273; then `session.py` 1246, `worker_utils.py` 1210, `server.py` 1188, `worker_review.py` 1170, `task_queue.py` 1142, `config.py` 1107, `start.sh` 1059. The 2026-08-10 own-tooling rule above calls a file at the ceiling a blocked file. Split `worker_tldr.py` and `loop-runner.sh` before their next change, not during it.
- [ ] 🟡 Nothing builds the web UI on install. No `vite build` / `npm ci` in `install.sh`, `configs/scripts/start.sh`, or any orchestrator script; `orchestrator/server.py:161-163` falls back to serving the pre-Vite `orchestrator/web/app-*.js` + `styles.css` (2705 lines, referenced by nothing, recorded in PROGRESS.md as replaced) whenever `web/dist/` is absent — which is every fresh machine, since `dist/` is gitignored. Also: 0 web tests; `package.json` declares `lint` but there is no `eslint.config.*`, so ESLint 9 exits before linting; `tsc` is clean. Fix: build `dist/` in `install.sh` (or commit it), delete the legacy files and the fallback branch, add an eslint config or drop the script.
- [ ] 🟡 Five settings keys are published as supported and read by nothing. `reactions_enabled` and `reaction_configs` (`orchestrator/config.py:308-309`): `orchestrator/worker.py:207` constructs `ReactionExecutor()` with no arguments, so `DEFAULT_CONFIGS` always apply and `reactions_enabled: false` is a no-op. `min_workers` is an editable field in the React settings panel (`orchestrator/web/src/components/settings/SettingsPanel.tsx:135`, `lib/types.ts:281`) while `orchestrator/session.py` only ever reads `max_workers`. `patrol_auto_ideas` and `replay_interrupted_on_startup` have no reader in `orchestrator/`, `configs/`, or tests. All five appear in `templates/orchestrator-settings.example.json`, whose contract is "every supported key". Fix: wire or delete each, then add a test that every `_SETTINGS_DEFAULTS` key has at least one reader outside `config.py` — the audit found these with a 30-line script in one pass.
- [ ] 🟡 Shell portability: this repo reaches macOS through `shared-nfs/claude-dotfiles` (see the session-scorecard item above), CI runs Ubuntu only, and 2 of 40 scripts carry an OS guard. GNU-only calls in shipped hooks and scripts: `stat -c` in 8 files (`session-context.sh`, `auto-audit.sh`, `stop-check.sh`, `post-compact-reinject.sh`, `memory-sync.sh`, `run-tasks.sh`, `run-tasks-parallel.sh`, `commit-archeology.sh` — three are sync SessionStart/Stop hooks); `date -d` (`start.sh`, `minimax-usage.sh`); `readlink -f` (`loop-runner.sh`, `scan-todos.sh`); coreutils `timeout` (`session-context.sh`, `skill-suggest.sh`); gawk 3-argument `match()` (`loop-runner.sh`, `session-scorecard.sh`); bash-4-only `declare -A` (`rule-cluster.sh`, `scan-todos.sh`), `mapfile` (`checks.sh`), `${var,,}` (`start.sh`) against the bash 3.2 macOS ships. Fix: a `configs/hooks/lib/portable.sh` with `_mtime`, `_epoch_from`, `_realpath` shims, or a macOS leg in the `shell-tests` matrix so the failure is at least visible.
- [ ] 🟡 Fixed `/tmp` paths on a shared host: `/tmp/clade-radar.lock` (`configs/scripts/radar-cron.sh:21`), `/tmp/memory-watchdog.pid` and `.log` (`memory-watchdog.sh:27-28`), `/tmp/claude-sync-push.lock` (`sync-push.sh:24`), `/tmp/claude-skill-suggest/` (`configs/hooks/skill-suggest.sh:114`), `/tmp/claude-edit-shadows/` (`hooks/lib/correction-pair.sh:22`, `edit-shadow-detector.sh:19`, `session-end-cleanup.sh:27`). With 40 accounts on aries and the dotfiles shared over NFS, the first account to create a lock or directory owns it and every other account's hook fails open: `flock` on a file it cannot open, a shadow directory it cannot write, so correction pairing is silently off for everyone but one user. Fix: `${XDG_RUNTIME_DIR:-/tmp/clade-$(id -u)}` in one shared helper.
- [ ] 🟡 `orchestrator/mcp_server.py:604` runs `subprocess.run(..., timeout=300)` inside `async def _execute_skill`, blocking the MCP server's event loop for the whole skill run (up to 5 minutes) and serialising every concurrent MCP call behind it. Use `asyncio.create_subprocess_exec` + `asyncio.wait_for`. (The audit counted 54 blocking file reads/writes in other async defs — small local IO, acceptable; this is the one that matters.)
- [ ] 🟡 Release drift: `.claude-plugin/plugin.json` and the Codex plugin manifest say 0.3.1, `mcp-package/pyproject.toml` says 0.2.0, the newest CHANGELOG release and git tag are both 0.2.0 (2026-07-13), 240 commits ago; CHANGELOG's top section is "Unreleased". Either cut v0.3.1 (tag + CHANGELOG section + mcp-package bump, in one PR) or reset the plugin manifests to the last released version. A marketplace consumer today installs "0.3.1" of something that has no release notes.
- [ ] 🟡 No Python lint or type gate exists anywhere. `orchestrator/requirements-dev.txt` holds pytest and PyYAML only; there is no ruff/flake8/pyflakes/mypy config in the repo; CI's Python step is `py_compile`. Measured on non-test code: 178 bare `except:` / `except Exception:`, 89 of them followed by `pass` or `continue`. Add `ruff` (pyflakes + bugbear rules, `BLE001` off until the baseline is worked down) to the `syntax-check` job; it is a single wheel and runs in seconds, so it fits the stdlib-only constraint of that job.
- [ ] 🔵 `orchestrator/compression_feedback.py` is dead: `CLAUDE.md:127` says "consumed by /handoff skill", `configs/skills/handoff/` never references it, and its only importer is `tests/test_compression_feedback.py`. Wire it into `/handoff` or delete it and correct the map line. Related: `configs/scripts/check-arch-map.py:21` skips `task_factory/`, so its 4 modules sit outside the coverage gate by construction — list them or state the exclusion in CLAUDE.md.
- [ ] 🔵 `orchestrator/task_factory/ci_watcher.py:113` — `subprocess.check_output(["git", "remote", "get-url", "origin"])` is the only subprocess call in `orchestrator/` without a `timeout=`; a hung credential helper or an NFS-backed checkout stalls the status loop.
- [ ] 🔵 Two tree-sitter tests (`orchestrator/tests/test_pagerank_and_jsparse.py:128,140`) skip locally and in CI because `requirements-treesitter.txt` is installed nowhere, so they have never run. Install it in the pytest job or delete the tests.
- [ ] 🔵 Docs parity: `README.zh-CN.md` has 14 H2 sections against `README.md`'s 13 — "支持的语言" has no English counterpart. `docs/COMPATIBILITY-RETIREMENT.md` and `docs/structural-close-ladder.md` lack the line-1 language toggle and line-3 back link every other `docs/` file carries. `README.md` sits at 301 lines, one over the `/sync` threshold; `BRAINSTORM.md` is 2668 lines, past the Read tool's 2000-line default.
- [ ] 🔵 `orchestrator/evals/swebench/run_clade_swebench_testdriven.py:14` hardcodes `sys.path.insert(0, "/home/alexshen/projects/clade/orchestrator")` — lowercase `clade`, a path that does not exist even on this host. Use `Path(__file__).resolve().parents[2]`.
- [ ] 🔵 `TODO.md` is 96% history: 219 `[x]` against 8 open `[ ]` in 835 lines (before this section). The single source of open work should not need a full-file Read to find the open items. Move closed phases to `PROGRESS.md`, whose role statement already covers what shipped.
- [ ] 🔵 `configs/scripts/run-tasks.sh` (674 lines) and `run-tasks-parallel.sh` (794) share 188 identical non-trivial lines. Extract `configs/scripts/lib/run-tasks-common.sh`.
- [ ] 🔵 `install.sh` never prunes, so `~/.claude/` accumulates what the repo removed: 7 hooks not in `configs/hooks/` (`frustration-trigger`, `post-commit-verify`, five `slack-*`; none wired in `settings.json`) and `mcp_server.py`, `sync-openclaw-token.sh`, `loop-runner.sh.bak-20260819` in `~/.claude/scripts/`. `install.sh:214` and `:242` also copy `configs/models.env` and `configs/commands/*.md`, neither of which exists in the repo. Add an orphan report (print, never delete) and drop the two dead copy paths.
- [ ] 🔵 Session-start context cost: `session-context.sh` injected 17.8–23.5 KB on this session's own runs, roughly 5–6k tokens before the first user message. `~/.claude/corrections/rules.md` is 24.6 KB in 55 lines and the hook tails 25 of them plus 25 project lines (`configs/hooks/session-context.sh:217-221`). Add a byte budget with a "N more rules — run /audit" tail so a growing rule file cannot grow the per-session tax without bound.
- [ ] 🔵 The CORS default `"http://localhost:*,http://127.0.0.1:*"` (`orchestrator/server.py:134`) can never match — `CORSMiddleware` compares `allow_origins` literally; requests only pass because `allow_origin_regex` (`:138`) covers localhost/127.0.0.1/100.x. That regex is `http://` only, so the HTTPS Caddy front-end VISION describes is blocked unless `CORS_ORIGINS` names the exact origin. Drop the dead default; make the regex `https?://`.
- [ ] 🔵 Orphan agents: `configs/agents/paper-reviewer.md` and `second-opinion-gemini.md` are referenced by no skill, hook, or script (`second-opinion-codex` is, via `codex-orchestrate`). Keep-or-delete decision.
- [ ] 🔵 No dependency vulnerability scan in CI (no `pip-audit`, no `npm audit`); `fastapi` 0.131.0 is ten minor versions behind 0.141.1, `cryptography` 49 → 50. `npm audit` was clean at audit time. Add a scheduled (weekly, not per-push) audit step next to the existing `real-api-loop` schedule.
- [ ] 🔵 `orchestrator/task_schema.py` (390 lines) has no direct test; every migration is exercised only through `task_queue` tests, so a broken `ALTER TABLE` inside its try/except is invisible until a column is read. Add a test that opens a v1-schema fixture, runs `ensure_schema`, and asserts every column in `_ALLOWED_TASK_COLS` exists.

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
