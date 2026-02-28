# Goal: Phase 9 — Meta-Intelligence TUI Layer

## Context

Claude Code Kit is a bash+Python automation framework. CLI layer lives in `configs/` (installed to `~/.claude/`). The real scripts are in `~/.claude/scripts/` (especially `loop-runner.sh`). Goal: minimize human intervention by improving session startup context, loop intelligence, and kit completeness.

**North star:** System should run autonomously 8+ hours. Human sets direction, reviews results.

---

## Requirements

### 1. session-context.sh — Smart Warm-up
File: `configs/hooks/session-context.sh`

Read this file first. It already shows: recent commits, git status, branch, docker containers, handoff files.

Add TWO new sections after the existing git log block:

**Section A — Loop state:**
```
if [[ -f ".claude/loop-state" ]]; then
  CONVERGED=$(grep "^CONVERGED=" .claude/loop-state | cut -d= -f2)
  ITERATION=$(grep "^ITERATION=" .claude/loop-state | cut -d= -f2)
  GOAL=$(grep "^GOAL=" .claude/loop-state | cut -d= -f2 | xargs basename 2>/dev/null)
  if [[ "$CONVERGED" == "true" ]]; then
    CONTEXT+= "Loop: ✓ converged (${GOAL}, iter ${ITERATION})\n"
  elif [[ "$CONVERGED" == "false" ]]; then
    CONTEXT+= "Loop: ⟳ running (${GOAL}, iter ${ITERATION})\n"
  fi
fi
```

**Section B — Next TODO:**
Find the first `- [ ]` line in `TODO.md` (if exists) and add it to context:
```
NEXT_TODO=$(grep -m1 "^\- \[ \]" TODO.md 2>/dev/null | sed 's/- \[ \] \*\*//' | sed 's/\*\*.*//' | xargs)
if [[ -n "$NEXT_TODO" ]]; then
  CONTEXT+= "\nNext TODO: ${NEXT_TODO}\n"
fi
```

### 2. loop-runner.sh — Auto-PROGRESS on Convergence
File: `~/.claude/scripts/loop-runner.sh`

