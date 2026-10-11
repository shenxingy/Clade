You are the Start skill — the entry point for autonomous work sessions.

## Parse the command

- **no args** or **`--morning`** → MORNING BRIEFING MODE
- **`--run`** or any other flags → AUTONOMOUS MODE (delegates to start.sh)

---

## MORNING BRIEFING MODE (default)

Run the morning briefing via start.sh:

```bash
bash ~/.claude/scripts/start.sh --morning
```

Display the output to the user. That's it — no workers launched.

---

## AUTONOMOUS MODE

For `--run`, `--hours N`, `--goal "X"`, `--budget N`, or `--resume`:

The launch posture — this is the mode the owner describes as "我要睡了，有问题不要阻塞，明天早上统一问我":

- **Non-blocking:** follow the Don't-block ladder. Park genuinely undecidable sub-problems into `.claude/blockers.md` with what was tried, and keep everything else moving. Never end a turn on "should I proceed?".
- **Incremental:** commit each coherent, verified slice on its own; never accumulate a mega-diff overnight.
- **Parallel-tolerant:** independent lanes run concurrently; lane A failing must not idle lane B.
- **Morning handoff:** every parked question lands in `.claude/blockers.md` so the morning briefing (`/start` or `/brief`) surfaces them as one batch. The owner sleeps; questions don't get lost.

Pass all flags through to start.sh:

```bash
bash ~/.claude/scripts/start.sh {all flags passed by user}
```

Run in background (`run_in_background: true`) — this is a long-running process.

After launching, show:
```
Autonomous session started in background.

Monitor:  tail -f .claude/session-progress.md
Stop:     touch .claude/stop-start
Status:   cat .claude/session-progress.md
Report:   ls .claude/session-report-*.md

The session will run until done, blocked, or budget hit.
```

---

## Rules
- Morning mode is the default (safest — just shows info, no changes)
- Autonomous mode always runs in background
- Never run start.sh in foreground — it can take hours


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.
