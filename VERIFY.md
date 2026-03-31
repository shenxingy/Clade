# VERIFY — Clade
<!-- Managed by /review skill. Edit checkpoint descriptions freely; statuses are updated by the agent. -->
<!-- Legend: ✅ pass  ❌ fail  ⚠ known limitation  ⬜ not yet tested -->

**Project type:** cli + skill-system + orchestrator (FastAPI)
**Last full pass:** 2026-03-30
**Coverage:** 44 ✅, 0 ❌, 3 ⚠, 0 ⬜ untested

---

## Install & CLI Setup
<!-- Running install.sh should produce a working local Claude Code setup. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| I1 | `./install.sh` runs without errors — no missing source files, no broken symlinks | ✅ | 2026-03-30 | 29 config skills + 3 userSettings = 32 total installed |
| I2 | All skills from `configs/skills/` are installed to `~/.claude/skills/` | ✅ | 2026-03-30 | all 29 skills including 4 new ones (investigate, cso, retro, document-release) |
| I3 | All hooks from `configs/hooks/` are installed to `~/.claude/hooks/` | ✅ | 2026-03-28 | |
| I4 | All scripts from `configs/scripts/` are installed to `~/.claude/scripts/` | ✅ | 2026-03-28 | spot-checked key scripts |
| I5 | All templates from `configs/templates/` are installed to `~/.claude/templates/` | ✅ | 2026-03-28 | |
| I6 | `~/.local/bin/slt` symlink exists and points to `statusline-toggle.sh` | ✅ | 2026-03-28 | |
| I7 | `~/.local/bin/committer` symlink exists and points to `committer.sh` | ✅ | 2026-03-28 | |
| I8 | `~/.local/bin/devmode` symlink exists and points to `devmode.sh` | ✅ | 2026-03-28 | |

## Behavior Anchors (CLAUDE.md `## Features`)
<!-- Each anchor must work end-to-end. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| B1 | `slt` command runs without error; output changes on repeated calls (symbol→percent→number→off→…) | ✅ | 2026-03-28 | |
| B2 | `committer "type: msg" file1 file2` stages only the named files and commits — does not stage unstaged files nearby | ✅ | 2026-03-28 | tested with bystander file in temp repo |
| B3 | `devmode` toggles `~/.claude/.dev-mode` flag; `devmode on/off/status` work as expected | ✅ | 2026-03-28 | |
| B4 | `/commit` skill prompt contains: analyze → split by module → confirm → commit → push flow | ✅ | 2026-03-28 | all 4 keywords present |
| B5 | `/loop` skill prompt contains: goal file input → supervisor plans → workers execute → convergence check | ✅ | 2026-03-28 | |
| B6 | `/review` skill prompt contains: VERIFY.md load → checkpoint loop → fix-in-session → convergence | ✅ | 2026-03-28 | |
| B7 | `loop-runner.sh` exists, is executable, and passes `bash -n` syntax check | ✅ | 2026-03-28 | |

## Hook Behavior
<!-- Hooks must fire correctly and not over-block. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| H1 | `pre-tool-guardian.sh` passes `bash -n` syntax check | ✅ | 2026-03-30 | |
| H2 | `pre-tool-guardian.sh` blocks `alembic upgrade` when dev-mode is OFF | ✅ | 2026-03-30 | tested via base64-decoded command |
| H3 | `pre-tool-guardian.sh` allows `alembic upgrade` when dev-mode is ON | ✅ | 2026-03-30 | |
| H4 | `pre-tool-guardian.sh` blocks `rm -rf /` regardless of dev-mode | ✅ | 2026-03-30 | |
| H5 | `pre-tool-guardian.sh` blocks `git push --force origin main` regardless of dev-mode | ✅ | 2026-03-30 | |
| H6 | All other hooks pass `bash -n` syntax check | ✅ | 2026-03-30 | all 12 hooks pass |
| H7 | `pre-tool-guardian.sh` does NOT block when migration pattern appears only in a variable assignment string (false-positive fix) | ✅ | 2026-03-30 | `INPUT='...alembic upgrade...'` now allowed |

## Shell Script Integrity
<!-- All scripts must be syntactically valid. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SH1 | All `configs/hooks/*.sh` pass `bash -n` | ✅ | 2026-03-30 | all 12 hooks |
| SH2 | All `configs/scripts/*.sh` pass `bash -n` | ✅ | 2026-03-30 | all 27 scripts pass (incl. provider-switch.sh) |
| SH3 | `install.sh` passes `bash -n` | ✅ | 2026-03-30 | |

## Orchestrator — Python Syntax & Tests
<!-- The orchestrator Python modules must compile and pass tests. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| PY1 | All Python modules pass `python -m py_compile` (full list from CLAUDE.md) | ✅ | 2026-03-30 | all 15 modules |
| PY2 | `pytest tests/` passes with zero failures | ✅ | 2026-03-30 | 19/19 passed in 2.00s |
| PY3 | No circular imports — `python -c "import server"` runs without ImportError | ✅ | 2026-03-30 | |

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
| SK1 | Every dir in `configs/skills/` contains `prompt.md` | ✅ | 2026-03-30 | all 29 skill dirs (incl. 4 new: investigate, cso, retro, document-release) |
| SK2 | `/review` skill: prompt.md contains all 7 steps and convergence condition | ✅ | 2026-03-30 | |
| SK3 | `/verify` skill: prompt.md contains VERIFY.md coverage section and `VERIFY_COVERAGE` footer field | ✅ | 2026-03-30 | |
| SK4 | `/commit` skill: references `committer` script; `git add .` only appears in prohibition rule | ✅ | 2026-03-30 | also has scope drift check (Step 3.5b) |
| SK5 | `/investigate` skill: contains Iron Law, 3-strike rule, Blast Radius Gate, and structured DEBUG REPORT format | ✅ | 2026-03-30 | |
| SK6 | `/cso` skill: contains OWASP Top 10, STRIDE threat model, and false-positive filter | ✅ | 2026-03-30 | |
| SK7 | `/retro` skill: reads git history via parallel bash commands; outputs metrics table + narrative | ✅ | 2026-03-30 | |
| SK8 | `/document-release` skill: covers README audit, CHANGELOG polish, and cross-doc consistency | ✅ | 2026-03-30 | |
| SK9 | `/provider` skill: references `provider-switch.sh`; API keys never stored in config files | ✅ | 2026-03-30 | |
| SK10 | 26/29 workflow skills have Completion Status footer (DONE/BLOCKED/NEEDS_CONTEXT/DONE_WITH_CONCERNS) | ✅ | 2026-03-30 | 3 utility skills exempt: brief, minimax-usage, slt |

---

## Known Limitations (⚠)

| ID | Checkpoint | Status | Notes |
|----|-----------|--------|-------|
| KL1 | Guardian false-positive when blocked pattern appears inline with a command (not a pure assignment) | ⚠ | Fixed 2026-03-30: SCANNABLE strips `VAR='...'` and `VAR="..."` lines. Residual edge case: `ENV_VAR="..." migration-cmd` on one line not stripped (rare). Use base64-decode trick for guardian tests. |
| KL2 | `/commit`, `/loop`, `/start` skills cannot be fully E2E tested without actual uncommitted changes or a running background loop | ⚠ | Skill prompt content verified; runtime behavior requires manual spot-check |
| KL3 | Orchestrator API endpoint behavior untested (no running server in this review session) | ⚠ | Python syntax + tests pass. API routes require `uvicorn server:app` running |

---
<!-- Add new checkpoints above this line. /review appends discovered scenarios here automatically. -->
