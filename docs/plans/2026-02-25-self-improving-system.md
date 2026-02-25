# Plan: Self-Improving Claude Code System

**Date**: 2026-02-25
**Status**: Draft → Ready for implementation
**Context**: Claude Code Kit already has 70% of the infrastructure. This plan closes the automation gaps to create a true closed-loop learning system.

---

## Architecture: The Training Loop

```
                         ┌─────────────────────────────────────┐
                         │         SIGNAL CAPTURE              │
                         │                                     │
                         │  Explicit ──► correction-detector   │
                         │  Implicit ──► edit-shadow-detector  │  ◄── NEW
                         │  Systemic ──► stats-aggregator      │  ◄── NEW
                         └──────────────┬──────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────────────┐
                         │       PATTERN RECOGNITION           │
                         │                                     │
                         │  history.jsonl ──► stats.json       │  ◄── NEW (cron)
                         │  Cluster similar corrections        │  ◄── NEW
                         │  Detect rule candidates             │
                         └──────────────┬──────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────────────┐
                         │        RULE LIFECYCLE               │
                         │                                     │
                         │  candidate → rules.md (auto)        │  EXISTS
                         │  rules.md → /audit (scheduled)      │  ◄── NEW
                         │  PROMOTE → CLAUDE.md (auto-insert)  │  ◄── NEW
                         │  RETIRE → archive (age/contradict)  │  ◄── NEW
                         └──────────────┬──────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────────────┐
                         │        EVALUATION                   │
                         │                                     │
                         │  Session scorecard (auto)           │  ◄── NEW
                         │  Correction rate trend              │  ◄── NEW
                         │  Rule effectiveness tracking        │  ◄── NEW
                         └─────────────────────────────────────┘
```

---

## 1. Signal Taxonomy

| Signal | Type | Capture Method | Confidence | Volume |
|--------|------|---------------|------------|--------|
| User says "wrong/revert/不要" | Explicit | correction-detector.sh regex | HIGH | ~5/day |
| User edits file Claude just wrote | Implicit | NEW: PostToolUse diff comparison | MEDIUM | ~20/day |
| User reverts a commit | Implicit | NEW: git reflog monitor | HIGH | ~2/day |
| Type-check fails after edit | Systemic | post-edit-check.sh (EXISTS) | HIGH | ~10/day |
| Task completion blocked | Systemic | verify-task-completed.sh (EXISTS) | HIGH | ~3/day |
| Hook blocks a command | Systemic | pre-tool-guardian.sh (EXISTS) | HIGH | ~1/day |
| User manually runs a command Claude should have | Implicit | NEW: Bash command pattern analysis | LOW | ~5/day |

---

## 2. Rule Lifecycle

```
Raw Signal ──► Candidate Rule ──► Validated Rule ──► CLAUDE.md Principle ──► Hook Enforcement
   (auto)         (auto)           (7 days)           (14+ days)             (30+ days)
                                   /audit weekly       /audit promotes        manual review
```

### Graduation Criteria
- **candidate → validated**: Rule survives 7 days without contradiction, triggered 2+ times
- **validated → CLAUDE.md**: Rule is 14+ days old, general (not project-specific), /audit marks PROMOTE
- **CLAUDE.md → hook**: Rule violation is high-impact and detectable programmatically

### Retirement Criteria
- Rule contradicted by newer rule → archive with reason
- Rule not triggered for 60 days → mark stale, remove on next /audit
- Rule superseded by CLAUDE.md principle → REDUNDANT, remove
- Max 50 rules in rules.md (FIFO eviction already exists)

---

## 3. Eval Framework

### Session Scorecard (auto-generated at session end)

```json
{
  "session_id": "abc123",
  "date": "2026-02-25",
  "metrics": {
    "corrections_received": 2,
    "files_user_edited_after_claude": 1,
    "commits_reverted": 0,
    "type_check_failures": 3,
    "commands_blocked_by_hooks": 0,
    "tasks_completed": 5,
    "tasks_failed": 1
  },
  "score": 0.78,
  "trend": "improving"
}
```

### Tracked Metrics (weekly trend)
1. **Correction rate** = corrections / total user messages (lower = better)
2. **Self-fix rate** = type errors caught by hooks / total type errors (higher = better)
3. **First-attempt success** = tasks completed without retry / total tasks
4. **Rule trigger rate** = times a correction matches an existing rule domain (lower = rules working)

