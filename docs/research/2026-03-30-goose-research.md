---
name: 2026-03-30-goose-research.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "Goose: 5 MCP transport types, Recipe YAML with Jinja2 templates, AGENTS.md subdirectory loading, GooseMode permissions"
integrated_items:
  - "MCP server architecture — Clade MCP server implemented in orchestrator/"
  - "AGENTS.md pattern — Clade uses CLAUDE.md instead"
needs_work_items:
  - "Recipe dependency system with Jinja2 templates — could enhance goal file format"
  - "AGENTS.md subdirectory loading — not implemented (Clade only reads root CLAUDE.md)"
reference_items:
  - "5 MCP transports: Stdio, StreamableHttp, Platform, Builtin, InlinePython"
  - "Recipe YAML format with sub_recipes and value templates"
---

# Goose (block/goose) Deep Research

**Date**: 2026-03-30  
**Sources**: GitHub repo (block/goose @ v1.28.0), source code, official docs, blog posts  
**Purpose**: Understand Goose architecture for Clade design inspiration

---

## Quick Stats

| Metric | Value |
|--------|-------|
| Stars | 33,785 |
| Forks | 3,157 |
| Language | Rust (core) + TypeScript (Electron UI) |
| Latest | v1.28.0 (2026-03-18) |
| License | Apache 2.0 |
| Created | 2024-08-23 |

---

## 1. Overall Architecture

Goose is a **two-interface, one-backend** system. The same core library (`crates/goose`) powers both a CLI (`crates/goose-cli`) and a desktop Electron app (`ui/desktop`). The desktop app communicates with a background HTTP server (`crates/goose-server`, binary: `goosed`) via REST + SSE.

### Module Hierarchy (Rust crates)

```
crates/
├── goose              # Core library — all agent logic
│   ├── agents/        # Agent, ExtensionManager, MCP client, platform tools
│   ├── providers/     # LLM provider trait + 30+ implementations
│   ├── recipe/        # Recipe format, builder, template engine
│   ├── session/       # Session persistence (SQLite via sqlx)
│   ├── context_mgmt/  # Conversation compaction
│   ├── hints/         # .goosehints / AGENTS.md loading
│   ├── security/      # Prompt injection scanner
│   ├── config/        # Config YAML + keyring secrets
│   └── acp/           # Agent Client Protocol (ACP/SACP)
│
├── goose-cli          # CLI entry: `goose` binary
├── goose-server       # HTTP server: `goosed` binary (Axum)
├── goose-mcp          # Bundled MCP servers (developer, memory, etc.)
├── goose-acp          # ACP server implementation
└── goose-acp-macros   # Proc macros for ACP custom methods

ui/desktop/            # Electron app (TypeScript + Vite)
```

### Data Flow

```
User (CLI/Desktop)
     │
     ▼
goose-server (Axum REST + SSE)
     │  POST /reply   ← message in
     │  GET  /events  ← SSE stream out (AgentEvent)
     ▼
Agent (goose core)
     │  reply() → BoxStream<AgentEvent>
     ├─→ ExtensionManager.call_tool()
     │       ├─→ MCP stdio subprocess (external MCP server)
     │       ├─→ MCP streamable HTTP (remote MCP server)
     │       ├─→ Platform extension (in-process Rust impl)
     │       └─→ Builtin MCP server (in-process via DuplexStream)
     │
     └─→ Provider.stream() → LLM API
```

### Key Structural Decisions

1. **Rust core, TypeScript shell**: All logic lives in `goose`. The Electron app is thin — it renders UI and proxies through `goosed`. No business logic in TypeScript.

2. **Single config file**: `~/.config/goose/config.yaml` shared between CLI and Desktop. Extensions, provider settings, permissions all in one YAML.

3. **Secrets in system keyring**: API keys stored via OS keyring (not in config.yaml). Config stores `env_keys: [MY_KEY]` as pointer; keyring holds the value.

4. **SQLite session storage**: Sessions persisted in `~/.local/share/goose/sessions/sessions.db` (schema version 9 as of v1.28).

---

## 2. MCP-Native Design Philosophy

