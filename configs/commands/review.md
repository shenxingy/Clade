Perform a comprehensive project review — then **fix every issue found**. Repeat until the project is clean. Do NOT just report and stop.

## Ground Rules

- Read CLAUDE.md first. Follow project conventions exactly.
- Every finding must cite `file:line`. No guessing.
- Fix Critical and Warning issues immediately after finding them — don't batch everything to the end.
- After each fix, verify it didn't break anything nearby.
- Loop: after completing all phases, re-run a quick scan. If new Critical/Warning issues appear, fix them and scan again. Max 3 full iterations.
- When a section is clean, say so — don't fabricate issues.

---

## Phase 0: Context

1. Read `CLAUDE.md` — understand stack, conventions, forbidden patterns, file structure.
2. Detect project type: web frontend (HTML/CSS/JS/TS/React), backend (Python/Go/Rust/Node), CLI tool, library, or mixed. This determines which checks apply.
3. Read `VISION.md` and `TODO.md` to understand stated goals and current state.
4. Note: verify_cmd from `.claude/orchestrator.json` if present — run it as a sanity check at each loop end.

---

## Phase 1: Document Health & Goal Alignment

### 1.1 Document Existence
Check for: `CLAUDE.md`, `VISION.md`, `TODO.md`, `PROGRESS.md`, `BRAINSTORM.md`
- Report missing files as 🟡 Warning.

### 1.2 Document Consistency
- **VISION ↔ TODO**: Do all TODO items trace to a VISION goal? Orphan TODOs with no stated goal → flag.
- **TODO ↔ PROGRESS**: Items marked `[x]` in TODO but absent from PROGRESS → flag. PROGRESS entries about work not in TODO → flag.
- **PROGRESS lessons applied**: Are past mistakes in PROGRESS reflected in CLAUDE.md guardrails? If not, add the missing guardrails now.
- **BRAINSTORM**: If non-empty, note it as unprocessed.
- **CLAUDE.md accuracy**: Does it describe the actual current tech stack and structure? If outdated, update it.

### 1.3 Feature/Goal Consistency *(new)*
For each major feature stated in VISION.md or completed in TODO.md:
- Search the codebase for the corresponding implementation.
- If a feature is claimed done but has no code → 🔴 Critical.
- If significant code exists for a feature not in VISION/TODO → possible scope creep → 🟡 Warning.
- If a VISION phase is marked ✓ but TODO still has open `[ ]` items under it → 🔴 Critical.

---

## Phase 2: Code Structure & File Health

### 2.1 File Size Enforcement *(Claude Code constraint)*
Find all source files. For each file over the limit:
- **>1500 lines**: 🔴 Critical — split it. Claude Code's Read tool reads 2000 lines by default; files >1500 are unreliable to edit. Extract logical sections into separate files following existing module patterns.
- **1000–1500 lines**: 🟡 Warning — plan a split. Note it.
- Files that are large HTML with inline JS/CSS: extract CSS >200 lines to `.css`; extract JS if it has its own module logic.

When splitting, verify: no circular imports introduced, all existing call sites updated, tests still pass.

### 2.2 Module Count
Per component/feature area: count files. Flag if:
- **1 monolith file** doing everything: 🟡 Warning — identify logical sections to extract.
- **>10 tiny fragments**: 🟡 Warning — consider consolidating tightly coupled pieces.
- Target: 4–6 modules per major component.

### 2.3 Import Graph (DAG check)
Search for circular imports:
- Python: look for `from A import B` where B also imports A (direct or transitive).
- TypeScript: same pattern with `import`.
- Flag any cycle as 🔴 Critical. Break cycles using lazy imports or dependency inversion.

### 2.4 Section Markers
For files >200 lines, check if logical sections are marked with `# ─── Section Name ───` (or `// ─── Section Name ───` for JS/TS). Missing markers in large files → 🔵 Info — add them.

### 2.5 Dead Code & Unused Artifacts
- Unused imports (scan key directories)
- Exported functions/components never imported elsewhere
- Commented-out code blocks (>3 lines) — remove them
- Files that appear orphaned (not imported anywhere)

Fix: remove confirmed dead code. If uncertain about orphaned files, note them but don't delete.

### 2.6 Code Duplication
- Near-identical functions across files → extract to shared utility
- Repeated constants/magic numbers → define once, reference everywhere
- Copy-pasted blocks >10 lines → abstract into a function

### 2.7 Naming & Conventions
- Are naming conventions consistent (camelCase/snake_case, file naming)?
- Match against CLAUDE.md prescriptions.
- Fix: rename inconsistent identifiers if safe (search all call sites first).

---

## Phase 3: Lint & Compilation

