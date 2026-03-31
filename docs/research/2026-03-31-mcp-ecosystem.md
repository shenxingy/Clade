# MCP (Model Context Protocol) Ecosystem — Deep Research

**Date**: 2026-03-31
**Scope**: MCP protocol specification, ecosystem mapping, AI coding tool integrations, comparison with skills/plugins
**Purpose**: Foundation for Clade skills auto-discovery using MCP as the protocol layer

---

## Executive Summary

MCP (Model Context Protocol) is an open-source standard for connecting AI applications to external systems — data sources, tools, and workflows. Launched by Anthropic in late 2024, MCP reached 8 million downloads within 5 months of release, establishing itself as the dominant protocol for AI tool interoperability. The protocol is now governed by the Linux Foundation's Agentic AI Foundation (AAIF), with major contributors including Anthropic, GitHub, Microsoft, and Google.

For the Clade redesign, MCP is directly relevant: **Clade skills map naturally to MCP tools**, and MCP's discovery mechanism (`tools/list`, `prompts/list`) could replace the current manual skill registration system with automatic discovery.

---

## 1. MCP Protocol Specification

### 1.1 Protocol Overview

MCP defines a **client-server architecture** where an MCP host (AI application like Claude Code or Cursor) creates one MCP client per MCP server. Each client maintains a dedicated connection to its corresponding server.

```
MCP Host (AI Application)
  ├── MCP Client 1 ←→ MCP Server A (e.g., Filesystem)
  ├── MCP Client 2 ←→ MCP Server B (e.g., GitHub)
  └── MCP Client 3 ←→ MCP Server C (e.g., Database)
```

**Key analogy**: MCP is like USB-C for AI applications. Just as USB-C provides a standardized way to connect devices, MCP provides a standardized way to connect AI applications to external systems.

### 1.2 Protocol Layers

MCP consists of two layers:

1. **Data Layer**: JSON-RPC 2.0 based protocol for client-server communication
   - Lifecycle management (initialization, capability negotiation, shutdown)
   - Core primitives (tools, resources, prompts)
   - Client primitives (sampling, elicitation, logging)
   - Utility features (notifications, progress tracking, tasks)

2. **Transport Layer**: Communication mechanisms between participants
   - **Stdio transport**: Standard input/output for local processes (optimal performance, no network overhead)
   - **Streamable HTTP transport**: HTTP POST + optional SSE for remote servers, supports OAuth/bearer tokens

### 1.3 Discovery Mechanism (Lifecycle Handshake)

The MCP connection begins with a capability negotiation handshake:

**Step 1: Client sends `initialize` request**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-11-25",
    "capabilities": {
      "elicitation": {},
      "roots": { "listChanged": true },
      "sampling": {}
    },
    "clientInfo": {
      "name": "claude-desktop",
      "version": "1.0.0"
    }
  }
}
```

**Step 2: Server responds with its capabilities**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-11-25",
    "capabilities": {
      "tools": { "listChanged": true },
      "resources": { "subscribe": true }
    },
    "serverInfo": {
      "name": "filesystem-server",
      "version": "1.0.0"
    }
  }
}
```

**Step 3: Client sends `notifications/initialized`**
```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

**Version negotiation**: If client sends `"2025-11-25"` but server only supports `"2025-06-18"`, server responds with its supported version. Client either accepts or disconnects.

### 1.4 Core Primitives (Server-Side)

MCP defines three core primitives that servers can expose:

#### Tools
Executable functions that AI models can invoke. Each tool has:
- `name`: Unique identifier (e.g., `filesystem_read_file`)
- `title`: Human-readable display name
- `description`: Detailed explanation
- `inputSchema`: JSON Schema for parameter validation
- `outputSchema` (optional): Expected output structure

**Protocol operations:**
| Method | Purpose | Returns |
|--------|---------|---------|
| `tools/list` | Discover available tools | Array of tool definitions |
| `tools/call` | Execute a specific tool | Tool execution result |

**Example tool definition:**
```json
{
  "name": "searchFlights",
  "description": "Search for available flights",
  "inputSchema": {
    "type": "object",
    "properties": {
      "origin": { "type": "string", "description": "Departure city" },
      "destination": { "type": "string", "description": "Arrival city" },
      "date": { "type": "string", "format": "date" }
    },
    "required": ["origin", "destination", "date"]
  }
}
```

**User interaction model**: Tools are **model-controlled** — AI models can discover and invoke them automatically. However, MCP emphasizes human oversight through approval dialogs, permission settings, and activity logs.

#### Resources
Passive data sources providing read-only context. Each resource has:
- `uri`: Unique identifier (e.g., `file:///path/to/doc.md`)
- `name`: Display name
- `mimeType`: Content type
- `annotations` (optional): `audience`, `priority`, `lastModified`

