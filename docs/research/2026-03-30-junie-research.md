---
name: 2026-03-30-junie-research.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "JetBrains Junie: Plan→Execute→Verify loop, IntelliJ inspection engine, Agent Skills auto-routing, LLM-agnostic"
integrated_items:
  - "Plan→Execute→Verify loop — partially implemented (PLAN phase in Blueprint, but no formal Verify)"
needs_work_items:
  - "Formal Verify phase after task execution — not implemented"
  - "IntelliJ inspection engine feedback — not applicable"
reference_items:
  - "Agent Skills auto-routing based on task type"
  - "LLM-agnostic design with model abstraction"
---

# JetBrains Junie — Deep Research

**Date**: 2026-03-30
**Status**: Beta (Junie CLI launched March 2026)
**Sources**: GitHub, official docs, JetBrains blog, InfoQ, community reviews

---

## 1. What Is Junie

Junie is JetBrains' AI coding agent. It started as an IntelliJ plugin (January 2025), integrated into AI Chat (December 2025), and launched Junie CLI in public beta (March 2026). The current positioning:

> "An LLM-agnostic coding agent that ships code from your terminal, IDE, or CI/CD pipeline — powered by any LLM you choose."

Three deployment surfaces:
- **IDE plugin** — embedded in IntelliJ IDEA, PyCharm, WebStorm, GoLand, etc.
- **Junie CLI** — standalone terminal agent (`junie` command)
- **GitHub Action** — CI/CD pipeline integration via `JetBrains/junie-github-action`

Alongside Junie CLI, JetBrains launched **Air** — an "Agentic Development Environment" that runs Junie, Claude Agent, OpenAI Codex, and Gemini CLI concurrently in isolated worktrees, connected via the **Agent Client Protocol (ACP)**.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Deployment Surfaces                   │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  IntelliJ    │  │  Junie CLI   │  │ GitHub Action │  │
│  │  IDE Plugin  │  │  (terminal)  │  │  (CI/CD)      │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
└─────────┼─────────────────┼──────────────────┼──────────┘
          │                 │                  │
          └─────────────────┼──────────────────┘
                            │
             ┌──────────────▼──────────────────┐
             │         Junie Core Engine        │
             │  Plan → Execute → Verify loop   │
             │  ┌──────────────────────────┐   │
             │  │    LLM Abstraction Layer │   │
             │  │  (model profiles JSON)   │   │
             │  └──────────────────────────┘   │
             │  ┌──────────────────────────┐   │
             │  │  Tool Use / Action Space │   │
             │  │  - file read/write       │   │
             │  │  - shell exec (!)        │   │
             │  │  - test runner           │   │
             │  │  - MCP server calls      │   │
             │  └──────────────────────────┘   │
             │  ┌──────────────────────────┐   │
             │  │  Context Layer           │   │
             │  │  - AGENTS.md / guidelines│   │
             │  │  - Agent Skills          │   │
             │  │  - Session history       │   │
             │  └──────────────────────────┘   │
             └─────────────────────────────────┘
                            │
          ┌─────────────────┼──────────────────────┐
          │                 │                       │
   ┌──────▼──────┐  ┌───────▼──────┐  ┌────────────▼──┐
   │ LLM APIs    │  │  MCP Servers │  │  IDE APIs     │
   │ OpenAI      │  │  (local/     │  │  IntelliJ     │
   │ Anthropic   │  │  remote)     │  │  inspections  │
   │ Google      │  └──────────────┘  │  refactoring  │
   │ xAI/Grok    │                    │  test runner  │
   │ OpenRouter  │                    └───────────────┘
   └─────────────┘
```

---

## 3. Agent Loop — Plan → Execute → Verify

Junie's core execution cycle (observed from docs + reviews):

```
User prompt
    │
    ▼
┌───────────────────────────────┐
│  1. PLAN PHASE (Shift+Tab)    │
│  - Read-only codebase scan    │
│  - Identify affected files    │
│  - Generate PLAN.md with:     │
│    - Atomic tasks             │
│    - File paths to modify     │
│    - Commands to run          │
│    - Acceptance checks        │
│  - Present to user for review │
└──────────────┬────────────────┘
               │ (user approves or modifies)
               ▼
