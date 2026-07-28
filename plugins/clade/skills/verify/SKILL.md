---
name: verify
description: "Verify project behavior anchors — compilation, tests, and interaction checks after autonomous runs. NOT the Codex built-in /verify (which runs the app to observe a single change working) — this one walks the AGENTS.md \"Features (Behavior Anchors)\" list."
---

# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Plugin skills are namespaced. Invoke this workflow explicitly as
  `$clade:verify`; a bare `$name` does not select the installed Clade plugin.
- Read the nearest `AGENTS.md` files for repository instructions. If a project
  has only `CLAUDE.md`, treat it as legacy project guidance and read it too.
- Store new Clade working state under `.clade/` (or `~/.clade/` for personal
  state). Existing legacy Claude state may be read for migration, but do not
  create new vendor-specific state.
- A `/skill-name` reference means the corresponding Codex
  `$clade:skill-name` plugin skill, or the same workflow invoked naturally when
  explicit skill invocation is not available.
- Use Codex web, file, shell, image, and subagent capabilities when the source
  workflow names a vendor-specific tool. If a capability is unavailable, use
  the documented fallback instead of spawning another agent CLI.
- Paths such as `<plugin-root>/...` are relative to the installed Clade plugin
  containing this `SKILL.md`; resolve that root before invoking a helper.

## Canonical Clade workflow

You are the Verify skill. You check that a project's key behaviors still work after code changes.

---

## Step 1: Detect project type

Read `AGENTS.md` and look for `## Project Type` section. Extract:
- **Type**: web-fullstack, api-only, cli, ml-pipeline, library, skill-system, toolkit
- **Test command**: if provided, this is the primary verification method
- **Verify command**: if provided, run this as a smoke test

If `## Project Type` is missing, auto-detect by scanning the repo:
- `package.json` with `next`/`react` → web-fullstack
- `requirements.txt` with `fastapi`/`flask` → api-only
- `setup.py`/`pyproject.toml` with CLI entrypoints → cli
- `Cargo.toml` / `go.mod` → check for `main` package
- Fallback: unknown

## Step 2: Read behavior anchors

Read `AGENTS.md` and look for `## Features (Behavior Anchors)` section. Each line is a feature to verify:
```
- [feature-name]: [what should happen when user does X]
```

If no anchors found, note this gap and proceed with what's available.

## Step 3: Run verification strategy

Execute checks based on project type. Run all applicable strategies:

### Strategy: Test suite (all project types)
If a test command is specified in `## Project Type`:
```bash
timeout 120 {test_command}
```
Record: pass/fail + count of passing/failing tests.

**Context hygiene**: if `~/.clade/scripts/quiet-run.sh` is installed, wrap the command:
```bash
timeout 130 bash ~/.clade/scripts/quiet-run.sh {test_command}
```
Full output lands in `.clade/logs/quiet-*.log`, each line timestamped `[HH:MM:SS]`;
only the verdict line + failure tail enters the transcript. The exit code is
mirrored, so pass/fail detection is unchanged. **Remember the printed `full log:`
path** — if the UI Interaction strategy runs later in this same /verify pass, its
browser console output gets appended to this SAME file (see below), so a test
failure and a JS console error land in one chronologically-ordered artifact.

If no test command but common test patterns exist:
- `timeout 120 pytest` / `timeout 120 python -m pytest` (Python)
- `timeout 120 npm test` / `timeout 120 npx jest` (Node)
- `timeout 120 cargo test` (Rust)
- `timeout 120 go test ./...` (Go)

Try the likely command. If it works, report results. If not, skip.
**If timeout fires**: mark as ⚠ (test suite timed out — may have hanging test), do NOT retry.

### Strategy: Compile/type check
- Python: `python -m py_compile {main_files}` or `mypy` if configured
- TypeScript: `npx tsc --noEmit`
- Rust: `cargo check`
- Go: `go build ./...`