### Why MCP?

Goose's core thesis: **extensions = MCP servers, full stop**. There is no proprietary plugin format. Every extension (whether a remote service, a local subprocess, or a bundled Rust implementation) speaks the Model Context Protocol.

Stated advantages:
- Zero lock-in: any MCP server works out-of-the-box (Stripe's Toolshed, GitHub Copilot's tools, etc.)
- Standard tool schema (JSON Schema) understood by every LLM
- Existing MCP ecosystem (~thousands of servers) immediately usable
- Extension authors write once, work with any MCP-compatible agent

Goose itself *is* exposed as an MCP server (ACP layer, see §6).

### ExtensionConfig — All Five Transport Types

```rust
// crates/goose/src/agents/extension.rs
pub enum ExtensionConfig {
    // 1. External process via stdin/stdout (most common)
    Stdio { name, cmd, args, envs, env_keys, timeout, .. }

    // 2. Remote MCP server via HTTP streaming
    StreamableHttp { name, uri, envs, headers, timeout, .. }

    // 3. In-process Rust impl (platform extensions)
    //    — no subprocess overhead, direct Rust function calls
    Platform { name, display_name, .. }

    // 4. Bundled MCP binary shipped inside goose
    //    — runs as child process but the binary is embedded
    Builtin { name, display_name, timeout, .. }

    // 5. Inline Python code (executes via `uvx --with mcp python`)
    InlinePython { name, code, dependencies, timeout, .. }

    // (deprecated) Sse — kept for config file compatibility only
}
```

### How MCP Registration Works

**Static registration** (persisted in config.yaml):
```yaml
extensions:
  my_tool:
    enabled: true
    type: stdio
    name: my_tool
    cmd: npx
    args: ["-y", "@modelcontextprotocol/server-everything"]
    timeout: 300
```

**Dynamic registration** (via the `manage_extensions` platform tool at runtime):  
The `ext_manager` platform extension exposes tools like `search_available_extensions` and `manage_extensions` that allow the LLM itself to add/remove/enable/disable extensions during a session.

**Code path for adding a Stdio extension**:
```
ExtensionManager::add_extension(config)
  → resolve env vars (config + keyring)
  → malware check (deny_if_malicious_cmd_args)
  → spawn child process (Command::new(cmd))
  → wrap in GooseMcpClient (implements McpClientTrait)
  → store in extensions: HashMap<String, Extension>
```

### McpClientTrait — The Core Interface

```rust
// crates/goose/src/agents/mcp_client.rs
#[async_trait]
pub trait McpClientTrait: Send + Sync {
    async fn list_tools(&self, session_id, cursor, cancel_token) -> ListToolsResult;
    async fn call_tool(&self, ctx, name, arguments, cancel_token) -> CallToolResult;
    fn get_info(&self) -> Option<&InitializeResult>;
    async fn list_resources(&self, ..) -> ListResourcesResult;
    async fn read_resource(&self, ..) -> ReadResourceResult;
    async fn list_prompts(&self, ..) -> ListPromptsResult;
    async fn get_prompt(&self, ..) -> GetPromptResult;
    async fn subscribe(&self) -> mpsc::Receiver<ServerNotification>;
    async fn get_moim(&self, session_id) -> Option<String>;  // MOIM injection
    async fn update_working_dir(&self, new_dir) -> Result<()>;
}
```

Platform extensions implement `McpClientTrait` directly in Rust — no subprocess, no serialization overhead. Builtin MCP servers use `tokio::io::DuplexStream` for zero-copy in-process communication.

### Tool Namespacing

External MCP tools are **prefixed** with the extension name:
- Extension `github` tool `create_pr` → exposed as `github__create_pr`

Platform extensions with `unprefixed_tools: true` are exposed without prefix (e.g., `developer` tools: `shell`, `write`, `edit`, `read`, `tree`).

---

## 3. AGENTS.md Open Standard

### What It Is

AGENTS.md is Goose's (and Codex's) answer to CLAUDE.md: a **project-context file** that the agent injects into system prompt when entering a directory. Goose treats it as an open, universal standard — any agent framework should honor it.

