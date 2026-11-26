---
title: "Claude Code 2.1.331: the re-checks queued for after the upgrade from 2.1.283"
date: 2026-11-26
review_date: 2027-01-26
status: integrated
summary: >
  aries moved from Claude Code 2.1.283 to 2.1.331 on 2026-11-23 21:27 PST.
  Six checks had been queued in TODO.md for that upgrade. Five hold with no
  change: subagent compactions now reach post-compact-reinject.sh's subagent
  branch; pre-tool-guardian.sh never answers "allow", so the 2.1.323
  permission change cannot reach it; radar-cron.sh is a system cron job running
  `claude -p` and /radar declares no allowed-tools or hooks; every model ID in
  use is one 2.1.331 knows, so the unknown-model 1M default reaches no session;
  and the 2.1.318 three-minute move does not reach Workflow subagents, so the
  270 s wait warning stays. One changed: pre-tool-guardian is now wired with
  "onFailure": "block" and a 15 s timeout, because on 2.1.331 a guardian
  timeout still ran the command unchecked (on 2026-11-26, 7 of the 283 Bash
  calls of one Workflow run whose own builds starved its cgroup scope).
  secret-scanner was left fail-open on purpose.
integrated_items:
  - "configs/settings-hooks.json: pre-tool-guardian carries \"onFailure\": \"block\" and a 15 s timeout; pinned by tests/lib/hooks-onfailure.sh (sourced by tests/test-hooks.sh)"
needs_work_items:
  - "context-policy.json verified_through_cc_version is still 2.1.283; the trigger formula and precedence were not re-read in the 2.1.331 binary"
reference_items:
  - "Watch: a guardian timeout now refuses the call. At the old 5 s limit that was 7 of the 283 Bash calls of one Workflow run whose builds starved its cgroup scope, and 0 of the 858 other Bash calls on the host in the same 15 minutes (2026-11-26 19:04-19:19Z); the limit is now 15 s"
  - "Not run live: no Claude Code session was started to watch onFailure block a call; the evidence is the official hooks reference, the 2.1.295 changelog line and the 2.1.331 binary's strings"
---

# Claude Code 2.1.331: the re-checks queued for the upgrade

## Verdict

| # | Queued check | Verdict on 2.1.331 | Change here |
|---|---|---|---|
| a | 2.1.323 passes `agent_id` to post-compaction hooks | **Holds.** Subagent compactions no longer get the project restore | none |
| b | 2.1.323: a permission error after a PreToolUse "allow" is decided as if no hook answered | **Does not apply.** The guardian's rewrite carries no `permissionDecision` | none |
| c | 2.1.325: scheduled tasks and `/loop` ask before a skill with `allowed-tools` or hooks | **Does not apply** to `radar-cron.sh`, for two separate reasons | none |
| d | 2.1.323: an unrecognised model ID is assumed to have 1M, not 200K | **Reaches no session on aries.** The policy's reasoning holds | none |
| e | 2.1.288 fail-closed PreToolUse matching, and `onFailure: "block"` (2.1.295) | **Field honoured.** Guardian timeouts still ran commands unchecked | `pre-tool-guardian` gets `"onFailure": "block"` and a 15 s timeout; `secret-scanner` deliberately does not |
| f | 2.1.318 moves a background subagent's shell command to the background after 3 minutes | **Does not reach Workflow subagents.** 103 foreground calls ran past 270 s | none; the 270 s warning stays |

Nothing is needed from the owner. Two things to watch: guardian timeouts now
refuse a call instead of running it, and the context policy still reports
"verified through 2.1.283".

## a. `agent_id` in post-compaction hooks