### 3.1 Detect and Run Linter
Based on project type, run the appropriate tool and fix ALL errors:

| Stack | Lint command | Type check |
|-------|-------------|------------|
| TypeScript | `npx eslint . --fix` (if config exists) | `tsc --noEmit` |
| Python | `ruff check --fix .` or `flake8` | `mypy .` or `pyright` |
| Rust | `cargo clippy --fix` | `cargo check` |
| Go | `go vet ./...` | `go build ./...` |
| Shell | `shellcheck configs/hooks/*.sh configs/scripts/*.sh` | — |

If no linter config exists, run the type checker alone.

### 3.2 Fix Lint Errors
Fix every error the linter reports. Re-run until exit code 0.
- If auto-fix isn't available, fix manually.
- If a lint rule is genuinely wrong for this project, note it but don't suppress it silently.

### 3.3 Build/Compile Check
Run the project's build command if it exists (from CLAUDE.md or detected):
- TypeScript: `tsc --noEmit`
- Python: `python -m py_compile $(find . -name "*.py" -not -path "*/venv/*")`
- Rust: `cargo build`
- Go: `go build ./...`

Fix all compilation errors before moving to the next phase.

### 3.4 Run Test Suite
Run the project's test command (from CLAUDE.md or detected):
- Python: `pytest` or `python -m pytest tests/ -v`
- TypeScript: `npm test` or `npx jest`
- Rust: `cargo test`
- Go: `go test ./...`

Fix all test failures before moving to the next phase. If no test command is found, note it as 🟡 Warning.

### 3.5 CI Workflow Check
If `.github/workflows/` exists, read the CI config and verify all CI steps would pass locally. The goal: no push should break CI.

---

## Phase 4: Comments & Documentation

### 4.1 Inline Comment Quality
Scan for and fix:
- `TODO`, `FIXME`, `HACK`, `XXX`, `TEMP`, `WORKAROUND` — list all with `file:line`. Resolve what can be resolved now; add to TODO.md for the rest.
- Comments that just restate the code ("increment counter by 1" above `i += 1`) — remove them.
- Stale comments that describe behavior the code no longer has — update or remove.

### 4.2 Missing Documentation
For public functions/classes/API endpoints in the main codebase:
- Missing docstrings on non-obvious functions → add them (1 sentence max — what it does and why, not how).
- Complex algorithms with no explanation → add a short comment before the block.
- Don't add docstrings to simple getters, trivial wrappers, or internal helpers.

### 4.3 README / Docs Accuracy
- Does README reflect the actual commands, file structure, and behavior?
- Are code examples in docs still valid (check against actual code)?
- Fix any outdated examples or stale command references.

---

## Phase 5: Bugs & Error Handling

### 5.1 Common Bug Patterns
Search for and fix:
- **Race conditions**: shared mutable state accessed from multiple threads/tasks without locks or transactions. Add appropriate synchronization.
- **Resource leaks**: file handles, DB connections, network sockets opened but not closed in all paths. Add `finally`/`defer`/`with` blocks.
- **Off-by-one errors**: loop bounds, slice indices, pagination math. Check by tracing with concrete values.
- **Hardcoded values**: URLs, ports, timeouts, credentials that should be in config. Move to env vars or config files.
- **Missing null/undefined checks**: direct property access on possibly-null values. Add guards.

### 5.2 Error Handling at Boundaries
Every system boundary must handle errors:
- **API calls**: handle network errors, non-2xx responses, timeouts.
- **File I/O**: handle missing files, permission errors, disk full.
- **DB queries**: handle connection errors, constraint violations, null results.
- **User input**: validate and sanitize at the entry point.
- Fix: wrap unguarded boundary calls in proper error handling. Never swallow errors silently (`except: pass` or empty `catch {}`).

### 5.3 Type Safety
- `any` type usage in TypeScript → replace with proper types where feasible.
- Missing Python type hints on public functions → add them.
- Bare `except`/`catch` → specify the exception type.

---

## Phase 6: Security

### 6.1 Secrets & Credentials
- Scan for hardcoded API keys, passwords, tokens in any file (not just `.env`):
  - Search for patterns: `api_key =`, `secret =`, `password =`, `token =`, `Bearer `, `sk-`, `ghp_`
  - Check config files, constants files, test fixtures.
  - If found: 🔴 Critical — move to env var, add to `.gitignore`, note that git history may need cleaning.

### 6.2 Injection Vectors
- **SQL injection**: raw string-formatted queries → use parameterized queries.
- **Shell injection**: user input in `subprocess`/`exec` calls → use argument lists, not strings.
- **XSS**: unescaped user content in HTML/JSX → use proper escaping or sanitization.
- **Path traversal**: user-supplied file paths without normalization/validation → add path validation.

