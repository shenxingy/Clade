---
name: 2026-09-05-codex-gpt56-and-harness-review.md
date: 2026-09-05
status: integrated
review_date: 2026-12-05
summary:
  - "23 readers, 123 agents, 115 candidates, 76 claimed gaps, 52 upheld by a skeptic instructed to refute. Almost nothing in the GPT-5.6 generation is a capability this toolkit lacks; the yield is four places where THIS REPOSITORY's own record is wrong, all four reproduced by hand before filing."
  - "MEASURED, live path: both destructive-command guardians allow every recursive delete an agent actually writes. They block the literal catastrophic forms and ALLOW the same command against $BUILD_DIR/, ${OUT}/, $OUT/*, $(pwd)/*, ./* and a bare glob after a cd. Every Bash call is a fresh shell, so a variable set earlier is unset now and the target expands to the filesystem root — the exact string the test suite asserts a block for when typed literally. The force-push rows are the control: both hooks ran and acted."
  - "The two guardians have also drifted: the Codex mirror allows a recursive delete of a named home path the Claude side blocks. codex-migration.json records them as a parity pair and nothing feeds one command to both and compares verdicts."
  - "FALSIFIED: 'Codex cannot fan out', written down three times (worker_provider.py:363 UNSUPPORTED, the tests pinning it and forbidding CONDITIONAL, and an open roadmap item). Two headless spawn edges sit in this host's Codex database using Clade's own agent roles, and it was reproduced live: a codex exec --json run created a depth-1 clade_cheap_explorer child on 0.153.4. The gate is the resolved model's catalog multi_agent_version, never the session source. configs/skills/codex-orchestrate had it right all along."
  - "The cheap Codex tier is set to the middle tier: the catalog's own upgrade lineage puts gpt-5.6-luna in the cheap slot (successor of gpt-5.4-mini) and gpt-5.6-terra in the mid slot (successor of gpt-5.4). Luna appears nowhere in the repository."
  - "METHOD FAILURE, caught by the completeness critic and not by the lead: the readers were pointed at openai/codex origin/main, described as current. That commit is dated 2026-07-14 and is 1,931 commits behind the rust-v0.153.4 tag — this project ships from tags, not from its default branch. Roughly ninety candidates cite a July tree. Every kept claim was re-checked against the release tag, the installed binary, or a live run; the verifiers that switched oracle overturned something nearly every time."
  - "New upstream vocabulary worth naming: `ultra` is an EFFORT level meaning automatic task delegation, not a model; every 5.6 model is tool_mode code_mode_only; and the base prompt traded engineering advice for a request-verb authority envelope ('finish' extends persistence, not authority) plus a destructive-action protocol whose rule about unresolved variables is exactly what the guardians fail."
integrated_items:
  - "docs/research/2026-09-05-codex-gpt56-and-harness-review.md — this document: what the GPT-5.6 catalog, the 5.5-to-5.6 base-prompt diff, the feature flags, the CLI surface and this host's Codex state databases actually say, separated from what the readers claimed."
  - "TODO.md — four filed findings with their evidence, plus an in-place FALSIFIED annotation on the 2026-09-02 'Codex cannot fan out' item so nobody acts on the premise."
  - "docs/research/README.md — indexed."
  - "~/.claude/research/known-concepts.md — 18 concepts appended (run 2026-09-05), including reasoning-effort-as-delegation-switch, code mode, catalog-driven capability, upgrade lineage as tier truth, request-verb authority envelope, literal-path guard blindness, guard-by-rewrite, model-judged approval, persisted prefix rules, hook trust by content hash, thread goals, system-owned stop states, and address-preserving context eviction."
