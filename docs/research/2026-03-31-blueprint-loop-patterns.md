---
name: 2026-03-31-blueprint-loop-patterns.md
date: 2026-03-31
status: reference
review_date: 2026-03-31
summary:
  - "Blueprint pattern: PRE/LLM CORE/POST phase separation across 5 systems (Stripe Minions, LangGraph, Composio, OpenHands, mini-swe-agent)"
integrated_items:
  - "Blueprint PRE/LLM CORE/POST pattern — already implemented in Clade loop (worker.py PRE/POST phases)"
needs_work_items:
  - "Hard loop-back criteria (2-round CI cap) — could enhance loop exit conditions"
  - "Phase separation recommendations — already partially implemented"
reference_items:
  - "Stripe Minions 2-round CI cap for loop termination"
  - "Mini-swe-agent exception-driven loop termination"
---

# Blueprint Loop Patterns — Deterministic Pre/Post Phases with LLM Cores

**Date**: 2026-03-31
**Purpose**: Research how different agent systems separate deterministic work from LLM work, forming a "Blueprint" architecture pattern applicable to Clade redesign.

---

## 1. Executive Summary

The Blueprint pattern — where pre/post phases are deterministic and only the core work uses LLM — appears independently across four major agent frameworks:

| System | Pre Phase | LLM Phase | Post Phase | Loop Decision |
|--------|-----------|-----------|------------|---------------|
| **Stripe Minions** | Parse input, pre-hydrate context, run linters (<1s) | Implement task, fix CI failures | Push branch, trigger CI, apply autofixes, create PR | 2-round CI cap (hard) |
| **LangGraph StateGraph** | `START` → deterministic node | LLM node (via `RunnableCallable`) | deterministic node → `END` | Conditional edges (deterministic functions) |
| **Composio ao** | Lifecycle poll (30s), batch GraphQL fetch, status determination | Agent executes in worktree | Reaction execution (send-to-agent or notify-human) | State machine transitions |
| **OpenHands** | EventStream dispatch, action selection | CodeActAgent LLM step | Observation write, Condenser trigger | Event cause chain + state enum |
| **mini-swe-agent** | (minimal — no pre phase) | Single `query()` call | `_check_finished()` for magic string | Exception-driven (`InterruptAgentFlow`) |

**Core insight**: All systems converge on the same principle — **LLMs should not decide what is deterministically knowable**. The pre phase does context preparation that doesn't need intelligence; the post phase does verification that can be automated; only the middle phase requires genuine reasoning.

---

## 2. The Blueprint Pattern Defined

### 2.1 What Makes a Loop "Blueprint"

A Blueprint loop has three distinct zones:

```
┌─────────────────────────────────────────────────────────────┐
│                    BLUEPRINT LOOP ARCHITECTURE              │
│                                                             │
│  ┌─────────────┐    ┌──────────────────┐    ┌───────────┐ │
│  │   PRE       │ → │   LLM CORE        │ → │   POST     │ │
│  │  (det.✅)   │    │  (intelligent🤖)  │    │ (det.✅)  │ │
│  └─────────────┘    └──────────────────┘    └───────────┘ │
│                                                             │
│  PRE:  git diff, parse input, context prep, lint, tests     │
│  LLM:  plan, implement, decide, fix, review                 │
│  POST: verify output, update state, push, create PR          │
└─────────────────────────────────────────────────────────────┘
```

**Key properties**:
1. **PRE and POST are closed under determinism** — same input always produces same output, no randomness
2. **LLM is isolated to the uncertain parts** — where the path forward genuinely cannot be predicted
3. **State is explicitly preserved** — checkpoint, state dict, or event log carries context between phases
4. **Loop-back is a deterministic decision** — not left to LLM preference, but based on measurable criteria

### 2.2 Why This Pattern Emerged

The pattern emerged independently across systems because of three pressures:

1. **Token cost at scale**: Running LLM inference for "should I run linters?" wastes tokens. Stripe's 1,300+ PRs/week makes this optimization mandatory.
2. **Failure blast radius**: If every step is LLM-decided, a single LLM error cascades. Deterministic gates catch failures early.
3. **Auditability**: Regulated environments (finance, healthcare) need auditable decision trails. "LLM decided to skip tests" is not auditable; "linter returned non-zero exit code, therefore retry" is.

---

## 3. System-by-System Analysis

### 3.1 Stripe Minions — The Blueprint Pioneer

**Source**: Stripe's Minions system (1,300+ PRs/week, 3M+ tests, 500 MCP tools)

Stripe's architecture is the clearest expression of the Blueprint pattern. The state machine for every PR:

```
[deterministic] Parse Slack thread + extract links
[deterministic] MCP pre-hydrate all links (fetch tickets, docs, code refs)
[AGENT NODE]    Implement task
[deterministic] Run configured linters (<1s, pre-cached)
[deterministic] Push branch
[deterministic] Trigger CI
[AGENT NODE]    (if failures) Fix CI failures
[deterministic] Apply autofixes
[deterministic] Second CI push (max)
[deterministic] Create PR from template
```

**How PRE/post are separated from LLM**:

| Phase | Activities | Why Deterministic |
|-------|-----------|------------------|
| PRE | Parse links, MCP pre-hydrate | File I/O + API calls, no decision |
| LLM | Implement, fix failures | Genuine uncertainty |
| POST | Lint, push, CI trigger, autofix, PR create | Git operations + CI APIs, scripted |

**The 2-CI-round cap** is the key loop-back decision: after 2 rounds, return to human. This is NOT an LLM decision — it is a hard counter.

**Pre-hydration pattern**: Before the agent node starts, deterministic MCP tool calls fetch all linked content. The agent starts with full context already built. This is the equivalent of "PRE phase fills the context buffer."

**Context engineering**: Rule files (`.cursor/rules` format) scoped per subdirectory. Tool subsetting — each agent type gets ~50 of 500 tools. "Flooding an agent with 500 tools degrades reasoning quality."

### 3.2 Pi Coding Agent — Extension Hooks as Pre Phase

**Source**: `pi-mono/packages/coding-agent`

Pi is a minimal terminal coding harness. Its Blueprint-like pattern emerges through the **extension hook system**:

```typescript
pi.on("before_agent_start", async (event, ctx) => {
  // Fire AFTER user message, BEFORE agent.prompt()
  // Return { messages: [...], systemPrompt?: "..." }
  // This IS the pre-hydration/prep phase
});

pi.on("tool_result", async (event, ctx) => {
  // Transform tool output before LLM sees it — POST processing
});
```

**Structured compaction as Blueprint POST**:

When context exceeds limits, Pi's compaction is a deterministic post phase:
```typescript
// Trigger: contextTokens > contextWindow - reserveTokens
// Algorithm:
//  1. Walk messages newest → oldest, accumulate tokens
//  2. Find nearest valid cut point
//  3. LLM summarizes everything before cut
//  4. Append CompactionEntry with summary + firstKeptEntryId
```

The summary format is **structured** (not free text):
```
## Goal
## Constraints & Preferences
## Progress (Done / In Progress / Blocked)
## Key Decisions + rationale
## Next Steps
## Critical Context
```

This is the POST phase — it transforms raw history into distilled state.

**JSONL session tree**: Every entry has `id` + optional `parentId`, forming a branching tree in one file. The `buildSessionContext()` walks from leaf to root; on `compaction` entry, emits summary first then messages from `firstKeptEntryId`.

### 3.3 LangGraph StateGraph — The Most Blueprint-Like Framework

**Source**: LangGraph v0.4.x documentation and source

LangGraph is the only framework where **the Blueprint pattern is the native programming model**. The StateGraph is literally a directed graph where:

- **Nodes** = functions (deterministic OR LLM调用)
- **Edges** = control flow (deterministic functions)
- **State** = shared TypedDict across all nodes

**How LangGraph separates determinism from LLM**:

```python
from typing import Annotated, Literal
from typing_extensions import TypedDict
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# ─── 1. Define State Schema ───
class State(TypedDict):
    query: str
    search_results: Annotated[list[str], add]  # merge strategy
    messages: Annotated[list, add_messages]   # dedup + merge
    final_answer: str

# ─── 2. Deterministic PRE node ───
def prep_node(state: State) -> dict:
    """PRE: fetch related context, validate inputs — deterministic"""
    validated = state["query"].strip()
    return {"query": validated}  # Partial state update

# ─── 3. LLM CORE node ───
def llm_node(state: State) -> dict:
    """CORE: actual LLM reasoning — uncertain work"""
    # This is where the LLM actually thinks
    result = llm.invoke(state["messages"])
    return {"messages": [result]}

# ─── 4. Deterministic POST node ───
def post_node(state: State) -> dict:
    """POST: format output, write to storage — deterministic"""
    formatted = state["final_answer"].upper()
    return {"final_answer": formatted}

# ─── 5. Conditional edge (deterministic routing function) ───
def route_after_prep(state: State) -> Literal["llm_node", "post_node"]:
    """PRE phase decides whether to proceed to LLM or skip"""
    if not state["query"]:
        return "post_node"  # Empty query — skip LLM, go to post
    return "llm_node"

# ─── 6. Build graph ───
builder = StateGraph(State)
builder.add_node("prep", prep_node)      # deterministic PRE
builder.add_node("llm", llm_node)       # LLM CORE
builder.add_node("post", post_node)     # deterministic POST

builder.add_edge(START, "prep")         # START → PRE
builder.add_conditional_edges("prep", route_after_prep)
builder.add_edge("llm", "post")          # LLM → POST
builder.add_edge("post", END)           # POST → END

graph = builder.compile()
```

**Key LangGraph Blueprint mechanisms**:

1. **`interrupt()` for human-in-loop**: The POST phase can call `interrupt()` to pause and wait for human approval before proceeding.

```python
def human_review_node(state: State):
    decision = interrupt({
        "content": state["draft"],
        "instruction": "Review and approve or reject"
    })
    return {"approved": decision}
```

2. **`Command` for conditional routing**: A node can simultaneously update state AND control routing.

```python
def review_node(state: State) -> Command[Literal["revise_node", END]]:
    if approved:
        return Command(goto=END)
    else:
        return Command(update={"draft": ""}, goto="revise_node")
```

3. **`Send` for Map-Reduce parallelism**: Dynamic fan-out from one node to multiple:

```python
from langgraph.types import Send

def distribute_tasks(state: State) -> list[Send]:
    return [
        Send("worker_node", {"task": t, "context": state["context"]})
        for t in state["pending_tasks"]
    ]

builder.add_conditional_edges("supervisor", distribute_tasks)
```

4. **Checkpointing for state preservation**: After every super-step, the full state is saved. Recovery is from the last checkpoint, not the beginning.

```python
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")
graph = builder.compile(checkpointer=checkpointer)
```

**LangGraph's edge types**:

| Edge Type | Syntax | Behavior |
|-----------|--------|----------|
| Normal | `builder.add_edge("a", "b")` | Always go from a to b |
| Conditional | `builder.add_conditional_edges("a", routing_fn)` | routing_fn(state) → target node name |
| Dynamic | `builder.add_conditional_edges("a", Send_fn)` | Returns `list[Send]` for parallel fan-out |

The conditional edge routing function is **always deterministic** — it reads state and returns a string label. The LLM never directly controls routing.

### 3.4 Composio agent-orchestrator — Event-Driven Blueprint

**Source**: `ComposioHQ/agent-orchestrator` (5,617 stars, TypeScript)