### Strategy: Verify command (smoke test)
If a verify command is specified in `## Project Type`, run it.

### Strategy: Behavior anchor check
For each anchor in `## Features`:
1. Determine if the anchor is testable with available tools
2. If testable: run a quick check (e.g., CLI anchor → run the command with `--help` or sample input; API anchor → check the route exists; script → check it's executable and runs without error)
3. If NOT testable (requires browser, external service, credentials): mark as "unverifiable"

Anchor test examples:
- `install.sh: copies files to ~/.clade/` → `bash install.sh --dry-run` or check the script is syntactically valid: `bash -n install.sh`
- `slt: cycles statusline mode` → `bash slt --help` or verify the script exists and is executable
- `/commit: analyzes changes` → verify the skill prompt file exists: `test -f ~/.clade/skills/commit/prompt.md`
- CLI tool → `{tool} --help` should exit 0
- API endpoint → check route is defined in source code (grep)

### Strategy: UI Interaction (frontend only)

**Conditions** — ALL must be true:
1. Project type is `web-fullstack` (from AGENTS.md `## Project Type`)
2. Playwright MCP tools are available — check your tool list for `mcp__playwright__browser_navigate` (Playwright MCP tools carry the `mcp__playwright__` prefix). If absent, the browser MCP is not wired in — skip.

If conditions are not met, set `INTERACTION_RESULT: skipped` and move on.

> Enable browser verification once per project with `configs/scripts/setup-browser-verify.sh <project_dir>` — it adds the Playwright MCP to `.clade/mcp.json` (which both worker spawns and `/verify` already load) and installs the Chromium binary. Below, `browser_navigate`/`browser_snapshot`/etc. are shorthand for the `mcp__playwright__`-prefixed tools.

**Flow:**

1. Run `configs/scripts/ensure-dev-server.sh` (no args needed — it reads `AGENTS.md`'s `Frontend: ... port NNNN` line itself, defaulting to 3000). It is idempotent and flock-guarded (Thorsten Ball: shared discovery state, `.clade/dev-server.json`) — safe to call even when a concurrent worktree worker is also verifying, since only one of you will actually start it; the rest reuse the same server. Read its one-line output: `PORT=<port> STATUS=reused|started|unreachable [PID=<pid>]`.

2. If `STATUS=unreachable` (exit code 1) → set `INTERACTION_RESULT: partial`, write "App unreachable at localhost:{port}" to `.clade/playwright-issues.md`, and move on. Do NOT block the verify. Do NOT retry startup yourself — the script already tried for 30s.

3. Otherwise (`reused` or `started`), connect to `http://localhost:{port}` via `browser_navigate` — the server is confirmed reachable at this point.

4. Take a `browser_snapshot` of the home page to get the accessibility tree.

5. Walk up to **5 pages** (home + up to 4 linked pages):
   - For each page: `browser_snapshot` → identify interactive elements (buttons, forms, links, inputs)
   - Click/fill key interactive elements → check for errors, broken states, console errors
   - If a page requires authentication and no test credentials are available in AGENTS.md, mark as unverifiable — do NOT report login failure as a `[BUG]`
   - Take another snapshot after interactions to verify state changes

6. Call `browser_console_messages` once (after the page walk, not per-page — this
   is a summary read, not a live stream). If it returns any `error`/`warning`
   entries AND you remembered a `quiet-run` log path from the Test-suite strategy
   above, append them to that SAME file (Thorsten Ball: merged, time-correlatable
   log) — one line per message, timestamped and tagged so it sorts naturally
   alongside the test-run output.

   **Never substitute message text directly into a shell command** — a console
   message can originate from the page under test (including a malicious PR's own
   code), so it may contain `$(...)`, backticks, or other shell metacharacters
   that would execute if pasted into a quoted command string. Instead, for each
   message: write it verbatim to a scratch file with the **file-editing tools** (not
   shell-interpreted, so no escaping is needed), then append using only paths/
   fixed text in the shell command, never the message content itself:
   ```bash
   printf '[%s] [browser] ' "$(date +%H:%M:%S)" >> <remembered log path>
   cat <scratch file path> >> <remembered log path>
   printf '\n' >> <remembered log path>
   ```
   If no quiet-run log path exists (no test command / quiet-run not used), skip the
   append — the console findings still feed into `.clade/playwright-issues.md` below.

7. Evaluate:
   - Does navigation work? Are pages rendering content (not blank/error)?
   - Do interactive elements respond? Are forms submittable?
   - Any JS errors visible in the page? Any "undefined"/"null"/"NaN" rendering?
   - Is the UX intuitive? (layout makes sense, text is readable, actions are discoverable)

8. Write findings to `.clade/playwright-issues.md` (overwrite, do not append):
   - `[BUG]` tag for broken functionality (crashes, errors, broken flows, missing data)
   - `[UX]` tag for usability issues (confusing layout, missing feedback, accessibility gaps)
   - Include which page/element was affected

9. Set result:
   - `INTERACTION_RESULT: pass` — all flows work, no bugs found
   - `INTERACTION_RESULT: partial` — some flows unverifiable (app didn't start, pages unreachable)
   - `INTERACTION_RESULT: fail` — broken UI or unexpected errors found (`[BUG]` items exist)

**Bounds:** Max 2 minutes of interaction time. Max 5 pages. If time runs out, report what you found so far.

### Strategy: Lint/format (optional, lightweight)
Only if project has linting configured (`.eslintrc`, `ruff.toml`, etc.):
```bash
{lint_command}
```
Report warnings but don't count as failures.

## Step 4: Check VERIFY.md coverage (if present)

If `VERIFY.md` exists in the project root, read it and report coverage status.

This is a **read-only** step — do NOT fix anything here. `/verify` reports; `/review` fixes.

1. Count checkpoints by status: ✅ / ❌ / ⚠ / ⬜
2. Identify any ❌ checkpoints — these are confirmed regressions
3. Identify ⬜ checkpoints — these are coverage gaps (untested)

**Impact on VERIFY_RESULT:**
- Any ❌ checkpoint in VERIFY.md → VERIFY_RESULT = `fail` (confirmed regression)
- Only ⬜ checkpoints (no ❌) → VERIFY_RESULT = `partial` at most (gaps, not regressions)
- All ✅ or ⚠ → VERIFY.md does not degrade VERIFY_RESULT

If VERIFY.md does not exist: skip this step silently. Output `VERIFY_COVERAGE: none` in footer.

---

## Step 5: Produce report

Write a human-readable summary, then the machine-parseable footer.

### Summary format:
```
## Verify Report — {project_name}

### Test Suite
{pass/fail/skip details}

### Compile Check
{pass/fail details}

### Behavior Anchors
- [anchor-name]: PASS / FAIL (reason) / UNVERIFIABLE (reason)
- ...

### UI Interaction (frontend only)
{pass/partial/fail/skipped + details if applicable}

### VERIFY.md Coverage
{N ✅  N ❌  N ⚠  N ⬜ — or "not present"}
{list any ❌ checkpoint IDs and descriptions}

### Notes
{any observations, warnings, suggestions}
```

### Structured issue checklist (`.clade/verify-issues.md`)

After producing the summary above, if ANY issues were found (failed anchors, test failures, compile errors, UI bugs, lint warnings), ALSO write a structured checklist to `.clade/verify-issues.md`.

**Rules:**
- Overwrite each run (not append) — old issues are stale
- Only create this file when there ARE issues. If everything passes, do NOT create it.
- One `- [ ]` checkbox per issue, one line each
- Use sections below — omit sections with no issues

**Format:**
```
## Failed Anchors
- [ ] anchor-name: brief description of failure

## Test Failures
- [ ] test_module::test_name: assertion error / brief reason

## Compile Errors
- [ ] file:line: error description

## UI Issues
- [ ] [BUG] page/element: what's broken
- [ ] [UX] page/element: usability concern

## Lint Warnings
- [ ] file:line: warning code + message
```

**Copying from playwright-issues.md:** If `.clade/playwright-issues.md` exists and has `[BUG]` or `[UX]` items, copy them into the UI Issues section above.

**Annotation convention (for human reviewers):**
Users can annotate each checkbox to control what happens next:
- `[fix]` → auto-creates a fix task on next run
- `[skip]` → moved to `.clade/skipped.md` (won't be raised again)
- `[wontfix]` → moved to `.clade/skipped.md` with wontfix reason

Example: `- [ ] [fix] slt: cycles to wrong mode after "off"`

Unannotated items remain in the file for next review.

### Footer (MUST be the last 5 lines — start.sh greps these):

```
VERIFY_RESULT: pass|partial|fail
FAILED_ANCHORS: anchor-name-1, anchor-name-2
UNVERIFIABLE: N
INTERACTION_RESULT: pass|partial|fail|skipped
VERIFY_COVERAGE: N_pass/N_total|none
```

**Decision rules for VERIFY_RESULT:**
- **pass**: all testable anchors pass, test suite passes (or no test suite), compile succeeds, no ❌ in VERIFY.md
- **partial**: some anchors are unverifiable (no test strategy, missing tools, insufficient coverage) BUT no testable anchor is regressing. Also used when: no test suite exists, no anchors defined, verify command not provided, or VERIFY.md has ⬜ gaps but no ❌ failures.
- **fail**: at least one testable anchor is now broken/regressing, OR test suite has new failures, OR compile errors introduced, OR VERIFY.md has ❌ checkpoints

**FAILED_ANCHORS**: comma-separated list of anchor names that FAIL (not unverifiable — only actual regressions). Use `none` if no failures. NEVER leave blank — blank line breaks grep in start.sh.

**UNVERIFIABLE**: count of anchors that could not be tested (integer). `0` if all anchors were testable.

**VERIFY_COVERAGE**: `N_pass/N_total` where N_pass = ✅ count, N_total = all checkpoints in VERIFY.md. Use `none` if VERIFY.md does not exist.

**INTERACTION_RESULT**: UI interaction test outcome.
- `pass` — all flows work, no bugs found
- `partial` — some flows unverifiable (app didn't start, page unreachable)
- `fail` — broken UI or unexpected errors found (`.clade/playwright-issues.md` has details)
- `skipped` — not a frontend project or no Playwright MCP available

## Rules

- Run verification commands with `the configured Codex permission policy` context (the caller handles this)
- Never modify project code — this is a read-only verification skill
- Wrap ALL subprocess calls with `timeout N`: test suites `timeout 120`, curl/DB queries `timeout 30`, compile checks `timeout 60`. If timeout fires → mark ⚠, do NOT retry
- Fail-open on infrastructure errors (can't install deps, missing tools): mark as unverifiable, not fail
- When in doubt between partial and fail: if you CAN test it and it broke → fail. If you CAN'T test it → partial.


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.clade/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.

## Additional skill reference

# Verify Skill

Post-iteration verification used by `start.sh` to check that behavior anchors still pass after autonomous work. Not user-invocable — called internally by the autonomous loop.

## Delivery completion

If this workflow changes files or external state:

- Inspect the real final state before responding, including `git status` for a
  repository task.
- Never report `DONE` while task-owned changes are uncommitted. Use or continue
  `$clade:delivery` and create a repository-compliant checkpoint or preserve
  the work when committing is unavailable.
- When the user request or trusted repository policy makes publication,
  deployment, or live verification part of the task, do not silently downgrade
  the result to local-only work.
- If a required delivery transition lacks authority, credentials, a destination,
  or reachable external state, report `BLOCKED` or `NEEDS_CONTEXT` rather than
  appending a "not committed/pushed/deployed" caveat after `DONE`.
