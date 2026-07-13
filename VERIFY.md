# VERIFY — Clade
<!-- Managed by /review skill. Edit checkpoint descriptions freely; statuses are updated by the agent. -->
<!-- Legend: ✅ pass  ❌ fail  ⚠ known limitation  ⬜ not yet tested -->

**Project type:** cli + skill-system + orchestrator (FastAPI)
**Last full pass:** 2026-04-17
**Coverage:** 83 ✅, 0 ❌, 4 ⚠, 0 ⬜ untested

---

## Install & CLI Setup
<!-- Running install.sh should produce a working local Claude Code setup. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| I1 | `./install.sh` runs without errors — no missing source files, no broken symlinks | ✅ | 2026-07-13 | fresh and idempotent installs pass in an isolated HOME |
| I2 | All skills from `configs/skills/` are installed to `~/.claude/skills/` | ✅ | 2026-07-13 | 128/128 skills installed and validated |
| I3 | All hooks from `configs/hooks/` are installed to `~/.claude/hooks/` | ✅ | 2026-07-13 | 30/30 hooks installed and executable |
| I4 | All scripts from `configs/scripts/` are installed to `~/.claude/scripts/` | ✅ | 2026-07-13 | 35 shell scripts plus Python helpers installed |
| I5 | All templates from `configs/templates/` are installed to `~/.claude/templates/` | ✅ | 2026-04-12 | |
| I6 | `~/.local/bin/slt` symlink exists and points to `statusline-toggle.sh` | ✅ | 2026-04-12 | |
| I7 | `~/.local/bin/committer` symlink exists and points to `committer.sh` | ✅ | 2026-04-12 | |
| I8 | `~/.local/bin/devmode` symlink exists and points to `devmode.sh` | ✅ | 2026-04-12 | |

## Native Codex Distribution
<!-- Codex runs Clade skills directly from a native plugin; external MCP clients can select Codex as their execution runtime. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| CX1 | `.agents/plugins/marketplace.json` installs `plugins/clade/` as a valid Codex plugin | ✅ | 2026-07-13 | validated and installed locally as `clade@clade` |
| CX2 | All 20 curated Codex skills match their canonical sources and contain no nested `claude -p` execution | ✅ | 2026-07-13 | deterministic generator and CI drift gate pass |
| CX3 | Native lifecycle hooks inject read-only session context and guard destructive Bash commands | ✅ | 2026-07-13 | regression tests cover force-push rewriting/blocking and recursive deletion |
| CX4 | `clade-mcp` selects Claude, Codex, or auto runtime without changing the backwards-compatible default | ✅ | 2026-07-13 | unit tests and MCP initialization handshake pass |

## Behavior Anchors (CLAUDE.md `## Features`)
<!-- Each anchor must work end-to-end. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| B1 | `slt` command runs without error; output changes on repeated calls (symbol→percent→number→bar→off→…) | ✅ | 2026-04-12 | full cycle verified: off→symbol→percent→number→bar→off; bar mode renders ▓▓▓▓░░░░░░ |
| B2 | `committer "type: msg" file1 file2` stages only the named files and commits — does not stage unstaged files nearby | ✅ | 2026-04-12 | tested with bystander file in temp repo |
| B3 | `devmode` toggles `~/.claude/.dev-mode` flag; `devmode on/off/status` work as expected | ✅ | 2026-04-10 | on/off/status all return correct output |
| B4 | `/commit` skill prompt contains: analyze → split by module → confirm → commit → push flow | ✅ | 2026-04-10 | committer keyword present |
| B5 | `/loop` skill prompt contains: goal file input → supervisor plans → workers execute → convergence check | ✅ | 2026-04-10 | |
| B6 | `/review` skill prompt contains: VERIFY.md load → checkpoint loop → fix-in-session → convergence | ✅ | 2026-04-15 | 9 steps total (original 7 + new Step 5.4 E2E interrupts + Step 5.5 SEO) |
| B7 | `loop-runner.sh` exists, is executable, and passes `bash -n` syntax check | ✅ | 2026-04-10 | -rwxrwxr-x, syntax OK |

