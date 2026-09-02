# Agent Ground Rules

These rules enable autonomous, unattended operation across all projects.

## Commits
- Use `committer "type: message" file1 file2` for all commits — NEVER `git add .`
  - `committer` is at `~/.local/bin/committer` (symlinked from `~/.claude/scripts/committer.sh`)
  - This prevents parallel agents from staging each other's files
- Conventional commit format required: `feat/fix/refactor/test/chore/docs/perf`
- Commit small and often — each logical unit gets its own commit

## Pull Requests
- One PR = one independently reviewable and reversible feature, bug fix, or
  refactor. Tests, migrations, generated contracts, and docs for that same
  behavior stay with it.
- Multiple commits do not make a multi-feature branch acceptable. Separate
  roadmap phases and independently useful capabilities into separate PRs.
- When features depend on each other, use stacked PRs and require each branch
  to pass its own CI. Never reuse a final aggregate branch's green result as
  the only evidence for every layer.
- Create PRs through `/create-pr`; it performs the scope gate and safely
  reconstructs an oversized branch before opening review.

## CI — run it on hardware you already own

**Hosted CI is billed per job, rounded up to the minute, per job.** A workflow
whose four jobs take 24s, 39s, 60s and 73s bills four minutes, not three. The
platform multiplies it: Linux 1x, Windows 2x, **macOS 10x**. Public
repositories get standard runners free; private ones do not, and that is where
the bill comes from.

So the default is inverted from the usual habit: **the local run is the gate,
and the hosted run is the receipt.** Push only after a full local pass. This is
not only about money — a local run answers in seconds and needs no push to
start, which is the larger saving on a public repo where the minutes are free.

**Run the real gates, not a remembered subset:**

```bash
python3 ~/.claude/scripts/ci-local.py --list   # what runs here, what cannot, and why
python3 ~/.claude/scripts/ci-local.py          # run them; exit 0 only if all passed
python3 ~/.claude/scripts/ci-local.py --json   # machine-readable, for an automatic fixer
```

It parses `.github/workflows/*.yml` and executes the same `run:` blocks, so it
works on any repository and **cannot drift from CI by construction**. A
hand-maintained "run these before committing" list is the thing that drifts:
one such list in this toolkit was wrong twice, covering 4 of 7 gates and later
7 of 11 plus 0 of 18 suites, both times looking authoritative.

**Reading its output honestly.** A skipped job is reported with its reason and
never dropped — "nothing ran" and "everything passed" must not look alike. Jobs
it will not run locally, each for a good reason: `pull_request_target`
workflows (they act on the GitHub API, not the tree), steps needing a
repository secret, conditional `schedule`/`workflow_dispatch` tiers (`--all`
includes them), and jobs whose `runs-on` names a platform this machine is not.

**Cross-platform work goes to the machine that has the platform.** A macOS job
belongs on your Mac and a Windows job on your Windows box — over SSH or by
running an agent locally on that machine — not on a hosted runner at 10x or 2x.
`--list` names the platform each skipped job needs.

**Keep hosted CI for what only it can do:** fork PRs from people whose machines
you do not trust, the clean-machine property (a fresh checkout with no local
state), and platforms you do not own. Deleting a hosted workflow whose gate now
runs locally is a cost DECISION; read the commit that removed it before
reporting its absence as a gap.

**With no remote CI, a green local run is the only gate.** Run it to
completion before every push, and never chain it behind `echo` — that masks the
exit code and turns a red run green.

## Communication
- When blocked on something requiring human input: write to `.claude/blockers.md` and stop
  - Format: `## Blocker [datetime]\n[what you need]\n[what you tried]`
- Don't loop retrying what you cannot fix — surface it clearly, then stop
- When starting a task, switching focus, or reaching a milestone: `vt title "action - context"` (if VibeTunnel installed)

## Autonomy
- Proceed WITHOUT asking for: file edits, test runs, builds, type-checks, lint, **commits via `committer`** (reversible with `git reset --soft HEAD~1`)
- Ask the user BEFORE: deleting files, modifying .env, running migrations, force-pushing, `git push` to shared/protected branches
- **Bug fix / gap closure without permission**: When a bug or a concrete, reversible gap is clearly identified with a clear implementation and no destructive side effects — build it immediately. "Should we fix?" or offering to "open a TODO" creates an unnecessary round-trip (identified ≠ executed). Ask only when the fix is ambiguous, destructive, or has architectural tradeoffs.
- **Recommendation = decision for low-stakes A/B/C**: If you've enumerated options, marked one as recommended, and the action is reversible (commits, file edits, doc reorganization, choice of where to write a section), just do the recommended one. Don't ask "A or B?" after writing "I recommend A" — the user reads the recommendation, picks "A" 95% of the time, and the round-trip wastes a turn. Reserve A/B/C-and-ask for irreversible actions or genuine architectural forks where you'd be uncertain even after thinking longer.
- **Stop hook nagging ≠ user input needed**: When a Stop hook complains about uncommitted files mid-task, this is a process signal, not a user question. If the project rule is "commit small and often" and `committer` is available — commit and move on. Don't escalate the hook output to the user as a decision point.
- **Deployment topology**: Before checking localhost, scan for known deployment URLs (Tailscale internal domain, env vars like SITE_URL, INTERNAL_HOST). Default-to-localhost assumption produces wrong-context reads when the real service is remote.

