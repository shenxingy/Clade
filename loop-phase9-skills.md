# Goal: Phase 9.6 — Pattern Intelligence & Self-Improvement Skills

## Context

Claude Code Kit CLI layer. Skills live in `configs/skills/`, hooks in `configs/hooks/`.
After loop converges, `install.sh` auto-runs (deploy gap fixed).

**North star:** Minimize human intervention. System learns from patterns, surfaces insights automatically.

---

## Requirements

### 1. `/map` skill ✓
Create `configs/skills/map/prompt.md`

When the user runs `/map`, Claude should:
1. Scan the project structure using Glob/Read tools
2. Identify major modules and their responsibilities
3. Generate a Mermaid diagram showing module relationships
4. Write `ARCHITECTURE.md` to the project root with:
   - A brief description of each top-level directory
   - A Mermaid `graph TD` diagram of module dependencies
   - Key files in each module
5. Tell the user "Updated ARCHITECTURE.md"

The skill prompt should instruct Claude to read existing `ARCHITECTURE.md` first (if any) and update it rather than overwrite blindly.

### 2. Prompt fingerprint tracker
Create `configs/hooks/prompt-tracker.sh`

This hook fires on `UserPromptSubmit` (check `configs/settings-hooks.json` for how hooks are registered — it uses a JSON array). The hook reads the prompt from stdin JSON (field `prompt` or `message`).

The hook should:
1. Read prompt text from stdin: `prompt=$(echo "$input" | jq -r '.prompt // .message // ""')`
2. Generate a fingerprint: first 80 chars, lowercased, spaces collapsed: `fingerprint=$(echo "$prompt" | tr '[:upper:]' '[:lower:]' | tr -s ' ' | cut -c1-80)`
3. Append to `.claude/prompt-log.jsonl`: `{"date":"...", "fp":"...", "prompt":"first 80 chars"}`
4. Count how many times this fingerprint has appeared (grep the log file)
5. If count >= 3: output a `systemMessage` to stdout suggesting skill creation:
   `{"systemMessage": "💡 You've run a similar prompt ${count}x — consider making it a /skill: '${fingerprint}'"}`
6. Always exit 0, always async=true (non-blocking)
7. Skip if prompt is < 20 chars (too short to be a recurring pattern)

Also update `configs/settings-hooks.json` to register this new hook under `UserPromptSubmit`. Look at the existing format in that file first.

### 3. `/incident` skill
Create `configs/skills/incident/prompt.md`

When the user runs `/incident` (optionally with a description), Claude should:
1. Ask (or use provided description): what went wrong, what was the context, what was the impact
2. Perform root cause analysis
3. Write a structured entry to `.claude/incidents.md` (create if not exists):
   ```
   ## Incident — {date}
   **What:** ...
   **Context:** ...
   **Root cause:** ...
   **Fix applied:** ...
   **Prevention:** ...
   ```
4. If a corrective rule can be extracted, offer to append it to `corrections/rules.md` in the format:
   `- [{date}] {domain} ({root-cause-category}): {do this} instead of {not this}`
5. Tell the user the incident was logged

### 4. Revert rate tracker
Extend `configs/hooks/session-context.sh`

Read the file first. At the end, before the final `jq` output, add:

```bash
# Revert rate check
REVERT_COUNT=$(git log --oneline --since="7 days ago" --grep="^Revert" 2>/dev/null | wc -l | tr -d ' ')
TOTAL_COUNT=$(git log --oneline --since="7 days ago" 2>/dev/null | wc -l | tr -d ' ')
if [[ "${TOTAL_COUNT:-0}" -gt 10 && "${REVERT_COUNT:-0}" -gt 0 ]]; then
  REVERT_RATE=$(( REVERT_COUNT * 100 / TOTAL_COUNT ))
  if [[ "$REVERT_RATE" -gt 10 ]]; then
    CONTEXT="${CONTEXT}\n⚠ High revert rate this week: ${REVERT_COUNT}/${TOTAL_COUNT} commits (${REVERT_RATE}%)\n"
  fi
fi
```

---

## Success Criteria

- `configs/skills/map/prompt.md` exists and describes the /map workflow
- [x] `configs/hooks/prompt-tracker.sh` exists, is executable, exits 0
- [x] `configs/settings-hooks.json` registers prompt-tracker under UserPromptSubmit
- `configs/skills/incident/prompt.md` exists
- `configs/hooks/session-context.sh` includes revert rate check
- All files committed with `committer`
- `install.sh` will auto-run after convergence (deploy gap already fixed)

## Notes

- All hooks must exit 0 — never block Claude
- prompt-tracker.sh must be async=true in settings-hooks.json
- Read `configs/settings-hooks.json` before editing to understand the format
- Read `configs/hooks/session-context.sh` fully before editing (it's ~100 lines)
- Skill prompts should be self-contained — no external dependencies