The agent-orchestrator (ao) has a **reaction-based** Blueprint rather than phase-based. The distinction between deterministic and LLM work is enforced through the **LifecycleManager**:

```
┌──────────────────────────────────────────────────────────────────┐
│              LifecycleManager pollAll() (every 30s)               │
│                                                                  │
│  1. Batch GraphQL fetch: PR state + CI checks + reviews (1 call)  │
│  2. For each session: checkSession()                             │
│      ├── determineStatus() → status enum                         │
│      ├── On status transition → executeReaction()                │
│      └── On reaction escalation → notifyHuman()                  │
└──────────────────────────────────────────────────────────────────┘
```

**ReactionConfig as Blueprint specification**:

```typescript
"ci-failed": {
  auto: true,
  action: "send-to-agent",
  message: "CI is failing. Run `gh pr checks` to see the failures, fix them, and push.",
  retries: 2,
  escalateAfter: 2,
}
"review-comments": {
  auto: true,
  action: "send-to-agent",
  message: "Review comments on your PR. Address each one and push.",
  escalateAfter: "30m",
}
```

**How ao separates determinism**:

| Component | Deterministic? | Why |
|-----------|---------------|-----|
| LifecycleManager.pollAll() | Yes | 30s timer, no LLM |
| SCM batch GraphQL fetch | Yes | API calls, scripted |
| determineStatus() | Yes | State machine enum, no LLM |
| executeReaction() | Yes | Scripted actions |
| Escalation decision | Yes | Attempt count + duration check |
| **Agent work** | No (LLM) | Agent decides how to fix |

**Status state machine** (deterministic transitions):

```
spawning → working → pr_open → ci_failed → (back to working after fix)
                   ↓           ↓
                   → review_pending
                   → changes_requested → (back to pr_open after address)
                   → approved
                   → mergeable
                   → merged (terminal)
```

**Agent activity detection via JSONL** (not terminal scraping):

```typescript
// Reads Claude Code's native JSONL session file
const lastEntry = readLastJsonlEntry(sessionFile);
switch (lastEntry.type) {
  case "tool_use":
  case "user":       return "active";    // Agent is working
  case "assistant":
  case "summary":
  case "result":     return "ready";     // Agent finished turn, waiting
  case "permission_request": return "waiting_input";  // Agent blocked on approval
  case "error":      return "blocked";  // Agent hit error
}
```

This is the PRE phase for ao — before deciding what to do, it reads the agent's actual state from its native session format. No terminal scraping, no inference needed.

**Review comment fingerprinting** (POST deduplication):

```typescript
// Fingerprint = sorted concatenation of comment IDs
function makeFingerprint(ids: string[]): string {
  return [...ids].sort().join(",");
}
// Only send to agent when fingerprint CHANGES
// Prevents re-sending the same comments every poll cycle
```

### 3.5 OpenHands — Event Sourcing as Blueprint Infrastructure

**Source**: OpenHands (70k+ stars, V0→V1 migration in progress)

OpenHands uses **event sourcing** where every action and observation is logged. The Blueprint separation is enforced through the **Event types**:

```python
Event (base dataclass)
├── _id: int              # Global monotonically increasing
├── _timestamp: str       # ISO format
├── _source: EventSource  # AGENT / USER / ENVIRONMENT
├── _cause: int | None    # Links observation → action that triggered it
└── tool_call_metadata, llm_metrics, response_id

Action(Event)  — things agent DECIDES to do
├── MessageAction          # User/agent messages
├── CmdRunAction           # bash commands
├── FileEditAction
├── AgentDelegateAction    # Delegates to sub-agent
├── CondensationAction    # Triggers context compression
└── MCPAction             # MCP tool calls

Observation(Event)  — results of actions
├── CmdOutputObservation
├── ErrorObservation
└── AgentDelegateObservation
```

**The Blueprint pattern in OpenHands**:

```
PRE (deterministic):
  EventStream.add_event() — synchronous write to disk
  _process_queue() — async dispatch to subscribers
  determineStatus() — state machine enum

LLM CORE:
  Agent.step() — LLM decides next action

POST (deterministic):
  Runtime.execute(action) — runs command, returns observation
  EventStream.add_event(observation) — persisted before dispatch
  Condenser.trigger() — if token limit exceeded, triggers CondensationAction
```

**Condenser system** (context management as Blueprint POST):

```python
Condenser (abstract)
├── NoOpCondenser                    # No compression
├── RecentEventsCondenser            # Keep only last N events
├── LLMSummarizingCondenser          # LLM generates summary (default)
├── StructuredSummaryCondenser       # Structured format summary
└── CondenserPipeline               # Compose multiple condensers
```

When condensation triggers, a `CondensationAction` is written to the EventStream. The summary is **structured** (not free text):

```markdown
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

This is nearly identical to Pi's compaction format — independent invention of the same structured summary pattern.

**Replay/Recovery as Blueprint checkpoint**:

```python
ReplayManager(replay_events: list[Event])

# In control loop:
if replay_manager.should_replay():
    action = replay_manager.step()  # Return next historical Action
    # Execute directly, no LLM call
else:
    action = agent.step(state)     # Normal LLM inference
```

Replay only re-executes **Action** events (which are deterministic replays of what the agent decided). **Observation** events are regenerated (same action → same result).

### 3.6 mini-swe-agent — The Minimal Blueprint

**Source**: mini-swe-agent (3,600+ stars, ~150 lines core logic)

mini-swe-agent is the most instructive because of its **extreme simplicity**. The entire agent loop:

```python
class DefaultAgent:
    def step(self) -> list[dict]:
        return self.execute_actions(self.query())

    def query(self) -> dict:
        message = self.model.query(self.messages)
        self.add_messages(message)
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        outputs = [self.env.execute(action)
                   for action in message.get("extra", {}).get("actions", [])]
        return self.add_messages(
            *self.model.format_observation_messages(message, outputs)
        )

    def run(self, task: str = "") -> dict:
        self.messages = []
        self.add_messages(system_msg, instance_msg)
        while True:
            try:
                self.step()
            except InterruptAgentFlow as e:
                self.add_messages(*e.messages)
            if self.messages[-1].get("role") == "exit":
                break
        return self.messages[-1].get("extra", {})
```

**mini-swe-agent's implicit Blueprint**:

| Phase | Implementation | Why Deterministic |
|-------|---------------|------------------|
| PRE | `env.execute(action)` for setup commands | Subprocess run, scripted |
| LLM CORE | `model.query(messages)` | Genuine uncertainty |
| POST | `_check_finished()` checks for magic string | String match, deterministic |
| Loop-back | `InterruptAgentFlow` exception | Exception carries control flow |

**Exception-driven control flow** — the cleanest Blueprint mechanism:

```python
class InterruptAgentFlow(Exception):
    def __init__(self, *messages: dict):
        self.messages = messages  # Carries context to add to history

class Submitted(InterruptAgentFlow): pass    # Task complete
class LimitsExceeded(InterruptAgentFlow): pass  # Budget exhausted
class FormatError(InterruptAgentFlow): pass    # LLM format error
```

The loop-back decision is NOT "should I continue?" — it is "did a terminal exception occur?" The `Submitted` exception is raised when `_check_finished()` sees `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` in output.

**Single tool (bash)**: The entire system has exactly ONE tool. The insight: LLMs already know bash. Don't teach them something they already know.

```
┌─────────────────────────────────────────────────────────────────┐
│                    mini-swe-agent Loop                          │
│                                                                 │
│  while True:                                                    │
│      try:                                                        │
│          step() → execute_actions(query())                       │
│                    ├── query() → model.query(messages) [LLM]     │
│                    └── execute_actions() → env.execute(action)   │
│                                                                    │
│          except InterruptAgentFlow:                               │
│              add_messages(*e.messages)                           │
│              if terminal(exit): break                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Cross-System Patterns

