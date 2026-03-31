# Stripe Minions + Pi Coding Agent — Research Findings

---
name: 2026-03-30-stripe-minions-pi-agent.md
date: 2026-03-30
status: integrated
review_date: 2026-03-31
summary:
  - "Stripe Blueprint hybrid nodes + Pi structured compaction + skills discovery"
integrated_items:
  - "Blueprint hybrid nodes — /loop skill 有 PRE/LLM CORE/POST phases"
  - "Structured compaction — /handoff skill 有 Goal/Progress/Decisions/Next Steps format"
  - "Skills discovery — session-context.sh 注入 skill descriptions 到 system prompt"
  - "2-round failure cap — --max-consecutive-failures 在 loop skill"
  - "Tool output truncation (50KB/2000 lines) — worker.py 有实现"
  - "Pre-hydration hook — worker.py 新增 _pre_hydrate()，在 agent 开始前通过 gh CLI 预先抓取引用的 GitHub issues/PRs 内容并注入 task file"
  - "Session tree (JSONL) — worker.py 使用 SessionTree class，每次 worker 执行写入 append-only JSONL 文件，支持 branching + replay"
  - "Curated tool subsets per task type — worker.py 新增 _TOOL_SUBSETS，review 类型自动限制 Edit/Write 工具，fix 类型允许部分限制"
needs_work_items: []
reference_items:
  - "RPC mode for orchestrator — MCP server 已实现 (c1cc435)，研究建议的纯 JSONL RPC 不是优先项"
  - "Agent definitions as Markdown — Python 定义更类型安全，不是问题"
  - "Retry: error removed from context before retry — 低优先级"
  - "Extension hot-reload — skill reload 需要 restart，但不是关键"
  - "Rule files same format as Cursor — 不是优先项"
  - "Background lint daemon — post-edit-check hook 部分覆盖"

**Date**: 2026-03-30
**Sources**:
- https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents
- https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2
- https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent

**Purpose**: Extract borrowable patterns for Clade redesign.

---

## 1. Stripe Minions — Key Findings

### Scale & Metrics
- **1,300+ PRs merged per week**, zero human-written code in the PR body
- Codebase: hundreds of millions of lines, primarily Ruby + Sorbet
- 3M+ tests, ~500 MCP tools in Toolshed
- Devbox startup: **10 seconds** (pre-warmed pool)
- Local linting: **< 1 second** (background daemon with precomputed cache)
- CI rounds per run: **at most 2** (hard cap, intentional)

### Architecture: Three Layers

```
Devboxes (AWS EC2, pre-warmed, isolated)
    ↓
Agent Harness (forked goose, fully unattended, no confirmation dialogs)
    ↓
Context + Tools (scoped rule files + Toolshed MCP, curated per agent)
```

Key: reuse **human developer infrastructure** rather than building agent-specific sandboxes.
Isolation (no production access, no internet egress) = full autonomy without risk.

### The Core Innovation: Blueprints

Blueprints are **state machines mixing deterministic nodes + agentic nodes**:

```
[deterministic] Parse Slack thread + extract links
[deterministic] MCP pre-hydrate all links
[AGENT NODE]    Implement task
[deterministic] Run configured linters   (<1s, pre-cached)
[deterministic] Push branch
[deterministic] Trigger CI
[AGENT NODE]    (if failures) Fix CI failures
[deterministic] Apply autofixes
[deterministic] Second CI push (max)
[deterministic] Create PR from template
```

**Why this matters**: LLMs should NOT decide "should I run linting?" or "should I create a PR?" — those are deterministic control flow. Constraining LLM agency to only the genuinely uncertain parts:
- Saves tokens at scale
- Reduces blast radius of errors
- Makes behavior predictable and auditable

The **2-CI-round hard cap** is deliberate: "diminishing marginal returns if an LLM runs against indefinitely many CI rounds."

### Context Engineering

**Rule files**: Use `.cursor/rules` format, scoped per subdirectory. One set maintained, consumed by Minions + Cursor + Claude Code simultaneously. Global rules used "almost exclusively sparingly."

**Pre-hydration pattern**: Before the agent node starts, deterministic MCP tool calls fetch all linked tickets, docs, code references. Agent starts with full context already built.

**Tool subsetting**: Each agent type gets a curated subset of ~500 Toolshed tools. Flooding an agent with 500 tools degrades reasoning quality.

### Failure Handling Philosophy