## Adaptive Delegation
- Decide before broad repository reads whether the lead should solve the task or use one direct subagent.
- Keep architecture, ambiguous requirements, security-sensitive changes, migrations, broad refactors, and work without a deterministic verifier in the lead session.
- Use `Explore` for bounded read-heavy discovery and `bounded-implementer` for one low-risk change only when file ownership and a deterministic verifier are explicit.
- **Hand-rolled fan-out**: at most three agents for genuinely independent
  read-only work. Never run concurrent writers on the same files, and do not
  edit a delegated file until its owner returns.
- **A planned Workflow run is exempt from that three.** Its size is governed by
  `workflowSizeGuideline` in settings, and the cap exists to stop an unplanned
  spray of Agent calls, not to stop a script that assigns disjoint file
  ownership. Read as a blanket rule it silently fought every workflow — it sat
  in context while a 166-agent review ran on 2026-09-02.
- **Prefer `pipeline()` to `parallel()` whenever the work has stages, and cut
  more units than there are slots.** Measured across 89 parallel runs (1777
  agents, 49.9 h): 45% of all makespan was spent with exactly one agent still
  running. Shape decides that, not agent count — a 110-agent pipeline finished
  with a 0% single-agent tail at 80% utilisation despite a 6.9x straggler
  spread, while a 10-agent barrier with a 2.0x spread wasted 19%. Check any run
  with `workflow-scorecard.py`; a tail over 15% means the shape was wrong.
- Subagents must not delegate recursively — enforced, not merely asked:
  `install.sh` sets `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`. A Workflow script
  orchestrates from the lead, so its agents never need to nest and the cap costs
  it nothing. Permit one cheap retry at most; then the lead resumes with the
  collected evidence.
- The lead reviews every returned diff and verifier result before acceptance. Cross-vendor delegation remains explicit-only.

## Context Management
- Context window ~80% full → run `/handoff` to save state, then start a new session with `/pickup`
- If `.claude/handoff-*.md` exists at session start → it is auto-loaded; run `/pickup` to activate
- Task queue pattern: the user may send multiple tasks in sequence — queue them, execute in order, don't wait between tasks

## Code Architecture (Claude Code-Optimized)

Structure code for efficient Claude Code tool usage:

- **File size**: Keep each file under 1500 lines (Read tool default = 2000 lines; under 1500 = readable in one shot)
- **Module count**: 4-6 modules per component. NOT 1 monolith, NOT 15+ fragments. Each additional file = 1 extra Read tool call.
- **Section markers**: Use clear `# ─── Section Name ───` headers so Grep can navigate within files
- **Edit-friendly**: Shorter files = fewer string duplicates = reliable Edit tool operations
- **Cohesion over separation**: Keep tightly coupled code in one file. Fix a bug by reading 1 file, not 3.
- **DAG imports**: Module dependency graph must be a strict DAG (no circular imports). Use lazy imports or duck typing (`Any`) to break potential cycles.
- **CSS extraction**: For HTML files with inline CSS > 200 lines, extract to separate `.css` file. Keep JS inline if tightly coupled (SPA globals, no module system).

## README & Docs

- README is a landing page, not a reference manual. Target: 200–300 lines.
- When README exceeds ~300 lines: move detailed sections to `docs/` files. Keep in README: install, key features table, command table, links to docs.
- Every README must have a TOC (GitHub anchor format) when it has 5+ sections.
- docs/ files: line 1 = language toggle, line 3 = back link to README, then internal TOC.
- The `/sync` skill checks: if README > 300 lines, flag sections that should move to docs/.

## Engineering Values

These guide all judgment calls — apply them when choosing between approaches:

- **DRY**: Flag repetition aggressively. Three near-identical blocks = refactor signal.
- **Tests non-negotiable**: Err toward too many tests, not too few. Cover failure paths, not just happy paths.
- **Engineered enough**: Not fragile/hacky, not premature-abstraction. Match complexity to actual requirements.
- **Edge cases over speed**: Thoughtfulness > velocity. Handle empty DB, first run, null input, concurrent access.
- **Explicit over clever**: Readable in 6 months > clever today. Name things clearly, avoid magic.
- **Dependency bugs**: Minimal repro first, then upstream patch > pin-with-linked-issue > documented workaround with upstream link. Silent workarounds are forbidden — see `/investigate` Phase 6b.

## Plan Mode

When entering Plan Mode for a non-trivial change, offer the user a choice before proceeding:

- **BIG CHANGE**: Work through interactively — Architecture → Code Quality → Tests → Performance, up to 4 top issues per section.
- **SMALL CHANGE**: One question per section only.

For each issue found: describe concretely (file:line), give 2–3 options with tradeoffs, give an opinionated recommendation, then ask before proceeding. Number issues (1, 2, 3) and letter options (A, B, C) so the user can respond unambiguously (e.g. "1A, 2B").

## Pre-Code Reflection

Before writing or modifying code, consider these failure patterns (learned from cross-project audits):

- **Settings/wiring**: If adding a config/setting/flag — trace the full path: definition → read → callsite → effect. Untested wiring = silent feature breakage.
- **Edge cases**: Does this work on first run (empty DB, no git history)? On a different OS (stat -c vs -f, path separators)? With empty/null/duplicate input?
- **Async boundaries**: If async — what happens when the world changes mid-flight? Subprocess needs kill+drain on timeout? Closure captures stale state? Lock granularity sufficient?
- **Security surface**: Am I validating at the system boundary? Any secrets, credentials, or user input flowing into commands/queries/URLs without sanitization?
- **Deploy gap**: Will this change actually reach the runtime? Source ≠ deployed. Config ≠ loaded. Defined ≠ called.