## Hook Behavior
<!-- Hooks must fire correctly and not over-block. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| H1 | `pre-tool-guardian.sh` passes `bash -n` syntax check | ✅ | 2026-04-10 | |
| H2 | `pre-tool-guardian.sh` blocks `alembic upgrade` when dev-mode is OFF | ✅ | 2026-04-10 | guardian intercepted test command containing pattern — live proof |
| H3 | `pre-tool-guardian.sh` allows `alembic upgrade` when dev-mode is ON | ✅ | 2026-04-10 | source verified: `if [[ "$DEV_MODE" == false ]]` gate at line 40 |
| H4 | `pre-tool-guardian.sh` blocks `rm -rf /` regardless of dev-mode | ✅ | 2026-04-10 | source verified: lines 78-96 |
| H5 | `pre-tool-guardian.sh` blocks `git push --force origin main` regardless of dev-mode | ✅ | 2026-04-10 | source verified: lines 99-108 |
| H6 | All other hooks pass `bash -n` syntax check | ✅ | 2026-07-13 | all 30 hooks pass |
| H7 | `pre-tool-guardian.sh` does NOT block when migration pattern appears only in a variable assignment string (false-positive fix) | ✅ | 2026-04-10 | SCANNABLE strips `VAR='...'` and `VAR="..."` lines (guardian.sh:47-50) |
| H8 | `session-baseline.sh` captures sorted `git status --porcelain` output keyed by `session_id` at SessionStart, excluding `.claude/` paths | ✅ | 2026-04-15 | tested in /tmp repo: baseline file written to `.claude/sessions/<sid>.baseline`, `.claude/` paths filtered out |
| H9 | `stop-check.sh` ignores pre-existing dirty files (present in baseline) and blocks only on session-produced changes — prevents deadlock between parallel CC sessions on same repo | ✅ | 2026-04-15 | tested: preexisting dirt → exit 0 silent; new session file → exit 2 with filename in output |
| H10 | `stop-check.sh` circuit breaker: exits 0 when `stop_hook_active=true` (Claude Code retry) AND after 2 consecutive attempt-counter blocks | ✅ | 2026-04-15 | both escape paths verified — prevents LLM from being trapped in stop-hook loop |
| H11 | `pre-tool-guardian.sh` blocks env-prefixed migrations (`DATABASE_URL="..." alembic upgrade`) and compound statements (`VAR=x && alembic upgrade`) while still allowing pure assignment lines containing the pattern | ✅ | 2026-04-15 | 9/9 regression+new tests pass (/tmp/guardian-tests.sh). Fix: strip regex now anchors to end-of-line — pure assignments stripped, env-prefix commands scanned. Resolves former KL1 false-negative. |

## Shell Script Integrity
<!-- All scripts must be syntactically valid. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SH1 | All `configs/hooks/*.sh` pass `bash -n` | ✅ | 2026-07-13 | all 30 hooks pass |
| SH2 | All `configs/scripts/*.sh` pass `bash -n` | ✅ | 2026-07-13 | all 35 scripts pass |
| SH3 | `install.sh` + `uninstall.sh` pass `bash -n` | ✅ | 2026-06-04 | uninstall.sh rewritten to derive removal lists from configs/ |