### Storage
- `~/.claude/corrections/scorecards.jsonl` — one entry per session
- `~/.claude/corrections/weekly-report.md` — generated by /audit, human-readable trend

---

## 4. Implementation Roadmap

### Phase 1: Quick Wins (< 1 day each)

#### 1a. Auto-populate stats.json
- **File**: `configs/hooks/correction-detector.sh`
- **Change**: After logging to history.jsonl, also increment domain counter in stats.json
- **How**: Detect domain from `$CLAUDE_PROJECT_DIR` + recent git diff file extensions (same logic as verify-task-completed.sh)
- **Effect**: Adaptive quality gates start working immediately

#### 1b. Session scorecard generator
- **File**: NEW `configs/scripts/session-scorecard.sh`
- **Trigger**: Called by `/sync` skill at session end (add one line to sync/prompt.md)
- **How**: Parse history.jsonl (last session), count type-check warnings from logs, compute metrics
- **Output**: Append to `~/.claude/corrections/scorecards.jsonl`

#### 1c. Scheduled /audit via cron-like hook
- **File**: `configs/hooks/session-context.sh`
- **Change**: At session start, check `~/.claude/corrections/.last-audit` timestamp. If >7 days old, inject "Run /audit before starting work — your corrections are due for review" into session context.
- **Effect**: Audit becomes semi-automatic (nudge, not forced)

#### 1d. Auto-promote in /audit skill
- **File**: `configs/skills/audit/prompt.md`
- **Change**: After classification, if PROMOTE rules exist, auto-append them to the appropriate CLAUDE.md section (with `[auto-promoted YYYY-MM-DD]` tag). Remove from rules.md. Update `.last-audit`.
- **Effect**: Rule graduation becomes one-click instead of manual copy-paste

### Phase 2: Medium Effort (1-3 days each)

#### 2a. Implicit signal: edit-shadow detector
- **File**: NEW `configs/hooks/edit-shadow-detector.sh`
- **Trigger**: PostToolUse on Edit|Write (same as post-edit-check)
- **How**: Record `{file, timestamp, tool}` to `/tmp/claude-edits-$SESSION.jsonl`. On next UserPromptSubmit, check if user's message references a file Claude recently edited OR if user uses Edit tool on same file → log as implicit correction.
- **Limitation**: Only catches edits within same session. Good enough for v1.

#### 2b. Implicit signal: revert detector
- **File**: NEW `configs/hooks/revert-detector.sh`
- **Trigger**: PreToolUse on Bash
- **How**: If command matches `git revert|git reset|git checkout -- ` patterns, log as implicit correction with the reverted commit message as context
- **Output**: Log to history.jsonl with `"type": "implicit-revert"`

#### 2c. Stats dashboard in /audit
- **File**: `configs/skills/audit/prompt.md`
- **Change**: Before classification, read scorecards.jsonl and show weekly trend:
  ```
  Weekly Trend (last 4 weeks):
    Correction rate:  0.12 → 0.09 → 0.08 → 0.06  ↓ improving
    First-attempt:    0.72 → 0.75 → 0.80 → 0.83  ↑ improving
  ```
- **Effect**: Concrete evidence of improvement (or regression)

#### 2d. Rule dedup and clustering
- **File**: `configs/scripts/rule-cluster.sh`
- **How**: Simple text similarity (shared domain + root-cause → same cluster). When 3+ rules share a cluster, suggest a generalized principle.
- **Called by**: /audit skill before classification
- **Example**: 3 rules about "overflow clipping CSS" → generalize to "Never use overflow-hidden on containers with absolute-positioned children"

### Phase 3: Long-term (ongoing)

#### 3a. Cross-project learning
- **Mechanism**: /audit checks both project-specific `corrections/rules.md` AND global `~/.claude/corrections/rules.md`. Rules that appear in 2+ projects get promoted to global.
- **File changes**: audit/prompt.md, session-context.sh (load global rules alongside project rules)

#### 3b. Memory integration
- **File**: `configs/skills/sync/prompt.md`
- **Change**: At session end (/sync), if significant learnings occurred (new rules, resolved blockers), auto-write a summary to project memory file.
- **File**: `configs/hooks/session-context.sh`
- **Change**: Load `memory/MEMORY.md` at session start alongside corrections.

#### 3c. A/B rule testing (shadow mode)
- **Mechanism**: New rules added with `[shadow]` tag. Corrections are logged against shadow rules but rules aren't shown to Claude. After 14 days, compare correction rate with/without rule → auto-promote or discard.
- **Complexity**: Requires splitting sessions into "with rule" and "without rule" groups. May be overkill for single-user setup.

