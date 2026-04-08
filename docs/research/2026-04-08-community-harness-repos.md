---
date: 2026-04-08
topic: Community Claude Code Harness Repos — Deep Analysis
sources:
  - https://github.com/shareAI-lab/learn-claude-code
  - https://github.com/claude-code-best/claude-code
  - https://github.com/affaan-m/everything-claude-code
status: integrated
---

[中文] | [Back to README](../../README.md)

# Research: Community Claude Code Harness Repos (2026-04-08)

Deep analysis of three community repos — architecture patterns, implementation details, and gaps for Clade.

---

## 1. shareAI-lab/learn-claude-code

**"Bash is all you need — A nano claude code–like agent harness, built from 0 to 1"**

A 19-chapter teaching repo walking from a minimal loop to full multi-agent systems. Primary value: it makes the design backbone explicit at each stage.

### 1.1 Query Control Plane (s00a) — Critical Design Pattern

The repo's most important architectural insight is the **Query Control Plane** — the layer that sits above the data path and decides when/why/how the loop continues.

Why `messages[] + while True` breaks down:
- No way to know if reactive compaction already ran
- No way to count continuation attempts
- No way to distinguish a retry from a normal write-back
- No way to carry a temporary output budget

The fix: split `QueryParams` (immutable input) from `QueryState` (mutable process state), with an explicit `TransitionReason`:

```python
# External input — never mutated
QueryParams = {
    "messages": [...],
    "system_prompt": "...",
    "tool_use_context": {...},
    "max_output_tokens_override": None,
    "max_turns": None,
}

# Live state — patched at each continue-site
QueryState = {
    "messages": [...],
    "turn_count": 1,
    "continuation_count": 0,
    "has_attempted_compact": False,
    "transition": None,  # TransitionReason
}

TRANSITIONS = (
    "tool_result_continuation",
    "max_tokens_recovery",
    "compact_retry",
    "transport_retry",
)
```

**Gap in Clade**: `Worker._run()` has implicit state. When the reflection retry loop fires, there's no `transition_reason` field. Debugging why a worker ran 3 iterations vs 1 requires reading logs. Adding explicit transition state would make debugging and the status dashboard clearer.

### 1.2 Context Compact (s06) — Three-Level Strategy

The s06 implementation shows a clean three-tier approach:

**Level 1: `persist_large_output()` — disk offload**
```python
PERSIST_THRESHOLD = 30000  # chars

def persist_large_output(tool_use_id, output):
    if len(output) <= PERSIST_THRESHOLD:
        return output
    stored_path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    stored_path.write_text(output)
    preview = output[:2000]
    return (
        "<persisted-output>\n"
        f"Full output saved to: {rel_path}\n"
        f"Preview:\n{preview}\n"
        "</persisted-output>"
    )
```

**Level 2: `micro_compact()` — replace old tool results**
```python
KEEP_RECENT_TOOL_RESULTS = 3

def micro_compact(messages):
    # Keep only 3 most recent tool results; replace older ones
    tool_results = collect_tool_result_blocks(messages)
    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for _, _, block in tool_results[:-KEEP_RECENT_TOOL_RESULTS]:
        block["content"] = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
    return messages
```

**Level 3: `compact_history()` — full LLM summarization**
```python
def compact_history(messages, state, focus=None):
    transcript_path = write_transcript(messages)  # save full transcript first
    summary = summarize_history(messages)  # LLM summarization prompt
    if focus:
        summary += f"\n\nFocus to preserve next: {focus}"
    if state.recent_files:
        summary += f"\n\nRecent files to reopen if needed:\n{recent_lines}"
    state.has_compacted = True
    return [{"role": "user", "content": f"Conversation compacted.\n{summary}"}]
```

Key: transcript is always saved before compaction. `recent_files` tracked via LRU (5 entries) so the model knows what to re-read after compaction.

**Gap in Clade**: Our `ObservationMaskingCondenser` handles Level 1. We have no Level 2 (micro_compact). Level 3 exists in the loop-runner but not in worker.py. Also: we don't track `recent_files` to re-read after compaction.

