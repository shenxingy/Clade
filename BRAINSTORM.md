# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md/TODO.md, they're cleared.*

---

## [AI] From OpenClaw research — high-signal findings

These are concrete, verified techniques from projects with proven velocity. Not generic advice.

### 1. Self-organizing swarm (no central dispatcher)
Workers use a shared task queue and self-claim:
```
1. TaskList() → find unclaimed pending tasks
2. TaskUpdate({ owner: "me" }) → claim atomically
3. Execute → TaskUpdate({ status: "completed" })
4. Loop
```
Current bottleneck: our orchestrator assigns tasks from outside. A swarm model removes that bottleneck entirely — workers keep themselves busy.

### 2. Oracle pattern (second-model review before merge)
After a worker finishes, send diff + task description to a fresh Claude instance (different model, no context bias). It outputs APPROVED / REJECTED + reason. Only approved diffs get pushed. This catches "completed but wrong" silently, which our current verify_and_commit misses.
- Tool: `npx -y @steipete/oracle` or equivalent inline call
- Trigger: after `verify_and_commit()` passes, before `auto_push`

### 3. PLANNING/BUILDING phase distinction in loops
Current loop: supervisor reviews → spawns fix workers → repeat.
Better: **PLANNING loop** (read codebase, write `IMPLEMENTATION_PLAN.md`, no code changes) → **BUILDING loop** (pick top task from plan, implement, commit, mark done, repeat).
Planning loop runs once; building loop runs until plan is exhausted.
Phase swap is triggered by "STATUS: COMPLETE" sentinel in plan.

### 4. Dual-condition exit gate (smarter convergence)
Our current convergence: `last N iterations all ≤ K changes`.
Ralph's implementation adds: **semantic analysis** of whether changes are meaningful, not just counting. Circuit breaker: stop after 3 iterations with zero changes AND no pending plan items.

### 5. `uzi broadcast` — message all running workers
Critical missing feature: when you realize all workers need to know something ("use fetch not axios", "the API endpoint changed"), you currently can't tell them. A broadcast endpoint sends a message to every running worker's stdin / injects into their task context.
```
POST /api/sessions/{id}/workers/broadcast
body: { message: "..." }
```
Each worker gets the message appended to their task description and their process is "poked" (like the existing /message endpoint but for all workers at once).

### 6. AGENTS.md auto-generation from git blame
Parse `git blame --porcelain` across all files → build a file→owner map. Workers get injected with "you own X, stay out of Y" rules. Prevents merge conflicts without manual AGENTS.md maintenance.

### 7. GitHub Issues as persistent task database
Instead of (or alongside) SQLite tasks.db, sync tasks to/from GitHub Issues. Benefits:
- Tasks survive machine restarts
- Human can add/edit tasks from GitHub UI on phone
- Multiple orchestrator instances see the same queue
- PR gets auto-linked to issue → native progress tracking
- `/pm:epic-sync` from CCPM pattern applies here

### 8. Context budget indicator per worker
Show estimated token usage per worker in the worker card. When approaching 80% context window, worker is auto-instructed to `/compact`. Prevents silent context overflow failures.
- Heuristic: count chars in task description + log file size → estimate tokens
- UI: small bar under worker card, yellow at 60%, red at 80%

### 9. Semantic code TLDR (massive token reduction)
The parcadei/Continuous-Claude-v3 approach: instead of including raw files, generate:
- Function signatures + docstrings only (strips bodies)
- Import graph (who imports who)
- Call graph for the relevant function
- ~1,200 tokens vs 23,000 for raw file
Inject this as context instead of CLAUDE.md content stuffing.

### 10. `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` expose
Claude Code 2.1 has a native Agent Teams mode: shared task list, mailbox-based inter-agent messaging, designated team lead. We could offer a "Teams mode" that sets this env var and exposes the native task list in the UI (alongside or instead of our SQLite queue).

### 11. Model tier auto-routing
Currently: user picks model per task manually.
Better: route by score:
- score < 50 → escalate to opus (needs smart agent to clarify ambiguity first)
- score 50-79 → sonnet (default)
- score ≥ 80 → haiku (clear task, cheap to run)
Saves significant cost on batch runs.

### 12. Loop self-improvement: orchestrator reviews its own codebase
The iteration loop we built (artifact → supervisor → fix workers → converge) works on any artifact — not just papers. The orchestrator could run a loop on its own `server.py` or `index.html`:
- Supervisor reviews the code for inefficiencies, missing features, bugs
- FIXABLE findings → workers fix them
- Loop converges when no more improvements found
This is the "pipeline can iterate on itself" observation from the user.

### 13. `/handoff` → `/pickup` session continuity
When a worker's context window is 80% full, it writes a handoff file (`.claude/handoff-{worker_id}.md`) and a new worker picks up from that handoff. This extends effective task length beyond the context window limit.
We already have `/handoff` and `/pickup` skills in our skills system — but workers don't use them automatically.

### 14. Task "hot path" indicator
Before running tasks, analyze the dependency DAG and highlight the critical path (the longest chain). Workers on the critical path should get higher priority (run first or with more powerful model). Workers on non-critical paths can use haiku.

### 15. Intervention recording (reuse successful corrections)
When the user sends a /message to a worker, record the message and outcome. If the same failure pattern recurs in future tasks, auto-inject the previous correction as context ("in the past when X happened, the fix was Y").

---

*Process these into GOALS.md (Phase 2-4) and TODO.md when ready.*
