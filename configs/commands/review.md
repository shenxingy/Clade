Perform a comprehensive tech debt review of this project. Work through each section systematically, using Glob/Grep/Read to gather evidence before making any claims. Do NOT guess — only report issues you can verify in the code.

## Instructions

- Run this review from the project root directory
- Read CLAUDE.md first to understand project conventions
- Be specific: cite file paths and line numbers for every finding
- Prioritize: label each finding as 🔴 Critical / 🟡 Warning / 🔵 Info
- Be honest: if a section looks clean, say so — don't fabricate issues
- At the end, produce a single actionable summary

---

## Phase 1: Project Document Health

Read all project documents and assess their alignment.

### 1.1 Document Existence Check
Check if these files exist at the project root: `CLAUDE.md`, `GOALS.md`, `TODO.md`, `PROGRESS.md`, `BRAINSTORM.md`
- Report which ones are missing

### 1.2 Document Consistency Audit
Read each existing document and answer:
- **GOALS ↔ TODO alignment**: Do TODO items actually trace back to GOALS? Are there goals with no corresponding TODOs? Are there orphan TODOs that serve no goal?
- **TODO ↔ PROGRESS alignment**: Do completed items in TODO match what's recorded in PROGRESS? Are there TODO items marked done but missing from PROGRESS? Are there PROGRESS entries about work not reflected in TODO?
- **PROGRESS lessons applied**: Are lessons/failures from PROGRESS reflected in current TODO priorities or CLAUDE.md guardrails? Or are past mistakes being repeated?
- **BRAINSTORM inbox status**: Is BRAINSTORM.md empty (processed) or has it accumulated unprocessed ideas?
- **CLAUDE.md accuracy**: Does CLAUDE.md reflect the actual current state of the project (tech stack, conventions, file structure)? Or is it outdated?

### 1.3 Development Direction Check
Based on GOALS.md and the current codebase state:
- Is the project moving toward its stated goals?
- Are there signs of scope creep (work being done that doesn't serve any goal)?
- Are priorities appropriate (P0 items done before P1, etc.)?
- Any stale TODOs that should be archived or re-prioritized?

---

## Phase 2: Code Quality

### 2.1 Dead Code & Unused Artifacts
Search for:
- Unused imports (sample key directories, not exhaustive)
- Exported functions/components that are never imported elsewhere
- Commented-out code blocks (more than 3 lines)
- Files that appear orphaned (not imported by anything)

### 2.2 Code Duplication
Look for:
- Near-identical functions or logic blocks across files
- Copy-pasted patterns that should be abstracted
- Repeated constants or magic numbers/strings

### 2.3 Naming & Convention Consistency
Check:
- Are naming conventions consistent (camelCase vs snake_case, file naming patterns)?
- Do patterns match what CLAUDE.md prescribes?
- Are there files or directories that break the established structure?

### 2.4 Comment Quality
Scan for:
- `TODO`, `FIXME`, `HACK`, `XXX`, `TEMP`, `WORKAROUND` comments — list them all with file:line
- Stale comments that describe code that has changed
- Comments that just restate the code (noise)
- Missing comments where complex logic needs explanation

### 2.5 Type Safety & Error Handling
Check:
- `any` type usage (TypeScript) or missing type hints (Python)
- Bare `except`/`catch` blocks that swallow errors silently
- Missing error handling at system boundaries (API calls, file I/O, DB queries)
- Unchecked null/undefined access patterns

---

## Phase 3: Potential Bugs & Risks

### 3.1 Common Bug Patterns
Search for:
- Race conditions (shared mutable state, missing locks/transactions)
- Resource leaks (unclosed connections, streams, file handles)
- Off-by-one errors in loops or pagination
- Hardcoded values that should be configurable (URLs, ports, timeouts, secrets)

### 3.2 Security Surface
Check:
- Secrets or API keys committed in code (not just .env — also config files, constants)
- SQL/NoSQL injection vectors (raw query construction)
- XSS vectors (unescaped user input in templates/JSX)
- Missing input validation at API boundaries
- Overly permissive CORS or auth configurations

### 3.3 Dependency Health
If package.json / pyproject.toml / requirements.txt exists:
- Are there obviously outdated major versions?
- Are there known deprecated packages?
- Are there redundant dependencies (multiple libs doing the same thing)?

---

## Phase 4: Architecture & Maintainability

### 4.1 Separation of Concerns
- Are business logic, data access, and presentation properly separated?
- Are there god files/functions that do too much (>300 lines)?
- Is there proper layering (routes → services → data access)?

### 4.2 Configuration Management
- Is all configuration externalized to env vars or config files?
- Are there environment-specific hardcoded values?

### 4.3 Test Coverage (Quick Assessment)
- Do test files exist? What's the general coverage pattern?
- Are critical paths (auth, payments, data mutations) tested?
- Are there test files that are empty or have skipped tests?

---

## Output Format

After completing all phases, produce a summary in this format:

```markdown
# Tech Debt Review — [Project Name]
**Date**: YYYY-MM-DD
**Reviewed by**: Claude Code

## Executive Summary
[2-3 sentences: overall health assessment]

## Document Health
[Summary of Phase 1 findings]

## Top Findings (by priority)

### 🔴 Critical (fix now)
1. [Finding with file:line reference]

### 🟡 Warning (fix soon)
1. [Finding with file:line reference]

### 🔵 Info (consider when convenient)
1. [Finding with file:line reference]

## Metrics Snapshot
- Dead code / unused artifacts found: N
- TODO/FIXME/HACK comments: N
- `any` types or missing type hints: ~N
- Potential security issues: N
- Document consistency score: X/5

## Recommended Next Steps
1. [Most impactful action]
2. [Second most impactful action]
3. [Third most impactful action]
```

Present the full report directly in the conversation output. Do NOT save the report to a file — it becomes stale as soon as findings are fixed. If the user explicitly asks to save it, then write it to `docs/reviews/YYYY-MM-DD-tech-debt-review.md`.

## After the report: update TODO.md

After printing the report, automatically update `TODO.md`:

1. Read the current TODO.md (create it if missing)
2. Find or create a section `## Tech Debt` (add at the end if absent)
3. Add each 🔴 Critical and 🟡 Warning finding as an unchecked item:
   ```
   ## Tech Debt
   - [ ] 🔴 [brief description] (`file:line`)
   - [ ] 🟡 [brief description] (`file:line`)
   ```
4. Skip findings already present in TODO.md (match by description)
5. Skip 🔵 Info items — those are optional and shouldn't pollute the backlog
6. Report how many items were added:
   ```
   TODO.md updated: added 3 items (2 critical, 1 warning) to ## Tech Debt
   ```