needs_work_items:
  - "The guardian delete gap is filed, not fixed. The fix shape already exists in the same file — the force-push branch answers {decision:allow, updatedInput} — so an unassigned $NAME target can be rewritten to ${NAME:?…}; command substitution and glob-only targets have no safe rewrite and should be refused. Needs the mirrored Codex change and cases in tests/test-pre-tool-guardian.sh, which contains no unset-variable or glob case at all."
  - "No test feeds one command to both guardians and compares verdicts, which is what would keep the parity pair honest rather than aligning one regex once."
  - "The Codex subagents capability is still declared UNSUPPORTED with a false reason, and the test that forbids CONDITIONAL has to change with it. Dormant layer, so no runtime consequence today."
  - "AGENTS.override.md silently outranks AGENTS.md at home and project scope, so install.sh can merge its managed block into a file Codex never reads. Warn at install time; also correct the resolution order stated in docs/codex.md and implemented in configs/skills/delivery/scripts/git_context.py."
  - "plugins/clade/hooks/hooks.json SessionStart matcher omits `clear`; the Claude-side file runs on startup|clear|fork and carries the reason in a comment. Same lesson, one surface."
  - "docs/research/2026-08-29-ecosystem-audit.md records PreModelSwitch/PostModelSwitch as features that do not exist. Both shipped in 2.1.251. A fabrication record needs a version stamp or it suppresses the real feature later."
  - "48 further upheld gaps are summarised by theme in this document rather than filed individually — loops and stop taxonomy, the skill-catalog context budget and its unmeasured usage, the learning pipeline's missing decay and citation signal, cost-per-success measurement, and the Codex configuration layers (.codex/ project layer, model_context_window, service_tier, -p profile) this repository has never used."
  - "Not covered, and named so a later sweep does not assume otherwise: `codex exec -p <profile>` (the one place a worker profile could ship as a named config bundle), `codex mcp-server` against Clade's own MCP package, --strict-config, --search, the shell_snapshot and apps/connectors features, and this host's 1.1M-row Codex log database. Benchmark and price figures were left out because every source page returned 403 here."
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
found instead is four places where Clade's own record is wrong, one of them a
live safety hole.

Method: 23 parallel readers over the upstream source, the release notes from
0.150.0 to 0.153.4, the live model catalog and its per-model system prompts,
this host's Codex state databases, and the wider field; then a classification
pass against this repository, then a skeptic per claimed gap. 123 agents, 115
candidates, 76 claimed gaps, 52 upheld. The findings headed "verified" were
reproduced by hand.

**A correction about the source tree, stated first because it discounts
everything read from it.** The readers were pointed at a worktree of
`openai/codex` at `origin/main`, `4df8027a97`, and the brief described it as
current. It is not. That commit was authored 2026-07-14 and is **1,931 commits
behind the `rust-v0.153.4` tag** and 188 behind `rust-v0.145.0`; the release
tags carry commits that the default branch does not. So roughly ninety
candidates cite line numbers in a July tree. The completeness critic caught
this, not the lead. Every claim this document keeps was re-checked against the
real release tag `rust-v0.153.4` (`3d2ee51ca2`), the installed binary, or a
live run — and the line numbers moved: `collab_tools_enabled`, the predicate
the central finding rests on, sits at `spec_plan.rs:647` in the release and at
`:338` in the July tree.

The general lesson is worth more than the correction. The verifiers that
switched to `git show rust-v0.15x.y:<path>` or probed the installed binary
overturned something almost every time; the ones that read the tree did not.
For a tool that ships from tags rather than from its default branch, the
default branch is not the product.

## What is actually new, measured on this host

These facts come from the installed CLI, its on-disk state, and the upstream
source — not from a search result. Anything below can be re-checked with the
command shown.

### Which versions this was read against

| Surface | Here | Upstream | Check |
|---|---|---|---|
| Codex CLI | 0.153.4 — was 0.145.0 when the sweep began | 0.153.4 stable, 2026-09-04 | `codex --version`; `gh api repos/openai/codex/releases` |
| Claude Code CLI | 2.1.261 | — | `claude --version` |
| Clade Codex tiers | cheap `gpt-5.6-terra`, strong `gpt-5.6-sol` | catalog lists `gpt-5.6-luna` as the "fast and affordable" tier | `orchestrator/config.py:312`, `configs/codex-agents/*.toml` |

The CLI updated itself mid-review, which is worth stating rather than hiding:
`threads.cli_version` in the state database records 573 sessions on 0.145.0 up
to 2026-09-04 22:06 and everything after on 0.153.4. The host is now level with
upstream stable. Where a fact below depends on the older build it says so, and
the two are separated because the review's central finding was first observed
on 0.145.0 and then reproduced live on 0.153.4.

Note that `codex --version` here runs through a wrapper script
(`~/.local/bin/codex` → `codex-statusline`), and that
`~/.codex/packages/standalone/current` still points at a 0.144.6 release
directory, so neither of those is a reliable version oracle — the state
database is.

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
three days ago. The released source says why. In `rust-v0.153.4`,
`collab_tools_enabled` (`codex-rs/core/src/tools/spec_plan.rs:647`) is the
single gate on the whole spawn/wait tool family, and it branches only on
`multi_agent_version`: Disabled means no tools, V1 checks the spawn depth, V2
allows them unless this turn is itself a subagent. The session source appears
in it once, to ask whether the caller is already a child — never to distinguish
headless from interactive. `SessionSource::Exec` is listed beside `Cli` and
`Mcp` as a delegation root.

