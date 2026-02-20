# Progress Log

Hard-won insights from building and maintaining this toolkit.

---

### 2026-02-20 — Stop hook, auto-pull, sync skill improvements

**What was done:**
- `session-context.sh`: Added auto-pull at session start — fetches remote, pulls if clean, warns if dirty
- `settings-hooks.json`: Fixed Stop hook loop — added instruction to surface manual steps to user instead of retrying indefinitely
- `sync` skill: Flipped commit flag — commit is now default, `--no-commit` to skip

**What worked:**
- `git pull --ff-only` is the right default: fast-forward only, fails safely if branch has diverged

**Lessons:**
- Stop hook returning `ok=false` causes Claude to attempt auto-fix; without a "give up" instruction it loops forever on failures like missing CLI tools or interactive TUI prompts
- `drizzle-kit push` requires interactive confirmation by default; `--force` skips it — document this in project-specific PROGRESS.md when encountered
- CLI flag convention: destructive/irreversible actions opt-in (`--force`, `--delete`); common desired actions should be default with opt-out (`--no-commit`, `--dry-run`)
