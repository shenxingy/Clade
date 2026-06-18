---
name: SST opencode — Peer Harness Deep-Dive
date: 2026-06-18
status: needs_work
review_date: 2026-06-18
reconciled: 2026-06-18
summary: >
  opencode (github.com/sst/opencode) is the most architecturally similar peer
  to Clade — a terminal coding agent built on an explicit client/server split
  (Hono server + Go TUI client, SSE event bus, SQLite/Drizzle session store).
  It is INTERACTIVE-first where Clade is AUTONOMOUS-first, which makes many of
  its headline features (Tab plan/build toggle, /share links, ask/once/always
  permission prompts, LSP diagnostics) different-not-deficient for Clade's
  unattended worker model. After grepping orchestrator/ + configs/, Clade
  already independently has: a FastAPI client/server split, SQLite session
  persistence, per-agent model/tools frontmatter, event-sourced worker state,
  and commit-level undo. Three genuine deltas survive scrutiny: single-provider
  lock-in (Claude-only vs 75+), no granular bash/edit permission layer (Clade
  skips all permissions by design — fine for trusted worktrees, a real gap for
  the supervisor's nested judge calls), and no OpenAPI/SDK generation off the
  FastAPI routes.
integrated_items:
  - "Client/server split — Clade has FastAPI server + WebSocket clients (orchestrator/server.py:18, server.py:145-535) independently of opencode's Hono+SSE design."
  - "SQLite session/task persistence with migrations (orchestrator/task_queue.py:44-196) parallels opencode's Drizzle/SQLite WAL store."
  - "Per-agent model + tools + maxTurns frontmatter (configs/agents/audit-budget.md:1-9) matches opencode's agent markdown frontmatter (model/temperature/permission/steps)."
  - "Event-sourced worker state — immutable action→observation log with causal cause_id (orchestrator/event_stream.py:2-117) parallels opencode's SSE bus + event store."
  - "Commit-level undo — _undo_commit / git reset HEAD~1 on failed gate (orchestrator/worker.py:905-959) is Clade's revert primitive."
  - "Model aliases resolve a friendly name to a dated snapshot (orchestrator/config.py:39-52), the same indirection as opencode's models record aliasing."
needs_work_items:
  - "Static command deny-list on nested judge `claude -p` spawns (🔵 DEFERRED low — defense-in-depth; judges are short read-only Haiku verifiers so risk is low, build deliberately)"
reference_items:
  - "Single-provider lock-in — SKIP different-by-scope: Clade is Claude-orchestration by design; FastAPI /docs already exposes the API — a generated client SDK is low-value for an autonomous tool"
  - "No generated SDK — SKIP different-by-scope: Clade is Claude-orchestration by design; FastAPI /docs already exposes the API — a generated client SDK is low-value for an autonomous tool"
  - "Tab plan/build agent toggle + /undo /redo message-level revert: INTERACTIVE-only — Clade workers are unattended, no human at a Tab key. Reference, not gap."
  - "/share + opncd.ai public conversation links: opencode's value is sharing an interactive human↔agent transcript. Clade's unit of work is a PR + event log, not a chat to show a colleague. Different artifact, not a deficit."
  - "LSP integration (30+ servers, diagnostics-as-feedback): opencode's own docs recommend documenting lint/typecheck commands over LSP ('servers get out of sync, use memory, slow workflows'). Clade already does exactly that via lint reflection (worker_utils.py:274-334, parse ruff/pylint output → retarget). Mechanism-equivalent, Clade picked the path opencode recommends."
  - "OpenCode Zen / Go managed model marketplace: a commercial billing service; out of scope for a single-user self-hosted harness."
  - "Hono framework + Effect/Zod config: implementation-language choices (TS/Bun). Clade is Python/FastAPI; no porting value."
---

[中文] | [Back to README](../../README.md)

# Research: SST opencode — Peer Harness Deep-Dive (2026-06-18)

opencode is the closest architectural peer to Clade among community harnesses:
a terminal coding agent built around an explicit **client/server split** with a
**session model**, **provider abstraction**, **permission system**, and **LSP**.
This dives into each subsystem and compares against verified Clade behavior
(grepped, not assumed). Core framing: **opencode is interactive-first, Clade is
autonomous-first** — that asymmetry decides most verdicts.

Sources: [GitHub](https://github.com/sst/opencode) ·
[Architecture overview (DeepWiki)](https://deepwiki.com/sst/opencode/1-overview) ·
[Session mgmt (DeepWiki)](https://deepwiki.com/sst/opencode/2.1-session-management) ·
[Provider/model config (DeepWiki)](https://deepwiki.com/sst/opencode/3.3-provider-and-model-configuration) ·
[Server docs](https://opencode.ai/docs/server/) ·
[Permissions docs](https://opencode.ai/docs/permissions/) ·
[Agents docs](https://opencode.ai/docs/agents/) ·
[LSP docs](https://opencode.ai/docs/lsp/) ·
[Share docs](https://opencode.ai/docs/share/)

---

## 1. Architecture: Client/Server Split

opencode runs a **headless Hono HTTP server** (`opencode serve`, default
`127.0.0.1:4096`). The TUI is a Go client; desktop (Electron/Solid), VS Code,
and web are alternate clients. All AI orchestration is server-side; clients talk
HTTP + **SSE** (`/event`, first frame `server.connected`, then bus events). The
server publishes **OpenAPI 3.1 at `/doc`**, which also generates the TS SDK.
Monorepo `packages/`: `opencode` (CLI+server), `@opencode-ai/sdk`,
`@opencode-ai/plugin`, plus frontends.

Core server pieces: `SessionPrompt.loop()` (agent loop), `Provider.getModel()`
(AI SDK), `Tool.execute()`, Drizzle ORM (state), Effect+Zod (config).

**Clade comparison — already has the split (independent convergence).**
Clade is *already* client/server: `orchestrator/server.py:18` imports
`FastAPI, WebSocket, WebSocketDisconnect`; `server.py:145-535` defines the REST
surface (`/api/sessions`, `/loop/start`, `/swarm/start`, `/interrupt`) and the
WebSocket pushes live status — the SSE-equivalent. The difference is *intent*:
opencode's clients are human UIs for one interactive session; Clade's "clients"
are a dashboard observing many autonomous workers. **Verdict: convergent, not a
gap.** The one missing piece is the **generated SDK** (see §7).

---

## 2. Session Model

opencode persists sessions in **SQLite via Drizzle + WAL** (`journal_mode=WAL`,
`busy_timeout=5000`, FK on). Each session: `SessionID`, `ProjectID`, title,
timestamps, token usage. Messages are ordered; each message holds **Parts**
(text / tool-call / reasoning) with **cursor-based pagination** for long
histories. Sessions support **parent↔child** (`parentID`) for subagents/forks,
and emit to a **global event bus** for UI sync. Lifecycle: create / list / get /
remove (cascading delete).

**Clade comparison — present, structured differently.**
Clade persists to SQLite with the same concurrency posture and migration style:
`task_queue.py:44-196` creates `tasks`, `commits`, `iteration_loops`,
`worker_messages`, `interventions`, `ideas`, with try/except `ALTER TABLE`
migrations in `_ensure_db()`. Clade's "session" is a `ProjectSession`
(`session.py:111`) registered in a `SessionRegistry` (`session.py:610`); its
durable unit is the **task + commit + event**, not a chat message with Parts.
Parent/child exists as task `depends_on` + swarm sub-workers rather than
`parentID` sessions. **Verdict: equivalent persistence, different granularity
(task-centric vs message-centric) — driven by autonomous vs interactive. Not a
gap.** opencode's **Parts** abstraction (typed message segments) is cleaner than
scraping raw worker stdout, but Clade's `event_stream.py` already gives typed
events; adopting Parts would duplicate that.

---

## 3. Provider Abstraction

opencode's spine: **provider-agnostic, 75+ providers** via the Vercel `ai` SDK +
**Models.dev** registry. Models are `providerID/modelID`; `Provider.getModel()`
returns a `LanguageModel`. Rich per-model metadata: `limit.context`,
`tool_call`, `reasoning`, `interleaved`, `cost` (in/out pricing). Auth chains
through env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), config, or the `Auth`
system; Bedrock gets `profile`/`region`/`endpoint`. Models filter via
`whitelist`/`blacklist`; aliases map new keys → existing model IDs.

**Clade comparison — GENUINE single-vendor lock-in.**
Verified: `config.py:39-52` `_MODEL_ALIASES` hardcodes exactly three Claude
snapshots (`haiku`/`sonnet`/`opus`). Grep for `OPENAI|bedrock|vertex|ollama|
base_url|provider_id` across `config.py worker.py` → **zero hits**. Every spawn
shells out to the literal `claude` binary (`session.py:253`, `worker.py`). Clade
has the *alias indirection* opencode has (friendly name → dated snapshot) but no
*provider* dimension. **Verdict: real deficit, but correctly low-priority** —
Clade is "Claude Code orchestration," the `claude` CLI *is* the substrate, and
the project name is literally about Claude. Worth a `base_url`/provider hook only
if Clade ever wants to drive an OpenAI-compatible CLI; until then this is
scoped-by-design. Logged as needs_work for honesty, not urgency.

---

## 4. Permissions

opencode resolves every tool action to **`allow` / `ask` / `deny`**, configured
per tool category (`bash`, `edit`, `read`, `webfetch`, `task`, `skill`, `lsp`,
`external_directory`, `doom_loop`, …). Granular **last-match-wins glob rules**:
`bash: {"*":"ask", "git *":"allow", "rm *":"deny"}`. Per-agent overrides in
frontmatter. `ask` → UI offers `once` / `always` / `reject` with a suggested
pattern. Sensible defaults: `.env` denied, `doom_loop` + `external_directory`
ask.

**Clade comparison — mostly different-by-design, one real seam.**
Verified: Clade passes `--dangerously-skip-permissions` at **26 call-sites**.
For **worker** spawns this is *correct* — workers run inside throwaway git
worktrees (`worker.py:239-276`, `git worktree add … -b branch`), and the whole
autonomous premise is no human at an `ask` prompt. opencode's `once/always/
reject` flow is meaningless without an interactive operator.

**But the same flag wraps the nested non-worker judge calls** — supervisor
(`session.py:253`), plan/build (`session.py:510`), horizontal decompose
(`session.py:713`), next-goals (`session.py:776`) — which run `claude -p` to
*parse JSON*, yet still inherit full unsandboxed `bash`/`edit`. These don't need
an interactive prompt, but they *could* benefit from opencode's **declarative
deny-list** (`bash: {"rm -rf *": deny, "curl *": deny}`) as static
defense-in-depth — a judge that's prompt-injected via repo content can't be
asked, but it *can* be statically blocked. **Verdict: the interactive
ask/once/always layer is different-not-deficient; a static command deny-list for
nested spawns is a genuine, autonomy-compatible gap.** Note Clade already
hardens these calls another way (pure-judge `SETTING_SOURCES_NONE`,
`config.py:53+`) — so this is hardening a partially-covered surface, not virgin
ground.

---

## 5. LSP Integration

opencode ships **30+ LSP servers** (pyright, gopls, rust-analyzer, tsserver…),
auto-started by file extension, feeding **diagnostics back to the agent** as
post-edit feedback. Notably, **opencode's own docs hedge**: LSP servers "get out
of sync, use significant memory, vary by version, and slow down agent
workflows," and recommend **documenting lint/typecheck commands in instruction
files** so the agent runs them directly. LSP is **disabled by default**.

**Clade comparison — Clade already took the path opencode recommends.**
Verified: zero `.py` files reference `lsp|pyright|gopls|diagnostic`. Instead,
`worker_utils.py:274-334` runs the linters directly (`ruff` preferred, `pylint`
fallback) on changed files and **parses the output** into `file:line: message`
retarget hints (`_extract_lint_targets`, regex at `worker_utils.py:266`) for a
reflection retry. That is mechanism-equivalent to "diagnostics as feedback" —
and it is precisely the run-the-command-yourself approach opencode steers users
toward over persistent LSP. **Verdict: reference, not gap.** A persistent LSP
would add cross-file *navigation* (go-to-def, find-refs) the lint loop lacks, but
that's an interactive-editor affordance, not an autonomous-loop need.

---

## 6. Session Sharing

`/share` syncs full conversation history to opencode servers and returns a
public `opncd.ai/s/<id>` link (no viewer auth). Modes: manual / auto / disabled;
enterprise can SSO-gate or self-host; `/unshare` deletes the data.

**Clade comparison — different artifact.**
Clade has no equivalent and grep confirms none. But the unit opencode shares is
an **interactive human↔agent chat transcript** — valuable to show a teammate
"how I prompted this." Clade's deliverable is a **PR + structured event log**
(`event_stream.py`) already visible on GitHub and the dashboard. The shareable
thing already exists in a more durable form. **Verdict: different-not-deficient.**
If anything, Clade could render an event-log permalink from the dashboard, but
that's a UI nicety, not a missing capability.

---

## 7. Agent Model & SDK

opencode: **primary** agents (build = all tools; plan = edits/bash default to
`ask`) vs **subagents** (general/explore/scout), defined in markdown frontmatter
(`mode`, `model`, `temperature`, `permission`, `steps`, `prompt`), invoked via
**Task tool** or **`@mention`**, switched with **Tab**.

**Clade comparison — agent defs match; SDK is the one real adjacent gap.**
Verified: `configs/agents/audit-budget.md:1-9` already uses frontmatter
`name/description/model: sonnet/maxTurns: 20/tools: Read, Write, Glob, Grep` —
structurally the same per-agent model+tools+step-budget contract. Clade lacks the
**Tab primary-agent toggle** (interactive-only) and the **`@mention`** summon
(Clade's Agent tool dispatch covers automatic invocation). The portable win is
opencode's **OpenAPI-3.1-at-`/doc` → generated SDK**: Clade's FastAPI gives
`/docs` for free but ships no client SDK, so external automation hand-rolls HTTP.
**Verdict: agent model convergent; generated SDK is a small genuine gap.**

---

## Verdict Summary

| Subsystem | opencode | Clade (verified) | Verdict |
|-----------|----------|------------------|---------|
| Client/server | Hono + SSE + Go TUI | FastAPI + WS (`server.py:18,145-535`) | Convergent |
| Session store | SQLite/Drizzle WAL, Parts | SQLite + migrations (`task_queue.py:44-196`) | Convergent (task vs msg) |
| Provider | 75+ via AI SDK/Models.dev | Claude-only (`config.py:39-52`) | **Gap (low-pri, scoped)** |
| Permissions | allow/ask/deny globs | skip-all (`--dangerously-skip-permissions` ×26) | Mostly by-design; **static deny-list for nested spawns = gap** |
| LSP | 30+ servers (docs hedge) | lint reflection (`worker_utils.py:274-334`) | Reference (Clade picked recommended path) |
| Sharing | `/share` public links | event log + PR | Different artifact |
| Agent defs | md frontmatter | md frontmatter (`agents/*.md:1-9`) | Convergent |
| SDK gen | OpenAPI 3.1 → TS SDK | `/docs` only, no SDK | **Gap (small)** |
| Undo | message-level `/undo` | commit-level `_undo_commit` (`worker.py:905-959`) | Convergent (coarser) |

**Bottom line:** opencode and Clade converged on the same skeleton (server +
SQLite sessions + per-agent frontmatter + event bus + undo) from opposite ends —
opencode building *out* from an interactive TUI, Clade building *out* from an
autonomous loop. Of opencode's headline features, four are interactive-only and
correctly different-not-deficient (Tab toggle, ask/once/always, `/share`, LSP
nav). Three genuine deltas survive: **(1)** single-provider lock-in (real but
scoped-by-design — Clade *is* Claude orchestration), **(2)** no static command
deny-list on nested judge spawns (autonomy-compatible defense-in-depth worth
adding), **(3)** no generated SDK off the FastAPI routes (small). None require
architectural change; (2) is the only one with a clear safety payoff.
