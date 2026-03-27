You are the Commit skill. You analyze all uncommitted changes and create well-organized commits split by logical module, following the project convention of one commit per independent unit of change.

## Parse the command

- **No arguments** → Analyze, plan, confirm, commit, push (default)
- **`--no-push`** → Commit only, skip push
- **`--dry-run`** → Show plan only, don't commit

---

## Step 1: Analyze changes

```bash
git status --short
git diff --stat
git diff --cached --stat
```

Collect ALL changed files — both staged and unstaged.

If nothing is changed, check for unpushed commits:
```bash
git log origin/main..HEAD --oneline
```
- Unpushed commits exist AND `--no-push` was NOT used → push immediately, report result, exit
- No unpushed commits either → say "Nothing to commit or push" and exit

---

## Step 2: Group by logical module

Group files into commits using these heuristics. Use judgment — logical cohesion matters more than rigid categories. Files that clearly serve the same feature go in one commit regardless of type.

**Category signals (first match is a hint, not a rule):**

| Category | File patterns | Commit prefix |
|----------|--------------|---------------|
| Database/Schema | `*schema*`, `*migration*`, `*drizzle*`, `*prisma*`, `*.sql` | `db:` |
| API/Backend | `**/api/**`, `**/routes/**`, `**/handlers/**`, `**/services/**` | `feat:` / `fix:` |
| Frontend/UI | `**/components/**`, `**/pages/**`, `**/app/**`, `**/*.css`, `**/styles/**` | `feat:` / `fix:` |
| Config/Infra | `**/.env*`, `**/config/**`, `**/docker*`, `**/*.yml`, `**/settings*` | `config:` |
| Tests | `**/test*`, `**/__tests__/**`, `**/*.test.*`, `**/*.spec.*` | `test:` |
| Docs | `README*`, `TODO.md`, `PROGRESS.md`, `VISION.md`, `CLAUDE.md`, `**/docs/**` | `docs:` |
| Scripts/Tools | `**/scripts/**`, `**/*.sh`, `**/hooks/**`, `**/skills/**`, `**/commands/**` | `chore:` |

**Cross-cutting rule:** If schema + API + frontend changes all implement the same feature (e.g., "add users table + CRUD routes + UI"), group them into ONE `feat:` commit — don't split what belongs together.

---

## Step 3: Generate commit messages

For each group, generate a message:
- Format: `<type>(<scope>): <description>`
- Scope: optional module name (e.g., `auth`, `dashboard`, `api`)
- Description: imperative, present tense, ≤72 chars
- **Never add Co-Authored-By lines**

Examples:
- `feat(auth): add JWT refresh token endpoint`
- `fix(dashboard): correct activity chart date range`
- `db: add sessions table for token storage`
- `chore: add auto-pull to session-context hook`
- `docs: sync session progress and TODO updates`

---

## Step 3.5: README sync (before committing)

Before grouping into commits, check if the README needs to be updated to reflect the changes. This step ensures docs never drift from code.

### 3.5.1 — Counted artifacts

If the README mentions counts like "N hooks", "M skills", "X agents", etc.:
- Count the actual files in the corresponding directories
- If the count changed, update the README line to match
- Do the same for any translated README (e.g., README.zh-CN.md)

### 3.5.2 — Pipeline flowchart

A flowchart is **mandatory** if the repo contains a pipeline — any chain of scripts, workers, queues, or stages that process data in sequence. The flowchart must always reflect the actual code.

**Detect a pipeline:** look for patterns like worker→supervisor loops, task queues, multi-stage processing scripts, webhook→handler→queue chains, or background runner scripts.

**If a flowchart exists in the README** and any changed file touches the pipeline:
- Re-read the relevant pipeline scripts/code
- Verify each box and arrow in the diagram matches the actual flow
- Update any stale edges, renamed stages, or missing new stages

**If no flowchart exists** and the repo has a pipeline:
- Read the pipeline scripts to understand the actual flow
- Generate a mermaid diagram (prefer `graph LR` for horizontal flows) that accurately represents it
- Insert it in the README under the most relevant section (e.g., "Architecture", "How It Works", or right after the intro)

**Mermaid style guide:**
```
graph LR
  A[User Input] --> B[Supervisor]
  B --> C[Worker 1]
  B --> D[Worker 2]
  C --> E[(Task Queue)]
  D --> E
  E --> F{Converged?}
  F -->|no| B
  F -->|yes| G[Done]
```
Use `[label]` for processes, `[(label)]` for storage, `{label}` for decisions, `([label])` for terminal nodes.

**Rule:** If the flowchart would be wrong or absent, fix it now — a stale diagram is worse than no diagram.

### 3.5.3 — Include README changes in commits

If any README files were updated in this step:
- Add them to the existing `docs:` group (or create one)
- They are part of this commit run, not a separate follow-up

---

## Step 4: Show plan and execute immediately

Present the plan, then execute immediately — do NOT ask for confirmation:

```
Commits (3):

1. feat(auth): add JWT refresh token endpoint
   → packages/api/routes/auth.ts
   → packages/api/services/jwt.ts

2. db: add sessions table for token storage
   → packages/db/schema.ts

3. docs: sync session progress
   → TODO.md, PROGRESS.md
```

Exception: if `--dry-run` was used, show the plan and stop.

---

## Step 5: Execute commits

For each group in order:
1. Stage only those files: `git add <file1> <file2> ...`
2. Commit: `git commit -m "<message>"`
3. Report result: `✓ <message> (<short-hash>)`

If a commit fails, stop immediately and report the error — don't continue to the next group.

---

## Step 5.5: CI gate (before push)

Before pushing, run a quick local CI check to ensure GitHub Actions will pass. Read `CLAUDE.md` for the project's verify/test commands. At minimum:

1. **Python projects**: `python -m py_compile` on all changed `.py` files + `pytest` if tests exist
2. **TypeScript projects**: `tsc --noEmit` if tsconfig exists
3. **Shell scripts**: `bash -n` on changed `.sh` files

```bash
# Example for clade:
cd orchestrator && python -m py_compile <changed .py files> && .venv/bin/python -m pytest tests/ -v
```

- If CI checks pass → proceed to push
- If CI checks fail → stop, report errors, fix them, then re-run `/commit`
- Skip this step if `--no-push` was used (no point checking CI if not pushing)

---

## Step 6: Push (unless --no-push)

After all commits succeed and CI checks pass, push by default:
```bash
git push
```

Report the result.

---

## Step 7: Summary

```
Commit complete:
  ✓ feat(auth): add JWT refresh token endpoint (abc1234)
  ✓ db: add sessions table (def5678)
  ✓ docs: sync session progress (ghi9012)
  ✓ Pushed to origin/main
```

Or if `--no-push` was used:
```
Commit complete:
  ✓ 3 commits. Run `git push` to push, or `/commit` next time (pushes by default).
```

---

## General rules

- Never commit `.env` files, secrets, or credentials — warn if detected
- Never use `git add .` or `git add -A` — always add specific files
- If working tree is clean, say so and exit immediately
- Never ask for confirmation — analyze, commit, push in one shot (unless `--dry-run`)
- **Alternative for simple cases:** For agents that need a quick single commit without multi-group splitting, use `~/.claude/scripts/committer.sh "type: message" file1 file2 ...` instead of this skill. The commit skill is for interactive, multi-group commit workflows.