Clade states the opposite in three places:

- `orchestrator/worker_provider.py:363` — `"subagents": CapabilityState.UNSUPPORTED`, sourced as "codex exec has no headless sub-agent spawn". This is the value `resolve_capabilities` enforces, so a task declaring `subagents` REQUIRED is refused on Codex.
- `orchestrator/tests/test_subagents_capability.py` — its docstring states "the truth is that `codex exec` spawns no sub-agent at all", and `test_codex_subagents_is_not_a_shrug` forbids the CONDITIONAL state that the evidence actually supports.
- `TODO.md:624` — an open item, "Codex cannot fan out, and that is why it is slower … the only parallelism available to Codex is Clade spawning N `codex exec` processes from outside".

And it states the correct thing in a fourth: `configs/skills/codex-orchestrate/prompt.md:3` calls itself "the manual version of Codex's native fan-out (`model_reasoning_effort = ultra`)" and even names a slot cap. The skill on the live terminal path was right; the dormant layer's capability table and the roadmap item were wrong.

Then it was reproduced live, on the current build, rather than left resting on
two historical rows. A `codex exec --json` run in a scratch directory, read-only
sandbox, model `gpt-5.6-terra` at low effort, asked to delegate one bounded
lookup:

```
codex exec --json --skip-git-repo-check -s read-only -m gpt-5.6-terra \
  -c model_reasoning_effort=low "Delegate to the clade_cheap_explorer subagent …" < /dev/null
```

The event stream carried a `collab_tool_call` item, so the collaboration tools
were present in a headless turn, and the database gained a third
`source='exec'` spawn edge: child `01a072b1-0c12…`, depth 1,
`agent_role: clade_cheap_explorer`, nickname Volta, 55,549 tokens, parent
recorded at `cli_version 0.153.4`. Headless Codex delegates, today, on the
version this host runs.

Two practical notes from that run. The spawn itself never appears in the JSONL
— only the `wait` call does, and it reports `receiver_thread_ids: []` — so a
supervisor that watches `codex exec --json` cannot see its worker's children
and must read the state database to know they happened. And the child answered
that its search was blocked, which is what a `read-only` sandbox plus a
delegated shell command produces; a real delegating worker needs its sandbox
set for the child's work, not just the parent's.

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

## What is worth taking

Of 115 candidates, 76 were classified as gaps and 52 survived a skeptic whose
instruction was to refute them on three axes: Clade already has it, upstream is
misdescribed, or it is not worth doing for a single-user terminal toolkit. The
survivors cluster into eight groups. What follows is the strongest item or two
from each, with the first concrete step. The rest are in `TODO.md`.

### Command guards and privilege — nine survivors, one of them measured live

The guardian defect above is the headline, and three finders reached it
independently from different directions. Beside it:

- **Decide on the resolved target, not the command text.** Upstream's approval
  judge is expected to *investigate* before deciding — it runs as a hardened
  clone of the actor's own configuration and can read the filesystem. Clade's
  guardians pattern-match a string. Same first step as the delete fix: resolve
  the target, then judge.
- **A post-denial protocol.** Upstream ships three things Clade's block path
  lacks: a timeout is not a denial, an explicit instruction not to reach the
  same outcome by a workaround, and a per-turn denial circuit breaker. One
  sentence appended to every block reason in both guardians covers the middle
  one.
- **An escalation vocabulary.** A declared permission delta and a session
  profile that can only ever be a subset of the parent's, rather than the
  binary allow/deny Clade's learned-allow path writes.
- **"Always allow" is a policy amendment, not a memory.** Upstream refuses to
  learn an allow-rule for bare interpreter prefixes and simulates the rule
  before offering it. `configs/hooks/permission-request.sh` currently matches
  `^python.*-c\b` as a test pattern, which is an interpreter prefix wearing a
  test's clothes.
- **Egress has no guard at all here.** Upstream keeps network policy in the
  same rules file as exec policy, defaulting to deny. Clade's guardian inspects
  no `curl`, `gh api`, `ssh` or `nc` target.

### Configuration layers this repository has never used — seven survivors