Key code:
```rust
// crates/goose/src/hints/load_hints.rs
pub const GOOSE_HINTS_FILENAME: &str = ".goosehints";  // Goose-specific
pub const AGENTS_MD_FILENAME: &str = "AGENTS.md";       // Universal standard
```

Both files are loaded. They are concatenated into the system prompt via `load_hint_files()`. The list is configurable via `CONTEXT_FILE_NAMES` env var.

### AGENTS.md vs CLAUDE.md — Concrete Differences

| Aspect | AGENTS.md | CLAUDE.md |
|--------|-----------|-----------|
| Scope | Universal — honored by Goose, Codex, Pi, others | Claude Code-specific |
| Location | Project root (and subdirectories, loaded lazily) | Project root or `~/.claude/` |
| Auto-discovery | Yes — loaded when agent enters any dir | Yes — loaded at session start |
| Subdirectory hints | Yes — loaded when tool touches a subdirectory | No — only root loaded |
| Format | Free-form Markdown | Free-form Markdown |
| Naming convention | Convention, not enforced | Enforced by Claude Code |
| Global user file | No | `~/.claude/CLAUDE.md` |
| File imports | Via `@file` syntax in `.goosehints` | No |

### AGENTS.md Format Specification

AGENTS.md is **free-form Markdown** — there is no strict schema. By convention:

```markdown
# AGENTS Instructions

## Setup
Steps to initialize the development environment.

## Commands

### Build
```bash
cargo build
```

### Test
```bash
cargo test
```

### Lint
```bash
cargo clippy
```

## Structure
Brief description of the repository layout.

## Rules
- Rule 1: constraint on agent behavior
- Rule 2: coding conventions

## Never
Things the agent must never do.

## Entry Points
- CLI: path/to/main.rs
- Server: path/to/server.rs
```

Goose's own `AGENTS.md` is a near-perfect reference implementation (see the file at the top of this document's research). Key fields it actually uses:
- **Setup** — how to activate the build environment
- **Commands** — build, test, lint, UI
- **Git** — commit conventions (DCO sign-off)
- **Structure** — crate layout
- **Development Loop** — iterative dev workflow
- **Rules** — coding standards (Tests, Error, Provider, MCP, Server)
- **Code Quality** — comment philosophy
- **Never** — hard prohibitions
- **Entry Points** — binary roots

### Subdirectory Loading

Goose dynamically loads hints from subdirectories as the agent navigates:
```rust
// SubdirectoryHintTracker watches tool call arguments
// When a tool uses a path argument, the parent directory is queued
// On next turn, hints from that directory are injected
impl SubdirectoryHintTracker {
    fn record_tool_arguments(&mut self, arguments, working_dir);
    fn load_new_hints(&mut self, working_dir) -> Vec<(String, String)>;
}
```
This means a monorepo can have `services/payments/AGENTS.md`, `services/auth/AGENTS.md`, each loaded only when the agent enters that subdirectory. CLAUDE.md does not support this.

---

## 4. Session Management

### Storage Architecture

Sessions use **SQLite via sqlx**, schema version 9:
- DB path: `~/.local/share/goose/sessions/sessions.db`
- Each session = one row with full metadata + serialized conversation

```rust
pub struct Session {
    pub id: String,
    pub working_dir: PathBuf,
    pub name: String,              // auto-generated or user-set
    pub user_set_name: bool,
    pub session_type: SessionType, // User | Scheduled | SubAgent | Hidden | Terminal | Gateway | Acp
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub extension_data: ExtensionData,
    pub total_tokens: Option<i32>,
    pub input_tokens: Option<i32>,
    pub output_tokens: Option<i32>,
    pub accumulated_total_tokens: Option<i32>,
    // ... accumulated input/output tokens
    pub schedule_id: Option<String>,
    pub recipe: Option<Recipe>,
    pub user_recipe_values: Option<HashMap<String, String>>,
    pub conversation: Option<Conversation>,  // full message history
    pub message_count: usize,
    pub provider_name: Option<String>,
    pub model_config: Option<ModelConfig>,
    pub goose_mode: GooseMode,
}
```

