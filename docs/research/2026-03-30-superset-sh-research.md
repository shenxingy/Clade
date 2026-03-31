---
name: 2026-03-30-superset-sh-research.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "Superset: TerminalHost with Semaphore, headless xterm.js emulator, universal hook injection, notification server"
integrated_items:
  - "Universal hook installation — Clade uses install.sh (vs superset-sh settings.json merge)"
needs_work_items: []
reference_items:
  - "TerminalHost with Semaphore for session concurrency control"
  - "Headless xterm.js emulator — not applicable (Clade uses worktree subprocesses)"
  - "Notification server with Telegram/Slack integration — not implemented"
---

# superset-sh/superset — Deep Technical Research

**Repository**: https://github.com/superset-sh/superset (~8300 stars)
**Date**: 2026-03-30
**Context**: Clade Orchestrator UI direct competitor analysis

---

## Overview

Superset is a monorepo (~8300 stars) that orchestrates multiple CLI-based coding agents (Claude Code, Codex, Cursor, Gemini, OpenCode, etc.) in parallel using Electron for the desktop app and Next.js for the web UI. It uses git worktrees for agent isolation, a custom headless xterm.js emulator for terminal state persistence, and a universal hook injection system that patches each agent's native configuration to integrate with Superset's notification system.

**Key differentiator vs Clade**: Superset is a desktop-first application with deep OS integration (native notifications, PTY management, filesystem events), while Clade's orchestrator is a web-based FastAPI server with a React UI. Superset's terminal emulation is notably more sophisticated, with xterm.js state serialization and mode tracking.

---

## 1. Full Architecture (Electron Desktop App)

### 1.1 Process Architecture

The desktop app uses a standard Electron multi-process model with a main process, preload scripts, and a renderer process.

```
apps/desktop/
├── src/
│   ├── main/                    # Electron main process
│   │   ├── index.ts            # Main entry, app lifecycle
│   │   ├── terminal-host/      # PTY management, session handling
│   │   │   ├── terminal-host.ts    # TerminalHost class (session registry)
│   │   │   ├── session.ts          # Session class (PTY + emulator)
│   │   │   ├── headless-emulator.ts # xterm.js headless wrapper
│   │   │   ├── pty-subprocess.ts    # PTY subprocess IPC
│   │   │   └── pty-subprocess-ipc.ts # Frame encoding/decoding
│   │   ├── lib/
│   │   │   ├── agent-setup/   # Hook injection, wrapper scripts
│   │   │   ├── terminal/       # Terminal utilities
│   │   │   └── notifications/  # Notification server + manager
│   │   ├── host-service/      # Headless service layer
│   │   └── windows/           # Window management
│   ├── preload/               # Preload scripts (context bridge)
│   └── renderer/              # React UI
│       ├── components/        # React components
│       ├── stores/            # Zustand stores
│       └── hooks/            # React hooks
```

### 1.2 Terminal Host Architecture

The `TerminalHost` class (`apps/desktop/src/main/terminal-host/terminal-host.ts:55`) is the central manager for all PTY sessions:

```typescript
export class TerminalHost {
    private sessions: Map<string, Session> = new Map();
    private killTimers: Map<string, NodeJS.Timeout> = new Map();
    private pendingAttaches: Map<string, PendingAttach> = new Map();
    private spawnLimiter = new Semaphore(MAX_CONCURRENT_SPAWNS);
    private onUnattachedExit?: (event: {
        sessionId: string;
        exitCode: number;
        signal?: number;
    }) => void;
```

Key design:
- Sessions are identified by `sessionId` (UUID) and stored in a Map
- PTY spawning is controlled by a semaphore (max 3 concurrent spawns)
- Multiple renderer clients can attach to the same session (for concurrent viewing)
- Sessions survive pane switches via the snapshot mechanism
- Kill timers provide fail-safe cleanup if PTY doesn't exit within 5 seconds

### 1.3 Main Process Entrypoint

`apps/desktop/src/main/index.ts` handles:
- App lifecycle (ready, quit, activate)
- Window creation
- Host-service startup
- Agent hook setup via `setupAgentHooks()`
- Notification server startup
- tRPC router registration

### 1.4 IPC via tRPC

The desktop app uses tRPC for main ↔ renderer communication. Routers are defined in `apps/desktop/src/lib/trpc/routers/`:

- `workspaces/` — workspace CRUD, worktree management
- `terminal/` — terminal session management (createOrAttach, write, resize, detach, signal, kill, listSessions)
- `chat-runtime-service/` — chat/runtime integration
- `changes/` — git operations, diff viewing, staging
- `notifications.ts` — notification subscriptions via `observable()`
- `projects/` — project management
- `settings/` — settings management
- `browser/` — browser integration

