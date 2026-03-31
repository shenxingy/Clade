---
name: 2026-03-30-openai-codex-agents-sdk-research.md
date: 2026-03-30
status: needs_work
review_date: 2026-03-31
summary:
  - "Codex CLI: Rust rewrite, sandboxing (Landlock/seccomp), MCP server, Agents SDK with handoff pattern"
integrated_items:
  - "MCP server — orchestrator/mcp_server.py exposes skills as MCP tools via @list_tools + @call_tool decorators"
needs_work_items:
  - "Typed worker handoffs with input_filter — Agents SDK HandoffInputData enables workers to hand off directly to specialized workers. Clade /handoff is session-level, not task-routing level (no structured context passing between workers)"
  - "Tracing span hierarchy — Clade has no structured tracing. Agents SDK span-per-task + nested llm_call_span + tool_call_span would improve observability"
  - "Guardrails (pre/post task validation) — Clade has no input validation before worker dispatch. Pre-task guardrail (is task well-formed?) and post-task guardrail (did worker address the goal?) not implemented"
  - "MultiProvider per-task routing — Clade /provider is hot-swap (whole session). Prefix-based per-task routing (e.g., haiku for TLDR, sonnet for implement) not implemented"
reference_items:
  - "Sandbox Policy DSL — not applicable (Claude Code has built-in safety boundaries)"
  - "Codex skills discovery mechanism — different from Clade's skill system"
---

# OpenAI Codex CLI + Agents SDK — Deep Research

**Date**: 2026-03-30
**Repos**:
- Codex CLI: https://github.com/openai/codex
- Agents SDK: https://github.com/openai/openai-agents-python
- Agents Docs: https://openai.github.io/openai-agents-python/

---

## Part 1: Codex CLI (Rust)

### 1.1 Why Rust?

Codex CLI was rewritten from TypeScript to Rust and is now the **only maintained implementation**. The stated rationale:

- **Zero-dependency install** — a single native binary, no Node.js runtime required.
- **Native sandboxing** — direct access to OS-level primitives: macOS `sandbox-exec` (Seatbelt), Linux Landlock + seccomp + bubblewrap. These are kernel APIs that require a systems language.
- **Performance + TUI** — the Ratatui-based fullscreen TUI requires tight control over I/O, terminal state, and async scheduling (Tokio).
- **Workspace architecture** — a Cargo workspace lets them split into many focused crates while sharing types via the `codex-protocol` crate.

### 1.2 Rust Module Graph

The `codex-rs/` root is a Cargo workspace with ~40+ crates. Key structural layers:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Entry Points (binaries)                                                      │
│  cli/         — `codex` multitool subcommand dispatcher                      │
│  tui/         — fullscreen TUI via Ratatui                                   │
│  exec/        — headless non-interactive `codex exec PROMPT`                 │
│  mcp-server/  — `codex mcp-server` (exposes Codex as MCP tool)               │
│  cloud-tasks/ — `codex cloud` (cloud sandbox task submission)                │
└─────────────────────────┬────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────────────────┐
│  core/  — Business logic library (the heart of Codex)                        │
│    codex/          — main Codex struct, turn orchestration, session state     │
│    exec_policy.rs  — approval decision engine (AskForApproval policy eval)   │
│    sandboxing/     — adapter: translates policy → platform sandbox call       │
│    seatbelt.rs     — macOS: spawns under sandbox-exec                        │
│    landlock.rs     — Linux: spawns under codex-linux-sandbox                 │
│    windows_sandbox.rs — Windows restricted token / AppContainer              │
│    agent/          — agent turn loop, context management                     │
│    mcp/            — MCP client (connects to external MCP servers)           │
│    memories/       — persistent memory subsystem                             │
│    skills.rs       — skill discovery and loading                             │
│    compact.rs      — context compaction (conversation truncation)            │
│    context_manager/ — context window management                              │
│    exec.rs         — process spawning + output capture                       │
│    safety.rs       — command safety heuristics                               │
└─────────────────────────┬────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────────────────┐
│  Protocol / Shared Types                                                     │
│  protocol/        — AskForApproval, SandboxPolicy, Op/EventMsg enums         │
│  execpolicy/      — policy rule engine (allowlist/denylist DSL)              │
│  sandboxing/      — platform-agnostic sandbox command builder                │
│  config/          — config.toml schema + defaults                            │
└─────────────────────────┬────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────────────────┐
│  Platform Executables                                                         │
│  linux-sandbox/   — codex-linux-sandbox binary (bubblewrap + seccomp)        │
│  windows-sandbox-rs/ — Windows AppContainer launcher                         │
└──────────────────────────────────────────────────────────────────────────────┘

