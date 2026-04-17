---
name: status
description: Session activity dashboard — lists background agents, /loop iterations, worktrees, orchestrator workers, unpushed commits, and recent PR activity. Use when the user asks "what's going on right now" mid-session.
when_to_use: "现在啥情况了, 现在什么状态, what's the status, what's going on, session dashboard, background activity, 后台跑到哪了 — asked mid-session when the user started something and came back to check"
user_invocable: true
---

# Status Skill

Show a compact dashboard of everything currently active in this session and its surroundings. Focus on **things the user started and forgot about**, not on docs or priorities.

## When this fires vs. related skills

| Skill | Scope |
|---|---|
| `/poke` | Heartbeat — "are you stuck right now?" (≤3 lines) |
| `/status` | Dashboard — "what's running in the background?" (this skill) |
| `/brief` | Overnight summary — "what ran while I was asleep?" |
| `/pickup` | New session — "resume the last handoff" |

Don't invoke `/next`, `/brief`, or `/pickup` from here — they're separate flows.

## What to check (in order — stop early if nothing active)

### 1. In-conversation background handles
- Background `Bash` processes launched with `run_in_background: true` this session
- `Agent` calls launched with `run_in_background: true`
- Active `/loop` or `/batch-tasks` invocations in this conversation

Check via the conversation history — these handles surface in prior tool results.

### 2. Local git state
```bash
git status -sb
git log --oneline @{upstream}..HEAD 2>/dev/null | head -5   # unpushed
git worktree list
```

### 3. Orchestrator layer (if running on this machine)
Probe `http://localhost:8000/health` (or project-specific port). If reachable:
- Active workers
- Running loops
- Recent task completions (last hour)

Skip silently if orchestrator isn't running — it's optional.

### 4. GitHub (only if user mentioned a PR recently)
```bash
gh pr list --author "@me" --state open --limit 5
gh run list --limit 3   # recent CI runs
```

Skip if no recent PR context in conversation.

## Output format

```
━━━ Session Status ━━━
Background here:
  • {handle} — {what it's doing} ({elapsed})
  • ... or "none"

Local git:
  Branch: {name} ({N ahead / M behind} upstream)
  Dirty:  {N files} | Worktrees: {count}
  Unpushed: {count}

Orchestrator: {N workers, M loops active | not running}

GitHub: {open PRs, CI state | skipped}
━━━━━━━━━━━━━━━━━━━━━━━
→ {one-line recommendation: continue watching X / poke loop Y / resume your last task}
```

## Rules

- If everything is `none / clean / not running`: say so in one line, don't pad the dashboard.
- Keep total output ≤20 lines. This is a glance, not a report.
- Do NOT summarize commits, TODOs, or goals — that's `/brief` or `/pickup`.
- Do NOT kill, restart, or modify any background process unless the user explicitly asks.
- If a background agent finished since the user last saw it, highlight the result in the "Background here" row (e.g. `• worker-3 — DONE 12m ago: tests passed`).
- If a background process appears **hung** (no progress in 5+ minutes for an active-looking task): flag it explicitly; don't kill it unprompted.

## Completion Status

- ✅ **DONE**: Dashboard shown; user has a clear picture of active work.
- ⚠ **DONE_WITH_CONCERNS**: Some sources unreachable (e.g. orchestrator down) — noted in output.
- ❌ **BLOCKED**: Unable to read git or conversation state — surface the failure.