Example from `notifications.ts`:
```typescript
export const createNotificationsRouter = () => {
    return router({
        subscribe: publicProcedure.subscription(() => {
            return observable<NotificationEvent>((emit) => {
                const onLifecycle = (data: AgentLifecycleEvent) => {
                    emit.next({ type: NOTIFICATION_EVENTS.AGENT_LIFECYCLE, data });
                };
                const onTerminalExit = (data: TerminalExitNotification) => {
                    emit.next({ type: NOTIFICATION_EVENTS.TERMINAL_EXIT, data });
                };
                notificationsEmitter.on(NOTIFICATION_EVENTS.AGENT_LIFECYCLE, onLifecycle);
                notificationsEmitter.on(NOTIFICATION_EVENTS.TERMINAL_EXIT, onTerminalExit);
                return () => {
                    notificationsEmitter.off(NOTIFICATION_EVENTS.AGENT_LIFECYCLE, onLifecycle);
                    notificationsEmitter.off(NOTIFICATION_EVENTS.TERMINAL_EXIT, onTerminalExit);
                };
            });
        }),
    });
};
```

---

## 2. Universal Hook Injection Mechanism

### 2.1 Overview

Superset injects hooks into each supported agent by modifying their native configuration files and creating wrapper scripts. The injection happens in `apps/desktop/src/main/lib/agent-setup/index.ts` via `setupAgentHooks()`.

### 2.2 Agent Wrapper System

Each agent has a wrapper script in `~/.superset/bin/` that:
1. Sets Superset-specific environment variables (`SUPERSET_HOME_DIR`, `SUPERSET_WORKSPACE_ID`, `SUPERSET_PANE_ID`, `SUPERSET_TAB_ID`, `SUPERSET_SESSION_ID`, etc.)
2. Forwards execution to the real agent binary
3. The notify script path is passed so agents can send lifecycle events

Wrapper creation uses `buildWrapperScript()` from `agent-wrappers-common.ts`:

```typescript
export function buildWrapperScript(binName: string, execLine: string): string {
    return dedent`
        # ${WRAPPER_MARKER}
        REAL_BIN="$(command -v "${binName}" 2>/dev/null || echo "${binName}")"
        export SUPERSET_HOME_DIR="${supersetDir}"
        export SUPERSET_TAB_ID="${tabId}"
        export SUPERSET_PANE_ID="${paneId}"
        export SUPERSET_WORKSPACE_ID="${workspaceId}"
        export SUPERSET_SESSION_ID="${sessionId}"
        ${execLine}
    `;
}
```

### 2.3 Claude Code Hook Injection

Claude Code uses `~/.claude/settings.json` for hooks. Superset merges its hook definitions into this file via `createClaudeSettingsJson()` in `agent-wrappers-claude-codex-opencode.ts:242`.

Hook events registered:
- `UserPromptSubmit` — when user submits a prompt
- `Stop` — when agent stops
- `PostToolUse` — after each tool use (with `matcher: "*"`)
- `PostToolUseFailure` — after tool use failure
- `PermissionRequest` — when agent requests permission

```typescript
const managedEvents: Array<{
    eventName: "UserPromptSubmit" | "Stop" | "PostToolUse" | "PostToolUseFailure" | "PermissionRequest";
    definition: ClaudeHookDefinition;
}> = [
    {
        eventName: "UserPromptSubmit",
        definition: {
            hooks: [{ type: "command", command: managedHookCommand }],
        },
    },
    {
        eventName: "Stop",
        definition: {
            hooks: [{ type: "command", command: managedHookCommand }],
        },
    },
    {
        eventName: "PostToolUse",
        definition: {
            matcher: "*",
            hooks: [{ type: "command", command: managedHookCommand }],
        },
    },
    // ... PostToolUseFailure, PermissionRequest
];
```

The hook command dynamically resolves the notify script path at runtime:
```typescript
export function getClaudeManagedHookCommand(): string {
    return `[ -n "$SUPERSET_HOME_DIR" ] && [ -x "$SUPERSET_HOME_DIR/${CLAUDE_DYNAMIC_NOTIFY_RELATIVE_PATH}" ] && "$SUPERSET_HOME_DIR/${CLAUDE_DYNAMIC_NOTIFY_RELATIVE_PATH}" || true`;
}
```

### 2.4 Codex Hook Injection

Codex uses `~/.codex/hooks.json`. Superset creates this file via `createCodexHooksJson()` with `SessionStart` and `Stop` hooks. The wrapper script (`~/.superset/bin/codex`) injects a notify script that intercepts Codex's session lifecycle callbacks.

### 2.5 OpenCode Plugin Injection

OpenCode uses a plugin system. Superset writes a JavaScript plugin file (`~/.superset/opencode-plugin/superset-notify.js`) and configures OpenCode to load it via `createOpenCodePlugin()`.

The plugin file template (`opencode-plugin.template.js`) hooks into OpenCode's lifecycle events and sends HTTP notifications to the desktop app.

### 2.6 Cursor Hook Injection

Cursor uses hook scripts. Superset creates:
- `~/.cursor/hooks/superset-hook.sh` — the hook script
- `~/.cursor/hooks.json` — hook configuration

The agent wrapper (`~/.superset/bin/cursor-agent`) sets environment variables and wraps cursor's agent command.

### 2.7 Gemini CLI Hook Injection

