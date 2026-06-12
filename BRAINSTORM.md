# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md / TODO.md or acted on, they're cleared.*

## How this file works

- **Add an idea**: append a `## {date}` section with the idea, why it matters, and any sources.
- **Resolve an idea**: strike it through with `~~text~~` + a one-line "RESOLVED / DEFERRED + date + where-it-landed" reason.
- **Periodic cleanup**: when strikethroughs dominate the file, move them to `docs/archive/BRAINSTORM-resolved.md` so the inbox stays focused on live thinking.

Past resolved/deferred items live in [`docs/archive/BRAINSTORM-resolved.md`](docs/archive/BRAINSTORM-resolved.md).

---

## [Research] 2026-06-12 — Elite workflows ROUND 2 (deeper re-sweep, same 6 sources)

User question: 再学习一轮他们，看看我们的学习成果和他们的是否还有gap. Round 2 dug below round 1's surface: actual dotfiles/.claude/pi-extension internals (Mic92, lovesegfault), project repos as machine-operations manuals (felixrieseberg), fleet-automation mechanics + blog doctrine (domdomegg), merged-PR craft threads (controversial), plus Anthropic engineering blog 2025-26, claude-code official hook/subagent docs, and the claude_agent_sdk + CMA cookbooks. ~70 new mechanisms surveyed; every candidate verified against the codebase before a verdict.

> **RESOLVED 2026-06-12** — 4 confirmed gaps, all landed same turn with covering tests (suite 517→521): non-interactive git env `d01a8d7`; fix-task Phase-3 structural close + oracle one-step-removed + negative-scope completion contract `adf98db`. Wave-1/2 deploy-gap audit: zero gaps (details below).

### Confirmed gaps (landed same turn)

1. **[S/medium] Non-interactive git env** (Mic92 `git-rebase-env.ts`): nothing set `GIT_EDITOR` — a worker hitting rebase/amend parks on an editor forever. Now `GIT_EDITOR/GIT_SEQUENCE_EDITOR/GIT_PAGER=cat` in worker.py spawn env (setdefault) + both shell runners' generated runner scripts. `d01a8d7`
2. **[S/medium] Fix-task structural close** (lovesegfault REVIEW.md): fix template stopped at "patch + lint" — no sibling sweep, no dead-code sweep, no done-gate. Phase 3 added to `_fix_two_phase`: sweep whole file ±50 lines + module, remove obsoleted state, end completion summary with a literal `Done-gate:` command line. `adf98db`
3. **[S/medium] Verifier one step removed** (lovesegfault r25: 8/12 regressions were introduced BY fixes verified only against the original claim): oracle now walks inverse input / next lifecycle transition / sibling consumer with concrete examples on fix-intent tasks (`_FIX_ONE_STEP_CRITERION`). `adf98db`
4. **[S/low] Negative-scope declaration** (controversial): completion contract now demands deliberate exclusions + uncertainties in `summary`, which already flows into structured PR bodies — reviewers learn weak spots from the author. `adf98db`

### Parity confirmed with round-2 evidence (查过了，不是照搬)

- SHA-pinned CI actions with version comments → ci.yml already pins all `uses:` to full SHAs (cookbooks devsec discipline, verified)
- Numeric narration bound to source keys (lovesegfault census ratchet) → `docs/facts.json` + doc-align.py check/apply is the same mechanism
- Tool scoping as capability security (cookbooks `disallowed_tools`) → `config._TOOL_SUBSETS` per task type (review = read-only) already does this for workers
- Fail-open-toward-stopping loop hooks → official ralph-wiggum plugin validates Clade's existing stop-hook circuit-breaker doctrine
- `setting_sources` judge/worker split → SDK notebook 01 documents the exact contract behind this week's 386a862/9fd1720 fixes
- Conflict handling: run-tasks-parallel aborts the merge and reruns the task serially on updated main — deterministic, never LLM-guessed conflict resolution; judged BETTER than mic92's resolve-doctrine at this topology (different_not_deficient)
- File-claim locks / fresh-context respawn / 1-2k distilled subagent summaries (C-compiler + multi-agent blog) → OWN_FILES + loop-runner re-spawn + worker TLDR
- Immutable feature list anti-reward-hacking (Nov-25 blog) → VERIFY.md checkpoints + fix-intent test criterion cover the same failure
- Friction logs / model self-reported feedback (domdomegg) → partial parity via BRAINSTORM [AI] inbox + skipped.md routing

