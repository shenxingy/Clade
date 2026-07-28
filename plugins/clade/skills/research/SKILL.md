---
name: research
description: "Research external tools/competitors for a topic and write findings to BRAINSTORM.md (project topics) or ~/.clade/research/ (personal topics). Use when user says \"/research [topic]\"."
---

# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Plugin skills are namespaced. Invoke this workflow explicitly as
  `$clade:research`; a bare `$name` does not select the installed Clade plugin.
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

Research external tools/competitors/approaches for a given topic and write a structured analysis to BRAINSTORM.md (project-scoped topics) or `~/.clade/research/` (personal topics — see Rules).

## Capability Detection (run first)

Detect available research tools before starting:

| Tier | Tools available | What you can do |
|------|----------------|----------------|
| **Tier 0** — Training data only | No MCP tools, web search unavailable | Use knowledge cutoff (Aug 2025). Mark all results with `⚠ Training data only — verify current status`. |
| **Tier 1** — web search available | `web search` tool responds | Search with current year (2026) for up-to-date data. Max 5 searches. |
| **Tier 2** — web search + web page fetch | Both tools available | Search for results, then fetch primary sources for depth. |

Test by attempting a `web search` call. If it fails or returns no results → fall back to Tier 0 and note it prominently in the output.

## Steps

0. **FIRST: Determine if topic is personal or project-scoped** (see Personal Topic Detection below)
   - If **personal** → skip step 1, go to step 5 (write to ~/.clade/research/ instead)
   - If **project-scoped** → proceed with steps 1-5 (write to BRAINSTORM.md)
1. Read `VISION.md`, `TODO.md`, and `BRAINSTORM.md` for project context (understand what already exists before researching)
2. Detect research tier (see above). Run web search with current year (2026) for 3-5 relevant tools/approaches. Max 5 searches.
3. For each result: extract key features, pricing/licensing, UX patterns, what they do well, what they do poorly
4. Compare against current VISION.md — what gaps does this research reveal? what patterns can we borrow?
5. Write findings:

```markdown
## [Research] {date} — {topic}

### Tools surveyed
| Tool | Key features | What to borrow |
|---|---|---|
| ... | ... | ... |

### Gaps vs current VISION
- ...

### Recommended additions to TODO.md
- [ ] ...
```

## Personal Topic Detection

Before starting research, check ALL of these:

| Criterion | Personal | Project-Scoped |
|-----------|----------|---|
| **Ownership** | User's own infrastructure, accounts, hardware, tools | Project's domain, codebase, user's work assignments |
| **Scope** | User's life decisions, personal setup, self-improvement | Product features, tech decisions, competitor analysis |
| **Audience** | Only the user cares | Project team cares, code review will see it |
| **Reusability** | Specific to user's context, not portable | Patterns generalizable to the project |

**Apply the "Stranger Clone Test"**: If someone cloned this repo, would they learn anything about the user's personal life, accounts, or infrastructure? If YES → PERSONAL. If NO → project-scoped.

**Examples:**
- ✅ PERSONAL: "what laptop to buy", "best personal finance apps", "home server setup", "password manager comparison for my accounts"
- ✅ PROJECT-SCOPED: "auth libraries for Node", "UI component libraries", "competitor analysis vs SalesForce", "LLM pricing tiers"

## Rules
- Always read VISION.md first — generic suggestions are noise, project-specific insights are signal
- Always search with year 2026 for up-to-date information
- Be specific and actionable — "add OAuth2 login flow like tool X's 2-click setup" not "add authentication"
- Mark entries as `[Research]` (not `[AI]`) so they're distinguishable in BRAINSTORM.md
- Do NOT auto-process into GOALS.md or TODO.md — just write to BRAINSTORM.md inbox or personal research dir
- **Personal-topic routing**: If determined to be PERSONAL in step 0, write report to `~/.clade/research/{YYYY-MM-DD}-{slug}.md` INSTEAD of BRAINSTORM.md — personal context must never land in a git-tracked project file


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.clade/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.

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
