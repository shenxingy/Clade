# Skills/Plugins Auto-Discovery: Cross-Tool Analysis

---
name: 2026-03-31-skills-auto-discovery.md
date: 2026-03-31
status: integrated
review_date: 2026-03-31
summary:
  - "Cross-tool auto-discovery: convention-based, protocol-based, config-driven, manifest-based"
integrated_items:
  - "Convention-based skill discovery — install.sh copies skills to ~/.claude/skills/"
  - "Skill description injection — session-context.sh scans ~/.claude/skills/*/SKILL.md and injects descriptions into system prompt"
  - "available_skills.md generation — install.sh generates listing of all skills with name/description/invocation"
  - "Goal file dependencies — resolve-goal-deps.py resolves includes recursively, loop/prompt.md pre-processes goal files before use"
  - "Template substitution {{}} syntax — resolve-goal-deps.py supports {{variable}} substitution from values: dict per include"
needs_work_items: []
reference_items:
  - "MCP tool registration at runtime — not needed for Clade (workers are Python-defined)"
  - "Composio plugin slot architecture — overkill for Clade scope"
---

**Date**: 2026-03-31
**Purpose**: Research how AI coding tools discover and register capabilities without manual configuration
**Sources**: Composio agent-orchestrator source, Goose source, MCP SDK source, Cursor research, Claude Code skills system

---

## Executive Summary

Auto-discovery mechanisms fall into four architectural patterns:

| Pattern | Mechanism | Examples |
|---------|-----------|----------|
| **Convention-based** | Directory scan for known filenames | Claude Code (`SKILL.md`), Cursor (`.cursor/agents/*.md`) |
| **Protocol-based** | Standard RPC handshake | MCP (`tools/list`, `prompts/list`) |
| **Config-driven** | Explicit registration in config file | Composio, Goose |
| **Manifest-based** | Package exports a manifest object | Composio `PluginModule.manifest` |

Most tools combine multiple patterns. The industry trend is toward **protocol-based discovery** (MCP) as the universal standard, with **manifest-based** registration for richer metadata.

---

## 1. Claude Code Built-in Skills

### Discovery Mechanism: Convention over Configuration

Claude Code discovers skills through **directory convention**. Skills live in `~/.claude/skills/<skill-name>/` and must contain a `SKILL.md` file.

```
~/.claude/skills/
├── loop/
│   ├── SKILL.md       ← required manifest
│   └── prompt.md      ← optional additional content
├── commit/
│   └── SKILL.md
└── batch-tasks/
    └── SKILL.md
```

### SKILL.md Format

```yaml
---
name: loop
description: Goal-driven autonomous improvement loop using Blueprint architecture
when_to_use: "run loop, autonomous loop, keep fixing until done"
argument-hint: 'GOAL_FILE [--model haiku|sonnet|opus] [--max-iter N]'
user_invocable: true
---

# Skill content (Markdown)
```

Frontmatter fields:
- `name`: Skill identifier (matches directory name)
- `description`: Human-readable description shown in `/skill` list
- `when_to_use`: Trigger phrases that invoke this skill
- `argument-hint`: Usage syntax for the skill
- `user_invocable`: Whether users can invoke directly via slash command

### Discovery Process

1. At session start, Claude Code scans `~/.claude/skills/` directories
2. Each directory with `SKILL.md` is registered as a skill
3. Skills are indexed by `name` and `when_to_use` patterns
4. When user types `/<skill>` or matching phrase, skill content is injected into context

### Installation: Manual Copy (Not Auto-Discovery)

Claude Code does NOT auto-discover skills from arbitrary directories. Installation requires explicit copy via `install.sh`:

```bash
# From install.sh
for skill_dir in "$SCRIPT_DIR/configs/skills/"/*/; do
  skill_name=$(basename "$skill_dir")
  mkdir -p "$CLAUDE_DIR/skills/$skill_name"
  cp "$skill_dir"* "$CLAUDE_DIR/skills/$skill_name/"
done
```

**Key limitation**: No runtime discovery of new skills. Adding a skill requires file system installation.

### Tool/Ability Advertisement

Claude Code skills do NOT advertise specific tools. The skill content is injected as text into the LLM context. The LLM decides which tools to use based on the skill description alone.

---

## 2. Cursor Skills System

### Discovery Mechanism: Directory Convention + File Naming