### 6.3 Auth & Access Control
- API routes that should require auth but don't → 🔴 Critical.
- Missing rate limiting on auth endpoints → 🟡 Warning.
- Overly permissive CORS (`*` on production APIs) → 🟡 Warning.
- Error messages that leak implementation details (stack traces, DB schemas) → replace with generic messages.

### 6.4 Dependency Vulnerabilities
If `npm audit`, `pip-audit`, or `cargo audit` is available:
- Run it.
- Report Critical/High severity findings.
- Fix what can be fixed by version bumping.

---

## Phase 7: Architecture & Maintainability

### 7.1 Separation of Concerns
- Business logic mixed into route handlers or UI components → extract to service layer.
- Data access logic scattered across the app → consolidate to repository/DAO pattern.
- God functions (>100 lines doing multiple distinct things) → split at logical boundaries.

### 7.2 Configuration Management
- Any environment-specific hardcoded values → externalize to env vars.
- Multiple config files with overlapping concerns → consolidate.

### 7.3 Test Coverage (quick assessment)
- Are test files present? Do critical paths have tests?
- Empty test files or fully-skipped test suites → 🟡 Warning.
- Don't write new tests during review — note gaps for later.

---

## Phase 8: UI/UX (skip if project has no frontend)

Detect frontend: look for `.html`, `.tsx`, `.jsx`, `.vue` files, or a `web/` directory.

### 8.1 Event Binding
For every interactive element (button, form, link, input):
- Verify the handler exists and is attached (not just defined).
- Verify the handler actually does what the label implies.
- Buttons with no `onclick`/`addEventListener`/event prop → 🔴 Critical.
- Links with `href="#"` and no click handler → 🟡 Warning.

### 8.2 Form Logic
- Required fields validated before submit?
- Submit button disabled or shows loading state during async operations?
- Success/error feedback shown to user after form submit?
- Fix: add missing validation, disable-during-submit, and feedback.

### 8.3 Error States
- What happens if an API call fails? Is an error message shown?
- What happens on empty data? Is an empty state rendered?
- Fix: add `catch` → show error message, add empty-state UI where missing.

### 8.4 Loading States
- Async operations that show no loading indicator → 🟡 Warning.
- Data displayed before it's loaded (flash of incorrect content) → 🟡 Warning.

### 8.5 Navigation Consistency
- All navigation paths lead somewhere valid (no dead ends)?
- Back button behavior consistent with user expectations?
- Breadcrumbs or titles reflect current location?

---

## Loop Logic

After completing Phases 1–8 and fixing all issues found:

1. Run a **quick re-scan** — search for: remaining `🔴 Critical` patterns, lint errors (re-run linter), compilation errors (re-run build).
2. If any Critical or Warning issues remain from the fixes themselves (e.g., a split introduced a new import cycle), fix them.
3. Repeat until: zero Critical, zero Warning from re-scan. OR iteration limit (3 full passes) reached.
4. On reaching the iteration limit: document remaining issues clearly — don't silently stop.

---

## Output Format

After all iterations, produce a final summary:

```markdown
# Review Complete — [Project Name]
**Date**: YYYY-MM-DD
**Iterations**: N
**Fixed**: X issues

## What Was Fixed
- [Brief description of each fix with file:line]

## Remaining Issues (if any)
### 🔴 Critical (could not fix automatically)
- [reason it wasn't fixed]

### 🟡 Warning (deferred)
- [brief description + file:line]

## Clean Sections
[List phases/areas that are fully clean]

## Metrics
- Files split for size: N
- Lint errors fixed: N
- Security issues resolved: N
- Dead code removed: N
- Comments cleaned up: N
```

## After the Summary: update TODO.md

For any remaining unfixed Critical/Warning issues:
1. Find or create `## Tech Debt` section in TODO.md.
2. Add each as `- [ ] 🔴/🟡 [description] (\`file:line\`)`.
3. Skip items already present. Skip 🔵 Info items.
4. Report: `TODO.md updated: added N items`.

## After TODO.md: commit and push

Commit all changes made during the review. Split by logical category:

1. **Code fixes** — group by phase or feature area. Use `committer` to stage only the relevant files:
   - `committer "fix: resolve lint errors" file1 file2 ...`
   - `committer "refactor: split large file into modules" file1 file2 ...`
   - `committer "fix: security issues — path traversal, injection" file1 file2 ...`
2. **Doc updates** — TODO.md, PROGRESS.md, CLAUDE.md changes go in one commit:
   - `committer "docs: review findings — update TODO + docs" TODO.md PROGRESS.md ...`
3. **Push** — after all commits: `git push`
