# /incident Skill: Structured Incident Logging

## Overview
This skill helps you systematically capture incidents, analyze their root causes, and extract lessons learned to prevent future recurrence.

## Workflow

### Step 1: Gather Incident Details
If the user provided a description with `/incident <description>`, use that. Otherwise, ask the user:
- **What went wrong?** (the symptom, the failure, what the user observed)
- **What was the context?** (what was being done, what changed, what was the state)
- **What was the impact?** (did it affect production, other users, how long did it last)

### Step 2: Perform Root Cause Analysis
Once you have the details, conduct a structured RCA:
- **Immediate cause**: What directly caused the failure? (e.g., missing validation, race condition, config not deployed)
- **Root cause**: Why was the immediate cause present? (e.g., code not tested, config drift, async task not awaited)
- **Category**: Classify the root cause into one of these categories:
  - `settings-disconnect`: Config defined but not wired, loaded, or called
  - `edge-case`: Untested input, OS-specific behavior, empty/null/first-run state
  - `async-race`: TOCTOU (time-of-check-time-of-use), stale closures, missing locks, zombie processes
  - `security`: Unsanitized input, leaked secrets, missing auth/validation
  - `deploy-gap`: Source differs from deployed, config not reloaded, code defined but not called at runtime

### Step 3: Write Incident Entry
Create or update `.claude/incidents.md` with a new entry:

```markdown
## Incident — {date: YYYY-MM-DD}
**What:** {1-2 sentence symptom - what went wrong}
**Context:** {1-2 sentences - what was being done, what changed}
**Root cause:** {1-2 sentences - why did it happen, which category}
**Fix applied:** {how was it resolved, if immediate fix exists}
**Prevention:** {what should prevent this next time - concrete steps, not vague}
```

Example:
```markdown
## Incident — 2026-02-26
**What:** API endpoint returned 500 on startup, database connection string missing from error response.
**Context:** Deploying to production with new secrets management; assumed .env would be loaded from system but it wasn't.
**Root cause:** Secrets loading hook defined in config but never called during server startup. [deploy-gap]
**Fix applied:** Added explicit `await loadSecrets()` call in server init before database connect.
**Prevention:** Add startup checklist: (1) required envvars defined, (2) all config-loading hooks executed, (3) test startup on fresh container.
```

### Step 4: Extract Corrective Rule (Optional)
If the incident reveals a pattern worth remembering, offer to append a rule to `corrections/rules.md`:

Format:
```
- [YYYY-MM-DD] {domain} ({root-cause-category}): {do this} instead of {not this}
```

Example:
```
- [2026-02-26] deploy (deploy-gap): Call `loadSecrets()` explicitly in server init — not rely on framework autoload
```

Ask the user if they want to add the rule. If yes, append it to the file. If no, skip.

### Step 5: Confirm and Close
Once the incident entry is written, print:

```
✓ Incident logged to .claude/incidents.md — [link to timestamp]
```

If a rule was added:
```
✓ Corrective rule added to corrections/rules.md
```

---

## Implementation Notes

- **Keep it concise**: Incident entries should be scannable — one incident per date.
- **Date format**: Use YYYY-MM-DD (e.g., 2026-02-27).
- **Prevention is key**: The "Prevention" section is the most valuable part — it should be concrete and actionable, not vague.
- **Root cause category** is required for rule extraction — it helps organize lessons by type.
- **If .claude/incidents.md doesn't exist**, create it with a header: `# Incident Log\n\n`.
- **If corrections/rules.md doesn't exist**, create it with a header: `# Correction Rules\n\n`.

---

## User Interaction Model

1. User runs `/incident` with optional description: `/incident "API timeout during batch job"`
2. If no description, ask for what/context/impact
3. Conduct RCA together (ask clarifying questions if needed)
4. Write the incident entry to `.claude/incidents.md`
5. Offer to extract a rule — get user confirmation before appending
6. Confirm logging is complete


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.