┌───────────────────────────────┐
│  2. EXECUTE PHASE             │
│  - Iterate through plan tasks │
│  - For each task:             │
│    a. Read relevant files     │
│    b. Generate code changes   │
│    c. Show diff to user       │
│    d. Await approval (or      │
│       auto-proceed in brave)  │
│    e. Apply change            │
│  - Run shell commands (!)     │
│  - Create/modify files        │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  3. VERIFY PHASE              │
│  - Run build (compiler check) │
│  - Run test suite             │
│  - Run IDE inspections        │
│    (IntelliJ inspection engine│
│     = same as editor squiggles│
│  - On failure: re-enter loop  │
│    with error context         │
└───────────────────────────────┘
```

**Brave Mode** (`Ctrl+B`): skips approval checkpoints, runs fully autonomously. Recommended only on clean branches.

**Plan Mode** (`Shift+Tab`): analysis-only, no file writes. Shows what Junie would do.

**Think More** toggle: deeper chain-of-thought reasoning, costs more credits, reduces rework.

---

## 4. IDE Static Analysis Integration

This is Junie's primary differentiation from Cursor and Copilot.

### How It Works (IDE Plugin Mode)

When Junie writes code inside IntelliJ, it triggers the IDE's inspection engine directly via the IntelliJ Platform SDK:

- **Inspections engine**: Same engine that shows squiggly underlines in the editor — Junie runs this programmatically after each file write, reads the diagnostic output (warnings/errors with file:line format), and feeds it back into the next LLM call as "what's wrong with this code"
- **Refactoring APIs**: Junie can invoke IntelliJ's structural refactoring (rename, extract method, etc.) — not just text substitution
- **Test runner**: JUnit/pytest/etc. run results returned to agent as structured pass/fail with stack traces
- **VCS integration**: Git diff, blame, and history accessible directly

### What the Feedback Loop Looks Like

```
LLM generates code
       │
       ▼
  Write to file
       │
       ▼
  Run inspections (IntelliJ engine)
  → Returns: [{file, line, severity, message, suggestion}]
       │
       ├── No errors? → Run tests
       │                    │
       │              Tests pass? → Done
       │              Tests fail? ──────────────┐
       │                                        │
       └── Has errors? ──────────────────────── ▼
                                      Re-prompt LLM with:
                                      - Inspection results
                                      - Test failure output
                                      - Stack traces
                                      Loop until clean or max-iter
```

**In CLI Mode**: Without the full IntelliJ runtime, Junie falls back to running shell-level tools (compiler invocations, linters via `!` shell commands, test runners). The IDE inspection advantage is specific to the IntelliJ plugin.

### Qodana Connection

JetBrains' Qodana (headless IntelliJ inspection runner for CI) uses the same inspection engine. In theory, Junie in CI mode could invoke Qodana — but this is not explicitly documented as a built-in integration. Teams can configure it via MCP or custom prompts.

---

## 5. LLM-Agnostic Design

### Provider Configuration

Three authentication modes:

```
Mode 1: JetBrains subscription
  JUNIE_API_KEY=<token from junie.jetbrains.com/cli>
  (JetBrains routes to best model automatically)

Mode 2: BYOK — named providers
  JUNIE_LLM_PROVIDER=anthropic   # or openai, google, xai, openrouter
  JUNIE_ANTHROPIC_API_KEY=sk-...
  JUNIE_MODEL=claude-sonnet-4-5  # or omit for default

Mode 3: Custom model profile (local/self-hosted)
  File: .junie/models/my-profile.json or ~/.junie/models/*.json
```

### Custom Model Profile Format (JSON)

```json
{
  "baseUrl": "http://localhost:11434/v1/responses",
  "id": "qwen3-coder:latest",
  "apiType": "OpenAIResponses",
  "extraHeaders": {
    "X-Custom-Source": "Junie"
  },
  "fasterModel": {
    "id": "qwen2.5-coder:1.5b",
    "baseUrl": "http://localhost:11434/v1/responses"
  },
  "primaryModel": {
    "id": "qwen3-coder:32b"
  }
}
```

Supported `apiType` values: `OpenAICompletion`, `OpenAIResponses`, `Google`, `Anthropic`

Select via: `junie --model custom:my-profile`

### Environment Variables (Full List)

| Variable | Purpose |
|---|---|
| `JUNIE_API_KEY` | JetBrains API key |
| `JUNIE_LLM_PROVIDER` | BYOK provider (openai/anthropic/google/xai/openrouter) |
| `JUNIE_ANTHROPIC_API_KEY` | Anthropic BYOK key |
| `JUNIE_OPENAI_API_KEY` | OpenAI BYOK key |
| `JUNIE_GOOGLE_API_KEY` | Google BYOK key |
| `JUNIE_GROK_API_KEY` | xAI/Grok BYOK key |
| `JUNIE_OPENROUTER_API_KEY` | OpenRouter BYOK key |
| `JUNIE_MODEL` | Model identifier (defaults to `Default`) |
| `JUNIE_MODEL_LOCATIONS` | Extra paths for model profile discovery |
| `JUNIE_MODEL_DEFAULT_LOCATIONS` | Toggle per-user/per-project model paths (default: true) |

**"Automatic gear-shift"**: JetBrains' stated philosophy is to auto-select the best model per task (primary vs. faster model). Users can override manually with `/model`.

---

## 6. MCP Extension System

### Configuration Format

```
Locations:
  Project scope: <projectRoot>/.junie/mcp/mcp.json   (version-controlled)
  User scope:    ~/.junie/mcp/mcp.json                 (private, machine-level)
```

```json
{
  "mcpServers": {
    "LocalServer": {
      "command": "npx",
      "args": ["-y", "@scope/server-mcp"],
      "env": {
        "ENV_VAR": "value"
      }
    },
    "DockerServer": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp-image:latest"]
    },
    "RemoteServer": {
      "url": "https://mcp.example.com/v1",
      "headers": {
        "Authorization": "Bearer token"
      }
    }
  }
}
```

Connection types: **Local** (npx, Docker, binary) or **Remote** (HTTP/HTTPS).

### How MCP Tools Are Used

1. On task start, Junie scans configured MCP servers for available tools
2. LLM decides which tools are relevant to the current task
3. Before executing: user approval prompt (unless brave mode)
4. Tool result returned to LLM as context
5. `/mcp` slash command for manual server management

Server status states: `Starting` → `Active` / `Inactive` / `Failed` / `Authorization required` / `Disabled`

### MCP in CI (GitHub Action)

```yaml
with:
  allowed_mcp_servers: "mcp_github_checks_server"
```

The `fix-ci` built-in prompt uses MCP to fetch GitHub Actions check logs — this is how Junie reads build failure output from the CI system.

---

## 7. Agent Skills (Subagent System)

Agent Skills are the closest thing Junie has to subagents — domain-specific behavioral modules that activate automatically based on task relevance.

### Directory Structure

```
<project>/.junie/skills/          ← version-controlled, project-specific
    my-skill/
        SKILL.md                  ← required
        scripts/                  ← optional shell scripts
        templates/                ← optional code templates
        checklists/               ← optional reference material

~/.junie/skills/                  ← user-level, applies to all projects
    shared-skill/
        SKILL.md
```

Project-level skills override user-level skills with matching names.

### SKILL.md Format

```markdown
---
name: code-review
description: Performs comprehensive code review covering security vulnerabilities,
             performance bottlenecks, code style violations, and architectural concerns
version: 1.0.0
tags: [review, security, performance]
---

## Key Principles

1. Check for SQL injection vectors in all user-facing inputs
2. Verify error handling at all async boundaries
3. Confirm test coverage for all public methods

## Security Checklist

- [ ] No hardcoded credentials
- [ ] Input validation at system boundaries
- [ ] No `error.message` in API 500 responses

## References

- See `./checklists/security.md` for full OWASP checklist
- See `./scripts/run-bandit.sh` for automated security scan
```

YAML frontmatter fields:
- `name` (required) — unique identifier, used for override resolution
- `description` (required) — summary used by LLM to determine relevance
- `version` (optional) — for tracking
- `tags` (optional) — categorization
- `allowed-tools` (optional) — restrict tools available during skill execution

### How Skills Are Invoked

Skills activate **automatically** — Junie scans all skill folders, evaluates `description` against the current task, and injects relevant skill content into the system prompt. No explicit `@skill-name` syntax required.

This is semantic routing, not explicit invocation.

---

## 8. Guidelines and Memory System

### File Discovery Order (CLI)

Junie checks these locations in order:

1. Custom path (if set in IDE settings)
2. `.junie/AGENTS.md` — primary guidelines, project root
3. `AGENTS.md` — project root (AGENTS.md open format, compatible with Cursor/Copilot/Claude Code)
4. `.junie/rules/*.md` — all Markdown files in rules directory
5. `.junie/guidelines.md` — legacy format (still supported)

### AGENTS.md / guidelines.md Recommended Sections

```markdown
# Project Guidelines

## Quick-Start Checklist
- Always run `npm test` before committing
- Never modify `src/schema/` without a migration

## Development Commands
| Task    | Command          |
|---------|-----------------|
| Install | `npm install`    |
| Test    | `npm test`       |
| Build   | `npm run build`  |
| Dev     | `npm run dev`    |

## Architecture
- Frontend: React + TypeScript (no class components)
- Backend: FastAPI, async only
- DB: PostgreSQL, all migrations in `alembic/`

## Coding Standards
- Files < 1500 lines
- No circular imports
- Error handling at all system boundaries

## Explicit Prohibitions
- Never change `package-lock.json` directly
- Never drop columns in migrations
- Never return stack traces in 500 responses
```

### Memory

Session history accessible via `/history` (last 10 sessions). No persistent long-term memory beyond guidelines files.

---

## 9. Spec-Driven Development Approach

JetBrains documented a spec-driven workflow (October 2025) where Junie creates and works from structured documents:

### Document Set

```
docs/requirements.md   ← what to build (user stories + acceptance criteria)
docs/plan.md           ← how to build it (priorities, risks, dependencies)
docs/tasks.md          ← atomic checklist (phase-organized, checkbox format)
.junie/guidelines.md   ← how the agent should work on tasks.md
```

### requirements.md Format

```markdown
## REQ-001: User Authentication

**User Story**: As a user, I want to log in with email/password so that I can access my account.

**Acceptance Criteria**:
- WHEN valid credentials are submitted THEN user receives a JWT token
- WHEN invalid credentials are submitted THEN system returns 401 with generic message
- WHEN token expires THEN refresh endpoint issues new token
```

### tasks.md Format

```markdown
## Phase 1: Setup

- [ ] 1.1 Initialize project structure [REQ-001 → PLAN-A]
- [ ] 1.2 Configure database connection [REQ-001 → PLAN-B]

## Phase 2: Core Implementation

- [x] 2.1 Implement password hashing [REQ-001 → PLAN-C]
- [ ] 2.2 Create JWT generation service [REQ-001 → PLAN-C]
```

### Usage Pattern

User tells Junie: "Complete tasks 1.1 and 1.2 from tasks.md and mark them as completed."

Junie updates checkboxes on completion. This creates an externalized task state that persists across sessions and is reviewable in git.

This is JetBrains' answer to AWS Kiro's spec-driven approach — less formalized than Kiro's hook system, but compatible with any editor.

---

## 10. CI/CD Integration — GitHub Action

### Full Input Parameter Reference

```yaml
uses: JetBrains/junie-github-action@v1
with:
  # Auth (required — one of)
  junie_api_key: ${{ secrets.JUNIE_API_KEY }}
  # OR BYOK:
  anthropic_api_key: ${{ secrets.ANTHROPIC_KEY }}
  openai_api_key: ${{ secrets.OPENAI_KEY }}
  google_api_key: ${{ secrets.GOOGLE_KEY }}

  # Trigger control
  trigger_phrase: "@junie-agent"      # default
  assignee_trigger: "junie-bot"       # username trigger
  label_trigger: "junie"              # label trigger

  # Task configuration
  prompt: "fix-ci"                    # builtin: fix-ci, code-review, minor-fix
  # OR custom multi-line prompt:
  prompt: |
    Review changes for security issues.
    Focus on: SQL injection, XSS, secrets.

  # Branch management
  base_branch: "main"
  create_new_branch_for_pr: "true"    # creates junie/fix-xxx branch

  # MCP
  allowed_mcp_servers: "mcp_github_checks_server"

  # Behavior
  silent_mode: "false"                # true = no commits/comments
  use_single_comment: "true"          # updates vs. creates new comments
  model: "sonnet"                     # claude sonnet, gpt, gemini-pro, etc.
  junie_version: "888.212"

  # Integrations
  jira_base_url: "https://co.atlassian.net"
  jira_email: ${{ secrets.JIRA_EMAIL }}
  jira_api_token: ${{ secrets.JIRA_TOKEN }}
```

### Outputs

```yaml
outputs:
  branch_name:    # branch Junie created
  commit_sha:     # commit SHA if committed
  pr_url:         # PR URL if created
  junie_title:    # summary title
  junie_summary:  # full change summary (parseable for CI gates)
  should_skip:    # whether execution was skipped
```

### Key Workflows

**Auto-fix failing CI**:
```yaml
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
jobs:
  fix:
    if: |
      github.event.workflow_run.conclusion == 'failure' &&
      !startsWith(github.event.workflow_run.head_branch, 'junie/')
    steps:
      - uses: JetBrains/junie-github-action@v1
        with:
          allowed_mcp_servers: "mcp_github_checks_server"
          create_new_branch_for_pr: "true"
          prompt: "fix-ci"
```

**Silent security audit** (blocks CI without commenting):
```yaml
- uses: JetBrains/junie-github-action@v1
  id: junie
  with:
    silent_mode: "true"
    prompt: "Scan git diff for accidentally committed secrets."
- name: Check results
  run: |
    if echo "${{ steps.junie.outputs.junie_summary }}" | grep -q "SECRETS_FOUND"; then
      exit 1
    fi
```

---

## 11. Terminal Mode (Junie CLI)

### Commands

```bash
# Interactive mode
junie

# Headless/CI
junie --auth="$JUNIE_API_KEY" "fix the failing test in auth.test.ts"

# Specify model
junie --model custom:local-ollama

# With specific guidelines file
junie --guidelines .junie/custom-guidelines.md
```

### Slash Commands

| Command | Function |
|---|---|
| `/account` | Manage credentials / BYOK keys |
| `/model` | Switch LLM for current session |
| `/new` | Clear session context |
| `/history` | View/resume last 10 sessions |
| `/usage` | Token usage and cost breakdown |
| `/mcp` | MCP server management |
| `/quit` | Exit preserving login |
| `?` | Show all shortcuts |

### Keyboard Shortcuts

| Shortcut | Function |
|---|---|
| `Shift+Tab` | Toggle plan mode (read-only analysis) |
| `Ctrl+B` | Enable brave mode |
| `Ctrl+F` | Faster results mode |
| `Ctrl+R` | Search prompt history |
| `Ctrl+T` | View session transcript |
| `@filename` | Attach file to context |

### File References

```
@src/auth.ts          # attach single file
@src/                 # attach directory
Drag-and-drop files   # also supported
PNG/JPEG images       # for UI specs/screenshots
```

---

## 12. JetBrains Air — Multi-Agent Environment

Launched March 2026 alongside Junie CLI. Air is built on abandoned Fleet IDE codebase.

**Supported agents in Air**:
- JetBrains Junie
- Anthropic Claude Agent
- OpenAI Codex
- Google Gemini CLI
- Any ACP-compatible agent (via registry)

**Isolation mechanism**: Git worktrees — each agent gets an isolated branch, preventing interference.

**Task model**: One focused task per agent session. Notifications when agents complete.

**Agent Client Protocol (ACP)**:
- Open standard, co-authored by JetBrains and Zed editor
- JSON-RPC over stdio (local) or HTTP/WebSocket (remote)
- Reuses JSON representations from MCP where applicable
- Agents implement protocol once, work in any ACP-compatible editor
- "Like LSP but for AI agents"
- Apache license, open source
- Registry at `agentclientprotocol.com`

---

## 13. Comparison: Junie vs Cursor vs GitHub Copilot

| Dimension | Junie | Cursor | GitHub Copilot |
|---|---|---|---|
| **Model** | Any (BYOK) | Claude/GPT (configurable) | GPT/Claude |
| **IDE** | JetBrains only (+ CLI) | Cursor IDE only | Any (VS Code, JetBrains) |
| **Static Analysis** | Native IntelliJ inspections | LSP/compiler errors only | LSP/compiler errors only |
| **Agent Loop** | Plan → Execute → Verify | Composer/Agent mode | Copilot Workspace |
| **Static Analysis Source** | IntelliJ inspection engine | External linters/compiler | External linters |
| **Test Runner** | Native IDE integration | CLI subprocess | CLI subprocess |
| **Multi-file Awareness** | Deep (IDE project model) | Deep (codebase index) | Moderate |
| **CI/CD** | GitHub Action | None native | None native |
| **Terminal Mode** | Yes (Junie CLI) | No | No |
| **Subagents** | Agent Skills (auto-routing) | No | No |
| **Spec-driven** | Yes (tasks.md + guidelines) | No | No |
| **MCP** | Yes | Yes | No |
| **Pricing** | $0–$30/mo + credits | $20/mo | $10/mo |
| **Benchmark (SWEBench)** | 60.8% | ~72% | ~55% |

**JetBrains' unique advantages**:
1. IntelliJ inspection engine gives semantic Java/Kotlin/Python understanding — not just text matching
2. Deep refactoring APIs (rename across project, extract method, etc.)
3. GitHub Action is the most capable native CI integration among the three
4. Agent Skills auto-routing is unique
5. LLM-agnostic from day 1 (BYOK + custom model profiles)

**JetBrains' weaknesses**:
1. IDE plugin only works in JetBrains IDEs (no VS Code)
2. Community Edition not supported (requires paid IDE)
3. Static analysis advantage disappears in CLI mode (no IntelliJ runtime)
4. No granular accept/reject for individual changes within a task
5. Tends to expand scope ("eager" behavior — refactors things not asked)
6. Slower than Cursor (~3-4 min per task vs ~1-2 min)

---

## 14. "Agentic Debt" — JetBrains' Framing

JetBrains coined "Shadow Tech Debt" to describe AI-generated code that is:
- Architecture-blind (no structural understanding of the codebase)
- Generated without context about existing patterns
- Inconsistent with team conventions

Their solution: Junie CLI with:
- Guidelines files (AGENTS.md) that encode project conventions
- Agent Skills that encode domain knowledge
- IDE integration that gives structural (not textual) code understanding
- Spec-driven approach that externalizes intent as reviewable artifacts

Air's multi-agent approach addresses the fragmentation problem: "each agent in a different tool, different context, no structural understanding."

---

## 15. What Clade Can Borrow

### High-Value Patterns

**1. Agent Skills as auto-routing subagents**

Skills activate by semantic relevance (description matching), not explicit invocation. For Clade, this means skills could be loaded into worker context automatically based on task type — no need for the user to specify which skills apply.

```
Current Clade: user writes explicit skill invocations
Junie pattern: scan .clade/skills/, match description to task, auto-inject
```

**2. Linting/static analysis feedback to LLM**

Junie's killer feature is feeding IntelliJ diagnostic output directly into the next LLM call:

```
[After code change]
System: "The following inspection warnings were found:
  auth.py:42: B105 hardcoded_password_string (severity: HIGH)
  auth.py:67: W503 line break before binary operator
Please fix these issues before proceeding."
```

For Clade's Python workers, this could be:
- Run `ruff check` / `mypy` after every file write
- Parse structured output: file, line, code, message
- Inject into next worker LLM call as context
- Loop until clean (or max N iterations)

**3. PLAN.md as a reviewable planning artifact**

Junie writes the plan to a file (`PLAN.md`) before executing. This makes plans:
- Reviewable by humans
- Resumable across sessions
- Auditable in git history

Clade's loop-runner already has goal files — adding a plan artifact would make supervisor output more traceable.

**4. Spec-driven task tracking with checkbox state**

tasks.md with checkbox state (`- [ ]` / `- [x]`) that the agent updates on completion. This externalizes task state from the LLM context window — critical for long-running loops.

Clade already has TODO.md — the pattern to adopt is having workers check off items they complete, not just reporting "done" in a summary.

**5. Allowlist for shell commands**

Junie's `allowlist.json` (~/.junie/allowlist.json) stores "always allow" decisions for shell commands. For Clade's loop-runner, this would mean not asking the user repeatedly for approval of standard build/test commands.

**6. Silent mode for CI gate outputs**

The pattern of `silent_mode=true` + parsing `junie_summary` output for keywords (`SECRETS_FOUND`, `TESTS_FAILED`) enables CI gates without human-in-the-loop. Clade's GitHub Action integration could adopt this pattern.

**7. fasterModel + primaryModel split**

Junie uses two models: a heavier primary for code generation and a lighter faster model for context summarization, routing decisions, and TLDR generation. Clade's `worker_tldr.py` already does this pattern — worth making it explicit in config.

### Lower Priority

- MCP config format: Clade already supports MCP via Claude Code CLI
- AGENTS.md format: Clade uses CLAUDE.md which serves the same purpose
- ACP: relevant only if Clade targets multi-agent environments

---

## Sources

- [GitHub — JetBrains/junie](https://github.com/JetBrains/junie)
- [Junie CLI Beta Launch Blog](https://blog.jetbrains.com/junie/2026/03/junie-cli-the-llm-agnostic-coding-agent-is-now-in-beta/)
- [Junie Documentation Home](https://junie.jetbrains.com/docs/)
- [Agent Skills Documentation](https://junie.jetbrains.com/docs/agent-skills.html)
- [Guidelines and Memory](https://junie.jetbrains.com/docs/guidelines-and-memory.html)
- [MCP Configuration](https://junie.jetbrains.com/docs/junie-cli-mcp-configuration.html)
- [Custom LLM Models](https://junie.jetbrains.com/docs/custom-llm-models.html)
- [Environment Variables](https://junie.jetbrains.com/docs/environment-variables.html)
- [Terminal Usage](https://junie.jetbrains.com/docs/junie-cli-usage.html)
- [GitHub Action](https://junie.jetbrains.com/docs/junie-on-github.html)
- [GitHub Action Cookbook](https://github.com/JetBrains/junie-github-action/blob/main/COOKBOOK.md)
- [GitHub — JetBrains/junie-guidelines](https://github.com/JetBrains/junie-guidelines)
- [Spec-Driven Approach Blog](https://blog.jetbrains.com/junie/2025/10/how-to-use-a-spec-driven-approach-for-coding-with-ai/)
- [What's Next for Junie](https://blog.jetbrains.com/junie/2025/05/what-s-next-for-junie-building-a-smart-and-controllable-ai-coding-agent/)
- [Air Launch Blog](https://blog.jetbrains.com/air/2026/03/air-launches-as-public-preview-a-new-wave-of-dev-tooling-built-on-26-years-of-experience/)
- [Air Supported Agents](https://www.jetbrains.com/help/air/supported-agents.html)
- [Agent Client Protocol](https://agentclientprotocol.com/overview/introduction)
- [JetBrains × Zed ACP Blog](https://blog.jetbrains.com/ai/2025/10/jetbrains-zed-open-interoperability-for-ai-coding-agents-in-your-ide/)
- [Junie Review 2026](https://vibecoding.app/blog/junie-review)
- [InfoQ: JetBrains Junie Agent](https://www.infoq.com/news/2025/01/jetbrains-junie-agent/)
- [JetBrains Agentic Era Blog](https://blog.jetbrains.com/junie/2025/07/the-agentic-ai-era-at-jetbrains-is-here/)
- [JetBrains Agentic Debt (The New Stack)](https://thenewstack.io/jetbrains-names-the-debt-ai-agents-leave-behind/)
- [Junie Dev Experience Blog](https://lengrand.fr/my-experience-using-junie-for-the-past-few-months/)
- [Coding Guidelines for AI Agents](https://blog.jetbrains.com/idea/2025/05/coding-guidelines-for-your-ai-agents/)