### Session Types

```rust
pub enum SessionType {
    User,       // Normal interactive session
    Scheduled,  // Triggered by scheduler
    SubAgent,   // Spawned by delegate/summon tool
    Hidden,     // Internal sessions not shown in UI
    Terminal,   // Terminal-based sessions
    Gateway,    // ACP gateway sessions
    Acp,        // Agent Client Protocol sessions
}
```

`SubAgent` sessions cannot spawn further delegates (nested delegation prevention — enforced at the agent level).

### Conversation Compaction

Automatic compaction triggers when context usage exceeds `DEFAULT_COMPACTION_THRESHOLD = 0.8` (80%):
```rust
pub async fn compact_messages(
    provider: &dyn Provider,
    session_id: &str,
    conversation: &Conversation,
    manual_compact: bool,
) -> Result<(Conversation, ProviderUsage)>
```

Strategy:
1. Identify the last assistant text message
2. Summarize all prior messages (tool pairs batched in groups of 10)
3. Replace old messages with the summary
4. Continue from summary point

Manual triggers: `/compact`, `/summarize`, "Please compact this conversation".

Thinking text shown to user: "goose is compacting the conversation..."

### MOIM (Message of Incoming Messages)

A context injection mechanism that adds a timestamped info block before each turn:
```
<info-msg>
It is currently 2026-03-30 14:35:00
Working directory: /home/user/project
[background task status if any subagents running]
</info-msg>
```

This gives the LLM temporal awareness and working directory without burning tokens on every system prompt regeneration. Only injected for models with context >= 32k tokens.

### Auto-Naming

Sessions are auto-named by asking the LLM after message 3:
```rust
pub static MSG_COUNT_FOR_SESSION_NAME_GENERATION: usize = 3;
```

---

## 5. Extension System

### Five Categories of Extensions

**1. External MCP Servers (Stdio)**  
Most common. Any command that implements MCP stdio transport. Examples: `npx @modelcontextprotocol/server-github`, `uvx mcp-server-git`.

**2. Remote MCP Servers (StreamableHttp)**  
Persistent HTTP endpoints. Used for managed services (e.g., Stripe Toolshed). Auth via env vars or headers.

**3. Platform Extensions (in-process Rust)**  
Built into the goose binary. Zero overhead, direct Rust function calls. Current platform extensions:

| Name | Description |
|------|-------------|
| `developer` | File ops (write/edit/read), shell, tree — the core coding toolkit |
| `analyze` | Code structure analysis via tree-sitter |
| `todo` | In-session task tracking |
| `apps` | HTML/CSS/JS app creation (sandboxed windows) |
| `chatrecall` | Search past conversations |
| `ext_manager` | Enable/disable/discover extensions at runtime |
| `orchestrator` | Multi-agent session management |
| `summon` | load/delegate tools (recipe + subagent launcher) |
| `summarize` | Conversation summarization |
| `tom` | (internal) |

**4. Builtin MCP Servers (embedded binary)**  
Shipped inside goose, exposed via `goose mcp <server>`. Implementations in `crates/goose-mcp/`:

| Name | Purpose |
|------|---------|
| `computercontroller` | Web scraping, PDF/DOCX/XLSX processing, system automation |
| `memory` | Persistent key-value memory |
| `autovisualiser` | Auto-visualize data |
| `tutorial` | Interactive tutorial content |
| `peekaboo` (macOS) | Screenshot capture |

**5. InlinePython**  
Write Python MCP server inline in a recipe's YAML. Auto-executes via `uvx --with mcp python`:
```yaml
extensions:
  - type: inline_python
    name: my_tool
    code: |
      # Standard MCP Python server code
      from mcp.server import Server
      ...
    dependencies: ["numpy", "pandas"]
```

### Security: Env Var Sanitization

Goose blocks 31 sensitive environment variables from being overridden by extensions (including `PATH`, `LD_PRELOAD`, `PYTHONPATH`, `NODE_OPTIONS`, etc.). Any attempt to set these logs a warning and silently drops the value.