### 1.3 Memory System (s09) — DreamConsolidator with 7-Gate Check

The `DreamConsolidator` implements a background memory consolidation pass with exactly 7 gates that ALL must pass before running:

```
Gate 1: enabled flag
Gate 2: memory directory exists with memory files
Gate 3: not in plan mode
Gate 4: 24-hour cooldown since last consolidation
Gate 5: 10-minute throttle since last scan attempt
Gate 6: >= 5 sessions worth of data
Gate 7: PID-based lock file available
```

The Dream consolidation runs 4 phases:
1. Orient: scan MEMORY.md index for structure/categories
2. Gather: read individual memory files for full content
3. Consolidate: merge related memories, remove stale entries
4. Prune: enforce 200-line limit on MEMORY.md index

**Gap in Clade**: Our auto-memory system writes entries but has no consolidation/deduplication pass. Memory files will accumulate stale/redundant entries over time. The 7-gate check pattern is clean — worth adopting for our memory pruning.

### 1.4 Task System (s12) — Bidirectional Dependency Clearing

The `TaskManager.update()` bidirectionally manages dependencies:
- When task completes, **automatically removes it from all other tasks' `blockedBy` lists**
- When `add_blocks` is called, **also updates the target task's `blockedBy` list**

```python
def _clear_dependency(self, completed_id):
    for f in self.dir.glob("task_*.json"):
        task = json.loads(f.read_text())
        if completed_id in task.get("blockedBy", []):
            task["blockedBy"].remove(completed_id)
            self._save(task)
```

**Gap in Clade**: Our `task_queue.py` stores `depends_on` as a list but completing a task doesn't cascade to unblock its dependents. Workers check `depends_on` before claiming, but the SwarmManager has to re-query on each `_refill_once()` call.

### 1.5 Autonomous Agents (s17) — Claim Lock + Idle Cycle + Identity Re-injection

Three key patterns:

**Claim lock (threading.Lock)** to prevent two workers claiming the same task:
```python
_claim_lock = threading.Lock()
# In TaskManager.claim():
with _claim_lock:
    task = self._load(task_id)
    if task["status"] != "pending": raise ValueError("Already claimed")
    task["status"] = "in_progress"
    task["owner"] = worker_name
    self._save(task)
```

**Idle cycle**: poll every 5s for up to 60s timeout
```
IDLE → check inbox → message? → resume WORK
     → scan .tasks/ → unclaimed ready task? → claim → resume WORK
     → timeout → shutdown
```

**Identity re-injection after compression**:
After compact, inject identity block at start of messages:
```python
messages = [identity_block, ...remaining...]
# identity_block = "You are 'coder', role: backend, team: my-team"
```

**Gap in Clade**: Our workers don't have identity re-injection after context compaction. If a worker's context is compacted mid-task, it loses its role identity.

### 1.6 Worktree Isolation (s18) — EventBus for Observability

The clean design principle: **"Isolate by directory, coordinate by task ID."**

```
task record = control plane (what to do, status, dependencies)
worktree    = execution plane (where to do it)
```

EventBus: append-only JSONL for all lifecycle events:
```python
class EventBus:
    def emit(self, event, task_id=None, wt_name=None, error=None, **extra):
        payload = {"event": event, "ts": time.time(), ...}
        with self.path.open("a") as f:
            f.write(json.dumps(payload) + "\n")
```

**Gap in Clade**: Our worker has logging but no structured EventBus. Worker lifecycle events (claim, start, tool_call, compact, done, failed) aren't queryable as structured data.

---

## 2. claude-code-best/claude-code

**Reverse-engineered Claude Code source — architectural ground truth**

### 2.1 Core Loop Architecture

```
cli.tsx → main.tsx → query.ts → QueryEngine.ts → REPL.tsx
                                     ↓
                              conversation state
                              compaction
                              file history snapshots
                              attribution
                              turn bookkeeping
```

- `query.ts` = single API call + streaming + tool dispatch
- `QueryEngine.ts` = conversation state + compaction + file history + attribution
- `REPL.tsx` = React/Ink terminal component