**Two discovery patterns:**
- **Direct Resources**: Fixed URIs pointing to specific data
- **Resource Templates**: Dynamic URIs with parameters (e.g., `travel://activities/{city}/{category}`)

**Protocol operations:**
| Method | Purpose | Returns |
|--------|---------|---------|
| `resources/list` | List direct resources | Array of resource descriptors |
| `resources/templates/list` | Discover resource templates | Array of template definitions |
| `resources/read` | Retrieve resource contents | Resource data with metadata |
| `resources/subscribe` | Monitor resource changes | Subscription confirmation |

**User interaction model**: Resources are **application-driven** — the host application decides how to incorporate context (tree views, search, automatic inclusion).

#### Prompts
Pre-built instruction templates that structure interactions with LLMs.

**Protocol operations:**
| Method | Purpose | Returns |
|--------|---------|---------|
| `prompts/list` | Discover available prompts | Array of prompt descriptors |
| `prompts/get` | Retrieve prompt details | Full prompt definition with arguments |

**Example prompt:**
```json
{
  "name": "plan-vacation",
  "title": "Plan a vacation",
  "description": "Guide through vacation planning process",
  "arguments": [
    { "name": "destination", "type": "string", "required": true },
    { "name": "duration", "type": "number" },
    { "name": "budget", "type": "number" }
  ]
}
```

**User interaction model**: Prompts are **user-controlled** — they require explicit invocation (slash commands, command palettes, UI buttons).

### 1.5 Client Primitives (Server-Can-Ask-Client)

MCP also defines primitives that allow servers to request actions from the client:

#### Sampling
Allows servers to request LLM completions through the client. Enables agentic workflows without server-side AI SDK integration.

```json
{
  "method": "sampling/createMessage",
  "params": {
    "messages": [{ "role": "user", "content": "Analyze these flight options..." }],
    "modelPreferences": {
      "hints": [{ "name": "claude-sonnet-4-20250514" }],
      "costPriority": 0.3,
      "intelligencePriority": 0.9
    }
  }
}
```

**Security**: Human-in-the-loop — users review and approve both request and response.

#### Elicitation
Allows servers to request specific information from users during interactions.

```json
{
  "method": "elicitation/requestInput",
  "params": {
    "message": "Please confirm your booking details:",
    "schema": {
      "type": "object",
      "properties": {
        "confirmBooking": { "type": "boolean" },
        "seatPreference": { "type": "string", "enum": ["window", "aisle"] }
      },
      "required": ["confirmBooking"]
    }
  }
}
```

#### Roots
Allows clients to specify which directories servers should focus on (filesystem boundaries).

```json
{
  "uri": "file:///Users/agent/travel-planning",
  "name": "Travel Planning Workspace"
}
```

**Design philosophy**: Roots are advisory (servers "SHOULD" respect), not enforced. Actual security must be at OS level via file permissions/sandboxing.

### 1.6 Transport Mechanisms

#### Stdio Transport
- Client launches MCP server as subprocess
- Server reads from stdin, writes to stdout
- Stderr used for logging (not MCP messages)
- Messages delimited by newlines
- Best for: local servers, single-user scenarios

#### Streamable HTTP Transport
- Server as independent process handling multiple clients
- HTTP POST for client-to-server messages
- Optional SSE (Server-Sent Events) for server-to-client streaming
- Session management via `MCP-Session-Id` header
- Supports OAuth 2.1, bearer tokens, API keys
- Best for: remote servers, multi-user scenarios

**Security requirements for HTTP transport:**
1. **Origin header validation** — prevents DNS rebinding attacks
2. **Localhost binding** — servers should bind to `127.0.0.1`, not `0.0.0.0`
3. **Authentication** — required for all connections