Supporting crates:
  connectors/       — OpenAI API client abstraction
  app-server/       — local HTTP server for app-mode (IDE extensions)
  app-server-protocol/ — JSON protocol between CLI and app server
  otel/             — OpenTelemetry integration
  git-utils/        — git branch/diff helpers
  hooks/            — hook runtime (pre/post turn callbacks)
  skills/           — skill loading from ~/.codex/skills/
  state/            — SQLite-backed session state (rollout persistence)
  rollout/          — conversation rollout serialization/deserialization
  cloud-tasks-client/ — HTTP client for cloud sandbox backend
  network-proxy/    — network proxy (for managed network mode)
```

### 1.3 Codex as MCP Server

**Command**: `codex mcp-server`

The `mcp-server/` crate exposes Codex as an MCP tool that other agents can call. The architecture:

**Transport**: JSON-RPC over stdin/stdout (standard MCP transport). Reads newline-delimited JSON from stdin, writes responses to stdout. Uses Tokio channels internally (bounded capacity 128).

**Tool Definition** (`CodexToolCallParam`):
```rust
// mcp-server/src/codex_tool_config.rs
pub struct CodexToolCallParam {
    pub prompt: String,           // the task prompt
    pub model: Option<String>,    // override model (e.g. "gpt-5.2")
    pub profile: Option<String>,  // config.toml profile
    pub cwd: Option<String>,      // working directory
    pub approval_policy: Option<CodexToolCallApprovalPolicy>,  // untrusted|on-failure|on-request|never
    pub sandbox: Option<CodexToolCallSandboxMode>,              // read-only|workspace-write|danger-full-access
    pub config: Option<HashMap<String, serde_json::Value>>,    // arbitrary TOML overrides
    pub base_instructions: Option<String>,
    pub developer_instructions: Option<String>,
    pub compact_prompt: Option<String>,
}
```

**Reply mechanism** (`CodexToolCallReplyParam`): The caller can send follow-up messages mid-task (e.g., approval decisions for exec requests) via a separate `codex_tool_call_reply` tool call.

**Approval elicitation**: When Codex needs user approval (shell command, patch), it sends an MCP `elicit` request back to the calling agent — effectively inverting control. The calling agent must respond with `ExecApprovalResponse` or `PatchApprovalResponse` before the tool call continues.

**Key modules**:
- `message_processor.rs` — routes incoming JSON-RPC to `CodexToolRunner`
- `codex_tool_runner.rs` — manages a Codex session per tool call, bridges MCP ↔ core
- `exec_approval.rs` — MCP-level approval elicitation for shell commands
- `patch_approval.rs` — MCP-level approval elicitation for file patches

**Testing**: Use `npx @modelcontextprotocol/inspector codex mcp-server`.

### 1.4 Sandbox Mechanism

Codex has three sandbox layers, each activated by the platform:

#### macOS — Seatbelt (`sandbox-exec`)
```rust
// core/src/seatbelt.rs
pub async fn spawn_command_under_seatbelt(
    command, cwd, sandbox_policy, sandbox_policy_cwd,
    stdio_policy, network, env
) -> Child {
    // Calls create_seatbelt_command_args_for_policies() from codex-sandboxing
    // which generates the Apple Seatbelt (.sb) profile text inline
    // Then: /usr/bin/sandbox-exec -p <policy_text> <command>
}
```

The `.sb` profile is generated at runtime based on `FileSystemSandboxPolicy` (which paths are writable) and `NetworkSandboxPolicy` (whether network is allowed). The `CODEX_SANDBOX_ENV_VAR` env var is set so nested processes know they are sandboxed.

#### Linux — Bubblewrap + Seccomp
```
// linux-sandbox/src/
//   bwrap.rs        — calls bwrap with --bind/--ro-bind/--dev-bind mounts
//   landlock.rs     — Landlock LSM (in-kernel path restriction, kernel 5.13+)
//   launcher.rs     — orchestrates bwrap + seccomp setup
```

The `codex-linux-sandbox` helper binary applies **two layers**:
1. **In-process**: `no_new_privs` syscall + seccomp BPF filter (blocks privileged syscalls)
2. **Bubblewrap** (`bwrap`): namespace-based filesystem isolation — workspace writable, rest read-only
3. **Landlock** (when supported): kernel-level path restrictions as fallback/complement

Network isolation on Linux is done via seccomp (block socket-related syscalls) rather than a network namespace.

#### Windows — Restricted Token + AppContainer
```rust
// core/src/windows_sandbox.rs
// Uses Windows Job Objects + Restricted Token for filesystem isolation
// AppContainer (when available) for network/process isolation
// WindowsSandboxLevel enum: Basic | AppContainer | JobObject
```

Note: The Windows sandbox is considerably weaker than macOS/Linux equivalents. The docs acknowledge this limitation.

#### Sandbox Policy Modes
```rust
// protocol/src/protocol.rs
pub enum SandboxPolicy {
    DangerFullAccess,           // no restrictions
    ReadOnly { access, network_access },  // read everywhere, write nowhere
    WorkspaceWrite {            // read everywhere, write in workspace only
        writable_roots: Vec<PathBuf>,
        network_access: bool,
    },
    FullAccess {                // write everywhere (legacy)
        network_access: bool,
    },
}
```

### 1.5 Approval Modes

```rust
// protocol/src/protocol.rs
pub enum AskForApproval {
    UnlessTrusted,  // "untrusted" — only known-safe read-only commands auto-approved
    OnFailure,      // DEPRECATED — auto-approve but escalate if command fails
    OnRequest,      // "suggest" — approve when model explicitly requests it
    Never,          // "full-auto" — never ask, execute everything
}
```

Plus a `Granular` variant for fine-grained control:
```rust
AskForApproval::Granular {
    sandbox_approval: bool,   // whether to prompt on sandbox-restricted commands
    rules: bool,              // whether to apply exec-policy rules
}
```

**Policy evaluation flow** (`core/src/exec_policy.rs`):
1. Parse shell command via `bash::parse_shell_lc_plain_commands()`
2. Check against `is_known_safe_command()` — a curated allowlist of read-only commands
3. Check against user-defined `rules/*.rules` files (DSL allowlist/denylist)
4. Check `command_might_be_dangerous()` — heuristic detection of risky patterns
5. Based on `AskForApproval` policy, either auto-approve, ask user, or reject

**Banned prefix suggestions**: The policy engine has a hardcoded list of shell interpreters (`python3`, `bash`, `node`, `perl`, `ruby`, `osascript`, etc.) that cannot be used as allowlist prefixes — preventing bypass via interpreter injection.

### 1.6 Cloud Sandbox

`codex cloud` (`cloud-tasks/` crate) submits tasks to a ChatGPT-hosted cloud environment:

- **Backend**: `https://chatgpt.com/backend-api` (or `CODEX_CLOUD_TASKS_BASE_URL`)
- **Auth**: ChatGPT OAuth via `codex login` — loads auth tokens from keyring
- **Environments**: Pre-loaded repo snapshots (`env_id`) — the cloud side has already cloned the repository
- **`best_of_n`**: Submit N parallel attempts and pick the best result (shown in the TUI diff view)
- **Task lifecycle**: `TaskStatus` enum tracks `pending → running → complete/failed`
- **TUI**: `cloud-tasks/src/ui.rs` shows a scrollable diff viewer, task status, timestamps

The cloud sandbox architecture from the user's perspective:
1. `codex cloud` → authenticates + reads `git` branch info
2. Submits `{prompt, env_id, best_of_n}` to backend
3. Backend runs Codex in an isolated container with repo pre-loaded
4. Returns diff(s) for user to apply locally

This is conceptually identical to Clade's loop-runner but hosted — each task is an isolated worktree equivalent.

---

## Part 2: OpenAI Agents SDK

### 2.1 Core Primitives

The SDK is built on three primitives: **Agent**, **Runner**, **Handoff**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Agent                                                                       │
│    name, instructions, tools[], handoffs[], guardrails[]                    │
│    output_type (structured output schema)                                   │
│    hooks (AgentHooks — lifecycle callbacks)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
              │ .run() / Runner.run()
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Runner.run(agent, input, context, run_config)                              │
│    ↓ prepare_input_with_session()                                           │
│    ↓ run_input_guardrails()           [parallel by default]                 │
│    ↓ loop:                                                                  │
│       run_single_turn() → model call → process_model_response()             │
│         → NextStepHandoff → execute_handoffs() → new agent, repeat         │
│         → NextStepFinalOutput → run_output_guardrails() → done             │
│         → NextStepRunAgain → loop                                           │
│         → NextStepInterruption → human-in-the-loop                         │
│    ↓ save_result_to_session()                                               │
│    → RunResult                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Multi-Agent Coordination: Two Patterns

#### Pattern A — Manager (Agents-as-Tools)

The orchestrator agent calls sub-agents as regular function tools via `agent.as_tool()`. The orchestrator retains control throughout and combines sub-agent outputs.

```python
researcher = Agent(name="Researcher", instructions="...")
writer = Agent(name="Writer", instructions="...")

manager = Agent(
    name="Manager",
    tools=[
        researcher.as_tool(tool_name="research", description="Research a topic"),
        writer.as_tool(tool_name="write", description="Write content"),
    ]
)

result = await Runner.run(manager, "Write a report on quantum computing")
```

**Data flow**: Manager → tool call → sub-agent runs internally → tool output returned → manager continues. Sub-agent's conversation is isolated; only the final output is returned to the manager.

**Best for**: Tasks where one agent must own the final synthesis, or where multiple specialist outputs must be combined.

#### Pattern B — Handoff (Routing/Delegation)

The active agent transfers control to another agent, which then becomes the active agent for the remainder of the run. Implemented as a special tool call.

```python
billing_agent = Agent(name="Billing", instructions="...")
support_agent = Agent(
    name="Support",
    handoffs=[handoff(billing_agent)]  # appears as tool: transfer_to_billing
)
```

**Default tool name**: `transfer_to_<agent_name>` (snake_case).

### 2.3 Handoff — Code-Level Implementation

#### Data Structures

```python
# src/agents/handoffs/__init__.py

@dataclass
class HandoffInputData:
    input_history: str | tuple[TResponseInputItem, ...]  # pre-run conversation
    pre_handoff_items: tuple[RunItem, ...]               # items before this turn
    new_items: tuple[RunItem, ...]                        # current turn (incl. handoff call)
    run_context: RunContextWrapper | None                 # context at handoff time
    input_items: tuple[RunItem, ...] | None               # filtered items for next agent

@dataclass
class Handoff(Generic[TContext, TAgent]):
    tool_name: str                    # "transfer_to_billing"
    tool_description: str
    input_json_schema: dict           # strict JSON schema for tool-call args
    on_invoke_handoff: Callable       # async fn(ctx, input_json) -> Agent
    input_filter: HandoffInputFilter | None
    nest_handoff_history: bool | None
    agent_name: str
    is_enabled: bool | Callable
```

#### The `handoff()` Factory

```python
def handoff(
    agent: Agent,
    tool_name_override=None,
    tool_description_override=None,
    on_handoff: Callable | None = None,  # side-effect callback only
    input_type: type | None = None,       # Pydantic type for tool-call args
    input_filter: Callable | None = None, # filter history passed to next agent
    nest_handoff_history: bool | None = None,
    is_enabled: bool | Callable = True,
) -> Handoff
```

Key design note: `on_handoff` is for **side effects only** (e.g., logging, DB writes). The target agent is always the one captured in `handoff(agent)`. This prevents dynamic destination selection from `on_handoff`, which enforces deterministic routing.

`input_type` enables the model to pass structured metadata at handoff time (e.g., `{"reason": "billing query", "priority": "high"}`). This is validated via Pydantic's `TypeAdapter` before being passed to `on_handoff`. Critically, this metadata is **separate from conversation history** — it does not appear in the next agent's input unless explicitly included.

#### Execution in the Agent Loop

```python
# src/agents/run_internal/turn_resolution.py

async def execute_handoffs(agent, original_input, pre_step_items, new_step_items,
                           new_response, run_handoffs, hooks, context_wrapper, run_config):
    # Multiple simultaneous handoffs: only first is honored, rest get error output
    if len(run_handoffs) > 1:
        # append error items for extras, record SpanError
        ...

    actual_handoff = run_handoffs[0]
    with handoff_span(from_agent=agent.name) as span_handoff:
        # 1. Invoke the handoff (runs on_handoff side-effect callback if any)
        new_agent = await handoff.on_invoke_handoff(ctx, tool_call.arguments)
        span_handoff.span_data.to_agent = new_agent.name

        # 2. Append HandoffOutputItem to conversation
        new_step_items.append(HandoffOutputItem(source_agent=agent, target_agent=new_agent))

        # 3. Fire hooks (parallel): global on_handoff + agent-level on_handoff
        await asyncio.gather(
            hooks.on_handoff(ctx, from_agent=agent, to_agent=new_agent),
            agent.hooks.on_handoff(...) if agent.hooks else noop,
        )

        # 4. Build HandoffInputData, apply input_filter
        handoff_input_data = HandoffInputData(
            input_history=original_input,
            pre_handoff_items=pre_step_items,
            new_items=new_step_items,
        )
        if handoff.input_filter:
            handoff_input_data = await handoff.input_filter(handoff_input_data)

        # 5. Optionally compress prior history into a summary
        if nest_handoff_history:
            handoff_input_data = nest_history(handoff_input_data, mapper)

    # 6. Return NextStepHandoff — the main run loop re-enters with new_agent
    return SingleStepResult(next_step=NextStepHandoff(new_agent), ...)
```

#### State Transfer in Detail

The `input_filter` is the primary mechanism for controlling what the receiving agent sees:

```
Full history visible to source agent:
  [original_input] + [pre_handoff_items] + [new_items (incl. handoff call)]

What receiving agent sees (default — no filter):
  → [original_input] + [pre_handoff_items] + [new_items]
  (full transcript including all prior turns)

With remove_all_tools filter:
  → all items with tool calls/outputs stripped

With nest_handoff_history=True:
  → prior turns compressed into a summary message (via history_mapper)
  + new_items (current turn only)

Custom input_filter can do anything: select specific items, add system context,
translate messages, etc.
```

The `RunContextWrapper.context` object flows unchanged to the new agent — application state is always fully accessible across handoffs without any explicit transfer.

### 2.4 Tracing System

#### Architecture

```
Runner.run()
    │
    ├─ create_trace_for_run()              → Trace (workflow-level container)
    │       trace_id = "trace_<32 chars>"
    │       workflow_name, group_id, metadata
    │
    └─ agent_span(agent_name)              → Span[AgentSpanData]
           │
           ├─ generation_span()            → Span[GenerationSpanData]
           │       model, input, output, tokens, model_config
           │
           ├─ function_span(tool_name)     → Span[FunctionSpanData]
           │       input, output
           │
           ├─ guardrail_span(name)         → Span[GuardrailSpanData]
           │       triggered: bool
           │
           ├─ handoff_span(from, to)       → Span[HandoffSpanData]
           │
           └─ mcp_tools_span(server)       → Span[MCPListToolsSpanData]

Context propagation: Python contextvars (no manual passing required)
→ concurrent asyncio tasks automatically inherit parent span
```

#### Span Data Types

```python
# tracing/span_data.py
class AgentSpanData:      name, handoffs[], tools[], output_type
class GenerationSpanData: input, output, model, model_config, usage
class FunctionSpanData:   name, input, output
class GuardrailSpanData:  name, triggered
class HandoffSpanData:    from_agent, to_agent
class MCPListToolsSpanData: server, result, error
class TranscriptionSpanData: input_audio, output_text, model
class SpeechSpanData:     input_text, output_audio, model
class CustomSpanData:     name, data: dict
```

#### Processor Pipeline

```python
# Two-tier architecture:
TraceProvider                        ← creates Trace instances
    └─ List[TracingProcessor]        ← each processor sees all traces/spans

# Default: BatchTraceProcessor → BackendSpanExporter → OpenAI dashboard
# Custom: implement TracingProcessor ABC

class TracingProcessor(ABC):
    def on_trace_start(self, trace: Trace) -> None: ...
    def on_trace_end(self, trace: Trace) -> None: ...
    def on_span_start(self, span: Span) -> None: ...
    def on_span_end(self, span: Span) -> None: ...
    def shutdown(self) -> None: ...
    def force_flush(self) -> None: ...

# Add alongside default:
add_trace_processor(my_processor)

# Replace default entirely:
set_trace_processors([my_processor])  # OpenAI backend excluded unless re-added
```

**Ecosystem**: 25+ third-party integrations — Weights & Biases, MLflow, Langfuse, Arize-Phoenix, LangSmith, Braintrust, etc.

**Sensitive data**: `RunConfig(trace_include_sensitive_data=False)` strips LLM inputs/outputs from spans. Controlled per-run or globally via `OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA=0`.

### 2.5 Guardrails

```
Input guardrails (parallel by default):
  User input → [guardrail_1, guardrail_2] → ✓ proceed | ✗ InputGuardrailTripwireTriggered
                     ↕ concurrent with
               agent starts processing (parallel mode = better latency)
               — OR —
               agent waits (blocking mode = no token waste if guardrail fires)

Output guardrails (sequential):
  Agent output → guardrail_1 → guardrail_2 → ✓ return | ✗ OutputGuardrailTripwireTriggered
```

Implementation pattern — guardrail is itself an agent call:
```python
@input_guardrail
async def math_check(ctx, agent, input) -> GuardrailFunctionOutput:
    result = await Runner.run(cheap_classifier_agent, input, context=ctx.context)
    return GuardrailFunctionOutput(
        output_info=result.final_output,       # arbitrary metadata passed back
        tripwire_triggered=result.final_output.is_math_homework
    )
```

**Tool guardrails** (added 2025): Wrap `@function_tool` calls with pre/post validation. Can skip the call, replace the output, or tripwire. Apply on every tool invocation regardless of position in the chain.

**Boundary rules**:
- Input guardrails: only on the **first** agent in a workflow
- Output guardrails: only on the **last** agent
- Tool guardrails: every function-tool call throughout

### 2.6 Voice Pipeline

```
AudioInput (complete)          StreamedAudioInput (chunks)
      │                               │
      └──────────┬────────────────────┘
                 ▼
         VoicePipeline.run(audio_input)
                 │
                 ▼
         STT Model (transcription_span)
         → text transcript
                 │
                 ▼
         VoiceWorkflowBase.run(transcript)  ← your agent logic here
         → text output (streamed)
                 │
                 ▼
         TTS Model (speech_span)
         → StreamedAudioResult
              ├─ AudioChunkEvent
              ├─ TurnStartedEvent / TurnEndedEvent
              └─ ErrorEvent
```

`SingleAgentVoiceWorkflow` is the out-of-box workflow — wraps a single Agent. Custom workflows implement `VoiceWorkflowBase`.

Configuration: `VoicePipelineConfig(stt_model, tts_model, trace_include_sensitive_audio_data)`.

### 2.7 Model-Agnostic Design

The abstraction layer:

```python
# src/agents/models/interface.py

class Model(ABC):
    @abstractmethod
    async def get_response(
        self,
        system_instructions, input, model_settings,
        tools, output_schema, handoffs, tracing,
        *, previous_response_id, conversation_id, prompt
    ) -> ModelResponse: ...

    async def stream_response(...) -> AsyncIterator[TResponseStreamEvent]: ...

class ModelProvider(ABC):
    @abstractmethod
    def get_model(self, model_name: str | None) -> Model: ...
```

**Built-in providers**: `OpenAIProvider` (Responses API + Chat Completions), `LiteLLM` (via `litellm/` prefix), `AnyLLM` (via `any-llm/` prefix).

**`MultiProvider`** — routes by model name prefix:
```python
# "gpt-4.1"         → OpenAI provider (no prefix or "openai/" prefix)
# "litellm/claude-3" → LiteLLM provider
# "any-llm/..."      → AnyLLMProvider
# custom: MultiProvider(provider_map=MultiProviderMap({
#     "my-backend/": MyCustomProvider()
# }))
```

`ModelSettings` covers: temperature, top_p, max_tokens, tool_choice, parallel_tool_calls, reasoning effort, store/truncation options — provider-independent.

---

## Part 3: Synthesis — Implications for Clade

### 3.1 Handoff Pattern → Clade Task Routing

Clade's current model: a linear supervisor → worker task queue. The Agents SDK Handoff pattern offers a richer primitive:

**What Clade could adopt**:
1. **Typed handoffs between workers**: Instead of a worker returning a raw string result and the supervisor re-dispatching, a worker could hand off directly to a specialized follow-up worker with structured context (e.g., `HandoffInputData` equivalent containing: the task, the partial work done, the next sub-task).
2. **`input_filter` for context compression**: Before handing off to the next worker, compress or filter the conversation — analogous to Clade's TLDR generation but wired into the task routing itself.
3. **`on_handoff` side effects**: When routing to a specialized worker, trigger bookkeeping (DB write, metric increment) in a clean, composable hook.

**The key insight**: Handoff = "I delegate, you own it now." This is different from agents-as-tools = "I outsource, I still own it." Clade's loop-runner always returns control to supervisor — this is the manager pattern. Adding a handoff primitive would allow chains of workers where each one decides the next step.

### 3.2 Tracing System → Clade Observability

Clade has no structured tracing. The Agents SDK tracing system is directly applicable:

**Immediate wins for Clade**:
1. **Span-per-task**: Wrap each worker task in a `task_span(task_id, worker_id)` that records start/end time, input prompt, output summary.
2. **Nested spans**: Within a task, add `llm_call_span()` (captures model + tokens) and `tool_call_span()` (captures which tools were invoked).
3. **ProcessorInterface**: Define `TracingProcessor` ABC → implement a `SQLiteTracingProcessor` that writes to the existing `task_queue.db`. No new infrastructure needed.
4. **Trace IDs flow**: Use Python `contextvars` to propagate trace_id through async workers without threading it manually through every function signature.
5. **Sensitive data flag**: A `trace_include_sensitive_data` equivalent would let Clade redact LLM prompts/outputs from logs in production mode.

**Architecture sketch**:
```python
# Add to worker.py or a new tracing.py leaf module

class SpanData:
    name: str
    start_time: float
    end_time: float | None
    data: dict
    error: str | None

class CladeSQLiteTracingProcessor(TracingProcessor):
    def on_span_end(self, span):
        # write to task_spans table in task_queue.db
        ...
```

The BatchTraceProcessor pattern (buffer → flush) would be particularly valuable for Clade's high-throughput parallel worker scenarios.

### 3.3 Guardrails → Clade Input/Output Validation

Clade's workers currently have no input validation before spending tokens. Guardrails offer:

1. **Pre-task guardrail**: Before dispatching a task to an expensive worker, run a fast/cheap classifier: "Is this task well-formed? Does it have enough context? Is it duplicate?" Parallel mode = near-zero latency penalty.
2. **Post-task guardrail**: After a worker completes, validate the output before marking the task done: "Did the worker actually address the original goal? Is the output coherent?"
3. **Blocking mode for budget gates**: When the project is near its token budget, switch guardrails to blocking mode — prevent workers from starting expensive tasks at all.

### 3.4 Codex MCP Server → Clade as MCP Server

Clade skills are currently only invokable via Claude Code's slash-command mechanism. The Codex MCP server pattern (`codex mcp-server`) shows how to expose an agent framework as a generic MCP tool:

- `CodexToolCallParam` maps directly to Clade's `loop-runner` parameters (goal, max_iter, project_dir)
- The approval elicitation pattern (MCP `elicit` for blocking decisions) maps to Clade's intervention system
- This would allow any MCP-capable agent (Claude Desktop, Cursor, other IDEs) to invoke Clade's loop runner as a tool

### 3.5 MultiProvider → Clade Provider Abstraction

Clade currently has a `/provider` skill that hot-swaps the LLM. The Agents SDK's `Model` ABC + `MultiProvider` pattern (prefix-based routing) is cleaner:

```
"claude-sonnet" → AnthropicProvider
"minimax/..."   → MinimaxProvider  
"gpt-4.1"       → OpenAIProvider
```

This would let Clade route different tasks to different models within the same run — e.g., cheap model for TLDR generation, expensive model for actual implementation.

### 3.6 Sandbox → Clade Execution Safety

Codex's three-tier sandbox (macOS Seatbelt / Linux bubblewrap+seccomp / Windows restricted token) with per-command policy evaluation is significantly more robust than Clade's current approach. Key lessons:

1. **Policy DSL**: Codex's `rules/*.rules` allowlist DSL is user-configurable without code changes. Clade could add a similar `~/.claude/exec-policy.rules` file.
2. **Interpreter injection prevention**: The BANNED_PREFIX_SUGGESTIONS list prevents bypass via `bash -c "dangerous_command"`. Any Clade exec validation should block shell interpreter prefixes.
3. **`CODEX_SANDBOX_ENV_VAR`**: Injecting an env var so nested processes know they're sandboxed allows recursive sandbox awareness — useful if Clade ever nests agent calls.

---

## Summary Table

| Feature | Codex CLI | Agents SDK | Clade Today | Clade Could Adopt |
|---|---|---|---|---|
| Execution model | Single agent, long-running turns | Multi-agent, composable | Supervisor + worker pool | Handoff routing between workers |
| Sandboxing | OS-level (seatbelt/bubblewrap/seccomp) | None (LLM-only) | None | Policy DSL + interpreter blocklist |
| Tracing | OTEL (otel/ crate) | Built-in span hierarchy | None | SpanData + SQLiteTracingProcessor |
| Approval flow | AskForApproval enum + policy rules | Guardrails (input/output/tool) | Human intervention (DB) | Parallel input guardrails pre-dispatch |
| MCP role | Client + Server | Client | None | MCP server for loop-runner |
| Multi-model | Config profile per session | MultiProvider (prefix routing) | /provider skill (hot-swap) | Per-task model routing |
| State transfer | Conversation rollout (SQLite) | HandoffInputData + input_filter | Task DB + TLDR | HandoffInputData-style structured context |
| Cloud execution | codex cloud (ChatGPT backend) | None | None | Pattern: task + env_id + best_of_n |
