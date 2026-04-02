Generate a concise morning briefing for the current project. Follow these steps:

1. Run `git log --since="18 hours ago" --oneline` to get recent commits.
2. Run `git log --since="18 hours ago" --format="%s" | wc -l` to count commits.
3. Check if the orchestrator is running: `curl -s http://localhost:4000/api/sessions/overview 2>/dev/null`
   - If running and returns valid JSON: extract pending/running/done/failed counts and total_cost for each session.
   - If not running or returns an error: skip API data, note orchestrator offline.
4. If PROGRESS.md exists, read its last 2000 characters to find the most recent lesson entry.
5. Read TODO.md to find the next 3 open `- [ ]` items.

Then output a concise markdown briefing with exactly these sections:

## Overnight Activity
- Number of commits in the last 18 hours
- Most recent 5 commit messages (one per line)

## Queue Status
- Pending / Running / Done / Failed counts (from orchestrator if available, else "Orchestrator offline")
- Total cost if available (format: $X.XX)

## Recent Lessons
- The last lesson from PROGRESS.md (one paragraph max). If PROGRESS.md missing: "(no PROGRESS.md found)"

## Suggested Next Actions
1. First open TODO item
2. Second open TODO item
3. Third open TODO item
4. One improvement suggestion based on recent commits or lessons (be specific, not generic)

Keep the entire briefing under 40 lines. Be specific and actionable. Do not pad with filler text.