### 4.1 Loop-Back Decision Mechanisms

How each system decides to loop back vs proceed:

| System | Mechanism | Deterministic? |
|--------|-----------|----------------|
| Stripe Minions | 2-round CI cap (counter) | Yes — hard limit |
| LangGraph | Conditional edge routing function | Yes — reads state |
| Composio ao | Reaction attempt count + duration | Yes — counter + timestamp |
| OpenHands | Event cause chain + status enum | Yes — state machine |
| mini-swe-agent | `Submitted` exception | Yes — magic string match |

**Key insight**: In NONE of these systems does the LLM decide whether to continue. Loop-back is always determined by a **measurable, deterministic criterion**.

### 4.2 State Preservation Between Iterations

| System | Mechanism | What is Preserved |
|--------|-----------|-------------------|
| LangGraph | Checkpoint (SQLite/Postgres) | Full state dict |
| OpenHands | EventStream (append-only JSON) | All events + causal chain |
| Pi | JSONL tree with compaction | Message history + structured summary |
| mini-swe-agent | Messages array (in-memory) | Full trajectory |
| Composio ao | Metadata files + in-memory state | Session state |

**Recovery granularity**:

| System | Recovery Level |
|--------|---------------|
| LangGraph | Last checkpoint (full state snapshot) |
| OpenHands | Last event (event log replay) |
| Pi | Last compaction entry + messages from firstKeptEntryId |
| mini-swe-agent | Full trajectory (in memory — no crash recovery) |
| Composio ao | Metadata files survive restart, in-memory does not |

### 4.3 Pre-Hydration / Context Filling Patterns

| System | Pre-Hydration Mechanism |
|--------|------------------------|
| Stripe Minions | MCP pre-hydrate links before agent starts |
| Pi | `before_agent_start` hook fetches context |
| Composio ao | `Tracker.generatePrompt()` fetches issue + branch |
| OpenHands | MicroAgents (RecallAction) for project knowledge |
| LangGraph | Deterministic `prep` node fills state |

**The pre-hydration pattern** is universal: before the LLM acts, deterministic code fills the context.

### 4.4 Post-Phase Verification Patterns

| System | Verification Mechanism |
|--------|------------------------|
| Stripe Minions | CI run + autofixes applied automatically |
| Composio ao | Reaction system — send-to-agent on CI failure |
| OpenHands | Condenser triggers on token overflow |
| mini-swe-agent | Magic string `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` |
| Pi | Structured compaction summary |

---

## 5. The Blueprint Pattern Applied to Clade

### 5.1 Current Clade vs Blueprint Target

```
Current Clade Loop:
  supervisor (LLM) → plans all tasks
    → worker (LLM) → executes in worktree
      → task_queue (SQLite)
    → worker result (raw)
  Loop decision: supervisor LLM decides "are we done?"

Target Blueprint Loop:
  supervisor (det. PRE) → git diff, parse TODO, context prep
    → supervisor (LLM CORE) → plan next task batch
    → worker (LLM CORE) → implement task
    → supervisor (det. POST) → verify, update state, decide loop-back
      → worker result → lint, test, verify
```

### 5.2 Explicit Phase Separation for Clade

**PRE phase** (always deterministic):
```
1. git diff --stat — what changed since last iteration?
2. Parse TODO.md — what are the pending P0/P1 items?
3. Read PROGRESS.md — what was accomplished last session?
4. Check task_queue — what failed/succeeded in last run?
5. Context prep: assemble file list + recent error messages
```

**LLM CORE phase** (only here uses LLM):
```
1. Supervisor: decide which tasks to assign this iteration
2. Worker: implement assigned tasks
```