Gemini CLI has a settings JSON file. Superset creates:
- `~/.gemini-cli/hooks/superset-hook.sh` — hook script
- `~/.gemini-cli/settings.json` — hook configuration

### 2.8 Notify Script

The central notification mechanism is `notify.sh` (`apps/desktop/src/main/lib/agent-setup/templates/notify-hook.template.sh`):

```bash
#!/bin/bash
# Superset agent notification hook
curl -s "http://127.0.0.1:${DESKTOP_NOTIFICATIONS_PORT}/hook/complete" \
    -G --data-urlencode "paneId=${SUPERSET_PANE_ID}" \
    --data-urlencode "tabId=${SUPERSET_TAB_ID}" \
    --data-urlencode "workspaceId=${SUPERSET_WORKSPACE_ID}" \
    --data-urlencode "sessionId=${SUPERSET_SESSION_ID}" \
    --data-urlencode "eventType=${1:-Stop}" \
    --data-urlencode "hookSessionId=${SUPERSET_HOOK_SESSION_ID}" \
    --data-urlencode "env=${SUPERSET_ENV}" \
    --data-urlencode "version=${HOOK_PROTOCOL_VERSION}"
```

The notify script is installed to `~/.superset/hooks/notify.sh` with mode 0o755.

### 2.9 Notification Server

The desktop app runs an Express server on `DESKTOP_NOTIFICATIONS_PORT` (default 8743) to receive hook callbacks (`apps/desktop/src/main/lib/notifications/server.ts`):

```typescript
app.get("/hook/complete", (req, res) => {
    const { paneId, tabId, workspaceId, sessionId, hookSessionId, eventType, env, version } = req.query;

    // Environment mismatch detection prevents dev/prod cross-talk
    if (clientEnv && clientEnv !== SERVER_ENV) {
        console.warn(`[notifications] Environment mismatch: received ${clientEnv} request on ${SERVER_ENV} server.`);
        return res.json({ success: true, ignored: true, reason: "env_mismatch" });
    }

    const mappedEventType = mapEventType(eventType as string | undefined);
    const resolvedPaneId = resolvePaneId(
        paneId as string | undefined,
        tabId as string | undefined,
        workspaceId as string | undefined,
        sessionId as string | undefined,
    );

    const event: AgentLifecycleEvent = {
        paneId: resolvedPaneId,
        tabId: tabId as string | undefined,
        workspaceId: workspaceId as string | undefined,
        eventType: mappedEventType,
    };

    notificationsEmitter.emit(NOTIFICATION_EVENTS.AGENT_LIFECYCLE, event);
    res.json({ success: true, paneId: resolvedPaneId, tabId });
});
```

---

## 3. Server-Side Headless Terminal Emulator

### 3.1 HeadlessEmulator Class

Located in `apps/desktop/src/main/lib/terminal-host/headless-emulator.ts`, this class wraps `@xterm/headless` with mode tracking and snapshot generation.

Key features:
- Uses `@xterm/addon-serialize` for snapshot generation
- Tracks DECSET/DECRST modes (application cursor keys, mouse tracking, bracketed paste, etc.)
- Parses OSC-7 sequences for CWD tracking
- Generates rehydrate sequences to restore mode state on session restore

```typescript
const MODE_MAP: Record<number, keyof TerminalModes> = {
    1: "applicationCursorKeys",
    6: "originMode",
    7: "autoWrap",
    9: "mouseTrackingX10",
    25: "cursorVisible",
    47: "alternateScreen",      // Legacy alternate screen
    1000: "mouseTrackingNormal",
    1001: "mouseTrackingHighlight",
    1002: "mouseTrackingButtonEvent",
    1003: "mouseTrackingAnyEvent",
    1004: "focusReporting",
    1005: "mouseUtf8",
    1006: "mouseSgr",
    1049: "alternateScreen",    // Modern alternate screen with save/restore
    2004: "bracketedPaste",
};
```

### 3.2 Snapshot Mechanism

The `getSnapshot()` method returns a `TerminalSnapshot`:

```typescript
interface TerminalSnapshot {
    snapshotAnsi: string;           // Serialized xterm buffer with ANSI escape codes
    rehydrateSequences: string;     // DECSET/DECRST sequences to restore modes
    cwd: string | null;             // Current working directory from OSC-7
    modes: TerminalModes;            // Current terminal mode state
    cols: number;                   // Terminal columns
    rows: number;                  // Terminal rows
    scrollbackLines: number;        // Number of scrollback lines
    debug: {                        // Debug info for diagnostics
        xtermBufferType: string;
        hasAltScreenEntry: boolean;
        altBuffer?: { lines: number; nonEmptyLines: number; cursorX: number; cursorY: number };
        normalBufferLines: number;
    };
}
```

### 3.3 Session Class