## Orchestrator — Python Syntax & Tests
<!-- The orchestrator Python modules must compile and pass tests. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| PY1 | All Python modules pass `python -m py_compile` (full list from CLAUDE.md) | ✅ | 2026-07-13 | all orchestrator modules compile clean |
| PY2 | `pytest tests/` passes with zero failures | ✅ | 2026-07-13 | 968 passed, 2 skipped |
| PY3 | No circular imports — `python -c "import server"` runs without ImportError | ✅ | 2026-04-10 | |
| PY4 | Orchestrator API returns 200 + valid JSON on core GET routes (`/api/projects`, `/api/sessions`, `/api/sessions/overview`, `/api/tasks`, `/api/ideas`, `/api/processes`, `/api/metrics/pass-at-k`) | ✅ | 2026-04-15 | tested against running instance on :8010 — 7/7 endpoints 200, all parse as valid JSON (29 projects, 1 session, 38 tasks, 10 ideas, pass_rate=1.0). Resolves former KL3. |

## Templates & Assets
<!-- Required template files must be present and valid markdown. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| T1 | `configs/templates/VERIFY-frontend.md` exists and contains all 6 required sections | ✅ | 2026-04-12 | 12 sections now (added SEO & Discoverability SEO1–SEO9 and Paid Ads ADS1–ADS4) |
| T2 | `configs/templates/VERIFY-backend.md` exists and contains all 6 required sections | ✅ | 2026-04-12 | 9 sections |
| T3 | `configs/templates/VERIFY-ai.md` exists and contains all 6 required sections | ✅ | 2026-03-28 | |
| T4 | `configs/templates/loop-goal.md` exists (loop skill depends on it) | ✅ | 2026-04-12 | |
| T5 | `configs/templates/CLAUDE.md` project template exists | ✅ | 2026-04-12 | |

## Skills Quality
<!-- Each skill must have a valid SKILL.md. First-party skills also carry prompt.md; upstream-synced skills (email-*, some ads-*/blog-*/seo-*) are SKILL.md-only by design. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SK1 | Every dir in `configs/skills/` contains `SKILL.md` | ✅ | 2026-07-13 | 128/128 skill dirs pass `validate-skills.py` with zero warnings |
| SK2 | `/review` skill: prompt.md contains all 7 steps and convergence condition | ✅ | 2026-04-15 | 9 steps total; original Steps 1-7 all present + new 5.4 (E2E) + 5.5 (SEO) |
| SK3 | `/verify` skill: prompt.md contains VERIFY.md coverage section and `VERIFY_COVERAGE` footer field | ✅ | 2026-04-10 | |
| SK4 | `/commit` skill: references `committer` script; `git add .` only appears in prohibition rule | ✅ | 2026-04-10 | |
| SK5 | `/investigate` skill: contains Iron Law, 3-strike rule, Blast Radius Gate, and structured DEBUG REPORT format | ✅ | 2026-04-10 | |
| SK6 | `/cso` skill: contains OWASP Top 10, STRIDE threat model, and false-positive filter | ✅ | 2026-04-10 | |
| SK7 | `/retro` skill: reads git history via parallel bash commands; outputs metrics table + narrative | ✅ | 2026-04-10 | |
| SK8 | `/document-release` skill: covers README audit, CHANGELOG polish, and cross-doc consistency | ✅ | 2026-04-10 | |
| SK9 | `/provider` skill: references `provider-switch.sh`; API keys never stored in config files | ✅ | 2026-04-10 | |
| SK10 | Eligible workflow skills have Completion Status footer (DONE/BLOCKED/NEEDS_CONTEXT/DONE_WITH_CONCERNS) | ✅ | 2026-04-17 | 32/32 eligible workflow skills pass (brief/minimax-usage/slt exempt; seo-*/ads-*/blog-* exempt). Count grew from 27 on 2026-04-15 — +3 for poke/status/go/learn visibility + generate-hook moved inside scope. |

---

## Known Limitations (⚠)

| ID | Checkpoint | Status | Notes |
|----|-----------|--------|-------|
| KL2 | `/commit`, `/loop`, `/start` skills cannot be fully E2E tested without actual uncommitted changes or a running background loop | ⚠ | Skill prompt content verified; runtime behavior requires manual spot-check |
| KL4 | Windows not supported — scripts use bash, `~/.claude/` paths, and POSIX tools | ⚠ | WSL2 would work; native Windows CMD/PowerShell is out of scope |

