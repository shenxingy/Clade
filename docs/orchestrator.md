[English](orchestrator.md) | [中文](orchestrator.zh-CN.md)

← Back to [README](../README.md)

# Orchestrator Web UI

## Table of Contents

1. [Overview](#overview)
2. [Workflow](#workflow)
3. [Layout](#layout)
4. [GUI Settings Reference](#gui-settings-reference)
5. [Broadcast to All Workers](#broadcast-to-all-workers)
6. [Iteration Loop (Autonomous Refinement)](#iteration-loop-autonomous-refinement)

---

## Overview

The fastest way to go from idea to parallel execution. One chat session with an AI orchestrator decomposes your goal into tasks; a dashboard shows N workers executing them simultaneously.

```bash
./orchestrator/start.sh
# → Opens http://localhost:8765 in your browser
```

**No build step.** Single HTML file + FastAPI backend. Requires Python 3.9+.

## Workflow

```
1. Chat: "Build a SaaS with auth, billing, analytics"
   → Orchestrator asks 2-3 clarifying questions (stack, constraints, existing code)
   → You answer (type or use OS voice input)

2. Orchestrator proposes task breakdown
   → Writes .claude/proposed-tasks.md
   → UI shows confirmation overlay: "4 tasks ready. Start all?"

3. Click "Start All Workers"
   → Workers launch in parallel: claude -p "$(cat task.md)" --dangerously-skip-permissions
   → Dashboard updates every 1s: status, last commit, elapsed time

4. Monitor:
   Worker 1 │ running  │ feat: add NextAuth config    │ 2m34s │ [Pause] [Chat]
   Worker 2 │ running  │ feat: create Stripe webhook  │ 1m12s │ [Pause] [Chat]
   Worker 3 │ blocked  │ needs Stripe API key         │ 0m45s │        [Chat]

5. Worker 3 blocked → click [Chat] → type "Use sk_test_xxx"
   → Worker stops, message injected as context, worker restarts

6. All done: progress bar 100%, review with: git log --oneline
```

## Layout

```
┌─────────────────────────────────┬──────────────────────────────┐
│  Orchestrator Chat (PTY)        │  Task Queue                  │
│                                 │  ├ pending: Implement auth   │
│  > Build a SaaS with auth...    │  ├ pending: Add Stripe       │
│  < What tech stack?             │  └ [Run] [Delete] [+ Add]    │
│  > Next.js, Prisma, Stripe      ├──────────────────────────────┤
│  < Writing 4 tasks...           │  Workers                     │
│                                 │  ┌──────────────────────────┐│
│  ┌─ 4 tasks ready ──────────┐   │  │ running │ feat: auth...  ││
│  │ Start All Workers? [Yes] │   │  │ 2m34s   │ [Pause][Chat]  ││
│  └──────────────────────────┘   │  └──────────────────────────┘│
│  [Type message... ]   [Send]    │  ████░░░░░ 35%  ETA ~8 min   │
└─────────────────────────────────┴──────────────────────────────┘
```

## GUI Settings Reference

Open the **⚙ Settings** panel (top-right of the Web UI) to configure:

| Setting | Default | Effect |
|---------|---------|--------|
| Auto-start workers | ON | Workers launch immediately when `proposed-tasks.md` is written |
| Auto-push | ON | Push to feature branch after each commit |
| Auto-merge | ON | Squash-merge `orchestrator/task-*` PRs automatically |
| Auto-review | ON | Post AI code review comment on each PR |
| **Oracle validation** | OFF | Haiku independently reviews each diff before push — catches "completed but wrong" silently; rejects bad pushes |
| **Auto model routing** | OFF | Picks model by scout score: score ≥80 → haiku, 50-79 → sonnet, <50 → sonnet + ask-first warning |
| **Context budget warnings** | ON | Token bar on every worker card (green → amber at 120K → red at 160K); writes `.claude/context-warning-{id}.md` with `/compact` instructions |
| **AGENTS.md → Generate** | — | Builds file→branch ownership map from `git log`; copy output to `.claude/AGENTS.md` to prevent cross-worker collisions |
| **Webhook secret** | _(empty)_ | HMAC-SHA256 secret for `POST /api/webhooks/github`. **Security note:** if left empty, the endpoint accepts all requests — set this before exposing the orchestrator to the internet |

## Broadcast to All Workers

When all running workers need the same correction mid-run, use the **→ All Workers** bar visible at the top of the workers section in Execute mode:

```
Example: "The DB schema changed — column is now user_id not userId"
→ All running workers stop, receive the message as prepended context, and restart
```

Useful when you realize a global constraint changed and every worker needs to know.

## Iteration Loop (Autonomous Refinement)

Closes the review → fix → verify feedback loop for any iterative artifact (papers, code audits, content QA).

```
1. Execute mode → Loop section
2. Enter: artifact path = paper.tex  (or server.py, README.md, etc.)
           codebase dir = ./src       (optional, for DATA_CHECK workers)
           K = 2, N = 3               (converge when ≤2 changes for 3 consecutive iters)

3. ▶ Start Loop — the supervisor:
     FIXABLE   → spawns a worker to fix it automatically
     DATA_CHECK → spawns a read-only worker to verify a claim against your codebase
     DEFERRED  → adds to the accordion below (requires human review — never auto-fixed)
     CONVERGED → loop ends, toast fires

4. After all workers finish → count changes → check convergence → repeat
5. Converged? Review deferred items in the accordion.
```

The loop runs fully unattended. Set `max_iterations` in Settings as a safety cap.
