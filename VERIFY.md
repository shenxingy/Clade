# VERIFY — Clade
<!-- Managed by /review skill. Edit checkpoint descriptions freely; statuses are updated by the agent. -->
<!-- Legend: ✅ pass  ❌ fail  ⚠ known limitation  ⬜ not yet tested -->

**Project type:** cli + skill-system + orchestrator (FastAPI)
**Last full pass:** 2026-04-12
**Coverage:** 67 ✅, 0 ❌, 5 ⚠, 0 ⬜ untested

---

## Install & CLI Setup
<!-- Running install.sh should produce a working local Claude Code setup. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| I1 | `./install.sh` runs without errors — no missing source files, no broken symlinks | ✅ | 2026-03-30 | 29 config skills + 3 userSettings = 32 total installed |
| I2 | All skills from `configs/skills/` are installed to `~/.claude/skills/` | ✅ | 2026-04-10 | 29/29 skills installed |
| I3 | All hooks from `configs/hooks/` are installed to `~/.claude/hooks/` | ✅ | 2026-04-10 | 17/17 hooks installed (4 new since last review: linter-config-guard, permission-request, revert-detector, post-tool-use-lint) |
| I4 | All scripts from `configs/scripts/` are installed to `~/.claude/scripts/` | ✅ | 2026-04-10 | 27/27 scripts installed |
| I5 | All templates from `configs/templates/` are installed to `~/.claude/templates/` | ✅ | 2026-03-28 | |
| I6 | `~/.local/bin/slt` symlink exists and points to `statusline-toggle.sh` | ✅ | 2026-03-28 | |
| I7 | `~/.local/bin/committer` symlink exists and points to `committer.sh` | ✅ | 2026-03-28 | |
| I8 | `~/.local/bin/devmode` symlink exists and points to `devmode.sh` | ✅ | 2026-03-28 | |

## Behavior Anchors (CLAUDE.md `## Features`)
<!-- Each anchor must work end-to-end. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| B1 | `slt` command runs without error; output changes on repeated calls (symbol→percent→number→bar→off→…) | ✅ | 2026-04-12 | full cycle verified: off→symbol→percent→number→bar→off; bar mode renders ▓▓▓▓░░░░░░ |
| B2 | `committer "type: msg" file1 file2` stages only the named files and commits — does not stage unstaged files nearby | ✅ | 2026-03-28 | tested with bystander file in temp repo |
| B3 | `devmode` toggles `~/.claude/.dev-mode` flag; `devmode on/off/status` work as expected | ✅ | 2026-04-10 | on/off/status all return correct output |
| B4 | `/commit` skill prompt contains: analyze → split by module → confirm → commit → push flow | ✅ | 2026-04-10 | committer keyword present |
| B5 | `/loop` skill prompt contains: goal file input → supervisor plans → workers execute → convergence check | ✅ | 2026-04-10 | |
| B6 | `/review` skill prompt contains: VERIFY.md load → checkpoint loop → fix-in-session → convergence | ✅ | 2026-04-10 | |
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
| H6 | All other hooks pass `bash -n` syntax check | ✅ | 2026-04-10 | all 17 hooks pass (4 new: linter-config-guard, permission-request, revert-detector, post-tool-use-lint) |
| H7 | `pre-tool-guardian.sh` does NOT block when migration pattern appears only in a variable assignment string (false-positive fix) | ✅ | 2026-04-10 | SCANNABLE strips `VAR='...'` and `VAR="..."` lines (guardian.sh:47-50) |

## Shell Script Integrity
<!-- All scripts must be syntactically valid. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SH1 | All `configs/hooks/*.sh` pass `bash -n` | ✅ | 2026-04-10 | all 17 hooks pass |
| SH2 | All `configs/scripts/*.sh` pass `bash -n` | ✅ | 2026-04-10 | all 27 scripts pass |
| SH3 | `install.sh` passes `bash -n` | ✅ | 2026-04-10 | |