Cursor 2.4 introduced Skills via two mechanisms:

1. **Built-in Skills**: Ship with Cursor installation, no discovery needed
2. **Custom Skills**: `.cursor/agents/<name>.md` or `.cursor/agents/<name>/SKILL.md`

### Custom Skill Format

```markdown
# Skill Name

## Description
What this skill does.

## Triggers
- /skill-name
- when user says this

## Instructions
Detailed instructions for the agent...
```

### Auto-Discovery Process

1. Cursor scans for `.cursor/agents/` directories in the project
2. Any `*.md` or `SKILL.md` file is treated as a skill
3. Skills are indexed by name and trigger patterns
4. Agent dynamically loads skill content when triggered

**Key difference from Claude Code**: Cursor supports per-project skills via `.cursor/agents/` in the project directory. Claude Code only supports user-global skills in `~/.claude/skills/`.

### Skill Dependencies

Cursor skills do not have an explicit dependency system. Skills can reference other skills by calling them, but there is no structured dependency graph.

---

## 3. Composio agent-orchestrator: Plugin System

**Source**: `packages/core/src/plugin-registry.ts` + `packages/core/src/types.ts`

### Architecture: 7 Plugin Slots + Manifest Contract

Composio defines 7 pluggable slots:

```
Runtime    → tmux, process, docker, k8s, ssh, e2b
Agent      → claude-code, codex, aider, opencode
Workspace  → worktree, clone
Tracker    → github, linear, gitlab
SCM        → github, gitlab
Notifier   → desktop, slack, discord, webhook, openclaw, composio
Terminal   → iterm2, web
```

### Plugin Contract

```typescript
// packages/core/src/types.ts

interface PluginManifest {
  name: string;           // e.g. "tmux", "claude-code"
  slot: PluginSlot;       // which slot this fills
  description: string;
  version: string;
  displayName?: string;   // e.g. "Claude Code"
}

interface PluginModule<T = unknown> {
  manifest: PluginManifest;
  create(config?: Record<string, unknown>): T;
  detect?(): boolean;     // optional: is binary available?
}
```

### Discovery Mechanism: Three Sources

```typescript
// packages/core/src/plugin-registry.ts

// 1. Built-in plugins (hardcoded list)
const BUILTIN_PLUGINS = [
  { slot: "runtime", name: "tmux", pkg: "@composio/ao-plugin-runtime-tmux" },
  { slot: "agent", name: "claude-code", pkg: "@composio/ao-plugin-agent-claude-code" },
  // ...
];

// 2. npm packages with @composio/ao-plugin-* prefix
// 3. Local file paths specified in config
```

### Plugin Loading Process

```typescript
async loadFromConfig(config: OrchestratorConfig): Promise<void> {
  // Step 1: Load built-ins
  await this.loadBuiltins(config);

  // Step 2: Load user-configured plugins
  for (const plugin of config.plugins ?? []) {
    const specifier = resolvePluginSpecifier(plugin); // local path or npm pkg
    const mod = await import(specifier);
    this.register(mod); // calls plugin.create(config)
  }
}
```

### Plugin Registration

```typescript
register(plugin: PluginModule, config?: Record<string, unknown>): void {
  const { manifest } = plugin;
  const key = makeKey(manifest.slot, manifest.name); // e.g. "agent:claude-code"
  const instance = plugin.create(config);
  plugins.set(key, { manifest, instance });
}
```

### Local Plugin Resolution

```typescript
// packages/core/src/plugin-registry.ts

function resolveLocalPluginEntrypoint(pluginPath: string): string | null {
  // 1. If it's a file, use it directly
  // 2. If it's a directory, look for:
  //    a) package.json "exports" field
  //    b) package.json "module" field
  //    c) package.json "main" field
  //    d) dist/index.js
  //    e) index.js
}
```

### Tool/Ability Advertisement

Plugins do NOT advertise individual tools. Each plugin implements a **slot interface** (e.g., `Agent`, `Runtime`, `Workspace`) with fixed methods. The orchestrator knows what methods exist because it knows the slot interface, not because the plugin advertises capabilities.

Example: The `Agent` slot interface:
```typescript
interface Agent {
  name: string;
  getLaunchCommand(config: AgentLaunchConfig): string;
  getEnvironment(config: AgentLaunchConfig): Record<string, string>;
  getActivityState(session: Session): Promise<ActivityDetection | null>;
  // ...
}
```