### 2.2 Feature Flag System

```typescript
import { feature } from 'bun:bundle';
// Enabled via: FEATURE_<FLAG_NAME>=1 env var

if (feature('DAEMON')) { /* long-running supervisor */ }
if (feature('BRIDGE_MODE')) { /* remote control mode */ }
if (feature('FORK_SUBAGENT')) { /* worktree subagent */ }
```

Known flags: `BUDDY`, `DAEMON`, `BRIDGE_MODE`, `BG_SESSIONS`, `VOICE_MODE`, `FORK_SUBAGENT`, `SSH_REMOTE`, `DIRECT_CONNECT`, `COORDINATOR_MODE`, `PROACTIVE`, `KAIROS`, `CHICAGO_MCP`

### 2.3 Tool Architecture — 61 Structured Tool Directories

Each tool has: `name`, `description`, `inputSchema`, `call()`, optional React render component. Tools render their own output in the terminal (not just raw text). This enables tool-specific UI: file diffs show highlighted, test results show colored pass/fail, etc.

### 2.4 Multi-Provider Support

```
Anthropic direct
AWS Bedrock
Google Vertex
Azure
OpenAI-compatible (Ollama/DeepSeek/vLLM via CLAUDE_CODE_USE_OPENAI=1)
```

### 2.5 Bridge / Remote Control Mode

`claude remote-control` (`claude rc`) — event-driven dispatch via JWT-authenticated HTTP. GitHub webhook → dispatch → Claude agent → fix → PR. This is essentially what our orchestrator's SwarmManager does, but implemented as a native Claude Code mode.

### 2.6 Key Implementation Details

- **React Compiler runtime** — memoization in all components (`_c()` calls)
- **`src/bootstrap/state.ts`** — module-level singletons for session-global state
- **`src/context.ts`** — builds system/user context: git status + date + CLAUDE.md + memory files
- **61 tool directories** in `src/tools/<ToolName>/` — each self-contained

---

## 3. affaan-m/everything-claude-code (ECC)

**Production-ready plugin: 39 agents, 73 commands, 179 skills. Scale: largest community harness.**

### 3.1 Context Budget Audit (`/context-budget`)

Counts token overhead per component type with optimization recommendations.

Token estimation:
- Prose: `words × 1.3`
- Code: `chars / 4`
- **MCP tools: ~500 tokens/tool** ← biggest lever

```
Component Breakdown (example):
Agents:   16 files  → ~12,400 tokens  (200 lines = heavy agent flag)
Skills:   28 active → ~6,200 tokens   (>400 lines = bloated skill flag)
Rules:    22 files  → ~3,100 tokens   (>100 lines = verbose flag)
MCP tools: 87 tools → ~43,500 tokens  ← largest category
CLAUDE.md: 2 files  → ~1,200 tokens   (>300 lines = bloated flag)

Top saving: remove 3 CLI-replaceable MCP servers → -27,500 tokens (47% reduction)
```

**Gap in Clade**: Workers receive TLDR + fault localization + caller hints + repro tests + SBFL + recent completions. We have `context_span_budget` (6000 chars) but no per-session audit of total context overhead before worker spawns.

### 3.2 Plankton Code Quality — Three-Phase Post-Edit Enforcement

The most technically sophisticated quality system in the community:

```
PostToolUse Edit/Write:
  Phase 1: Auto-Format (silent)
    → ruff format, biome, shfmt, taplo, markdownlint
    → Fixes 40-50% silently. No output to main agent.

  Phase 2: Collect Violations (JSON)
    → Unfixable violations → structured JSON {line, col, code, message}
    → Still no output.

  Phase 3: Delegate + Verify
    → spawn: claude -p <violations>
    → Model routing by violation type:
        Haiku  (120s): formatting/imports (E/W/F codes)
        Sonnet (300s): complexity/refactoring (C901/PLR)
        Opus   (600s): type system/deep reasoning
    → Re-run Phase 1+2 to verify
    → Exit 0 if clean, Exit 2 if still failing (reported to main agent)
```

