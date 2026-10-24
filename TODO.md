# TODO — Clade

> **This file is the single source of open work.** An unchecked `- [ ]` here
> is the only thing that means "not done yet". `VISION.md` says why the system
> exists, `IMPLEMENTATION_PLAN.md` is a completed dated plan, and `PROGRESS.md`
> is a dated journal — none of them carries open items, and none of them
> overrides this file. Decided 2026-08-29.

> Vision and architecture: see [VISION.md](VISION.md)

Phases 1–14 complete.

## Codex plugin update compatibility

- [ ] Retire the retained-cache workaround only after an upstream Codex release
  preserves old session hook paths or atomically refreshes live hook engines.
  Related: [openai/codex#36605](https://github.com/openai/codex/issues/36605).
  Reproduce an update with two live threads: old hook and skill paths must remain
  usable, new threads must load the new bundle. CLI 0.156.1 cleared old Clade
  paths; `configs/scripts/codex-plugin-update.py` now snapshots/restores complete
  bundles. Raw CLI/app updates, SIGKILL during replacement, and native Windows
  are outside the verified protection; retained backups support manual recovery.

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
- [x] 🔴 **DataForSEO: decided — no paid APIs, and the free path is now the
      default.** 2026-09-12, owner's call. No integration is being built; what
      changed instead:
      `/seo` carries a **free-by-default policy** naming the keyless tools that
      do the work (`fetch_page.py --googlebot`, `parse_html.py`,
      `capture_screenshot.py`, `commoncrawl_graph.py`, curl for
      robots/llms/sitemap/JSON-LD), marks DataForSEO/Moz/Ahrefs/Semrush as
      opt-in only, and states plainly that a paid source may never be the reason
      a dimension goes unreported. The same rule went into `configs/CLAUDE.md`
      for every project.
      **`seo-geo` was not runnable and now is.** It described what to score and
      never said how to obtain it — no fetch, no robots.txt read, no llms.txt
      read — and the only integration it named was the paid one. It has a Step 0
      that acquires everything free and keyless, verified end to end against a
      live site: browser vs non-JS fetch (174,476 B both ways, so no JS gap),
      robots.txt 200, llms.txt 404, zero JSON-LD blocks.
      Running it surfaced an interpretation trap I fell into myself: a
      `User-Agent: * / Allow: /` robots.txt names zero AI tokens and permits all
      of them, so "0 crawlers found" inverts the answer. The skill now resolves
      per crawler as allowed / blocked / ungoverned, never "not found".
      13 assertions in `tests/test-seo-geo.sh`, wired into CI; removing Step 0
      fails six of them.
- [x] 🟡 **The dead DataForSEO tool names now carry a version gate.**
      `seo-geo` had already been corrected; the live citations were in
      `seo-dataforseo`, whose 84 tool names are ALL v2 names. v3.0.0
      (2026-08-11) replaced ~79 per-endpoint tools with `api_request` plus three
      docs tools and deprecated v2, so on a v3 install none of them resolve —
      and the skill is `user_invocable: false`, so a caller sees a sub-skill
      that silently found no tools rather than an error naming the cause.
      Rewriting 84 names against `api_request` was not done, deliberately:
      DataForSEO is a paid API and nothing may depend on it. Instead SKILL.md,
      prompt.md and the tool catalogue each open with the version gate, what to
      check, the two ways forward, and the statement that the keyless path for
      the same questions is `/seo` and `/seo geo`.

- [ ] 🟡 **Re-measure the path-scoped rule channel on 2026-11-16, and delete it if
      it did not land.** `configs/rules/` shipped 2026-09-17 as the answer to
      "move the review to where the writing happens". It is a BET, not a measured
      result: the evidence behind it is that a prose rule in a context file is
      followed ~64% of the time and decays within a session (arXiv:2605.10039),
      so proximity *should* beat position — and no study says it does. Every
      other change in that batch is a correction; this one is a hypothesis, and
      it is the only thing in this repository with a delete-by date, which is
      itself the gap two independent reviewers named: 26 proposed actions, two
      withdrawal conditions.

      What to run, and what each answer means:

      ```bash
      # 1. Is the channel reaching sessions at all? Sentinels are per session per
      #    rule file and are garbage-collected after 7 days, so this is a 7-day rate.
      #    Since 2026-10-18 a subagent writes its own <sid>.agent-<id> sentinel,
      #    and the hook also fires on Bash: compare against post-change weeks only.
      #    Sentinels also hold `#<cksum> <size>` body keys now; drop those lines.
      cat ~/.claude-profiles/*/projects/*/.claude/sessions/*.rules-injected \
        2>/dev/null | grep -v '^#' | sort | uniq -c | sort -rn
      # 2. Are the rules still TRUE? Each one states a measured fact. Re-run the
      #    measurements named inside configs/rules/*.md; a rule whose fact no
      #    longer holds is worse than no rule.
      python3 configs/scripts/check-asserted-numbers.py
      ```

      **Zero injections, or rules whose facts no longer reproduce → delete
      `configs/rules/`, the install.sh deploy block and the four cases in
      tests/test-hooks.sh.** Do not keep it on the argument that it ought to work.
      A channel nobody reaches is the wired-and-empty defect it was built to fix,
      one level up.

- [ ] 🟡 **Convergence is not proven, and round 6 says why.** Rounds 1-5 audited
      the tree and found 61, 25, 34, - and 23; 43% of the last were siblings of
      earlier fixes, which the sibling gate now catches mechanically. Round 6
      changed the question and audited the SEVEN SCRIPTS WRITTEN THAT DAY, with
      every finding independently refuted before counting. It confirmed 34.
      New code carries defects at a rate manual review does not catch, and five
      of the 34 were self-tests that could not fail — the exact class the day
      was spent gating. Both structural answers are now in place
      (`check-sibling-facts.py`, `test_self_tests_can_fire.py`). What is NOT
      established is whether a second pass over the same scope, after fixes,
      returns near zero. Run it before claiming convergence.

- [ ] 🔵 **Three resolve-eval fixtures hard-code `python -m pytest`.**
      `evals/resolve_cases/synthetic-*.json` name a bare `python`, whose
      packages resolve through the user site directory computed from $HOME. The
      harness scores them fine on a normal machine and on CI; under a different
      HOME the subprocess cannot import pytest, the parser sees no result lines,
      and three tests fail. `_pytest_launcher` was hardened for exactly this
      (it now verifies the launcher RUNS, not just that `which` finds it), but
      these fixtures bypass it by naming their own command. Either template the
      interpreter for BUNDLED cases only — a user-supplied `test_cmd` must
      never be rewritten, the harness promises to run what it is given — or
      state in the fixtures that they assume pytest on the default `python`.

- [x] 🔵 **`templates/CLAUDE.md` is orphaned — confirm deletion.** DONE 2026-09-16: deleted. install.sh
      §10 was the only code that read it and was removed 2026-09-12 as dead
      (§8 already deploys `configs/CLAUDE.md`, the maintained source, and §10
      copied a frozen 2026-02 snapshot only when the target lacked "Agent
      Ground Rules" — so on any machine that had installed once it did nothing,
      and on a fresh one it raced §8 with stale content). The live project
      template is `configs/templates/CLAUDE.md`, which `test-pr-scope-policy.sh`
      now pins instead. Nothing reads the root copy. Deleting it needs your
      word; leaving it is one more frozen file that will be mistaken for source.

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
- [x] **Dependency scanning — decided and built.** `pip-audit` and `npm audit`
      run weekly in `ci.yml`'s `dependency-audit` job as of 2026-09-02, and the
      four highs the npm half found were fixed on 2026-09-02 (`a9cb20e`). What remains
      genuinely undecided is narrower than the original item: a Dependabot
      config and a CodeQL step. Neither is scheduled; say so rather than
      leaving the whole question open, which made the built half invisible.
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

- [x] 🔴 **Credential rotation — owner decided not to rotate.** 2026-09-12: the
      13 credentials found by the census were masked from disk; the owner
      判断 rotation is not needed and closed it. The census table and the
      re-check command stay in git history if that changes. Nothing further to
      do here.

- [ ] 🟡 **Two session transcripts still hold 12 occurrences.** Mode 0600,
      owner-only, and they are the harness's own resumable state, so they were
      deliberately left alone: for a leaked key the remedy is rotation, after
      which every copy is inert.

      **The owner has since declined rotation** (2026-09-12), which inverts
      this. With no rotation coming, the plaintext in those two files stays
      live indefinitely, so scrubbing is the only remaining mitigation rather
      than an optional tidy-up before a rotation that would make it moot. Left
      for the owner rather than done: these are their own session files, and
      scrubbing edits the harness's resumable state.
      `python3 configs/scripts/scrub-corrections.py ~/.claude/projects/-home-alexshen-projects/438ce949-b228-4732-8f6e-7bfc8a3feae7.jsonl ~/.claude/projects/-home-alexshen-projects-business-business-tools-tinyfish-partnership-research/ad98341a-1dcf-42ee-b85b-3ab4eb5461e4.jsonl --apply`

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
- [x] 🔵 `reactions.create_executor_from_config` has zero production callers and reads a settings key that no longer exists. Removing it means dropping three tests in `test_leaf_modules.py`. DONE 2026-09-08 — removed, with the three tests that only covered it.
- [x] 🔵 Nothing enforces the top-level `docs/*.md` header convention; two of fourteen files had drifted off it and no gate noticed. Cheapest control: assert in `check-references.py` that every top-level `docs/*.md` links `../README.md` in its first three lines. DONE 2026-09-08 — `check-references.py` now asserts every top-level `docs/*.md` links back to the README in its first lines, and the two drifted files were fixed. Red-phase checked against a deliberately broken page.
- [x] 🔵 The global agent rules assert that `/sync` flags a README over 300 lines. The shipped skill has no such logic — its only line-count rule caps `PROGRESS.md` at 100. Implement the check or correct the claim. DONE 2026-09-08 — implemented in the skill rather than by correcting the claim, and the generated mirrors were regenerated.
- [ ] 🔵 Web lint has no home. The `npm run lint` script was deleted because eslint was never installed; re-adding it properly needs a `web` job in `ci.yml` and the coupled CLAUDE.md checklist line, which `check-ci-checklist.py` enforces.
- [ ] 🔵 **Kimi footer quota: upstream the payload, retire the spawn.** `/kimi-usage`
      and `~/.kimi-code/hooks/statusline.sh` (2026-09-18) get plan usage through
      `kimi web`'s documented `GET /api/v1/oauth/usage`, which means the footer's
      background refresh boots a ~600 MB Kimi server for ~2 s up to every five
      minutes unless one is already running. Kimi's `status_line.command`
      snapshot carries only session state, and upstream already has open requests
      for the managed quota in the footer (MoonshotAI/kimi-code #872, #1835,
      #3231; ACP frames #2483; direct-endpoint policy #2937 unanswered). The
      repository accepts community TUI PRs (#2255 shipped the status line itself).
      A PR adding `usage: { limit5h, limit7d, monthTotal, monthCode }` to the
      snapshot — the exact analogue of Claude Code's `rate_limits` — would let the
      helper read it from stdin as `claude-usage-watch.py --statusline-input` does
      and delete the cache-and-spawn path. Until then the Kimi wiring is skipped
      under Git Bash (Kimi runs the command via cmd.exe), same gap as the guardian
      hook.
### Standing-brief configuration — 2026-09-02
      **INVESTIGATED 2026-09-08 — the premise is inverted.** Nothing reads the
      report because it has never once been produced: no
      `~/.claude/patrol-report-*.md` has ever existed on this host and no
      `start.sh --patrol` appears in six months of history; the only automatic
      trigger lives in the dormant orchestrator. The ingestion is also largely
      already built — the report's Raw Findings section already parses as the
      `===TASK===` format `run-tasks.sh` consumes.
      What was actually broken is the scanner's precision, and that half is now
      FIXED: its prunes were anchored at the scan root, so every nested
      `node_modules`, `dist`, `.venv` and `.claude/worktrees` copy sailed through.
      On this repository the scan emitted **217 task blocks; it now emits 5**.
      Building ingestion on top of the old output would have queued a thousand
      "split typescript.js" tasks.
      REMAINS YOURS TO DECIDE: whether patrol should run at all, given that it
      never has. If it should, the ingestion bridge is a few lines, not a
      pipeline.

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
- [x] 🔵 `install.sh --ultracode` has no test. `tests/test-install.sh` covers the
      spawn-depth merge next to it; the same shape applies — assert the two keys
      land, that an existing `settings.json` key survives the merge, and that an
      invalid size falls back to medium rather than writing garbage. ALREADY DONE — and it was already done when the item was filed. `43d3b7a` closed it eleven minutes after `a662335` opened it; only the checkbox was never ticked. All three named behaviours are covered by "Suite 10" in `tests/test-install.sh`, including the `cleanupPeriodDays=4242` canary for the key-survival case.

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
- [x] 🟡 **The scope rule is mechanical now, not a note.** DONE 2026-09-02.
      `docs/layers.json` declares each surface as `load-bearing`, `dormant` or
      `generated`, with the reason and the date, and defines that vocabulary in
      the file itself rather than somewhere a reader has to find. The
      orchestrator is `dormant` with an explicit "do not delete, do not treat as
      debt; CI keeps it compiling and that is the contract".
      `/review`, `/cso` and `/next` each read it before ranking anything, so the
      marker changes what an audit does rather than merely existing.
      `configs/scripts/check-layers.py` keeps the declaration matching the tree —
      unknown status, path that does not exist, dormant with no reason, and an
      unclaimed source directory each fail it, checked one at a time. It caught
      two unclaimed directories on its first run, which is why the `cli` layer
      lists eight paths and not five.

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

- [x] 🟡 **Codex fan-out: the premise was wrong and the measurement shipped.**
      The original item said `codex exec` cannot subdivide. It can — measured
      2026-09-05 on this host's `~/.codex/state_5.sqlite`, which holds
      `source='exec'` parent threads with depth-1 children, reproduced live on
      CLI 0.153.4. The gate is the resolved model's catalog
      `multi_agent_version`, not the session source, so the capability is
      CONDITIONAL with the condition written down rather than UNSUPPORTED.
      The measurement half shipped too: `workflow-scorecard.py --codex-children`
      counts what a Codex worker actually delegated, with a self-test that
      distinguishes a real zero from an unreadable state file.
      **Still genuinely open, and narrower:** nothing counts N externally
      spawned `codex exec` processes as one fan-out. That is Clade's own
      parallelism over Codex, not Codex's, and the worker pool that would do it
      is in the dormant layer.
- [x] 🟡 **The polling rule now has a number.** DONE 2026-09-02.
      `workflow-scorecard.py --polls` reads lead-session transcripts and reports
      repeated status reads per background job, beside the straggler figures. A
      poll is a status-only Bash call that is not the first of its kind — the
      repetition is what makes it a poll, since checking once is a check.
      **The first version could not fire, which is the finding.** Its mutation
      guard was a bare `>>?[^&]`, and that matches the `>/` of `2>/dev/null`, so
      every status command that silenced stderr was classified as mutating and
      every session ever scanned reported zero polls. Zero read as discipline.
      Fixed, and it now reports 30 polls against 35 jobs in one recent session
      and 8 against 30 in another.
      Because this is the second instrument here to ship unable to fire, it has
      a `--self-test` with a positive and a negative control, wired into the
      same CI job as `red-phase-audit.py --self-test`. Reintroducing the
      original regex fails it.

- [x] 🟡 **Measured why the learning system does not measurably learn.** The
      item said measure the existing rules' effect before adding capture. Done
      2026-09-02, and the answer is that the instrument cannot fire, for two
      independent reasons.

      1. **`rule-effectiveness.json` is `{}` — it has never recorded anything.**
         Not a wiring bug: `record_rule_miss` is called, and reached. The gate in
         front of it is `RULE_DOMAINS[i] == DOMAIN`, and the two sides speak
         different vocabularies. `detect_domain` emits a closed set of eleven
         labels (frontend, backend, ml, devops, security, unknown…). Rules are
         filed under free text the model invents at write time —
         `windows-remote-probe`, `verify-gating`, `throughput`, `scope`,
         `proposals`. **The equality can essentially never hold**, so the best
         match is never found and no miss is ever recorded.
      2. **`stats.json` was not valid JSON.** It held two nested sets of
         unresolved `<<<<<<< Updated upstream` / `>>>>>>> Stashed changes`
         markers, so every `jq` increment failed into its own `|| rm -f` and was
         discarded, for an unknown length of time. A counter that stops counting
         looks exactly like a quiet week. `correction-detector.sh` now validates
         the file, keeps the unreadable copy beside it, and reseeds — pinned by
         three assertions in `tests/test-correction-pairing.sh`. The live file is
         repaired by taking the largest value seen per key across the conflicting
         branches, since counters only increase.

      **Deliberately not "fixed" by loosening the match.** The word-overlap
      score the code already computes was tried against the real rules: for a
      correction about a hardcoded model and a stale deployed copy, the top
      match was a rule about auditing asset provenance. Common English words
      dominate. Shipping a threshold on that would replace an absent number with
      a wrong one, which is worse. What is needed is a shared vocabulary between
      the classifier and the rule format, and that is a design decision, filed
      below rather than guessed at.

- [ ] 🟡 **Decide the shared vocabulary for rule domains.** Either constrain the
      rule format's domain field to `detect_domain`'s closed set (loses the
      specificity of `windows-remote-probe`), or give each rule both a free-text
      tag and a closed-set domain, or replace equality with a real similarity
      measure validated against labelled pairs. Until one is chosen, rule-miss
      counting stays structurally impossible. Evidence and the rejected option
      are in the item above.

- [x] 🔴 **The catastrophic-`rm` guard reads flags out of FILENAMES, and it is
      the same textual-matching defect as the literal-path blindness already on
      record.** `pre-tool-guardian.sh:115-116` (and the duplicate pair at
      `169-170`) test the whole statement string for `\brm\b.*-[a-zA-Z]*r` and
      `.*-[a-zA-Z]*f` to decide that `-r` and `-f` were passed. Any hyphen in an
      operand can supply them. Reproduced 2026-09-07 on this host: `rm -f
      /home/alexshen/.claude/research/.radar-write-probe` was blocked as
      "Catastrophic rm -rf blocked on system/home directory" — there is **no
      `-r` flag in that command at all**; the `-wr` inside the filename
      `.radar-write-probe` matched, `-f` matched the real flag, and `/home`
      matched `DANGEROUS_NAMED_PATHS`. So any non-recursive `rm -f` under
      `/home` whose filename contains a hyphen followed by letters and an `r`
      is blocked, which is a large share of ordinary cleanup.
      This is the OVER-blocking mirror of the under-blocking already logged in
      `~/.claude/research/known-concepts.md` (2026-09-05, "literal-path guard
      blindness": the same guard allows `rm -rf $VAR/`, `${VAR}/` and bare
      globs). One root cause, both directions: the guard matches command TEXT
      instead of parsing argv. Fix is to classify tokens — options only before
      the first non-option operand — not to add more regex.
      **Not fixed in the 2026-09-07 radar run on purpose:** this is the
      always-on destructive block, the highest-stakes guard in the stack, and
      that run had no execute permission, so not one test could be run against
      a change to it. Needs a lead session with a working verifier.
      DONE 2026-09-07. The verifier it was waiting for is the suite built
      the day before, so this was fixed with tests rather than by reading.
      Both guardians now classify tokens: a token supplies flags only when
      it starts with `-`, after a `--` nothing does, long forms are read by
      name, and an option may still follow an operand because GNU rm
      permutes — what an operand may never do is BE one. The dangerous-path
      match is unchanged; only the flag question moved.
      The blast radius was wider than filed: the rewrite and refuse paths
      added on 2026-09-05 had copied the same text match, so a plain
      single-file `rm -f` of a variable path was being rewritten and one
      under a command substitution refused, both on the strength of a
      hyphen in the filename. Seven assertions failed before the fix; the
      suite is 95 cases with 30 of them parity checks, and the seventeen
      ordinary commands sweep clean.

- [x] 🟡 **`domain` is now written on every correction record and is `unknown`
      on every one of them.** Moving the call before the append
      (`correction-detector.sh:147`) fixed the *field's absence*, not its
      *value*: measured on this machine, all 32 records carrying `domain`
      (2026-09-02 → 2026-09-07, every record since the field was added) are
      `"unknown"`, so the rule-effectiveness matching the move was meant to
      restore still never fires. Cause is in the classifier's INPUT, not its
      vocabulary (distinct from the item above): `domain-detect.sh:15` derives
      the file list from `git diff --name-only --diff-filter=ACMR HEAD`, which
      **exits 0 with empty output on a clean tree**, so the `||` fallbacks never
      run and every grep misses. UserPromptSubmit is exactly when the tree tends
      to be clean — the user says "that's wrong" after the work was committed.
      The fix is a design choice, which is why it is filed: the session shadow
      (`cp_recent_files`, already read in this same hook) is the obvious
      alternative input, but it changes what `domain` MEANS — "files in the diff
      right now" vs "files Claude touched this session" — and that redefinition
      propagates into `stats.json` and every rule-miss count. Pick the meaning
      first. Note `_STATS_SEED` (`correction-detector.sh:173`) also lacks four
      domains `detect_domain` can return (`devops`, `security`, `cli`,
      `mobile`), so those increments land on a key that was never seeded. DONE 2026-09-08 — the classifier was starved of input, not of vocabulary, exactly as the item argued. This is the one that unblocks rule-effectiveness matching.


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

- [x] 🔵 `orchestrator/ruff.toml`'s "Known live bugs" block still describes two
      parked per-file-ignores in the present tense. Both bugs were fixed and both
      entries deleted in the same commit, so a maintainer triaging a
      worktree-cleanup failure is told `Worker.stop()` currently raises. Rewrite
      as a past-tense note about what the gate's first run found.
- [x] 🔵 `docs/MIGRATE_FROM_HERMES.md` still lists `compression_feedback.py` as
      "present in Clade today"; the module was deleted by this branch.
      `check-references.py` does not resolve backticked `orchestrator/*.py`
      paths, which is why nothing caught it — teaching it to would also have
      caught the stale CLAUDE.md map line.
- [x] 🔵 The 0.3.1 CHANGELOG section omits the release's own security work — the
      two HIGH starlette advisories, prompt redaction, per-user runtime paths,
      the MCP event-loop fix — and the two compatibility notes an upgrader needs
      (`/web` now 503s until built, `reaction_configs` and `patrol_auto_ideas`
      removed). Its `[0.3.1]` compare link also points at a tag the release
      deliberately did not create.
- [x] 🔵 `configs/skills/brief/prompt.md` probes the orchestrator with an
      unauthenticated curl and now reports it offline. Add the bearer header the
      way `docs/configuration.md` documents, then regenerate the mcp-package
      mirror.
- [x] 🔵 `configs/scripts/usage-agent.py`'s docstring and `CLAUDE.md`'s usage line
      still say "leave empty for open ingest". Ingest is exempt from the control
      plane only while `usage_ingest_token` is set, so an empty token now means
      the node must send the hub's `api_token` instead.
- [x] 🔵 `session-context.sh`'s dropped-rules notice counts header and blank lines
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
      all three clean. DONE 2026-09-08 — rewritten as a past-tense record of what the gate's first run found. Verified that every config-bearing line is byte-identical and that F821 still fires. DONE 2026-09-08. DONE 2026-09-08 — added to both language files. DONE 2026-09-08, and the review caught it half-finished. The premise was also wrong: the route and port were correct, the real defect was a bare `curl` with no bearer token. The first delivery fixed that and left the mcp-package mirror stale, which turns a green gate red; the lead regenerated it before landing. DONE 2026-09-08, both halves. The docstring told operators ingest was open by default, which stopped being true when `TokenAuthMiddleware` landed: `/api/usage/ingest` is exempt from the control-plane token only WHILE `usage_ingest_token` is set, so leaving it empty requires a token rather than removing the need for one. `CLAUDE.md` said the same thing wrongly and is corrected, including the distinction from the separate `usage_hub_token` setting an orchestrator-running node uses. DONE 2026-09-08 — it counts rules now, pinned by a test.

- [ ] 🟡 Anthropic's documented fix for the other half of the prompt-cache miss —
      stagger a fan-out so the first response primes the shared prefix before
      the rest are sent — is not implemented. Only the system-prompt half is.
      Claude Code already does this inside its own Workflow runtime.
- [ ] 🟡 Adversarial verification with N skeptics is measurably overspent:
      Terminal-Bench V2 puts pairwise verification at 73.1% with one judge and
      77.5% with sixteen. This session ran three refuters per finding. One
      better-calibrated verifier returning a score plus its evidence belongs in
      `worker_review.py` instead.
- [x] 🔵 Three tests in `test_static_serving.py` use `with TestClient(...)`, which
      runs the FastAPI lifespan and therefore mints a control-plane token into
      the developer's real settings file. They exercise routing only and do not
      need it. DONE 2026-09-08 — the routing tests no longer boot the server that mints a token.
      **INVESTIGATED 2026-09-08 — half is already built, half is your call.**
      Measured against the tree: `oracle_verdict_samples` defaults to 1 and a
      default review spends two judge subprocesses, one per pass — not N
      skeptics. The only place N>1 is forced is a security or data-sensitive
      diff, bumped to 3 as a deliberate control on the auto-merge gate, and the
      cited numbers (73.1% at K=1 vs 77.5% at K=16) are a COST argument, not a
      correctness one — cutting it would be weakening a gate, which this sweep
      is not allowed to do.
      What is genuinely unbuilt is replacing the categorical confidence with a
      calibrated numeric score, which moves the threshold that authorises
      auto-merge. Nothing here measures oracle confidence today, so the
      threshold is yours to pick before anyone can implement it.

- [x] 🔵 `orchestrator/tests/test_worker_modules.py` is 1446 lines, 54 under the ceiling. The natural split lifts the autoscale and fan-out sections into their own file.
- [x] 🔵 `tests/test-loop.sh` is 1442 lines, 58 under the ceiling, and the loop-runner split just pushed it there by adding deploy-parity entries. It is now the closest first-party file to the gate after `test_worker_modules.py`.
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
      red-phase checked separately. DONE 2026-09-08 — autoscale and fan-out moved verbatim into `test_autoscale_and_fanout.py`; the total test count is unchanged. DONE 2026-09-08 — the environment suites moved into a sourced sibling (`tests/test-loop-env.sh`), so the entry point named by CI and the checklist stays `tests/test-loop.sh` and neither needed editing.

- [x] 🔵 `node_test_sample` and `node_health_check` communicate through three bare globals (`LAST_TEST_OUTPUT`, `LAST_TEST_RESULT`, `PREV_FAILED`) that are now a cross-file coupling between `loop_verify.sh` and `loop-runner.sh`. Sourced shell makes it work; the `# Writes:` header is the only thing recording it. DONE 2026-09-08 — the verify state is a declared interface rather than three loose globals, with behaviour unchanged.

### Codex GPT-5.6 review — 2026-09-05

Filed from [`docs/research/2026-09-05-codex-gpt56-and-harness-review.md`](docs/research/2026-09-05-codex-gpt56-and-harness-review.md).
23 readers over the upstream source at `4df8027a97`, the 0.150–0.153 release
notes, the live model catalog with its per-model system prompts, this host's
Codex state databases, and the wider field. The yield is the same shape as the
2026-08-29 sweep: almost nothing upstream is a capability this toolkit lacks,
and what the sweep actually found is places where **this repository's own
record is wrong**. The four below were reproduced by hand before filing.

- [x] 🔴 **Both guardians allow every recursive delete an agent actually
      writes.** Measured with a probe that feeds real `PreToolUse` payloads to
      `configs/hooks/pre-tool-guardian.sh` and
      `plugins/clade/hooks/pre_tool_guardian.py`: both block the literal
      catastrophic forms, and both ALLOW the same recursive-force delete when
      the target is written as `$BUILD_DIR/`, `"$BUILD_DIR"/`, `${OUT}/`,
      `$OUT/` plus a star, `$(pwd)/` plus a star, `./` plus a star, or a bare
      star after a `cd`. The force-push rows are the control: both hooks ran
      and both acted, so those ALLOWs are decisions, not a dead hook. In Claude
      Code every Bash call is a fresh shell, so a variable set in an earlier
      call is unset in this one and the target expands to the filesystem root —
      the exact string `tests/test-pre-tool-guardian.sh` asserts a block for
      when it is typed literally. `rm --preserve-root` does not help, because
      the expanded argument is root-plus-star rather than root.
      The fix shape is already in the same file: the force-push branch answers
      `{"decision":"allow","updatedInput":{…}}`. Rewriting an unassigned
      `$NAME` target to `${NAME:?guardian: recursive delete on an unset
      variable}` leaves a set variable untouched and makes an unset one abort
      naming itself; command substitution and glob-only targets have no safe
      rewrite and should be refused. Needs the mirrored change in the Codex
      hook and cases in `tests/test-pre-tool-guardian.sh`, which today contains
      no unset-variable or glob-target case at all.
      DONE 2026-09-06. Both guardians now answer a delete they cannot
      resolve: a target headed by an unassigned `$NAME` is rewritten to
      `${NAME:?…}` through the same `updatedInput` shape the force-push
      branch already used, so a set variable runs untouched and an unset
      one aborts naming itself; a command substitution or a bare glob is
      refused, because neither offers a name to make required. A delete
      inside single quotes is left alone. `tests/test-pre-tool-guardian.sh`
      grew a REWRITE verdict and thirteen cases; sixteen assertions failed
      against the unfixed hooks before any code changed. A sweep of
      seventeen ordinary commands produced no new block.
      Known limitation, pinned as its own case rather than left to
      surprise someone: the rm rule has always been blind to command
      position, so delete text inside a DOUBLE-quoted string is rewritten
      too. Fixing that means command-position parsing for `rm` while
      keeping `echo $(rm …)` blocked, which is a larger change than this.

- [x] 🟡 **The two guardians have drifted, and the parity pair is untested.**
      The shell hook blocks a recursive delete of `/home`, `/etc`, `/usr`,
      `/var`, `/sys`, `/proc`, `/boot`; the Codex mirror's regex covers only
      root, `~`, `$HOME` and `${HOME}` at token start, so it allows what the
      Claude side blocks. `configs/codex-migration.json` records the two as a
      parity pair and `orchestrator/tests/test_codex_migration_policy.py`
      checks that pairing, but nothing feeds one command to both hooks and
      compares verdicts. That table-driven test is the durable fix; aligning
      the regex alone would drift again.
      DONE 2026-09-06, and the drift was wider than filed. Beside the
      named system paths, the Python mirror split commands on LINES where
      the shell hook splits on statements, so a home path merely sharing a
      line with a benign delete read differently on the two surfaces. Both
      now split on `;|&`. `assert_parity` feeds one command to both hooks
      and fails when the verdicts differ; twenty-two commands run through
      it, seven of which failed before the fix.

- [x] 🟡 **"Codex cannot fan out" is false, and it is written down three
      times.** `~/.codex/state_5.sqlite` holds two `source='exec'` parent
      threads that spawned depth-1 children on CLI 0.145.0, using Clade's own
      roles: `clade_cheap_explorer`
      (99,654 tokens, 2026-08-01) and `clade_cheap_worker` (58,092 tokens,
      2026-09-02). Upstream says why: the predicate that adds the spawn tools
      to a turn reads only the resolved model's `multi_agent_version` and never
      the session source, and `SessionSource::Exec` is whitelisted as a
      delegation root beside Cli and Mcp. So `orchestrator/worker_provider.py:363`
      (`subagents: UNSUPPORTED`, sourced "codex exec has no headless sub-agent
      spawn"), the docstring and `test_codex_subagents_is_not_a_shrug` in
      `orchestrator/tests/test_subagents_capability.py`, and the open item at
      the end of the 2026-09-02 audit section are all built on a false premise.
      The honest value is CONDITIONAL **with the condition written down** —
      delegation depends on the resolved model's catalog `multi_agent_version`
      (Sol and Terra carry v2, Luna v1) and, under v1, on explicit authorization
      in the prompt or `AGENTS.md`, which the managed block already grants when
      it tells Codex to delegate to `clade_cheap_explorer`. That is very likely
      what authorized both observed spawns. Note the test that forbids
      CONDITIONAL must change with it, and `configs/skills/codex-orchestrate/prompt.md:3`
      was right all along — it calls itself the manual version of native
      `ultra` fan-out.
      Reproduced live on 2026-09-05 against CLI 0.153.4: a headless
      `codex exec --json` run asked to delegate emitted a `collab_tool_call`
      and created a third `source='exec'` spawn edge (child depth 1, role
      `clade_cheap_explorer`, 55,549 tokens). The spawn is invisible in the
      JSONL — only the `wait` item appears, with an empty
      `receiver_thread_ids` — so a supervisor watching the event stream cannot
      see its worker's children and must read `~/.codex/state_5.sqlite`.
      DONE 2026-09-06. `subagents` is CONDITIONAL with the condition in
      its `sources` entry — the resolved model's catalog
      `multi_agent_version`, and under v1 delegation being authorised in
      the prompt or `AGENTS.md`. The gate did not weaken: REQUIRED admits
      SUPPORTED only, so a run that must subdivide is still refused on a
      route we cannot prove; only the PREFERRED degradation changed, from
      `unsupported` to `conditional`. The test that forbade CONDITIONAL
      now asserts the condition names `multi_agent_version` and that the
      falsified reason cannot come back. Three of its assertions failed
      against the old value first.

- [x] 🔵 **The cheap Codex tier is set to the middle tier.** Both the live
      catalog and upstream's bundled one encode `gpt-5.4-mini` ("small, fast,
      cost-efficient") → `gpt-5.6-luna` and `gpt-5.4` ("strong model for
      everyday coding") → `gpt-5.6-terra`, so OpenAI's own lineage puts Luna in
      the cheap slot. Clade sets Terra as `codex_cheap_model`
      (`orchestrator/config.py:312`, `templates/orchestrator-settings.example.json:116`,
      `docs/codex.md:215`), as the model of both profiles in
      `configs/codex-agents/`, and instructs Codex in prose to use it
      (`configs/CODEX_AGENTS.md:69`). Luna appears nowhere in the repository.
      The two profiles exist for bounded read-only discovery and one low-risk
      implementation, which is the cheap slot's job. Luna has the same tool
      surface, the same context window and the same effort ladder minus
      `ultra`, which a bounded subagent has no use for. Per-token prices are
      not in either catalog, so the saving is not quantified here.
      DONE 2026-09-06. `codex_cheap_model` and both `configs/codex-agents`
      profiles are `gpt-5.6-luna`; `codex_strong_model` stays Sol. The
      generated settings reference was regenerated rather than hand-edited.

      **Amended 2026-09-12:** two doc pages still named Terra as the cheap
      default — `docs/codex.md:223` and `docs/codex.zh-CN.md:178` — and
      `worker_routing.py` hard-coded `gpt-5.6-terra` as the fallback for a
      missing setting at two sites, so a machine with no explicit setting
      routed cheap work to the mid tier. Both fallbacks now read
      `_SETTINGS_DEFAULTS`, which removes the duplicate literal rather than
      re-syncing it.
- [x] 🟡 **`AGENTS.override.md` outranks `AGENTS.md`, so the managed block can
      be installed and never read.** Codex resolves instructions
      first-filename-wins with no merge, at both scopes:
      `LOCAL_AGENTS_MD_FILENAME = "AGENTS.override.md"` is probed before
      `AGENTS.md` in `codex-rs/codex-home/src/instructions/mod.rs:10` (home) and
      `codex-rs/core/src/agents_md.rs:42` (project), verified at the
      `rust-v0.153.4` tag. `install.sh` merges the Clade block into
      `~/.codex/AGENTS.md` and is careful in every other respect, but if an
      override file exists beside it Codex reads that instead and the merge is
      invisible. The string appears nowhere in this repository. Fix: warn at
      install time naming the shadowing file, never delete it (same report-only
      policy as the orphan sweep), plus a case in `tests/test-install.sh`. The
      same precedence also makes a claim wrong in four places — `docs/codex.md`
      states the order as AGENTS.md then CLAUDE.md, two skill surface files
      repeat it, and `configs/skills/delivery/scripts/git_context.py` implements
      that flat probe in code.
      DONE 2026-09-06. `install.sh` warns when a non-empty override sits
      beside the file it just merged, names it, states that the managed
      block will not load, and neither deletes nor moves it — the merge
      still runs, so removing the override is the whole fix. It tests `-f`
      as well as `-s`, because `[[ -s dir ]]` is true for a directory that
      Codex would never resolve. Three assertions in
      `tests/test-install.sh` failed against the unfixed installer, while
      the clean-install and file-preservation cases passed either way. The
      precedence is now stated in `docs/codex.md`, its Chinese copy, the
      two skill surface files, and implemented in `git_context.py`, which
      probes the override first and skips that directory's `AGENTS.md`
      when it finds one.

- [x] 🟡 **The Codex `SessionStart` hook misses `clear`, and the reason it
      matters is already written down on the Claude side.**
      `configs/settings-hooks.json:6` runs on `startup|clear|fork` and carries
      the rationale in its own description field: clear and fork mint a new
      session id with no baseline, so a startup-only matcher silently disables
      the stop gate for every cleared or forked session.
      `plugins/clade/hooks/hooks.json:5` says `startup|resume|compact`. Same
      lesson, learned on one surface, not carried to the other. Fix is the
      matcher plus an assertion in `orchestrator/tests/test_codex_plugin.py`,
      which today pins only which event names exist, not their matchers.
      DONE 2026-09-06, with a correction worth keeping. The first attempt
      at this — by a loop worker — set the matcher to `startup|clear|fork`,
      dropping `resume` and `compact` and adding `fork`, and wrote a
      docstring asserting that Codex has no `resume` source. The released
      enum says otherwise: `SessionStartSource` in
      `codex-rs/hooks/src/events/session_start.rs` at `rust-v0.153.4` has
      exactly `Startup`, `Resume`, `Clear`, `Compact`, and no `fork`. The
      matcher is `startup|resume|clear|compact`, and the test cites the
      enum so the next reader does not have to re-derive it.

- [x] 🔵 **A fabrication record went stale and now suppresses a real feature.**
      `docs/research/2026-08-29-ecosystem-audit.md:51` records `PostModelSwitch`
      and `--restricted` as fabrications that do not exist in CLI 2.1.236. Both
      shipped since: `grep -ac` against the installed 2.1.258 binary counts 38
      occurrences of `PreModelSwitch` and 17 of `PostModelSwitch`, and
      `--restricted` is in `claude --help`. The entry was correct when written
      and is read by later audit rounds as a standing claim, so left alone it
      does the inverse of its purpose. Amended in place this round; the general
      rule is that a "does not exist" finding needs a version stamp, because
      absence is only ever true of one build.
      DONE 2026-09-05 in the review PR: the entry carries a dated
      amendment naming both shipped features and the versions that shipped
      them.

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

## 2026-09-18 converge-loop 实战暴露的 loop-runner 缺陷（business/artifact 收敛 run 实录）

- [ ] 🟠 `node_commit_changes` 清扫无差别——worker 在 repo 内建的嵌套 git 对象（13,053 个文件，logs/claude-tasks/shadow/*.git）被整体扫进 main 并推送（business `e03bb70c`，已 revert `fa81f743`）。清扫应排除 `.git`、logs/、node_modules/ 或仅限 task-owned paths（与 CODEX_AGENTS.md 的 stage-only-task-owned-paths 同规则）。
- [ ] 🟠 脏工作树让 hydrate_context 爆炸——context 含 13,094 行 git status 时 supervisor 传参超 ARG_MAX（`/usr/bin/timeout: Argument list too long`，exit 126）。hydrate 应对 git status 截断/排除未跟踪目录，或 context 经 stdin/文件传入而非 argv。
- [ ] 🟡 goal 复选框无自动勾稽——6 迭代全程 "10 unchecked"，收敛只能靠人工核验后勾。score_and_write 应把已完成 work item 回写 goal（`_From:` 段对账），否则收敛判定恒为 not-done。
- [ ] 🟡 loop 在任何 cwd 的 repo 原地跑 `pnpm build` 类门——会打断从该 checkout 服务的生产进程（本次直接把 companyOS 运行中构建的静态资产搞成 503）。goal/loop 文档应要求 worker 门在 worktree 或要求 lead 确认目标 checkout 非生产服务源；或在 loop_args 加 `--worktree` 默认。
- [ ] 🟡 目标文件必须是 checkbox 列表——纯 prose goal 会让 supervisor 返回 0 任务（stuck_no_tasks）。loop_args 起步检查应直接报 "goal 无 - [ ] 项" 而非跑三轮空转。

## 2026-09-19 design-sense-as-rules follow-ups (PR feat/design-rules)

- [ ] 🟡 `design-lint source` thresholds are the essay's numbers (4-px grid, ≤2 families, 4–6 sizes, 3–4 weights, ≤4 radii, ≤3 shadows, 400 ms, 16 px), not measured fire rates. Measured once on business/company-os (579 files): 643/1950 spacing off-grid (33%), 411 `transition-all` sites, 114/585 durations > 400 ms — a mixed tree, not a clean one. Run it on a tree the owner considers clean, record the WARN counts per check in the script docstring, and only then decide whether any WARN deserves a threshold rather than "each site needs a written reason".
- [ ] 🟡 The review loop in `design-review.md` asks for captures at 390/768/1280/1440, but nothing in the skill produces them — the agent reaches for Playwright by hand each time. A `design-shots` helper (Playwright, four widths + dark mode, one PNG per width, optional ruler overlay) would make the loop's first step mechanical; `seo-visual` already carries the Playwright pattern to borrow.
- [ ] 🟠 `configs/scripts/design-lint.py` is at 1,489 of the 1,500-line ceiling after the `source` lane and its runtime checks landed. The next change to it must split first, not trim: the source lane (`# ─── Lane: source` through `lint_source`) is self-contained except for `Report`, `resolve_value`, `custom_properties`, `_STYLE_BLOCK` and `_FOCUS_RESTORE`, which the `html` lane shares — move those five into `design_lint_common.py`, the lane into `design_lint_source.py`, and keep `design-lint.py` as the CLI. `test_design_lint.py` loads the script by path (hyphenated name), so the split module needs the same `spec_from_file_location` treatment; `install.sh` already copies every `configs/scripts/*.py`, so deployment needs no change.

## 2026-09-20 skill listing budget follow-ups

- [x] 🟡 ~~Trim the longest model-facing descriptions to bring the fraction back to 0.04~~ **Done 2026-09-20, landing at 0.05 instead of 0.04 — decision recorded:** every named skill was trimmed (radar, localize, codex-orchestrate, frontend-design, banana, plus the next tier: outbound, seo, loop, qa-explore, domain-model, landscape, equip, review, audit, internal-deploy, skill-new, obs-review-loop, converge-loop, go) and the email hub (next item) made email-check name-only. Listing: 38,660 → 33,998 chars; minimum fraction 0.0424. Two things moved the target: (1) the fraction is a CAP, not the cost — what is sent is the listing itself (~8.5k tokens), so the trims are the saving and the fraction is only the ratchet; (2) 0.04 would leave ~zero headroom, so the next skill added would break the gate. 0.05 keeps ~6,000 chars (~15 skills) of headroom, matching the previous commit's headroom convention. Constraint discovered: the Codex plugin carries only `description`, so the platform/Chinese triggers that `test_frontend_design_pipeline.py` requires must live in frontend-design's description, not only in `when_to_use` — and every trim must keep the golden-set phrases in `test_routing_eval.py` literally (substring matching).
- [x] 🟡 ~~The six `email-*` skills have no hub~~ **Done 2026-09-20:** added the `email` hub (configs/skills/email/SKILL.md, routes check|audit|plan|review|sequence|write like `/blog`), `email-*` are name-only (81 overrides), `email` added to the codex-migration marketing-domain-bundles exclusion, and a golden routing test ("email inbox triage deliverability sequence" → email) wires the hub into `test_routing_eval.py`.
- [ ] 🟡 `RESERVED_CHARS = 8000` (bundled skills always kept in full) was measured from one session on Claude Code 2.1.258. Re-measure after each Claude Code upgrade: run `claude -p ok --debug` on a 200k model and compare the "Skill listing over budget: N skills, K chars" line with `check-skill-listing.py --no-overrides`. (2026-09-20: still on 2.1.258, no re-measure needed; also pending when quota resets Sep 21 — a headless Haiku re-run of the 7 selection prompts against the trimmed listing, since the weekly limit blocked it today. The live install was verified arithmetically instead: `check-skill-listing.py --skills ~/.claude/skills --overrides ~/.claude/settings.json --usage ~/.claude.json` → fits, 0 dropped.)

## 2026-09-20 pace-scale follow-ups

- [ ] 🔵 **`claude-usage-watch.py:_elapsed_pct` hard-codes a 7-day period.**
  Pointed at any longer window it clamps elapsed to 0, and `delta` silently
  collapses to raw usage% while `projected` reads 0 — an "ahead" badge painted
  the low-usage red. It cannot fire today because Claude Code's `seven_day`
  really is seven days, and `test_claude_usage_watch.py` pins the clamp so the
  trap is visible rather than latent. Take the period from the payload if a
  second window is ever surfaced there.
- [ ] 🔵 **The Kimi month window's START is inferred, not read.** Kimi's
  `/api/v1/oauth/usage` returns only `usedRatio` and `resetAt` (verified
  2026-09-20), so `_month_period` assumes the window opened exactly one
  calendar month before the reset. That is right for a subscription renewing
  on a fixed day and wrong for anything else, and nothing detects the
  difference. Revisit with the upstream payload work in the Kimi footer item
  above.

## 2026-09-21 radar sweep follow-ups

- [ ] 🟠 **The correction-pairing shadow is blind to a Bash-side write — the
  tool-bypass failure Ronacher named, on the pipeline that grounds every rule.**
  `edit-shadow-detector.sh` is wired to `Edit|Write` only
  (`configs/settings-hooks.json` PostToolUse) and reads nothing but
  `tool_input.file_path` (`edit-shadow-detector.sh:13`), so a file rewritten
  through the Bash tool — `python3 - <<EOF`, `sed -i`, `cat > f`, `tee` —
  never enters the session shadow. Downstream, three consumers go quiet for
  exactly those files: `correction-detector.sh`'s "Concrete signal" block
  (files behind this correction), `revert-detector.sh`'s `reverted_files`
  (shadow ∩ pathspec → `[]`, so `repeat` can never fire), and the shadow-first
  `domain` classifier added 2026-09-08. Same shape as the `worker-checkpoint.sh`
  blind spot fixed 2026-09-16 (`2acb91a`), but that fix took a snapshot; the
  shadow needs file NAMES, which a PostToolUse Bash hook does not receive.
  Capability we lack: pair a rejection with a file the agent changed from the
  shell. Shape of a fix: PreToolUse Bash records `git status --porcelain` into
  the session scratch (pre-tool-guardian.sh already runs there), PostToolUse
  Bash diffs it and appends the delta to the shadow; untracked files need the
  `--others --exclude-standard` half. Not built in the 2026-09-21 sweep: that
  run had no execute permission, and this touches two hooks with an async
  ordering question. How often it fires is NOT measured — the shadow records
  what it saw, not what it missed.
- [ ] 🟡 **Verify the 2026-09-21 sweep's four unrun changes on a machine with a
  shell**, in this order: `bash tests/test-correction-pairing.sh` (worker gate,
  §5b), `bash tests/test-hooks.sh` (secret-scanner note, needs python3),
  `bash -n configs/scripts/radar-cron.sh` + a dry `--allowedTools` check
  (`claude -p 'reply ok' --allowedTools "WebSearch,WebFetch(domain:arxiv.org)"`
  must not treat the CSV as a prompt), then `./install.sh` so the deployed
  copies under `~/.claude/` stop lagging the source. Until install.sh runs, the
  live correction detector still records worker briefs and the live
  secret-scanner still advises rotation.
  **Partly closed 2026-09-28:** `install.sh` ran 2026-09-24 19:23 (deployed
  `correction-detector.sh`, `secret-scanner.sh`, `radar-cron.sh` and
  `skills/radar/SKILL.md` were byte-identical to source at the start of the
  09-28 sweep), and `radar-cron.sh` is verified LIVE: the 09-28 cron log shows
  ten FOLDED lines and that sweep's `WebSearch` calls succeeded. The two test
  suites are still not known to have run, and the nine files are still
  uncommitted in this tree.
- [ ] 🟠 **`history.jsonl` keys a correction on the raw cwd, so one repository
  is many "projects" and recurrence can never match.** First filed by the
  2026-08-24 radar run (which never reached TODO.md — its digest sat in `$HOME`)
  at 63 distinct keys / Clade spanning 6; measured 2026-09-21 at **128 distinct
  keys over 1,223 records, Clade spanning 12** (`projects/Clade`,
  `projects/clade`, `projects/clade/orchestrator`, four `.worktrees-Clade/task-N`,
  a `.claude/worktrees/wf_*`, `/tmp/clade-fleet-fix`, three
  `/tmp/claude-*/scratchpad/*`), faceswap-platform-100 spanning 12, 31 keys
  under some `worktrees` path. The worker gate landed today removes the
  worker-brief half; user-driven sessions in `~/projects/worktrees/product-*`
  still fragment. `revert-detector.sh`'s `repeat` needs exact `project`
  equality, and `cross-project-rules.jsonl`'s multi-project test counts these
  as different projects, so the same mistake across three worktrees reads as
  three first offences. Fix: an additive `repo` field = the main worktree's
  toplevel (`git rev-parse --git-common-dir`, resolved absolute, `/.git`
  stripped; `$PROJECT` itself when not a repo), written by both detectors and
  used by `repeat`, session-scorecard and auto-audit in place of `project`.
  Additive so no reader breaks. Not built in the 2026-09-21 sweep: the `domain`
  field took two rounds of fixes when added without a runnable test, and this
  run could not execute one.

## 2026-09-28 radar sweep follow-ups

Digest: `~/.claude/research/radar-2026-09-28.md`. This sweep could search the web
but could not execute `bash`, `python3` or `git`, so everything below that was
built is written and **unrun**.

- [x] 🟠 **Run and commit the 2026-09-28 sweep's two changes.** — DONE
  2026-10-10 (commit 43e4918 + 6ae2ab3). Both verification runs passed:
  `test-correction-pairing.sh` 85/85 with all three prescribed mutation
  checks going red as specified (rd_is_probe neutralized → §3e red; break-line
  removed → cd-after-revert red; heredoc bypass → §3g first/third/last red),
  file restored byte-identical after each. `test-checks.sh` 65/65 for the
  obs-review-loop contract. `install.sh` ran the same day; deployed copies
  verified byte-identical to source.
  (1) `revert-detector.sh`: `revert_scope:"probe"` for a revert the same
  command puts back (`git apply`/`git stash pop` after it, or the `MUTATION`
  label), plus `cd` resolution (variables the command assigns, `~`, relative
  joins, only a `cd` BEFORE the revert). Verify: `bash -n
  configs/hooks/revert-detector.sh`, then `bash tests/test-correction-pairing.sh`
  (§3e, §3f are new), then delete the `rd_is_probe` call and confirm §3e goes
  red, then delete the `rd_is_revert_segment … && break` line and confirm the
  "cd AFTER the revert" case goes red. Commit with `CLAUDE.md` and
  `configs/skills/radar/SKILL.md`. (2) `/obs-review-loop` untrusted-input
  contract: `bash tests/test-checks.sh`. Then `./install.sh`.
- [ ] 🟠 **Run `/doctor prompt-audit` (Claude Code ≥ 2.1.283, 2026-09-25)
  interactively over `~/.claude/CLAUDE.md`, `configs/CLAUDE.md` and the skills.**
  It flags stale paths, dead commands, contradictions and prompting patterns
  written for older models, which is the surface none of this repo's drift
  gates reach: `check-references.py`/`check-runnable-paths.py`/
  `check-sibling-facts.py` read this repository, and `/audit` reads only
  `corrections/rules.md`, while the private global CLAUDE.md carries ~80
  auto-promoted prose rules and Opus 5.5 became the default on 2026-09-22
  (2.1.280). Not run by the sweep: it proposes edits to the owner's global
  instructions, which is not an unattended change, and the local version was
  not checkable (`claude --version` was gated; a 2026-09-22 session banner in
  history.jsonl showed 2.1.278).
- [ ] 🟡 **`pre-tool-guardian.sh` does not block fetch-and-execute** (`curl …
  | sh`, `wget -O- … | bash`, `bash <(curl …)`), the execution step of the
  June 2026 agentjacking attack (a crafted Sentry event made Claude Code,
  Cursor and Codex run attacker code, 85% success across the agents tested). The
  guardian's only related rule is the `ssh`/`bash -c` check at line 320. Not
  built unattended: this is the always-on guard, legitimate installers use the
  same shape (`curl -fsSL https://claude.ai/install.sh | bash`), so it needs an
  allowlist decision and a calibration run — and the 2026-09-07 ledger already
  records this guard failing in both directions from textual matching.
- [ ] 🟡 **Most "explicit corrections" are not corrections.** Of the 45
  `type:"explicit"` records 2026-09-21 → 09-28, by one reader's hand label, 14
  reject or redirect something the agent did; the other 31 are approvals ("可以
  直接往 main 提交"), questions ("代码在哪儿", "…对不对"), new task briefs and
  pasted text. Only one class of false positive has been removed so far: worker
  briefs, 2026-09-21. Every downstream count inherits the noise:
  `session-scorecard.sh`'s per-rule misses, auto-audit's recurrence test, and
  radar's own Lane C clusters. The matcher needs a labelled sample before it
  changes; this week's 45 are a start. Not built: the matcher's vocabulary is
  the whole behaviour, and changing it without a labelled set is a guess.

## 2026-10-05 radar sweep follow-ups

Digest: `~/.claude/research/radar-2026-10-05.md`. Same constraint as the last
three sweeps: `bash`, `git` and script execution were gated, so nothing below
that was built has been run.

- [x] 🔴 **Land the radar backlog before it grows again.** — DONE 2026-10-10.
  Committed per sweep: 09-21 batch (73123ca: correction-detector worker-brief
  gate, secret-scanner de-nag, radar-cron fold-in), 09-28+10-05 batch
  (43e4918: revert-detector probe scope + cd resolution + heredoc stripping,
  pairing tests §3d–3g), obs-review-loop untrusted-input (6ae2ab3),
  internal-deploy bottom-line contract (5b798d3). All suites green
  (85/164/65), three mutation checks red-as-prescribed, `install.sh` deployed
  and eight deployed copies verified byte-identical to source.
- [x] 🟠 **Run the heredoc fix in `revert-detector.sh` (written 2026-10-05).** —
  DONE 2026-10-10 (commit 43e4918). Verified as prescribed: `bash -n` clean,
  `test-correction-pairing.sh` 85/85, and with the `rd_strip_heredocs` call
  replaced by the raw command, §3g's first, third and last assertions went red
  (git text in a heredoc body, a `cd` inside a body, `<<-` pathspec).
  `rd_strip_heredocs` removes heredoc bodies before any parsing; the persisted
  `prompt` keeps the raw command. Of 386 implicit-revert records all-time, 16
  of the 323 unclipped ones (5%) contain no revert outside a heredoc body, and
  up to 43 more clipped ones may be the same (upper bound 59, 15%). Verify:
  `bash -n configs/hooks/revert-detector.sh`, then
  `bash tests/test-correction-pairing.sh` (§3g is new), then replace
  `COMMAND=$(rd_strip_heredocs "$RAW_COMMAND")` with `COMMAND="$RAW_COMMAND"`
  and confirm §3g's first, third and last assertions go red.
- [x] 🔴 **Land the same-command-edit probe signal (built 2026-10-12 by the
  radar cron, UNRUN — bash and git were gated).** — DONE 2026-10-16 on branch
  `fix/revert-probe-same-command-edit`. `bash -n` clean;
  `test-correction-pairing.sh` 119/119 (one control added: a comment naming
  `sed -i` inside the revert segment is not the edit — without it, deleting
  the revert-segment skip in `rd_mutates_reverted_path` stayed green). Six
  mutations each turned the suite red: the call site (5 assertions), the label
  (1), the heredoc strip (3), the heredoc bodies (1), the `git apply` restore
  (5), the revert-segment skip (1). The bash replay of the same 115 records
  gives 64 `probe` / 50 `paths` / 1 no record, matching the Python mirror.
  Was: a mutation probe with no
  label and no `git apply` is still a rejection. Measured 2026-10-05 15:00Z →
  10-12: 115 implicit-revert records, all `paths`, 0 `probe`, although the
  hook carrying `rd_is_probe` was installed 2026-10-10 01:12Z (55 records came
  after). Built: `rd_mutates_reverted_path` in `configs/hooks/revert-detector.sh`
  (in-place `sed`/`perl`/`ruby -i`, `python3 -c`, or an interpreter heredoc
  whose opener or body names the reverted path; `$VAR` pathspecs match
  `$VAR`/`${VAR}`), `_rd_heredoc_split` shared by `rd_strip_heredocs` and the
  new `rd_heredoc_bodies`, and `tests/test-correction-pairing.sh` §3h (8
  assertions, 4 controls) plus a label-only case in §3e — the old label
  fixture also edits its file, so without it deleting the label signal stays
  green. A Python mirror of the rule marks 64 of the 115 (56%) and passes every
  fixture. Verify, in order: `bash -n configs/hooks/revert-detector.sh`;
  `bash tests/test-correction-pairing.sh` (§3g must stay green — the heredoc
  walk was refactored); delete `|| rd_mutates_reverted_path "$COMMAND"
  "$RAW_COMMAND" "$_paths"` from the call site and confirm §3h's first four
  assertions go red; restore; `./install.sh`. Land it on its own branch — the
  checkout was on `fix/warm-pace` when the edit was made.
- [ ] 🟡 **The 51 revert records the edit signal does not cover.** 22 restore a
  file edited in an EARLIER tool call, then re-run the tests (a probe split
  across calls — needs the shadow's write time vs the last user turn, not the
  command text); 14 bare "restore and confirm clean" commands; 5 `git restore
  --staged` without `--worktree`/`-W`, which change no file and should not
  match `REVERT_PATTERNS` at all (small: exclude in `rd_is_revert_segment` and
  the top-level match, with a test).
- [ ] 🟠 **Retire `rule-injector.sh` or stop it duplicating Claude Code.**
  Claude Code loads `~/.claude/rules/*.md` and `.claude/rules/*.md` natively,
  and a `paths:` rule loads when Read/Write/Edit touches a matching file
  (code.claude.com/docs/en/memory, "Path-specific rules"). That is the same
  directory, the same key and the same trigger as the hook. Measured over 2,363
  local transcripts: the hook fired in 10 sessions; in 5 of them the native
  loader delivered the same rule as a `nested_memory` attachment, 10 rule-pairs
  in all, and in 5 of those 10 the native copy arrived first. The hook's only
  extra reach is basename matching for slash-less patterns (`CLAUDE.md`,
  `README.md`), which fired the Clade-specific `measured-claims.md` on files in
  dictation, faceswap and addy repos. Recommended: drop the hook from
  `settings-hooks.json`, rewrite slash-less patterns as `**/NAME`, move the
  CLAUDE.md "Path-scoped rules" section and the four `tests/test-hooks.sh`
  cases plus `tests/test-rule-injector.sh` to the native mechanism (and
  `check-ci-checklist.py` with them). Not built: it removes a wired hook and a CI
  suite, and nothing could be run.
  **Strengthened 2026-10-12:** a later Claude Code release "Fixed path-scoped
  rules and nested CLAUDE.md files not loading when Claude views a file with a
  single-file cat, head, tail, sed -n or grep command in the Bash tool"
  (changelog, 2.1.29x). The native loader now also fires on Bash reads, which
  the hook (PostToolUse Edit|Write) never saw, so the native mechanism's reach
  is a strict superset except for the slash-less basename case. Lands with the
  CLI upgrade below.
  **Changed 2026-10-18:** the hook now also runs on Bash (any command naming an
  existing file, writes included — the native fix covers single-file reads),
  walks nested `<dir>/.claude/rules`, and dedups per subagent. "Strict superset"
  no longer holds; re-measure the overlap before retiring it. Until then a
  single-file `cat`/`head` of a matching file can deliver a rule twice (native +
  hook) on a CLI that has the native fix.
- [ ] 🟡 **`/equip` scans each skill alone; ColluSkill splits a payload across
  skills.** arXiv:2608.09732 (August 2026) reports 96.0% attack success against
  six per-skill scanners. Sub-payloads sit in separately packaged skills joined
  by artifact flow, for example one skill writes a file that another runs.
  `equip_audit.py` is per-skill by construction ("For each skill in the target,
  runs red-flag checks"). Their chain-aware scanner cut success to 22.5% at 99.5%
  benign allowance. Cheapest first slice: list the paths each skill writes and
  the paths each skill executes or sources across the target AND the installed
  set, and flag the overlaps. Needs a false-positive calibration run on the
  vendored seo/blog/ads families before it can gate anything.
- [ ] 🟡 **Hooks run `git` in whatever directory a session opens.** GitSpawn
  (Manifold Security, disclosed 2026-09-02): a `.git/config` with
  `core.fsmonitor` runs its helper on `git status`, outside any agent sandbox.
  Vendors patched their own background git calls. 13 Clade hooks call git,
  including the three SessionStart ones (`session-baseline.sh`,
  `session-context.sh`, `commit-archeology.sh`), and none sets
  `-c core.fsmonitor=false`. The exposure is a repo that arrives as a zip or on
  a shared drive (clone does not carry `.git/config`), and an agent in bypass
  mode would run `git status` itself anyway, so the hooks only make it fire
  earlier. Fix shape: one `clade_git` wrapper in `hooks/lib` passing
  `-c core.fsmonitor=false`, used by every hook.
- [ ] 🟡 **Claude Code is at 2.1.283; 2.1.288 fixed PreToolUse hooks being
  SKIPPED** "when matching failed or tool input couldn't serialize to JSON".
  The call is now blocked instead. `pre-tool-guardian.sh` is a PreToolUse hook,
  so on this host it fails open in that case until the CLI updates. 2.1.287 also
  added Mods (unsandboxed TypeScript plugins that can rewrite tool calls and
  approve permissions), so the one plugin enabled here,
  `scamai-mnemo@scamai-internal`, needs re-reviewing whenever an update could
  add a mod (`frontend-design@claude-plugins-official` is installed but not
  enabled).
  **Extended 2026-10-10:** the 2026-10-08 changelog adds `onFailure: "block"`
  for command/HTTP hooks that can't start, time out, or exit unexpectedly —
  explicit fail-closed instead of relying on the versioned default. After the
  upgrade, set it on the guardian-class hooks (`pre-tool-guardian.sh`,
  `secret-scanner.sh`) in `templates/settings.json` and `settings-hooks.json`,
  and pin the behavior in `tests/test-hooks.sh`. Verify unknown-field tolerance
  on the older CLI first (host may lag the field).
  **Extended 2026-10-12:** the host is still 2.1.283 (`~/.local/share/claude/
  versions/`), now 13 releases behind 2.1.296 (2026-10-09). Two later fixes
  touch this stack directly: a skill's `allowed-tools` and `effort` were
  dropped "when the Skill tool finished before the response stream ended,
  which denied the skill's Bash commands in `-p` runs" — the cron radar runs
  `-p`; and `prompt`/`agent` hooks "written as instructions (such as 'Block
  commands that...') allowing what they should block" (2.1.294). Ours are
  phrased as conditions (`stop-completeness-check` judges MET / NOT MET), so
  that one is `have it`; re-read both prompt hooks after the upgrade anyway.

## 2026-09-23 artifact standard follow-ups (PR feat/artifact-skill)

Study: [docs/research/2026-09-23-artifact-standard.md](docs/research/2026-09-23-artifact-standard.md).
Shipped: `/artifact` skill + references, `configs/scripts/artifact-lint.py`
(24 checks, `--survey`, `--self-test` with 19 pinned mutations),
`configs/rules/artifact.md`, `/landscape` pointer, the internal exemplar page.

- [x] Publisher head standard upstream: the memory system's artifact publisher
      emitted pages that start with `<title>` — 341 of the hub's 384 head-standard
      failures at the evening snapshot (331 of 386 at the morning one). Fixed
      and merged on that repository on 2026-09-24 (eight tests, byte-preserving
      and idempotent).
- [ ] Confirm the publisher fix is LIVE, not only merged: a smoke page
      submitted without a doctype was still served without one right after the
      merge, so the live checkout had not pulled. Re-run
      `artifact-lint.py --survey` once it has and confirm the failure share
      drops below 5%.
- [ ] Run `artifact-lint.py` in the publish path as a non-blocking WARN so a
      page learns its findings at publish time, not in an audit.
- [x] The owner's four hub pages with no `<h1>` (a styled `div` as the title)
      were repaired on 2026-09-23: heading layer, head standard, declared
      artifact-type; republished, backups kept outside the hub.
- [ ] Work-log template: 93 of 106 hub work-logs lack the Goal · Now · Human
      TODO · Blockers header; ship the header in the protocol's page template.
- [ ] Measure reading, not only structure: page-level reads from the hub's
      access logs, so "legible at a glance" becomes a behaviour, not a claim.
- [ ] Ship `/artifact` natively in the Codex plugin: today it sits in the
      `specialized-opt-in-workflows` exclusion because its prompt leans on the
      Claude-bundled `dataviz` / `artifact-diagramming` skills and on
      `~/.claude/scripts/artifact-lint.py`; a native version bundles the lint
      the way `/green` bundles `ci-local.py` and inlines the figure rules.
- [ ] Contrast in the lint: `design-lint html` already computes the pairs;
      wire it into `artifact-lint` as an optional check instead of a second run.

## 2026-10-03 plugin validator pin follow-up

- [ ] 🟡 **Resolve the plugin-root CLAUDE.md warning, then unpin the validator.**
      `.github/workflows/validate-plugin.yml` installs Claude Code CLI 2.1.287
      because 2.1.288+ warns "CLAUDE.md at the plugin root is not loaded as
      project context" and `--strict` fails on it. The marketplace entry's
      `source` is `./`, so the repository's own development CLAUDE.md sits at the
      plugin root. Options: move the development context to `.claude/CLAUDE.md`
      (every script and doc that names `CLAUDE.md` moves with it, including
      `check-ci-checklist.py`), or give the plugin its own source directory.
      Done when `claude plugin validate . --strict` exits 0 on the newest CLI and
      the pin is bumped.

## 2026-10-03 local-gate findings (from the conversation-mode delivery)

- [ ] 🟡 **`ci-local.py` runs a workflow's global installs on the developer's
      machine.** Forcing the Linux jobs on macOS ran `validate-plugin.yml`'s
      `npm install -g @anthropic-ai/claude-code`, which created a second,
      global `claude` under `/opt/homebrew` that nobody asked for (removed by
      hand). A step that installs into global state should be skipped with a
      reason, or redirected into a throwaway prefix, the way `actions/setup-python`
      is already replaced by a cached venv.
- [ ] 🟢 **`tests/test-correction-pairing.sh:285` fails on macOS only.** It
      compares `ls … | wc -l` to `"1"`; BSD `wc` pads with spaces, so the suite
      reports 1 failure on every Mac and none on Linux. Trim the count
      (`| tr -d ' '`) like the rest of the file does.

## 2026-10-10 radar sweep follow-ups

Digest: `~/.claude/research/radar-2026-10-10.md`. Lane A live (6 probe
families), Lane B re-read done (Anthropic harness piece unchanged), Lane C
quiet. Built this run: `/incident` agent-caused-incident fields
(`configs/skills/incident/prompt.md`, synced to both deploy copies).
Queued below: what was not built and why.

- [ ] 🟡 **Co-installed skill conflict ("One Skill Too Many",
  arXiv:2610.11647, 2026-10-08).** Empirical: ~1 in 4 installed skills has a
  same-job rival; substitution between rivals is decided at the FIRST skill
  read; install location (not listing order) decides which runs; a pre-tool
  hook at first read restores fidelity. We carry ~150 skills and our only
  instrument is lexical: `test_routing_eval.py` DISAMBIGUATION_RANK1. Cheapest
  slice: build a rivalry index over installed skills' descriptions (pairs
  above a similarity threshold), then a PreToolUse hook on the Skill tool that
  warns when the invoked skill has a known rival. Needs a calibration pass on
  the installed set before it can gate; read the paper first to check the
  hook's exact intervention shape.
- [ ] 🟡 **Permission-minimality testing (Aletheia, 2026-09-30).** Method:
  convert rule-requested authorities into typed permissions, rerun the task
  with one permission removed at a time; tests still passing means the
  permission was never needed (found all 314 AIShellJack inputs). Applies to
  our own surface — `templates/settings.json` permissions and guardian rules
  accrete, nothing ever removes one. Not built: needs a deterministic
  rerun-the-task harness, which is the expensive half.
- [ ] 🟡 **Verify evidence bundles sit outside worker-writable zones.**
  Adversa's October digest reports harnesses (Claude Code, Codex, Antigravity,
  OpenCode, Grok Build) let agents delete their own execution traces, and
  frontier models do it unprompted — "logs the agent can write are not
  evidence". Our evidence bundle is digest-chained by design (ledger
  2026-08-15), but nobody has checked whether the chain anchor is writable by
  the worker it records. Check: can a loop worker delete or rewrite its own
  `logs/loop/` evidence without breaking the chain verification somewhere a
  worker cannot touch?

## 2026-10-12 radar sweep follow-ups

Digest: `~/.claude/research/radar-2026-10-12.md`. Weekly cron run; `bash`,
`git` and file writes outside `$HOME`/repo were gated, `python3 -c` and `jq`
ran. The 2026-10-05 🔴 ("radar's fixes never land") is CLOSED: the reflog shows
the backlog committed and rebased onto `origin/main` on 2026-10-10. Built this
run without being able to run it: the same-command-edit probe signal, verified
and landed 2026-10-16 in #124 (item under 2026-10-05 above). This run's
uncommitted edits sat in the checkout of an unrelated branch for four days. Queued here:

- [ ] 🟠 **`rule-effectiveness.sh` cannot fire — the domain vocabularies are
  disjoint.** `correction-detector.sh:304-320` records a miss only for a
  `rules.md` rule whose domain EQUALS the correction's `$DOMAIN`. `$DOMAIN`
  comes from `domain-detect.sh`'s 13 fixed values (frontend, backend, ml, cli,
  …, unknown); rules are written with free-form topical domains. Measured
  2026-10-12 on the author's machine: 681 rules across 58 `rules.md` files, 224
  distinct domains, 0 in common. `~/.claude/corrections/rule-effectiveness.json`
  is `{}`, mtime 2026-04-15. The hit side has the mirror-image defect:
  `session-scorecard.sh:118-126` records a HIT for every rule whose domain had
  no correction this session — with disjoint vocabularies, every rule, every
  run, so were it running, every rule would read as effective. It runs only
  from `/sync`; `scorecards.jsonl` was last written 2026-03-19. `/audit` (prompt.md:34,
  65, 69), `/generate-hook` (prompt.md:16) and `/radar` all read that file as
  evidence of which rules keep failing — they have been reading an empty
  instrument. Not built because the match criterion is a design choice: (a)
  word-overlap above a threshold with the domain gate dropped, (b) stamp each
  rule with the detector's domain when it is written, or (c) match on
  root-cause (`premature-action`, `inaccurate-self-reporting` …), the one
  vocabulary both sides already share. Whichever is chosen, its first test is a
  mutation: with the gate as it is today, the test must be red.
- [ ] 🟡 **Promoted rules have no half-life.** 93 `[auto-promoted …]` lines in
  the global `~/.claude/CLAUDE.md` (462 lines). `/audit` retires a promoted rule
  only when a hook takes it over; `auto-audit.sh` archives `rules.md` lines
  after 60 days but never touches a promoted one. Osmani, "Audit your Agent
  files" (2026-08-27): "Your coding agent's configuration has a half-life";
  Anthropic removed "more than 80% of [the Claude 5] system prompt with no
  measurable loss"; his ablation is to rerun a task with the local layer
  removed. DBNT (pypi `dbnt`) decays rule confidence with a 90-day half-life
  unless revalidated. Shape still open (it needs a cheap, re-runnable ablation
  harness), so this is a BRAINSTORM-grade item. Note the counter-evidence
  Clade already cites: arXiv:2605.10039 found no detectable effect from file
  size or position.
  **2026-10-18:** the count is no longer 93. The global file's promoted rules
  were consolidated by hand into 9,997 chars of one-line principles (73,577 →
  38,458 chars for the whole file; full text in
  `~/.claude/corrections/promoted-archive.md`). Since #134, `auto-audit.sh`
  refuses any promotion past a 40,000-byte budget. That caps growth, but it is
  still not a half-life: nothing re-validates a rule that is already in.

## 2026-10-18 instruction-budget follow-ups

Found while consolidating a project CLAUDE.md (127k → 12k chars) and the global
one (73.6k → 38.5k) after Claude Code warned "237.0k chars, over the 150.0k-char
total limit". Fixed so far: the promotion gate (#134). Open:

- [x] 🟡 **Path-scoped rules do not fire on shell file access.** — DONE
  2026-10-18 on branch `feat/rule-injector-shell-access`: wired on the existing
  PostToolUse `Bash` block; command tokens that exist as files after the run
  (glob tokens skipped, ≤ 40 files, relative to `.cwd`); nested
  `<dir>/.claude/rules` walked up to the project root; sentinel keyed on
  `agent_id`. Review round (same branch): output kept under the 10,000-character
  `additionalContext` cap with held-back rules left undelivered, a leading `cd`
  honoured, third-party trees and `claudeMdExcludes` skipped, unreadable rule
  files skipped, identical text deduped, NUL-safe input. Pinned by
  `tests/test-rule-injector.sh`, whose last suite removes each guard from a copy
  of the hook and requires the suite to go red (with a no-op control that must
  stay green), so CI re-runs the mutations; 30 rules × 15 globs × 40 files in
  about 0.16 s. Live check 2026-10-18: a headless session in a project with a
  nested `paths:` rule ran only `head -3 <matching file>` through Bash, and the
  rule arrived in context. `agent_id` is still taken from the documented 2.1.283
  hook-input schema, not from a logged subagent payload. Original item: Claude Code
  loads a `paths:` rule after a Read, and `rule-injector.sh` loads one after an
  Edit or Write. A `cat`, `sed -i` or heredoc write never triggers either.
  Measured 2026-10-18 over the author's 40 most recent main-session transcripts
  (regex count, so approximate): 484 Read calls against 6,890 Bash calls that
  read through `cat`/`head`/`tail`/`sed -n`, and 373 Edit/Write calls against
  2,738 Bash calls with a write shape (`sed -i`, a redirect to a file, a heredoc,
  `tee`). Most file access never fires a scoped rule. Fix: add
  `rule-injector.sh` to the EXISTING PostToolUse `Bash` block in
  `settings-hooks.json`. When `file_path` is empty, match path-like tokens from
  `.tool_input.command` (each glob compiled to an ERE once per rule file, to
  stay inside 5 s). Subagents carry the parent's `session_id`, so the
  once-per-session sentinel suppresses a rule in every subagent after the first
  injection. Log one subagent's hook input to see whether it carries
  `agent_id`, and key the sentinel on it. Pin it with a `tests/test-rule-injector.sh`
  case (`sed -i … tests/test_x.py` injects a `**/test_*` rule) plus a mutation,
  and update the hook header and CLAUDE.md "Path-scoped rules" in the same
  commit, since both say Edit|Write only.
- [x] 🟡 **DONE 2026-10-18 — the delivery controller treats hosted checks as the
  receipt (`--checks receipt` default; failed checks still refuse; BLOCKED →
  auto-merge).** Was: the delivery skills wait on hosted checks; the owner's standing rule
  is not to. `create-pr/prompt.md` ("Wait for this PR's remote checks"),
  `delivery/prompt.md` (same) and `merge-pr/prompt.md` ("requires completed
  successful checks"), plus the `ready` controller, which refuses while any
  check is pending. The owner's rule, promoted 2026-09-24: once the local gate
  is green, merge and let hosted CI be the receipt (不要等，直接合并). The
  global CLAUDE.md now says its rule overrides a skill's wait. The skills
  should say so themselves: accept a recorded `ci-local.py` pass in place of
  completed remote checks (or `gh pr merge --auto` where protection requires
  them). Regenerate the plugin and mcp-package copies.
- [ ] 🟡 **On or after 2026-10-25: did any rule moved out of always-loaded
  context stop working?** On 2026-10-18 one project moved 54 promoted rules from
  its CLAUDE.md into path-scoped `.claude/rules/` files, and the global file's
  96 rules were condensed to one line per principle. A rule that keeps getting
  violated after the move is the measurable failure. For each correction
  recorded since 2026-10-18 (`grep -h '^- \[2026-10-\(1[89]\|2[0-9]\)\]'
  <project>/.claude/corrections/rules.md ~/.claude/corrections/rules.md`), grep
  its key phrase in that project's `.claude/rules/*.md` and in
  `~/.claude/corrections/promoted-archive.md`. A hit means the moved or
  condensed rule did not hold. Move it back into CLAUDE.md (the work it governs
  evidently touched no matching file) or sharpen its line. Pair the result with
  which scoped files actually fired: `cat <project>/.claude/sessions/*.rules-injected
  | grep -v '^#' | sort | uniq -c`.
- [x] 🔵 **DONE 2026-10-18 — a named figure type is now drawn, alternatives argued
  beside it.** Was: `/artifact` allows zero figures even when the brief names a figure
  type. `configs/skills/artifact/prompt.md` ("zero figures is valid when prose
  or a lookup table answers it better") contradicts a promoted rule. When the
  brief names a flow chart or a structure diagram, draw it and argue the
  alternative on the page. Add that exception and regenerate the derived
  copies.

## 2026-10-19 radar sweep follow-ups

Digest: `~/.claude/research/radar-2026-10-19.md`. Weekly cron run. As on
10-12, `bash`, `bash -n`, `git` and every test run needed approval nobody was
present to give; `grep`, `jq` and `stat` ran, so every count below was
computed. New instrument this run: Claude Code writes a
`hook_non_blocking_error` attachment into the transcript whenever it rejects a
hook's output. Tallied over every transcript on the author's machine, it
exposed two hooks that have delivered nothing (the command is now in
`configs/skills/radar/SKILL.md`, Lane C).

- [x] 🟠 **Verify and land this run's edits.** — DONE 2026-10-19. The hook fix
  landed in #139: `bash -n` clean; `test-hooks.sh` and `test-skill-routing.sh`
  (48/48) green; deleting `"hookEventName":"PostToolUse",` turned §3 and §3b
  red; 313 rejections re-counted across both profiles (2026-08-26 → 10-19,
  deduped). The rule and radar docs land with this section. Was: uncommitted in the `main`
  checkout: `configs/hooks/skill-suggest.sh` (adds `"hookEventName":"PostToolUse"`;
  Claude Code rejected all 309 of its outputs, 2026-08-26 → 10-18 on 2.1.236 →
  2.1.283), `configs/skills/generate-hook/prompt.md` (the template taught the
  same event-less shape to every generated hook), `tests/test-hooks.sh` (§3
  asserts the event name; new §3b checks every `"hookSpecificOutput"` literal in
  `configs/hooks/*.sh`, 16 today, with a ≥10 count guard against a vacuous
  pass), `configs/rules/measured-claims.md` (installed globally, it told every
  repo to run a Clade-only script; seen live injecting into a docforensics
  README read), `configs/skills/radar/SKILL.md`. Steps: `bash -n
  configs/hooks/skill-suggest.sh`; `bash tests/test-hooks.sh`; `bash
  tests/test-skill-routing.sh`; mutation: delete `"hookEventName":"PostToolUse",`
  from skill-suggest.sh, and §3's new assertion AND §3b must both go red; restore;
  `./install.sh`; land on its own branch via `/create-pr`. Live proof after
  install: edit any `*_test.py`, and the transcript must show the suggestion,
  with no new `hook_non_blocking_error` for `PostToolUse:Edit`.
- [x] 🔴 **`pre-tool-guardian.sh` rewrites have never applied, and would break
  commands if they did.** — DONE 2026-10-20, in the order below.
  - **Tests first.** `classify()` now reads the schema the runtime accepts:
    LEGACY, NO-EVENT, REWRITE-ESCALATES, REWRITE-NO-ALLOW and CRASH are all
    failures. Against the old guardians, 100 of 144 cases were red.
  - **Statement-aware trigger.** An awk walk honours quotes, comments and
    heredoc bodies, and reads only a `git [opts] push` statement, plus wrapped
    `ssh` / `bash -c` / `eval` for blocks. It also blocks force or delete of
    main by refspec destination, and by the cwd's current branch when no
    refspec is given.
  - **Schema.** Rewrites are `hookSpecificOutput.updatedInput` with NO
    `permissionDecision`. Measured live on 2.1.283: "allow" bypasses
    permission prompts; omitted, a rewritten unallowed command was still
    denied. Blocks are `permissionDecision: "deny"`.
  - **A second defect found on the way.** The guardian crashed (`set -e` +
    `rm_scan_flags` returning 1) on 10 of 20,111 replayed real commands.
    That is a non-blocking error, so the command ran with every later check
    skipped. After the fix: 0 crashes, 0 legacy outputs. All 69 changed
    verdicts were reviewed; each was an old false positive.
  - **Same pass:**
    - `linter-config-guard.sh` moved to deny, and its path is now JSON-escaped.
    - The Kimi shim reads the current shape and turns a rewrite into a deny
      that names the safer command. The old shim + new guardian would have let
      `git push --force origin main` through under Kimi.
    - The Codex mirror got the same walk, keeping its own contract (Codex
      0.163 requires "allow" with updatedInput).
  - **Proof.** 12 mutations each go red. Live `claude -p`: on a stale clone
    the rewrite was rejected "(stale info)", keeping the other agent's commit;
    a force push to main was denied with the new reason.
  - **Adversarial review of the first cut.** It found that reading a statement
    only when its first word is `git` let these through, all blocked by the
    old text match:
    - a push behind a prefix (`timeout 120`, `sudo -u bob`), a group (`{ }`),
      a keyword (`then`, `do`) or a function;
    - a script fed to a shell on stdin (`… | bash`, `bash <<EOF`, `ssh host <<EOF`).

    Now:
    - the first `git`, shell, `ssh` or `eval` word in the statement decides;
    - a shell is read by its `-c` argument, or by the whole command when it
      reads stdin;
    - a script file argument is not read, so `bash run.sh "…push…"` is no
      longer a false block;
    - `HEAD` and `@` destinations count as the current branch.

    On the 20,111-command replay this changed no verdict. 177/177 cases
    pass under mawk, BWK awk (the macOS family) and busybox awk; 8 further
    mutations go red.

  Was: rewrites have never applied, and would break
  commands if they did.** Both rewrite branches (force push → `--force-with-lease`,
  `pre-tool-guardian.sh:278-287`; unset-variable recursive delete →
  `${VAR:?…}`, `:251-259`) answer `{"decision":"allow","updatedInput":…}`.
  Claude Code rejects it: "top-level decision is the legacy approve|block field;
  for "allow" use hookSpecificOutput.permissionDecision". 41 rejections in
  transcripts, 2026-09-22 → 10-19, on 2.1.258 and 2.1.283. Each one ran the
  ORIGINAL command. So the 2026-09-06 unset-variable delete guard has protected
  nothing. The rewrites themselves are also wrong. Of the 41 (the categories
  overlap):
  - 14 would have turned `--force-with-lease` into `--force-with-lease-with-lease`
    (`sed 's/--force\b/…'` matches inside it);
  - 7 would have put `--force-with-lease` on `git worktree remove` or `rm`,
    because the trigger is "`git push` anywhere AND `--force`/`-f` anywhere";
  - 2 would have corrupted a ref (`feat/verdict-c-f-split` →
    `feat/verdict-c--force-with-lease-split`, via the greedy `-f\b` sed).

  **Fixing the schema alone would turn these into live breakage.** Order:
  (1) tests first. `classify()` in `tests/test-pre-tool-guardian.sh:50-55` is a
  substring check: any `updatedInput` reads REWRITE, so it cannot tell an
  accepted output from a rejected one, and parity compares verdicts, not
  shapes. Assert the Claude Code schema (`.hookSpecificOutput.hookEventName ==
  "PreToolUse"`, `.permissionDecision`), the rewritten command's exact text,
  and `--force-with-lease` / `git worktree remove --force` / `-f`-in-a-ref-name
  all left untouched. Each must be red against today's hook. (2) Make the
  trigger segment-aware: only a `--force`/`-f` TOKEN of a `git push` segment.
  The Codex mirror `plugins/clade/hooks/pre_tool_guardian.py:192-201` already
  has the token-exact regex and the right output shape, but it still rewrites
  non-push segments. (3) Only then emit `hookSpecificOutput`. Also check before
  the CLI upgrade past 2.1.283: the guardian's BLOCKS still ride the legacy
  top-level `"decision":"block"`, which current docs no longer list for
  PreToolUse. If a later version drops it, every guardian block (force push to
  main, `rm -rf ~`, `DROP TABLE`) becomes a non-blocking error. Re-run the
  `hook_non_blocking_error` tally after upgrading.
- [ ] 🟡 **The two guardians still disagree on 160 of 20,111 real commands,
  all outside force push.** This is down from 192; the 2026-10-20 force-push
  walk fixed 33 and introduced none of its own. What remains is older:
  - the Codex mirror has no self-killing `pkill -f` rule (48);
  - the two split `rm` statements differently around newlines and heredoc
    bodies (59 where only the mirror blocks, 35 where only it rewrites, plus
    smaller sets).

  Fix: move the rm and pkill statement detection onto the same quote- and
  heredoc-aware walk, in both guardians. Measure by replaying the same 20,111
  commands; the extraction recipe is in this item's commit.
- [x] 🟡 **The cron radar cannot verify anything it builds** — DONE
  2026-10-20, options (b) and (c) together, in the wrapper rather than the
  agent's permissions:
  - `radar-cron.sh` makes a worktree of the kit on a fresh `radar/<date>`
    branch from origin/main, outside `~/.claude`, and runs the agent with it as
    cwd. Measured on 2.1.283 with `acceptEdits`: outside its cwd the agent is
    refused even a Read, so no other checkout is reachable; `--add-dir` grants
    the read-only inputs.
  - Afterwards the wrapper runs `bash -n` on changed shell files and the
    suites that name a changed file, inside bwrap with no network and the
    filesystem read-only except the worktree. A suite's write outside the
    worktree never reaches the host; this is tested.
  - It commits to the local branch with the results in the message, removes
    the worktree, and never pushes, because the run read the open web and
    private history.
  - `session-context.sh` lists `radar/*` branches when a session opens the kit.
  - Pinned by `tests/test-radar-cron.sh` (24 cases); 7 mutations each go red.

  The agent's own permissions are unchanged (no Bash), so option (a) was not
  needed. Was: the cron radar cannot verify anything it builds — and it leaves
  its edits uncommitted in whatever checkout is open: on `fix/warm-pace` for
  four days after 10-12, and on `main` on 10-19, where an unrelated session's
  Stop hook found them. Option (c) below fixes that half on its own.
  `radar-cron.sh:118-133` allows `WebSearch` plus `WebFetch` on 13 hosts, and
  acceptEdits adds file edits, but not `bash`/`git`/tests. So the skill's
  "build and verify now" can only ever yield "built, unrun" for code, as on
  10-12 and again today. Not widened here, because it is a security fork:
  acceptEdits plus running a script the agent can edit is arbitrary code
  execution in a run that also reads untrusted web content. Options: (a) allow
  only `Bash(bash -n:*)` (parse, never execute); (b) run tests under Claude
  Code's Bash sandbox with network off, which removes the exfiltration leg of
  the lethal trifecta; (c) keep it as is, but have `radar-cron.sh` open a draft
  branch with the edits so they never sit uncommitted in someone's checkout.
- [ ] 🟡 **A batch worker that times out loses a patch that may already pass.**
  `run-tasks-parallel.sh:376-409`: on exit 124 the next attempt runs `git
  checkout . && git clean -fd`, and after the last attempt the task is
  PERMANENTLY FAILED. The worktree is never checked. Field data ("Harness or
  Model?", arXiv:2609.11987): 22 of 81 runs cancelled at the wall-clock ceiling
  had already produced a passing patch. The batch runner has no per-task
  verifier to check with (no `verify` field), so adding one is the design step;
  the shadow checkpoint repo already preserves the state to check.
- [ ] 🔵 **Redirect-written mutation probes still file as rejections.**
  `rd_mutates_reverted_path` (`revert-detector.sh:270-297`) knows in-place
  sed/perl/ruby, `python3 -c` and interpreter heredocs. It does not know `git
  show REV:f > f; <tests>; git checkout -- f` or `echo … >> f`. A jq replay over
  the whole `history.jsonl` finds 4 such records (2 in the 10-12 → 10-19 window,
  one carrying a false `reverted_files`). The fix is to treat a `>`/`>>`/`tee`
  whose target basename equals a reverted path as an edit. It is small, but not
  built: the frequency is low and this run could not run the suite.

## 2026-10-22 Workflow efficiency audit follow-ups

Audit of every Workflow run still on disk on aries: **316 runs, 3,646 agents,
218,031 API calls, 2026-09-22 → 2026-10-22, both profiles** (older transcripts
are purged by Claude Code's 30-day `cleanupPeriodDays` default). 40-agent audit
workflow `wf_5a4854b2-6a4`: 12 worst runs diagnosed one by one, 6 dimensions,
one adversarial verifier per diagnosis and per dimension, then a completeness
critic and 3 gap-fillers. Raw data, per-agent work and the preprocessing script:
`~/.claude/research/workflow-audit-2026-10-22/` (private, outside the repo).
Money figures are **list-price equivalents at Opus 5.5 rates, per API call:
$20,252 total**. The account is on a subscription, so the real currency is quota
(see Q-items), not dollars. Levers overlap; do not add their percentages.

Verdict: the biggest wall-clock sink is NOT script shape. Of 367 h of parallel
makespan, 35.6% is deliberate one-agent stages and only 17.3% is stragglers;
38% of serial-stage time is agents sleeping on external jobs. The cheap wins are
(1) fix the instrument, which misdiagnoses half the runs it flags and double
counts tokens; (2) stop foreground waits from expiring the 5-minute subagent
cache; (3) stop failing silently (usage-limit nulls, truncated handoffs,
placeholder args); (4) a lean agent type for read-only roles. Effort and model
tiering are real but unmeasured. Each needs a paired A/B before rollout.

### Instrument — `configs/scripts/workflow-scorecard.py`

- [ ] 🔴 **The scorecard counts every API call about 1.9 times.** `read_agent()`
  (`:162-184`) sums usage and `turns` per transcript RECORD, but one API message
  is split across several records that each repeat its usage (one transcript:
  163 assistant records, 87 message ids). Across the corpus: 413,161 records vs
  218,031 calls; cache_read 46.4B, not 88.2B. `in_tokens` (`_INPUT_FIELDS`,
  `:71-77`) also adds cache reads at full weight and the comment calls it cost.
  It overstates input 7.6x at 0.1x weights and 11.9x at Opus 5.5's real 0.05x.
  Fix: key usage by `message.id` (input fields once, output = max over the id),
  count turns as distinct ids. Emit input / cache_read / cache_create / output
  separately, plus a cost field priced per model from the binary's tier table.
  Add a two-records-one-message fixture to `--self-test` and a mutation to
  `test_self_tests_can_fire.py`. Fix the ids BEFORE writing any ledger row (below).
- [ ] 🔴 **The tail verdict treats deliberate one-agent stages as stragglers.**
  `sweep()` (`:187-234`) keeps an integer, not the running set. So
  `tail_alone` cannot tell a lone build, fix or synth stage (35.6% of 367 h
  over 259 parallel runs) from an agent that outlived its siblings (17.3%).
  `_verdict()` (`:936-953`) prints "straggler tail" on 182 of 258 parallel runs.
  85 of those (47%) have outlived < 15%, and 83 of the 85 are serial-dominated.
  For them, pipeline() cannot help, so the advice is wrong. 12 of the top 15 runs
  by the tool's own ranking are misdiagnosed. Fix: credit lone time to an agent
  id. Emit `serial_frac`, `outlived_frac` and `idle_frac`. Verdict order:
  sequential → outlived ≥ 0.15 "straggler, pipeline() or finer units" → serial
  ≥ 0.25 "serial stage <label> alone N min, shorten or overlap it" → low util.
  List every verdict that holds, not the first. Print a "longest serial stage"
  line next to "largest tail".
- [ ] 🟡 **The main mode has no self-test.** `--self-test` (`:996-998`) runs only
  the poll and codex-children self-tests. Changing `if running == 1:` to `== 99`
  and the straggler verdict to `if False:` still prints PASSED (reproduced). Add
  `self_test_sweep()`: three synthetic runs written as `agent-*.jsonl` files and
  read through `scan_workflow()`. They are a barrier with one 3x agent, a
  fan-out → lone build → fan-out chain, and a queued pipeline with a 6x spread.
  Add mutations for the running-set check, the serial/outlived test, the verdict
  order and the 0.15 threshold.
- [ ] 🟡 **The guidance's figures can no longer be re-derived and have drifted.**
  "89 runs / 1,777 agents / 45%" and "110-agent pipeline, 0% tail" came from
  transcripts purged after 30 days, and no ledger kept them. Today's population
  gives 52.9% single-agent (35.6% serial + 17.3% outlived), and 70.5% of runs are
  flagged (was 61.8%). Add `--ledger PATH` (default
  `~/.claude/workflow-scorecard/runs.jsonl`): one per-call-deduplicated row per
  run_id, append-only. Then restate or delete the figures at every site, in one
  commit: `CLAUDE.md:150-154`, `:800-806`, `:812`, `:825`;
  `configs/CLAUDE.md:213-219` (then `./install.sh` for `~/.claude/CLAUDE.md`);
  `docs/research/2026-09-02-agent-orchestration-efficiency.md:7-8`, `:121`;
  `docs/research/README.md:74`; and `docs/configuration.md:159-161` if it still
  quotes them. Add the figures to `check-asserted-numbers.py`'s patterns.
- [ ] 🔵 **The scorecard ignores labels, phases, outcomes, model and effort it
  already has on disk.** `agent-*.meta.json` carries label and phase for 94.8% of
  agents. `journal.jsonl` carries started/result/failed: 202 agents without a
  result in 59 runs, and 39 `failed`. Transcripts carry `message.model` and
  effort. None are read; `_identity()` guesses identity from the brief, which is
  boilerplate in 314 of 315 runs. Add per-phase rows (n, wall time, within-phase
  spread), an outcome column, per-agent model and effort, a first-turn-context
  median, a long-gap cache-miss share, and returned-result size. Rename `util`
  to `util_vs_peak`, because the denominator is the peak reached, not the cap.

### Speed and cost levers (guidance plus hooks)

- [ ] 🟡 **Foreground waits longer than 5 minutes expire the subagent prompt
  cache.** Subagents get a 5-minute TTL only. 1,459 cache misses follow a gap over
  300 s (median 585 s). They carry 548M of 1,342M cache writes (41%) and cost
  $2,631 of $20,252 (13.0%). 82.5% of that cost follows a Bash `until …; do
  sleep N; done` poll. Waits are 102.7 h, 38% of serial-stage agent time.
  Fix: every blocking wait ≤ 270 s per Bash call (re-check, then sleep again), or
  detach the job and end the agent once its result path is recorded. Put this in
  the workflow guidance and in a warn-only PreToolUse Bash rule in
  `pre-tool-guardian.sh` that fires only when the hook input has `agent_id`.
  Estimated −$2.4k (−12%), or ~0.27 weekly caps a week. Do NOT set a 1-hour
  subagent TTL: the 2x write premium cancels it on quota.
- [ ] 🟡 **Every workflow subagent re-reads ~54k tokens of instructions and skill
  listing on every call.** Turn-1 context has a median of 72.6k tokens, of which
  only the 18.9k tools+system prefix is shared between siblings. Agent
  frontmatter `omitClaudeMd` exists in 2.1.283 (verified in the binary), and
  `agentType` is the only per-agent lever `agent()` takes. Ship
  `configs/agents/wf-reader.md`: a tools allowlist without Skill, Artifact,
  SendFeedback, ReportFindings or ListAgents, `omitClaudeMd: true`, and a ~1.5k
  body restating the reader rules. Use it only for host-safe read-only roles
  (1,885 agents with no ssh, systemd or ops use): −6 to −7%. Before adoption,
  run a smoke test that a custom agentType with a schema still gets
  StructuredOutput, plus a small quality A/B. Writers keep CLAUDE.md, because the
  committer and push rules must reach them.
- [ ] 🟡 **Every `agent()` without `effort` runs at xhigh.** The owner's
  `effortLevel` is inherited. 0 agents ran at `low`; mechanical stages ran at
  xhigh 302 of 314 times. The observational output-only floor for a per-stage
  table is $570–835 (2.8–4.1%). The ceiling is unmeasured, and no run ever scored
  the same items at two efforts. Run the paired A/B first: ~20 known-answer
  items with seeded false claims, xhigh vs medium/low, per-call metrics. Then
  publish the stage table (low for collect/inventory/classify, medium for
  single-claim verify, default for implement, judge and synth). Model switching
  is NOT the main lever: Sonnet 5 reads cost the same as Opus 5.5 reads, the
  realistic move is 8.6%, and Haiku's 200k window cannot hold 59% of agents.
- [ ] 🔵 **Serial stages need their own rule; the guidance only covers
  stragglers.** Add next to the pipeline bullet (`configs/CLAUDE.md:213-219` and
  its mirror in `CLAUDE.md`): "A one-agent stage is on the critical path for its
  whole length. Shorten it: a tight brief, a per-stage effort, keep-warm waits,
  and return as soon as the artifact the next stage consumes is frozen." Also
  "units that each build their own worktree from origin/main go in
  `pipeline(UNITS, implVerify, landBehindMutex)`, not a for-await loop". That
  loop shape appears in 3 of 294 scripts; it cost ~4–8 h in `wf_03143d52-955`.
  Recoverable time from reshaping is small (~9–20 h of 272 h serial-agent time).
  In 3 of 5 cases, the "this could overlap" diagnoses were refuted by a hidden
  data dependency.

### Silent failures (outcome)

- [ ] 🟡 **Usage-limit nulls hide inside "completed" runs.** 90 agents (32
  agent-h) died on usage limits (46 weekly, 44 five-hour). 64 of them were in 16
  runs reported `completed`, and at least one run (`wf_c0717cfa-12b`) shipped a
  judgement whose audit and critic the lead filled in alone.
  `resumeFromRunId` was used on 4 of 324 launches. Fix: guidance that a script
  counts nulls per stage and returns `{incomplete, failed:[labels], resume}`
  instead of feeding nulls downstream. Add a pre-launch quota gate: 7-day ≥ 90%,
  or 5-hour plus projected burn ≥ 100%, means defer or switch account. That gate
  would have deferred 77 of the 82 metered losses.
  - [x] Prerequisite: `claude-usage-watch.py:28-29` read only the primary
    profile. Resolve it from `CLAUDE_CONFIG_DIR` and keep the 5-hour window.
    DONE 2026-10-23 — token, macOS Keychain item and cache now resolve from
    `CLAUDE_CONFIG_DIR` (else `~/.claude`, also when it is empty), the cache
    keeps `five_hour`, and 10 new test cases in `test_claude_usage_watch.py`
    pin it (7 red on the old script; the 3 that stay green pin the `~/.claude`
    fallback and the primary's unsuffixed Keychain item).
  - [ ] The gate must not trust the cache's age. With `--statusline-input` and a
    usable `rate_limits` payload (the normal status-line case),
    `claude-usage-watch.py` neither reads nor writes `usage-watch-cache.json`,
    so a profile's cache can be arbitrarily old. Reject a cache whose `_at` is
    older than about 5 minutes, or refresh it by running the script without
    `--statusline-input`.
  - [ ] An account swap inside one profile (a re-login to another account) can
    still show the previous account's reading: up to 5 minutes from the fresh
    cache, up to 7 days from the stale fallback when the API is down. The cache
    records no account. Store an account hash with it and drop a mismatch.
  - [ ] Dormant layer, same blind spot: `orchestrator/server.py` reads
    `~/.claude/usage-watch-cache.json` (:1131), `stats-cache.json` (:1048) and
    `projects/` (:1077) from fixed paths, ignoring `CLAUDE_CONFIG_DIR`. The
    :1131 reader also expects keys this cache never holds (`usage_pct`,
    `elapsed_pct`, `remaining_days`), so its pace is always 0; a path fix alone
    would not make it correct.
- [ ] 🟡 **Prior results are silently truncated inside prompts.** About 81 of 294
  scripts apply `.slice(…)` to a `JSON.stringify`'d result inside an `agent()`
  prompt without a `log()`. That is 26–28% of scripts, mostly docforensics.
  48 of 66 checkable sites actually cut; the median share lost is 41%. Build
  `configs/scripts/check-workflow-script.py`: a stdlib regex for this rule
  (~80% precision at script level), with optional node+acorn AST rules for
  unlogged array caps (6 scripts) and uncapped agent-width fan-outs (2). Print
  "not checked" when no parser is found. Add `--self-test`, mutations and a
  `--survey` mode. Wire it as a report-only PreToolUse hook on `Workflow`. The
  hook must resolve `scriptPath` and saved `name` inputs, not only `script`.
- [ ] 🔵 **Placeholder args reach Workflow.** 10 of 324 launches carried
  placeholder or partial args, repeated in 5 sessions. One of them
  (`wf_f95c1fbf-fbb`) completed with an empty result instead of failing.
  A sentinel-pattern check on args would catch 9 of 10 with 0 false positives
  on this corpus. Add it to the same Workflow hook. Convention: more than a
  handful of items go in a scratch JSON file; args carries the path and an
  expected count that the script asserts.
- [ ] 🔵 **Workflow results overflow the 8,000-char notification.** 92% do
  (259 of 281); the cap is in the 2.1.283 binary. The lead then digs through
  journals: ~266 reads, ~1.8M chars. Rule: the last stage writes full results to
  a file and returns ≤ 6k chars (verdict, counts with denominators, open items,
  path).
- [ ] 🔵 **Fix rounds bounce through the lead.** 20 strict corrective re-runs
  took 33.2 h of 508.6 h makespan (6.5%), and there were 38 lead-only relaunches
  right after a reviewing run. Rule: verify → fix → re-check, at most 2 rounds
  inside the script, returning only units still open.
- [ ] 🔵 **AskUserQuestion freezes the lead while a workflow finishes.** 7
  completions sat unread for 36.5 completion-hours, behind 4 of 26 questions in
  59 sessions. Rule or warn-hook: with a live background task, ask in plain text
  and end the turn.
- [ ] 🔵 **Outcome is unmeasured, and the two correction signals cannot measure
  it.** Hand-labelled owner messages within 6 h of a run give a 10.5% rejection
  rate on 124 observable runs (lower bound). Of 13 rejections, 7 were a misread
  goal or premise, and 6 runs with execution defects had passed verify; the
  defects appeared on the owner's devices. Explicit correction records have 33%
  precision and 41% recall. 172 of 220 implicit-revert records come from
  subagents. Fixes: `revert-detector.sh` tags or skips calls whose hook input
  has `agent_id`; add `correction-detector.sh` patterns (不太对|理解错|打不开…)
  and drop the tag-question shape; add a scorecard `--outcome` mode that emits
  the 6-hour windows for weekly labelling. Guidance: a 3-line launch contract
  (objective, acceptance criteria, premises) before ≥ 5-agent runs started from
  a long brief. UI verify stages need a device matrix (webkit iPhone, the
  owner's screens, elementFromPoint).
