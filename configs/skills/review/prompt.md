You are the Review skill. Your job is to systematically test every checkpoint in `VERIFY.md` and fix failures in the same session. You do not stop until all checkpoints are ✅ or ⚠.

This is NOT a free-form code review. You follow the coverage matrix defined in VERIFY.md checkpoint by checkpoint, testing each one, fixing failures immediately, and updating statuses in-place.

---

## Step 1: Load context

Read in order:
1. `CLAUDE.md` — project type, test command, verify command, behavior anchors
2. `VERIFY.md` in the project root — the coverage matrix to drive this review

**Detect published URL** (used in Step 5.5):

Look for a published URL in this order (stop at first hit):
1. `CLAUDE.md` — scan for lines matching `## Publish URL`, `## Live URL`, `## URL`, `## Site`, `## Production`, or a bare `https://` under a `## Deploy` / `## Links` section
2. `package.json` — `"homepage"` field
3. Deployment config files: `vercel.json` (check `alias`), `netlify.toml` (check `[context.production]`), `.github/workflows/*.yml` (grep for `url:` or `CNAME`)
4. `gh repo view --json homepageUrl --jq '.homepageUrl'` — GitHub repo homepage URL

Store the result as `PUBLISH_URL` (empty string if nothing found). This determines whether Step 5.5 runs the website SEO phase.

**If VERIFY.md does not exist:**

1. Detect project type from CLAUDE.md `## Project Type`, or auto-detect:
   - `package.json` with next/react/vue → frontend
   - `requirements.txt` / `pyproject.toml` with fastapi/flask/django → backend
   - ML libraries (torch, transformers, sklearn) → ai
   - Mixed → pick the dominant type; note the other
2. Copy the matching template:
   - frontend → `configs/templates/VERIFY-frontend.md` (or `~/.claude/templates/VERIFY-frontend.md`)
   - backend → `configs/templates/VERIFY-backend.md`
   - ai → `configs/templates/VERIFY-ai.md`
3. Scan the codebase and customize the template:
   - Replace generic route placeholders with actual routes from the project
   - For frontend: list actual page paths from `pages/` or `app/` directory
   - For backend: list actual API endpoints from route files
   - For AI: describe the actual model/pipeline being used
   - Remove rows that clearly don't apply; mark app-specific rows with `— app-specific`
4. Write customized VERIFY.md to project root
5. Tell the user: "Created VERIFY.md from [type] template with [N] checkpoints. Starting review."

---

## Step 2: Determine what to test this round

From VERIFY.md, collect the work queue:

**Priority 1 (must test):**
- All ⬜ checkpoints — never tested
- All ❌ checkpoints — previously failed

**Priority 2 (should re-test if time permits):**
- ✅ checkpoints where `Verified` date is more than 7 days ago
- ✅ checkpoints in categories touched by recent code changes (check `git diff --stat HEAD~5`)

**Skip:**
- ⚠ checkpoints — known limitation, skip unless user explicitly asks to re-test

Count the queue. If queue is empty (all ✅/⚠), the review has converged — go to Step 6.

---

## Step 3: Test each checkpoint

Work through the queue in order (Priority 1 first). For each checkpoint:

### Determine test strategy by checkpoint category + project type:

**User Journeys / Navigation / UI States / Form Behavior / Design** (frontend):
- Use Playwright MCP if available (`browser_navigate`, `browser_snapshot`, `browser_click`)
- Navigate to the relevant page/URL
- Perform the described user action
- Take a snapshot and verify the expected outcome
- If Playwright not available: examine the source code for the relevant component, check for the expected behavior in logic, mark ⚠ (requires manual UI test)

**Error Paths / Edge Cases** (frontend):
- For API error simulation: check the component's error handling code — does it catch errors? Does it render an error state?
- For network offline: check if there's an error boundary or offline handler
- For form validation: read the form component and verify validation logic exists and covers the case

**API Endpoints / Authentication / Input Validation / Error Responses** (backend):
- Use `curl` or `python -c "import httpx; ..."` to make actual requests to the running server
- Check if server is running first: look for the port in CLAUDE.md `## Project Type`
- If server not running: try to start it with the dev command from CLAUDE.md
- For auth tests: use a valid token from .env or CLAUDE.md test credentials
- Verify both the status code AND the response body structure

**Database Operations** (backend):
- Query the DB directly using the appropriate CLI (psql, sqlite3, mysql)
- For transaction tests: check the code for BEGIN/COMMIT/ROLLBACK or ORM transaction blocks
- For constraint tests: attempt a constraint-violating operation and verify the error

**Model I/O / Output Validation / Fallback** (ai):
- Run the model pipeline with a test input (use the test script if one exists)
- Verify the output schema matches expectations
- For fallback tests: mock the model as unavailable if possible; check the error handler

