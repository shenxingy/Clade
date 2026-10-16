Research external tools/competitors/approaches for a given topic and write a structured analysis to BRAINSTORM.md (project-scoped topics) or `~/.claude/research/` (personal topics — see Rules).

## Retrieval routing (run first)

Load the installed `web-search` skill when available. It selects native tools
for small lookups and TinyFish for bulk/recurring collection or unavailable
native retrieval, with excerpts, bounded output, private caching and explicit
failure handoffs. Keep analysis in this session; do not launch another model
CLI. Provider documentation tools and user-selected/excluded providers take
precedence. If the skill is absent, use available native search and page tools.

Start with at most 5 targeted searches. Expand only when an unresolved evidence
gap justifies it. One empty search is not proof that live research is unavailable:
revise the query or use the configured fallback. If all available retrieval
paths fail, label current facts unverified; do not pass training knowledge off
as live research.

## Steps

0. **FIRST: Determine if topic is personal or project-scoped** (see Personal Topic Detection below)
   - If **personal** → skip step 1, go to step 5 (write to ~/.claude/research/ instead)
   - If **project-scoped** → proceed with steps 1-5 (write to BRAINSTORM.md)
1. Read `VISION.md`, `TODO.md`, and `BRAINSTORM.md` for project context (understand what already exists before researching)
2. Follow retrieval routing above. Search for 3-5 relevant tools/approaches and read primary sources. Add date filters when freshness matters; do not append a year to every query indiscriminately.
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
- Check source dates and current primary documentation for changing facts.
- Be specific and actionable — "add OAuth2 login flow like tool X's 2-click setup" not "add authentication"
- Mark entries as `[Research]` (not `[AI]`) so they're distinguishable in BRAINSTORM.md
- Do NOT auto-process into GOALS.md or TODO.md — just write to BRAINSTORM.md inbox or personal research dir
- **Personal-topic routing**: If determined to be PERSONAL in step 0, write report to `~/.claude/research/{YYYY-MM-DD}-{slug}.md` INSTEAD of BRAINSTORM.md — personal context must never land in a git-tracked project file


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.