**POST phase** (always deterministic):
```
1. Run linters (shell script, exit code only matters)
2. Verify syntax (python -m py_compile)
3. Update task_queue status
4. Update PROGRESS.md
5. Decision: did we converge? (check: all P0 tasks done OR max iterations reached)
```

### 5.3 Recommended Loop-Back Decision

```python
def should_loop_back(task_results: list[TaskResult], iteration: int) -> bool:
    """
    Deterministic loop-back decision — NO LLM call.
    Returns True if we should continue, False if converged/escalated.
    """
    # Hard limits
    if iteration >= MAX_ITERATIONS:  # e.g., 10
        return False

    # Success: all P0 tasks completed
    if all(t.status == "completed" for t in task_results if t.priority == "P0"):
        return False

    # Escalation: too many failures
    failed = [t for t in task_results if t.status == "failed"]
    if len(failed) >= MAX_CONSECUTIVE_FAILURES:  # e.g., 3
        return False

    # Continue: meaningful work happened
    if any(t.status == "completed" for t in task_results):
        return True

    # Continue: progress made (file changes, test improvements)
    return True
```

### 5.4 State Schema for Blueprint Loop

```python
from typing import TypedDict, Literal
from typing_extensions import Annotated

class LoopState(TypedDict):
    # Phase tracking
    phase: Literal["prep", "llm", "post"]

    # Iteration context
    iteration: int
    max_iterations: int

    # Pre phase output
    pending_tasks: list[str]      # P0/P1 TODO items
    changed_files: list[str]      # git diff --stat output
    last_error: str | None        # From failed task

    # LLM phase output
    planned_tasks: list[dict]     # Tasks assigned this iteration
    task_results: list[dict]       # Results from workers

    # Post phase output
    converged: bool
    needs_escalation: bool
    escalation_reason: str | None
```

---

## 6. Comparative Summary

### 6.1 Blueprint Pattern Matrix

| Property | Stripe | Pi | LangGraph | Composio | OpenHands | mini-swe |
|----------|--------|----|-----------|----------|-----------|----------|
| **Explicit pre/post phases** | Yes | Yes (hooks) | Yes (nodes) | Partial (reactions) | Yes (events) | Implicit |
| **Deterministic edges** | Yes | Yes | Yes | Yes | Yes | N/A |
| **LLM-only nodes** | Yes | Yes | Yes | Yes | Yes | Yes |
| **Hard loop-back criteria** | 2-round CI | Token limit | Checkpoint | Retry count | Event cause | Exception |
| **State preservation** | Devbox warm pool | JSONL tree | SQLite checkpoint | Metadata files | EventStream | In-memory |
| **Crash recovery** | Reconnect | JSONL replay | Checkpoint restore | State reload | Event replay | None |

### 6.2 What's Universal vs System-Specific

**Universal across all systems**:
1. Pre phase is deterministic file I/O + context preparation
2. Loop-back is a deterministic decision (counter, state enum, or exception)
3. LLM is isolated to genuinely uncertain work
4. State is explicitly preserved (checkpoints, events, or structured summaries)

**System-specific choices**:
1. **Mechanism**: Exceptions (mini-swe) vs state machine (Composio) vs event log (OpenHands) vs nodes+edges (LangGraph)
2. **Scale**: Single task (mini-swe) vs fleet (Composio) vs org-wide (Stripe)
3. **Isolation**: Git worktree (Composio, Clade) vs warm pool (Stripe) vs subprocess (mini-swe)
4. **Context management**: Compaction (Pi, OpenHands) vs checkpoint (LangGraph) vs pre-hydration (Stripe)

---

## 7. Implementation Recommendations for Clade

### 7.1 Phase 1: Refactor Loop to Blueprint

Refactor `/loop` skill to separate:

```python
# PRE phase — deterministic
def loop_prep(goal_file: Path, state: LoopState) -> dict:
    """Git diff, parse TODO, context prep. No LLM."""
    diff = subprocess.run(["git", "diff", "--stat"], capture_output=True)
    todos = parse_todo(goal_file)
    return {
        "changed_files": parse_diff_stat(diff.stdout),
        "pending_tasks": todos,
        "phase": "llm"
    }

# LLM CORE — only this uses LLM
async def loop_llm(state: dict) -> dict:
    """Supervisor plans, worker executes. LLM only here."""
    plan = await supervisor_plan(state)  # LLM call
    results = await workers_execute(plan)  # LLM calls in workers
    return {"planned_tasks": plan, "task_results": results, "phase": "post"}

# POST phase — deterministic
def loop_post(state: dict) -> dict:
    """Verify, update state, decide loop-back. No LLM."""
    verify_task_outputs(state["task_results"])
    update_task_queue(state["task_results"])
    converged = check_convergence(state)
    return {"converged": converged, "phase": "prep" if not converged else "end"}
```

### 7.2 Phase 2: Structured Compaction (from Pi/OpenHands)

Replace free-text handoffs with structured summaries:

```markdown
## Goal
<!-- From GOALS.md -->

## Progress
  ### Done
  - Task 1: implemented feature X
  - Task 2: fixed bug Y
  ### In Progress
  - Task 3: implementing feature Z (blocked on API)
  ### Blocked
  - Task 4: needs design decision

## Key Decisions
- Chose approach A over B because [reason]
- Deferred Task 5 to next iteration

## Next Steps
- Complete Task 3 (unblock: get API key from Alex)
- Start Task 5 after Task 3

## Critical Context
- ENV: production database accessed via worktree
- PATTERNS: Avoid using Feature X (see PROGRESS.md)
```

### 7.3 Phase 3: Hard Loop-Back Criteria

Replace LLM-decided loop continuation with hard criteria:

```python
LOOP_LIMITS = {
    "max_iterations": 10,
    "max_consecutive_failures": 3,
    "min_tasks_per_iteration": 1,
}

def should_continue(state: LoopState) -> tuple[bool, str | None]:
    """
    Returns (should_continue, escalation_reason).
    Deterministic — NO LLM call.
    """
    if state["iteration"] >= LOOP_LIMITS["max_iterations"]:
        return False, "max_iterations"

    failed = [t for t in state["task_results"] if t["status"] == "failed"]
    if len(failed) >= LOOP_LIMITS["max_consecutive_failures"]:
        return False, f"too_many_failures({len(failed)})"

    completed = [t for t in state["task_results"] if t["status"] == "completed"]
    if not completed:
        return False, "no_progress"

    return True, None
```

### 7.4 Phase 4: Checkpoint-Based Recovery

From LangGraph's checkpointing pattern:

```python
class LoopCheckpoint:
    """Saves loop state after each phase completion."""

    def save(self, iteration: int, phase: str, state: dict) -> None:
        path = Path(f"~/.claude/loop-checkpoints/{project_name}/{iteration}-{phase}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"iteration": iteration, "phase": phase, "state": state}, path.open("w"))

    def recover(self) -> dict | None:
        """Find latest checkpoint and restore."""
        checkpoint_dir = Path(f"~/.claude/loop-checkpoints/{project_name}/")
        if not checkpoint_dir.exists():
            return None
        checkpoints = sorted(checkpoint_dir.glob("*.json"))
        if not checkpoints:
            return None
        return json.load(checkpoints[-1].open())
```

---

## 8. Key Research Sources

- [Stripe Minions Blog Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- [Stripe Minions Blog Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- [Pi Coding Agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent)
- [LangGraph Documentation](https://docs.langchain.com/oss/python/langgraph)
- [Composio agent-orchestrator](https://github.com/ComposioHQ/agent-orchestrator)
- [OpenHands Architecture](https://github.com/OpenHands/OpenHands)
- [mini-swe-agent](https://github.com/swe-land/mini-swe-agent)
- [SWE-agent Paper (arXiv:2405.15793)](https://arxiv.org/abs/2405.15793)