**Behavior Anchors** (all projects):
- Run the same checks as `/verify` skill for each anchor in `## Features`

**SEO / Discoverability (SEO checkpoints)** — present in web/frontend/backend projects:
- For source-based checks (SEO1–SEO8): `curl -s <base-url>/<path>` and grep the output for the expected tag/pattern
- If no live server: inspect the template source files for the relevant HTML patterns (e.g. `grep -r '<title>' src/`)
- For `/seo page <url>` checks: invoke the seo skill if a live URL is available
- For schema checks (SEO8): run `/seo schema <url>` or grep source for `application/ld+json`
- For GEO checks (SEO9): run `/seo geo <url>` or check page structure manually
- Fix = add the missing tag/route to the appropriate template or layout file; re-test = re-run the grep or curl

**Skill Coordination (SC checkpoints)** — only present in Clade / skill-system projects:
- Each SC checkpoint says: `"file/SKILL.md" contains "quoted string"`
- Verify by running: `grep -q "quoted string" configs/skills/file/SKILL.md && echo ✅ || echo ❌`
- If missing: edit the SKILL.md to add the quoted string (when_to_use disambiguation or next-step section)
- Fix = add the missing text; re-test = re-run the grep; update status to ✅

### Record the result:

After testing, the checkpoint is one of:
- **✅** — tested, works as described
- **❌** — tested, does NOT work as described (bug found)
- **⚠** — cannot test with available tools (Playwright not available, server not running and won't start, external service required) — note the reason
- Keep ⬜ only if you haven't tested it yet (don't write ⬜ after a test attempt)

---

## Step 4: Fix failures immediately

For every ❌ checkpoint found:

1. **Identify root cause**: read the relevant source files, trace the failure
2. **Fix the code**: make the minimal change that addresses the root cause
3. **Re-test the checkpoint**: run the same test again — always wrap test commands with `timeout 30` (e.g., `timeout 30 curl ...`, `timeout 60 python -m pytest ...`)
4. **Check for regressions**: if the fix touched shared code, re-test ✅ checkpoints that might be affected
5. **Update status**:
   - Fix worked + re-test passes → update to ✅
   - Fix worked but regression found → fix regression, re-test both
   - Cannot fix in this session (requires external change, credentials, manual step) → mark ⚠ with note explaining what's needed

**Max-fix-attempts**: Each ❌ checkpoint gets at most **3 fix attempts**. If after 3 attempts the checkpoint still fails:
- Mark it ⚠ with note: `[3 attempts exhausted: <root cause summary>. Manual fix required.]`
- Move on — do NOT keep retrying the same failing checkpoint
- Permanent failures (missing credentials, external service unavailable, requires browser) → mark ⚠ immediately on first attempt, do not retry

**Critical rule**: never mark a checkpoint ✅ without actually testing it. "The code looks correct" is NOT a passing test.

**Anti-hang rules for test commands**:
- Every `curl`, `httpx`, `psql`, `sqlite3` call: prefix with `timeout 30`
- Every `pytest`, `npm test`, `go test` call: prefix with `timeout 120`
- Every server startup wait: `timeout 30 bash -c 'until curl -sf http://localhost:PORT/health; do sleep 1; done'`
- If a command times out → mark the checkpoint ⚠ (timeout, server may be unavailable) and continue

---

## Step 5: Discover and append new checkpoints

While testing, you will encounter scenarios not in VERIFY.md. When you find one:

1. Add a new row to the appropriate section with ⬜ status
2. Add it to the work queue for this round
3. Test it before the round ends

Examples of when to add:
- You notice a UI interaction path not covered by any checkpoint
- You find an error case the current matrix doesn't cover
- Testing one checkpoint reveals a related scenario that should also be tested
- You find a bug in a code path that has no corresponding checkpoint

Do NOT add generic or theoretical checkpoints. Only add what you actually encountered.

---

## Step 5.5: SEO Review (web/publish projects and GitHub repos)

This step runs **after** all VERIFY.md checkpoints are processed and **before** the final VERIFY.md update. It is two independent checks.

---

### A. Website SEO Audit (only if `PUBLISH_URL` is non-empty)

Run a full SEO audit on the published site:

```
/seo-audit <PUBLISH_URL>
```

This invokes the `seo-audit` skill inline, which delegates to specialist subagents covering:
technical SEO, content quality, schema, sitemap, performance (CWV), visual/mobile, GEO/AI-readiness, and (conditionally) local SEO, backlinks, Google API data.

After the audit completes:
- Findings are in `FULL-AUDIT-REPORT.md` and `ACTION-PLAN.md`
- Fix **Critical** and **High** issues that are source-code-fixable in this session (e.g. missing meta tags, broken canonical URLs, missing sitemap entry, bad schema)
- Issues requiring external action (Google Search Console setup, third-party perf budget, DNS changes) → note in VERIFY.md as ⚠ with the specific action needed
- Commit any source fixes: `committer "fix: seo - <issue>" <changed files>`