"Shift-left": catch failures as early as possible.
- Pre-push lint daemon (< 1s) → before CI even runs
- CI round 1 → autofixes applied automatically
- CI round 2 → agent gets one more attempt
- After 2 rounds → return to human, no more agent iterations

Humans can provide additional instructions for incomplete runs → triggers another code push.

---

## 2. Pi Coding Agent — Key Findings

Pi is a **minimal, maximally extensible** terminal coding harness. Written in TypeScript/Bun.
Philosophy: no built-in opinions on MCP, sub-agents, permissions, plan mode — extension hooks for everything.

### Four Operating Modes

| Mode | Use Case |
|------|----------|
| Interactive | Full TUI with history tree navigation, branching |
| Print/JSON | Non-interactive, structured JSON event stream for scripting |
| **RPC** | **JSONL over stdin/stdout — any language drives Pi as subprocess** |
| SDK | npm package for embedding in TypeScript |

The RPC mode is the key pattern for multi-agent orchestration.

### Most Elegant Design: JSONL Session Tree

Sessions stored as **flat JSONL files where every entry has `id` + optional `parentId`**, forming a tree in one file.

Entry types:
- `message` — LLM messages (user/assistant/tool_result)
- `compaction` — summary text + `firstKeptEntryId` (where kept messages start)
- `branch_summary` — LLM summary when navigating away
- `model_change`, `thinking_level_change`, `label` — metadata
- `custom` — extension state (excluded from LLM context)

**Why elegant**: branching from any historical point = append new entries with parentId pointer. No file duplication. `buildSessionContext()` walks from current leaf to root; on `compaction` entry, emits summary first then messages from `firstKeptEntryId`. History preserved, context truncated correctly.

### Compaction Strategy (Backward Accumulation)

**Trigger**: `contextTokens > contextWindow - reserveTokens` (default: 16,384 reserve)

**Algorithm**:
1. Walk messages newest → oldest, accumulate estimated tokens (chars/4)
2. Stop at `keepRecentTokens` threshold (default: 20,000)
3. Find nearest valid cut point (user/assistant/custom boundary, never mid-tool-call)
4. LLM summarizes everything before the cut
5. Append `CompactionEntry` with summary + `firstKeptEntryId`

**Structured summary format** (not free text — LLM fills in specific sections):
```
## Goal
## Constraints & Preferences
## Progress
  ### Done / In Progress / Blocked
## Key Decisions + rationale
## Next Steps
## Critical Context
<read-files> list </read-files>
<modified-files> list </modified-files>
```

**Iterative compaction**: subsequent compactions use `UPDATE_SUMMARIZATION_PROMPT` — preserves all prior summary info, adds new progress. Prevents information loss across multiple compaction cycles.

**Split-turn handling**: if cut falls mid-turn, generate two summaries in parallel (history + turn-prefix), concatenate.

**Extension override**: `session_before_compact` hook lets extensions replace the entire compaction logic (e.g., use Gemini Flash for cheaper summarization).

### Extension System — Full Lifecycle Hooks

Extensions are TypeScript files, auto-discovered from `~/.pi/agent/extensions/` and `.pi/extensions/`. Hot-reloaded via `/reload`.

Key extension hooks:
```typescript
pi.on("before_agent_start", async (event, ctx) => {
  // Fire AFTER user message, BEFORE agent.prompt()
  // Return { messages: [...], systemPrompt?: "..." }
  // This is the pre-hydration pattern: inject MCP context here
});

pi.on("tool_call", async (event, ctx) => {
  // Can return { block: true, reason: "..." } to prevent execution
});

pi.on("tool_result", async (event, ctx) => {
  // Transform tool output before LLM sees it
});

pi.on("context", async (event, ctx) => {
  // Filter/modify messages before each LLM call
});

pi.on("session_before_compact", async (event, ctx) => {
  // Replace compaction logic entirely
});
```

**Tool registration with full metadata**:
```typescript
pi.registerTool({
  name, label, description,
  promptSnippet,        // one-liner injected into "Available tools" system prompt section
  promptGuidelines,     // bullet points added to Guidelines section
  parameters,           // TypeBox schema
  execute,              // async (toolCallId, params, signal, onUpdate, ctx) => result
  renderCall,           // TUI rendering
  renderResult
});
```

### RPC Protocol (JSONL over stdin/stdout)

