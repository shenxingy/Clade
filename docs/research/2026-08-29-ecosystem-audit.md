---
name: 2026-08-29-ecosystem-audit.md
date: 2026-08-29
status: integrated
review_date: 2026-11-30
summary:
  - "Three research rounds (Claude Code surface, its blind spots, then the wider ecosystem) plus a six-lane documentation audit. Almost nothing upstream was a capability Clade lacked; the rounds' actual yield was 20 defects IN Clade, nearly all of one shape — a control that exists, is documented as working, and never applies."
  - "76 research agents, ~7.5M tokens, ~90 upstream candidates. Four survived a three-lens adversarial pass; the eight that did not are recorded below so they are not re-proposed."
integrated_items:
  - "Worker cost reporting — spawns carried no --output-format, so _parse_token_usage matched nothing and every worker was recorded at $0.00. That zero was the token-budget comparand (so token_budget_exceeded could never fire), the persisted usage.estimated_cost, and routing_break_even's success-per-dollar denominator. Now --output-format stream-json + orchestrator/agent_output.py, which projects the event stream back to prose so every log consumer is unaffected. Measured end-to-end: (0,0) $0.000000 -> (10,41) $0.041565"
  - "Per-model pricing (config.py:_MODEL_RATES) — a flat Sonnet rate understated Opus 1.67x and overstated Haiku 3x on the only figure the budget gate and routing analytics use"
  - "Model aliases -> Opus 5 / Sonnet 5; configs/models.env is now sourced by loop-runner.sh, which had hardcoded claude-sonnet-4-6 while models.env's own header said 'source this file instead of hardcoding' and install.sh was its only consumer"
  - "SECURITY: a worktree bounds the working tree, not .git. From inside a worker's worktree, git rev-parse --git-common-dir resolves to the PARENT repo, so an agent could write <main>/.git/hooks/pre-commit and have it run on the operator's next commit. Reproduced. Detection via worker_git_surface_guard (prevention needs an OS sandbox — see needs_work)"
  - "SECURITY: install.sh upgrades never merged .permissions, so templates/settings.json's deny rules (~/.ssh, ~/.aws, ~/**/.env) reached fresh installs only — while workers spawn with permissions bypassed, where deny is the last remaining bind. Deny-only union; a user's allow list is never widened"
  - "Worktree isolation failed open — every failure path discarded git's stderr and left the worker on the shared checkout. Now raises (worker_require_worktree)"
  - "Stopping a worker deleted everything it had written — stop() skips verification then force-removes the worktree, including on the automatic loop-detection and stuck-timeout paths. Now a wip: commit on the worker's own branch first"
  - "The Claude Code plugin advertised 37 agents and 14 hooks and loaded NONE of them — an agents array of file paths is schema-valid and resolves nothing, and plugin validate --strict exits 0 on it. Now a generated agents/ tree plus check-cc-plugin-components.sh, which LOADS the plugin and compares the resolved inventory to the tree"
  - "The memory watchdog matched none of the commands the orchestrator builds — its pattern required a token between 'claude' and '-p'. It freed nothing under memory pressure, signalled the sh -c wrapper rather than the agent, and ordered by pid rather than age. Had no tests at all"
  - "The worker activity heuristic read a transcript path Claude Code has never written, and its test built that same wrong layout — so it stayed green while always returning 'unknown'"
  - "Quota exhaustion was retried forever — a spent balance and a spent usage window both return 429 and were classified rate_limit. New quota_exhausted class, both abort"
  - "A GitHub issue-create timeout forked one task into a growing pair of duplicates; task_id was stamped into every issue body and never read back"
  - "Orchestrator worktrees moved out of .claude/worktrees/, which CLI 2.1.236 claims as its own managed pool and deletes along with a session"
  - "GATE: check-ci-checklist.py — CLAUDE.md's pre-commit checklist had drifted twice (7 of 11 syntax gates, 0 of 18 shell suites). It now also rejects a documented command that cannot execute, after the shellcheck line was found exiting 126 while the gate reported it covered"
  - "GATE: regen-settings-example.py — docs/configuration.md promised 'every supported orchestrator key'; the shipped reference had 33 of 75, one of them no longer a setting"
  - "GATE: red-phase-audit.py --self-test — the instrument that measures 'an added test already passed at base' could not be asked whether it still works. Its own source records a prior incident where an unrecognised pytest argument made every commit report 0 passed and the 0% fire rate read as good news. One positive and one negative control, run in CI"
  - "Mid-run evidence — verification landed in ONE terminal write, so a crash between 'tests passed' and 'the oracle returned' lost both. Now tests/oracle/push are separate revisions in the existing digest chain"
  - "Per-tool-call checkpoints — configs/hooks/worker-checkpoint.sh commits the worktree into a shadow repo OUTSIDE it after every agent write, so 'correct at call 14, wrong at 15' is answerable. Rests on a measured property: a separate --git-dir means a separate index, so checkpoints cannot contend with the worker's own commits"
  - "REFACTOR: worker.py 1500/1500 -> 1188 (WorkerPool -> worker_pool.py) and task_queue.py 1499/1500 -> 1142 (_ensure_db -> task_schema.py). Both files sat ON the ceiling, so every change began by reclaiming a line and pushed logic into leaves for budget rather than cohesion"
  - "DOCS: 9 high-severity contradictions, three of which broke at runtime — /brief probed a port nothing binds, two consumers parsed a loop-state file no writer produces (the session banner was silently empty), and every session start injected guidance for a superseded model generation. README 378 -> 301 and README.zh-CN 352 -> 300, with four false claims corrected and the architecture narrative added to the Chinese side, which never had it"
