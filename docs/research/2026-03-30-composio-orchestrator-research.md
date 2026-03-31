---
name: 2026-03-30-composio-orchestrator-research.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "Composio: 7 plugin slots, CI reaction system, activity detection, review comment fingerprinting"
integrated_items:
  - "Plugin slot architecture — not implemented (Clade uses flat worker pool)"
needs_work_items:
  - "Reaction system for GitHub PR review tracking — could enhance github_sync.py"
  - "Activity detection via Claude JSONL — could enhance worker.py"
reference_items:
  - "Flat metadata files vs SQLite for state"
  - "Batch GraphQL optimization"
---

# ComposioHQ/agent-orchestrator — Deep Research

**Date**: 2026-03-30
**Source**: https://github.com/ComposioHQ/agent-orchestrator
**Stats**: 5,617 stars · 40k+ lines TypeScript · 3,288 tests · MIT license

---

## 1. What It Is

A production-grade **agent fleet manager** that wraps any AI coding CLI (Claude Code, Codex, Aider, OpenCode) in a unified orchestration layer. Its core value: you point it at GitHub issues, it spawns parallel agents in isolated git worktrees, polls CI/PR state, and automatically routes CI failures and review comments back to the correct agent — all without human intervention until merge-ready.

```
ao start https://github.com/your-org/your-repo
→ opens http://localhost:3000 (Kanban dashboard)
→ ao spawn INT-1234  (agent takes it from here)
```

The project was written primarily by its own agent fleet, making it a proof-of-concept of the model it implements.

---

## 2. Eight Plugin Slots

Defined in `packages/core/src/types.ts` with the comment:

```
Architecture: 8 plugin slots + core services
  1. Runtime    — where sessions execute (tmux, docker, k8s, process)
  2. Agent      — AI coding tool (claude-code, codex, aider)
  3. Workspace  — code isolation (worktree, clone)
  4. Tracker    — issue tracking (github, linear, jira)
  5. SCM        — source platform + PR/CI/reviews (github, gitlab)
  6. Notifier   — push notifications (desktop, slack, webhook)
  7. Terminal   — human interaction UI (iterm2, web, none)
  8. Lifecycle Manager (core, not pluggable)
```

Note: only 7 are truly swappable (`PluginSlot` type). The Lifecycle Manager is the core state machine, not a plugin.

### Plugin Contract

Every plugin exports a `PluginModule<T>`:

```typescript
interface PluginModule<T = unknown> {
  manifest: PluginManifest;       // name, slot, description, version
  create(config?: Record<string, unknown>): T;
  detect?(): boolean;             // optional: is this plugin's binary available?
}
```

The plugin registry loads them by slot+name key (`"runtime:tmux"`, `"agent:claude-code"`, etc.) and instantiates via `create()`.

---

### Slot 1: Runtime

**Interface**: `Runtime`

```typescript
interface Runtime {
  name: string;
  create(config: RuntimeCreateConfig): Promise<RuntimeHandle>;
  destroy(handle: RuntimeHandle): Promise<void>;
  sendMessage(handle: RuntimeHandle, message: string): Promise<void>;
  getOutput(handle: RuntimeHandle, lines?: number): Promise<string>;
  isAlive(handle: RuntimeHandle): Promise<boolean>;
  getMetrics?(handle: RuntimeHandle): Promise<RuntimeMetrics>;
  getAttachInfo?(handle: RuntimeHandle): Promise<AttachInfo>;
}
```

**Implementations**: `tmux` (default), `process`, `docker`, `k8s`, `ssh`, `e2b`

**Key design**: `RuntimeHandle` is an opaque object `{ id: string, runtimeName: string, data: Record<string, unknown> }` — serialized to metadata so sessions survive restarts. The tmux implementation uses globally unique session names (`{hash}-{prefix}-N`) to prevent collisions across multiple orchestrator instances.

---

### Slot 2: Agent

**Interface**: `Agent`