### Rejected (different ≠ deficient / N-A)

- pueue job queue (mic92) — CC harness background tasks + Monitor cover it; smart-caveman register = personal style
- One-ruleset-many-harnesses + private claude.md repo (mic92) — single-tool scope (round-1 precedent); /btw tangent-strip + autoCompact-off = harness layer, unreachable from skill layer
- nostr-walkie phone steering — Telegram notify + web UI + worker mailbox cover the capability
- CMA platform features (outcome-grader event, session pods, transcript fork, FUSE memory, HITL webhooks, coordinator threads, sandbox workers) — hosted-platform topology; Clade is local-first; outcome-grader spirit = oracle
- WIF keyless auth / GCP secret brokerage — no cloud secret fleet; CI already key-gated + SHA-pinned
- nbdime (no notebooks), formal Quint/Kani/MBT layer (cost/scope), BASH_ENV direnv shim (no direnv here; .venv symlink bootstrap covers), tracey (re-confirmed round-1: VERIFY.md equivalent), two-stage permission classifier (CC ships auto mode at harness level)

### Noted, not landed (candidates for a future wave)

- [ ] Mutation testing as run-over-run missed-count diff ratchet, narrow high-signal targets first (lovesegfault mutants.toml) [M/medium — patrol-lane experiment]
- [ ] Judge hardening: pure judges could add `--disallowed-tools` belt-and-braces (cookbooks: allowed gates prompting, disallowed gates availability) [S/low]
- [ ] Standing friction-log instruction for workers (append harness pain to BRAINSTORM [AI]) [S/low]
- [ ] `input_examples` on mcp_server tool definitions (advanced-tool-use blog: 72%→90% complex-param accuracy) [S/low]
- [ ] Strike-ladder N=4..7 structural-close templates as /audit reference doc (delete-reimplementation, make-function-total, single-emit-chokepoint) [S/low prose]
- [ ] Flake-verdict policy doc for test-loop-real (felixrieseberg: "one SUCCESS = good, three identical failures = content must change") [S/low]

### Wave-1/2 deploy-gap audit (this repo's recurring failure class — checked deliberately)

All 15 spot-checked round-1 adoptions are wired end-to-end: oracle liveness returns `infra_error` flags; tests run BEFORE oracle gate and auto_push (worker.py:800); quiet-run.sh referenced by /verify, /review, loop-runner; rule-injector + mailbox-drain registered in settings-hooks.json; checks.sh called from committer.sh AND ci.yml; validate-skills in ci.yml AND install.sh; ensure_repo_invariants fired from session init; merge --auto + do-not-merge in routes/tasks.py; evals/ present (its README notes it already caught a 17/17 'unreviewed' misparse on day one); MCP compact default-on; commit-body mandate in /commit. **Zero deploy-gaps found.**

### Correction to round 1

domdomegg's npm publishing is NOT npm trusted publishing — it's GCP Workload Identity Federation token brokerage (GitHub OIDC → gcloud secrets access → masked `npm publish`); only his MCP-registry publishing is true OIDC. Still N-A for Clade (no package fleet), but the round-1 ledger term "OIDC secrets" was imprecise.

---

## [Research] 2026-06-12 — Elite workflows study (claude-cookbooks + 5 profiles)

User question: 完整的学习他们的工作流，看看凭什么他们能又高质量又快。 Six sources swept, every practice adversarially verified against Clade's codebase (verdicts: confirmed_gap / parity / different_not_deficient / N-A). 21 adopt-now gaps, 3 bigger bets, 31 parity confirmations, 28 rejections.

