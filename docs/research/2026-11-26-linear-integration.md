---
title: "Working from Linear issues: how coding agents connect, and what Clade does"
date: 2026-11-26
review_date: 2027-02-26
status: integrated
summary: >
  The owner asked how Clade should work with Linear, how other coding agents
  do it, what to automate, and what format an issue should take. Every vendor
  connects the same way: an issue goes out to an agent, a PR comes back, and a
  human stays responsible. Codex, Copilot, Cursor and Linear's own agent run
  that loop in their cloud. Clade runs it locally, because its gate runs on
  the owner's machines, so Clade reads issues through Linear's MCP server and
  links back through the PR. Two pieces were built: `delivery start --issue`
  with the PR link line (#282), and a `/linear ABC-123` skill for Claude Code,
  Codex and Kimi Code. Clade writes nothing to Linear without an explicit yes.
integrated_items:
  - "delivery start --issue ABC-123 and the /create-pr link line `Fixes ABC-123` / `Part of ABC-123` (#282)"
  - "/linear skill (configs/skills/linear/SKILL.md), shipped to Claude Code, the Codex plugin and the Kimi Code skill view"
needs_work_items: []
reference_items:
  - "Cloud agents in Linear (Codex, Copilot, Cursor, Linear's cloud coding agent): not adopted for work that needs the owner's machines"
  - "Linear Triage Loops: not adopted; they start agent work on arriving issues with no owner in the loop"
---

# Working from Linear issues

## Verdict

Linear holds who is responsible, what the task is and its status; the
repository holds the work and its evidence. Clade is the local executor
between them. Clade does not register as a Linear agent: it reads an issue
through Linear's MCP server, does the work as one delivery, and links back
through the PR's own words, which Linear's GitHub integration reads. Nothing
is written to Linear without the owner's explicit yes.

Built: `delivery start --issue` plus the `/create-pr` link line (#282), and
the `/linear ABC-123` skill. Deliberately not built: a TODO.md ↔ Linear sync,
automatic pickup from Triage, and any unattended write to Linear.

## How others connect agents to Linear

Official documentation, read 2026-11-25 and 11-26.

| Agent | Trigger | What comes back |
|---|---|---|
| OpenAI Codex | "Assign an issue to Codex or mention `@Codex` in a comment" | Codex "creates a cloud chat and replies with progress and results"; paid plans only |
| GitHub Copilot | assign the issue to Copilot | a linked "[WIP]" pull request created by Copilot cloud agent |
| Cursor | "Delegate an issue to `@Cursor` or mention `@Cursor` in a comment"; triage rules can delegate automatically | "an agent that will work on the task" |
| Linear cloud coding agent | delegate the issue to Linear | "draft pull requests using Claude Code or Codex" |
| Claude Code | none: there is no assignable Claude Code agent in Linear (an open Claude Code feature request, issue 12925, and a third-party blog) | a session reads and writes Linear through MCP |

Two rules are shared by all of them:

- **The human stays responsible.** "Delegate an issue to an agent while
  keeping a human teammate as the assignee. The assignee remains responsible
  for the work, while the agent contributes on their behalf."
- **Team conventions go in Agent guidance**, set by workspace admins at the
  workspace or team level (team guidance wins). "Guidance can specify which
  repository to use for certain code changes, how to reference issues in
  commits or pull requests, and what review process to follow." Each agent
  integration decides how to apply it.

## How a pull request links an issue

From Linear's GitHub integration docs:

- **Links:** the issue key in the branch name, in the PR title, or after a
  magic word in the PR title, description or a commit message. Magic words in
  PR comments link nothing.
- **Closing words** move the issue on merge: close(s/d/ing), fix(es/ed/ing),
  resolve(s/d/ing), complete(s/d/ing), implement(s/ed/ing).
- **Non-closing words** link without moving it: ref(s), references, part of,
  contributes to, toward(s). `relates to` / `related to` mark a relation only.
- **Default automation:** linked issues move to In Progress when the PR opens
  and to Done when it merges; teams can change this per PR state.

## What Clade does

1. **`delivery start --issue ABC-123`** (#282). Accepts a Linear or Jira key
   or a GitHub `#123`, stores it upper-case, keeps it across resumes and puts
   it in `evidence`. `/create-pr` then opens the PR body with `Fixes ABC-123`,
   or `Part of ABC-123` for one of several PRs.
2. **`/linear ABC-123`**. Reads the issue (state, assignee, scope, linked PRs,
   latest comments) and stops if it is closed, someone else's, or already has
   an open PR. Otherwise it starts one delivery on an `abc-123-<slug>` branch,
   builds and gates it locally, opens the PR, and drafts a verdict-first
   comment for the owner to approve before anything is posted.
3. **One MCP server for all three runtimes,** `https://mcp.linear.app/mcp`:
   `claude mcp add --transport http linear-server https://mcp.linear.app/mcp`
   (or the claude.ai Linear connector), `codex mcp add linear --url
   https://mcp.linear.app/mcp`, and a `linear` entry under `mcpServers` in
   Kimi Code's `~/.kimi-code/mcp.json`.

## What Clade deliberately does not automate

- **Syncing TODO.md with Linear.** Two sources of truth drift. TODO.md stays
  the record for Clade's own public work, and Linear for private company work.
- **Pickup from Triage.** Linear Loops "run agent behaviors, including coding
  work, each time an issue arrives in Triage". That starts work with no owner
  in the loop.
- **Writes to Linear.** A comment, state change, assignment or new issue is
  seen by the whole workspace, so `/linear` drafts it and posts it only on an
  explicit yes. Status moves come from the GitHub integration reading the PR.
- **Cloud agents for local work.** Work that needs the owner's machines (the
  local gate, data on private storage) stays with Clade. A small, well-specified
  fix can go to a cloud agent the workspace already has.

## Issue formats

**For an agent** (Clade or any other): say what is true when it is done.

```text
Title: the sentence that is true when it is done (≤ 80 characters)
**Outcome:** what is true afterwards, in one sentence
**Why:** one line, with a link to the evidence
**Repo / scope:** owner/repo · what may change · **Not:** what must not
**Done when:** checkable items, and the command that proves them (tests, gate)
**Context:** related PRs, threads, earlier issues
```

**For a person:** ask for one action, with a date.

```text
Title: one thing, verb first (Review and merge PR #76)
**Needs you:** one action and a date (Approve and merge PR #76 by Nov 28, or close it)
**Why it's waiting on you:** one line
* 2–4 lines of state (mergeable, which commit the checks passed on, where a merge deploys)
* links the recipient can open
```

One issue asks for one action; a batch becomes sub-issues.

## Left to each workspace

These are workspace-admin settings, not Clade's to decide: issue templates
for the two formats, Agent guidance that states the branch and PR
convention, and a GitHub integration that covers the repositories agents
open PRs in. Without that integration, PRs still carry the key but no status
moves.

## Sources

- Linear: [GitHub integration](https://linear.app/docs/github),
  [MCP server](https://linear.app/docs/mcp),
  [Agents in Linear](https://linear.app/docs/agents-in-linear),
  [Assign and delegate issues](https://linear.app/docs/assigning-issues),
  [Linear cloud coding agent](https://linear.app/docs/linear-cloud-coding-agent),
  read 2026-11-25 and 2026-11-26.
- [Codex in Linear](https://developers.openai.com/codex/integrations/linear),
  [Integrating Copilot cloud agent with Linear](https://docs.github.com/en/copilot/how-tos/copilot-integrations/integrate-cloud-agent-with-linear),
  [Bringing the Cursor Agent to Linear](https://cursor.com/blog/linear)
  (2025-08-21), read 2026-11-25.
- Claude Code: feature request "Linear Integration: Assign issues to Claude
  Code to trigger cloud agent sessions" (anthropics/claude-code, issue 12925,
  opened 2025-12-03, still open on 2026-11-26), and
  [How to use Claude Code with Linear](https://sinatra.dev/blog/claude-code-linear-integration),
  a blog by the vendor of an alternative tool, read 2026-11-25.