**Config protection** (critical — LLMs disable linters to pass quality checks):
```
Layer 1: PreToolUse hook blocks edits to .ruff.toml, biome.json, etc.
Layer 2: Stop hook detects config changes via git diff at session end
Layer 3: Protected files list enforced at all edit events
```

**Package manager enforcement**:
- `pip/pip3/poetry/pipenv` → blocked, use `uv`
- `npm/yarn/pnpm` → blocked, use `bun`
- Exceptions: `npm audit`, `npm view`, `npm publish`

**Gap in Clade**: Our `post-tool-use-lint.sh` runs `verify_cmd` but doesn't do model routing or config protection. Workers can potentially disable linters in their project's config files to pass checks.

### 3.3 Strategic Compact — Phase-Boundary Compaction

The key insight: **compact at logical boundaries, not arbitrary token counts.**

```
| Phase Transition          | Compact? | Why                              |
|---------------------------|----------|----------------------------------|
| Research → Planning       | Yes      | Research context → plan distilled|
| Planning → Implementation | Yes      | Plan in TodoWrite; free context  |
| Implementation → Testing  | Maybe    | Depends on test reference to code|
| Debugging → Next feature  | Yes      | Debug traces pollute context     |
| Mid-implementation        | No       | Losing variable names is costly  |
| After failed approach     | Yes      | Clear dead-end reasoning         |
```

What persists through compaction:
- CLAUDE.md, TodoWrite list, memory files, git state, disk files

What's lost:
- Intermediate reasoning, previously-read file contents, tool call history

**Trigger-Table Lazy Loading** for skills:
```
| Trigger           | Skill           | Load When              |
|-------------------|-----------------|------------------------|
| "test", "tdd"     | tdd-workflow    | User mentions testing  |
| "security", "xss" | security-review | Security-related work  |
| "deploy", "ci/cd" | deployment      | Deployment context     |
```

**Gap in Clade**: Our PreCompact hook writes a checkpoint but doesn't enforce phase-boundary logic. Workers compact reactively when context fills up, potentially mid-implementation.

### 3.4 Eval-Driven Development (eval-harness)

Formal evaluation framework:

```
Eval types:
  CAPABILITY: test if Claude can do X it couldn't before
  REGRESSION: ensure changes don't break existing behavior

Grader types:
  Code-based:   grep/test/build (deterministic)
  Model-based:  LLM evaluation (open-ended)
  Human:        flag for manual review

Metrics:
  pass@1:  first attempt success rate
  pass@3:  success within 3 attempts (target >90%)
  pass^k:  all k attempts succeed (reliability)
```

**Gap in Clade**: Our oracle gives approve/reject per attempt but doesn't track `pass@k` across retries for the same task. The `parallel_fix_samples` feature (N=3 copies) is closest, but we don't measure the success rate distribution.

### 3.5 Rules Distill — Cross-Skill Principle Extraction

Three-phase: deterministic collection → LLM cross-read → user review.

Extraction criteria (ALL must be true):
1. Appears in 2+ skills (not skill-specific knowledge)
2. Actionable behavior change ("do X" / "don't do Y")
3. Clear violation risk (what breaks if ignored — 1 sentence)
4. Not already in rules (even with different wording)

Verdict types: Append | Revise | New Section | New File | Already Covered | Too Specific

**Gap in Clade**: Our correction rules (from correction-detector.sh) are per-session captures. No mechanism to cross-read skills and distill principles that appear in multiple places.

### 3.6 Hook `id` Fields — Selective Enable/Disable

Every ECC hook has an `id` field:
```json
{
  "matcher": "Bash",
  "hooks": [{"type": "command", "command": "npx block-no-verify@1.1.2"}],
  "id": "pre:bash:block-no-verify"
}
```