### Runtime Extension Management

The `manage_extensions` platform tool lets the LLM enable/disable extensions during a session. The `search_available_extensions` tool lists what's configured. This enables self-reconfiguring agents.

---

## 6. ACP — Agent Client Protocol

Beyond MCP (which is for tools), Goose implements **ACP (Agent Client Protocol)** for agent-to-agent communication. This uses the `sacp` crate (Streaming Agent Client Protocol) under the hood.

ACP exposes an entire running Goose instance as a service:
- Session management (create/load/close sessions)
- Real-time streaming of agent responses
- Permission negotiation
- MCP capability advertisement

Transport: HTTP + SSE or WebSocket.

This is what enables embedding Goose inside other applications (VS Code Copilot Chat, Cursor, etc.) via the `goose-acp` crate.

```rust
// The main ACP server implementation
pub struct GooseAcpAgent {
    sessions: Arc<Mutex<HashMap<String, GooseAcpSession>>>,
    provider_factory: ProviderConstructor,
    session_manager: Arc<SessionManager>,
    permission_manager: Arc<PermissionManager>,
    goose_mode: GooseMode,
    // ...
}
```

---

## 7. Recipe System

### What is a Recipe?

A Recipe is a **portable, versioned, parameterized agent workflow** defined in YAML or JSON. It encapsulates:
- The system prompt (instructions)
- The opening message (prompt)
- Which extensions to enable
- LLM settings (provider, model, temperature, max_turns)
- Parameters with types and defaults
- Expected output schema (JSON Schema)
- Sub-recipes for decomposition
- Retry logic with shell-command success checks

Recipes are Goose's answer to "reproducible agent workflows." A recipe is the unit of sharing in the Goose cookbook.

### Complete Recipe Schema

```yaml
# Required fields
version: "1.0.0"                    # Semver format version
title: "Recipe Name"                # Short title
description: "What this does"       # Longer description

# At least one required:
instructions: |                      # System prompt / agent behavior
  You are a...
prompt: |                           # Opening user message (optional)
  Do X for {{ parameter_name }}

# Optional
extensions:
  - type: builtin                   # or stdio, streamable_http, platform, inline_python
    name: developer
    timeout: 300
    bundled: true

settings:
  goose_provider: anthropic
  goose_model: claude-sonnet-4-5
  temperature: 0.7
  max_turns: 50

parameters:
  - key: input_file                 # Referenced as {{ input_file }} in prompt/instructions
    input_type: string              # string | number | boolean | date | file | select
    requirement: required           # required | optional | user_prompt
    description: "Path to input"
    default: "./input.txt"
    options: ["a", "b", "c"]       # For select type

response:
  json_schema:                      # Force structured JSON output
    type: object
    properties:
      result: { type: string }
    required: ["result"]

sub_recipes:
  - name: analysis_step
    path: ./analyze.yaml
    values:
      target: "{{ input_file }}"
    sequential_when_repeated: false  # Run parallel when called multiple times

retry:
  max_retries: 3
  checks:
    - command: "test -f output.json"  # Shell command — exit 0 = success
      description: "Output file exists"
  on_failure: "rm -f output.json"    # Cleanup before retry
  timeout_seconds: 300
  on_failure_timeout_seconds: 600

activities:                          # UI "pills" shown in Desktop loading screen
  - "Phase 1: Analysis"
  - "Phase 2: Implementation"

author:
  contact: "github-username"
  metadata: "Optional extra info"
```

### Template Engine

Recipes use **Jinja2-style syntax**:
- `{{ parameter_name }}` — parameter substitution
- `{% if condition %}...{% endif %}` — conditional blocks  
- `{% extends %}` — template inheritance
- `{{ value | indent(4) }}` — filters
- `{{'{{literal}}'}}` — escape double braces

### Sub-recipes

Sub-recipes enable decomposition of complex workflows into reusable components. When `sub_recipes` is present, Goose auto-injects the `summon` platform extension (which provides `delegate` and `load` tools).

### The `summon` Extension: load + delegate

This is the core multi-agent primitive:

**`load(source?, cancel?)`**  
- Called with no args: lists all available sources (recipes, skills, agents)
- Called with a source name: injects its content into current context
- Called with `cancel: true` + a task ID: cancels a background delegate

**`delegate(instructions, source?, async?)`**  
- Spawns a subagent with `SessionType::SubAgent`
- `async: false` (default): blocks until complete, returns result text
- `async: true`: returns a task ID immediately, runs in background
- Multiple async delegates in one turn run **in parallel**
- Subagents cannot spawn further delegates (prevents unbounded recursion)

Background delegates are tracked via MOIM (the context info block), giving the main agent visibility into running tasks.

### Recipe Discovery

Goose loads recipes from:
1. `~/.config/goose/recipes/` — user's local recipes
2. `$RECIPE_DIR` env var
3. Current working directory (for sub-recipes)

The `load()` tool discovers and lists all of these.

---

## 8. GooseMode — Permission Levels

```rust
pub enum GooseMode {
    Auto,         // All tool calls approved automatically (unattended)
    Approve,      // Every tool call requires confirmation
    SmartApprove, // Only sensitive/risky calls require confirmation
    Chat,         // No tool calls at all (pure LLM chat)
}
```

Default: `Auto`. This is critical for Stripe Minions (see §9) — they run in `Auto` mode with isolation guarantees from the infrastructure layer.

---

## 9. Stripe Minions — Fork Analysis

### What Minions Is

Stripe Minions is not a public fork. It is an **internal deployment of Goose** with Stripe-specific customizations. Key facts from Stripe's engineering blog:
- "Agent Harness: forked goose, fully unattended, no confirmation dialogs"
- Running at 1,300+ PRs/week in production
- Heavily customized context engineering on top of the core Goose engine

### Changes Stripe Made (inferred from blog posts)

1. **GooseMode forced to Auto** — No confirmation dialogs whatsoever. Safety comes from infrastructure isolation (no prod access, no internet egress), not agent-level guards.

2. **Blueprint state machine** wrapped around Goose agent — The deterministic pre/post phases (lint, push, CI) are handled outside Goose. Goose handles only the `[AGENT NODE]` steps.

3. **Toolshed MCP integration** — Stripe built ~500 internal tools as MCP servers accessible to agents. Each agent type receives a **curated subset** — flooding an agent with 500 tools degrades reasoning.

4. **Pre-hydration pattern** — Before the agent node runs, all Slack thread links, tickets, and code references are fetched deterministically and injected into context.

5. **Context rules format** — Uses `.cursor/rules` subdirectory format (compatible with Cursor, Claude Code, and Goose simultaneously). The same rule files feed all their coding agents.

6. **Hard caps** — 2 CI rounds max (hard-coded). "Diminishing marginal returns if an LLM runs against indefinitely many CI rounds."

7. **No session persistence** — Each blueprint run is ephemeral. No resuming old sessions.

### The Core Insight from Minions

**LLMs should only handle genuinely uncertain decisions. All deterministic steps should be handled outside the agent node.**

Goose provides the `auto` mode agent. Stripe's Blueprint wraps it in a state machine. This pattern — deterministic shell + agentic core + deterministic shell — is the key innovation.

---

## 10. Linux Foundation AAIF Governance

Based on available public information (Goose GOVERNANCE.md and blog posts):

Goose follows a **lightweight technical governance model** with:
- **Contributors**: community members
- **Maintainers**: trusted members with write access to specific components
- **Core Maintainers**: 3-7 members with admin access, set overall direction
- Deadlock resolution: Bradley Axen (Goose creator at Block) as tie-breaker

### AAIF (Agents and AI Framework)

AAIF is a Linux Foundation initiative aimed at standardizing agent interoperability. Block/Goose has been involved in this space. The specific donation details were not publicly accessible at research time, but the project's governance document shows commitment to open standards.

The key implication for MCP standardization: by having Goose (the leading open-source local agent) adopt MCP as its sole extension mechanism, and AGENTS.md as a universal project context standard, Block is effectively establishing these as de-facto industry standards regardless of formal governance.

---