Full command set:
- `prompt`, `steer`, `follow_up`, `abort`, `new_session`
- `get_state`, `get_messages`, `get_commands`
- `set_model`, `cycle_model`, `get_available_models`
- `set_thinking_level`, `cycle_thinking_level`
- `compact`, `set_auto_compaction`
- `set_auto_retry`, `abort_retry`
- `bash`, `abort_bash`
- `fork`, `get_fork_messages`, `navigate_tree`
- `export_html`, `set_session_name`

Extensions can send back UI requests over the same channel:
```typescript
{ type: "extension_ui_request"; method: "select" | "confirm" | "input" | "notify" | "setStatus" }
```

This means **any language** can drive Pi as a subprocess and receive rich UI interaction requests.

### Subagent Spawning Pattern

Pi spawns subagents as separate `pi` processes:
```bash
pi --mode json -p --no-session [--model X] [--tools a,b,c] [--append-system-prompt /tmp/file]
```

Three execution modes:
1. **Single**: one subprocess, one task
2. **Parallel**: up to 8 tasks, max 4 concurrent, shared `nextIndex` counter for load distribution
3. **Chain**: sequential, `{previous}` placeholder substitutes prior step's output

Agent definitions are **Markdown files with YAML frontmatter** in `~/.pi/agents/` or `.pi/agents/`:
```yaml
---
name: agent-name
description: What this agent does
tools: read,bash,edit
model: claude-3-5-sonnet
---
{system prompt body}
```

### Skills System