**Novel hooks in ECC**:
| Hook ID | Purpose |
|---------|---------|
| `pre:bash:block-no-verify` | Block `--no-verify` git flag (defense in depth) |
| `pre:bash:auto-tmux-dev` | Auto-start dev servers in named tmux sessions |
| `pre:bash:commit-quality` | Quality check before git commit |
| `pre:write:doc-file-warning` | Warn on .md file writes (docs creep prevention) |
| `pre:edit-write:suggest-compact` | Suggest compact after N tool calls (strategic) |
| `pre:observe:continuous-learning` | Capture learning events pre-tool |
| `pre:mcp-health-check` | Verify MCP servers healthy before any tool call |
| `pre:governance-capture` | Capture governance/rules-relevant events |
| `pre:config-protection` | Block edits to linter configs |

**Gap in Clade**: Our `settings-hooks.json` has no `id` fields, no `description` fields. Hooks can't be selectively disabled without removing the entire block. Also missing: config protection hook (critical for code quality).

### 3.7 Hookify Rules DSL

A YAML-frontmatter rule format for creating hook behavior without writing shell scripts:

```markdown
---
name: warn-env-api-keys
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.env$
  - field: new_text
    operator: contains
    pattern: API_KEY
---
You're adding an API key to a .env file. Ensure this file is in .gitignore!
```

Operators: `regex_match | contains | equals | not_contains | starts_with | ends_with`

**Gap in Clade**: Our hooks are all bash scripts. A declarative rule format would let non-engineers add hook rules without writing shell code.

### 3.8 Autonomous Agent Harness Architecture

Replacing standalone frameworks with native Claude Code:

```
Hermes/AutoGPT        → ECC Equivalent
─────────────────────────────────────────
Gateway/Router        → Crons + dispatch
Memory System         → ~/.claude/projects/*/memory/ + MCP memory server
Tool Registry         → MCP servers
Orchestration         → Skills + Agents
Computer Use          → computer-use MCP
Task Queue            → TodoWrite + memory files
```

Key cron patterns for autonomous operation:
```
0 9 * * 1-5    daily standup (review PRs, issues, deploys)
0 * * * *      hourly monitoring (error rates, health)
0 2 * * *      nightly build + security scan
*/30 * * * *   continuous monitoring
0 10 * * 1     weekly quality metrics
```

### 3.9 Structured Observation Contract

Every tool response should return:
```json
{
  "status": "success|warning|error",
  "summary": "one-line result",
  "next_actions": ["..."],
  "artifacts": ["file paths / IDs"]
}
```

Every error path must include:
- Root cause hint
- Safe retry instruction
- Explicit stop condition

**Gap in Clade**: Worker output is unstructured text. We scrape raw output for commit hashes, test results, etc. A structured observation contract would make failure injection (reflection retries) more reliable and reduce false positives.

---

## Gap Summary for Clade

| Gap | Source | Priority | Effort | BRAINSTORM |
|-----|--------|----------|--------|------------|
| Explicit `transition_reason` in worker state | learn-cc s00a | High | Small | Added |
| `persist_large_output()` pattern (disk offload) | learn-cc s06 | Medium | Small | Added |
| `micro_compact()` — replace old tool results | learn-cc s06 | Medium | Small | Added |
| `recent_files` tracking for post-compact re-read | learn-cc s06 | Low | Small | Added |
| DreamConsolidator for memory pruning | learn-cc s09 | Medium | Medium | Added |
| Bidirectional dep clearing on task complete | learn-cc s12 | Medium | Small | Added |
| Identity re-injection after compaction | learn-cc s17 | Medium | Small | Added |
| EventBus JSONL for worker lifecycle observability | learn-cc s18 | Medium | Medium | Added |
| Linter config protection hook | ECC Plankton | High | Small | Added |
| Phase-boundary compact trigger | ECC strategic-compact | High | Medium | Added |
| Context budget audit before worker spawn | ECC context-budget | Medium | Medium | Added |
| Pass@k tracking across retries | ECC eval-harness | Medium | Medium | Added |
| Hook `id` + `description` fields | ECC | Low | Trivial | Added |
| Hookify-style declarative rule DSL | ECC | Low | Large | Noted |
| Structured observation contract for tool output | ECC | Medium | Large | Added |