## Cross-Platform Compatibility
<!-- Scripts must work on both Linux and macOS. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| XP1 | `sha256sum` calls have macOS fallback (`shasum -a 256`) in `install.sh`, `session-context.sh`, `start.sh` | ✅ | 2026-04-10 | `_SHA256` bash array pattern present in all 3 files |
| XP2 | `timeout` calls in `loop-runner.sh` use `_timeout()` cross-platform wrapper (gtimeout → timeout → no-op) | ✅ | 2026-04-10 | gtimeout→timeout fallback present |
| XP3 | `sed -i` uses `_sed_i()` wrapper in `tmux-dispatch.sh` | ✅ | 2026-04-10 | `_sed_i` wrapper with `sed -i ''` macOS branch present |
| XP4 | `readlink -f` uses python3 fallback in `scan-todos.sh` | ✅ | 2026-04-10 | `_readlink_f()` with python3 fallback present |
| XP5 | `stat -c` calls have `stat -f` macOS fallback in session-context.sh and run-tasks*.sh | ✅ | 2026-04-10 | all 5 instances use `|| stat -f` pattern |

## Research & Backlog Health
<!-- These checkpoints prevent research from being done but not absorbed. /review must check these. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| RH1 | `BRAINSTORM.md` has no unresolved `[AI]` items — all are struck-through (resolved) or explicitly deferred | ✅ | 2026-04-12 | Gap 3 resolved (MAX_REFLECTION_RETRIES enforced worker.py:736); Gaps 1,2,4,5,6,7 marked DEFERRED with rationale |
| RH2 | `REFERENCES.md` "Planned" items are either implemented (skill/hook/script exists) or marked DEFERRED | ✅ | 2026-04-12 | 0 "Planned" items remain; /cso /retro /document-release /investigate all ✅ DONE; /learn + /ship marked TODO |
| RH3 | `docs/research/*.md` `needs_work_items` are all addressed (resolved in code) or explicitly marked not-a-gap | ⚠ | 2026-04-10 | 2026-04-07/08 research fully resolved (confirmed via BRAINSTORM). 2026-03-30 landscape docs have remaining needs_work items, most marked "not a gap" in text but not strikethrough-formatted consistently. |
| RH4 | `docs/plans/*.md` implementation plans have been executed or marked deferred — no "orphaned plans" | ✅ | 2026-04-12 | loop-fix-debt3: DONE (R1-R4 all verified). loop-phase10: DEFERRED. gstack-learnings: DEFERRED. All 5 plan files have STATUS header. |