```typescript
interface Agent {
  name: string;
  processName: string;           // e.g. "claude", "codex"
  promptDelivery?: "inline" | "post-launch";

  getLaunchCommand(config: AgentLaunchConfig): string;
  getEnvironment(config: AgentLaunchConfig): Record<string, string>;
  detectActivity(terminalOutput: string): ActivityState;  // deprecated
  getActivityState(session: Session, readyThresholdMs?: number): Promise<ActivityDetection | null>;
  isProcessRunning(handle: RuntimeHandle): Promise<boolean>;
  getSessionInfo(session: Session): Promise<AgentSessionInfo | null>;

  // Optional:
  getRestoreCommand?(session: Session, project: ProjectConfig): Promise<string | null>;
  postLaunchSetup?(session: Session): Promise<void>;
  setupWorkspaceHooks?(workspacePath: string, config: WorkspaceHooksConfig): Promise<void>;
}
```

**Activity detection evolution**: originally terminal-scraping (`detectActivity` reads last few lines, looks for `❯` prompt). Now replaced by `getActivityState` which reads the agent's native files directly:
- **Claude Code**: reads last entry of `.jsonl` session file in `~/.claude/projects/{encoded-path}/`
- Last JSONL type `tool_use`/`user` → "active"; `assistant`/`summary` → "ready"; `permission_request` → "waiting_input"; `error` → "blocked"

**`promptDelivery: "post-launch"`** (used by claude-code): prompt is sent via `runtime.sendMessage()` after launch, because using `-p` flag causes one-shot exit behavior.

---

### Slot 3: Workspace

**Interface**: `Workspace`

```typescript
interface Workspace {
  name: string;
  create(config: WorkspaceCreateConfig): Promise<WorkspaceInfo>;
  destroy(workspacePath: string): Promise<void>;
  list(projectId: string): Promise<WorkspaceInfo[]>;
  postCreate?(info: WorkspaceInfo, project: ProjectConfig): Promise<void>;
  exists?(workspacePath: string): Promise<boolean>;
  restore?(config: WorkspaceCreateConfig, workspacePath: string): Promise<WorkspaceInfo>;
}
```

**Implementations**: `worktree` (default, uses `git worktree add`), `clone` (full clone)

See Section 4 for worktree management details.

---

### Slot 4: Tracker

**Interface**: `Tracker`

```typescript
interface Tracker {
  name: string;
  getIssue(identifier: string, project: ProjectConfig): Promise<Issue>;
  isCompleted(identifier: string, project: ProjectConfig): Promise<boolean>;
  issueUrl(identifier: string, project: ProjectConfig): string;
  branchName(identifier: string, project: ProjectConfig): string;
  generatePrompt(identifier: string, project: ProjectConfig): Promise<string>;

  // Optional:
  listIssues?(filters: IssueFilters, project: ProjectConfig): Promise<Issue[]>;
  updateIssue?(identifier: string, update: IssueUpdate, project: ProjectConfig): Promise<void>;
  createIssue?(input: CreateIssueInput, project: ProjectConfig): Promise<Issue>;
}
```

**Implementations**: `github` (issues), `linear`, `gitlab`

The key method is `generatePrompt` — it fetches the full issue description and formats it for injection into the agent's initial prompt.

---

### Slot 5: SCM (richest interface)

**Interface**: `SCM`

```typescript
interface SCM {
  name: string;
  detectPR(session: Session, project: ProjectConfig): Promise<PRInfo | null>;
  getPRState(pr: PRInfo): Promise<PRState>;
  getCIChecks(pr: PRInfo): Promise<CICheck[]>;
  getCISummary(pr: PRInfo): Promise<CIStatus>;
  getReviews(pr: PRInfo): Promise<Review[]>;
  getReviewDecision(pr: PRInfo): Promise<ReviewDecision>;
  getPendingComments(pr: PRInfo): Promise<ReviewComment[]>;
  getAutomatedComments(pr: PRInfo): Promise<AutomatedComment[]>;
  getMergeability(pr: PRInfo): Promise<MergeReadiness>;
  mergePR(pr: PRInfo, method?: MergeMethod): Promise<void>;
  closePR(pr: PRInfo): Promise<void>;

  // Optimization: batch fetch for N sessions in 1 GraphQL query
  enrichSessionsPRBatch?(prs: PRInfo[], observer?: BatchObserver): Promise<Map<string, PREnrichmentData>>;

  // Webhooks:
  verifyWebhook?(request: SCMWebhookRequest, ...): Promise<SCMWebhookVerificationResult>;
  parseWebhook?(request: SCMWebhookRequest, ...): Promise<SCMWebhookEvent | null>;
}
```

