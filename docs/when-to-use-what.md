**English** | [中文](when-to-use-what.zh-CN.md)

[Back to README](../README.md)

# When to Use What

Detailed guidance for choosing the right Clade skill for your situation.

## Table of Contents

1. [Direct Prompts](#direct-prompts)
2. [Research & Planning](#research--planning)
3. [Task Execution](#task-execution)
4. [Code Quality](#code-quality)
5. [Session Management](#session-management)
6. [System Maintenance](#system-maintenance)

---

## Direct Prompts

For most day-to-day work — bug fixes, small features, refactoring, codebase questions. Claude auto-detects complexity and enters plan mode when needed.

**Tip:** Be specific. "Add retry with exponential backoff to the API client" > "improve the API client".

## Research & Planning

### `/research TOPIC`
**When:** Before starting a complex feature or choosing a library.
- Searches the web, synthesizes findings, saves to `docs/research/<topic>.md`
- Useful for competitive analysis, API evaluation, architecture decisions
- Run before `/orchestrate` so the plan is grounded in real data

### `/model-research`
**When:** New Claude models drop, or periodically.
- Searches for latest benchmarks, pricing, and capability changes
- `--apply` updates the model guide, session context, and batch-tasks configs automatically

### `/next`
**When:** Wondering what to work on next.
- **Fast mode (default):** reads docs + git state, gives a one-shot top-pick + runner-up in ≤15 lines, no questions asked. Right for casual "下一步做什么" / "what's next?" queries.
- **Deep mode (`/next deep`):** multi-round interview from different angles — surfaces the best move when priorities are genuinely unclear and you want to think it through.
- Default to fast; escalate to deep only if the fast pick doesn't feel right.

### `/orchestrate`
**When:** Using the Orchestrator Web UI to plan large work.
- Asks clarifying questions, decomposes goal into tasks, writes `proposed-tasks.md`
- Workers pick up tasks from there; run inside the Web UI for best experience
- Better than `/batch-tasks` when the scope isn't fully defined yet

### `/map`
**When:** Onboarding to an unfamiliar codebase, or before dispatching agents.
- Generates file ownership map (from git log), module dependency graph, entry points
- Saved as `.claude/AGENTS.md` — workers read this to avoid stepping on each other
- Run once at project start, re-run after major refactors

## Task Execution

### `/batch-tasks`
**When:** You have a structured TODO list.
- Multi-step implementations broken into discrete tasks
- Use `--parallel` when tasks don't share files
- Well-defined TODO.md entries get high scout scores; vague tasks may be skipped

### `/loop GOAL_FILE`
**When:** You want Claude to keep iterating until a goal is met.
- Supervisor plans tasks each iteration, workers execute in parallel via git worktrees
- Runs unattended — leave it overnight, check results in the morning
- Write a clear goal file first; vague goals produce endless loops

### `/worktree`
**When:** Running parallel Claude Code sessions on the same repo.
- Creates an isolated git worktree with its own branch so sessions don't conflict
- Useful for working on two features simultaneously, or running a loop while also coding

### `/start`
**When:** Beginning an autonomous session.
- Default (no args): morning briefing — safe, read-only
- `--run`: full autonomous session — orchestrate → loop → verify → repeat
- `--goal goal.md`: targeted mode — skip orchestrate, use a goal file directly
- `--patrol`: scan all your projects without making changes
- `--research`: auto-generate research topics from TODO/GOALS/BRAINSTORM
- Budget (`--budget 10`), time (`--hours 8`), and iteration (`--max-iter 5`) limits for safety
- Resume with `--resume`; stop gracefully with `--stop`

## Code Quality

### `/review`
**When:** Before releases, after a long sprint, or onboarding to a codebase.
- **Finds and fixes** (not just reports): file size violations, lint errors, dead code, security issues, doc staleness
- 8 phases: doc health → goal alignment → code structure → lint → comments → bugs → security → UI
- Loops until clean — reruns after each fix pass, up to 3 iterations
- Remaining unfixed issues are written to `## Tech Debt` in TODO.md

### `/review-pr NUMBER`
**When:** Before merging a pull request.
- Reads the PR diff and posts a structured review comment (Critical / Warning / Suggestion)
- Faster than a full `/review` when you just need eyes on a specific change

### `/merge-pr NUMBER`
**When:** Ready to merge.
- Squash-merges the PR and deletes the feature branch
- Run after `/review-pr` gives the green light

### `/incident DESCRIPTION`
**When:** Something is broken in production.
- Diagnoses the issue, proposes a root cause, drafts a postmortem
- Adds follow-up tasks to TODO.md automatically
- Structured response is faster than free-form debugging under pressure

### `/investigate`
**When:** You hit a bug and need to find the root cause before fixing.
- Iron Rule: no fix without a confirmed hypothesis
- Uses scope lock and 3-strike escalation to prevent rabbit holes

### `/cso`
**When:** You need a security audit.
- Systematic OWASP + STRIDE review
- Covers attack surface, secrets archaeology, dependency supply chain, OWASP Top 10

## Session Management

### `/handoff`
**When:** Context is getting full (~80%) or before stopping work.
- Saves everything: what was done, what's pending, git state, exact next steps, gotchas
- Enables the next session (or a fresh overnight agent) to resume without human re-briefing

### `/pickup`
**When:** Starting a new session.
- Reads the latest handoff file and presents a concise briefing
- Verifies git state matches the handoff
- Immediately starts executing the first Next Step

### `/poke`
**When:** You hit `esc` during a long generation and want to confirm Claude isn't stuck.
- Prints a 3-line heartbeat: state (progressing/waiting/stuck/done), what it was doing, what's next
- Auto-continues if `progressing`; surfaces the block if `stuck` — never replans on its own
- Triggered by phrases like "卡住了吗" / "still working" / "are you stuck"

### `/status`
**When:** You started a background task / loop / agent earlier and want to check on it mid-session.
- Compact dashboard: in-conversation background handles, git state, orchestrator workers, recent PRs
- Different from `/brief` (overnight summary) and `/pickup` (resume from handoff) — `/status` is the "right now" view
- Triggered by "现在啥情况了" / "what's going on" / "session dashboard"

### `/go`
**When:** Claude offered enumerated options (A/B/C, 1/2/3) with a recommendation, and you want to accept the recommendation without re-reading every option.
- Scans the most recent assistant message for a recommendation marker, then executes immediately
- One-line confirmation, then act — saves you from typing "按推荐的来" each time
- Still confirms once for destructive actions (file delete, `git reset --hard`, force-push, migrations)

### `/commit`
**When:** Ready to commit.
- Analyzes all uncommitted changes, splits into logical commits by module
- Pushes by default; `--no-push` to skip, `--dry-run` to preview

### `/sync`
**When:** End of every coding session.
- Checks off completed TODO items, captures lessons in PROGRESS.md
- Run `/commit` after to commit everything split by module
- This builds institutional memory — skip it and you'll repeat past mistakes

### `/brief`
**When:** First thing in the morning after an overnight run.
- Shows commits from last 18h, queue status, recent lessons
- Lists next 3 open TODO items with one improvement suggestion

## System Maintenance

### `/audit`
**When:** Periodically, or when Claude ignores a rule.
- Finds rules in `corrections/rules.md` that should be promoted to CLAUDE.md or hooks
- Removes redundant or contradictory entries

### `/document-release`
**When:** After shipping a release.
- Updates README, CHANGELOG, CLAUDE.md, ARCHITECTURE, TODOs
- Ensures docs never drift from code

### `/pipeline`
**When:** Checking background pipeline health.
- Shows HEALTHY / DEGRADED / DEAD per project
- `watch` mode alerts on status changes via Telegram

### `slt`
**When:** Controlling the statusline display.
- `slt` cycles through modes: symbol → percent → number → off
- `slt theme` lists themes; `slt theme <name>` sets one
