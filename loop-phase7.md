# Goal: Implement Phase 7.1 and 7.2 — Task Velocity Engine (CLI Layer)

## Context

This repo is a Claude Code automation kit. We want to maximize commits/day by enforcing
per-file commit discipline at the hook level and adding CLI tooling for parallel task dispatch.

All tasks are clearly specified in TODO.md under "Phase 7 — Task Velocity Engine".

## Requirements

### 7.1 Hook Layer

1. **Commit reminder hook** — extend `configs/hooks/post-edit-check.sh`:
   - Count uncommitted files via `git diff --name-only HEAD | wc -l`
   - If count >= COMMIT_REMINDER_THRESHOLD (default 2), append to stdout:
     `systemMessage: "⚠ {N} files edited without commit — run: committer \"type: desc\" file1 file2"`
   - Must NOT block (no exit 1/2), must NOT change existing behavior

2. **CLAUDE.md per-file rule** — update `configs/templates/CLAUDE.md`:
   - In the Commits section, add rule:
     `"After modifying each file, commit immediately with committer before opening the next file. Never batch file edits into one commit."`

### 7.2 CLI/TUI Velocity

3. **scan-todos.sh** — create `configs/scripts/scan-todos.sh`:
   - Usage: `bash scan-todos.sh [project-dir] >> tasks.txt`
   - Scan for `TODO:|FIXME:|HACK:|XXX:` comments recursively (skip .git, node_modules)
   - Output `===TASK===` blocks compatible with batch-tasks format
   - Each block: `model: haiku\ntimeout: 600\n---\nfix(todo): {comment} in {file}:{line}\n\nFile: {file}\nLine: {line}\nComment: {comment}\n\nFix the TODO comment by implementing it properly.`
   - Dedup: skip if same file+line already in tasks.txt

4. **tmux-dispatch.sh** — create `configs/scripts/tmux-dispatch.sh`:
   - Usage: `bash tmux-dispatch.sh tasks.txt [--workers N]`
   - Create tmux session `claude-fleet` with N panes (default 4)
   - Each pane runs: `claude --dangerously-skip-permissions -p "{task_prompt}"`
   - Use flock on a counter file for atomic task assignment (each pane picks next task)
   - When a pane finishes, it picks the next task from the queue automatically
   - Print summary at end: `X success / Y failed / Z total`
   - If tmux not available, fall back to running tasks sequentially

## Success Criteria

- `bash configs/hooks/post-edit-check.sh` runs without error
- `bash configs/scripts/scan-todos.sh --help` or with no args prints usage
- `bash configs/scripts/tmux-dispatch.sh --help` or with no args prints usage
- `configs/templates/CLAUDE.md` contains the per-file commit rule
- All new scripts have `set -euo pipefail` and handle edge cases (empty input, missing deps)
- All changes committed with committer

## Notes

- `configs/hooks/post-edit-check.sh` already exists — extend it, do not replace it
- `configs/templates/CLAUDE.md` already exists — read it first before editing
- Scripts should work on bash 4+ (macOS and Linux)
- Use `===TASK===` format (3 equals signs) to match batch-tasks parser