**Implementations**: `github` (uses GraphQL batch), `gitlab`

**`enrichSessionsPRBatch`** is the key optimization: instead of N×3 API calls per poll cycle (state + CI + reviews per session), one GraphQL query fetches all PRs in one shot. The lifecycle manager calls this at the start of each `pollAll()` to populate a per-cycle cache.

---

### Slot 6: Notifier

**Interface**: `Notifier`

```typescript
interface Notifier {
  name: string;
  notify(event: OrchestratorEvent): Promise<void>;
  notifyWithActions?(event: OrchestratorEvent, actions: NotifyAction[]): Promise<void>;
  post?(message: string, context?: NotifyContext): Promise<string | null>;
}
```

**Implementations**: `desktop` (macOS/Linux notifications), `slack`, `discord`, `webhook`, `openclaw`, `composio`

**Routing**: events are routed by priority (`urgent` / `action` / `warning` / `info`) via `notificationRouting` config:

```yaml
notificationRouting:
  urgent: [desktop, slack]   # stuck, needs_input, errored
  action: [desktop, slack]   # PR ready to merge
  warning: [slack]           # auto-fix failed
  info: [slack]              # summary, all done
```

---

### Slot 7: Terminal

**Interface**: `Terminal`

```typescript
interface Terminal {
  name: string;
  openSession(session: Session): Promise<void>;
  openAll(sessions: Session[]): Promise<void>;
  isSessionOpen?(session: Session): Promise<boolean>;
}
```

**Implementations**: `iterm2` (opens tmux tab in iTerm2), `web` (browser-based xterm.js terminal over WebSocket)

---

## 3. CI Feedback Closed Loop

### Architecture

The CI feedback loop is entirely event-driven, not poll-triggered. Here is the exact flow:

```
CI fails on GitHub
    → webhook arrives (or poll detects ci_failed)
    → lifecycle manager detects status transition: pr_open → ci_failed
    → looks up reaction config for "ci-failed"
    → executeReaction() called
    → action: "send-to-agent"
    → sessionManager.send(sessionId, message)
    → runtime.sendMessage(handle, message)
    → agent receives text in its terminal/stdin
```

### Default CI Reaction Config

```typescript
"ci-failed": {
  auto: true,
  action: "send-to-agent",
  message: "CI is failing on your PR. Run `gh pr checks` to see the failures, fix them, and push.",
  retries: 2,
  escalateAfter: 2,
}
```

The message tells the agent **how to fetch the logs itself** (`gh pr checks`) rather than injecting the raw log. The agent then runs `gh pr checks` and `gh run view --log-failed` to get the actual failure output.

### "One Retry" Enforcement: ReactionTracker

```typescript
interface ReactionTracker {
  attempts: number;
  firstTriggered: Date;
}
// Key: "sessionId:reactionKey", e.g. "app-3:ci-failed"
const reactionTrackers = new Map<string, ReactionTracker>();
```

Logic in `executeReaction()`:

```typescript
tracker.attempts++;
const maxRetries = reactionConfig.retries ?? Infinity;
const escalateAfter = reactionConfig.escalateAfter;

// Number-based: escalate after N attempts
if (tracker.attempts > maxRetries) shouldEscalate = true;

// Duration-based: escalate after X minutes
if (typeof escalateAfter === "string") {
  const durationMs = parseDuration(escalateAfter); // "30m" → 1800000
  if (Date.now() - tracker.firstTriggered > durationMs) shouldEscalate = true;
}

if (shouldEscalate) {
  // Send urgent notification to human instead
  await notifyHuman(event, "urgent");
  return { escalated: true };
}

// Otherwise: send to agent
await sessionManager.send(sessionId, message);
```

**Tracker reset**: when the session transitions to a new state (e.g. ci_failed → pr_open after the fix), `clearReactionTracker(sessionId, "ci-failed")` is called, resetting the retry count. The same notification is treated as a new event on the next failure cycle.

### Review Comment Feedback Loop

Review comments use a **fingerprint deduplication** system to avoid re-sending the same comments:

```typescript
// Fingerprint = sorted concatenation of comment IDs
function makeFingerprint(ids: string[]): string {
  return [...ids].sort().join(",");
}

// If fingerprint changed (new comments), send to agent
// Track lastPendingReviewDispatchHash = fingerprint at last send
// Only re-send when new fingerprint !== lastDispatchHash
```

This prevents the agent from being spammed when:
- The agent already addressed comments (they get resolved)
- The same comment set exists after a push
- Polling runs multiple times before the agent responds

---

## 4. Worktree Management

### Creation

```typescript
// workspace-worktree plugin: packages/plugins/workspace-worktree/src/index.ts

async create(cfg: WorkspaceCreateConfig): Promise<WorkspaceInfo> {
  const worktreePath = join(worktreeBaseDir, cfg.projectId, cfg.sessionId);
  // ~/.worktrees/{projectId}/{sessionId}/

  // 1. Fetch from origin
  await git(repoPath, "fetch", "origin", "--quiet");

  // 2. Resolve base ref (origin/main or local main)
  const baseRef = await resolveBaseRef(repoPath, cfg.project.defaultBranch);

  // 3. Create worktree with new branch
  await git(repoPath, "worktree", "add", "-b", cfg.branch, worktreePath, baseRef);
  // git worktree add -b feat/INT-1234 ~/.worktrees/myapp/app-1 origin/main
}
```

**Directory structure**:
```
~/.worktrees/
  my-app/
    app-1/    ← worktree for session app-1 on branch feat/INT-1234
    app-2/    ← worktree for session app-2 on branch feat/INT-5678
    ...
```

### Concurrent Access

No explicit mutex on worktree creation — relies on `git worktree add` being atomic at the OS level. Session ID reservation uses a **file-based atomic lock**:

```typescript
async function reserveNextSessionIdentity(project, sessionsDir) {
  // reserveSessionId() writes the metadata file atomically
  // getNextSessionNumber() scans existing files for highest N
  const sessionId = `${project.sessionPrefix}-${nextNum}`;
  await reserveSessionId(sessionsDir, sessionId);
  return { sessionId, tmuxName };
}
```

### Cleanup

```typescript
async destroy(workspacePath: string): Promise<void> {
  // Get the common git dir to find the repo root
  const gitCommonDir = await git(workspacePath, "rev-parse", "--path-format=absolute", "--git-common-dir");
  const repoPath = resolve(gitCommonDir, "..");

  // Remove the worktree (does NOT delete the branch — intentionally)
  await git(repoPath, "worktree", "remove", "--force", workspacePath);
}
```

Branches are deliberately not deleted — "stale branches can be cleaned up separately via `git branch --merged` or similar."

### postCreate Hooks

After worktree creation, the workspace plugin calls `postCreate()` which:
1. Symlinks shared resources (`.env`, `.claude`) from the main repo into the worktree
2. Runs `postCreate` shell commands (e.g. `pnpm install`)
3. Sets up the **metadata updater hook** in `.claude/settings.json`

---

## 5. Agent Adapter Layer

### How Claude Code Is Adapted

The claude-code plugin (`packages/plugins/agent-claude-code/src/index.ts`) injects a PostToolUse hook script (`metadata-updater.sh`) into the agent's `.claude/settings.json` in each worktree. This bash script intercepts every `Bash` tool call the agent makes and:

- Detects `gh pr create` → extracts PR URL → writes `pr=<url>` to metadata file
- Detects `git checkout -b` → writes `branch=<name>` to metadata
- Detects `gh pr merge` → writes `status=merged` to metadata

This solves the fundamental problem of **dashboard ↔ agent state sync** without requiring any API hooks or agent cooperation.

### Launch Command Differences

| Agent | Launch | Prompt Delivery | Notes |
|-------|--------|-----------------|-------|
| `claude-code` | `claude --dangerously-skip-permissions` | post-launch (sendMessage) | `-p` causes one-shot exit |
| `codex` | `codex ...` | inline | uses `--system-prompt` or AGENTS.md |
| `aider` | `aider ...` | inline | `--system-prompt` flag |
| `opencode` | `opencode` | post-launch | subagent selection via `--subagent` |

### Activity Detection Methods

