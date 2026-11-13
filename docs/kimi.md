**English only**（中文版尚未提供 — no Chinese version yet）

← Back to [README](../README.md)

# Kimi Code compatibility: hooks and skills

Clade's Kimi bridge runs the existing Claude hook scripts through
`configs/kimi-hooks/decision-to-kimi.sh`; it does not maintain a second copy of
their logic. This page records the protocol evidence and the disposition of
every command or prompt wired in `configs/settings-hooks.json`, the agents and
instructions Kimi is given ([Installed behavior](#installed-behavior)), then how
Kimi is given Clade's skills without being offered the ones it cannot run
([Skill view](#skill-view)).

The evidence below was read in the installed **Kimi Code 2.6.0** bundled
source, not inferred from Claude Code or from hook documentation. Where the two
runtimes differ, the 2.6.0 source is the authority for this matrix.

## Table of Contents

1. [Protocol evidence](#protocol-evidence)
2. [Port matrix](#port-matrix)
3. [Installed behavior](#installed-behavior)
4. [Subagents under `kimi -p`](#subagents-under-kimi--p)
5. [Attribution and verification](#attribution-and-verification)
6. [Skill view](#skill-view)

## Protocol evidence

Source labels used in the matrix are relative to `packages/agent-core-v2/src/`
in the 2.6.0 bundle:

| Label | Bundled source location |
|---|---|
| AH | `features/externalHooks/agent/agentExternalHooksService.ts` |
| SH | `features/externalHooks/session/sessionExternalHooksService.ts` |
| RH | `features/externalHooks/internal/runHook.ts` |
| MH | `features/externalHooks/internal/matchHooks.ts` |
| UH | `features/externalHooks/internal/userPrompt.ts` |
| HT | `features/externalHooks/internal/types.ts` and `features/externalHooks/configSection.ts` |
| Edit | `agent/tools/edit/edit.ts` (`EditInputSchema`) |
| Write | `agent/tools/os/write/writeTool.ts` and the adjacent `WriteInputSchema` |
| Bash | `agent/tools/os/bash/bash.ts` (`BashInputSchema`) |
| Lifecycle | `workspace/sessionLifecycle/sessionLifecycleService.ts` (`createSessionId`) |

- **Configuration.** `[[hooks]]` accepts only `event`, `matcher`, `command`, and
  `timeout`; timeout is 1–600 seconds and defaults to 30. There is no Claude
  `type: "prompt"`, `async`, or `asyncRewake` field (HT, `HookDefSchema`; RH,
  `DEFAULT_TIMEOUT_SECONDS`). Matchers are JavaScript regular expressions (MH,
  `matches$1`).
- **Input.** `runMatchedHooks` adds `hookEventName`, `sessionId`, and `cwd`, then
  `toHookInputData` converts keys to snake_case. Thus `hook_event_name` is
  present even though that literal does not appear in the bundle. Tool events
  also carry `tool_name`, `tool_input`, and `tool_call_id`; Stop carries
  `stop_hook_active` (MH; AH, `runPreToolUse` and `runStop`). No external-hook
  call site supplies `transcriptPath`, so the adapter adds
  `transcript_path: null`.
- **Prompt parts.** UserPromptSubmit sends `prompt` as an array produced by
  `input.map(fromCorePart)`, not as a string. Its matcher value is the text
  parts joined with spaces (AH, `runPromptSubmitHook`; MH,
  `matcherValueText`). The adapter joins text parts with newlines for the
  Claude hooks and ignores non-text parts.
- **Edit/Write paths.** Both schemas call the file argument `path`, not
  `file_path` (Edit; Write). The adapter preserves `path` and adds the Claude
  `file_path` alias. Bash already uses `command` (Bash).
- **Results.** Exit 2 blocks with stderr. Exit 0 plus
  `hookSpecificOutput.permissionDecision: "deny"` blocks with
  `permissionDecisionReason`; `message` at the top level or in
  `hookSpecificOutput` is the non-blocking message. Other exits fail open (RH,
  `resultFromExitCode` and `structuredOutput`). The Claude fields
  `additionalContext`, `systemMessage`, `updatedInput`, and
  `updatedPermissions` are not Kimi result fields in this bundle.
- **Where a message reaches the model.** UserPromptSubmit injects non-blocking
  messages in `<hook_result>` parts, using `message` or plain non-JSON stdout
  (UH, `renderUserPromptHookResult` and `userPromptHookMessage`). PreToolUse and
  Stop consume only a block reason (AH, `runPreToolUse` and `runStop`). Stop
  permits one continuation per turn (`stopHookContinuationUsed`). PostToolUse,
  PostToolUseFailure, PostCompact, PermissionRequest, and PermissionResult are
  fire-and-forget (AH, `fireAndForget`, `notifyPostToolUse`,
  `registerPermissionHooks`, and `notifyPostCompact`). SessionStart awaits the
  hooks but discards every result (SH, `triggerSessionStart`).
- **Session ids and events.** Kimi creates `session_<UUID>` ids (Lifecycle).
  SessionStart is not triggered for `fork` or `reclaimed`; compaction has
  separate PreCompact/PostCompact events rather than Claude's
  `SessionStart(source=compact)` path (SH, constructor; AH,
  `registerFullCompactionHooks`). Notification is declared in the event schema,
  but the 2.6.0 bundle contains no `trigger("Notification")`,
  `triggerBlock("Notification")`, or `fireAndForgetTrigger("Notification")`
  call site. TaskCompleted is not declared at all (HT).

## Port matrix

“Ported” keeps the Claude event. “Ported with adaptation” changes the event,
delivery, or persisted-attribution handling. “Not applicable” means the
runtime-specific feature is outside this portable set, not that the script is
intrinsically unable to run. All installed rows execute through the general
adapter, including its input normalization and result translation.

| # | Claude event | Claude matcher | Hook wiring | Kimi status | Reason and Kimi source |
|---:|---|---|---|---|---|
| 1 | SessionStart | `startup\|clear\|fork` | `session-baseline.sh` | **ported** | Data-only baseline needs no model channel. Kimi wiring uses `startup\|clear`: fork/reclaimed does not emit SessionStart (SH, constructor and `triggerSessionStart`). |
| 2 | SessionStart | `startup\|clear\|fork` | `session-context.sh` | **ported with adaptation** | SessionStart results are discarded (SH), so a once-per-session-id runtime sentinel delivers the same text on the first UserPromptSubmit, whose message is injected (UH). |
| 3 | SessionStart | `startup\|clear\|fork` | `memory-staleness.sh` | **not portable** | It requires a transcript path to find memory and SessionStart supplies no context channel. Kimi supplies neither (MH; SH). |
| 4 | SessionStart | `startup` | `sync-pull.sh` | **not applicable** | Claude dotfiles-store bootstrap and Claude project-memory adoption are outside this hook port. Only the write-triggered `memory-sync.sh` side is in scope. |
| 5 | SessionStart | `startup` | `sync-health.sh` | **not portable** | Its useful stdout findings are discarded with SessionStart results (SH); logging alone would not deliver the advertised context. |
| 6 | SessionStart | `startup` | `commit-archeology.sh` | **not portable** | Plain stdout has no SessionStart model channel (SH, `triggerSessionStart`). |
| 7 | SessionStart | `compact` | `post-compact-reinject.sh` | **not portable** | Kimi does not use SessionStart for compaction, and PostCompact output is fire-and-forget (SH; AH, `notifyPostCompact`). |
| 8 | SessionEnd | — | `session-end-cleanup.sh` | **ported** | SessionEnd awaits the hook and the cleanup needs only its filesystem side effect (SH, `triggerSessionEnd`). |
| 9 | PreToolUse | `Bash` | `pre-tool-guardian.sh` | **ported** | The legacy command string is retained. Deny and rewrite-refusal become Kimi blocks (AH, `runPreToolUse`; RH). Kimi has no PreToolUse advisory channel, so the guardian's non-blocking wait warning is not delivered. |
| 10 | PreToolUse | `Bash` | `revert-detector.sh` | **ported with adaptation** | Moved to PostToolUse/Bash. Kimi PreToolUse is synchronous, while PostToolUse is fire-and-forget: the data-only detector does not delay every Bash call and needs no output (AH, `runPreToolUse` and `notifyPostToolUse`). |
| 11 | PreToolUse | `Workflow` | `workflow-preflight.sh` | **not portable** | Kimi 2.6.0 has no registered Workflow tool (the bundle's `registerAgentToolService` names include Bash, Read, Edit, Write, Agent, and AskUserQuestion, but not Workflow). |
| 12 | PreToolUse | `Edit\|Write` | `linter-config-guard.sh` | **ported** | The adapter maps `tool_input.path` to `file_path`; deny is a Kimi block (Edit; Write; RH). |
| 13 | PreToolUse | `AskUserQuestion` | `ask-while-live.sh` | **not portable** | The tool exists and deny would work, but this guard fails open without Claude's transcript and process-record formats. Kimi supplies no `transcriptPath` (MH; AH). |
| 14 | PostToolUse | `Edit\|Write` | `post-edit-check.sh` | **not portable** | Its exit-2 findings depend on Claude `asyncRewake`; Kimi PostToolUse is fire-and-forget and has no wake channel (AH, `notifyPostToolUse`). |
| 15 | PostToolUse | `Edit\|Write` | `post-tool-use-lint.sh` | **not portable** | An exit-2 result on fire-and-forget PostToolUse cannot deliver the lint failure to the model (AH; RH). |
| 16 | PostToolUse | `Edit\|Write` | `rule-injector.sh` | **not portable** | Its only product is additional context, which PostToolUse never delivers (AH, `fireAndForget`). |
| 17 | PostToolUse | `Edit\|Write` | `edit-shadow-detector.sh` | **ported** | Fire-and-forget is the desired data-only behavior; the adapter supplies `file_path` from Kimi's `path` (AH; Edit; Write). |
| 18 | PostToolUse | `Edit\|Write` | `worker-checkpoint.sh` | **not applicable** | It is armed only by Clade's Claude worker environment (`CLADE_WORKER_SHADOW_DIR`), not by an interactive Kimi session. |
| 19 | PostToolUse | `Edit\|Write` | `memory-sync.sh` | **ported** | Sync is a filesystem side effect and needs no result channel; `path` is normalized (AH; Edit; Write). |
| 20 | PostToolUse | `Edit\|Write` | `doc-align-check.sh` | **not portable** | `systemMessage` is unsupported and fire-and-forget output reaches no model (AH; RH). |
| 21 | PostToolUse | `Edit\|Write` | `skill-suggest.sh` | **not portable** | Its additionalContext suggestion is discarded by PostToolUse (AH, `fireAndForget`). |
| 22 | PostToolUse | `Bash` | `failure-detector.sh` | **not portable** | Its debugging context is fire-and-forget. Kimi also supplies a string `tool_output`, not Claude's `tool_result` with an exit code (AH, `notifyPostToolUse`). |
| 23 | PostToolUse | `Bash` | `rule-injector.sh` | **not portable** | Same lost context channel as row 16 (AH, `fireAndForget`). |
| 24 | PostToolUse | `Bash` | `memory-sync.sh` | **ported** | The same data-only sync command is wired separately for Bash; event + matcher + command is therefore the idempotency key (AH). |
| 25 | PostToolUse | `Bash` | `worker-checkpoint.sh` | **not applicable** | Same Claude-worker-only arming environment as row 18. |
| 26 | PostToolUse | `*` | `mailbox-drain.sh` | **not portable** | AdditionalContext is discarded, and the orchestrator's Claude-worker mailbox environment is not a Kimi channel (AH). |
| 27 | PostToolUse | `*` | `context-warning-drain.sh` | **not portable** | AdditionalContext is discarded; draining the one-shot file would falsely claim delivery (AH). |
| 28 | Stop | — | `iloop-hook.sh` | **not portable** | An iterative loop cannot fit Kimi's single Stop continuation per turn, and the hook also requires Claude's transcript path (AH, `runStop`; MH). |
| 29 | Stop | — | `stop-completeness-check` (`type: prompt`) | **not portable** | Kimi's strict hook schema has command hooks only; there is no prompt hook field (HT, `HookDefSchema`). |
| 30 | Stop | — | `stop-check.sh` | **ported with adaptation** | Exit 2 becomes a Kimi block and the baseline is wired. One continuation per turn is compatible with the guard's circuit breaker (AH, `runStop`; RH). |
| 31 | PreCompact | — | `precompact-state-save` (`type: prompt`) | **not portable** | Prompt hooks are not representable in Kimi's `[[hooks]]` schema (HT). |
| 32 | PreCompact | — | `pre-compact.sh` | **not portable** | PreCompact awaits the script but ignores its output, and the companion post-compact context has no delivery channel (AH, `runPreCompact` and `notifyPostCompact`). |
| 33 | Notification | `permission_prompt\|idle_prompt` | `notify-telegram.sh` | **not portable** | Notification is schema-declared but has no producer call site in the 2.6.0 bundle; Claude's two matcher values are not emitted (HT; AH). |
| 34 | TaskCompleted | — | `verify-task-completed.sh` | **not portable** | Kimi declares TaskStarted, not TaskCompleted (HT, `HOOK_EVENT_TYPES`). |
| 35 | UserPromptSubmit | — | `correction-detector.sh` | **ported with adaptation** | Prompt parts become a string, additionalContext becomes Kimi `message`, and the history filter preserves the `session_` underscore (AH; UH; Lifecycle). |
| 36 | UserPromptSubmit | — | `prompt-tracker.sh` | **not applicable** | The same prompt/message adaptation could work, but this optional analytics hook is deliberately outside the requested correction-and-secret portable set; it is not wired. |
| 37 | UserPromptSubmit | — | `secret-scanner.sh` | **ported with adaptation** | Prompt parts become a string and the non-blocking credential note becomes Kimi `message` (AH; UH). |
| 38 | PostToolUseFailure | — | `post-tool-use-failure.sh` | **not portable** | Failure recovery hints are additionalContext on a fire-and-forget event (AH, `notifyPostToolUse`). |
| 39 | PermissionRequest | — | `permission-request.sh` | **not portable** | PermissionRequest is fire-and-forget, so it cannot auto-allow; Kimi also has no `updatedPermissions` result field (AH, `registerPermissionHooks`; RH). |

Totals: **7 ported, 5 ported with adaptation, 23 not portable, 4 not
applicable** — 39 wirings accounted for, with 12 installed entries.

## Installed behavior

`install.sh` §11c keeps one declarative `(event, matcher, hook, timeout)` list,
with a once-only mode for session context. It appends an entry only when the
exact event + matcher + command tuple is absent. This has three important
consequences:

- reinstalling does not duplicate entries;
- a user-written entry is never rewritten or removed;
- a machine holding only the original guardian command keeps that exact
  command and gains the other 11 entries, with no replacement or orphaned
  adapter command.

A missing `~/.kimi-code` or missing `config.toml` still means no Kimi
configuration is created. `revert-detector.sh` is deliberately on
PostToolUse/Bash rather than PreToolUse/Bash, and `session-context.sh` is
deliberately on UserPromptSubmit rather than SessionStart, for the source
reasons in rows 10 and 2.

The same section installs Kimi's agents and standing instructions:

- `configs/kimi-agents/*.md` is copied to `~/.kimi-code/agents/`:
  - `ask-claude` and `ask-codex` are cross-vendor bridges, used only when the
    user asks for that vendor;
  - `clade-explorer` is read-only (`Read`, `ReadMediaFile`, `Grep`, `Glob`,
    `FetchURL`, `WebSearch`);
  - `clade-implementer` is the bounded-implementer contract (`Read`, `Bash`,
    `Write`, `Edit`, `Grep`, `Glob`).
- Both `clade-*` agents declare `subagents: []`, so they cannot delegate
  further, and both inherit the caller's model. Kimi enforces an agent's
  `tools` allowlist (`isToolActive`).
- `configs/KIMI_AGENTS.md` is merged into `~/.kimi-code/AGENTS.md` as the managed
  block. User text around it is kept. The block maps the Claude Code names used
  in Clade skills (`TodoWrite`, `WebFetch`, `Task`, `${CLAUDE_SKILL_DIR}`, …) to
  Kimi's tools. The pairs must equal the scanner's mapped rules in
  `configs/scripts/kimi-skill-compat.py` (`ScheduleWakeup` → `CronCreate`
  aside, because the policy never names that tool), and
  `orchestrator/tests/test_kimi_skill_compat.py` fails when they drift.

## Subagents under `kimi -p`

Kimi Code 2.6.0's non-interactive print mode can make every `Agent` call fail
immediately with `Agent timed out after 0 hours`. Interactive `kimi` is not
affected. The print entry calls `applyPrintModeConfigDefaults`
(`agent/task/printDefaults.ts`), whose `fillSectionDefault` writes
`subagent.timeoutMs = 0` at memory scope when the user has not set a value.
`resolveSubagentTimeoutMs` (`session/subagent/configSection.ts`) normally
defaults to 7,200,000 ms, but the explicit zero wins. `SubagentTool`
(`agent/tools/agent/agentTool.ts`) then passes it to `setTimeout` without a
zero-value guard. TOML's `timeout_ms` becomes `timeoutMs` through
`snakeToCamel` (`app/config/toml.ts`).

For an existing `~/.kimi-code/config.toml`, `install.sh` therefore writes
Kimi's normal default explicitly:

```toml
[subagent]
timeout_ms = 7200000
```

It inserts the key under an existing bare or quoted `[subagent]` header, or
appends the table when absent. Reinstalling is idempotent, and the step needs
no Python. Because 7,200,000 ms is Kimi's own default, interactive behavior
does not change. Print mode's zero is meant to mean **no limit**: swarm
honours it and only `SubagentTool` does not, so this workaround caps a
`kimi -p` subagent at two hours where print mode intends no limit; a larger
`timeout_ms` raises the cap.

The installer skips, with one message and no write:

- an existing bare, double-quoted, or single-quoted `timeout_ms` key;
- **any** root dotted key whose first segment is `subagent`, even when it is
  not `timeout_ms`, with any TOML quoting and whitespace around the dot;
- a root inline `subagent = { … }` table or other root assignment, including
  quoted spellings;
- a `subagent` array-of-tables;
- an unclosed single- or multi-line string or array, or an ambiguous quote run;
- an original or candidate TOML parse failure, or a candidate that fails the
  value-preservation check.

Root dotted and inline definitions are skipped rather than rewritten to keep
their layout intact and avoid redefining the table. If yours is skipped for
that reason, add `subagent.timeout_ms = 7200000` beside your other `subagent`
keys yourself. Header detection ignores multi-line basic (`"""`) and literal
(`'''`) string contents, and lines inside a multi-line array, whose elements
can start with `[`. When Python
3.11+ is available, the installer parses the original and a temporary
candidate, rejects any parse failure or change to another root value or an
existing subagent value, and only then renames the candidate. Without
`tomllib`, the conservative awk scanner alone decides.

Choose a different limit in that table, or override it for one print run:

```bash
KIMI_SUBAGENT_TIMEOUT_MS=600000 kimi -p '…'
```

Print defaults also set `swarm.timeoutMs` to zero, but swarm does not have the
same failure: `linkAttemptSignals` (`features/swarm/session/agentRunBatch.ts`)
treats `timeout <= 0` as no timer. The installer therefore leaves swarm
configuration untouched. This swarm finding comes from the 2.6.0 source, not
a live swarm run.

## Attribution and verification

Kimi's `session_<UUID>` survives intact in correction and revert history. The
shared correction shadow already accepted underscores; the two history-record
filters now accept them too, without changing the treatment of Claude UUIDs or
hostile path characters. A missing transcript path is persisted as JSON
`null`, not dereferenced and not fabricated.

`tests/test-kimi-hooks.sh` installs into a temporary HOME and executes the
exact commands read from the resulting TOML through `bash -c`, matching Kimi's
`hostProcess.spawn(..., {shell: true})`. Its classifier mirrors RH's exit and
JSON parsing. It covers block and allow cases for both PreToolUse guards,
prompt arrays, session attribution, correction pairing and cleanup, Stop,
once-only context, both memory-sync entries, all Claude block forms, plain
prompt context, fail-open behavior, legacy migration, reinstall idempotency,
user-entry preservation, and missing-config behavior.

No live Kimi process is launched by the suite. A live run after install,
on 2026-11-12, used Kimi Code 2.6.0 headless (`kimi -p`, `kimi-code/k3.1-pro`) in a
throwaway directory. Results:

| Check | Result |
|---|---|
| First prompt carries the `session-context.sh` `<hook_result>` block | yes |
| A database-migration command (`alembic` + `upgrade head`) | denied, with `pre-tool-guardian.sh`'s message |
| Write `.eslintrc.json` | denied, with `linter-config-guard.sh`'s message |
| Write an ordinary file | allowed |
| Agent tool lists `clade-explorer` and `clade-implementer` | yes, beside `plan`, `coder`, `explore` and the two bridges |
| An Agent call to `clade-explorer` runs | **no**: "Agent timed out after 0 hours" |
| After the skill view is deployed (#234), claude-only skills (`loop`, `batch-tasks`, `orchestrate`, `init-profile`, `iloop`, `blog`, `seo`) are absent from the model's skill list | yes; `commit`, `review` and `delivery` are listed |
| `Skill(skill="loop")` from the model | refused: "can only be triggered by the user (model invocation is disabled)" |
| `Skill(skill="commit")` from the model | loaded |
| After #235 is deployed (2026-11-13), asked without tools, the model maps `TodoWrite`, `WebFetch` and `${CLAUDE_SKILL_DIR}` | `TodoList`, `FetchURL`, `${KIMI_SKILL_DIR}`, citing "Clade Skills Written for Claude Code" (the map is in context; following it in a skill run is not measured) |
| After #236 is deployed (2026-11-13), with `KIMI_SUBAGENT_TIMEOUT_MS` unset, an Agent call to `clade-explorer` under `kimi -p` | yes: it read a file and returned its second line |
| `clade-explorer` asked to create a file | no file created; it answered that it has no file-writing or command tool and listed `FetchURL`, `Glob`, `Grep`, `Read`, `ReadMediaFile`, `WebSearch` |

The last failure hit the built-in `explore` too, so the agent definitions are
not the cause. Print mode's `applyPrintModeConfigDefaults` sets an unset
`subagent.timeoutMs` to 0, and the Agent tool arms `setTimeout` with that 0.
Setting `KIMI_SUBAGENT_TIMEOUT_MS` made `explore` complete. `install.sh` now
writes Kimi's own default into `config.toml` instead; see
[Subagents under `kimi -p`](#subagents-under-kimi--p).

Still unverified live:

- the single Stop continuation;
- interactive-TUI rendering of `<hook_result>`;
- the absence of a Notification producer;
- a hand-typed `/skill:<name>` for a hidden skill in the TUI (see
  [Skill view](#skill-view)).

## Skill view

Kimi 2.6.0 scans each directory in `extra_skill_dirs` and follows symlinked
child directories (`features/skill/workspace/environmentSkillDiscovery.ts`). It
lists every skill whose metadata does not disable model invocation
(`catalog/registry.ts::listInvocableSkills`; `disableModelInvocation`,
`disable-model-invocation` and `disable_model_invocation` are aliases in
`catalog/parser.ts::METADATA_ALIASES`). A skill with model invocation disabled
can still be run by hand with `/skill:<name>` in the interactive TUI or over
ACP. Those are the only two paths that parse a slash command:
`resolveUserInput` in the TUI and `detectSlashIntent` in
`acp-server/src/session.ts`. Both build their command map with no
model-invocation filter. Print mode (`kimi -p`) parses neither, so there the
text reaches the model as an ordinary prompt.

`install.sh` used to point `extra_skill_dirs` at `~/.claude/skills`, so Kimi was
offered all of them, including the ones that need Claude-only machinery. It now
builds a view instead:

1. `configs/scripts/kimi-skill-compat.py --json` classifies each skill from the
   primitives it uses: **native** (no Claude-specific primitive), **adapted**
   (only primitives with a Kimi equivalent, e.g. `TodoWrite` → `TodoList`,
   `WebFetch` → `FetchURL`, `Task` → `Agent`), **degraded** (a primitive with no
   Kimi equivalent, used only behind an "if available", optional or fallback
   guard), or **claude-only** (such a primitive used without a guard: Workflow,
   Monitor, `claude -p`, the Claude hook lifecycle). Mentions in front matter,
   comments or prose comparing the runtimes are not uses. On this tree: 114
   native, 13 adapted, 6 degraded, 15 claude-only of 148. The scan is static
   triage, not proof that a skill runs.
2. `configs/scripts/kimi-skill-view.py` writes `~/.kimi-code/clade-skills/`,
   owned through a `.clade-managed` marker; a directory there without the
   marker is left alone, and so is the config. Every non-claude-only skill,
   including a user skill the scan has never seen, is a symlink to its
   directory in `~/.claude/skills`. A claude-only skill is a real directory
   holding a copy of its `SKILL.md` with `disableModelInvocation: true` added to
   the front matter, plus symlinks to the rest of its files. `~/.claude/skills`
   is only read: it may be a symlink into the dotfiles sync store, and the
   tests hold it byte-identical. Removals unlink entries and never follow a
   symlink. A claude-only `SKILL.md` without a front matter is left out of the
   view, because Kimi rejects a directory skill whose first line is not `---`
   or that lacks `name` or `description` (`catalog/parser.ts::parseSkillText`).
3. Only after the view builds does `extra_skill_dirs` change: it is inserted
   when absent, and migrated only from the exact one-line value an earlier
   install wrote. A quoted key, a multi-line array, a nested array or any other
   value is the user's and stays byte-identical. On Python 3.11+ the original
   and the updated TOML are both parsed before the write, and every other root
   key and table must be unchanged; on an older Python only that textual rule
   applies. Without symlink support or a working Python, the view is skipped
   and the config is left as it was.

`orchestrator/tests/test_kimi_skill_compat.py` drives `install.sh` in a
temporary HOME, including a skill whose classification changes between
installs.
