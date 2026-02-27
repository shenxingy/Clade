# Goal: Implement Self-Improving System — Phase 1 + Phase 2

Implement the plan from `docs/plans/2026-02-25-self-improving-system.md`.
Focus on Phase 1 (quick wins) and Phase 2 (medium effort).

## Phase 1: Quick Wins

### 1a. Auto-populate stats.json
- [x] In `configs/hooks/correction-detector.sh`: after logging to history.jsonl, also increment the domain counter in `~/.claude/corrections/stats.json`
- [x] Domain detection logic: check `$CLAUDE_PROJECT_DIR` for recent git diff file extensions → map to domain (frontend/backend/ml/schema/systems/academic/unknown)
- [x] Extract domain-detection into a shared function in `configs/hooks/lib/domain-detect.sh` (reuse same logic as verify-task-completed.sh)
- [x] Verify: after a correction is detected, `cat ~/.claude/corrections/stats.json` shows incremented count

### 1b. Session scorecard generator
- [x] Create `configs/scripts/session-scorecard.sh` — generates session metrics
- [x] Reads: history.jsonl (entries from current session, by timestamp), counts corrections
- [x] Reads: recent git log for revert patterns
- [x] Outputs: one JSON line appended to `~/.claude/corrections/scorecards.jsonl`
- [x] Format: `{"date":"2026-02-25","session_id":"...","corrections":2,"implicit_corrections":0,"type_errors":3,"tasks_completed":5,"score":0.78}`
- [x] Add call to session-scorecard.sh in `configs/skills/sync/prompt.md` (run before doc updates)
- [x] Verify: after running /sync, scorecards.jsonl has a new entry

### 1c. Audit nudge at session start
- [x] In `configs/hooks/session-context.sh`: check if `~/.claude/corrections/.last-audit` is older than 7 days (or missing)
- [x] If stale: inject "Your correction rules haven't been audited in 7+ days. Consider running /audit to graduate mature rules." into session context
- [x] `/audit` skill should touch `.last-audit` after completing
- [x] Verify: delete .last-audit, start a new session → see the nudge

### 1d. Auto-promote in /audit
- [x] Update `configs/skills/audit/prompt.md`: after identifying PROMOTE rules, auto-append them to the appropriate section in `~/.claude/CLAUDE.md` with tag `[auto-promoted YYYY-MM-DD]`
- [x] Remove promoted rules from rules.md
- [x] Touch `~/.claude/corrections/.last-audit` with current timestamp
- [x] Verify: create a test rule dated 15 days ago, run /audit → rule appears in CLAUDE.md, removed from rules.md

## Phase 2: Medium Effort

### 2a. Implicit signal: edit-shadow detector
- [x] Create `configs/hooks/edit-shadow-detector.sh` — triggered by PostToolUse on Edit|Write
- [x] On each Claude edit: record `{file, timestamp}` to `/tmp/claude-edit-shadow-$$.jsonl`
- [x] Create companion check in correction-detector.sh: on UserPromptSubmit, check if user's message references a recently-edited file (within last 5 minutes) AND contains edit-like language → log as implicit correction with `"type":"implicit-edit"` in history.jsonl
- [x] Wire in `configs/settings-hooks.json`: add to PostToolUse matcher alongside post-edit-check
- [x] Verify: Claude edits a file, user says "actually change X in that file" → history.jsonl shows implicit entry

### 2b. Implicit signal: revert detector
- [x] Create `configs/hooks/revert-detector.sh` — triggered by PreToolUse on Bash
- [x] Detect patterns: `git revert`, `git reset --hard`, `git checkout -- <file>`, `git restore <file>`
- [x] On match: extract the target (commit hash or file path), log to history.jsonl with `"type":"implicit-revert"`
- [x] Wire in `configs/settings-hooks.json`: add to PreToolUse matcher alongside pre-tool-guardian
- [x] Verify: run `git revert HEAD` → history.jsonl shows revert entry

### 2c. Stats dashboard in /audit
- [x] Update `configs/skills/audit/prompt.md`: before rule classification, read scorecards.jsonl and compute weekly trends
- [x] Display: correction rate, first-attempt success rate, trend direction (↑/↓)
- [x] Show last 4 data points for trend visualization
- [x] Verify: populate scorecards.jsonl with test data, run /audit → trend chart appears

### 2d. Rule dedup and clustering
- [x] Create `configs/scripts/rule-cluster.sh` — groups rules by domain + root-cause
- [x] When 3+ rules share same domain: suggest a generalized principle
- [x] Output: suggested generalizations for /audit to present
- [x] Called by /audit skill before classification
- [x] Verify: add 3 rules with same domain, run /audit → generalization suggested

## Constraints

- All new bash scripts must use `set -euo pipefail` and `#!/usr/bin/env bash`
- All new hooks must output valid JSON (use jq)
- New hooks must fail-open (exit 0 on errors, not exit 2)
- Keep each new file under 100 lines
- Reuse lib/typecheck.sh pattern for shared code
- Use committer for all commits (NEVER git add .)
- Run install.sh after changes to verify deployment works

## Success criteria

- `bash install.sh` completes without errors
- All 4 Phase 1 items produce verifiable output
- All 4 Phase 2 items produce verifiable output
- No existing hook behavior is broken (session-context, correction-detector, guardian, post-edit-check, verify-task all still work)