| Method | Mechanism | Preferred? |
|--------|-----------|-----------|
| `getActivityState()` | reads agent's native files (JSONL, SQLite) | yes |
| `detectActivity()` | parses last N lines of terminal output | deprecated fallback |
| `isProcessRunning()` | `ps -eo pid,tty,args` with TTY matching | for exit detection |

The JSONL-based approach for Claude Code maps `lastType` in the final JSONL record:
- `tool_use` / `user` → `"active"`
- `assistant` / `summary` / `result` → `"ready"`
- `permission_request` → `"waiting_input"`
- `error` → `"blocked"`

The ps cache TTL (5s) prevents N concurrent `ps` calls when polling many sessions simultaneously.

---

## 6. Session State Machine

### Status States

```
spawning → working → pr_open → ci_failed → (back to working after fix)
                   ↓           ↓
                   → review_pending
                   → changes_requested → (back to pr_open after address)
                   → approved
                   → mergeable
                   → merged (terminal)

Also: needs_input, stuck, errored, killed, idle, done, terminated (terminal)
```

### Activity States (orthogonal to status)

```
active → agent is processing (thinking/writing)
ready  → agent finished its turn, waiting for input
idle   → inactive for > readyThresholdMs (default 5 min)
waiting_input → agent is asking a question / permission prompt
blocked → agent hit an error or is stuck
exited  → process is no longer running
```

### Lifecycle Polling Logic

`lifecycle-manager.ts` runs `pollAll()` every 30 seconds (configurable):

```
pollAll():
  1. List all non-terminal sessions
  2. Batch-fetch PR enrichment data via GraphQL (1 call for all PRs)
  3. For each session concurrently: checkSession(session)

checkSession(session):
  determineStatus() →
    1. Is runtime alive? → "killed"
    2. Agent activity via JSONL? → "needs_input" / "killed" / "stuck"
    3. Auto-detect PR by branch (for agents without hooks)?
    4. Check PR state from batch cache:
       - merged → "merged"
       - CI failing → "ci_failed"
       - changes_requested → "changes_requested"
       - approved + mergeable → "mergeable"
       - approved → "approved"
       - pending review → "review_pending"
       - otherwise → "pr_open"
    5. Stuck detection: idle beyond threshold?
    6. Default: "working"

  On status transition:
    → update metadata file
    → emit OrchestratorEvent
    → executeReaction() if reaction configured
    → notifyHuman() if no reaction handled it

  Review backlog dispatch (every poll, not just on transition):
    → fetch pending human comments
    → fingerprint check: new comments → send to agent
    → fetch automated bot comments
    → fingerprint check: new bot comments → send to agent
```

### Re-entrancy Guard

```typescript
let polling = false;
async function pollAll(): Promise<void> {
  if (polling) return; // skip if previous poll still running
  polling = true;
  try { ... }
  finally { polling = false; }
}
```

---

## 7. Notification System

### Event Types (27 total)

```
session.*:  spawned, working, exited, killed, idle, stuck, needs_input, errored
pr.*:       created, updated, merged, closed
ci.*:       passing, failing, fix_sent, fix_failed
review.*:   pending, approved, changes_requested, comments_sent, comments_unresolved
automated_review.*: found, fix_sent
merge.*:    ready, conflicts, completed
reaction.*: triggered, escalated
summary.*:  all_complete
```

### Priority Routing

```
urgent  → stuck, needs_input, errored, escalated
action  → approved, ready, merged, completed
warning → failed, changes_requested, conflicts
info    → summary, all done
```

Each priority maps to a list of notifiers via `notificationRouting` in config. Reactions short-circuit direct human notification — if a reaction handles the event (send-to-agent), no human notification is sent until escalation triggers.

---

## 8. Task Decomposition

### Architecture

`packages/core/src/decomposer.ts` — LLM-driven recursive decomposer:

```typescript
interface TaskNode {
  id: string;          // hierarchical: "1", "1.2", "1.2.3"
  depth: number;
  description: string;
  kind?: "atomic" | "composite";
  status: TaskStatus;
  lineage: string[];   // ancestor descriptions root→parent
  children: TaskNode[];
  issueId?: string;    // tracker issue created for this subtask
  sessionId?: string;  // AO session working on this task
}
```

### Two-Phase Process

**Phase 1: Plan (classify + decompose, no execution)**

