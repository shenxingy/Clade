---
name: 2026-09-05-codex-gpt56-and-harness-review.md
date: 2026-09-05
status: integrated
review_date: 2026-12-05
summary:
  - "PENDING — filled in when the review's compare/verify stage lands."
integrated_items:
  - "PENDING"
needs_work_items:
  - "PENDING"
---

**English**（中文版尚未提供 — [README 中文版](../../README.zh-CN.md)）

← Back to [README](../../README.md) · index: [Research](README.md)

# The Codex GPT-5.6 generation, read against Clade

## Why this exists

The ask was to look hard at what is new — the current Codex models above all —
and say what is worth learning. The honest answer needed two halves that are
usually conflated: what upstream actually does, read from its source rather
than its announcements, and what Clade already does, read from its files rather
than its documentation. Most of the value turned out to be in the second half.
Almost nothing upstream is a capability this toolkit lacks. What the sweep
found instead is three places where Clade's own record is wrong, two of them
load-bearing.

Method: 23 parallel readers over the upstream source at `4df8027a97`, the
release notes from 0.150.0 to 0.153.4, the live model catalog and its per-model
system prompts, this host's Codex state databases, and the wider field; then a
classification pass against this repository, then a skeptic per claimed gap.
Every number and verdict below that carries a file:line was re-checked by the
lead, and the three findings headed "verified" were reproduced by hand.

## What is actually new, measured on this host

These facts come from the installed CLI, its on-disk state, and the upstream
source — not from a search result. Anything below can be re-checked with the
command shown.

### Version lag

| Surface | Here | Upstream | Check |
|---|---|---|---|
| Codex CLI | 0.145.0 (standalone package dir holds 0.144.6) | 0.153.4 stable, 2026-09-04 | `codex --version`; `gh api repos/openai/codex/releases` |
| Claude Code CLI | 2.1.261 | — | `claude --version` |
| Clade Codex tiers | cheap `gpt-5.6-terra`, strong `gpt-5.6-sol` | catalog lists `gpt-5.6-luna` as the "fast and affordable" tier | `orchestrator/config.py:312`, `configs/codex-agents/*.toml` |

Eight minor releases sit between the installed CLI and upstream. Every claim in
this document about *behaviour* was checked against the upstream source at
`4df8027a97`; every claim about *what runs here* was checked against 0.145.0.

### The live model catalog (`~/.codex/models_cache.json`, fetched 2026-09-05T01:50Z)

| slug | catalog description | default effort | efforts | context / max | tool mode | multi-agent |
|---|---|---|---|---|---|---|
| `gpt-5.6-sol` | reliable agentic workhorse | low | low → max, **ultra** | 272k / 872k | `code_mode_only` | v2 |
| `gpt-5.6-terra` | balanced agentic coding | medium | low → max, **ultra** | 272k / 872k | `code_mode_only` | v2 |
| `gpt-5.6-luna` | fast and affordable | medium | low → max | 272k / 872k | `code_mode_only` | v1 |
| `gpt-5.5` | previous generation | medium | low → xhigh | 272k | function tools | — |
| `gpt-5.4-mini` | small, fast | medium | low → xhigh | 272k | — | — (catalog carries an `upgrade` → luna, "will be deprecated soon") |
| `gpt-5.3-codex-spark` | ultra-fast, text only | high | low → xhigh | 128k | — | — (not in API) |
| `codex-auto-review` (hidden) | "automatic approval review model" | medium | low → max | 272k / 872k | `code_mode_only` | v1 |
| `gpt-reserve` (hidden) | fast and affordable | medium | low → max | 272k / 872k | `code_mode_only` | v1 |

Three things in that table are new since the last sweep and none of them is a
benchmark number:

- **`ultra` is an effort level, not a model.** The catalog describes it as
  "maximum reasoning with automatic task delegation": the model decides to
  spawn subagents. Only Sol and Terra carry it, and both carry
  `multi_agent_version: v2`; Luna carries v1 and no ultra.