## Orchestrator — Python Syntax & Tests
<!-- The orchestrator Python modules must compile and pass tests. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| PY1 | All Python modules pass `python -m py_compile` (full list from CLAUDE.md) | ✅ | 2026-04-10 | all modules compile clean |
| PY2 | `pytest tests/` passes with zero failures | ✅ | 2026-04-10 | 178/178 passed in 2.78s (was 19 — significant test growth) |
| PY3 | No circular imports — `python -c "import server"` runs without ImportError | ✅ | 2026-04-10 | |

## Templates & Assets
<!-- Required template files must be present and valid markdown. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| T1 | `configs/templates/VERIFY-frontend.md` exists and contains all 6 required sections | ✅ | 2026-03-28 | |
| T2 | `configs/templates/VERIFY-backend.md` exists and contains all 6 required sections | ✅ | 2026-03-28 | |
| T3 | `configs/templates/VERIFY-ai.md` exists and contains all 6 required sections | ✅ | 2026-03-28 | |
| T4 | `configs/templates/loop-goal.md` exists (loop skill depends on it) | ✅ | 2026-03-28 | |
| T5 | `configs/templates/CLAUDE.md` project template exists | ✅ | 2026-03-28 | |

## Skills Quality
<!-- Each skill must have a valid prompt.md and SKILL.md. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SK1 | Every dir in `configs/skills/` contains `prompt.md` | ✅ | 2026-04-10 | all 29 skill dirs have prompt.md |
| SK2 | `/review` skill: prompt.md contains all 7 steps and convergence condition | ✅ | 2026-04-10 | |
| SK3 | `/verify` skill: prompt.md contains VERIFY.md coverage section and `VERIFY_COVERAGE` footer field | ✅ | 2026-04-10 | |
| SK4 | `/commit` skill: references `committer` script; `git add .` only appears in prohibition rule | ✅ | 2026-04-10 | |
| SK5 | `/investigate` skill: contains Iron Law, 3-strike rule, Blast Radius Gate, and structured DEBUG REPORT format | ✅ | 2026-04-10 | |
| SK6 | `/cso` skill: contains OWASP Top 10, STRIDE threat model, and false-positive filter | ✅ | 2026-04-10 | |
| SK7 | `/retro` skill: reads git history via parallel bash commands; outputs metrics table + narrative | ✅ | 2026-04-10 | |
| SK8 | `/document-release` skill: covers README audit, CHANGELOG polish, and cross-doc consistency | ✅ | 2026-04-10 | |
| SK9 | `/provider` skill: references `provider-switch.sh`; API keys never stored in config files | ✅ | 2026-04-10 | |
| SK10 | 26/29 workflow skills have Completion Status footer (DONE/BLOCKED/NEEDS_CONTEXT/DONE_WITH_CONCERNS) | ✅ | 2026-04-10 | 0 missing (3 utility skills exempt: brief, minimax-usage, slt) |

---

## Known Limitations (⚠)

| ID | Checkpoint | Status | Notes |
|----|-----------|--------|-------|
| KL1 | Guardian false-positive when blocked pattern appears inline with a command (not a pure assignment) | ⚠ | Fixed 2026-03-30: SCANNABLE strips `VAR='...'` and `VAR="..."` lines. Residual edge case: `ENV_VAR="..." migration-cmd` on one line not stripped (rare). Use base64-decode trick for guardian tests. |
| KL2 | `/commit`, `/loop`, `/start` skills cannot be fully E2E tested without actual uncommitted changes or a running background loop | ⚠ | Skill prompt content verified; runtime behavior requires manual spot-check |
| KL3 | Orchestrator API endpoint behavior untested (no running server in this review session) | ⚠ | Python syntax + tests pass. API routes require `uvicorn server:app` running |
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

---
<!-- Add new checkpoints above this line. /review appends discovered scenarios here automatically. -->
