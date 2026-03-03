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