### 1.7 Notifications (Real-time Updates)

MCP supports JSON-RPC notifications for dynamic updates:

```json
{ "jsonrpc": "2.0", "method": "notifications/tools/list_changed" }
```

When a server's available tools change (new functionality, modifications, removals), it sends a notification. Clients react by re-fetching the tool list.

**Key notifications:**
- `notifications/initialized` — client ready for operation
- `notifications/tools/list_changed` — tool list updated
- `notifications/resources/list_changed` — resource list updated
- `notifications/resources/updated` — specific resource changed (if subscribed)
- `notifications/cancelled` — request was cancelled

### 1.8 Tasks (Experimental)

Durable execution wrappers enabling deferred result retrieval and status tracking:
- `tasks/create` — start a task
- `tasks/get` — retrieve task status/result
- `tasks/cancel` — cancel running task
- `tasks/list` — list tasks
- `tasks/notify` — progress notifications

Useful for: expensive computations, workflow automation, batch processing, multi-step operations.

### 1.9 Security Model

**Authorization framework**: OAuth 2.1 based

**Trust boundaries:**
1. **Roots** (advisory): communicate filesystem boundaries, not enforced
2. **Elicitation**: servers request info, clients present UI, users approve
3. **Sampling**: servers request AI completions, users review both request and response
4. **Capability negotiation**: both parties declare what they support

**Server-side requirements:**
- Validate all tool inputs
- Implement proper access controls
- Rate limit tool invocations
- Sanitize tool outputs

**Client-side requirements:**
- Prompt for confirmation on sensitive operations
- Show tool inputs before calling server
- Validate tool results
- Implement timeouts
- Log usage for audit

**MCP Registry namespace authentication**: Uses reverse DNS format (`io.github.username/server`) tied to verified GitHub accounts, preventing namespace spoofing.

---

## 2. MCP Server Ecosystem

### 2.1 Official Reference Servers

The [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) repository contains reference implementations:

**Active servers (under `/src`):**
- **Everything** — Reference/test server demonstrating all primitives
- **Fetch** — Web content fetching optimized for LLMs
- **Filesystem** — Secure file operations with access controls
- **Git** — Repository reading, searching, manipulation
- **Memory** — Knowledge graph-based persistent storage
- **Sequential Thinking** — Problem-solving through thought sequences
- **Time** — Timezone conversion utilities

**Archived servers** (maintained separately):
- AWS KB Retrieval, Brave Search, EverArt, GitHub, GitLab, Google Drive, Google Maps, PostgreSQL, Puppeteer, Redis, Sentry, Slack, SQLite

### 2.2 MCP Registry Ecosystem