> **RESOLVED 2026-06-12** — implemented same day in two waves (~50 commits, `e038bc4..`): wave 1 = 20/21 adopt-now items (26 commits, tests 237→434); wave 2 = path-scoped rules + all 3 bigger bets + 4 completeness-audit additions + fallout fixes (24 commits, tests →499). Zero-gap audit closed the ledger at 87/87 practices accounted; 2 parity verdicts below were overturned with evidence (real-API e2e tier — landed `dac3c47`; mcp-package drift gate — landed `46ad977`). Only deliberate residue: oracle_second_provider wiring (conditional unmet), session-start canary (superseded by the eval harness). Applied-learnings table: [REFERENCES.md](REFERENCES.md). Detailed per-item dispositions remain below for the record.

### Sources surveyed

| Source | Who/What | Key takeaway |
|---|---|---|
| claude-cookbooks | Anthropic's official patterns repo (83 cookbooks, 45.3k stars), Claude itself a tracked commit author | Written rubrics make quality checkable → checkable quality makes review fast → fast review makes same-day merges safe. Deterministic validators gate; LLM only summarizes failures. |
| Mic92 (Jörg Thalheim) | NixOS core/infra, ~48 commits/day in 2026, anthropics org member | Closed loops: bot opens per-input PRs → fast CI → auto-merge → Claude repairs the stragglers. CI duration IS the system's clock speed, so he builds cache/shard/eval infra to shrink it. |
| felixrieseberg | Anthropic eng lead, Claude Code Desktop/Cowork; relic = C99 coding agent for 7 OS targets in 4 days | Agents multiply output — spend the multiplier on depth (tests, gates, release pipeline, docs day one), not breadth. Invariants compiled into the build, not trusted to prose. |
| domdomegg (Adam Jones) | Anthropic; ~172 original repos maintained at near-zero marginal cost | One hub repo fans CI/settings to ~110 repos nightly; bot PRs auto-merge behind CI with a label as the only human opt-in; release = 2 commands. Repo #100 costs what repo #1 did. |
| lovesegfault (Bernardo Meurer) | Anthropic Rust/Nix; rio-build = 3,922 commits/8mo solo, best public .claude/ toolkit observed | Every environment/pipeline is a versioned CI-verified artifact; every repeated judgment becomes a machine gate; Nth-strike on an invariant → structural fix, never another review rule. |
| controversial (Luke Deen Taylor) | Stainless product engineer; Claude-authored upstream PRs merged into zed in 3h42m | AI authors, human grounds and gates: real repro + reviewed diff + regression test + root-cause narrative + disclosure. Minimal diffs with evidence are the highest-trust merge currency. |

### 凭什么又快又好 — the meta-answer

1. **Quality is machine-checkable, so review collapses into verification.** Evidence-forcing rubrics run by a fresh-context grader (cookbooks), invariants compiled into the build — win95 API allowlist fails the link (felixrieseberg), drift checks whose failure message names the fix command (lovesegfault), en-dashes and sentence-final periods as Jest assertions (controversial). Once "good" is checkable, checking is instant.
2. **Verify/CI duration is the system's clock speed — engineered like a product.** Binary caches on free GHA storage, 8-way pytest shards, eval-reuse (mic92); eval-once/warm-trunk CI with a measured cost annotation on every knob (lovesegfault); 90-second dependabot merges (domdomegg). Every automation polls the gate; a fast total gate compounds everything.
3. **Approval economics inverted: default-allow + surgical deny list.** ~10 dangerous verbs behind a regex gate + terminal bell (mic92), sandbox-then-delegate over approval ladders (felixrieseberg), do-not-merge label as the only human opt-in (domdomegg), decide()/escalate() calibration (cookbooks).
4. **Done = merged with green CI, and the loop closes itself.** merge-when-green + repair-PRs re-entering the same gate (mic92); bot-approve + auto-merge fleets (domdomegg); triage-then-batch-delegate (felixrieseberg). Failures route back into the gate, not into a human inbox.
5. **Pay setup/context once, amortize across the fleet.** Hub-repo file-sync + self-deleting setup script (domdomegg); codesigning template stamped onto every app (felixrieseberg); git-state pre-injection and session bootstrap so turn #1 starts informed (mic92, lovesegfault).
6. **Small reversible units with evidence attached are the trust currency.** +45/-1 PR with regression test + root-cause narrative merged into zed in 3.7h (controversial); one PR per flake input so one red never blocks nine green (mic92); mandatory-vs-optional review findings so nothing queues on preferences (domdomegg).
7. **Every failure debugged at most once; repeat offenders get structural closes.** CI-failure-pattern catalog with validated fixes + the Nth-strike rule: "by third strike the review rule existed, was followed, and still broke — restructure so the compiler checks it" (lovesegfault); full attempt-memory in evaluator loops (cookbooks).
8. **AI multiplies output; winners spend the multiplier on depth, not breadth.** 7 repos, all release-grade day one (felixrieseberg); 92% private volume, public output curated to deep merged fixes (controversial); every capability ships with an eval harness and measured numbers (cookbooks).