**Limitation**: No dynamic tool discovery within a slot. Adding a new tool requires a new slot or plugin.

---

## 4. Goose Extension System

**Source**: Research from `crates/goose/src/agents/extension.rs` (from Goose research doc)

### Philosophy: MCP as the Universal Extension Format

Goose's core thesis: **extensions = MCP servers**. Every extension, regardless of transport, speaks MCP. There is no proprietary plugin format.

### Five Extension Transport Types

```rust
// crates/goose/src/agents/extension.rs

pub enum ExtensionConfig {
    Stdio {
        name: String,
        cmd: String,
        args: Vec<String>,
        envs: HashMap<String, String>,
        env_keys: Vec<String>,
        timeout: u64,
    },

    StreamableHttp {
        name: String,
        uri: String,
        envs: HashMap<String, String>,
        headers: HashMap<String, String>,
        timeout: u64,
    },

    Platform {
        name: String,
        display_name: String,
        // In-process Rust implementation
    },

    Builtin {
        name: String,
        display_name: String,
        timeout: u64,
        // Embedded binary shipped with goose
    },

    InlinePython {
        name: String,
        code: String,
        dependencies: Vec<String>,
        timeout: u64,
    },
}
```

### Discovery Mechanism: Static Config + Runtime Management

**Static (config.yaml)**:
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

**Dynamic (runtime)**: The `manage_extensions` platform tool allows the LLM to enable/disable extensions during a session.

### Extension Loading

```rust
ExtensionManager::add_extension(config)
  → resolve env vars (config + keyring)
  → malware check (deny_if_malicious_cmd_args)
  → spawn child process (Command::new(cmd))  // for Stdio
  → wrap in GooseMcpClient (implements McpClientTrait)
  → store in extensions: HashMap<String, Extension>
```

### Tool Namespacing

External MCP tools are **prefixed** with the extension name:
- Extension `github` tool `create_pr` → exposed as `github__create_pr`

Platform extensions with `unprefixed_tools: true` are exposed without prefix.

### Platform Extensions (Built-in)

These are in-process Rust implementations:

| Name | Description |
|------|-------------|
| `developer` | File ops (write/edit/read), shell, tree |
| `analyze` | Code structure analysis via tree-sitter |
| `todo` | In-session task tracking |
| `apps` | HTML/CSS/JS app creation |
| `chatrecall` | Search past conversations |
| `ext_manager` | Enable/disable/discover extensions at runtime |
| `orchestrator` | Multi-agent session management |
| `summon` | load/delegate tools |

### Tool/Ability Advertisement

Goose extensions advertise tools via **MCP protocol**. When `list_tools` is called, the MCP server returns all registered tools with their JSON Schema input/output schemas.

---

## 5. MCP Protocol Discovery Mechanism

**Source**: `packages/core/src/types/schemas.ts`, `packages/server/src/server/mcp.ts`

### Protocol Discovery Flow

```
Client                              Server
  │                                    │
  │──── initialize() ─────────────────►│
  │     { capabilities: { tools: {} } } │
  │                                    │
  │◄─── result ────────────────────────│
  │     { capabilities: {              │
  │         tools: { listChanged: true } │
  │       }                            │
  │     }                              │
  │                                    │
  │──── tools/list() ─────────────────►│
  │                                    │
  │◄─── { tools: [                    ││
  │        { name, description,        ││
  │          inputSchema }             ││
  │      ] }                          │
```

### Server Capabilities Advertisement

```typescript
// packages/core/src/types/spec.types.ts

export interface ServerCapabilities {
  tools?: {
    listChanged?: boolean;  // notifications/tools/list_changed supported
  };
  prompts?: {
    listChanged?: boolean;
  };
  resources?: {
    subscription?: boolean;
    listChanged?: boolean;
  };
}
```

### Tool Registration + Discovery

```typescript
// packages/server/src/server/mcp.ts

// Server registers a tool
server.registerTool(
  'calculate-bmi',
  {
    title: 'BMI Calculator',
    description: 'Calculate Body Mass Index',
    inputSchema: z.object({
      weightKg: z.number(),
      heightM: z.number()
    }),
  },
  async ({ weightKg, heightM }) => {
    return { content: [{ type: 'text', text: JSON.stringify({ bmi }) }] };
  }
);

// Server handles tools/list request
server.setRequestHandler(
  'tools/list',
  (): ListToolsResult => ({
    tools: Object.entries(this._registeredTools)
      .filter(([, tool]) => tool.enabled)
      .map(([name, tool]): Tool => ({
        name,
        title: tool.title,
        description: tool.description,
        inputSchema: tool.inputSchema,
      }))
  })
);
```

