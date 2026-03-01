[English](autonomous-operation.md) | [中文](autonomous-operation.zh-CN.md)

← Back to [README](../README.md)

# Overnight Autonomous Operation

## Table of Contents

1. [Pattern: Task Queue → Sleep → Review](#pattern-task-queue--sleep--review)
2. [Pattern: Parallel Sessions (3-4x throughput)](#pattern-parallel-sessions-3-4x-throughput)
3. [Pattern: Context Relay (long tasks across sessions)](#pattern-context-relay-long-tasks-across-sessions)
4. [Safety Guarantees](#safety-guarantees)

---

The kit is designed to run unattended — you sleep, agents work.

## Pattern: Task Queue → Sleep → Review

```bash
# 1. Write task files for what you want done
cat > tasks.txt << 'EOF'
===TASK===
model: sonnet
timeout: 600
retries: 2
---
Implement the user settings page at app/settings/page.tsx.
Follow the pattern in app/profile/page.tsx. Use the existing
useUser hook and the settingsSchema from lib/schema.ts.
===TASK===
model: sonnet
timeout: 600
retries: 2
---
Add rate limiting middleware to all /api/auth/* routes.
Use the existing rateLimiter in lib/middleware.ts. Set 10 req/min.
EOF

# 2. Queue and run
claude  # open session
/batch-tasks --run tasks.txt  # starts in background, you can close the terminal

# 3. You get Telegram notifications when blocked or done
# 4. Next morning: /pickup to see what was done, review commits
```

## Pattern: Parallel Sessions (3-4x throughput)

```bash
# Terminal 1 — feature A
git worktree add ../proj-feat-a -b feat/settings-page
cd ../proj-feat-a && claude
# → assign task A, /handoff when done

# Terminal 2 — feature B (independent)
git worktree add ../proj-feat-b -b feat/rate-limiting
cd ../proj-feat-b && claude
# → assign task B, /handoff when done

# Review both in main branch, merge PRs
```

## Pattern: Context Relay (long tasks across sessions)

```bash
# Session 1 (context getting full at ~80%)
/handoff  # saves state to .claude/handoff-2026-02-23-14-30.md
# close session

# Session 2 (fresh context)
/pickup   # reads handoff, immediately resumes next step
```

## Safety Guarantees

The `pre-tool-guardian.sh` hook protects unattended runs: database migrations, catastrophic `rm -rf`, force pushes to main, and SQL DROP statements are automatically blocked and redirected to manual execution — so agents can't irreversibly destroy state while you sleep.