Read the file first (it's large). Find the block after `state_write CONVERGED true` (around line 292-295).

After convergence is written, add a call to write PROGRESS.md. Use a subshell to not block:

```bash
# Auto-write PROGRESS.md entry on convergence
_write_loop_progress() {
  local goal_name started iterations project_dir log_summary progress_file
  goal_name=$(basename "${GOAL_FILE}" .md)
  started=$(state_read STARTED "unknown")
  iterations="${iteration}"
  project_dir="${PROJECT_DIR:-$(pwd)}"
  progress_file="${project_dir}/PROGRESS.md"

  # Get commits since loop started
  log_summary=$(git -C "${project_dir}" log --oneline --since="${started}" 2>/dev/null | head -20 || echo "no commits found")

  if [[ -f "$progress_file" ]]; then
    local entry
    entry="### $(date '+%Y-%m-%d') — Loop: ${goal_name}\n\n**Iterations:** ${iterations}\n**Goal file:** ${GOAL_FILE}\n**Commits since start:**\n\`\`\`\n${log_summary}\n\`\`\`\n\n---\n\n"
    # Prepend entry after the first line (the # Progress Log header)
    local tmp
    tmp=$(mktemp)
    head -3 "$progress_file" > "$tmp"
    printf "%b" "$entry" >> "$tmp"
    tail -n +4 "$progress_file" >> "$tmp"
    mv "$tmp" "$progress_file"
  fi
}

( _write_loop_progress ) &
```

### 3. loop-runner.sh — Notify on Convergence/Interruption
File: `~/.claude/scripts/loop-runner.sh`

Find the notify-telegram script at `configs/hooks/notify-telegram.sh`. Check if `TELEGRAM_TOKEN` env var is set.

Add a `_notify_loop` function and call it on both CONVERGED and INTERRUPTED:

```bash
_notify_loop() {
  local status="$1" msg="$2"
  # Try project-local notify script first, then global
  local notify_script=""
  for candidate in "${PROJECT_DIR:-$(pwd)}/configs/hooks/notify-telegram.sh" \
                   "${HOME}/.claude/hooks/notify-telegram.sh"; do
    if [[ -f "$candidate" ]]; then notify_script="$candidate"; break; fi
  done
  [[ -z "$notify_script" ]] && return 0
  [[ -z "${TELEGRAM_TOKEN:-}" ]] && return 0
  bash "$notify_script" "$msg" 2>/dev/null &
}
```

Call on convergence: `_notify_loop "converged" "✓ Loop converged: $(basename $GOAL_FILE) in ${iteration} iterations"`
Call on interruption (in `_cleanup`): `_notify_loop "interrupted" "✗ Loop interrupted: $(basename $GOAL_FILE) at iter ${iteration:-?}"`

### 4. loop-runner.sh — HORIZONTAL Mode
File: `~/.claude/scripts/loop-runner.sh`

Read the GOAL_FILE parsing section. After `GOAL_FILE` is validated, add:

```bash
# Parse MODE from first 10 lines of goal file
LOOP_MODE=$(head -10 "$GOAL_FILE" | grep "^MODE:" | cut -d: -f2 | xargs)
LOOP_MODE="${LOOP_MODE:-VERTICAL}"
```

In the supervisor prompt construction, find where the supervisor is told how many tasks to plan. When `LOOP_MODE == "HORIZONTAL"`, change the instruction to allow up to 20 tasks and require each to touch exactly 1 file.

Also create `configs/templates/loop-goal.md` — a template showing all available fields:
```markdown
# Goal: [Short description]

MODE: VERTICAL   # VERTICAL (default, feature tasks) or HORIZONTAL (file-level micro-tasks, up to 20)

## Requirements
[Describe the desired end state]

## Success Criteria
[Testable conditions that define "done"]
```

### 5. loop-runner.sh — --exit-gate Flag
File: `~/.claude/scripts/loop-runner.sh`

Add to argument parsing section:
```bash
EXIT_GATE=""
# In the while loop parsing args:
--exit-gate) EXIT_GATE="$2"; shift 2 ;;
```

Find the convergence check block (where `STATUS: CONVERGED` is detected). Before accepting convergence, run the gate:

```bash
if echo "$SUPERVISOR_OUTPUT" | grep -q "STATUS: CONVERGED"; then
  if [[ -n "$EXIT_GATE" ]]; then
    echo "  Running exit gate: ${EXIT_GATE}"
    if eval "$EXIT_GATE" > /tmp/loop-gate-output 2>&1; then
      echo "  ✓ Exit gate passed"
      state_write CONVERGED true
      _notify_loop "converged" "..."
      break
    else
      echo "  ✗ Exit gate failed — continuing loop with failure context"
      GATE_FAILURE=$(cat /tmp/loop-gate-output | tail -20)
      # Inject gate failure into next iteration's supervisor context
      EXTRA_CONTEXT="Exit gate failed:\n${GATE_FAILURE}\nDo NOT output STATUS: CONVERGED until the exit gate passes."
    fi
  else
    state_write CONVERGED true
    break
  fi
fi
```

### 6. verify-task-completed.sh — Commit Granularity Stats [✓]
File: `configs/hooks/verify-task-completed.sh`

Read the file first. At the end of the script (before final exit), add commit ratio tracking:

```bash
# Track commit granularity (non-blocking stats)
_track_commit_granularity() {
  local files_changed commits_made ratio stats_file
  files_changed=$(git diff --name-only HEAD~${1:-1} HEAD 2>/dev/null | wc -l | tr -d ' ')
  commits_made=$(git log --oneline --since="1 hour ago" 2>/dev/null | wc -l | tr -d ' ')
  [[ "$files_changed" -eq 0 ]] && return 0
  ratio=$(echo "scale=2; $commits_made / $files_changed" | bc 2>/dev/null || echo "0")
  stats_file="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/stats.jsonl"
  mkdir -p "$(dirname "$stats_file")"
  echo "{\"date\":\"$(date -Iseconds)\",\"commits\":$commits_made,\"files\":$files_changed,\"ratio\":$ratio}" >> "$stats_file"
}
( _track_commit_granularity ) &
```

### 7. Kit Completeness — Copy Missing Skills
Copy these skills from `~/.claude/skills/` into `configs/skills/`:
- `review-pr` → `configs/skills/review-pr/`
- `merge-pr` → `configs/skills/merge-pr/`
- `worktree` → `configs/skills/worktree/`

Use: `cp -r ~/.claude/skills/review-pr configs/skills/` etc.

Then check `install.sh` to see if it installs all dirs in `configs/skills/` automatically or needs updating.

### 8. /research Skill
Create `configs/skills/research/prompt.md`

This skill helps automate Steps 1-5 of the planning workflow. When invoked with `/research [topic]`:

1. Read current `VISION.md`, `TODO.md`, and `BRAINSTORM.md` for project context
2. Use WebSearch to find 3-5 relevant tools/competitors/approaches for the topic
3. For each result: extract key features, pricing model, UX patterns, what they do well/poorly
4. Compare against current VISION.md — what gaps does this reveal? what can we borrow?
5. Write a structured entry to `BRAINSTORM.md`:

```markdown
## [Research] {date} — {topic}

### Tools surveyed
| Tool | Key features | What to borrow |
|---|---|---|
...

### Gaps vs current VISION
- ...

### Recommended additions to TODO.md
- [ ] ...
```

The skill prompt should instruct Claude to:
- Always read VISION.md first
- Always search with the current year (2026) for up-to-date results
- Be specific and actionable — no generic suggestions
- Mark as `[Research]` so BRAINSTORM.md entries are distinguishable from `[AI]` entries

---

## Success Criteria

- `bash configs/hooks/session-context.sh` (with mock input) shows loop state + next TODO
- `bash ~/.claude/scripts/loop-runner.sh --help` shows `--exit-gate` in usage
- `configs/templates/loop-goal.md` exists and documents MODE field
- `configs/skills/review-pr/`, `configs/skills/merge-pr/`, `configs/skills/worktree/` exist
- `configs/skills/research/prompt.md` exists and contains the skill description
- All script changes committed with `committer`

## Notes

- `~/.claude/scripts/loop-runner.sh` is a large file — read it fully before editing
- All bash changes must use `set -euo pipefail` style and handle empty/null cases
- Never use `exit 1/2` in hooks — they block Claude's tool use
- `bc` may not be installed — use fallback for ratio calculation
- Commit each file change separately using `committer "type: desc" filename`
