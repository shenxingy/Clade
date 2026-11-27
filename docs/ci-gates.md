**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

← Back to [README](../README.md)

# CI gates

What each CI workflow runs, why each gate exists and what it caught, and how to
run one gate by hand. Moved verbatim from `CLAUDE.md` on 2026-11-16, so that
every Clade session no longer loads it. `check-ci-checklist.py` reads the
section below. It fails when CI runs a gate this file does not name, when a
command documented here cannot run, when a script, suite or eval that CI or
this file names is not in the tree, or when a job count stated here is wrong.

## Table of Contents

- [CI (GitHub Actions)](#ci-github-actions)
  - [Stacked PRs get no CI](#stacked-prs-get-no-ci)

## CI (GitHub Actions)

**Run the gates, do not re-type them.** `ci-local.py` parses these workflow
files and executes the same `run:` blocks, so it cannot drift from CI the way
this list has twice:

```bash
python3 configs/scripts/ci-local.py --list   # what runs here, what cannot, why
python3 configs/scripts/ci-local.py          # 5/5 jobs in ~180s on a 32-core box; exit 2 if not green (below)
python3 configs/scripts/ci-local.py --json   # machine-readable, for /green
```

It stands in for `actions/setup-python` with a cached venv outside the tree, so
`pip install` steps work on a PEP 668 system Python, and it closes stdin the way
a runner does — inheriting the terminal's instead made one suite hang for 13
minutes at 9% CPU. Each job gets what a runner gives it: an empty
`$RUNNER_TEMP`, `$GITHUB_WORKSPACE`, and its own `$GITHUB_ENV`, `$GITHUB_PATH`,
`$GITHUB_OUTPUT`, `$GITHUB_STEP_SUMMARY` and `$GITHUB_STATE` files, so a step
run inside a hosted job never writes the outer job's; `$GITHUB_ENV` and
`$GITHUB_PATH` writes reach the job's later steps, and outputs are written but
not read (`${{ steps.<id>.outputs.* }}` stays unproven). Each job also gets an
empty npm global prefix of its own (`NPM_CONFIG_PREFIX`, overriding the
caller's in any spelling, with its bins first on `PATH`), so
`validate-plugin.yml`'s `npm install -g` no longer rewrites this machine's own
`claude` and two gates at once no longer race in one prefix (npm `ENOTEMPTY`,
2026-11-17); npm's cache stays shared, since cacache is built for concurrent
writers. Four things still change this machine's npm state: a prefix the
workflow names itself, which wins as on a runner; `sudo npm install -g`, since
sudo resets the environment (a `sudo` step runs only under
`--allow-host-mutation`); `npm config set prefix`, which writes
`~/.npmrc` (the job's prefix still outranks it); and a step that uses nvm.
nvm refuses `NPM_CONFIG_PREFIX` and deactivates itself, so the step would exit
11, or, in a script without `-e`, pass on another node. A step whose text shows
nvm (it sources `nvm.sh` or runs `nvm`) runs without the prefix from the start.
One whose output shows nvm's refusal of the job's prefix (a script it runs
loads nvm, or an `eval`) runs once more without it, and that attempt is its
result; it gets fresh runner files, so the first attempt's `$GITHUB_ENV` and
`$GITHUB_PATH` writes are dropped. This is not a flake rerun, so `--no-rerun`
leaves it on, but a step that timed out is not run again. Either way its
output names it, and `--json` lists it under `no_npm_prefix`. Two shapes still
go wrong. A step that hides nvm's stderr and has no `-e` is not caught; it
runs on whatever node is left. A step that loads nvm where its text does not
show it (`run: ./ci/build.sh`, which sources `nvm.sh`) and is not safe to run
twice fails here and passes on a runner: what its first attempt did before
nvm refused (`mkdir out`) is still there, so the second run fails on it, and
so does the flake rerun. Runner labels compare case-insensitively, so `[self-hosted, macOS]` or an `ARM64` label is a
platform skip on another machine, and a workflow whose push trigger filters on
`tags:` alone is a tag tier, skipped with its reason on a head that carries no
tag (`--all` runs it). `/green` drives it to green without weakening a gate.

A lane it cannot reproduce — `services:`, `container:`, `strategy:`, a
reusable workflow, a `defaults:` other than `run: shell: bash`, a job body it
cannot read, a `runs-on:` or job-level `if:` it cannot evaluate, a step whose
`if:` or `${{ }}` expression it cannot evaluate, a step that needs a repository
secret (declared, inherited or in `run:` — never run here, since a tool run
without it falls back to this machine's own credentials), an action step other
than checkout, cache, artifacts or `setup-*` (a lint action, a local
composite), or a step run without a non-secret `${{ }}` env value it inherits —
is reported **unproven** and the summary reads `PARTIAL`; a run where no job ran
reads `NOTHING RAN`. A step written for a throwaway runner that would change the
host — `sudo`, `docker image/system/builder/volume prune`, a `docker rmi` of
every image, `rm` outside the checkout and `$RUNNER_TEMP`, `apt-get
remove/purge/autoremove` — is **skipped-unsafe** and never run (on 2026-11-25 a
"Free up disk space" step's prune deleted 316 GB of a host's Docker images): a
setup or cleanup step leaves the result intact, a gate step holding one is
unproven, the JSON lists both under `skipped_unsafe`, and `--allow-host-mutation`
runs them on a throwaway VM. This repository's own `Install shellcheck` step is
one; the gate after it fails, not skips, where shellcheck is missing. A step that exits non-zero is rerun once with the same
command, env and directory; green the second time it is **FLAKY** — its job is
not failed, the summary reads `FLAKY` (or `PARTIAL`, which outranks it) and
names each one as `Job › Step (first exit N)`, and the JSON lists it under
`flaky`. A step that hit the step timeout is not rerun, and `--no-rerun` makes
the first failure final. The step timeout is 900 s scaled by the host's load per
CPU at the start (1x-4x, so 3,600 s at most); the run prints it, and
`--timeout N` sets it: a fixed 900 s killed this repository's pytest step, which
took 1,914 s at load ~80 on 32 cores. A run that is PARTIAL, FLAKY or NOTHING RAN
exits 2 (a failure is 1); `--no-strict` exits 0 there, as every run did through
the report-only week of 2026-11-06 to 11-13. This repository has no unproven
lane. Its one was `Syntax Check › Sibling facts (report only)`, which picked its
diff range with `${{ github.event_name }}` and was skipped on every local run;
it reads the runner's `$GITHUB_EVENT_NAME` and `$GITHUB_BASE_REF` now. A local
run sets neither, so it takes the push branch (`HEAD~1..HEAD`), and it skips
the `git fetch --deepen=1` that only a shallow checkout needs, so it needs no
network. Both `pull_request_target` workflows
(`honeypot-check`, `vouch-gate`) have no push or pull_request trigger and are
skipped as GitHub-side, and the four key-gated tiers, the only steps here that
use a secret, gate on `schedule`/`workflow_dispatch`, which is harmless.
`tests/test-ci-local.sh` pins the classes (the rerun and FLAKY cases in
`tests/lib/ci-local-flaky.sh`, the labels, tag tiers and runner files in
`tests/lib/ci-local-runner.sh`, the skipped-unsafe steps in
`tests/lib/ci-local-host-mutation.sh`, the record's head, dirty flag and clean
stdout in `tests/lib/ci-local-record.sh`, the default exit 2 and `--no-strict`
in `tests/lib/ci-local-strict.sh`, all of which it sources) and removes each
guard from a copy of the runner to show the suite notices.

The list below is the EXPLANATION — why each gate exists and what it caught.
`check-ci-checklist.py` keeps it complete. Run it by hand only when you want
one gate rather than the set:

```bash
# 1. Python syntax check (all modules — same find-based sweep CI runs)
cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 .venv/bin/python -m py_compile

# 1b. Python lint gate. py_compile proves a file PARSES; it cannot see a name
#     that is never bound. Both F821 hits on this gate's first run were live
#     NameErrors that had shipped under a green syntax gate — Worker.stop()
#     called an unimported preserve_worktree_wip, so every worker stop path
#     raised before cleanup. Rules and the MEASURED ignore baseline live in
#     orchestrator/ruff.toml; the version is pinned in requirements-dev.txt and
#     CI reads it from there. `--config` is not optional: the file sits under
#     orchestrator/ but governs the whole tree. The ignore list shrinks and
#     never grows; BLE001 (435 blind excepts, 89 swallowing into a bare pass)
#     is deliberately not selected yet. [lint.per-file-ignores] is NOT a
#     baseline — it parks known live NameErrors, and each entry must be deleted
#     in the same commit as its fix.
ruff check --config orchestrator/ruff.toml .

# 1c. Type gate over the load-bearing layer. Types were WRITTEN and never READ:
#     97.3% of orchestrator core parameters and 87.9% of configs/ carried
#     annotations with ZERO checkers anywhere, so the cost was paid and none of
#     the benefit collected. Runs in the `pytest` job, not `syntax-check`,
#     because `pip install -r requirements-dev.txt` already runs there — one pin
#     line governs local and CI with no second grep-install block to drift. Runs
#     from the REPOSITORY ROOT: mypy.ini's `files =` resolves against the working
#     directory, so `cd orchestrator` first checks nothing and exits non-zero.
#     Scope is configs/ only and it sits at ZERO — orchestrator/ carries ~70 and
#     orchestrator/tests/ 187, which is separate work; ads/, blog/ and seo/ are
#     absorbed upstream code and are excluded in mypy.ini. Its first run found
#     three real defects, not style: a `.group()` on a possibly-None match in an
#     unattended archiver, an int passed where an (r,g,b) tuple was expected on
#     greyscale images, and a str shadowing a list[str].
python3 -m mypy --config-file mypy.ini

# 2. Tests, plus the two offline evals the same `pytest` job runs
cd orchestrator && .venv/bin/python -m pytest tests/ -v
cd orchestrator && .venv/bin/python evals/run_provider_conformance.py
cd orchestrator && .venv/bin/python evals/run_hack_eval.py

# 2b. Can the red-phase instrument still go red? One positive and one negative
#     control. A harness that cannot fire reports a clean 0% exactly like a
#     clean codebase — this one has shipped that failure before.
python3 configs/scripts/red-phase-audit.py --self-test

# 2c. Same question of the polling instrument, in the same `pytest` job.
#     `workflow-scorecard.py --polls` counts repeated status reads per
#     background job; its mutation guard matched the `>/` of `2>/dev/null`, so
#     every session ever scanned reported zero polls and the number read as
#     discipline. Second instrument in this repo to ship unable to fire.
python3 configs/scripts/workflow-scorecard.py --self-test

# 2d. And of the skill-contract gate. Its first version accepted the bare word
#     rather than the literal `--flag`, so it could not fire — flag names are
#     common English words.
python3 configs/scripts/check-skill-contracts.py --self-test

# 2e. And of the Workflow preflight (`workflow-preflight.sh` → this script's
#     --hook mode). Its controls run through hook_main, the hook's own entry
#     point, and each of its mutations in test_self_tests_can_fire.py turns it
#     red — including "a deadline in the script stage drops the deny", the
#     property that makes the args check run first. A 2026-10-23 review
#     removed 48 guards one at a time and 30 of the checker's stayed green in
#     both this self-test and the suite (every truncation method, sink and
#     exclusion but one, the quota numbers at their boundaries, the real
#     deadline timer); each now has a control and a mutation. The shell
#     wrapper's guards (4 of the 48 also stayed green) are mutated by
#     tests/test-workflow-preflight.sh itself.
python3 configs/scripts/check-workflow-script.py --self-test

# 2f. And of the session keeper (pytest job). keep-sessions.py copies the
#     transcripts of corrected sessions, redacted and gzipped, to
#     ~/.local/share/clade/sessions/ before Claude Code's 30-day cleanup;
#     radar-cron.sh runs it weekly. A keeper that stopped masking, followed a
#     symlink out of a session, or copied a session marked private would still
#     print "kept N sessions". The self-test drives main() on a synthetic HOME
#     with a negative control per exclusion, under umask 022 so the 0700/0600
#     checks can fail; its mutations are in
#     orchestrator/tests/can_fire/keep_sessions.py, which
#     test_self_tests_can_fire.py loads.
python3 configs/scripts/keep-sessions.py --self-test

# 2g. And of the harness-usage report, in the same `pytest` job. A report that
#     cannot attribute a hook's trace lists that hook as never fired, and the
#     never-fired list is what a reviewer retires from. Its first draft, over
#     335 main-thread transcripts (30 days to 2026-11-06, the author's host),
#     left 179 SessionStart and 159 UserPromptSubmit traces unattributed:
#     those contexts carry no command and no shared call id. Pairing them by
#     content brought that to 0 and 34 (the 34 are an older correction-detector
#     message that no longer matches its source). The controls
#     drive main() under a temporary HOME; the mutations, the list of guards
#     the self-test is proven to check, live in
#     orchestrator/tests/can_fire/harness_usage.py, which
#     test_self_tests_can_fire.py loads into its MUTATIONS.
python3 configs/scripts/harness-usage.py --self-test

# 2h. And of the status line's task-time estimate (pytest job). task-eta.py
#     prints how long the task has run, the job it waits on while no turn runs,
#     a Monitor's timeout as a bound, and nothing when idle; its p25-p75 band
#     for what is left reaches only --json. A lookup that fell back to the global
#     median, a task boundary moved to the turn, background work no longer seen
#     in flight (or a stopped job still seen), an idle pane printing a time, or
#     an estimate past 4 h would all still print a plausible line. The self-test fits a seeded synthetic
#     history, never the host's transcripts, and checks the lookup against the
#     median on held-out draws; its mutations, with a no-op control that must
#     stay green, are in orchestrator/tests/can_fire/task_eta.py.
python3 configs/scripts/task-eta.py --self-test

# 2i. Global CLAUDE.md ceiling (pytest job, test_conventions.py section 5).
#     install.sh installs configs/CLAUDE.md as ~/.claude/CLAUDE.md, which Claude
#     Code loads into every session and subagent and warns about past 40,000
#     chars per file on a 200k-context model. The template grew from 20,322
#     chars (5aac2b3, 2026-10-17) to 32,555 bytes (e82c0c8, 2026-11-26) with
#     nothing to stop it; auto-audit.sh's budget refuses promotions only. With
#     the owner's private Cross-Project Rules tail (16,073 bytes on the author's
#     host that day) the installed file is 48,628 bytes, already past the
#     warning. CLAUDE_MD_CEILING_BYTES only moves down: the test fails over it,
#     and fails more than 1,000 bytes under it until a cut lowers it, so raising
#     it is always a visible edit in the same diff. A third case fails if
#     install.sh stops copying that file, so the gate cannot watch a stale one.
cd orchestrator && .venv/bin/python -m pytest tests/test_conventions.py -q -k global_claude_md

# 3. Shell syntax check (hooks, scripts, installer). One file per `bash -n`: it
#    parses only its first argument, so `bash -n a.sh b.sh` never reads b.sh.
for f in configs/hooks/*.sh configs/hooks/lib/*.sh configs/codex-hooks/*.sh \
         configs/kimi-hooks/*.sh configs/scripts/*.sh install.sh uninstall.sh \
         .claude/pre-commit.sh; do
  bash -n "$f" || echo "FAILED: $f"
done

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
#    sync never bumps a row's date to match a fix: it names any rewritten row
#    that carries a date ("re-verify, then update its date"). A fact whose value
#    is itself a date is rewritten like any other value, and is not listed
#    unless its line carries another date. Its --self-test runs in the pytest
#    job (test_self_tests_can_fire.py, mutations in can_fire/doc_align.py).
python3 configs/scripts/doc-align.py verify             # doc-align.py sync to fix

# 8. Skill registry validation
python3 configs/scripts/validate-skills.py configs/skills

# 8b. Settings reference drift gate — templates/orchestrator-settings.example.json
#     is GENERATED from config.py:_SETTINGS_DEFAULTS. Adding a setting without
#     regenerating leaves docs/configuration.md's "every supported key" promise
#     false; it had drifted to 33 of 75 keys, one of them no longer a setting.
python3 configs/scripts/regen-settings-example.py --check   # regenerate without --check

# 8c. Skill overrides drift gate — configs/settings-skill-overrides.json is
#     GENERATED from the skills tree: every hub-family sub-skill (blog-*, seo-*,
#     ads-*) listed `name-only`, plus the skillListingBudgetFraction that fits.
#     Why it exists: Claude Code lists skills to the model inside a character
#     budget of window × bytes/token × fraction (default 1% = 8,000 chars on a
#     200k model) and, over budget, keeps descriptions by USAGE score — a skill
#     nobody has invoked scores 0 and is listed by name only, so it can never be
#     auto-selected. Measured 2026-09-20 (Claude Code 2.1.258): listing 66,408
#     chars over 166 skills; 103 of Clade's 144 never used; on a stock install
#     a 200k model drops all 142 and a 1M model drops 95 — the 95 name-only
#     lines this repository's own sessions had been showing. install.sh merges
#     the file into ~/.claude/settings.json, the user's own entries winning.
python3 configs/scripts/regen-skill-overrides.py --check      # regenerate without --check

# 8d. Context policy file + self-test — configs/context-policy.json holds the one
#     value install.sh may write into a user's settings.json (`autoCompactWindow`
#     350000, opt-in, §8d). Claude Code drops an out-of-range value silently
#     (int 1e5–1e6 with `.catch(void 0)` in the 2.1.236–2.1.283 schema), so a bad
#     edit would ship as a no-op nobody sees; --check refuses it, an unparseable
#     version bound, a retire_from at or below the floor, a Codex/Kimi mode other
#     than report-only, and a value whose measurement block names no population.
#     --self-test (controls in context_policy_selftest.py) runs `apply` and
#     --check through the real CLI against fake `claude` binaries, including a
#     server-side window cached in .claude.json (retract, write nothing) and a
#     null or empty cache (write), and counts a step only when apply exited 0;
#     its mutations are in test_self_tests_can_fire.py.
python3 configs/scripts/context-policy.py --check
python3 configs/scripts/context-policy.py --self-test

# 8e. Outcome scorecard self-test. Every other scorecard measures INPUTS —
#     workflow-scorecard (parallelism), session-scorecard (corrections), /retro
#     (velocity) — so "the agents ran a lot" could pass for "the work was good".
#     outcome-scorecard.py asks whether merged PRs stuck: reverted (by sha,
#     exact title, or a revert PR naming #N), fixed-forward (a later fix by
#     anyone into the same base branch sharing a non-bookkeeping path — a
#     SIGNAL, precision unmeasured), settling (younger than --settle, never
#     kept), and review load. An
#     instrument that cannot fire reads "nothing reverted" as good news, so the
#     self-test drives main() on fixtures and a fake gh (never the network),
#     with a positive and a negative control per rule; its mutations are in
#     orchestrator/tests/can_fire/outcome_scorecard.py, which
#     test_self_tests_can_fire.py loads. No gh call carries --jq: the fixtures hold
#     gh's raw output and the fake gh records GhSource's arguments, because a
#     --jq string and an already-flat fixture left four mutations green.
python3 configs/scripts/outcome-scorecard.py --self-test

# 8f. Friction rank self-test. The correction channel is slow and yields generic
#     rules; the harness's own verdicts, ranked by how many sessions they recur
#     in, yield one-sentence harness repairs (Gorokh, 2026-10-08, one operator's
#     fleet). friction-rank.py reads them through transcripts.py and never clips
#     a verdict text — radar's hand tally cut stderr at 90 characters. The
#     self-test drives main() on synthetic transcripts under --root with --now
#     pinned: every verdict class, a quoted refusal that is NOT one, the family
#     rules (heredocs stripped, cd skipped, option values skipped, subcommands
#     kept), sessions before count, held-out weeks and their span, the window,
#     main-thread-only, the refusals table's classes, the latest occurrence and
#     unreadable transcripts. Its mutations are in
#     orchestrator/tests/can_fire/friction_rank.py, which
#     test_self_tests_can_fire.py loads.
python3 configs/scripts/friction-rank.py --self-test

# 9. Architecture map coverage — every orchestrator module listed in docs/orchestrator-architecture.md
python3 configs/scripts/check-arch-map.py

# 10. Reference resolution — every markdown link, anchor, and path resolves
python3 configs/scripts/check-references.py

# 10c. Action pinning — every `uses:` is a commit SHA, never a movable tag.
#      The repo already pinned 8 of 12; the 4 it missed were exactly the ones in
#      the two `pull_request_target` workflows, which run with write scopes on
#      fork PRs. Resolve a tag with:
#        gh api repos/<owner>/<repo>/git/ref/tags/<tag> -q .object.sha
python3 configs/scripts/check-action-pinning.py

# 10b. Roadmap authority — TODO.md is the single source of open work; VISION.md,
#      IMPLEMENTATION_PLAN.md and PROGRESS.md each state their role and carry no
#      unchecked `- [ ]`. Nothing named a winner before, so VISION's milestone
#      table stopped at Phase 13 while TODO tracked a finished Phase 14.
python3 configs/scripts/check-roadmap-authority.py

# 10d. Progress-log cap — the /sync skill caps PROGRESS.md at 100 lines and
#      prescribes docs/progress-archive/. Stated in prose only, the file reached
#      1,209 lines and the directory was never created. Same shape as every
#      other drift here: a rule nothing checked.
python3 configs/scripts/archive-progress.py --check      # --apply to archive

# 10e. Layer declaration — docs/layers.json says which surfaces actually run and
#      how much a finding in each is worth. The /review, /cso and /next skills
#      read it. It exists because an audit spent most of its effort on the
#      dormant orchestrator and nothing in the tree said it was dormant.
python3 configs/scripts/check-layers.py

# 10f. Skill contracts — a skill must not advertise what it does not do. Every
#      `--flag` in an argument-hint must appear in the body, and every path the
#      front matter names must resolve. /create-pr advertised --dry-run and only
#      ever published; a run asking to preview opened a real PR.
python3 configs/scripts/check-skill-contracts.py

# 10h. Skill listing budget — with the shipped overrides and fraction, does the
#      whole model-facing listing fit a FRESH install on a 200k model, so no
#      description is dropped? Reimplements the binary's arithmetic (entry =
#      `- name: description - when_to_use` capped at 1536; greedy fill by usage
#      score; ~8,000 chars reserved for the bundled skills that always keep
#      theirs). Validated: with this machine's usage history it predicts the 95
#      name-only skills the session prompt actually showed. Prints the minimum
#      fraction when it fails; --usage ~/.claude.json shows what this machine
#      keeps; --no-overrides shows the stock situation. Its --self-test has
#      mutations in test_self_tests_can_fire.py.
python3 configs/scripts/check-skill-listing.py

# 10f. Runnable paths — if a skill tells you to run it, it must exist.
#      check-references.py strips inline code spans by design, so every runnable
#      path was invisible to it; that is how five installer paths that had never
#      existed survived every gate. A first attempt was withdrawn at ~30%
#      precision. This one measured 22 findings, all real, after the reference
#      convention was settled. 19 known phantoms are baselined in the script and
#      that list shrinks only; a NEW one fails the build.
python3 configs/scripts/check-runnable-paths.py

# 10g. Sibling facts — before changing a stated fact, find every other place
#      that states it. 43% of round 5's findings were siblings of earlier
#      fixes. Reports, never blocks; --strict makes it fail.
python3 configs/scripts/check-sibling-facts.py

# 11. Shellcheck (CI installs shellcheck; local may not). The `bash` prefix is
#     required — checks.sh is mode 100644, so invoking it directly exits 126 —
#     and the file list must match CI's, which is every hook, adapter and
#     script plus install.sh, uninstall.sh and .claude/pre-commit.sh. The line
#     here used to be neither: it ran one file, and did not run at all.
bash configs/scripts/checks.sh shellcheck configs/hooks/*.sh configs/hooks/lib/*.sh configs/codex-hooks/*.sh configs/kimi-hooks/*.sh configs/scripts/*.sh install.sh uninstall.sh .claude/pre-commit.sh

# 12. Every suite the `shell-tests` job runs — all 38, not a convenient subset
#     (`loop` also runs test-loop-holdout.sh, and sources test-loop-env.sh, through
#     tests/lib/loop-fixture.sh — neither has a step of its own)
for t in loop checks commit-archeology skill-routing pr-scope-policy audit worktree-env \
         rule-injector mailbox-drain correction-pairing sync-store hooks hook-provenance \
         worker-checkpoint \
         kimi-hooks codex-hooks sync-link-projects sync-link-projects-remote sync-health memory-sync-breaker \
         post-edit-check session-context session-scorecard post-compact-reinject \
         memory-staleness \
         context-warning-drain ensure-dev-server quiet-run scan-health \
         pre-tool-guardian ask-while-live loop-args memory-watchdog ci-local \
         seo-geo radar-cron workflow-preflight \
         wf-reader-guard; do
  bash "tests/test-$t.sh" >/dev/null || echo "FAILED: $t"
done

# 13. The install-test job (its own CI job, not part of shell-tests)
bash tests/test-install.sh

# 13b. Same job: install.sh §8d, the opt-in context policy, against a throwaway
#      $HOME with fake `claude` binaries on PATH — sidecar ownership, a user
#      value or deletion never touched, step-aside for every skip_when and for
#      managed files and drop-ins, retract-and-write-nothing while .claude.json
#      caches a server-side window, fail closed on an unreadable version,
#      symlink- and mode-preserving writes, ~/.codex and ~/.kimi-code
#      byte-identical to an install.sh without §8d, uninstall.sh. Its last suite
#      removes each guard from a copy of context-policy.py and requires red.
bash tests/test-context-policy-install.sh

# 13c. Same job: the status line's task-time segment end to end, against a
#      throwaway $HOME and synthetic transcripts — install.sh adds
#      statusLine.refreshInterval or keeps the user's, the segment reads
#      "20m workflow", the whole line fits COLUMNS (the pane's width) with
#      the task time last to go, the line never reads the model (no refit,
#      the same line with it missing or corrupt) while --json on a missing
#      model starts one detached refit behind a lock, every fail-soft case
#      exits 0 with the other segments. Its last suite removes each guard from a copy
#      of statusline-command.sh, install.sh or task-eta.py and requires red.
bash tests/test-statusline-eta.sh

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

This checklist drifted twice before anything watched it: 4 of 7 gates until
2026-08-22 (`df802c3`), then 7 of 11 `syntax-check` gates and 0 of 17 shell
suites until 2026-08-29. `check-ci-checklist.py` (item 15) now enforces the
superset and runs in CI, and `ci-local.py` runs the gates so nobody has to
re-type them. **When you add a CI step, add its explanation here in the same
commit.** The gate catches a forgotten entry as long as the new step invokes
something `ARTEFACT_PATTERNS` already recognises, or lands in `syntax-check` or
`shell-tests`, whose step counts it also compares. A step running a tool no
pattern names is invisible to it — the gate's own documented blind spot (the
comment under `ARTEFACT_PATTERNS` in `check-ci-checklist.py`), which fired the
day the ruff step landed. **A new KIND of gate therefore needs its pattern
added to that script in the same commit too.**

On push/PR to `main`, four workflow files fire:

- `ci.yml` — `syntax-check` (29 gates), `pytest` (suite + 2 offline evals),
  `shell-tests` (38 suites), `install-test`. `run_hack_eval.py` scores
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