needs_work_items:
  - "DECISION: worker_env_deny defaults to [] — the mechanism works (worker.py) but the default means it never applies, so a worker fed untrusted GitHub text inherits the full parent environment. Picking a default list is a judgement about the operator's machine: GH_TOKEN is needed for push, ANTHROPIC_API_KEY conditionally, and guessing wrong breaks workers silently. Candidate starting list: TG_BOT_TOKEN, AWS_*, GOOGLE_*, MINIMAX_API_KEY"
  - "DECISION: an OS sandbox at the spawn chokepoint. The git-control-surface escape is DETECTED, not prevented — a worker must be able to write .git to commit at all, so no git-level setting closes it. Landlock, not bubblewrap: this host reports landlock at ABI 8 in /sys/kernel/security/lsm while bwrap's user-namespace mode fails under kernel.apparmor_restrict_unprivileged_userns=1. Upstream reference: openai/codex codex-rs/linux-sandbox. This is a project, not a patch"
  - "DECISION: four documents track overlapping roadmap state (TODO.md, VISION.md, IMPLEMENTATION_PLAN.md, PROGRESS.md). IMPLEMENTATION_PLAN's stale block has been scoped rather than deleted, but which document is authoritative is a consolidation call"
  - "routes/webhooks.py verifies an HMAC signature, but webhook_secret defaults to '' and the verifier then returns True — an unauthenticated endpoint that can start permission-bypassed workers. It logs a warning on every request, so this reads as a deliberate default. Separately, even a valid signature carries no ACTOR check: any GitHub user's comment is as authorised as the operator's. Upstream reference: anthropics/claude-code-action requires a write-access check and a bot check before starting"
  - "37 medium/low documentation findings from the 2026-08-29 audit remain unaddressed (49 raised, 46 confirmed, 9 landed)"
  - "OpenTelemetry: Claude Code ships claude_code.cost.usage, .token.usage, .subagent.spawn and 8 more behind CLAUDE_CODE_ENABLE_TELEMETRY + OTEL_EXPORTER_OTLP_ENDPOINT. worker.py forwards the parent environment verbatim, so exporting the block before uvicorn reaches every worker with no code change. Blocking condition: ship it with a collector-side redaction processor or not at all. NOTE tracing.py's 'intentionally NOT OpenTelemetry' comment is about causal SPANS, not metrics — do not cite it to dismiss this"
  - "install.sh has no preflight for managed-policy machines: strictPluginOnlyCustomization locks agents/hooks/mcp/skills and disableSideloadFlags rejects --plugin-dir and --mcp-config. On a locked machine install.sh exits 0 and nothing loads, while docs/configuration.md says 'Nothing. Everything works out of the box.'"
  - "Deterministic sanitizer for untrusted GitHub text (HTML comments, zero-width characters, image alt text, hidden attributes). The only current defence is the LLM distillation pass, which is default-off, so with defaults raw GitHub text reaches the task file verbatim"
  - "ci.yml carries no permissions: block. The repo default is already 'read', so this is defence-in-depth against that default changing, not a current problem"
  - "METHODOLOGY: SlopCodeBench (arXiv:2603.24755) measures exactly /loop's setting — an agent extending its own code across evolving specs, converged on by tests plus a judge. Structural erosion rose in 80% of trajectories and mean high-complexity function count went 4.1 -> 37.0 while pass-rate metrics detected none of it. Clade measures zero structural quantity anywhere. Proposed: one advisory scalar per iteration in worker_tldr.py (it already has the parsers), shipped advisory; make convergence a conjunction only once there is a slope to threshold on. Explicitly do NOT add 'write clean code' to the worker prompt — the paper measured that as cutting initial erosion ~34% while leaving the degradation RATE unchanged"