Skills are Markdown files conforming to the [Agent Skills standard](https://agentskills.io/specification).
Discovered from `~/.pi/agent/skills/` and `.pi/skills/`.

- **Descriptions** always in system prompt context
- **Full instructions** load on-demand (the agent uses the `read` tool when needed)
- This keeps base context window small while making skills discoverable

Injected as XML into system prompt:
```xml
<available_skills>
  <skill>
    <name>skill-name</name>
    <description>description</description>
    <location>/absolute/path/to/SKILL.md</location>
  </skill>
</available_skills>
```

### Retry Logic

Retryable patterns: 429, 503, overloaded, rate limit, network errors.
**Context overflow is NOT retried** — routed to compaction instead.

Default: 3 attempts, 2s/4s/8s exponential backoff.
**Error message removed from LLM context before retry** (but kept in session JSONL for history).

### Multi-Provider Abstraction

Supports Anthropic, OpenAI, Azure, Gemini, Vertex, Bedrock, Mistral, Groq, Cerebras, xAI, OpenRouter, Vercel AI Gateway, and more.

Also supports OAuth-based providers (subscription accounts): Claude Pro/Max, ChatGPT Plus, GitHub Copilot, Gemini CLI.

Custom providers registered via `~/.pi/agent/models.json` with `compat` flags for fine-grained OpenAI API compatibility.

---

## 3. Cross-Cutting Insights

### Insight 1: Blueprints > Pure Agent Loops

The most important takeaway from Stripe:

> LLMs should NOT make decisions that are deterministically knowable. Reserve agentic (LLM) nodes only for steps where the path forward is genuinely uncertain.

**Applied to Clade**: Every iteration loop has predictable pre/post steps (git status check, syntax check, doc update, commit). These should be deterministic nodes, not left to the LLM to decide whether to run.

### Insight 2: Compaction is the Unsolved Hard Problem

Both systems deal with context limits differently:
- Stripe: devbox isolation limits run length naturally
- Pi: explicit JSONL tree + backward-accumulation + structured summaries

Pi's approach is the more principled one for truly long-running sessions.
**Key**: the summary must be **structured** (Progress/Key Decisions/Next Steps), not free text, or the LLM can't effectively rebuild state on reload.

### Insight 3: Skills Should Be Discoverable, Not Memorized

Pi's skills system: descriptions always in context, full instructions load on-demand via read tool.

**Clade's current problem**: skills require the user to know the slash command name to use them. There's no discovery mechanism. Pi's approach inverts this: the LLM reads skill descriptions and decides when to apply one.

### Insight 4: Tool Output Truncation is a First-Class Concern

Pi enforces hard limits (50KB / 2000 lines) on all tool outputs.
Stripe uses selective test execution for the same reason.

Unbounded tool output is the most common cause of context overflow in production agents.

### Insight 5: Pre-Hydration via Extension Hook is the Right Pattern

Pi's `before_agent_start` hook fires AFTER user message is built but BEFORE the agent loop starts. This is the correct place to inject MCP-fetched context, git state, ticket details, etc.

**Current Clade equivalent**: system prompt or hardcoded context. Not composable.

### Insight 6: Visual Interface > Terminal is Correct

Pi proves a rich TUI with session history tree, branch navigation, and streaming tool visualization is achievable. The RPC mode proves the agent core and UI can be completely decoupled — enabling web frontends, IDE plugins, or any other interface.

### Insight 7: Separate Sessions from Agent State

Pi's JSONL tree cleanly separates:
- **Agent state** (current messages, model, settings) — ephemeral, rebuilt from session file
- **Session history** (the JSONL tree) — persistent, append-only

This means crashes don't lose history, compaction doesn't mutate history, and branching is free.

---

## 4. Borrowable Patterns for Clade

Ranked by impact:

### High Impact

| Pattern | Source | What to Adopt |
|---------|--------|---------------|
| **Blueprint hybrid nodes** | Stripe | Refactor `/loop` skill to use deterministic pre/post phases; LLM only for "implement" + "fix failures" |
| **Structured compaction summaries** | Pi | Current `/handoff` skill uses free text — switch to structured Goal/Progress/Decisions/Next Steps format |
| **Session tree (JSONL)** | Pi | Replace SQLite task storage with append-only JSONL tree; enables branching + efficient replay |
| **Skills discovery via descriptions** | Pi | Inject all skill descriptions into every system prompt; let LLM decide which to load, not user |
| **2-round failure cap** | Stripe | Add hard iteration cap to `/loop` (e.g., 3 consecutive failures → escalate to human) |

### Medium Impact

| Pattern | Source | What to Adopt |
|---------|--------|---------------|
| **Pre-hydration hook** | Pi | Add `before_agent_start` hook in Claude Code hooks — inject git status, TODO.md summary, recent failures before each session |
| **Tool output truncation** | Pi | Add explicit truncation (50KB / 2000 lines) to all Clade tool wrappers |
| **Curated tool subsets per task type** | Stripe | Different worker types (implement vs review vs fix) get different tool lists |
| **RPC mode for orchestrator** | Pi | Orchestrator communicates with workers via JSONL RPC instead of file polling |
| **Agent definitions as Markdown** | Pi | Worker agent definitions as `.md` files with frontmatter (name/description/tools/model) |

### Lower Impact (but clean)

| Pattern | Source | What to Adopt |
|---------|--------|---------------|
| **Retry: error removed from context** | Pi | On retryable failure, remove error message from LLM context before retry |
| **Extension hot-reload** | Pi | Skills can be reloaded without restarting the agent |
| **Rule files same format as Cursor** | Stripe | Consolidate Clade rule files to match `.cursor/rules` format; shared maintenance |
| **Background lint daemon** | Stripe | Pre-run syntax/type check in background before commit, not as blocking step |

---

## 5. What We Should NOT Copy

- **Devbox AWS EC2 setup**: Stripe's infrastructure is at a completely different scale. Git worktrees (what Clade uses) are the right equivalent.
- **Toolshed's 500 tools**: overkill. Curate, don't accumulate.
- **Pi's full extension TypeScript system**: good architecture but engineering overhead. Claude Code hooks + skills are simpler for our use case.
- **Pi's full multi-provider abstraction**: we're Claude-native; this complexity isn't needed.

---

## 6. The Big Rewrite Question

Given Stripe + Pi findings, Clade's fundamental architecture should shift toward:

```
Current Clade                    Target Direction
─────────────────────────────    ──────────────────────────────
Skills: slash commands           → Skills: auto-discovered by description
Loop: pure LLM decides all       → Blueprints: deterministic pre/post + LLM nodes
Handoff: free-text summary       → Structured compaction (Goal/Progress/Decisions)
Session: SQLite rows             → Append-only JSONL tree with branching
UI: terminal scrollback          → Visual window with session tree navigation
Orchestrator: polling workers    → RPC-driven workers (JSONL protocol)
Skills docs: ad-hoc              → Uniform frontmatter: name/description/tools
```

The core insight from both Stripe and Pi: **the interface between human intent and agent execution needs structure**. Today's Clade is too free-form — skills are named but not described, loops iterate without hard stop conditions, sessions accumulate without structured checkpoints.

Both masters have independently converged on: structured metadata → discoverable capabilities → bounded execution → structured state preservation.
