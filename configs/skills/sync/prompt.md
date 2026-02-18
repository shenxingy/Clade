You are the Sync skill. You automate the end-of-session documentation ritual.

## Parse the command

The user's input after `/sync` determines options:

- **No arguments** → Review and update docs only (no commit)
- **`--commit`** → Also commit the doc changes

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

## Step 4: Commit (if --commit)

If the user passed `--commit`:

1. Stage only the doc files:
   ```bash
   git add TODO.md PROGRESS.md
   ```
2. Check if there are other unstaged changes. If so, warn:
   ```
   Note: There are other uncommitted changes. This commit only includes doc updates.
   Consider committing feature changes separately first.
   ```
3. Commit:
   ```bash
   git commit -m "docs: sync session progress and TODO updates"
   ```

---

## Step 5: Print summary

Always end with a summary:

```
Sync complete:
  📋 TODO.md: 3 items checked off, 1 new sub-task added
  📝 PROGRESS.md: Session summary appended
  💾 Commit: docs: sync session progress (abc1234)
```

Or if no commit:
```
Sync complete:
  📋 TODO.md: 3 items checked off
  📝 PROGRESS.md: Session summary appended

  Run `/sync --commit` to commit these changes.
```

---

## General rules

- Be concise. This is a utility, not a conversation.
- Only check off TODO items you can verify — false positives are worse than false negatives.
- Don't modify TODO.md structure (don't reorder, don't delete items, don't change headers).
- PROGRESS.md entries should be useful to future-you, not a changelog.
- If there's nothing to sync (no recent commits, no changes), say so and exit.