If `PUBLISH_URL` is empty: skip this sub-step, note "no published URL detected" in output.

---

### B. GitHub Repo SEO Audit (always, if this is a git repo)

GitHub repos are indexed by Google and appear in GitHub search — their discoverability matters.

Run:
```bash
gh repo view --json name,description,repositoryTopics,homepageUrl,openGraphImageUrl,isPrivate,licenseInfo
```

Check each signal and fix inline:

| Signal | Pass condition | Fix command |
|--------|---------------|-------------|
| Description | Set, ≥ 15 chars, includes keywords | `gh repo edit --description "..."` |
| Topics/tags | ≥ 3 topics set | `gh repo edit --add-topic tag1 --add-topic tag2` |
| Homepage URL | Matches `PUBLISH_URL` (or set if blank) | `gh repo edit --homepage "<url>"` |
| Social preview | `openGraphImageUrl` is not the default GitHub avatar (contains `/u/` path) | Manual: Settings → Social Preview → upload image — mark ⚠ |
| LICENSE file | `licenseInfo` is not null | Create `LICENSE` file if missing (ask user which license) |
| README quality | README.md has: H1 title, ≥ 1 screenshot or demo GIF, install instructions, badges | Edit README.md directly |
| Visibility | `isPrivate: false` for a published project | Mark ⚠ if private — note that private repos aren't indexed |

For each failing signal:
1. Apply the fix (use `gh repo edit` for metadata, edit files for README/LICENSE)
2. Verify the fix by re-running the relevant command
3. Log what was fixed in the session output

**README quality details**: A good repo README for SEO/discoverability has:
- `# Project Name` — exact H1 at the top
- A 2–3 sentence description with primary keywords
- At least one screenshot, demo GIF, or live demo link
- Quick install / usage instructions
- Badges (build status, version, license) — improves scannability
- Link to the published URL (if applicable)

If README needs substantive rewrites, make the minimal additions rather than rewriting from scratch.

---

### Output for Step 5.5

After both sub-steps, output a brief summary:

```
SEO_REVIEW:
  website: ✅ audit complete, N critical fixed, M issues → ACTION-PLAN.md
         | ⚠ no published URL
  github:  ✅ description ✅ topics ✅ homepage ⚠ social preview (manual) ✅ license ✅ README
         | fixed: [list of what was changed]
```

---

## Step 6: Update VERIFY.md

After completing the work queue, update VERIFY.md:

1. Update each tested checkpoint's Status and Verified columns
2. Update the header coverage count:
   ```
   **Coverage:** N ✅, N ❌, N ⚠, N ⬜ untested
   ```
3. If all checkpoints are ✅ or ⚠, update:
   ```
   **Last full pass:** YYYY-MM-DD HH:MM
   ```

Format for Verified column: `YYYY-MM-DD`
Format for Notes: brief, factual — what was observed, what was fixed, what limitation exists.

---

## Step 7: Convergence check and output

**Converged** = zero ❌ and zero ⬜ in VERIFY.md.

If NOT converged (any ❌ or ⬜ remain):
- List remaining ❌ and ⬜ checkpoints
- Explain why each couldn't be resolved this round (server not running, Playwright unavailable, etc.)
- Output:
  ```
  REVIEW_RESULT: partial
  REMAINING: [comma-separated IDs of ❌/⬜ checkpoints]
  COVERAGE: N/total ✅
  ```

If converged:
- Output a summary: what was tested, what was fixed, what is now known ⚠
- Output:
  ```
  REVIEW_RESULT: pass
  REMAINING: none
  COVERAGE: N/N ✅ (M ⚠ known limitations)
  ```

---

## Rules

- **Fix in session**: when you find a bug, fix it now — don't document and defer
- **Test, don't assume**: "the code looks right" does not count as ✅
- **Update VERIFY.md as you go**: don't batch all updates to the end — if the session is interrupted, partial progress should be saved
- **One checkpoint at a time**: complete test → fix → re-test → update before moving to next
- **Stale ✅ are not failures**: if a checkpoint was verified 8 days ago, re-test it, but start from a neutral stance
- **⚠ means untestable with current tools, not "probably fine"**: the reason for ⚠ must be specific (e.g., "requires Playwright MCP, not available in this session")
- **Never modify VERIFY.md section headers or IDs** — the IDs are stable references
- **If the server/app is not running**: try to start it (check CLAUDE.md for the start command). If it won't start, diagnose why and fix it before trying to test UI/API checkpoints.
- **Commit fixes as you go**: after fixing a ❌ checkpoint and confirming ✅, commit with `committer "fix: [description]" [changed files]` — don't batch all fixes into one commit


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.