## Skill Coordination
<!-- Verifies that skills chain correctly: next-step guidance exists, when_to_use has NOT-for disambiguation, no dead-ends. -->
<!-- HOW TO VERIFY: grep for the quoted string in the cited file. ✅ if found, ❌ if missing. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SC1 | `sync/SKILL.md` description contains "run /commit after" | ✅ | 2026-04-12 | bidirectional sync↔commit chain |
| SC2 | `commit/SKILL.md` when_to_use contains "after /sync" | ✅ | 2026-04-12 | |
| SC3 | `ship/SKILL.md` contains "document-release" as next step | ✅ | 2026-04-12 | "After shipping" section added |
| SC4 | `loop/SKILL.md` contains "After convergence" section with "/commit" | ✅ | 2026-04-12 | added this session |
| SC5 | `orchestrate/SKILL.md` contains "After Orchestrating" section with "/batch-tasks" or "/loop" | ✅ | 2026-04-12 | added this session |
| SC6 | `batch-tasks/SKILL.md` contains "After batch-tasks" section with "/commit" | ✅ | 2026-04-12 | added this session |
| SC7 | `loop/SKILL.md` when_to_use contains "NOT for TODO.md tasks (use /batch-tasks)" | ✅ | 2026-04-12 | |
| SC8 | `batch-tasks/SKILL.md` when_to_use contains "NOT for goal-file loops (use /loop)" | ✅ | 2026-04-12 | |
| SC9 | `sync/SKILL.md` when_to_use contains "NOT for post-release doc sync (use /document-release)" | ✅ | 2026-04-12 | |
| SC10 | `document-release/SKILL.md` when_to_use contains "NOT for session-end" | ✅ | 2026-04-12 | |
| SC11 | `commit/SKILL.md` when_to_use contains "NOT for releases (use /ship)" | ✅ | 2026-04-12 | |
| SC12 | `ship/SKILL.md` when_to_use contains "NOT for committing mid-session (use /commit)" | ✅ | 2026-04-12 | |
| SC13 | `research/SKILL.md` when_to_use contains "NOT for internal priorities (use /next)" | ✅ | 2026-04-12 | |
| SC14 | `next/SKILL.md` when_to_use contains "NOT for external research (use /research)" | ✅ | 2026-04-12 | added this session |
| SC15 | `review/SKILL.md` when_to_use contains "NOT for post-iteration anchor checks in autonomous loops (use /verify)" | ✅ | 2026-04-12 | added this session |
| SC16 | `orchestrate/SKILL.md` when_to_use contains "NOT for running tasks" | ✅ | 2026-04-12 | |
| SC17 | `blog/SKILL.md` when_to_use contains "NOT for site-wide SEO audit" | ✅ | 2026-04-12 | blog↔seo disambiguation |
| SC18 | `ship/SKILL.md` contains "blog audit" as post-ship step | ✅ | 2026-04-12 | /ship chains to /blog audit for blog projects |
| SC19 | `loop/SKILL.md` description contains "NOT the Claude Code built-in /loop" — disambiguates from CC runtime's interval-polling skill of same name | ✅ | 2026-04-17 | added 2026-04-17 to resolve LLM routing ambiguity after discovering both skills share the `loop` name |
| SC20 | `review/SKILL.md` description contains "NOT the Claude Code built-in /review" — disambiguates from CC runtime's PR-review skill of same name | ✅ | 2026-04-17 | added 2026-04-17; routes users to `/review-pr` for PR reviews, keeps this skill scoped to VERIFY.md coverage |
| SC21 | `audit/SKILL.md` when_to_use contains "NOT for SEO audit (use /seo-audit)" — routes domain audits to specialized skills | ✅ | 2026-04-17 | added 2026-04-17; `/audit` is scoped to `corrections/rules.md` meta-audit only — domain audits go to /seo-audit, /blog-audit, /ads-audit, /cso |
| SC22 | `status/SKILL.md` mentions `/poke`, `/brief`, AND `/pickup` in its scope-differentiator section so LLM doesn't mis-route between session-state skills | ✅ | 2026-04-17 | all three present: `grep -c` returns /poke=1, /brief=3, /pickup=3; table at top distinguishes heartbeat / dashboard / overnight / handoff-resume |
| SC23 | `verify/SKILL.md` frontmatter keeps `user_invocable: false` — the typed-`/verify`-hits-the-built-in safety argument (2026-07-10 rename spike verdict: keep shared names) rests entirely on this flag | ✅ | 2026-07-10 | `grep '^user_invocable: false' configs/skills/verify/SKILL.md`; if this flips to true, typed `/verify` becomes ambiguous with the CC built-in and the won't-rename verdict must be revisited |

## E2E Interrupts
<!-- Step 5.4 E2E interrupt testing results. Applies only to user-facing apps with auth/payment/long-running ops. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| E1 | E2E interrupt scenarios (I-*, P-*, T-*, SEQ-* from e2e-interactions.md) | ⚠ | 2026-04-15 | CLI tool — no browser-based auth/payment/long-running UI flows; e2e-interactions.md is a reference for downstream projects using this skill-system |

---
<!-- Add new checkpoints above this line. /review appends discovered scenarios here automatically. -->