### Dynamic Discovery

MCP supports **runtime registration**. Tools can be added/removed after the server starts:

```typescript
// Adding a tool at runtime
server.registerTool('new-tool', config, handler);

// Notifying clients of changes
server.notification({ method: 'notifications/tools/list_changed' });
```

### Prompts and Resources Discovery

Same pattern as tools:

```typescript
// Prompts
server.registerPrompt('review-code', config, handler);
server.setRequestHandler('prompts/list', () => ({ prompts: [...] }));

// Resources
server.registerResource('file://...', config, handler);
server.setRequestHandler('resources/list', () => ({ resources: [...] }));
```

---

## 6. AGENTS.md: Cross-Tool Project Context Standard

### What It Is

AGENTS.md is an **open standard** for project context files, honored by Goose, Codex, and potentially other frameworks. It is NOT a plugin system but a convention for providing project-specific instructions to agents.

### Format

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

### Discovery

1. Agent enters a directory
2. Looks for `AGENTS.md` or `.goosehints` in current and parent directories
3. Loads content into system prompt

### Subdirectory Loading (Goose-specific)

```rust
// crates/goose/src/hints/load_hints.rs

// SubdirectoryHintTracker watches tool call arguments
// When a tool uses a path argument, the parent directory is queued
// On next turn, hints from that directory are injected
impl SubdirectoryHintTracker {
    fn record_tool_arguments(&mut self, arguments, working_dir);
    fn load_new_hints(&mut self, working_dir) -> Vec<(String, String)>;
}
```

### Comparison: AGENTS.md vs CLAUDE.md

| Aspect | AGENTS.md | CLAUDE.md |
|--------|-----------|-----------|
| Scope | Universal — honored by multiple agents | Claude Code-specific |
| Location | Project root and subdirectories | Project root or `~/.claude/` |
| Auto-discovery | Yes — loaded when agent enters any dir | Yes — loaded at session start |
| Subdirectory hints | Yes — loaded when agent navigates | No |
| Format | Free-form Markdown | Free-form Markdown |
| Naming convention | Convention, not enforced | Enforced by Claude Code |

---

## 7. Cross-Tool Comparison

### Discovery Pattern Summary

| Tool | Pattern | Dynamic? | Dependencies | Tool Discovery |
|------|---------|----------|--------------|---------------|
| Claude Code | Convention (directory scan) | No | No | No |
| Cursor | Convention (`.cursor/agents/`) | No | No | No |
| Composio | Config + manifest | No | No (slot interface) | No |
| Goose | Config + MCP protocol | Yes (runtime mgmt) | No | Yes (via MCP) |
| MCP | Protocol handshake | Yes | No | Yes (tools/list) |

### Plugin/Skill Dependency Support

| Tool | Dependency System |
|------|-------------------|
| Claude Code | None — flat list |
| Cursor | None — skills can call other skills but no structured deps |
| Composio | None — plugins have no dependency declaration |
| Goose | Sub-recipes can depend on other recipes (via `{{}}` template) |
| MCP | None — servers don't declare dependencies |

### Indexing/Categorization

| Tool | How Categorized |
|------|-----------------|
| Claude Code | By `name` + `when_to_use` patterns |
| Cursor | By filename + trigger phrases |
| Composio | By slot (`runtime`, `agent`, `workspace`, etc.) |
| Goose | By extension name + MCP tool namespace |
| MCP | No categorization — flat list of tools/prompts/resources |

---

## 8. Architecture Patterns for Clade

### Pattern 1: Convention + Manifest Hybrid

Combine directory scanning with a manifest file:

```
configs/skills/
├── loop/
│   ├── SKILL.md        ← manifest (name, description, triggers)
│   ├── prompt.md       ← skill content
│   └── dependencies/   ← optional sub-skills
└── commit/
    └── SKILL.md
```

**Discovery**: Scan `configs/skills/*/SKILL.md` at startup or on `install.sh` run.

### Pattern 2: MCP as Tool Discovery Protocol

