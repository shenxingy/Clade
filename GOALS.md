# GOALS — Claude Code Orchestrator

**North star:** 1000+ commits/day. You describe requirements, AI implements them in parallel overnight. You wake up to merged PRs.

**Design principle:** Every step that a human does manually is a bug. Every step that a worker does sequentially instead of in parallel is waste.

---

## Phase 1 — One-Shot Batch (DONE)
*Status: ✓ shipped*

Plan mode → orchestrate → tasks auto-import → workers run in parallel → PRs created and merged.
You type a goal once, come back to committed code.

**Success criteria (achieved):**
- [x] Split Plan/Execute UI
- [x] Git worktree isolation per worker
- [x] Auto-push + auto-merge pipeline
- [x] SQLite persistence across restarts
- [x] Scheduler for overnight runs
- [x] Task dependency DAG
- [x] Retry with failure context injection
- [x] Scout readiness scoring

---

## Phase 2 — Feedback Loops (IN PROGRESS)
*Status: iteration loop shipped, more to come*

The output of one batch feeds the next planning step. Autonomous refinement cycles, not just one-shot batches.

**Success criteria:**
- [x] Iteration loop (Ralph-style supervisor) — review artifact → fix → verify → repeat
- [ ] Self-organizing swarm — workers self-claim tasks, no central assignment bottleneck
- [ ] Oracle validation — second model reviews before merge (independent bias-free check)
- [ ] Model tier routing — auto-assign haiku/sonnet/opus by task complexity score
- [ ] `uzi broadcast` — inject a message into ALL running workers simultaneously
- [ ] PLANNING/BUILDING phase distinction — loop has explicit plan phase before execute phase

---

## Phase 3 — AI-Native Context Engineering
*Status: not started*

Workers should have maximum relevant context at minimum token cost. Context is the bottleneck for task quality.

**Success criteria:**
- [ ] AGENTS.md auto-generation — file ownership inferred from git blame, injected into every worker
- [ ] Semantic code TLDR — 5-layer index (AST, call graph, imports) at ~1,200 tokens vs raw 23,000
- [ ] Context budget tracking — show token usage estimate per worker in UI
- [ ] `/compact` injection — workers told to compact when approaching context limit
- [ ] Skills system — on-demand domain knowledge loaded per task, not stuffed into base CLAUDE.md

---

## Phase 4 — Swarm Intelligence
*Status: not started*

N workers operating as a true swarm: shared task pool, file ownership enforcement, no-collision parallel execution at scale.

**Success criteria:**
- [ ] Swarm mode — N workers all pulling from shared queue, self-claiming, no central allocator
- [ ] File ownership system — AGENTS.md declares who owns what; workers respect boundaries
- [ ] GitHub Issues sync — use Issues as persistent multi-session task database
- [ ] Agent Teams integration — expose `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- [ ] Cross-worker messaging — workers can message each other (mailbox pattern)
- [ ] Worker dashboard → 1000+ commit/day pace visible in real time

---

## The OpenClaw Recipe (what made 600 commits/day possible)

1. **`committer "msg" file1 file2`** — scoped staging, the anti-collision primitive (✓ we use this)
2. **One worktree per task** — true isolation, zero branch collisions (✓ done)
3. **AGENTS.md with file ownership** — parallel agents never touch each other's files
4. **Ralph loop** — autonomous iteration until a goal is met, not one-shot
5. **Self-organizing workers** — workers pull from queue, no bottleneck at dispatch
6. **Oracle second-model review** — independent validation with fresh context before merge
7. **Model tier routing** — haiku for triage/scoring, sonnet for implementation, opus for architecture
8. **Context compaction discipline** — workers `/compact` between subtasks to extend range

---

## Why This Matters

The cost of ideas is near-zero with AI. The bottleneck is now:
1. **Task clarity** (scouting, scoring, planning loops)
2. **Execution parallelism** (worktrees, swarm)
3. **Integration quality** (oracle review, file ownership)
4. **Iteration speed** (feedback loops, no human in the loop for known-good patterns)

Reaching 1000+ commits/day is not about AI being faster — it's about removing every human-required step in the loop.
