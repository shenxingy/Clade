# Agent Ground Rules

These rules enable autonomous, unattended operation across all projects.

## Commits
- Use `committer "type: message" file1 file2` for all commits — NEVER `git add .`
  - `committer` is at `~/.local/bin/committer` (symlinked from `~/.claude/scripts/committer.sh`)
  - This prevents parallel agents from staging each other's files
- Conventional commit format required: `feat/fix/refactor/test/chore/docs/perf`
- Commit small and often — each logical unit gets its own commit

## Communication
- When blocked on something requiring human input: write to `.claude/blockers.md` and stop
  - Format: `## Blocker [datetime]\n[what you need]\n[what you tried]`
- Don't loop retrying what you cannot fix — surface it clearly, then stop
- When starting a task, switching focus, or reaching a milestone: `vt title "action - context"` (if VibeTunnel installed)

## Autonomy
- Proceed WITHOUT asking for: file edits, test runs, builds, type-checks, lint
- Ask the user BEFORE: deleting files, modifying .env, running migrations, force-pushing
- **Bug fix without permission**: When bugs are clearly identified with a concrete fix and no destructive side effects — implement immediately. "Should we fix?" creates an unnecessary round-trip. Ask only when the fix is ambiguous, destructive, or has architectural tradeoffs.
- **Deployment topology**: Before checking localhost, scan for known deployment URLs (Tailscale internal domain, env vars like SITE_URL, INTERNAL_HOST). Default-to-localhost assumption produces wrong-context reads when the real service is remote.

## Context Management
- Context window ~80% full → run `/handoff` to save state, then start a new session with `/pickup`
- If `.claude/handoff-*.md` exists at session start → it is auto-loaded; run `/pickup` to activate
- Task queue pattern: the user may send multiple tasks in sequence — queue them, execute in order, don't wait between tasks

## Code Architecture (Claude Code-Optimized)

Structure code for efficient Claude Code tool usage:

- **File size**: Keep each file under 1500 lines (Read tool default = 2000 lines; under 1500 = readable in one shot)
- **Module count**: 4-6 modules per component. NOT 1 monolith, NOT 15+ fragments. Each additional file = 1 extra Read tool call.
- **Section markers**: Use clear `# ─── Section Name ───` headers so Grep can navigate within files
- **Edit-friendly**: Shorter files = fewer string duplicates = reliable Edit tool operations
- **Cohesion over separation**: Keep tightly coupled code in one file. Fix a bug by reading 1 file, not 3.
- **DAG imports**: Module dependency graph must be a strict DAG (no circular imports). Use lazy imports or duck typing (`Any`) to break potential cycles.
- **CSS extraction**: For HTML files with inline CSS > 200 lines, extract to separate `.css` file. Keep JS inline if tightly coupled (SPA globals, no module system).

## README & Docs

- README is a landing page, not a reference manual. Target: 200–300 lines.
- When README exceeds ~300 lines: move detailed sections to `docs/` files. Keep in README: install, key features table, command table, links to docs.
- Every README must have a TOC (GitHub anchor format) when it has 5+ sections.
- docs/ files: line 1 = language toggle, line 3 = back link to README, then internal TOC.
- The `/sync` skill checks: if README > 300 lines, flag sections that should move to docs/.

## Engineering Values

These guide all judgment calls — apply them when choosing between approaches:

- **DRY**: Flag repetition aggressively. Three near-identical blocks = refactor signal.
- **Tests non-negotiable**: Err toward too many tests, not too few. Cover failure paths, not just happy paths.
- **Engineered enough**: Not fragile/hacky, not premature-abstraction. Match complexity to actual requirements.
- **Edge cases over speed**: Thoughtfulness > velocity. Handle empty DB, first run, null input, concurrent access.
- **Explicit over clever**: Readable in 6 months > clever today. Name things clearly, avoid magic.

## Plan Mode

When entering Plan Mode for a non-trivial change, offer the user a choice before proceeding:

- **BIG CHANGE**: Work through interactively — Architecture → Code Quality → Tests → Performance, up to 4 top issues per section.
- **SMALL CHANGE**: One question per section only.

For each issue found: describe concretely (file:line), give 2–3 options with tradeoffs, give an opinionated recommendation, then ask before proceeding. Number issues (1, 2, 3) and letter options (A, B, C) so the user can respond unambiguously (e.g. "1A, 2B").

## Pre-Code Reflection

Before writing or modifying code, consider these failure patterns (learned from cross-project audits):

- **Settings/wiring**: If adding a config/setting/flag — trace the full path: definition → read → callsite → effect. Untested wiring = silent feature breakage.
- **Edge cases**: Does this work on first run (empty DB, no git history)? On a different OS (stat -c vs -f, path separators)? With empty/null/duplicate input?
- **Async boundaries**: If async — what happens when the world changes mid-flight? Subprocess needs kill+drain on timeout? Closure captures stale state? Lock granularity sufficient?
- **Security surface**: Am I validating at the system boundary? Any secrets, credentials, or user input flowing into commands/queries/URLs without sanitization?
- **Deploy gap**: Will this change actually reach the runtime? Source ≠ deployed. Config ≠ loaded. Defined ≠ called.