The [MCP Registry](https://github.com/modelcontextprotocol/registry) is the official centralized metadata repository for publicly accessible MCP servers.

**Ecosystem structure:**
```
Package Registries (npm, PyPI, Docker Hub) ← host code/binaries
                ↓
MCP Registry ← hosts metadata pointing to packages
                ↓
Aggregators (marketplaces) ← consume metadata, add curation
                ↓
Host Applications (Claude Code, Cursor) ← use aggregated data
```

**Key characteristics:**
- Server metadata in standardized `server.json` format
- Namespace management via DNS verification (GitHub, domain)
- REST API for client/aggregator discovery
- **Does NOT support private servers** — for private use, host your own registry

**Spam prevention:**
- Namespace authentication (GitHub/DNS/HTTP challenges)
- Character limits and validation
- Manual takedown by maintainers

### 2.3 Community MCP Servers

**smithery.ai** — MCP server marketplace (note: website encountered 403/blocking issues during research)

**turbomcp.ai** (redirect from mcp.run) — Enterprise MCP gateway with features:
- Standards-compliant, self-hosted MCP gateway
- OIDC-compatible IdP integration
- DLP features and AI kill-switch
- Audit logging
- RBAC system for server approvals
- OAuth & Dynamic Client Registration
- 1-click deactivation

### 2.4 SDK Ecosystem

Official MCP SDKs available for multiple languages:

| SDK | Language | Tier |
|-----|----------|------|
| TypeScript | TypeScript/JavaScript | Tier 1 |
| Python | Python | Tier 1 |
| C# | C#/.NET | Tier 1 |
| Go | Go | Tier 1 |
| Java | Java | Tier 2 |
| Rust | Rust | Tier 2 |
| Swift | Swift | Tier 3 |
| Ruby | Ruby | Tier 3 |
| PHP | PHP | Tier 3 |
| Kotlin | Kotlin | TBD |

**Tier definitions:**
- **Tier 1**: Full protocol support, actively maintained
- **Tier 2**: Feature complete, community managed
- **Tier 3**: Basic support, early stage

---

## 3. MCP Integration in AI Coding Tools

### 3.1 Claude Code

**Configuration**: MCP servers configured via `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "server-name": {
      "command": "python",
      "args": ["mcp-server.py"],
      "env": { "API_KEY": "${env:API_KEY}" }
    }
  }
}
```

**Support**: Full MCP support as an MCP host. Claude Code can connect to any MCP server and use its tools, resources, and prompts.

### 3.2 Cursor

**Configuration**: `mcp.json` files in:
- `.cursor/mcp.json` — project-level
- `~/.cursor/mcp.json` — global

**Example local stdio server:**
```json
{
  "mcpServers": {
    "server-name": {
      "command": "python",
      "args": ["mcp-server.py"],
      "env": { "API_KEY": "${env:API_KEY}" }
    }
  }
}
```

**Example remote server:**
```json
{
  "mcpServers": {
    "server-name": {
      "url": "http://localhost:3000/mcp",
      "headers": { "API_KEY": "value" }
    }
  }
}
```

**Supported features**: Tools, Prompts, Resources, Roots, Elicitation, MCP Apps (interactive UI)

**Transport methods**: stdio, SSE, Streamable HTTP

### 3.3 VS Code (Copilot)

**Configuration**: `mcp.json` in:
- `.vscode/mcp.json` — workspace (shareable via source control)
- User profile — via **MCP: Open User Configuration** command

**Adding servers:**
- Install from Extensions view with `@mcp` search
- MCP: Add Server from Command Palette
- Dev containers via `devcontainer.json`
- Command line: `code --add-mcp '{"name":"server-name","command":...}'`

**Security**: Trust confirmation on first use. Sandboxing available on macOS/Linux for stdio servers.

### 3.4 Goose (Block/Square)

**Key characteristic**: MCP-native design — primary extension mechanism is MCP servers, no proprietary plugin format.

Goose uses MCP as its **only** extension model, making it the most aligned with MCP-first architecture among mainstream AI coding tools.

### 3.5 OpenAI Codex CLI

**Key characteristic**: Codex CLI **exposes itself as an MCP server**, enabling multi-agent pipeline composition via the OpenAI Agents SDK.

This is a notable pattern: the agent itself becomes a server that other agents can orchestrate.

### 3.6 Gemini CLI (Google)

**MCP support**: Configured via `~/.gemini/settings.json`

Built-in features:
- Google Search grounding
- 1M token context window
- Plan Mode (read-only planning phase)
- ReAct loop

---

## 4. MCP vs Skills/Plugins Comparison

### 4.1 Conceptual Differences

| Aspect | MCP Tool | Skill |
|--------|----------|-------|
| **Definition** | Protocol-defined interface with JSON Schema | Markdown prompt file with metadata |
| **Discovery** | `tools/list` at runtime | Static registration in `settings.json` |
| **Invocation** | By name with typed arguments | Slash command or explicit call |
| **Composition** | Hierarchical (servers can call sampling) | Manual chaining via prompt design |
| **Transport** | stdio or HTTP (network-capable) | In-process via Claude Code |
| **Capability negotiation** | Protocol-level handshake | Implicit (skills always available) |
| **Version negotiation** | Built-in (`protocolVersion`) | N/A |
| **Real-time updates** | `listChanged` notifications | None |

### 4.2 Current Clade Skills Format

Clade skills consist of two files:

**SKILL.md** (metadata):
```markdown
---
name: commit
description: Analyze uncommitted changes, split into logical commits...
when_to_use: "commit, push, ship code..."
argument-hint: '[--no-push] [--dry-run]'
user_invocable: true
---
```

**prompt.md** (instructions):
```
You are the Commit skill. You analyze all uncommitted changes...
[detailed implementation]
```

### 4.3 What MCP Does NOT Cover (That Skills Need)

1. **Conversational flow management**: MCP tools are stateless function calls. Skills in Clade include multi-step workflows with conditional logic, loops, and human-in-the-loop checkpoints.

2. **Slash command binding**: MCP has no concept of `/skill-name` invocation. This is host-application specific.

3. **Context injection**: Skills receive Claude Code's current context (working directory, git status, etc.). MCP tools receive only their defined arguments.

4. **Session state**: Skills can maintain state across multiple invocations within a session. MCP tools are stateless.

5. **Skill composition**: Clade's loop skill orchestrates other skills. MCP has no native concept of skill-to-skill delegation.

6. **Metadata beyond schema**: Skills have `when_to_use` hints, `user_invocable` flags, and conversational instructions that go beyond input/output schemas.

### 4.4 What Skills Could Learn from MCP

1. **Runtime discovery**: Skills should advertise themselves via `tools/list` instead of static registration
2. **Capability negotiation**: Version-aware handshake before tool invocation
3. **Structured metadata**: JSON Schema for arguments instead of plain text `argument-hint`
4. **Change notifications**: When skills are added/removed/modified, hosts should be notified
5. **Remote execution**: MCP's HTTP transport enables skills to run on remote servers

---

## 5. MCP for Clade Skills Auto-Discovery

### 5.1 Current State

Clade skills are manually registered:
1. Skill files placed in `configs/skills/<name>/`
2. `install.sh` copies skills to `~/.claude/skills/`
3. Claude Code reads skills from that directory
4. No automatic discovery — new skills require reinstallation

### 5.2 MCP-Based Discovery Architecture

**Option A: Clade as MCP Host**
```
Clade (orchestrator) ← MCP clients → External MCP servers
                                       ├── GitHub MCP
                                       ├── Filesystem MCP
                                       └── Custom tool MCPs
```

**Option B: Clade Skills as MCP Servers**
```
Claude Code ← MCP client → Clade Skills MCP Server
                              ├── /skills/commit/tools
                              ├── /skills/review/tools
                              └── /skills/investigate/tools
```

**Option C: Hybrid (Recommended)**
```
Clade (orchestrator) ← MCP clients → External MCP servers
         ↑
    Skills as MCP servers
         ↑
Claude Code ← MCP client → Clade Skills Server (local stdio)
```

### 5.3 Implementation Sketch

**Skills MCP Server** (`skills_server.py`):

```python
from mcp.server import Server
from mcp.types import Tool

server = Server("clade-skills")

@server.list_tools()
async def list_tools():
    """Discover available Clade skills"""
    skills = load_skill_metadata()  # Read all SKILL.md files
    return [
        Tool(
            name=f"skill_{skill['name']}",
            description=skill['description'],
            inputSchema={
                "type": "object",
                "properties": {
                    "argument": {"type": "string"}
                }
            }
        )
        for skill in skills
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Execute a skill by invoking Claude Code with its prompt.md"""
    skill_name = name.replace("skill_", "")
    prompt = load_skill_prompt(skill_name)
    result = await execute_skill_prompt(prompt, arguments.get("argument"))
    return [TextContent(text=result)]
```

**Key benefits:**
1. Skills auto-discoverable via `tools/list`
2. Skill updates broadcast via `tools/list_changed` notifications
3. Skills can be remote (HTTP transport)
4. Argument validation via JSON Schema
5. Consistent with MCP ecosystem

### 5.4 Skill Metadata Mapping

Current Clade skill metadata:
```yaml
name: commit
description: Analyze uncommitted changes, split into logical commits...
when_to_use: "commit, push, ship code, 提交, 推送..."
argument-hint: '[--no-push] [--dry-run]'
user_invocable: true
```

MCP tool equivalent:
```json
{
  "name": "skill_commit",
  "title": "Commit",
  "description": "Analyze uncommitted changes, split into logical commits...",
  "inputSchema": {
    "type": "object",
    "properties": {
      "argument": {
        "type": "string",
        "description": "--no-push, --dry-run, or empty for default"
      }
    }
  },
  "annotations": {
    "when_to_use": "commit, push, ship code, 提交, 推送...",
    "user_invocable": true
  }
}
```

**Gap**: MCP's `annotations` field is for protocol hints (audience, priority), not custom skill metadata. Need extension or conventions.

### 5.5 Real-time Skill Updates

Current: Skills updated only on reinstallation

With MCP notifications:
```python
@server.on_skill_updated()
async def on_skill_updated(skill_name: str):
    await server.send_notification("notifications/tools/list_changed")
```

Or when skills directory changes:
```python
# Watch config/skills/ for changes
# On change: re-read SKILL.md files, send tools/list_changed
```

### 5.6 MCP Protocol Compliance for Skills

To make Clade skills fully MCP-compliant:

1. **Tool naming**: `skill_<name>` prefix to avoid collision with external MCP tools
2. **JSON Schema args**: Parse `argument-hint` into proper schema
3. **Content types**: Return `TextContent` or `ImageContent` as appropriate
4. **Error handling**: Return `isError: true` for tool execution failures
5. **Progress tracking**: Support `progress` notifications for long-running skills

---

## 6. Key Findings for Clade Redesign

### 6.1 Protocol Alignment

- **MCP is the right foundation**: The ecosystem has converged on MCP (Anthropic, Google, Microsoft, OpenAI all support it)
- **Skills map to MCP tools**: Natural 1:1 mapping with minor metadata extensions
- **Discovery mechanism is superior**: Runtime vs static registration enables dynamic skill loading

### 6.2 Practical Considerations

- **Don't abandon the prompt layer**: MCP defines interfaces, not implementation. Skills' markdown prompts are still the right abstraction for complex workflows.
- **Keep slash commands**: MCP has no equivalent to `/skill-name` — this is Claude Code-specific and should be preserved
- **Composition requires orchestration**: MCP's sampling lets servers call back to the LLM, but skill chaining (e.g., `/loop` calling `/commit`) needs Clade's own supervisor logic.

### 6.3 Recommended Approach

1. **Phase 1**: Implement a Clade Skills MCP server that exposes existing skills as MCP tools
   - Skills remain in `configs/skills/<name>/SKILL.md` + `prompt.md`
   - MCP server reads metadata and advertises via `tools/list`
   - Claude Code connects via stdio transport

2. **Phase 2**: Add skill discovery from MCP Registry
   - Query Registry API for skills matching criteria
   - Auto-install skills from trusted namespaces

3. **Phase 3**: Support external MCP servers in Clade orchestrator
   - Add MCP client to orchestrator layer
   - External tools (GitHub, filesystem) become orchestrator capabilities

---

## 7. References

### Official Documentation
- [MCP Specification](https://modelcontextprotocol.io/specification)
- [MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP Servers](https://modelcontextprotocol.io/servers)
- [MCP Registry](https://modelcontextprotocol.io/registry)
- [MCP SDKs](https://modelcontextprotocol.io/docs/sdk)

### Protocol Schemas
- [schema.ts (2025-11-25)](https://github.com/modelcontextprotocol/specification/blob/main/schema/2025-11-25/schema.ts)
- [Full specification](https://github.com/modelcontextprotocol/specification)

### Reference Implementations
- [Official MCP Servers](https://github.com/modelcontextprotocol/servers)
- [TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [Python SDK](https://github.com/modelcontextprotocol/python-sdk)

### Tool Integrations
- [Claude Code MCP](https://claude.ai/docs/claude-code/mcp)
- [Cursor MCP](https://cursor.com/docs/context/mcp)
- [VS Code MCP](https://code.visualstudio.com/docs/copilot/chat/mcp-servers)
- [Goose MCP](https://docs.goose.dev/docs/mcp)
- [Gemini CLI MCP](https://github.com/google-gemini/gemini-cli)

### Ecosystem
- [MCP Registry GitHub](https://github.com/modelcontextprotocol/registry)
- [smithery.ai](https://smithery.ai)
- [turbomcp.ai](https://turbomcp.ai)

---

## Appendix: MCP Protocol Version History

| Version | Date | Key Changes |
|---------|------|-------------|
| 2024-11-05 | Nov 2024 | Initial release, HTTP+SSE transport |
| 2025-03-26 | Mar 2025 | Streamable HTTP replaces HTTP+SSE |
| 2025-06-18 | Jun 2025 | Experimental tasks support |
| 2025-11-25 | Nov 2025 | Current latest, full feature set |

Protocol follows date-based versioning (YYYY-MM-DD).
