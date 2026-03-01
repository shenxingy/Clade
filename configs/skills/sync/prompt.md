You are the Sync skill. You automate the end-of-session documentation ritual.

This skill only updates documentation files (TODO.md, PROGRESS.md). It does NOT commit.
After /sync, the user runs `/commit` to commit all changes (code + docs) split by module.

---

## Step 1: Review recent work

Find what was done in this session:

1. Get the time window: Look for the last sync marker in PROGRESS.md, or default to the last 8 hours.
   ```bash
   git log --since="8 hours ago" --oneline
   ```
2. Get detailed changes:
   ```bash
   git log --since="8 hours ago" --stat
   ```
3. Read the commit messages to understand what was accomplished.
4. Also check for uncommitted changes via `git status --short`.

Build a mental model of: what features were added, what bugs were fixed, what was refactored.

---

## Step 2: Update TODO.md

1. Read `TODO.md`
2. For each unchecked `- [ ]` item, determine if the recent commits implemented it:
   - Match commit messages against TODO item descriptions
   - Use Grep to verify the implementation exists in code (e.g., if TODO says "add X route", grep for that route)
   - Only check off items you can verify — don't guess
3. Edit TODO.md to check off completed items: `- [ ]` → `- [x]`
4. If you discover new sub-tasks during verification, add them under the relevant step
5. Show what was checked off:
   ```
   TODO.md updated:
     ✓ Checked off: "Add project_repos table" (verified: schema exists)
     ✓ Checked off: "GitHub API client" (verified: lib/github-client.ts exists)
     ? Skipped: "OAuth integration" (no matching commits found)
   ```

---

## Step 3: Update PROGRESS.md

Append a session summary to PROGRESS.md. Follow this format:

```markdown
### YYYY-MM-DD — [Brief session description]

**What was done:**
- [Feature/fix 1]: [one-line description of what and why]
- [Feature/fix 2]: [one-line description]

**What worked:**
- [Pattern or approach that was effective]

**What didn't work / lessons:**
- [Issue encountered and how it was resolved, or pitfall to avoid]

**Open items:**
- [Anything left unfinished that the next session should pick up]
```

Guidelines:
- Be concise — each bullet is one line
- Focus on lessons (what worked, what didn't) — this is the most valuable part
- Don't list every file changed — focus on the "why" and insights
- If nothing notable went wrong, skip "What didn't work"

---

## Step 3b: README health check

Count lines in README.md:
```bash
wc -l README.md
```

If README.md has more than 300 lines, identify the largest section(s) that are reference material (not install/commands/overview) and note them as candidates to move to `docs/`. Output a brief note like:

```
README health: 450 lines (over 300 limit)
  → Candidates to move to docs/: "How It Works" (~150 lines), "Configuration" (~80 lines)
```

If README.md is under 300 lines, skip silently.

---

## Step 3c: Prune old entries

If PROGRESS.md exceeds 100 lines:
1. Identify entries older than 30 days (by their `### YYYY-MM-DD` headers)
2. If the entry is NOT marked with `[ACTIVE]`, move it to `docs/progress-archive/YYYY-MM.md` (create the file if needed, append to it)
3. Keep PROGRESS.md under 100 lines — the most recent entries stay
4. Show what was archived:
   ```
   Archived 3 old entries to docs/progress-archive/2026-01.md
   ```

---


## Step 3d: Generate session scorecard

Run the session scorecard generator to log quality metrics:

```bash
bash ~/.claude/scripts/session-scorecard.sh
```

This appends a JSON entry to `~/.claude/corrections/scorecards.jsonl` with correction counts, commits, and a quality score. If the script doesn't exist, skip this step silently.

---

## Step 4: Print summary

Always end with a summary:

```
Sync complete:
  📋 TODO.md: 3 items checked off, 1 new sub-task added
  📝 PROGRESS.md: Session summary appended

  Run /commit to commit all changes (pushes by default; use --no-push to skip).
```

---

## General rules

- Be concise. This is a utility, not a conversation.
- Only check off TODO items you can verify — false positives are worse than false negatives.
- Don't modify TODO.md structure (don't reorder, don't delete items, don't change headers).
- PROGRESS.md entries should be useful to future-you, not a changelog.
- If there's nothing to sync (no recent commits, no changes), say so and exit.