- **`AGENTS.override.md` silently outranks `AGENTS.md`**, at both home and
  project scope, first-filename-wins with no merge. `install.sh` carefully
  merges a managed block into `~/.codex/AGENTS.md` — and if an override file
  exists, Codex never reads the file it merged into. The fix is a warning at
  install time, not a deletion. This also makes a claim in `docs/codex.md`
  wrong: Clade states the resolution order as AGENTS.md then CLAUDE.md, in
  three prose sites and once in code (`configs/skills/delivery/scripts/git_context.py`).
- **The repo-owned `.codex/` project layer** — config, agents, hooks and rules
  that travel with the repository under a trust gate — is the Codex analogue of
  what `configs/` does for Claude, and Clade ships none.
- **`model_context_window` is the key that unlocks the larger window.** The
  catalog's `max_context_window` is a ceiling on *your override*, not a window
  the model gets by itself, so nothing here has ever used it. A read-heavy
  explorer profile is where it pays.
- **The model catalog is server-gated by CLI version** and cached in one shared
  file keyed on it, so two client versions on one host get different catalogs —
  which is exactly what happened here during this review. Any future check that
  validates a pinned Codex model must fail closed on a version mismatch rather
  than trust the cache.

### Hooks — seven survivors, two of them live parity defects

- **The Codex `SessionStart` matcher drops `clear`.** `configs/settings-hooks.json`
  runs the Claude-side hook on `startup|clear|fork` and carries the reason in a
  comment: clearing discards the injected context but keeps the process alive.
  `plugins/clade/hooks/hooks.json` says `startup|resume|compact`. The lesson was
  learned on one surface and not carried to the other.
- **Codex exposes ten hook events; Clade wires two.** More useful than the
  count: a handler can be a `prompt` or an `agent` rather than a command, and
  `async` exists. The stated reason for the narrow port in
  `configs/codex-migration.json` is now stale — the real remaining obstacle is
  that the correction pipeline writes into `~/.claude/corrections/` and reads a
  Claude-shaped transcript, not that the events are missing.
- **`PreModelSwitch` / `PostModelSwitch` now exist.** They matter here mainly
  because `docs/research/2026-08-29-ecosystem-audit.md` records them as
  fabricated features that do not exist. That record was right when written and
  is now false, and left alone it will suppress a real feature on the next
  sweep — the exact inverse of what it was written to prevent. Fabrication
  records need a version stamp.

### Loops, budgets and stop states — seven survivors

This is where upstream's design is genuinely ahead, and all of it is prompt and
bookkeeping rather than new machinery:

- **A six-state stop taxonomy** that separates "I failed" from "the provider
  ran out" from "the budget ran out" — `blocked`, `usage_limited`,
  `budget_limited` are three different states, and the *runtime* owns them, not
  the model. Clade's loop has one notion of stuck.
- **A completion audit as a standing prompt contract**: enumerate every
  requirement, name the authoritative evidence for each, and remember that a
  narrow check cannot support a broad claim and that the audit must *prove*
  completion rather than fail to find remaining work. Clade ticks goal items
  bound at plan time, and its verify node never sees the goal text.
- **An anti-scope-shrink clause**: do not redefine success around a smaller or
  easier-to-test task. This is the failure mode the loop cannot currently see,
  because the thing that ticks the box is the thing that chose the box.
- **Budget as a soft wrap-up, not a kill**, with per-tool-call accounting and
  an atomic trip.
- **The agent is told its remaining context and can ask for it**, then requests
  its own reset. Clade's status line does not show it and no skill can query it.

### The skill catalog — five survivors, and a number nobody had

Upstream renders its skill catalog under 2% of the model's context window, with
a three-tier degradation ladder, and emits the truncation as a metric. Clade
ships 138 skills whose descriptions are always resident, and until this sweep
nobody had measured what that costs or which of them are ever used. The finders
disagreed three ways about the exact size, which is itself the finding. The
cheap first step is an extension of `configs/scripts/validate-skills.py`, which
already parses every description and is already a CI gate.

Two more from this group are about attribution: upstream infers that a skill
was used from the *shell commands the agent ran*, not from an explicit
invocation — which is the only way to catch a skill that was read and ignored,
or followed without being invoked.

### The learning pipeline — seven survivors

The correction-to-rule pipeline writes into always-loaded files with no content
screen, no usage signal, no decay and no prediction. Upstream's memory design
supplies three of those: **what the reader cites is what memory keeps** (usage
accounting gated on citation), a **pollution mode** that quarantines a session
whose context came from untrusted input, and a **propose-only write path** where
the working agent files a note and a confined consolidator applies it. Clade
already enforces propose-only for goal files; it does not for rules.