If Clade workers need to expose tools:

1. Implement MCP server interface for each worker
2. Workers advertise capabilities via `tools/list` response
3. Supervisor discovers worker tools dynamically via MCP

**Complexity**: High. MCP requires significant implementation.

### Pattern 3: Config-Driven Registration with Slot Interface

Composio-style: Fixed slot interfaces, config-driven loading:

```typescript
interface SkillModule {
  manifest: { name: string; description: string; version: string };
  create(config?: Record<string, unknown>): Skill;
}

interface Skill {
  getInstructions(context: TaskContext): string;
  canHandle(task: Task): boolean;
  execute(task: Task): Promise<TaskResult>;
}
```

### Pattern 4: Recipe Dependencies (Goose-style)

Goose recipes can reference sub-recipes:

```yaml
# Parent recipe
sub_recipes:
  - name: analysis_step
    path: ./analyze.yaml
    values:
      target: "{{ input_file }}"
```

Clade goal files could reference other goal files or skill files.

### Recommended Hybrid Approach for Clade

**For Skills** (static, installed via `install.sh`):
- Convention-based: scan `configs/skills/*/SKILL.md`
- Manifest in frontmatter: name, description, triggers
- No dynamic discovery — require explicit install

**For Worker Tools** (dynamic, runtime):
- MCP protocol adoption OR simplified JSON-RPC over stdin
- Worker registers tools at startup with name + description + input schema
- Supervisor discovers available tools via `list_tools` RPC

**For Goal Dependencies**:
- Allow goal files to reference other goal files or skill files
- Template substitution with `{{}}` syntax (Goose-style)

---

## 9. Key Implementation Insights

### Composio Plugin Registry (plugin-registry.ts)

Key code patterns:

```typescript
// Manifest validation
export function isPluginModule(value: unknown): value is PluginModule {
  return Boolean(candidate.manifest && typeof candidate.create === "function");
}

// Normalize ESM default export
export function normalizeImportedPluginModule(value: unknown): PluginModule | null {
  if (isPluginModule(value)) return value;
  if (value && typeof value === "object" && "default" in value) {
    const defaultExport = (value as { default?: unknown }).default;
    if (isPluginModule(defaultExport)) return defaultExport;
  }
  return null;
}

// Local plugin entrypoint resolution
export function resolveLocalPluginEntrypoint(pluginPath: string): string | null {
  // 1. If file, return path
  // 2. If directory, check package.json exports/module/main
  // 3. Fallback to dist/index.js or index.js
}
```

### MCP Server Tool Registration

```typescript
// packages/server/src/server/mcp.ts

private setToolRequestHandlers(): void {
  this.server.registerCapabilities({
    tools: { listChanged: true }
  });

  this.server.setRequestHandler(
    'tools/list',
    (): ListToolsResult => ({
      tools: Object.entries(this._registeredTools)
        .filter(([, tool]) => tool.enabled)
        .map(([name, tool]): Tool => ({
          name,
          title: tool.title,
          description: tool.description,
          inputSchema: tool.inputSchema,
        }))
    })
  );
}
```

### Composio Agent Plugin Export

```typescript
// packages/plugins/agent-claude-code/src/index.ts

export const manifest = {
  name: "claude-code",
  slot: "agent" as const,
  description: "Agent plugin: Claude Code CLI",
  version: "0.1.0",
  displayName: "Claude Code",
};

export function create(): Agent {
  return createClaudeCodeAgent();
}

export function detect(): boolean {
  try {
    execFileSync("claude", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

export default { manifest, create, detect } satisfies PluginModule<Agent>;
```

---

## 10. Sources

- [Composio agent-orchestrator](https://github.com/ComposioHQ/agent-orchestrator) — `packages/core/src/plugin-registry.ts`, `packages/core/src/types.ts`, `packages/plugins/agent-claude-code/src/index.ts`
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk) — `packages/core/src/types/spec.types.ts`, `packages/server/src/server/mcp.ts`
- [Goose (block/goose)](https://github.com/block/goose) — `crates/goose/src/agents/extension.rs` (from research doc)
- [Cursor 2.0 & Devin 2.0 Research](./2026-03-30-cursor-devin-research.md)
- [Goose Research](./2026-03-30-goose-research.md)
- [Composio Orchestrator Research](./2026-03-30-composio-orchestrator-research.md)