## 11. Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    goose (Rust core)                      │
│                                                           │
│  ┌─────────────────┐    ┌──────────────────────────────┐ │
│  │     Agent        │    │      ExtensionManager         │ │
│  │  - reply()       │◄──►│  - extensions: HashMap        │ │
│  │  - GooseMode     │    │  - add_extension()            │ │
│  │  - RetryManager  │    │  - call_tool()                │ │
│  │  - SessionConfig │    │  - list_tools()               │ │
│  └────────┬─────────┘    └──────────┬───────────────────┘ │
│           │                          │                      │
│  ┌────────▼─────────┐    ┌──────────▼───────────────────┐ │
│  │  Provider trait  │    │       McpClientTrait           │ │
│  │  - stream()      │    │  implementations:              │ │
│  │  - complete()    │    │  ├─ GooseMcpClient (stdio)     │ │
│  │                  │    │  ├─ StreamableHttpClient       │ │
│  │  30+ impls:      │    │  ├─ Platform (in-process)      │ │
│  │  Anthropic,OpenAI│    │  └─ Builtin (DuplexStream)     │ │
│  │  Gemini, Ollama  │    └──────────────────────────────┘ │
│  │  Azure, Bedrock  │                                      │
│  │  OpenRouter, ...  │    ┌──────────────────────────────┐ │
│  └──────────────────┘    │       Session (SQLite)         │ │
│                           │  - id, type, working_dir      │ │
│  ┌───────────────────┐    │  - conversation history       │ │
│  │    Recipe engine  │    │  - token usage                │ │
│  │  - YAML/JSON parse│    │  - recipe + parameters        │ │
│  │  - Jinja templates│    └──────────────────────────────┘ │
│  │  - SubRecipes     │                                      │
│  │  - RetryConfig    │    ┌──────────────────────────────┐ │
│  └───────────────────┘    │     context_mgmt             │ │
│                           │  - compaction (80% threshold)  │ │
│  ┌───────────────────┐    │  - MOIM injection              │ │
│  │    hints/         │    └──────────────────────────────┘ │
│  │  - AGENTS.md      │                                      │
│  │  - .goosehints    │                                      │
│  │  - subdirectory   │                                      │
│  │    lazy-loading   │                                      │
│  └───────────────────┘                                      │
└─────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
  goose-cli (bin)             goose-server (Axum)
  - `goose session`           - POST /reply
  - `goose run`               - GET  /sessions/{id}/events (SSE)
  - `goose sessions list`     - REST /sessions, /config, /recipe
                              - WebSocket /ws
                                        │
                                        ▼
                               ui/desktop (Electron)
                               TypeScript + Vite
                               - Auto-generated API client
                               - just generate-openapi
```

---

## 12. Borrowable Patterns for Clade

### Pattern 1: Recipe as the Unit of Work

**What Goose does**: Recipes decouple "what to do" (instructions) from "how to run it" (provider, extensions, parameters). A recipe is portable, versioned, shareable.

**Clade equivalent today**: Skills (`.md` files) + loop goals (`.md` files). They're not parameterized and don't specify which extensions to use.

**Borrowable**: Add a `recipe:` header to skill files:
```yaml
---
provider: claude-sonnet-4-5
extensions: [developer]
parameters:
  - key: target
    type: string
    required: true
---
# Skill content here with {{ target }} substitution
```

### Pattern 2: RetryConfig with Shell Checks

**What Goose does**: Recipe `retry` block defines `max_retries` + shell commands as success predicates. The agent loops until all checks pass or retries exhausted.

**Clade equivalent today**: Loop goals with ad-hoc convergence criteria in plain text.

**Borrowable**: Add structured success criteria to goal files:
```yaml
convergence:
  checks:
    - command: "cd orchestrator && python -m py_compile server.py"
    - command: "cd orchestrator && .venv/bin/python -m pytest tests/ -q"
  max_iterations: 5