- **`tool_mode: code_mode_only`** on every 5.6-family model. The 5.5 catalog
  entry has no such field. The model reaches tools by writing code that a host
  executes, not by emitting one function call per tool.
- **The context figures depend on who is asking.** The server catalog handed
  this 0.144.6 client `context_window: 272000` and `max_context_window:
  872000` for every 5.6 model; the fallback catalog bundled in upstream 0.153
  (`codex-rs/models-manager/models.json`) says 372k for both, and gives
  `gpt-5.4` and `codex-auto-review` a 1,000,000 ceiling. Treat any single
  number quoted for "the 5.6 context window" as version-dependent until the
  CLI here is updated and the catalog re-fetched.

### The base prompt changed shape between 5.5 and 5.6

All five 5.6-family entries (Sol, Terra, Luna, reserve, auto-review) ship a
byte-identical `base_instructions` (md5 `4d96ce85…`); 5.5 ships a different,
older one. Diffing the two:

Removed from the base prompt: the whole "Engineering judgment" section, the
~40-line "Frontend guidance" block, the "Special user requests" review stance,
most editing constraints, the `multi_tool_use.parallel` instruction.

Added: a `# Personality` section; a "Writing style" section that *forbids*
over-formatting (bold, headers, lists) and demands CommonMark blank lines; a
"Technical communication" section (lead with the outcome, plain language);
compaction-continuation instructions ("do not restart from scratch … treat a
turn spanning compactions as one logical chain"); mid-turn user-message
handling (replace vs. add); a request-type-adaptive "Autonomy and persistence"
section with four envelopes — *answer/explain/review/report* (no external
writes), *diagnose* (no fix unless asked), *change or build* (implement, verify
in proportion to risk), *monitor or wait* — plus the sentence "a terminal
condition such as 'finish', 'babysit', or 'do not stop' requires persistence
toward the outcome, but does not broaden the set of authorized actions"; a
`# Destructive actions` protocol (resolve targets with read-only checks, never
`$HOME`/`~`/`/` as a recursive target, `mktemp -d`, prefer trash, report what
was removed and whether it is recoverable); a "Visualizations" rubric (when a
table/flow/tree/wireframe earns its place); and a much longer `# Using skills`
protocol (skill roots and aliases, orchestrator-hosted skills read through
`skills.list`/`skills.read`, "the main agent must read SKILL.md completely",
"do not delegate reading a skill to a subagent", announce every skill use in
the commentary channel).

The frontend rules did not survive into the 5.6 base prompt. In upstream's
bundled fallback catalog only the `gpt-5.5` entry still carries them, and the
`lucide` / "one-note palettes" text appears in no other file of the source
tree — so on 5.6 that guidance either arrives from a skill or does not arrive
at all. The direction is the one this repository already took when it moved
interface rules into the `frontend-design` skill rather than the global file.

### `codex features list` on 0.145.0

Stable and on: `apps`, `browser_use` (+external, +full CDP), `code_mode_host`,
`computer_use`, `fast_mode`, `goals`, `guardian_approval`, `hooks`,
`image_generation`, `in_app_browser`, `multi_agent`, `personality`,
`plugins`, `plugin_sharing`, `remote_plugin`, `remote_compaction_v2`,
`shell_snapshot`, `skill_search`, `skill_mcp_dependency_install`.
Stable and off: `memories`, `multi_agent_v2`, `secret_auth_storage`.
Under development: `artifact`, `chronicle`, `code_mode` (full),
`rollout_budget`, `token_budget`, `runtime_metrics`,
`external_agent_memory_import`, `executor_capability_discovery`,
`deferred_executor`, `exec_permission_approvals`, `request_permissions_tool`,
`realtime_conversation`, `concurrent_reasoning_summaries`,
`standalone_web_search`, `current_time_reminder`.
Removed: `enable_fanout`, `multi_agent_mode`, `plugin_hooks`, `steer`,
`codex_git_commit`, `js_repl`, `remote_control` (as a flag; the subcommand
stayed).

### On-disk state Codex keeps (`~/.codex/*.sqlite`, read with python `sqlite3`)

- `goals_1.sqlite` — `thread_goals(thread_id, goal_id, objective, status ∈
  {active, paused, blocked, usage_limited, budget_limited, complete},
  token_budget, tokens_used, time_used_seconds)` plus a continuation-deferral
  table. Ten rows on this host: the feature has been used here.
- `memories_1.sqlite` — `stage1_outputs(thread_id, raw_memory,
  rollout_summary, rollout_slug, usage_count, last_usage,
  selected_for_phase2, …)` and a `jobs(kind, job_key, status, worker_id,
  ownership_token, lease_until, retry_at, retry_remaining, last_error,
  watermarks)` table: a leased background job queue feeding a two-phase memory
  pipeline. Zero rows: the feature is off.
- `state_5.sqlite` — `threads` (732 rows, each with `git_sha`, `git_branch`,
  `git_origin_url`, `cli_version`, `sandbox_policy`, `approval_mode`,
  `tokens_used`), `thread_spawn_edges(parent, child, status)` (540 rows —
  every subagent spawn is a persisted edge), `thread_dynamic_tools` (with a
  `defer_loading` column), `remote_control_enrollments`,
  `external_agent_config_imports`.
- `logs_2.sqlite` — 1.1 million structured log rows.

### The CLI surface (0.145.0)

`docs/codex.md` (rewritten 2026-09-02) names `app-server`, `--json` and
`--output-schema` and nothing else on this list. Subcommands it does not
mention:
`review` (`--uncommitted` | `--base <branch>` | `--commit <sha>`), `cloud`
(`exec`/`status`/`list`/`apply`/`diff`), `app-server` (`daemon`, `proxy`,
`generate-ts`, `generate-json-schema`; `--listen stdio://|unix://|ws://`),
`remote-control` (`start`/`stop`/`pair`), `exec-server` (`--remote`,
`--environment-id`, `--use-agent-identity-auth`), `sandbox`
(`-P <permission-profile>`, `--sandbox-state-json`), `doctor --json`,
`features list|enable|disable`, `fork`, `archive`/`unarchive`/`delete`,
`plugin add|list|marketplace|remove`.

`codex exec` flags Clade's worker command line does not yet use: `--json`
(JSONL events), `--output-schema <file>`, `-o <file>` (last message),
`--ephemeral`, `-p <profile>` (`$CODEX_HOME/<name>.config.toml` layered on the
base config), `--add-dir`, `--ignore-user-config`, `--ignore-rules`,
`--search`, `-a untrusted|on-request|never`, `exec resume`.

### Policy files Codex reads

`~/.codex/rules/default.rules` — Starlark:

```
prefix_rule(pattern=["gh", "repo", "view"], decision="allow")
prefix_rule(pattern=["apply_patch"], decision="allow")
```

Every "always allow" answered in the TUI lands here as a prefix rule over the
argv vector, not a regex over a string. `--ignore-rules` skips the file.

### Bundled skills and the curated marketplace

`~/.codex/skills/.system/` ships `skill-creator`, `plugin-creator`,
`skill-installer`, `openai-docs`, `imagegen`. `~/.codex/plugins/cache/
openai-curated-remote/` holds OpenAI's remote-installed plugins
`deep-research-work` 0.1.14, `openai-templates` 0.1.1, `plugin-management`
0.1.0, each with `.app.json`, `.codex-plugin/plugin.json`, `skills/`, `tests/`.

## Lead-verified finding: the "Codex cannot fan out" premise is false, and Clade encoded it three times

A finder claimed it; the lead re-checked it independently, because it
contradicts a decision this repository already recorded as done.

`~/.codex/state_5.sqlite` holds 543 subagent threads. 529 were spawned by
interactive (`cli`) parents, 12 by other subagents — and **two by `source='exec'`
parents**, which is the headless path Clade's Codex worker uses:

| parent thread | when | CLI | child role | child tokens |
|---|---|---|---|---|
| `019fc0a0-64ef…` (a security review in `~/projects/internal/mnemo`) | 2026-08-01 23:59 | 0.145.0 | `clade_cheap_explorer` | 99,654 |
| `01a062bf-101e…` (an image-edit task in a scratchpad) | 2026-09-02 11:31 | 0.145.0 | `clade_cheap_worker` | 58,092 |

The child ids differ from their parents, each carries
`{"subagent":{"thread_spawn":{"parent_thread_id": …, "depth":1,
"agent_role":"clade_cheap_…"}}}` as its `source`, and both ran on 0.145.0 —
the version installed here, not some future build. The roles are Clade's own,
installed by `install.sh` from `configs/codex-agents/`.

So a headless `codex exec` did fan out, twice, using Clade's roles, one of them
three days ago. Upstream source says why: the predicate that adds the
spawn/wait tools to a turn reads only `multi_agent_version`, never the session
source, and `SessionSource::Exec` is whitelisted as a delegation root
alongside Cli and Mcp.

Clade states the opposite in three places:

- `orchestrator/worker_provider.py:363` — `"subagents": CapabilityState.UNSUPPORTED`, sourced as "codex exec has no headless sub-agent spawn". This is the value `resolve_capabilities` enforces, so a task declaring `subagents` REQUIRED is refused on Codex.
- `orchestrator/tests/test_subagents_capability.py` — its docstring states "the truth is that `codex exec` spawns no sub-agent at all", and `test_codex_subagents_is_not_a_shrug` forbids the CONDITIONAL state that the evidence actually supports.
- `TODO.md:624` — an open item, "Codex cannot fan out, and that is why it is slower … the only parallelism available to Codex is Clade spawning N `codex exec` processes from outside".

And it states the correct thing in a fourth: `configs/skills/codex-orchestrate/prompt.md:3` calls itself "the manual version of Codex's native fan-out (`model_reasoning_effort = ultra`)" and even names a slot cap. The skill on the live terminal path was right; the dormant layer's capability table and the roadmap item were wrong.

The honest replacement value is CONDITIONAL with the condition written down —
delegation depends on the resolved model's catalog `multi_agent_version`
(Sol and Terra carry v2, Luna v1) and, under v1, on explicit authorization in
the prompt or `AGENTS.md`, which Clade's managed block already grants when it
tells Codex to delegate to `clade_cheap_explorer`. That is very likely what
authorized both observed spawns.

## Lead-verified finding 2: both guardians allow every recursive delete an agent actually writes

Reproduced with `scratchpad/probe-guardian2.sh`, which feeds each command to
`configs/hooks/pre-tool-guardian.sh` and `plugins/clade/hooks/pre_tool_guardian.py`
as a real `PreToolUse` payload. The force-push rows are the control: both hooks
ran and both acted, so an ALLOW below is a decision, not a dead hook.

| command | shell hook | Codex hook |
|---|---|---|
| recursive-force delete of `/` | BLOCK | BLOCK |
| the same on `/` with a trailing star | BLOCK | BLOCK |
| the same on `~` | BLOCK | BLOCK |
| the same on `$HOME/x` | BLOCK | BLOCK |
| the same on `/home/alexshen/projects/x` | BLOCK | **ALLOW** |
| the same on `$BUILD_DIR/` | **ALLOW** | **ALLOW** |
| the same on `"$BUILD_DIR"/` | **ALLOW** | **ALLOW** |
| the same on `${OUT}/` | **ALLOW** | **ALLOW** |
| the same on `$OUT/` + star | **ALLOW** | **ALLOW** |
| the same on `"$DIR"/` + star | **ALLOW** | **ALLOW** |
| the same on `$(pwd)/` + star | **ALLOW** | **ALLOW** |
| the same on `./` + star | **ALLOW** | **ALLOW** |
| `cd /tmp/x &&` the same on a bare star | **ALLOW** | **ALLOW** |
| `git push --force origin main` | BLOCK | BLOCK |
| `git push --force origin feature/x` | REWRITE to `--force-with-lease` | REWRITE |

Two separate defects are visible.

**The literal-path assumption.** Both guardians match the *text* of the target.
An agent writes the delete against `"$BUILD_DIR"/`, not against a spelled-out
home path. In Claude Code every Bash call is a fresh shell, so a variable
assigned in an earlier call is unset in this one and the target expands to the
filesystem root — the exact string `tests/test-pre-tool-guardian.sh` asserts a
block for when it is typed literally. GNU `rm --preserve-root` does not help,
because the argument after expansion is root-plus-star, not root. The hook's
stated purpose is defeated by the normal way the command gets written.

While drafting this document the hook blocked two of my own writes, because the
prose quoted the dangerous strings literally. It is precise about text and
blind about meaning, which is the finding stated twice over.

**The two mirrors have drifted.** The shell hook blocks `/home`, `/etc`,
`/usr`, `/var`, `/sys`, `/proc`, `/boot`; the Codex mirror's regex covers only
root, `~`, `$HOME` and `${HOME}` at token start, so it allows a recursive delete
of a named home path that the Claude side blocks. `configs/codex-migration.json`
records these two as a parity pair; nothing tests the pair for equal verdicts.

The fix shape already exists in the same file: the force-push branch answers
`{"decision":"allow","updatedInput":{…}}` and rewrites `--force` to
`--force-with-lease`. The same rewrite turns an unset-variable delete into a
loud failure rather than a catastrophe: rewrite `$NAME` to
`${NAME:?guardian: recursive delete on an unset variable}` when the variable is
not assigned in the same command. A set variable runs unchanged; an unset one
aborts naming itself. Command substitution and glob-only targets have no safe
rewrite and should be refused.

Upstream's 5.6 base prompt states the rule this enforces, which is where the
idea came from: "when possible, avoid relying on unresolved environment
variables, globs, or command substitutions to identify destructive targets. Use
explicit, validated paths."

## Lead-verified finding 3: Codex hook payloads use Claude Code's tool names

`codex-rs/core/src/tools/hook_names.rs` serializes shell-like tools to
`"Bash"`, so `plugins/clade/hooks/hooks.json`'s `^Bash$` matcher is correct —
no defect there. The same file shows two things Clade does not use: file edits
serialize as `apply_patch` while accepting `Write` and `Edit` as matcher
aliases "for compatibility with hook configurations that describe edits using
Claude Code-style names", and sub-agent creation serializes as `spawn_agent`
with the alias `Agent`. A Codex-side hook can therefore match a subagent spawn,
which is the event Clade's fan-out accounting would need.
## Lead-verified finding 4: Clade's "cheap" Codex tier is the middle tier

The catalog encodes a lineage. `ModelInfo.upgrade` is a directed edge from a
retiring slug to its replacement, and both the live catalog on this host and
the fallback catalog bundled in upstream 0.153 carry the same two edges:

| retiring model | its description | replacement |
|---|---|---|
| `gpt-5.4-mini` | "Small, fast, and cost-efficient model for simpler coding tasks" | `gpt-5.6-luna` |
| `gpt-5.4` | "Strong model for everyday coding" | `gpt-5.6-terra` |

So OpenAI's own tiering puts Luna in the cheap slot and Terra in the mid slot.
Clade sets `codex_cheap_model` to Terra (`orchestrator/config.py:312`,
`templates/orchestrator-settings.example.json:116`, `docs/codex.md:215`), both
Codex agent profiles to Terra (`configs/codex-agents/clade_cheap_explorer.toml:3`,
`clade_cheap_worker.toml:3`), and instructs Codex in prose to "use
`gpt-5.6-terra` as the default cheap Codex tier"
(`configs/CODEX_AGENTS.md:69`). Luna appears nowhere in the repository.

Those two profiles exist to keep bounded read-only discovery and one low-risk
implementation off the lead's context. That is the cheap slot's job
description, and the model assigned to it is one tier above it. Whether the
saving is worth a config change is a judgment for the owner — the point here is
that the current value was chosen when Terra was the cheapest 5.6 model
documented, and the catalog has since named a cheaper one with the same tool
surface, the same 272k context, and the same effort ladder minus `ultra`
(which a bounded subagent has no use for anyway).

Not verified here: per-token prices. The catalogs carry no price field, so any
figure would have to come from the pricing page rather than from this machine.