```
For each task node (BFS, concurrent):
  1. If depth >= maxDepth → force "atomic"
  2. Call LLM with CLASSIFY_SYSTEM prompt → "atomic" or "composite"
  3. If atomic: mark ready, done
  4. If composite: call LLM with DECOMPOSE_SYSTEM → ["subtask1", "subtask2", ...]
  5. Create child nodes, recurse concurrently
```

**Phase 2: Approve + Execute**

```
if requireApproval: phase = "review"   (human sees plan, approves)
else:               phase = "approved" (auto-execute)
```

After approval, leaf nodes become GitHub issues, and each gets a spawned session.

### System Prompts

**CLASSIFY_SYSTEM** biases toward `atomic` (key heuristic: "at depth 2+, almost certainly atomic"):
```
- "atomic" = dev can implement directly without further planning
- "composite" = clearly contains 2+ independent concerns
- At depth 2 or deeper: almost certainly atomic
- When in doubt, choose atomic
```

**DECOMPOSE_SYSTEM**: minimum subtasks, no "test and polish" filler, no overlapping tasks, only real distinct work.

### Context Injection

Each agent's prompt receives its hierarchical context:
```
## Task Hierarchy
This task is part of a larger decomposed plan:
  0. Build authentication system
    1. Implement JWT token service        ← parent
      1.1. Write token generation code    ← (this task)

## Parallel Work
Sibling tasks being worked on in parallel:
  - Write token validation middleware  ← sibling
  - Write token refresh logic          ← sibling
```

This prevents agents from duplicating sibling work.

---

## 9. Full Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     agent-orchestrator (ao)                          │
│                                                                       │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │                    CLI + Web Dashboard                         │   │
│  │  ao start / ao spawn / ao status / ao send                    │   │
│  │  http://localhost:3000 (Next.js 15 + Kanban)                  │   │
│  └────────────────────────────┬──────────────────────────────────┘   │
│                               │                                       │
│  ┌────────────────────────────▼──────────────────────────────────┐   │
│  │                    Core Services                               │   │
│  │                                                               │   │
│  │  PluginRegistry ──── loads ──── 7 plugin slots               │   │
│  │                                                               │   │
│  │  SessionManager ─── spawn/kill/send/list ──── Session[]      │   │
│  │    └─ uses: Runtime + Agent + Workspace + Tracker             │   │
│  │                                                               │   │
│  │  LifecycleManager ─── 30s poll ──────────────────────────┐  │   │
│  │    └─ determineStatus()                                   │  │   │
│  │    └─ executeReaction()                                   │  │   │
│  │    └─ notifyHuman()                                       │  │   │
│  │    └─ maybeDispatchReviewBacklog()                        │  │   │
│  │                                                           │  │   │
│  │  Decomposer ──── LLM classify + decompose tree            │  │   │
│  └───────────────────────────────────────────────────────────┘  │   │
│                                                                   │   │
│  ┌────────────────────────────────────────────────────────────┐  │   │
│  │                    Plugin Slots                             │  │   │
│  │                                                            │  │   │
│  │  Runtime:    tmux | process | docker | k8s | ssh | e2b    │  │   │
│  │  Agent:      claude-code | codex | aider | opencode       │  │   │
│  │  Workspace:  worktree | clone                             │◄─┘   │
│  │  Tracker:    github | linear | gitlab                     │      │
│  │  SCM:        github (GraphQL batch) | gitlab              │      │
│  │  Notifier:   desktop | slack | discord | webhook | ...   │      │
│  │  Terminal:   iterm2 | web (xterm.js)                      │      │
│  └────────────────────────────────────────────────────────────┘      │
│                                                                       │
│  Storage: ~/.agent-orchestrator/{hash}-{projectId}/sessions/         │
│           ~/.worktrees/{projectId}/{sessionId}/  (git worktrees)     │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow for a Task