The `Session` class (`apps/desktop/src/main/terminal-host/session.ts:129`) owns:
- A PTY subprocess (spawned via Electron's `process.execPath` running `pty-subprocess.js`)
- A `HeadlessEmulator` instance for state tracking
- A set of attached clients (renderer WebSocket connections)
- Output capture to disk

**Key design decisions:**

**Shell Readiness Detection:**
```typescript
type ShellReadyState = "pending" | "ready" | "timed_out" | "unsupported";

const SHELL_READY_MARKER = "\x1b[9999H\x1b[6n\x1b[9999H";
```
- zsh, bash, fish shells inject a ready marker via wrapper scripts
- The Session scans PTY output for this marker before enabling user input
- Pre-ready escape sequences (e.g., DA1/Dsr responses) are dropped to prevent appearing as typed text
- Timeout after 15 seconds falls back to unbuffered mode

**Backpressure Management:**
```typescript
const EMULATOR_WRITE_QUEUE_HIGH_WATERMARK_BYTES = 1_000_000;
const EMULATOR_WRITE_QUEUE_LOW_WATERMARK_BYTES = 250_000;
```
When the emulator write queue exceeds 1MB, PTY reading is paused until it drops below 250KB. This prevents unbounded memory growth from continuous terminal output like `tail -f`.

**Snapshot Boundary Tracking for Concurrent Attaches:**
When multiple renderer clients attach to the same session simultaneously, `flushToSnapshotBoundary()` ensures all data received BEFORE the attach call is included in the snapshot:

```typescript
private async flushToSnapshotBoundary(timeoutMs: number): Promise<boolean> {
    const targetProcessedItems = this.emulatorWriteProcessedItems + this.emulatorWriteQueue.length;
    const waiterId = this.nextSnapshotBoundaryWaiterId++;
    // Wait for boundary or timeout
}
```

### 3.4 PTY Subprocess IPC

The PTY runs as a separate Node.js process (`pty-subprocess.js`) to isolate blocking writes from the main daemon. Communication uses framed messages:

```typescript
enum PtySubprocessIpcType {
    Ready = 0,      // Subprocess is ready to receive spawn commands
    Spawn = 1,      // Request PTY spawn with config
    Spawned = 2,    // PTY spawned, payload = PID
    Write = 3,      // Write to PTY stdin
    Data = 4,       // PTY stdout data
    Resize = 5,     // Resize PTY
    Kill = 6,       // Kill PTY process
    Signal = 7,     // Send signal to PTY
    Exit = 8,       // PTY exited
    Error = 9,      // Error occurred
    Dispose = 10,   // Clean up
}
```

Frame format: 5-byte header (4 bytes length + 1 byte type) + payload

### 3.5 Terminal State Persistence Across Pane Switches

When a user switches panes:
1. The renderer disconnects from the current session's WebSocket
2. The Session remains alive with its PTY running
3. The renderer connects to the new pane's session
4. `attach()` is called, which:
   - Flushes pending emulator writes to a snapshot boundary
   - Calls `emulator.flush()` to ensure all data is written
   - Returns `emulator.getSnapshot()` for rendering
   - Client writes rehydrate sequences to restore xterm modes before displaying snapshot

This means terminal output is preserved across pane switches, and new clients see the full scrollback buffer.

---

## 4. Priority Semaphore for Concurrent Attach Limiting

### 4.1 Semaphore Implementation

Located in `apps/desktop/src/main/terminal-host/terminal-host.ts:437`:

```typescript
class Semaphore {
    private inUse = 0;
    private queue: Array<{
        resolve: (release: () => void) => void;
        reject: (error: Error) => void;
        signal?: AbortSignal;
        onAbort?: () => void;
    }> = [];

    constructor(private max: number) {}

    acquire(signal?: AbortSignal): Promise<() => void> {
        if (signal?.aborted) {
            return Promise.reject(new TerminalAttachCanceledError());
        }

        if (this.inUse < this.max) {
            this.inUse++;
            return Promise.resolve(() => this.release());
        }

        return new Promise<() => void>((resolve, reject) => {
            const waiter = { resolve, reject, signal, onAbort };
            if (signal) {
                waiter.onAbort = () => {
                    const index = this.queue.indexOf(waiter);
                    if (index !== -1) {
                        this.queue.splice(index, 1);
                        waiter.reject(new TerminalAttachCanceledError());
                    }
                };
                signal.addEventListener("abort", waiter.onAbort, { once: true });
            }
            this.queue.push(waiter);
        });
    }

    private release(): void {
        this.inUse = Math.max(0, this.inUse - 1);
        const next = this.queue.shift();
        if (next) {
            if (next.onAbort && next.signal) {
                next.signal.removeEventListener("abort", next.onAbort);
            }
            if (next.signal?.aborted) {
                next.reject(new TerminalAttachCanceledError());
                this.release(); // Try next in queue
                return;
            }
            this.inUse++;
            next.resolve(() => this.release());
        }
    }
}
```

### 4.2 Usage in TerminalHost

```typescript
const MAX_CONCURRENT_SPAWNS = 3;
// ...
async createOrAttach(socket: Socket, request: CreateOrAttachRequest): Promise<CreateOrAttachResponse> {
    // ...
    if (!session) {
        const releaseSpawn = await this.spawnLimiter.acquire(pendingAttach.abortController.signal);
        try {
            session = createSession(request);
            session.spawn({ cwd, cols, rows, env });
            await promiseWithTimeout(session.waitForReady(), SPAWN_READY_TIMEOUT_MS);
        } finally {
            releaseSpawnOnce();
        }
        // ...
    }
    // ...
}
```

The semaphore limits how many PTY processes can be spawning simultaneously. This prevents resource exhaustion when many workspaces are opened quickly.

### 4.3 Priority NOT Implemented

Note: The codebase does NOT implement priority-based queueing. All waiting acquire calls are FIFO. Priority would require a more sophisticated queue structure with priority levels.

---

## 5. Worktree Isolation Per Agent

### 5.1 Data Model

Superset uses a three-level data model (in `packages/local-db/src/schema/schema.ts`):

**Projects** — represents a git repository:
```typescript
export const projects = sqliteTable("projects", {
    id: text("id").primaryKey().$defaultFn(() => uuidv4()),
    mainRepoPath: text("main_repo_path").notNull(),   // Path to main git repo
    name: text("name").notNull(),
    color: text("color").notNull(),
    tabOrder: integer("tab_order"),
    lastOpenedAt: integer("last_opened_at").notNull().$defaultFn(() => Date.now()),
    defaultBranch: text("default_branch"),
    workspaceBaseBranch: text("workspace_base_branch"), // Base branch for new workspaces
    branchPrefixMode: text("branch_prefix_mode").$type<BranchPrefixMode>(),
    branchPrefixCustom: text("branch_prefix_custom"),
    worktreeBaseDir: text("worktree_base_dir"),         // Where worktrees are created
    githubOwner: text("github_owner"),
    // ...
});
```

**Worktrees** — represents a git worktree within a project:
```typescript
export const worktrees = sqliteTable("worktrees", {
    id: text("id").primaryKey().$defaultFn(() => uuidv4()),
    projectId: text("project_id").notNull().references(() => projects.id),
    path: text("path").notNull(),           // Filesystem path to worktree
    branch: text("branch").notNull(),       // Branch checked out in worktree
    baseBranch: text("base_branch"),        // Branch worktree was created from
    gitStatus: text("git_status", { mode: "json" }).$type<GitStatus>(),
    createdBySuperset: integer("created_by_superset", { mode: "boolean" }),
    // ...
});
```

**Workspaces** — represents an active workspace (UI concept):
```typescript
export const workspaces = sqliteTable("workspaces", {
    id: text("id").primaryKey().$defaultFn(() => uuidv4()),
    projectId: text("project_id").notNull().references(() => projects.id),
    worktreeId: text("worktree_id").references(() => worktrees.id), // null for branch type
    type: text("type").notNull().$type<WorkspaceType>(), // "worktree" | "branch"
    branch: text("branch").notNull(),
    name: text("name").notNull(),
    tabOrder: integer("tab_order").notNull(),
    sectionId: text("section_id").references(() => workspaceSections.id),
    portBase: integer("port_base"), // Allocated port range for dev instances
    // ...
});
```

### 5.2 Worktree Creation

Worktree creation happens in `apps/desktop/src/lib/trpc/routers/workspaces/procedures/create.ts`:

```typescript
async function handleNewWorktree({ project, prInfo, localBranchName, workspaceName }) {
    const worktreePath = resolveWorktreePath(project, branch);

    await createWorktreeFromPr({
        mainRepoPath: project.mainRepoPath,
        worktreePath,
        prInfo,
        localBranchName,
    });

    const worktree = localDb.insert(worktrees).values({
        projectId: project.id,
        path: worktreePath,
        branch: localBranchName,
        baseBranch: compareBaseBranch,
        gitStatus: null,
        createdBySuperset: true,
    }).returning().get();

    const workspace = createWorkspaceFromWorktree({
        projectId: project.id,
        worktreeId: worktree.id,
        branch: localBranchName,
        name: workspaceName,
    });

    workspaceInitManager.startJob(workspace.id, project.id);
    initializeWorkspaceWorktree({
        workspaceId: workspace.id,
        projectId: project.id,
        worktreeId: worktree.id,
        worktreePath,
        branch: localBranchName,
        mainRepoPath: project.mainRepoPath,
        useExistingBranch: true,
        skipWorktreeCreation: true,
    });
}
```

`createWorktreeFromPr` runs `git worktree add`:
```typescript
export async function createWorktreeFromPr({
    mainRepoPath,
    worktreePath,
    prInfo,
    localBranchName,
}: {
    mainRepoPath: string;
    worktreePath: string;
    prInfo: PullRequestInfo;
    localBranchName: string;
}): Promise<void> {
    await git(["worktree", "add", "-B", localBranchName, worktreePath, `origin/${prInfo.headRefName}`]);
}
```

### 5.3 Branch Name Generation

Branch names are auto-generated with configurable prefixes:

```typescript
export function generateBranchName({
    existingBranches,
    authorPrefix,
}: {
    existingBranches: string[];
    authorPrefix?: string;
}): string {
    const timestamp = new Date().toISOString().replace(/[:.]/g, "").slice(0, 12);
    const base = authorPrefix
        ? `${authorPrefix}/feature-${timestamp}`
        : `feature-${timestamp}`;
    // Ensure unique by appending -2, -3, etc. if needed
}
```

### 5.4 Setup/Teardown Scripts

Workspaces can have setup and teardown scripts defined in `.superset/config.json`:

```json
{
    "setup": ["./.superset/setup.sh"],
    "teardown": ["./.superset/teardown.sh"]
}
```

Environment variables available:
- `SUPERSET_WORKSPACE_NAME` — workspace name
- `SUPERSET_ROOT_PATH` — path to main repository

Setup scripts are loaded via `loadSetupConfig()` and executed after workspace initialization by `workspaceInitManager`.

### 5.5 External Worktree Import

Superset can import existing worktrees from disk that weren't created by Superset:

```typescript
const allExternalWorktrees = await listExternalWorktrees(project.mainRepoPath);
const externalWorktrees = allExternalWorktrees.filter(wt => {
    if (wt.path === project.mainRepoPath) return false;  // Main repo
    if (wt.isBare) return false;                         // Bare repos
    if (wt.isDetached) return false;                     // Detached HEAD
    if (!wt.branch) return false;                        // No branch
    if (trackedPaths.has(wt.path)) return false;         // Already tracked
    return true;
});
```

---

## 6. Web UI vs Desktop Architecture

### 6.1 Web App (app.superset.sh)

The web application (`apps/web/`) is a Next.js 16 application with:

**Structure:**
```
apps/web/src/app/
├── (agents)/           # Agent UI routes
│   ├── layout.tsx     # Agents layout with auth gating
│   ├── page.tsx       # Main agents page
│   ├── [sessionId]/   # Dynamic session pages
│   └── components/     # Agent-specific components
├── (auth)/            # Authentication routes
├── (dashboard-legacy)/ # Legacy dashboard
├── tasks/             # Task management pages
└── api/              # API routes
```

**Architecture:**
- Next.js 16 with React (no middleware.ts — uses `proxy.ts`)
- Server-side rendering for initial load
- tRPC for client-server communication
- Electric SQL for cloud Postgres → local SQLite sync
- Cloud backend (`apps/api/`) exposes tRPC routes

**Authentication:**
- Uses Clerk for authentication
- Organization-based access control via `getAgentsUiAccess()`

### 6.2 Desktop App Architecture

The Electron desktop app (`apps/desktop/`) has a fundamentally different architecture:

**Main Process:**
- Express server for hook notifications (`DESKTOP_NOTIFICATIONS_PORT` default 8743)
- tRPC router for renderer ↔ main IPC
- PTY management via node-pty
- SQLite local database (no cloud sync needed)
- Native OS notifications via `NotificationManager`

**Renderer Process:**
- React UI using `packages/pane-layout` for the workspace/terminal UI
- Zustand for state management
- Connects to main process via tRPC

**Key Packages:**
- `packages/pane-layout` — React pane management (split panes, tabs, workspace switching)
- `packages/desktop-mcp` — Desktop MCP server for browser automation
- `packages/host-service` — Headless service layer (terminal, filesystem events, chat runtime)
- `packages/local-db` — Drizzle ORM + SQLite for local data

### 6.3 Architecture Differences Summary

| Aspect | Web App | Desktop App |
|--------|---------|-------------|
| Terminal emulation | None (just displays output) | Full xterm.js with state persistence |
| Agent execution | Via cloud backend | Via local PTY + wrappers |
| Database | Cloud Postgres + local SQLite (Electric) | Local SQLite only |
| Hook injection | Not applicable | Full universal hook system |
| Notifications | Browser notifications | Native OS notifications |
| Workspaces | Multiplayer/shared | Per-machine local |
| PTY sessions | Not supported | Full PTY with shell wrappers |

### 6.4 Host Service Layer

The `host-service` package (`packages/host-service/src/app.ts`) provides a local HTTP server:

```typescript
export function createApp(options?: CreateAppOptions): CreateAppResult {
    const app = new Hono();
    const { injectWebSocket, upgradeWebSocket } = createNodeWebSocket({ app });

    registerWorkspaceFilesystemEventsRoute({ app, filesystem, upgradeWebSocket });
    registerWorkspaceTerminalRoute({ app, db, upgradeWebSocket });

    app.use("/trpc/*", trpcServer({
        router: appRouter,
        createContext: async (_opts, c) => {
            return {
                git,
                github,
                api,
                db,
                runtime,
                deviceClientId: options?.deviceClientId ?? null,
                deviceName: options?.deviceName ?? null,
                isAuthenticated,
            };
        },
    }));

    return { app, injectWebSocket };
}
```

Services managed:
- `ChatRuntimeManager` — Mastra runtime for integrated chat
- `WorkspaceFilesystemManager` — Filesystem event watching
- `PullRequestRuntimeManager` — GitHub PR operations

---

## 7. Notification/Diff Surfacing

### 7.1 Agent Lifecycle Events

Superset defines a set of `AgentLifecycleEvent` types in `shared/notification-types`:

```typescript
type AgentLifecycleEventType =
    | "Start"
    | "Stop"
    | "Error"
    | "PermissionRequest"
    | "Checkpoint";
```

### 7.2 Event Flow

1. Agent runs with Superset wrapper
2. Agent lifecycle event occurs (Stop, Error, PermissionRequest, etc.)
3. Wrapper calls `notify.sh` with event type
4. `notify.sh` sends HTTP GET to `localhost:8743/hook/complete`
5. Express server receives callback, emits `AgentLifecycleEvent`
6. `notificationsEmitter` broadcasts to all subscribers
7. `NotificationManager.handleAgentLifecycle()` shows native notification if needed

### 7.3 NotificationManager

Located in `apps/desktop/src/main/lib/notifications/notification-manager.ts`:

```typescript
export class NotificationManager {
    handleAgentLifecycle(event: AgentLifecycleEvent): void {
        if (event.eventType === "Start") return; // Don't notify on start
        if (!this.deps.isSupported()) return;

        if (this.shouldSuppressForVisiblePane(event)) return;

        const workspaceName = this.deps.getWorkspaceName(event.workspaceId);
        const title = this.deps.getNotificationTitle(event);

        const isPermissionRequest = event.eventType === "PermissionRequest";
        const notification = this.deps.createNotification({
            title: isPermissionRequest
                ? `Input Needed — ${workspaceName}`
                : `Agent Complete — ${workspaceName}`,
            body: isPermissionRequest
                ? `"${title}" needs your attention`
                : `"${title}" has finished its task`,
            silent: true,
        });

        const key = event.sessionId ?? event.paneId ?? `_anon_${this.counter++}`;
        this.track(key, notification);

        this.deps.playSound();
        notification.show();
    }
}
```

### 7.4 Visibility-Aware Suppression

Notifications are suppressed if the relevant pane is already visible:

```typescript
private shouldSuppressForVisiblePane(event: AgentLifecycleEvent): boolean {
    if (!event.workspaceId || !event.tabId || !event.paneId) return false;
    const ctx = this.deps.getVisibilityContext();
    if (!ctx.isFocused) return false;
    return isPaneVisible({
        currentWorkspaceId: ctx.currentWorkspaceId,
        tabsState: ctx.tabsState,
        pane: {
            workspaceId: event.workspaceId,
            tabId: event.tabId,
            paneId: event.paneId,
        },
    });
}
```

### 7.5 Notification TTL and Sweep

Notifications auto-expire after 10 minutes to prevent buildup:

```typescript
const NOTIFICATION_TTL_MS = 10 * 60 * 1000;
const SWEEP_INTERVAL_MS = 5 * 60 * 1000;

private sweep(): void {
    const now = Date.now();
    for (const [key, entry] of this.active) {
        if (now - entry.createdAt > NOTIFICATION_TTL_MS) {
            this.active.delete(key);
        }
    }
}
```

### 7.6 Diff Surfacing

Diff surfacing is handled through the `changes` tRPC router (`apps/desktop/src/lib/trpc/routers/changes/`):

- `git-operations.ts` — git diff, status, staging
- `branches.ts` — branch management
- `file-contents.ts` — read file contents for diff viewing
- `staging.ts` — git staging operations
- `workers/git-task-runner.ts` — background git task execution

The UI displays diffs in the renderer using a diff viewer component. Changes are tracked per-workspace via the git status stored in the worktree record.

---

## 8. Blueprint/Deterministic Patterns

### 8.1 Supervisor Loop

Superset does NOT have an explicit "Blueprint" supervisor loop like Clade's `/loop` command. Instead, it uses an event-driven model:

1. User creates workspace with a goal/task
2. Agent runs to completion (or until intervention needed)
3. Notification sent on agent Stop/Error/PermissionRequest
4. User reviews output, decides next action
5. User creates new workspace for next task or continues current one

### 8.2 Workspace Init Manager

For setup/teardown execution, Superset uses `workspaceInitManager`:

```typescript
workspaceInitManager.startJob(workspace.id, project.id);
```

This queues initialization jobs that run setup scripts, install dependencies, etc. Jobs are processed asynchronously after workspace creation.

### 8.3 ChatRuntimeManager

For the integrated chat experience, `ChatRuntimeManager` (`packages/host-service/src/runtime/chat/chat.ts`) manages Mastra runtimes per session:

```typescript
export class ChatRuntimeManager {
    private readonly runtimes = new Map<string, RuntimeSession>();
    private readonly runtimeCreations = new Map<string, Promise<RuntimeSession>>();

    private async createRuntime(sessionId: string, workspaceId: string): Promise<RuntimeSession> {
        const runtime = await createMastraCode({
            cwd,
            disableMcp: true,
        });
        runtime.hookManager?.setSessionId(sessionId);
        await runtime.harness.init();
        runtime.harness.setResourceId({ resourceId: sessionId });
        await runtime.harness.selectOrCreateThread();

        const sessionRuntime: RuntimeSession = {
            sessionId,
            workspaceId,
            cwd,
            harness: runtime.harness,
            mcpManager: runtime.mcpManager,
            hookManager: runtime.hookManager,
            lastErrorMessage: null,
            pendingSandboxQuestion: null,
        };
        return sessionRuntime;
    }
}
```

This uses Mastra (from mastracode) as the runtime harness for agent execution with thread management and model switching.

### 8.4 Deterministic Patterns Observed

- **Shell-ready marker** — deterministic detection of shell initialization completion via injected marker
- **Snapshot boundaries** — deterministic point-in-time captures for concurrent attaches using processed item counters
- **Hook protocol versioning** — forward compatibility via version checking in notification server
- **Post-checkout hook tolerance** — graceful handling of git hook failures (`isPostCheckoutHookFailure()`)
- **Branch name sanitization** — `sanitizeBranchNameWithMaxLength()` ensures branch names are valid git identifiers

---

## 9. Key Technical Insights

### 9.1 What Superset Does Well

1. **Terminal state persistence** — The xterm.js headless emulator with mode tracking and snapshot generation is sophisticated. Sessions survive pane switches with full state preservation including scrollback buffer.

2. **Universal hook injection** — The approach of modifying each agent's native config (settings.json, hooks.json) rather than wrapping the binary is clean and reliable. Hooks are idempotent and marker-based.

3. **Backpressure management** — The high/low watermarks for emulator write queues prevent memory exhaustion from continuous terminal output.

4. **Shell readiness detection** — The SHELL_READY_MARKER mechanism prevents user input from racing with shell initialization. The 15-second timeout provides graceful degradation.

5. **Local-first with cloud sync** — Using Electric SQL to sync Postgres → SQLite gives offline capability with cloud persistence.

6. **Concurrent attach handling** — Multiple renderer clients can attach to the same session with snapshot boundary guarantees.

### 9.2 Gaps Relative to Clade

1. **No autonomous loop** — Superset lacks a Blueprint-style deterministic supervisor loop. Each agent run is manual and user-driven.

2. **No task queue** — No concept of queued tasks with retries, dependencies, or priority scheduling.

3. **Desktop-only for full features** — The web app cannot run agents; it's just a remote viewer. Clade's FastAPI server is more capable as a standalone backend.

4. **No SWARM-style parallel orchestration** — Multiple agents can run but aren't orchestrated together toward a common goal.

5. **Single-user focus** — Desktop app is designed for single-user local use; multiplayer requires cloud infrastructure.

### 9.3 Potential Clade Improvements Inspired by Superset

1. **Shell-ready marker detection** — Similar mechanism for detecting when an LLM subprocess is ready to accept input, replacing fixed sleep durations.

2. **Headless terminal emulator** — Consider adopting xterm.js headless for terminal state tracking and snapshot generation for better interactive session support.

3. **Priority semaphore** — Implement priority-based concurrent attach limiting for parallel task execution with queue management.

4. **Hook injection for Claude Code** — Similar direct merge into `~/.claude/settings.json` rather than wrapper scripts for more reliable hook execution.

5. **Worktree isolation** — Leverage git worktrees more directly for agent isolation as Superset does.

6. **Notification deduplication** — Use sessionId/paneId based deduplication with TTL for notifications.

---

## 10. File Map

| File | Purpose |
|------|---------|
| `apps/desktop/src/main/terminal-host/terminal-host.ts` | TerminalHost class, session registry, semaphore |
| `apps/desktop/src/main/terminal-host/session.ts` | Session class, PTY management, shell readiness |
| `apps/desktop/src/main/terminal-host/headless-emulator.ts` | xterm.js headless wrapper, mode tracking |
| `apps/desktop/src/main/lib/agent-setup/index.ts` | setupAgentHooks() entry point |
| `apps/desktop/src/main/lib/agent-setup/agent-wrappers-claude-codex-opencode.ts` | Claude/Codex/OpenCode hook injection |
| `apps/desktop/src/main/lib/agent-setup/agent-wrappers-cursor.ts` | Cursor hook injection |
| `apps/desktop/src/main/lib/agent-setup/agent-wrappers-gemini.ts` | Gemini hook injection |
| `apps/desktop/src/main/lib/agent-setup/notify-hook.ts` | Notify script creation |
| `apps/desktop/src/main/lib/notifications/server.ts` | Express hook server |
| `apps/desktop/src/main/lib/notifications/notification-manager.ts` | Native notification management |
| `apps/desktop/src/lib/trpc/routers/workspaces/procedures/create.ts` | Worktree creation logic |
| `packages/local-db/src/schema/schema.ts` | Projects, worktrees, workspaces schema |
| `packages/host-service/src/app.ts` | Host service app factory |
| `packages/host-service/src/runtime/chat/chat.ts` | ChatRuntimeManager for Mastra |
| `packages/pane-layout/src/core/store/store.ts` | Zustand pane layout store |
| `packages/mcp/src/server.ts` | MCP server with tool call hooks |