The sharpest item here is external: **skill misevolution** — an unsafe success
distilled into persistent cross-task state. Clade screens *foreign* state for
injection (`configs/scripts/equip_audit.py`) and does not screen the state it
writes about itself.

### Measurement — six survivors

- **Cost per successful execution, not tokens.** Token reduction is
  anti-correlated with success often enough that the token count alone is a
  misleading objective. `workflow-scorecard.py` counts tokens and wall-clock and
  has no success denominator.
- **`codex exec --json` usage is a running thread total, not a per-turn delta.**
  Anyone summing `turn.completed.usage` across turns multiplies the bill.
  `mcp-package` already parses this stream and reads none of its accounting.
  Note the flag takes no value: `--json` prints to stdout, `-o` writes the last
  message.
- **`codex doctor --json`** is a stable, redacted, per-check contract with
  cause / measured / expected / remedy per row — the shape Clade's own health
  checks should emit rather than prose.

### Delegation — four survivors, after the premise was corrected

The premise correction is the finding; what remains open is containment and
accounting. Codex subagents get four concurrency slots and **share one working
directory**, with the shipped prompt telling them that edits are immediately
visible to each other. So one worktree does not equal one writer any more:
a `codex-orchestrate` worker that spawns children has several writers inside
the isolation boundary Clade drew around it. The dispatch prompt should say
that children are for read-only discovery.

Two ideas worth stealing from elsewhere: a failed subagent that returns a
**resumable task id and partial state** instead of an empty result (OpenCode),
and **transitive abort** — cancelling a delegation cancels its whole subtree,
and a checkpoint restore that cannot be made safe *refuses* rather than
silently restoring (Cline).

## What was claimed and did not survive

Twenty-four gaps were refuted, and recording them is the point of doing the
pass — each is a thing not to re-propose next quarter.

Seven were **already built**: catalog-driven multi-agent versioning and the
headless spawn (both filed by this very review, hours earlier), deferred tool
exposure with search-based discovery, the MCP compact mode that collapses the
tool surface, remote plugin marketplaces, the agent-role TOML layer, and
addressable-recall compaction — which Claude Code already implements as the
`<persisted-output>` stub with results spilled to `tool-results/<id>.txt`.

Seven were **different, not deficient**: Clade's oracle already runs tool-less
and diff-scoped, its `/review-pr` already works in a detached worktree, its
hook trust model is offline-reproducible, and the commentary-channel contract
solves a Codex UI problem that does not exist on the Claude surface.

Nine were **not applicable**: they need a persistent thread-state database that
`codex exec` never has, a patched shell Codex ships and Clade does not, an OS
sandbox that does not work on this host at all
(`kernel.apparmor_restrict_unprivileged_userns=1` makes `bwrap` fail), or they
only improve the dormant orchestrator.

One notable refutation reversed a claim in this document's own family: the
`codex exec review` finding was upheld as a gap but its **headline was false** —
no typed finding object reaches the terminal, so a cross-vendor reviewer gets
prose either way.

## What this sweep did not cover

Stated because a review that does not say where it stopped reads as complete.

The stale-tree problem above is the largest limit. Beyond it, the completeness
critic named mechanisms that no reader opened: `codex exec -p <profile>`, which
is the one place a Codex worker profile could be shipped as a named config
bundle and is probably the most actionable unexamined surface; `codex mcp-server`
and the Codex MCP interface, even though Clade ships an MCP package and the
interaction between the two is undefined; `--strict-config`, `--search`,
`--approve-for-me`; the `shell_snapshot` and `apps`/connectors features; and
this host's 1.1-million-row Codex log database as a data source.

Two claims in the brief were themselves wrong and propagated: the flag list
included `codex exec -a`, which the installed binary rejects, and omitted
`--approve-for-me`.

Benchmark and price figures were deliberately left out of this document. The
pages carrying them return 403 to every fetch attempted here, so every such
number in the raw results is a third-party reproduction. The one number a
reader might want — that the 5.6 tiers differ by roughly an order of magnitude
per token — is worth checking on the pricing page rather than citing from here.

Finally, a caution about the proposals themselves: many of them edit
`configs/skills/codex-orchestrate`, and nothing in these results establishes
that this skill has ever actually been run. One reader measured skill usage
across roughly four thousand transcripts and found a small minority of the 138
skills invoked at all. Before building on a skill, check that it is used.