```
GitHub Issue "INT-1234"
    ↓  ao spawn INT-1234
Tracker.getIssue()  →  Issue{title, description}
    ↓
Workspace.create()  →  git worktree add -b feat/INT-1234 ~/.worktrees/app/app-1 origin/main
    ↓
Agent.setupWorkspaceHooks()  →  writes .claude/settings.json with metadata-updater.sh
    ↓
Runtime.create()  →  tmux new-session -d -s a3b4-app-1
    ↓
Runtime.sendMessage(handle, prompt)  →  [agent receives task]
    ↓
    ↓── (agent works, creates PR) ──────────────────────────┐
    ↓                                                        │
LifecycleManager polls every 30s:                           │
    Agent JSONL: last type = "result" → ready               │
    SCM batch: pr exists, CI passing → "pr_open"            │
    SCM batch: CI failing → "ci_failed"                     │
        ↓                                                    │
    Reaction "ci-failed":                                    │
    SessionManager.send(app-1, "CI failing. Run gh pr checks, fix, push.")
        ↓                                                    │
    [agent runs gh pr checks, fixes, pushes]                 │
        ↓                                                    │
    SCM batch: CI passing + approved → "mergeable"           │
    Notifier.notify(merge.ready, priority="action")          │
        ↓                                                    │
    Human merges PR (or auto-merge if configured)            │
    Status → "merged" (terminal)                            │
```

---

## 10. Comparison with Clade Orchestrator

### Structural Similarities

| Aspect | Clade | agent-orchestrator |
|--------|-------|--------------------|
| Agent runner | `subprocess` (Claude CLI) | Runtime plugin (tmux/process) |
| Task storage | SQLite (`tasks.db`) | Flat key=value metadata files |
| Worker isolation | git worktrees | git worktrees (workspace plugin) |
| CI handling | manual / oracle review | automated reactions → send-to-agent |
| Status tracking | `status` column in DB | metadata file + in-memory states map |
| Multiple projects | single project per instance | multi-project in one config |
| Dashboard | FastAPI + vanilla JS | Next.js 15 + Kanban |
| Loop / iteration | supervisor+worker loop pattern | LifecycleManager polling |
| Agent support | Claude Code only | Claude Code + Codex + Aider + OpenCode |

### Key Differences

**1. Plugin architecture vs monolith**
ao is fully plugin-based — every external dependency is a swappable interface. Clade hardcodes Claude Code as the only agent, tmux-like behavior via subprocess, and GitHub via `gh` CLI.

**2. Status as metadata file vs database**
ao stores session state in flat `key=value` files on disk (one file per session). These are written atomically and survive process restarts without any DB migration concerns. Clade uses SQLite which requires `ALTER TABLE` migrations for new fields.

**3. Reaction system vs fixed behavior**
ao's `ReactionConfig` is user-configurable per project: message content, retry count, escalation duration. Clade's CI handling is hardcoded in worker logic.

**4. CI log injection approach**
ao sends a message telling the agent to **fetch its own CI logs** (`gh pr checks`). Clade fetches logs server-side and injects them. ao's approach is simpler and avoids log truncation.

**5. Activity detection via native files**
ao reads Claude's JSONL session files directly to detect `waiting_input` vs `active` vs `ready`. Clade doesn't do this — it monitors subprocess stdout and process alive checks only.

**6. Batch GraphQL optimization**
ao batches all PR state/CI/review queries into a single GraphQL call per poll cycle. Clade makes individual `gh` CLI calls per task, which doesn't scale beyond ~10 concurrent workers.

**7. Multi-project support**
ao handles multiple repos in a single orchestrator instance with per-project plugin overrides. Clade is single-project.

---

## 11. Patterns Portable to Clade

### Pattern 1: Reaction System

Replace hardcoded CI handling with a configurable reaction table:

```python
REACTIONS = {
    "ci_failed": {
        "action": "send_to_agent",
        "message": "CI is failing. Run the failing tests and fix them.",
        "retries": 2,
        "escalate_after": 2,
    },
    "review_comments": {
        "action": "send_to_agent",
        "message": "Review comments on your PR. Address each one and push.",
        "escalate_after": "30m",
    },
}
```

Implement `ReactionTracker` with attempt counting and duration-based escalation. On escalation → notify human (Slack/webhook) instead of retrying.

### Pattern 2: Activity Detection via JSONL

Clade only knows if a worker is alive (process check). It doesn't distinguish `active` vs `waiting_input` vs `blocked`. Add:

```python
def get_claude_activity_state(workspace_path: str) -> ActivityState:
    project_path = workspace_path.lstrip('/').replace('/', '-').replace('.', '-')
    project_dir = Path.home() / ".claude" / "projects" / project_path
    jsonl_file = find_latest_jsonl(project_dir)
    last_entry = read_last_jsonl_entry(jsonl_file)
    match last_entry["type"]:
        case "tool_use" | "user": return "active"
        case "assistant" | "summary": return "ready"
        case "permission_request": return "waiting_input"
        case "error": return "blocked"
```

This would enable Clade to detect when Claude is waiting for permission and auto-approve or notify.

### Pattern 3: Review Comment Fingerprinting

Instead of always re-sending review feedback, fingerprint the comment set and only send on new comments:

```python
def fingerprint(comment_ids: list[str]) -> str:
    return ",".join(sorted(comment_ids))

# In task metadata:
last_review_fingerprint = task.metadata.get("last_review_fingerprint", "")
current_fingerprint = fingerprint([c["id"] for c in pending_comments])
if current_fingerprint != last_review_fingerprint:
    await send_to_agent(session, review_message)
    update_task_metadata(task_id, last_review_fingerprint=current_fingerprint)
```

### Pattern 4: Flat Metadata Files vs SQLite

For session state that must survive restarts and concurrent access: ao's approach of one-file-per-session (key=value) is more robust than SQLite for this use case — no migrations, no WAL lock contention, easy to inspect/debug. Clade's SQLite is fine for task descriptions and history, but runtime state could move to this pattern.

### Pattern 5: Prompt Layering

ao builds prompts in explicit layers:

```
1. BASE_AGENT_PROMPT (constant: git workflow, PR best practices)
2. Project context (repo, branch, issue details from tracker)
3. User rules (from agentRules / agentRulesFile in config)
4. Decomposition context (lineage + sibling tasks)
5. Additional instructions (user-provided override)
```

Clade could adopt this to make its prompt composition explicit and testable, rather than building prompt strings ad hoc in `worker.py`.

### Pattern 6: Batch Poll Optimization

When Clade has many concurrent workers, polling each for GitHub PR state individually is O(N) API calls per cycle. ao's `enrichSessionsPRBatch` reduces this to O(1) via GraphQL. For Clade with 10+ workers, implement:

```python
async def batch_poll_pr_states(prs: list[str]) -> dict[str, PRState]:
    # Single GraphQL query for all PRs
    # Returns {pr_url: {ci_status, review_decision, mergeable}}
```

### Pattern 7: Plugin Interface for Agent Swappability

If Clade wants to support agents beyond Claude Code (e.g., Codex for certain tasks), define a minimal `Agent` interface:

```python
class AgentPlugin(Protocol):
    name: str
    def get_launch_command(self, config: AgentConfig) -> str: ...
    def get_activity_state(self, session: Session) -> ActivityState: ...
    async def setup_workspace_hooks(self, workspace_path: str) -> None: ...
```

The hook-based metadata update approach (writing `.claude/settings.json` PostToolUse hook) is particularly valuable — it removes the need for server-side polling to detect PR creation.

---

## 12. Key Design Insights

1. **Reactions are the orchestrator's brain.** The entire CI/review loop is just `event → reaction → send_to_agent || notify_human`. This decoupling makes the behavior configurable without code changes.

2. **Agents fetch their own logs.** ao doesn't inject CI log content — it just tells the agent "CI is failing, run `gh pr checks` to see why." This is simpler and more reliable than server-side log extraction.

3. **Metadata files beat a database for session state.** One file per session = no migrations, no lock contention, easy atomic writes, survives crashes, easy grep for debugging.

4. **Native file introspection beats terminal scraping.** Reading Claude's JSONL session files is infinitely more reliable than regex-matching terminal output. Worth implementing in Clade.

5. **Fingerprinting prevents feedback storms.** Without fingerprinting, every poll cycle re-sends the same review comments. The `lastDispatchHash` pattern ensures exactly-once delivery.

6. **Batch GraphQL is a must at scale.** At 20 sessions, N×3 REST calls = 60 calls/cycle. One GraphQL batch = 1 call/cycle. Implement early before scale forces it.

7. **PostToolUse hooks are the cleanest integration point.** Rather than polling GitHub for PR state, ao hooks directly into the agent's tool use cycle. When the agent runs `gh pr create`, the hook captures the URL immediately and writes it to metadata.