```

### Pattern 3: Deterministic Pre/Post Phase (Blueprint Pattern)

**What Stripe Minions does**: Wraps the agent in a state machine. The agent is only invoked for genuinely uncertain nodes. Linting, pushing, creating PRs are deterministic shell steps.

**Clade equivalent today**: `loop-runner.sh` runs Claude for everything, including trivially deterministic steps.

**Borrowable**: Add a `blueprint:` section to loop goal files:
```yaml
pre_agent:
  - run: "cd orchestrator && python -m py_compile *.py"
  - run: "git status --short"
agent: true   # run the LLM here
post_agent:
  - run: "cd orchestrator && .venv/bin/python -m pytest tests/ -q"
  - if_success: "committer 'feat: complete goal' *.py"
```

### Pattern 4: SubAgent Type Isolation

**What Goose does**: `SessionType::SubAgent` is checked before allowing delegation. Subagents cannot spawn their own delegates. This is enforced at the infrastructure level, not relying on the LLM to "know" it shouldn't.

**Clade equivalent today**: No such isolation. Workers could theoretically spawn nested sessions.

**Borrowable**: Add a `WORKER_SESSION=1` env var check in `loop-runner.sh` worker sessions, and have the `batch-tasks` skill refuse to launch workers that already have this set.

### Pattern 5: AGENTS.md Subdirectory Loading

**What Goose does**: Lazily loads `.goosehints`/`AGENTS.md` from subdirectories as the agent navigates to them. A monorepo can have per-service context files.

**Clade equivalent today**: CLAUDE.md is loaded once at session start.

**Borrowable**: In the `start` skill's pre-work, scan for CLAUDE.md files in commonly-touched subdirectories and include them in the session context dynamically.

### Pattern 6: Inline Python MCP Extensions

**What Goose does**: `InlinePython` extension type — write a Python MCP server directly in a recipe YAML. `uvx --with mcp python` runs it in an isolated virtualenv.

**Clade equivalent today**: No equivalent. Skills are static Markdown.

**Borrowable**: Skills could embed executable Python helpers that run as local MCP servers, giving Claude Code richer tool access without requiring globally-installed packages.

### Pattern 7: GooseMode Auto with Infrastructure Isolation

**What Goose does**: `auto` mode = zero confirmation dialogs. Safety guaranteed by running in an isolated environment (no prod DB access, no internet egress), not by asking the LLM to be careful.

**Clade equivalent today**: Loop sessions already run unattended. But "fix now" behavior (from CLAUDE.md: "Execute clear non-destructive fixes immediately") relies on the LLM's judgment.

**Implication**: The right model is to push the safety boundary to the infrastructure level — restrict what directories/commands are accessible, not what the LLM is "allowed" to do. The LLM should be fully autonomous within a constrained sandbox.

### Pattern 8: Tool Subsetting

**What Stripe does**: Each agent type gets a curated subset of the 500 available Toolshed tools. More tools = worse reasoning.

**Clade equivalent today**: Workers run with all Claude Code tools available.

**Borrowable**: In recipes/skills, specify `available_tools: [shell, write, edit, read]` to restrict the tool surface for focused tasks. Goose already has this field in `ExtensionConfig`.

---

## 13. Key Takeaways

1. **MCP is the universal extension format**. Goose's bet has been validated by the ecosystem: every major agent framework now speaks MCP. Building proprietary plugin systems is wasted effort.

2. **Recipes are the right abstraction for workflows**. The Recipe schema (instructions + extensions + parameters + retry + sub_recipes) is more powerful than plain goal `.md` files. It makes workflows reproducible, shareable, and testable.

3. **Blueprint pattern separates determinism from agency**. The most effective agents don't let LLMs decide whether to run linters — they constrain LLM agency to only the genuinely uncertain decisions.

4. **Subagent isolation is an infrastructure concern**. Preventing nested delegation, enforcing session types, capping max_turns — these belong in the harness, not the prompt.

5. **Context engineering > prompt engineering**. Goose's MOIM, subdirectory hint loading, pre-hydration pattern — all about giving the model the right information at the right time, not crafting clever instructions.

6. **AGENTS.md will become universal**. It's being adopted by Goose, Codex, and other frameworks. Supporting it in Clade's hooks/install means Clade works better in any project that has it.