#### 3d. Hook-level enforcement for mature rules
- **Example**: Rule "never use overflow-hidden on popover containers" → becomes a PostToolUse hook that greps edited CSS files for the pattern and warns.
- **Process**: Manual review required. Not all rules are enforceable as hooks. Focus on rules that are: high-frequency, detectable by regex, high-impact.

---

## 5. Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | Mitigation |
|-------------|-------------|------------|
| **Rule explosion** (>50 rules) | Context window bloat, contradictions | FIFO eviction (exists), /audit graduation |
| **Overfitting to one user** | Rules become personal quirks, not general patterns | Cross-project validation, 14-day cool-off |
| **False positive hooks** | Block legitimate actions, create frustration | Fail-open for LLM hooks (exists), warn-only mode for new hooks |
| **Stale rules** | Old rules conflict with evolved codebase | 60-day expiry, automatic staleness detection |
| **Measuring the wrong thing** | Optimizing correction count → Claude avoids risky but useful suggestions | Score "first-attempt success" not just "corrections avoided" |
| **Context window bloat** | Loading all rules + stats + memory + handoff = no room for actual code | Budget: rules ≤50 lines, memory ≤200 lines, scorecard = 1 line summary |
| **Premature hook promotion** | Turning a 2-day-old rule into a blocking hook | 30-day minimum + manual review for hooks |

---

## 6. File Change Summary

### New Files
| File | Purpose | Phase |
|------|---------|-------|
| `configs/scripts/session-scorecard.sh` | Generate session metrics at end | 1b |
| `configs/hooks/edit-shadow-detector.sh` | Detect implicit corrections (user edits Claude's work) | 2a |
| `configs/hooks/revert-detector.sh` | Detect git reverts as implicit corrections | 2b |
| `configs/scripts/rule-cluster.sh` | Cluster similar rules for generalization | 2d |

### Modified Files
| File | Change | Phase |
|------|--------|-------|
| `configs/hooks/correction-detector.sh` | Add stats.json auto-increment | 1a |
| `configs/hooks/session-context.sh` | Add audit nudge (7-day check) + memory loading | 1c, 3b |
| `configs/skills/audit/prompt.md` | Add auto-promote + trend dashboard + clustering | 1d, 2c, 2d |
| `configs/skills/sync/prompt.md` | Add scorecard generation + memory write | 1b, 3b |
| `configs/settings-hooks.json` | Wire new hooks (edit-shadow, revert-detector) | 2a, 2b |
| `templates/corrections/stats.json` | No change (already correct structure) | — |

### Unchanged (leverage as-is)
- `configs/hooks/pre-tool-guardian.sh` — already captures blocked commands
- `configs/hooks/post-edit-check.sh` — already captures type errors
- `configs/hooks/verify-task-completed.sh` — already uses stats.json
- `configs/scripts/committer.sh` — no change needed
- `templates/CLAUDE.md` — updated via /audit auto-promote, not manually

---

## 7. Verification Steps

After each phase, verify:

1. **Phase 1**:
   - `cat ~/.claude/corrections/stats.json` shows non-zero counts after a coding session
   - `cat ~/.claude/corrections/scorecards.jsonl` has entries after /sync
   - Session start shows "audit nudge" if >7 days since last audit
   - /audit auto-promotes a rule and it appears in CLAUDE.md

2. **Phase 2**:
   - Edit a file, then manually edit same file → history.jsonl shows implicit correction
   - Run `git revert HEAD` → history.jsonl shows revert entry
   - /audit shows weekly trend chart
   - 3 similar rules → /audit suggests generalization

3. **Phase 3**:
   - Rule from project A appears in project B's session context (cross-project)
   - /sync writes meaningful summary to memory/MEMORY.md
   - Shadow rules accumulate data without affecting sessions

---

## Self-Challenge Notes

- **Necessity**: Phase 1 items are all <50 lines of bash each. Phase 3c (A/B testing) might be overkill for single user — defer.
- **Blind spot**: edit-shadow-detector relies on session-local temp files; won't work across session restarts. Acceptable for v1.
- **Boundary**: stats.json domain detection reuses verify-task-completed.sh logic — keep DRY by extracting to lib/.
- **Simplest approach**: Phase 1 is all "add 10-20 lines to existing files." No new abstractions. Good.
- **Rollback**: Every change is additive (new hooks, new fields). Nothing breaks if reverted.