### Confirmed gaps vs current VISION (确认的差距)

**Cluster A — Oracle integrity (北极星 90% 指标只有验证器是真的才算数)**

1. **[S/high] Oracle rubric: acceptance criteria must reach the grader** (cookbooks). `worker_review.py`: lift `task_description[:400]` truncation (lines 288, 361-364); inject parsed task schema (`config.py _parse_task_schema` — the criteria block `config.py:541` already builds never reaches the oracle); rewrite `_ORACLE_SPEC_PROMPT` per the rubric table: per-criterion verdicts, 'satisfied' must cite file:line evidence, no-fire list. Fixtures in `orchestrator/tests/test_worker_modules.py`.
2. **[S/high] Oracle liveness: fail-open ≠ approved** (lovesegfault). `_oracle_pass`/`_oracle_review_chunk` return a distinct infra_error flag instead of `(True,...)` on timeout/exception (lines 235/247/327); `worker.py` tags `oracle_result='unreviewed'`, counts consecutive infra errors, ≥3 → webhook + blockers.md. Optional known-bad-fixture canary at session start. Today a dead oracle silently approves everything forever.
3. **[M/high] Evidence before verdict** (mic92, nixpkgs-review). `worker.py`: move `_run_project_tests` + `_run_intramorphic_check` BEFORE the oracle gate and auto_push (today post-commit fail-open, 627-655); thread `test_evidence` into the oracle prompts; `/review-pr` checks out the PR into a worktree, runs the CI commands /commit Step 3.6 already discovers, posts an **Evidence** section before the verdict.
4. **[S/medium] Blocking/optional gate on the chunked oracle path** (domdomegg). `_oracle_review_chunk` (309-319) currently accepts any REJECTED with no severity/confidence gate — a style nit on one chunk nukes the commit + re-spends a worker run. Enforce 'REJECTED requires severity:error'; route warning/info to skipped.md/BRAINSTORM [AI] instead of dropping.

**Cluster B — CI tests what ships (deploy-gap class)**

5. **[S/medium] CI executes install.sh + shell-tests becomes a hard gate** (domdomegg + lovesegfault). New `tests/test-install.sh` + 4th ci.yml job: clean-HOME install, idempotency, Cross-Project-Rules survival (ab06c33 regression), symlinks resolve; smoke-run the INSTALLED copy. Same commit: delete `continue-on-error: true` + `|| echo ::warning` from shell-tests (ci.yml:76-83) — today a loop-runner regression merges green and ci_watcher can never see it.
6. **[S/medium] Prose code rules become failing tests** (felixrieseberg). `orchestrator/tests/test_conventions.py`: ≤1500 lines, import-DAG acyclicity, no exception text in 500 responses. History proves prose decays: worker.py blew past 1500, str(e) reached server.py:796.
7. **[S/medium] Repo-invariants preflight** (domdomegg). `github_sync.py ensure_repo_invariants()`: idempotent `gh label create`, permission/squash check; called from ProjectSession init + start.sh health check. Fixes silent-DOA Issues sync on fresh repos.
8. **[S/medium] Skill registry: one schema, one parser** (cookbooks). `configs/scripts/validate-skills.py` in ci.yml + install.sh preflight; shared by install.sh index generation and mcp_server.load_skills(). Kills the live 'description: Skill' drift degrading skill routing across 95+ skills.

**Cluster C — Commit path safety & history as context**

