# /learn — Per-Project Learnings

Record, search, and prune project learnings in `.claude/learnings.jsonl`.
Learnings accumulate across sessions and are typed, confidence-scored, and prunable.

**Storage:** `.claude/learnings.jsonl` in the current project directory (NOT `~/.claude/` — per-project).

**Entry schema:**
```json
{"id":"abc12345","type":"pitfall","content":"...","confidence":80,"tags":[],"created_at":"ISO8601","source":"session","pruned":false}
```

Types: `pattern` | `pitfall` | `preference` | `architecture` | `tool`

---

## Steps

### Step 1: Parse subcommand

Read the user's argument:
- No argument or `add [text]` → **add** mode
- `search <query>` → **search** mode
- `list [--type X]` → **list** mode
- `prune` → **prune** mode

### Step 2a: ADD mode

1. Extract the learning text from the user's message.
2. Infer `type` from content keywords:
   - "avoid" / "broken" / "wrong" / "never" / "bug" → `pitfall`
   - "always" / "prefer" / "use" / "best" → `preference`
   - "architecture" / "layer" / "component" / "structure" → `architecture`
   - "library" / "tool" / "package" / "cli" → `tool`
   - Default → `pattern`
3. Set `confidence` to 75 if not specified.
4. Generate `id` = first 8 chars of `uuid4()` equivalent (use `python3 -c "import uuid; print(str(uuid.uuid4())[:8])"` or timestamp hex).
5. Append to `.claude/learnings.jsonl`:
   ```bash
   echo '{"id":"...","type":"...","content":"...","confidence":75,"tags":[],"created_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","source":"session","pruned":false}' >> .claude/learnings.jsonl
   ```
6. Report: `Recorded [type] learning (confidence: 75%) → .claude/learnings.jsonl`

### Step 2b: SEARCH mode

1. Read all non-pruned entries from `.claude/learnings.jsonl`.
2. Score each entry against the query using term overlap (count shared words).
3. Return top 5 sorted by score descending, formatted as a markdown table:

| Type | Confidence | Content |
|------|-----------|---------|
| pitfall | 80% | ... |

4. If no entries or no matches, report "No matching learnings found."

### Step 2c: LIST mode

1. Read all non-pruned entries.
2. Filter by `--type X` if provided.
3. Group by type, display each group:
   ```
   ### pitfall (3)
   - [80%] Content here
   - [75%] Another learning
   ```
4. Show total count at end.

### Step 2d: PRUNE mode

1. Read all non-pruned entries.
2. Flag candidates where ANY of:
   - `confidence < 40`
   - Entry is older than 180 days AND `confidence < 60`
   - `content` length < 50 characters
3. Present candidates to user:
   ```
   Found 2 pruning candidates:
   1. [id: abc12345] pitfall (confidence: 35%): "short text"
   2. [id: def67890] pattern (90 days old, confidence: 55%): "..."
   Prune these? (y/N)
   ```
4. If user confirms, mark them `"pruned": true` in the file (tombstone, don't delete):
   ```python
   python3 -c "
   import json
   lines = open('.claude/learnings.jsonl').readlines()
   prune_ids = {'abc12345', 'def67890'}
   out = []
   for line in lines:
       e = json.loads(line)
       if e['id'] in prune_ids:
           e['pruned'] = True
       out.append(json.dumps(e))
   open('.claude/learnings.jsonl', 'w').write('\n'.join(out) + '\n')
   "
   ```

---

## Completion Status

- ✅ **DONE** — learning recorded / search results shown / list displayed / prune complete
- ⚠ **DONE_WITH_CONCERNS** — `.claude/learnings.jsonl` created for first time; confirm project dir is correct
- ❌ **BLOCKED** — cannot write to `.claude/`; write details to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — no argument given and no learning text found in context