`post-compact-reinject.sh` (SessionStart `compact`) and `pre-compact.sh` exit
early for a subagent, keyed on `agent_id`, with a `.../subagents/.../agent-*.jsonl`
`transcript_path` as the fallback (#247). The 2.1.323 changelog reads: "Fixed
`PreCompact`, `PostCompact` and post-compaction `SessionStart` hooks not
receiving `agent_id` and `agent_type` when a subagent compacts".

Measured over every subagent transcript on aries:

- **2.1.283:** 580 subagent compactions, each followed by a `SessionStart:compact`
  hook output carrying the main thread's project restore. 235 of them came after
  the #247 hook reached the dotfiles store (sync commit, 2026-11-16 19:39 PST).
  So on 2.1.283 the `transcript_path` fallback did not catch them: that version
  does not pass the subagent's own transcript path.
- **2.1.331:** 48 subagent compactions, and no `SessionStart:compact` output in
  any of them. In 28 of the 47 transcripts, a path-scoped rule injected before
  the compaction was injected again after it. `rule-injector.sh` injects a rule
  once per sentinel, and the subagent branch of `post-compact-reinject.sh` is
  what deletes that subagent's sentinel. So that branch ran.

## b. The guardian's rewrite path and the 2.1.323 permission change

The 2.1.323 change is: "Changed what happens when a tool's permission check fails
with an error after a `PreToolUse` hook returned 'allow': Claude Code now decides
the call as if no hook had answered". `pre-tool-guardian.sh` never returns
"allow". It denies with `permissionDecision: "deny"`. It rewrites with
`updatedInput` and no decision, and it warns with `additionalContext` alone (its
header, "Why the rewrite carries NO permissionDecision").
`tests/test-pre-tool-guardian.sh` already reads any decision on a rewrite as
`REWRITE-ESCALATES`, so the shape is pinned.

Two related changes were checked as well:

- 2.1.300: `updatedInput` "is now validated like Claude's own input: unknown keys
  are dropped, and input the tool rejects denies the call". The guardian sends
  the model's own `tool_input` back with only `command` replaced, so every key
  is one the Bash tool already accepted.
- 2.1.326: "Improved how a PreToolUse hook's `updatedInput` is kept when more
  than one hook answers a tool call; the rewrite now runs in more cases."

On 2.1.331 the guardian rewrote two calls (2026-11-25, a recursive delete through
an unset variable). Both ran, in the background, as the model had asked. No
guardian output was rejected on 2.1.331: there are no `hook_non_blocking_error`
records for it, where 2.1.283 had 41 for the legacy-decision shape.

## c. `radar-cron.sh` and the 2.1.325 scheduled-task prompt

The 2.1.325 change is: "Changed scheduled tasks and `/loop` to ask before
running a skill that declares `allowed-tools` or hooks; add `Skill(name)` to
`permissions.allow` to run it unattended". It does not reach the radar run, for
two independent reasons:

1. The radar run is not a Claude Code scheduled task or `/loop`. The system
   crontab runs `radar-cron.sh` (`7 8 * * 1`), which starts `claude --print`
   with `--permission-mode acceptEdits` and an explicit `--allowedTools` list.
2. `configs/skills/radar/SKILL.md` declares neither `allowed-tools` nor
   `hooks`, which is the condition for the prompt.

This was not observed live. The last radar run, 2026-11-23 16:07Z, was on 2.1.283
(the upgrade came at 05:27Z the next day). That run hit its 2,700 s timeout with
no digest, which is a separate radar matter. The first run on 2.1.331 is due
2026-11-30.

## d. The 1M default for unrecognised model IDs and the context policy

The 2.1.323 change is: "Changed the context window assumed for a model ID that
Claude Code doesn't recognize from 200K to 1M; use `/autocompact` to compact
earlier, or `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` to keep 200K".

The model IDs in 2.1.331 transcripts on aries since 2026-11-24 are
`claude-opus-5-5`, `claude-fable-5-2`, `claude-fable-5` and `claude-sonnet-5-5`,
plus `<synthetic>`. All four real IDs appear in the 2.1.331 binary's strings, 41
to 120 times each. So the unrecognised-model path reaches no session here.

The policy's reasoning (`docs/configuration.md`) still holds. The policy writes
`autoCompactWindow: 350000`, which Claude Code caps at the model's own window.
So the policy is a no-op on a model Claude Code knows to be 200K. For an ID it
does not recognise, 2.1.331 now assumes 1M. The 350,000 value then applies
there too: it compacts near 317,000 tokens instead of the default 967,000.
That is earlier, never later, than what Claude Code would do on its own.
Suppose a gateway serves a 200K model under an ID Claude Code does not know.
That session would overflow either way, and the fix is
`CLAUDE_CODE_DISABLE_1M_CONTEXT` or `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, not
Clade's key.

Not re-verified: `context-policy.py status` on 2.1.331 still prints "NOTICE:
you run 2.1.331, newer than the verified 2.1.283". The trigger formula and the
key's precedence were not re-read in the 2.1.331 binary. That stays a
follow-up.

## e. Fail-closed PreToolUse hooks and `onFailure: "block"`

The 2.1.288 changelog reads: "Fixed PreToolUse and PermissionRequest hooks being
skipped when matching them failed or the tool's input could not be serialized to
JSON; the call is now blocked". aries (2.1.331) has that fix. Of the other fleet
hosts, one Linux host runs 2.1.322 and the macOS runner 2.1.330, and both have it.
A third Linux host runs 2.1.287, which has neither that fix nor `onFailure`.

`onFailure` was added in 2.1.295: "a hook that can't start, times out, or exits
with an unexpected code blocks the action instead of letting it through". The
hooks reference documents it as a command, HTTP or `mcp_tool` hook field,
`"continue"` or `"block"`. It counts these as failures: can't start, an exit code
other than 0 or 2, a timeout, and output that does not parse or fails schema
validation. It has no effect on Stop, SubagentStop, TaskCompleted, TeammateIdle,
or `async`/`asyncRewake` hooks. The 2.1.331 binary carries the runtime message
`blocking because onFailure is "block"`.

**Why it matters on this host.** On 2.1.331 the guardian still failed open, and
every timeout came from one Workflow run. In the 15 minutes from 2026-11-26
19:04Z (load average 141–178 on 32 cores, `sar -q`), the host ran 1,141 Bash
calls: 585 on 2.1.331 and 556 on 2.1.283. 7 hit the guardian's 5 s timeout
(recorded as `hook_cancelled`, 5.5–8.4 s), and all 7 were among the 283 calls
of one 2.1.331 Workflow run, in a session of profile main2. The other 302 calls
on 2.1.331 had none, and 286 of them came from a second Workflow run on the same
profile and version at the same time. The 556 calls on 2.1.283 had none. Every
one of the 7 commands ran, unchecked. Up to 20:29Z that run made 1,567 Bash
calls and had no timeout outside those 15 minutes.

**Why that run.** A hook is a child of the Claude Code process, so it runs in
that process's cgroup scope: here the tmux scope the session was started in.
That run's agents ran their builds and tests in the same scope. Read at 20:26Z,
the scope had used 36,888 CPU-seconds and recorded 1,443 s of CPU pressure
(`cpu.pressure` "some", over the scope's life; its CLI process started at
18:44Z). The concurrent 2.1.331 run's scope had used 2,689 CPU-seconds and
recorded 229 s. The cpu controller is enabled down to `app.slice` and every
scope there has weight 100, so under contention all the processes of a busy
scope share one scope's portion of the CPU. In the window, trivially fast
commands (`ls`, `cat`, `git status` and the like, timed from tool_use to
tool_result) took a median 4.3 s and a p90 8.7 s in that run (82 calls),
against 2.0 s and 4.2 s in the concurrent 2.1.331 run (95 calls). Replayed now,
the guardian takes 0.05 s on each of the 7 commands; its runs that printed
output on 2.1.331 took 44–932 ms, and runs on a typical command 78–147 ms at
load ~110. So a timeout here means the hook's own scope was starved. It was not
a slow check and not a host-wide stall. Nor is it shown to be a 2.1.331 effect:
the second 2.1.331 run had none.

**The earlier timeouts.** Since 2026-10-27 there have been 12 guardian
timeouts, counted at about 19:50Z on 2026-11-26: the 7 above, in 23,855 Bash
calls on 2.1.331, and 5 in 402,281 on 2.1.283. Those 5 were all on 2026-11-22
between 00:14Z and 00:30Z, and they look host-wide. Both Workflow runs that
made Bash calls then had them (4 of 46 and 1 of 29 Bash calls, profiles main2
and main3), the load average was 345–590 on 32 cores, and each lasted 9–153 s
against the 5 s limit. That suggests Claude Code itself was stalled past its
own timer (an inference).

**Change.** `configs/settings-hooks.json` gives `pre-tool-guardian` the line
`"onFailure": "block"` and raises its `timeout` from 5 to 15 s. `install.sh`
replaces `.hooks` wholesale with the hooks it builds from that file, so the next
install carries both. `templates/settings.json` does carry hooks, on six events
(SessionStart, PostToolUse, Stop, Notification, TaskCompleted,
UserPromptSubmit), but it has no PreToolUse entry, and install.sh never uses
them: its merge path and its fresh-install path (step 8) both set
`.hooks = $hooks`. So the template needs nothing. A CLI older than 2.1.295
ignores the key. The evidence is that every deployed hook entry already carries
`id` and `description`, which Claude Code does not define. Those entries have
run on 2.1.283 throughout, and the guardian's own outputs appear in its
transcripts.

**The cost.** A timeout now refuses the call, and the agent sees `timed out;
blocking because onFailure is "block"`. At the old 5 s limit that would have
refused 7 of the 283 calls the starved run made in those 15 minutes (2.5%), and
none of the 858 other Bash calls on the host. A crash blocks every call, safe
ones included. That is why the guardian still runs without `set -e`.

**Why 15 s.** While a timeout failed open, the limit only bounded how long a
hung guardian could delay a call, and a timeout lost the check and nothing else.
Now a timeout refuses the call, so the limit decides how often a starved
guardian becomes a refusal. A normal run takes well under a second (above), so
15 s changes nothing on a normal call. In the starved run, 30 of the 82
trivially fast calls took 5 s or more end to end, 5 took 10 s or more and 2 took
15 s or more, and the guardian is only part of that time. How many of the 7 a
15 s limit would have let through is not measured: each was killed at 5 s. On a
CLI that still fails open (one fleet host runs 2.1.287), the longer limit lets a
starved guardian finish its check instead of being skipped. The price is that a
guardian that hangs holds the call 15 s before refusing it. The starvation
itself is avoided by running heavy agent work in its own scope
(`systemd-run --user --scope`). The Workflow run that produced this branch tells
its agents to do that, and it had no timeout in its 467 calls in the window, on
2.1.283.

**Why `secret-scanner.sh` stays fail-open.** TODO.md named it as guardian-class.
Its own contract says otherwise: "Never blocks — false positives must not stop
work". It runs on UserPromptSubmit and only ever adds a note; a credential
prompt reaches the model even when the scan succeeds. With `"block"`, a failure
blocks the prompt (the reference: "a `UserPromptSubmit` failure blocks the
prompt"). That would stop work on exactly the path that has nothing to protect.
No failure of it was recorded in the window (no `hook_cancelled` or error record
names it). A test pins it as fail-open, so making it fail closed has to be a
deliberate change.

**Pinned.** `tests/lib/hooks-onfailure.sh`, sourced by `tests/test-hooks.sh`,
checks four things. The guardian carries `"block"`, and a timeout of at least
15 s. `secret-scanner` carries none, or `"continue"`. And every `onFailure` in
the file sits where Claude Code honours it, with a fixture as the negative
control.

## f. The 270 s subagent-wait warning and the 2.1.318 three-minute move

The 2.1.318 change is: "Changed background subagents to move a shell command to
the background after 3 minutes on all providers, so the prompt cache doesn't
expire while it runs". That would be the native form of the guardian's 270 s
warning. The retire-when is that no foreground call outlives 270 s.

Replay over Workflow-subagent transcripts on 2.1.331 (587 transcripts,
2026-11-24 19:38Z to 2026-11-26 19:06Z):

- 20,988 Bash calls with results, 20,493 of them foreground;
- wall time per foreground call: 19,300 under 60 s, 472 at 60–170 s, 31 at
  170–190 s, 587 at 190–270 s, **103 at 270 s or more**;
- 118 foreground calls were moved to the background, every one at its own
  timeout ("did not complete within its …s timeout"). None was moved by the
  three-minute rule ("after running for …s").

Workflow subagents are not the "background subagents" the change covers. The
retire-when is not met: the warning stays. On 2.1.331 it fired 56 times in this
window.

## Also re-read

- **The two prompt hooks (2.1.294, "`prompt` and `agent` hooks written as
  instructions … allowing what they should block").**
  `stop-completeness-check` is phrased as a condition (MET / NOT MET), so the
  fix does not change it. `precompact-state-save` is written as instructions,
  but it blocks nothing. Removing it is already an open owner decision in
  TODO.md.
- **Mods (2.1.287).** No enabled plugin ships one. A mod is a plugin whose
  `hooks/hooks.json` lists `modules` (mods reference, "Files").
  `scamai-mnemo@scamai-internal` holds only `.mcp.json`.
  `stripe@claude-plugins-official`, which is now enabled, ships settings hooks
  on five events and no `modules`. Its UserPromptSubmit hook was cancelled once
  on 2026-11-22, at 30.6 s against a 5 s timeout.

## Populations and sources

- Transcripts: every `*.jsonl` under `~/.claude/projects` and
  `~/.claude-profiles/*/projects` on aries, read-only, by scripts run from a
  session scratch directory (not committed). The windows are stated beside
  each number.
- Changelog: `anthropics/claude-code` `CHANGELOG.md`, fetched 2026-11-26 (head
  2.1.332); each quoted line is under the version named.
- Hooks reference: `https://code.claude.com/docs/en/hooks.md`, "Block the action
  when a hook fails", fetched 2026-11-26.
- Mods reference: `https://code.claude.com/docs/en/plugins/mods/reference.md`,
  "Files".
- Binary: `~/.local/share/claude/versions/2.1.331`, read with `strings`.
- Fleet versions: each host's `~/.local/bin/claude` link target, read 2026-11-26.
- Per-run Bash counts and guardian timeouts: every Bash `tool_use` and every
  guardian `hook_cancelled` in the window, keyed by the transcript's profile,
  session and `workflows/wf_*` directory, deduplicated on the tool_use id.
- Host load: `sar -q` over `/var/log/sysstat/sa26` (2026-11-26 11:00–11:20 PST)
  and `sa21` (2026-11-21 16:00–16:40 PST, which is 2026-11-22 00:00–00:40Z).
- cgroup figures: `cpu.stat` `usage_usec`, `cpu.pressure` and `cpu.weight` of
  each session's scope under `user@<uid>.service/app.slice`, and
  `cgroup.subtree_control` up that path, read 2026-11-26 20:26Z.
- Guardian replay: the 7 timed-out `tool_input`s fed to
  `configs/hooks/pre-tool-guardian.sh` under `/usr/bin/time`, load ~44.