9. **[S/medium] Committer defense-in-depth** (felixrieseberg + lovesegfault). `configs/scripts/checks.sh`: staged-secret scan via `redact.py --check` (fail-closed, CLADE_ALLOW_SECRETS=1 override), shellcheck --severity=error, conventional regex — called from committer.sh AND as a ci.yml step (same code both places). Workers push autonomously overnight; a dev key in a worktree WILL get staged eventually.
10. **[S/medium] History carries the payload** (controversial + felixrieseberg). Fix-intent tasks get a test-presence oracle criterion; `routes/tasks.py` replaces `gh pr create --fill` with a structured body (task, completion summary, oracle verdict, test pointer, authorship note); /commit + loop-runner + worker_taskfile mandate 2-4-line bodies (mechanism/hazard/constraint). commit-archeology and /pickup consume this directly.
11. **[S/low] Attribution trailers on worker commits** (cookbooks). committer.sh appends Co-Authored-By + X-Clade-Task when CLADE_WORKER_TASK_ID is set; auto-audit/commit-archeology segment agent-vs-human stats.

**Cluster D — Autonomous loop hygiene**

12. **[S/medium] CI-failure tasks ship the log tail + bad-fix guardrails** (mic92). scan-ci-failures.sh embeds `gh run view --log-failed | tail -40`; ci_watcher.py includes failed steps; worker_hydrate.py learns actions/runs URLs; guardrails: never blame CI infra, never downgrade deps.
13. **[S/medium] /trim-tests + suite-runtime probe** (mic92). New skill shrinks branch-touched test files (table-driven consolidation, delete mock-only/brittle), reports coverage given up; scan-health probes verify_cmd duration >100s (TEST_SAMPLE_TIMEOUT=120 silently degrades past that).
14. **[S/medium] quiet-run.sh** (lovesegfault). Full log to file, stdout = status + failed names + last 80 lines, mirrored exit code; wired into /verify, /review, loop-runner worker block. Stops raw pytest/build output billing the transcript.
15. **[S/medium] PR auto-merge behind the project's own CI** (domdomegg). `routes/tasks.py`: do-not-merge label check, then `gh pr merge --auto` (project CI becomes the gate) with fallback to immediate merge. Today Clade merges before the target repo's CI reports.
16. **[M/medium] Worktree env bootstrap + per-file post-edit checks** (lovesegfault). run-tasks-parallel.sh symlinks .venv/node_modules into worktrees (today workers can't run the documented test command at all); post-tool-use-lint.sh checks the edited file, not the whole tree, under parallel editors.

**Cluster E — Learning system & context economy**

17. **[S/medium] Nth-strike → structural close + retire the prose rule** (lovesegfault). /audit gains ESCALATE-TO-STRUCTURAL (3+ effectiveness hits → run /generate-hook inline, archive the rule with a pointer); /generate-hook Step 6 retires the source; auto-audit.sh:196 advisory becomes REQUIRED. Caps the Auto-Promoted-Rules bloat already in progress.
18. **[M/medium] Path-scoped rule injection** (lovesegfault). `configs/hooks/rule-injector.sh` (PostToolUse Edit|Write) glob-matches file_path against `paths:` frontmatter in `.claude/rules/*.md` + `~/.claude/rules/*.md`, injects via additionalContext once per session; /audit + /generate-hook write file-domain rules there instead of global CLAUDE.md.
19. **[S/medium] Dependency-bug doctrine** (controversial). /investigate Phase 6b: minimal repro → upstream patch > pin-with-linked-issue > documented workaround — never silent; one Engineering Values bullet; referenced in scan-deps task template.
20. **[S/low] MCP compact mode** (cookbooks). CLADE_MCP_COMPACT=1: 3 tools (list/search/run_skill) instead of ~95 definitions for external clients — the overflow Clade already diagnosed in itself, still shipping to Cursor/Cline.
21. **[S/low] Cross-model second-opinion subagents** (mic92). `configs/agents/second-opinion-{codex,gemini}.md`: haiku + Bash-only, shell out read-only, relay verbatim, explicit-request only; optional `oracle_second_provider` setting for >N-file diffs.

**Bigger bets (need design discussion, 设计后再做)**

- **Prompt eval harness** (cookbooks): `orchestrator/evals/` with ~20 oracle fixtures from real history (incl. known false-approves), `run_oracle_eval.py` replaying through live `_oracle_review`, supervisor structural cases. Run before prompt merges, not per-push (API cost). This is the verifier gating Cluster A — today an oracle prompt edit cannot be shown to move the 90% metric before deploy.
- **Offline recovery e2e** (cookbooks): mock-gh with persistent .gh-state/ + turn-counting mock-claude (attempt 1 fails with planted pytest output, attempt 2 clean); `test_recovery_e2e.py` asserts failure → reflection context → adapted retry → success. Every recovery bug to date was found in paid production runs.
- **Mid-flight worker steering** (cookbooks): `configs/hooks/mailbox-drain.sh` (PostToolUse) drains `.claude/worker-inbox-{CLADE_TASK_ID}.md` as additionalContext; send_message writes the inbox for running tasks. Kills the kill+requeue cost of mid-task corrections. Design: delivery semantics + interplay with spawn-time mailbox injection.

### Parity confirmed (no action) — 证明我们查过了，不是照搬

- Diagnose-then-pick context primitives → condensers.py / worker_taskfile.py:159 / pre-compact.sh / handoff STRUCTURED v2
- Evaluator-optimizer with attempt memory → worker.py:557-584 reflections + :1324-1352 chained requeue + LoopDetectionService
- Runtime decomposition, workers get task+slice → loop-runner.sh:340-447 node_supervisor + /orchestrate + build_task_file
- Deterministic validators first, LLM on failure only → loop-runner [DET]→[LLM] gating + lint reflection + error_classifier.py
- Reviewer as versioned artifact → configs/agents/code-reviewer.md + /review-pr + VERIFY-*.md templates + _score_task
- Skills as tested CLIs with thin SKILL.md → configs/scripts/*.sh + CI shell-tests + mcp_server.py multi-harness
- Context pre-injection → session-context.sh + build_task_file + handoff/pickup
- Default-allow + surgical deny-gate → pre-tool-guardian.sh + permission-request.sh + notify-telegram.sh
- Terse operational CLAUDE.md → configs/templates/CLAUDE.md anchors/recipes
- Worktree fan-out with self-contained prompts → run-tasks-parallel.sh + context_version staleness stamping
- Mock-binary e2e harness → tests/test-loop.sh MOCK_CLAUDE_* + orchestrator/tests/
- Constraints-first frozen seams → OWN_FILES/FORBIDDEN_FILES + task_queue enforcement + DAG rule
- Product-as-skill → configs/skills/ + install.sh + mcp-package/
- Repo-local run config → /init-profile + .claude/orchestrator.json + session-context auto-load
- Depth over breadth → _post_convergence_scan hardening factories + VERIFY convergence + BRAINSTORM human gate
- Hub fan-out of shared automation → configs/ + install.sh + .kit-checksum + sync-setup.sh
- Generic CI contract (--if-present) → CLAUDE.md Test/Verify lines + worker_utils skip-silent
- Self-patching dependency loop → scan-deps.sh + dep_update.py + --patrol
- Self-compacting agent memory → hooks + corrections/rules.md + /audit + /learn --prune + rule re-injection
- Drift checks naming their fix → .kit-checksum + session-context warning + start.sh auto-reinstall
- Eval-once, ship plan to workers → build_task_file TLDR/pre-hydration + plan-once supervisor
- Portable quality kit / meta-tooling / content invariants / earliest-ring gates / visual pipeline review / quantified meters / provenance / micro-commits / budgets / minimal-diff currency → see verdicts (controversial: all parity)

### Rejected (different ≠ deficient / N-A)

- 3 scoped CI reviewers (cookbooks) — placement choice: AI review fires at PR creation; direct pushes would never trigger CI reviewers
- Changed-files-only CI (cookbooks) — Clade CI is free+fast; repo-wide py_compile is load-bearing
- decide()/escalate() tools (cookbooks) — 3-tier decisions/skipped/blockers.md + interventions table is the same calibration
- GH-native dep automerge / merge-when-green babysit / claude.md symlink repo / solo-PRs+merge-queue / CI-speed Nix infra / forge-triage TUI (mic92) — mechanism differences with capability coverage at Clade's topology (local gates, committed context, own task queue)
- CLAUDE.md/DECISIONS.md split, post-merge review, tag-push matrix, codesigning (N/A), VM sandbox (host-product layer), web installer (felixrieseberg) — different placement or no protected surface
- 2-command tag release, OIDC secrets (N/A), setup.js self-registration, standards-as-npm-packages, committed test credential (N/A — GitHub revokes), ship-cadence doctrine (already VISION.md) (domdomegg)
- CI-failure markdown catalog (covered by error_classifier + intervention replay), tracey spec traceability (VERIFY.md equivalent), Renovate fleet automerge (curate-first trust model), generated workflows (premature at 84 lines), signed release gate (N/A — no publish leg) (lovesegfault)
- Colocated notes.md (injection beats colocation for agent consumers), starter template (user-level kit is stronger; no repo-creation flow) (controversial)

### Recommended additions to TODO.md

*(BRAINSTORM is an inbox — these are recommendations for human promotion, grouped by cluster, ordered by impact.)*

- [ ] **Oracle integrity package** (the highest-leverage cluster — all four touch `worker_review.py`/`worker.py` and should land as one phase): (a) criteria-injection + evidence-forcing rubric [S/high]; (b) fail-open → 'unreviewed' + infra-error counter + canary [S/high]; (c) tests run BEFORE oracle/push, evidence threaded into prompts; /review-pr executes the change [M/high]; (d) severity:error gate on the chunked path, optional findings → follow-ups [S/medium]
- [ ] **CI hardening commit**: install-test job (clean-HOME install.sh + assertions) + flip shell-tests continue-on-error to false + optional alls-green-style gate job [S/medium]
- [ ] **test_conventions.py**: 1500-line cap, import-DAG acyclicity, no exception text in 500s — runs in CI pytest AND workers' local test command [S/medium]
- [ ] **checks.sh in committer**: staged-secret scan fail-closed + shellcheck, same script reused as a CI step [S/medium]
- [ ] **CI-failure task hydration**: log tails in scan-ci-failures.sh/ci_watcher.py, actions-run URLs in worker_hydrate.py, anti-infra/anti-downgrade guardrails [S/medium]
- [ ] **/trim-tests skill + scan-health suite-runtime probe** (>100s verify_cmd → trim suggestion task) [S/medium]
- [ ] **/audit ESCALATE-TO-STRUCTURAL** + /generate-hook Step 6 rule retirement [S/medium]
- [ ] **quiet-run.sh** verify wrapper wired into /verify, /review, loop-runner worker block [S/medium]
- [ ] **gh pr merge --auto + do-not-merge label** in routes/tasks.py merge_all_done [S/medium]
- [ ] **ensure_repo_invariants()** preflight in github_sync.py, called at session init + start.sh health check [S/medium]
- [ ] **validate-skills.py**: one frontmatter schema + shared parser for install.sh and mcp_server [S/medium]
- [ ] **Dependency-bug doctrine** in /investigate Phase 6b + Engineering Values bullet [S/medium]
- [ ] **History payload**: fix-task test-presence oracle criterion + structured PR bodies (replace --fill) + commit-body rule in /commit + loop-runner + worker_taskfile [S/medium]
- [ ] **Path-scoped rule-injector hook** (.claude/rules/*.md with paths: frontmatter) [M/medium]
- [ ] **Worktree env bootstrap + per-file post-edit lint** in run-tasks-parallel.sh / post-tool-use-lint.sh [M/medium]
- [ ] Low-priority lane: committer attribution trailers [S/low]; MCP compact mode [S/low]; second-opinion-{codex,gemini} agents [S/low]
- [ ] **Design discussions (bigger bets)**: prompt eval harness (orchestrator/evals/ — gates the oracle rewrite); offline recovery e2e with planted failures; mid-flight worker steering via PostToolUse mailbox drain


## [AI] Friction Log

[2026-06-12] loop-runner: work completed but exit reason read stuck_no_commits — supervisor kept planning after 5/5 criteria met instead of returning CONVERGED / workaround: verified convergence manually via git log + gates
[2026-06-12] loop-runner: commits stay local — no push phase, fleet sync silently deployed stale HEAD / workaround: manual git push before node pulls; consider a [DET] push node after commit_changes