reference_items:
  - "REJECTED by adversarial review (3 lenses, majority refute) — typed per-action risk enum (OpenHands): Clade already has risk-as-data at worker_review.py:230-244, and a risk-triggered pause stalls the exact runs that exist because the operator is asleep"
  - "REJECTED — Anthropic Sandbox Runtime (srt): its bubblewrap prerequisite fails on this host under AppArmor's unprivileged-userns restriction. Landlock is the viable route instead (see needs_work)"
  - "REJECTED — Roo Code tool-group allowlist + fileRegex write scoping: the allowlist half exists twice over (all 37 subagents declare tools: in frontmatter), and an Edit|Write-only hook is bypassed by any Bash write"
  - "REJECTED — Zed per-hunk diff review UI: the real defect was the destructive teardown, not a missing viewer; the operator's own git and editor already do per-hunk acceptance on an exposed worktree"
  - "REJECTED — durable HITL suspension (Restate/DBOS): the send/recv half is task_queue.py:210 worker_messages renamed; nothing in Clade self-suspends awaiting a human, so the deadline half solves a hosted-control-plane problem at n=1"
  - "REJECTED — LangGraph interrupt() semantics: the premise was that Clade name-checks a pattern it does not implement. It implements it at loop-runner.sh:171-203"
  - "REJECTED — per-key concurrency + rate limiter as DB state: under subscription auth the binding limit is a token quota, not concurrency, so a semaphore prevents zero 429s. Admission is already gated by max_workers, cost_budget and run_budget"
  - "REJECTED — persisted compensation stack (saga): the stated failure scenario has the ordering backwards. worker.py runs the oracle gate and returns False BEFORE the push, so no multi-effect forward path survives it"
  - "REBRANDS — mechanisms Clade already runs under another name: ledger-based manager/worker scaffolds = /loop; DBOS send/recv = worker_messages; LangGraph interrupt = check_interrupt(); DBOS PENDING-scan recovery = _recover_orphaned_tasks; Restate idempotency key = deterministic branch name + --force-with-lease; Aider's PageRank repo map = worker_tldr.py; cAST AST-boundary chunking = worker_tldr.py; SpecBench's visible-minus-held-out gap = evals/run_resolve_eval.py; RuVerBench k-vote = worker_review.py"
  - "FABRICATIONS caught by a later round — a PostModelSwitch hook event and a --restricted flag, neither of which exists in CLI 2.1.236 (0 occurrences). Root cause worth remembering: ~/.local/share/claude/versions/<v> is a FILE, not a directory, so a grep against <v>/claude fails with 'Not a directory' and the masked error reads as a clean zero. Prove a flag with claude --help or a binary-safe grep against the file, never from a docs mention | AMENDED 2026-09-05: both have since SHIPPED — PreModelSwitch/PostModelSwitch in 2.1.251 (38 and 17 occurrences in the installed 2.1.258 binary) and --restricted in 2.1.248 (present in claude --help at 2.1.261). The 2.1.236 finding was correct for that build and must not be read as a standing claim; an absence finding is only ever true of one version, so stamp it."
  - "UNVERIFIED, do not quote — vendor claims with no control arm: spec-driven development's 'order of magnitude fewer regenerate cycles' (GitHub) and '40-hour features in under 8 human hours' (AWS); DeepSeek Harness architecture notes (real repo, self-published in-repo claims); the Chinese Claude Code reverse-engineering corpus's compaction constants (archaeology of a leaked v2.1.88 bundle — 0 occurrences in 2.1.236)"
---

**English** — [← Research Index](README.md)

# 2026-08-29 — Ecosystem audit: three research rounds and a documentation audit

## Why this doc exists

Three rounds asked "what has the rest of the world built that we should learn
from". The answer, consistently, was **almost nothing** — and that answer is
only useful if the reasoning survives, so the rejected candidates are recorded
in `reference_items` above with the reason each was killed. Re-proposing them
is the failure mode this file exists to prevent.

The rounds' real yield was internal. Twenty defects, and they share one shape:

> A control exists. The documentation says it works. It never applies.

Deny rules that only reached fresh installs. A token-budget gate comparing
against a number that was always zero. A watchdog whose pattern matched none of
the commands the orchestrator builds. A `models.env` whose own header says
"source this file instead of hardcoding" and whose only consumer was
`install.sh`. An activity heuristic whose test **built the wrong directory
layout itself**, so it stayed green while returning "unknown" for every real
input.

It happened to the gates written during this same audit, twice: one reported
"covers all 35 gates ✓" over a documented command that exits 126, and a set of
new hook tests landed after `exit` in the suite and never ran while the suite
printed 62/62 green.

## The rule that came out of it

**A green test is not a working system.** The only reliable counter is a gate
that runs the real thing and compares:

| Gate | Runs | Caught |
|---|---|---|
| `check-cc-plugin-components.sh` | the actual plugin loader | 37 agents advertised, 0 resolved |
| `check-ci-checklist.py` | the actual workflow files | 4 undocumented gates, then a command exiting 126 |
| `regen-settings-example.py` | the actual `_SETTINGS_DEFAULTS` | 33 of 75 keys, 1 stale |
| `red-phase-audit.py --self-test` | a positive and a negative control | the harness's own inability to fire |
| `tests/test-hooks.sh` checkpoint block | real git operations | that a shadow commit never touches the worktree index |

Each replaced an assertion *about* the system with an execution *of* it.

## Method note

Rounds 2 and 3 were run with an explicit anti-fabrication rule after round 1
invented two features. Round 3 added a three-lens adversarial pass — scope,
duplication, evidence — where a majority refutation kills the finding. Four of
~45 candidates survived it. The eight that did not are the most useful part of
that round.
