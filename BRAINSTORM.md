# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md / TODO.md or acted on, they're cleared.*

## How this file works

- **Add an idea**: append a `## {date}` section with the idea, why it matters, and any sources.
- **Resolve an idea**: strike it through with `~~text~~` + a one-line "RESOLVED / DEFERRED + date + where-it-landed" reason.
- **Periodic cleanup**: when strikethroughs dominate the file, move them to `docs/archive/BRAINSTORM-resolved.md` so the inbox stays focused on live thinking.

Past resolved/deferred items live in [`docs/archive/BRAINSTORM-resolved.md`](docs/archive/BRAINSTORM-resolved.md).

---

## [Research] 2026-07-09 — "cue" mystery + 2026-H1 agentic concepts (queue-vs-loop, native workflows, skills ecosystem)

Trigger: user heard people online saying "cue", not just "loop". **Verdict: no tool named
Cue exists** (ghuntley.com/cue is a 404; no "Cue" coding agent in any 2026 roundup). The
word is **"queue"** — the Beads/Gas Town discourse: "don't just run a loop, keep a durable
work queue." Same session also surveyed what else is new in 2026 H1.

### Tools/concepts surveyed
| Concept | What it is | Verdict for Clade |
|---|---|---|
| **Beads** (Yegge, Oct 2025, 23k★, MIT) | Git-versioned agent work ledger — every task/fix/note is a queryable, durable "bead"; widely adopted standalone as agent memory | **Different-not-deficient.** Clade covers the capability: `task_queue.py` (SQLite CRUD), TODO/PROGRESS/handoff files (git-tracked ledger), `github_sync.py` (issues = portable cross-machine ledger). Watch item: beads' "agent files a note-to-itself as a first-class queue item" mechanic |
| **Gas Town** (Yegge, Jan 1 2026, MIT) | Multi-agent orchestration atop Beads — Mayor (coordinator), Polecats (workers), Refinery (merge serialization), Witness (monitor); "Kubernetes for agents" | **Capability parity**: WorkerPool/SwarmManager ≈ Polecats, oracle+supervisor ≈ Mayor, serialize-writers rule + worktrees ≈ Refinery, LoopDetectionService/status_loop ≈ Witness. Counter-voices (Parsons "Your Agent Orchestrator Is Too Clever", bitter-lesson argument; Mike Mason "coherence through orchestration, not autonomy") independently validate Clade's VISION choice of sequential focus |
| **Ralph loop consensus** (2026) | "Every AI coding harness is just a Ralph loop"; Anthropic/OpenAI/Stripe all shipped loop-shaped features; progress lives in files+git, not context | Parity — /loop + goal files + handoff IS this pattern; recorded for terminology |
| **Claude Code native absorption** (Jun 2026, Code w/ Claude Tokyo) | **Dynamic Workflows** (harness writes deterministic JS orchestration scripts, parallel subagents), **Routines** (cron/webhook-triggered agents), Desktop, Deployments | **Strategic overlap with Clade's orchestrator layer** — parallel fan-out and scheduling are becoming table stakes in the harness itself. Clade's moat is what the harness does NOT do: oracle gate, corrections-learning loop, cross-machine usage tracking, GitHub-issue sync, /equip curation |
| **Agent Skills open standard** (agentskills.io, spec published Dec 18 2025) | SKILL.md is now cross-vendor (~40 products incl. Codex, Copilot, Cursor, Gemini CLI); 490k+ skills on SkillsMP/Skills.sh/ClawHub | Clade's format is already conformant (name/description core + extra keys). Distribution is solved; **curation is the scarce thing** — /equip's curate-first trust model is the right bet |
| **ToxicSkills / skills security crisis** (Snyk 2026) | Audit of 22,511 marketplace skills → 140,963 issues; **prompt injection in 36% of skills tested** | **Confirmed gap → FIXED this session**: equip_audit had SEC/NOI/DRF/BLT/QLT/PERM but zero injection screening. Added INJ-01..04 (override/concealment=block, zero-width chars=warn, exfil-sinks=warn, base64 blob=info), backtick mention-exemption, zero-FP corpus gate test (commit 0272dc7) |
| **Design-system-as-skill** | Company design systems shipped as SKILL.md+assets repos (scamai/design-system is one instance of a real trend) | **Integrated this session**: /equip Layout E skill-at-root absorption (d9cc03b) + frontend-design detection cascade/hard-rules/decisions-log (cd078e7) |

### Gaps vs current VISION
- **Native Dynamic Workflows/Routines eat the orchestrator's undifferentiated middle.** VISION's "cockpit" pillar should double down on oracle-gated quality + learning loop + fleet/usage view, and consider *delegating* raw fan-out to the harness where available.
- No durable-ledger gap confirmed (queue ≠ missing; it's already SQLite+files+issues) — do not build a beads clone.

### Recommended additions to TODO.md (not auto-added)
- [ ] Positioning review: which orchestrator features are now harness table-stakes (parallel fan-out, cron) vs Clade moat (oracle, corrections, usage, sync) — update VISION.md accordingly
- [ ] Watch beads' agent-filed note-to-self mechanic; if loop-runner workers start losing cross-iteration context, that's the trigger to adopt
- [ ] Consider running INJ screening at /equip **sync** time too (audit gates adoption, but a later upstream update could introduce injection between audit and sync)

Sources: [ghuntley.com/loop](https://ghuntley.com/loop/) (cue→404), [yegge.ai/gastown](https://yegge.ai/gastown), [Gas Town HN thread](https://news.ycombinator.com/item?id=46734302), [Parsons — orchestrator too clever](https://www.chrismdp.com/your-agent-orchestrator-is-too-clever/), [Mason — coherence through orchestration](https://mikemason.ca/writing/ai-coding-agents-jan-2026/), [InfoQ — Dynamic Workflows](https://www.infoq.com/news/2026/06/dynamic-workflows-claude-code/), [Anthropic — introducing dynamic workflows](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code), [Agentman — skills ecosystem 2026](https://agentman.ai/blog/agent-skills-ecosystem-report-2026), [Register — Ralph Wiggum loops](https://www.theregister.com/2026/01/27/ralph_wiggum_claude_loops/), [Medium — every harness is a Ralph loop](https://medium.com/ai-all-in/every-ai-coding-harness-is-just-a-ralph-loop-69690dc69e7c)

---

## [Research] 2026-07-06 — Round 4: deep-mining the 17 newly-tracked experts

89 agents, 5.8M tok, 1387 tool calls. Mined 3-6 mechanisms per person (83 raw) → triage-dedup → 70 distinct candidates → adversarial verify (4-check framework: deficient-not-different / capabilities-not-names / single-tool-local-first scope / mechanism equivalence). Result: **25 confirmed_gap (36%), 15 parity, 28 different-not-deficient, 2 N/A.** Confirmed-gap rate meaningfully higher than prior rounds — verification surfaced 3 genuine LIVE BUGS in Clade's own shipped code (not "adopt an external pattern"), found only because checking each candidate against the real code forced a close read of adjacent logic.

**3 confirmed live bugs (fix under the bug-fix-without-permission rule, no separate ask needed):**
- [ ] Plan-drift: `oracle_result`/`oracle_reason` computed in `worker.py` but never persisted to the DB; `session.py:_run_plan_build` marks a checklist item `[x]` the instant status hits ANY terminal value — before the test/oracle gate resolves. A rejected/reverted commit still shows checked off.
- [ ] Dead code: `context_budget_warning` writes `context-warning-<id>.md`; zero readers exist (confirmed via grep) since it was introduced.
- [ ] Orphan-process safety hole: workers `setsid` (survive orchestrator restart); `_recover_orphaned_tasks()` only relabels DB rows without checking/killing the still-alive process; `retry_task` can silently collide into a shared worktree.

**22 external-pattern-adoption gaps, prioritized (leverage desc, effort asc — full prose + per-item source/mechanism in workflow transcript wf_06e7a1a3-f1f):**

*High/S (6):* cost-transparency PR line item (Simon Willison) · AGENTS.md honeypot canary for unreviewed AI PRs (Mitchell Hashimoto) · oracle magnitude-anomaly criterion for perf claims (Hashimoto) · oracle test-assertion-integrity criterion (Kent Beck) · domain-model skill: living glossary + gated ADRs (Matt Pocock) · risk-based oracle dispatch classifier (Takanori Sano)

*High/M (5, incl. the pgid bug + plan-drift bug already listed above):* idempotent ensure-dev-server.sh + shared discovery JSON (Thorsten Ball) · tagged log-merge incl. browser console (Ball) · qa-explore skill: git-log-scoped exploratory regression hunt (antirez)

*Medium/S (10, excl. context_budget_warning wiring already listed above):* Agent-Signature commit trailer / model provenance (Steve Yegge) · epistemic caveat on hydrated GitHub content (Armin Ronacher) · steer-now-vs-follow-up message mode (Ronacher/Pi) · corrupt-JSONL-line logging instead of silent swallow (Ronacher) · clean-room hydration distillation pass (antirez) · --dry-run for loop-runner.sh + oracle_cli.py (Peter Steinberger) · Vouch-style trusted-contributor gate (Hashimoto) · serialize-build/test-subagents CLAUDE.md bullet (Geoffrey Huntley) · converged-vs-hit-max-iter status distinction (Pieter Levels) · /equip audit scope extension + wildcard-consent + pinned-ref (tw93)

*Medium/M (2):* task-class-aware resampling (Ronacher) · quantified MCP/tool-schema context-budget audit (tw93)

**1 uncertain**: #32 RUBRIC.md-style agent-usability CI check (DHH) — its verification record is a placeholder ("reasoning": "test"), never actually adjudicated; re-verify before trusting its different_not_deficient label.

**2 N/A**: Release Gate Map (Yegge, presupposes multi-branch release-train topology Clade doesn't have) · pre-warm worktree provisioning (Rauch, targets VM/sandbox cold-boot latency Clade doesn't have).

> **LANDED 2026-07-06** — all 25 confirmed gaps implemented and tested (869→887 orchestrator tests added across the round). 9 of the external-pattern-adoption items ran as parallel worktree-isolated agents (qa-explore skill, Agent-Signature trailer, hydration caveat+distillation, steer/followup mode, corrupt-JSONL logging, dry-run flags, converged-vs-exhausted status, /equip audit extension, MCP budget audit) — all merged clean, caught 2 real cross-cutting bugs during merge review (worker.py breaching the 1500-line cap, a leaf-module import needing the allowlist extended) plus a standalone eval script's sys.path gap. 2 governance items (AGENTS.md honeypot canary, Vouch-style trust-gate) committed locally only, held from push per instruction — they change the public repo's trust surface and need separate sign-off.
>
> **Convergence self-review loop (5 rounds, narrowing to dry — same discipline as Round 3's HIGH-RCE catch):** R1 (6 lenses, full ~5500-line diff): **7 confirmed**, incl. 2 HIGH — loop/plan-managed tasks ([Loop-N]/[Plan-N]) bypassed their own tracked retry pipeline on oracle rejection, racing an untracked duplicate worker onto the same item; the CI-run log-tail hydration path was the one source left with neither the epistemic caveat nor optional distillation, despite being the MOST attacker-controlled (raw program output from a PR's own code). Plus: a pre-existing (not Round-4-introduced) plan_build off-by-one that silently wasted the final allowed loop iteration doing zero work; a shell-injection risk in /verify's own browser-console-log instructions (this round's own quiet-run feature); a missing CI wire for a 27-test suite; Agent-Signature not disclosing fallback-model uncertainty. R2 (targeting the R1 fixes): **2 confirmed** — the loop/plan guard from R1 only covered 1 of 4 sibling requeue sites (reproduced live); exempting loop/plan tasks from the oracle-reject escalation path made it permanently unreachable for them (no marker-based depth tracking applies), fixed via a new per-item reject-streak column. R3 (targeting the R2 fixes): **2 confirmed** — TaskQueue.upsert_loop's INSERT branch silently dropped the new column entirely (caught: this had made the R2 test itself pass for the wrong reason); 2 log lines still claimed "re-queued" when the requeue had actually been skipped. R4 (targeting the R3 fixes): **1 confirmed** (LOW, pre-existing) — the SAME unconditional-log-on-conditional-action bug class in adjacent typed-handoff code, zero prior test coverage. R5: **dry**. Findings-per-round: 7 → 2 → 2 → 1 → 0. Lesson: fixing a confirmed finding is itself a new surface — each fix round needs its own adversarial pass, not just a final test-suite-green check.

---

## [Research] 2026-07-06 — New elite-learnings candidates discovery (external ecosystem)

User question: 找新大佬 — Anthropic 之外的公司/组织/独立开发者/古法程序员拥抱 AI 时代的样本。7-angle sweep (43 agents, ~2.3M tok) → 43 raw candidates → dedup → 34 distinct → adversarial skeptical verify (each independently re-fetched URLs/dates, did not trust scout summaries) → **30 CONFIRMED_ADD, 4 WEAK_EVIDENCE**.

**Key structural fact the sweep surfaced**: all 6 currently-tracked names (Mic92, felixrieseberg, domdomegg, lovesegfault, controversial, claude-cookbooks) are Anthropic-affiliated. Every one of the 30 new confirmed candidates is external. This is a real scope fork (roster stays Anthropic-insider-only vs. broadens to "who's doing serious agentic-coding practice, period") — not decided yet, flagged to the user for a call rather than assumed.

**Process note**: verification caught a scout hallucination — "Shopify" candidate cited dense `Claude Opus 4.8` commit trailers that do not exist in the real commit history, and invented a non-existent model name. Downgraded to WEAK_EVIDENCE/flagged rather than silently trusted. Validates the mandatory adversarial-verify-with-refetch step (do not skip it as a formality).

### Confirmed adds by category (30 total; full evidence/URLs in workflow transcript, not reproduced here)

**Old-guard veterans (10, all high)** — deep systems/PL cred + dated 2026 agentic-era evidence: Steve Yegge (Sourcegraph/Amp; Beads/gastown), Thorsten Ball (Amp Inc co-founder; "Writing An Interpreter/Compiler In Go" author; AGENTS.md/headless-agent notes), Simon Willison (Django co-creator; cost-logged agent-driven OSS releases), Armin Ronacher/mitsuhiko (Flask/Jinja2; "The Coming Loop" harness critique), Salvatore Sanfilippo/antirez (Redis; independently re-derives Claude Code's Edit-tool design space), Peter Steinberger/steipete (OpenAI; OpenClaw; shipped prompt-injection-defense PR), Mitchell Hashimoto (HashiCorp; Ghostty AGENTS.md honeypot for undisclosed AI PRs), DHH (Rails/37signals; tmux dual-model workflow), Guillermo Rauch (Vercel; open-agents tool-approval-gating), Kent Beck (XP/TDD; "prefer MCP tools over eval" lesson).

**Independent builders (7, all high)** — incl. non-English-language: Geoffrey Huntley (originated the "Ralph Wiggum" loop pattern), Pieter Levels/@levelsio (ships via Claude Code `/goal` autonomous background on prod VPS), Matt Pocock (skill-authoring failure-mode taxonomy, 158k★ repo), tw93 (Chinese; Waza turns personal heuristics into Claude-runnable skills), fennu2333 (Chorus-AIDLC; isolated Reviewer-Agent anti-self-review-bias pattern — direct analog to `oracle_cli.py`), Takanori Sano / 4q_sano (Japan; 6-agent diff-risk-routed review orchestrator), minorun365 (Japan; spec-driven PLAN/SPEC/TODO/KNOWLEDGE.md automation pattern).

**Other company/org (11, 10 high + Ben Balter medium)** — one-shot mining tickets, not ongoing roster shape: Warp (Zach Lloyd, "Oz" agent-orchestration platform), Replit (Amjad Masad, nightly trace→PR→A/B-gate self-improvement loop), Amp Inc co-founders Nicolay Gerold + Camden Cheek (Handoff feature, `Amp-Thread-ID` commit provenance), Cloudflare (agent-think autonomous issue-fixer), Grab ("Entrypoint Skill" — 400 services, 100+ MRs/1.5mo), Block/Goose (multi-model co-authorship provenance at Fortune-500 scale), All Hands AI/OpenHands (self-hosted agentic SDLC), Mercari (long agentic pair-sessions with granular trailers), Samsung (embedded/systems-level agentic bug-fixing, post gen-AI-ban reversal), Ben Balter/GitHub (single-prompt issue→PR demo).

**Aggregator/meta-sources (2)** — recon-only, re-scan periodically rather than mine directly: The Pragmatic Engineer (Gergely Orosz; profiles a new named engineer almost every issue — Boris Cherny/Claude-Code-creator flagged as a standalone future deep-dive anchor), Latent Space (swyx + Alessio; Omnigent/multi-harness episode).

**Weak/watch-list (not added)**: Factory.ai founders (vendor marketing, thin repo), 2 Amp Inc engineers with genuinely good content but stale (>2mo) dates, Shopify (hallucinated evidence — see process note).

### Decided 2026-07-06

- [x] **Scope: roster EXPANDED.** The 17 individual-shaped entries (10 old-guard + 7 independent) are now full ongoing tracked-experts members, same standing as the original 6 (Mic92, felixrieseberg, domdomegg, lovesegfault, controversial, claude-cookbooks) — future rounds re-scan their blogs/repos. The 11 org-level entries (Warp, Replit, Cloudflare, Grab, Block/Goose, OpenHands, Mercari, Samsung, Ben Balter, plus Amp Inc's Gerold/Cheek folded into org context) are one-time targeted mining pulls, not re-scanned indefinitely. The 2 aggregators (Pragmatic Engineer, Latent Space) stay recon-only — used to surface next round's candidates, never mined directly.
- [x] **Full deep-mining pass authorized NOW** on all 17 individuals — see the Round-4-style study immediately below.

**Updated tracked-experts roster (as of this entry): Mic92, felixrieseberg, domdomegg, lovesegfault, controversial, claude-cookbooks + Steve Yegge, Thorsten Ball, Simon Willison, Armin Ronacher, antirez, Peter Steinberger, Mitchell Hashimoto, DHH, Guillermo Rauch, Kent Beck, Geoffrey Huntley, Pieter Levels, Matt Pocock, tw93, fennu2333, Takanori Sano, minorun365 (23 total).**

## [Research] 2026-07-05 — Elite workflows ROUND 3 (what's NEW since 2026-06-12)

User question: 看看最近从大佬们那是否有别的可以学的东西. First round that targets the ~3-week *delta* rather than re-sweeping the 6 sources. 4-phase workflow (35 agents, ~2M tok): 8 parallel web scouts (CC releases Feb–Jul 2026, new cookbooks/blog, Agent SDK+MCP, the 6 experts' recent public work, rival frameworks, eval/verifier, context/memory) → 49 raw findings → triage-dedup vs the two prior rounds' ledger → 25 candidates → one adversarial verifier each (default stance: already-covered/N-A) → synthesis. Result: **3 confirmed gaps, 22 parity/different/N-A.** Most "papers" this round were future-dated/likely-synthetic; the surviving gaps are grounded in Clade's OWN code, not the papers.

> **RESOLVED 2026-07-05** — all 3 gaps + the security sliver landed same day. Gap A (headline wiring bug) `677aa5d`; gaps B (oracle majority-vote) + C (--fallback-model failover) + spawn-env denylist `218c387` (all default-off). Suite 517→708-ish region; +17 new tests.

> **HARDENED 2026-07-06 (adversarial self-review convergence loop)** — ran review→fix rounds until 2 consecutive dry. R1 (7 findings, `5bf6500`+`c0e2f32`): **caught a HIGH command-injection I introduced in Gap C** — `worker_fallback_model` was spliced UNQUOTED into the worker shell command and skipped the `_ALLOWED_MODELS` guard (RCE via unauth `POST /api/settings`); now validated vs single-source `config.ALLOWED_MODEL_IDS` + `shlex.quote`. Plus: bad `oracle_verdict_samples` crashed the gate → degrade-to-1; several test-gaps closed. R2 (2, `f7e979a`): `worker_env_deny` non-list scalar bricked every spawn → coerce; resample tests were tautological (led with the majority verdict) → reordered to lead with the LOSING verdict + call-count, mutation-proved. R3 dry (1 refuted), R4 dry (0). Lesson: the generator≠reviewer discipline paid off — my own injection only surfaced under an independent adversarial pass.

### A. Post-compaction goal re-injection — [high / M] ✅ LANDED `677aa5d`
"Defined ≠ called" bug in Clade's own hooks. PreCompact SAVES `.claude/compact-state.md` (pre-compact.sh) and session-context.sh can RELOAD it, **but the only SessionStart entry was `matcher:"startup"`** — and CC fires SessionStart with `source:"compact"` on both auto- and manual compaction (confirmed via claude-code-guide against v2.1.201 docs: matcher = "Auto or manual compaction", exact-match against source). So after any in-session auto-compaction the pinned task goal was silently lost. Second decay path: rule-injector's `<session>.rules-injected` sentinel meant a compaction-dropped path-scoped rule never re-injected. **Fix:** new lean `post-compact-reinject.sh` on a `matcher:"compact"` SessionStart group (re-emits compact-state verbatim, deliberately NOT the heavy startup session-context.sh) + clears the rule sentinel so rules re-arm on next matching edit + 8-case test wired into CI shell-tests. (Residual: live-compaction empirical check that CC injects the additionalContext post-compaction — mechanism is the documented one + proven on the startup source.)

### C. `--fallback-model` chain (transport-level overload failover) — [low / S] ✅ LANDED `218c387`
`--fallback-model <model>` exists in installed CC v2.1.201; worker spawns (`worker.py:299`, `:994`) never pass it. On a mid-turn 529/overload during a long background worker, native CC exhausts retries and the process exits; Clade's only recovery is `error_classifier` re-queuing a WHOLE FRESH TASK (new session, in-session progress lost) — and that path is gated behind `auto_classify_retry`, default OFF. Native flag is lossless (in-process, per-turn). **Build:** append `--fallback-model` in `_build_cmd_and_env` (+ retry spawn + isolated judge/tldr spawns that strip user settings), derive target from the existing `config.py:129 auto_classify_retry_model_fallback` map, gate behind one new default-off `_SETTINGS_DEFAULTS` flag. Deferred to greenlight because it threads the flag through the core engine across ~5 sites + a single-vs-chain choice (help shows singular `<model>`).

### B. Oracle verdict majority-of-N (beat judge non-determinism) — [medium / M] ✅ LANDED `218c387` (default-off prototype)
Oracle verdict is single-shot; two-pass spec+quality is dimension decomposition, not resampling; confidence gating only demotes LOW-confidence *rejections* (protects the reject direction), so the dangerous false-APPROVE path that gates auto-merge has zero variance mitigation. `oracle_retry_sample_count`/`parallel_fix_samples` is *generator* diverse-sampling (Agentless 6C), a name-collision not judge resampling. **Build:** run `_oracle_pass`/`_oracle_review_chunk` K× + majority-vote, new `oracle_verdict_samples` (default 1), K=3 only on the critical/auto-merge path, require a *clean majority to APPROVE*. Tradeoff = 3× Haiku on the critical path; report says confirm with a verdict-stability fixture before making it default (JSON-rubric grading likely flips less than the paper's naked-preference regime).

### Security sliver ✅ LANDED `218c387` (mitigation shipped default-off; enable per-deploy)
Autonomous workers run `--dangerously-skip-permissions` with full `env={**os.environ}` passthrough while `worker_hydrate` pre-hydrates untrusted GitHub issue/PR text → a narrow prompt-injection exfil surface. CC `sandbox.credentials` can't engage (sandbox off by design). A Clade-shaped mitigation = optional spawn-time env denylist (`worker_env_deny`, pop keys in `_build_cmd_and_env`). Real but has functional tradeoffs (workers still need ANTHROPIC/gh creds) — human decides if the surface justifies it. [low / S]

### Parity / different-not-deficient (proves we checked, didn't skip)
PROJECTMEM judgment/retention → DreamConsolidator 7-gate + correction-pairing recurrence. QA execute-the-app agent → `/verify` (Playwright walk + anchor exec) + `/review`. Oracle pinned-judge/delimited-span/abstain → HAIKU_MODEL pin + diff_text span + confidence-gated demote. Task-typed verifiers + co-evolving rubric → `_read_constitution` + `_detect_fix_intent`. DivInit → worker.py:1308 plateau fan-out + `_DIVERSE_HINTS`. ast-grep structural-lint + meta-completeness gate → `test_conventions.py` + `validate-skills.py` + /audit→/generate-hook. Skill=tested-CLI → oracle_cli.py + test_oracle_cli.py. Cache-stable steering → mailbox-drain tail append (opposite of opencode's prefix-mutating bug). Trajectory-critic best-of-N → LoopDetectionService + end-of-run oracle + SWE-bench execution-grounded evidence. task_budget → token_budget DB column (cumulative). --json-schema → `_oracle_pass` + `_strip_json_fence`. Native /rewind → git-worktree discard + evaluator-optimizer. Domain-tuned compaction → /handoff STRUCTURED v2 + condenser keep_recent. Worker-pool scheduling → claim_next_pending + is_critical_path + _rank_tasks. Stale-npx MCP refresh → Clade's server is PyPI/uvx (immune).

### N-A (out of scope for local-first single-tool)
`sandbox.credentials` (CC binary-native; interactive users inherit via own settings.json; runtime masking already = redact.py + secret-scanner.sh). relic turn-pair eviction / self-healing transcript (wire-layer for a direct-to-API vintage-OS client; Clade delegates that layer to the `claude` subprocess; analogues = event_stream.py torn-tail tolerance + error_classifier).

---

## [Research] 2026-06-12 — Elite workflows ROUND 2 (deeper re-sweep, same 6 sources)

User question: 再学习一轮他们，看看我们的学习成果和他们的是否还有gap. Round 2 dug below round 1's surface: actual dotfiles/.claude/pi-extension internals (Mic92, lovesegfault), project repos as machine-operations manuals (felixrieseberg), fleet-automation mechanics + blog doctrine (domdomegg), merged-PR craft threads (controversial), plus Anthropic engineering blog 2025-26, claude-code official hook/subagent docs, and the claude_agent_sdk + CMA cookbooks. ~70 new mechanisms surveyed; every candidate verified against the codebase before a verdict.

> **RESOLVED 2026-06-12** — 4 confirmed gaps, all landed same turn with covering tests (suite 517→521): non-interactive git env `d01a8d7`; fix-task Phase-3 structural close + oracle one-step-removed + negative-scope completion contract `adf98db`. Wave-1/2 deploy-gap audit: zero gaps (details below).

### Confirmed gaps (landed same turn)

1. **[S/medium] Non-interactive git env** (Mic92 `git-rebase-env.ts`): nothing set `GIT_EDITOR` — a worker hitting rebase/amend parks on an editor forever. Now `GIT_EDITOR/GIT_SEQUENCE_EDITOR/GIT_PAGER=cat` in worker.py spawn env (setdefault) + both shell runners' generated runner scripts. `d01a8d7`
2. **[S/medium] Fix-task structural close** (lovesegfault REVIEW.md): fix template stopped at "patch + lint" — no sibling sweep, no dead-code sweep, no done-gate. Phase 3 added to `_fix_two_phase`: sweep whole file ±50 lines + module, remove obsoleted state, end completion summary with a literal `Done-gate:` command line. `adf98db`
3. **[S/medium] Verifier one step removed** (lovesegfault r25: 8/12 regressions were introduced BY fixes verified only against the original claim): oracle now walks inverse input / next lifecycle transition / sibling consumer with concrete examples on fix-intent tasks (`_FIX_ONE_STEP_CRITERION`). `adf98db`
4. **[S/low] Negative-scope declaration** (controversial): completion contract now demands deliberate exclusions + uncertainties in `summary`, which already flows into structured PR bodies — reviewers learn weak spots from the author. `adf98db`

### Parity confirmed with round-2 evidence (查过了，不是照搬)

- SHA-pinned CI actions with version comments → ci.yml already pins all `uses:` to full SHAs (cookbooks devsec discipline, verified)
- Numeric narration bound to source keys (lovesegfault census ratchet) → `docs/facts.json` + doc-align.py check/apply is the same mechanism
- Tool scoping as capability security (cookbooks `disallowed_tools`) → `config._TOOL_SUBSETS` per task type (review = read-only) already does this for workers
- Fail-open-toward-stopping loop hooks → official ralph-wiggum plugin validates Clade's existing stop-hook circuit-breaker doctrine
- `setting_sources` judge/worker split → SDK notebook 01 documents the exact contract behind this week's 386a862/9fd1720 fixes
- Conflict handling: run-tasks-parallel aborts the merge and reruns the task serially on updated main — deterministic, never LLM-guessed conflict resolution; judged BETTER than mic92's resolve-doctrine at this topology (different_not_deficient)
- File-claim locks / fresh-context respawn / 1-2k distilled subagent summaries (C-compiler + multi-agent blog) → OWN_FILES + loop-runner re-spawn + worker TLDR
- Immutable feature list anti-reward-hacking (Nov-25 blog) → VERIFY.md checkpoints + fix-intent test criterion cover the same failure
- Friction logs / model self-reported feedback (domdomegg) → partial parity via BRAINSTORM [AI] inbox + skipped.md routing

### Rejected (different ≠ deficient / N-A)

- pueue job queue (mic92) — CC harness background tasks + Monitor cover it; smart-caveman register = personal style
- One-ruleset-many-harnesses + private claude.md repo (mic92) — single-tool scope (round-1 precedent); /btw tangent-strip + autoCompact-off = harness layer, unreachable from skill layer
- nostr-walkie phone steering — Telegram notify + web UI + worker mailbox cover the capability
- CMA platform features (outcome-grader event, session pods, transcript fork, FUSE memory, HITL webhooks, coordinator threads, sandbox workers) — hosted-platform topology; Clade is local-first; outcome-grader spirit = oracle
- WIF keyless auth / GCP secret brokerage — no cloud secret fleet; CI already key-gated + SHA-pinned
- nbdime (no notebooks), formal Quint/Kani/MBT layer (cost/scope), BASH_ENV direnv shim (no direnv here; .venv symlink bootstrap covers), tracey (re-confirmed round-1: VERIFY.md equivalent), two-stage permission classifier (CC ships auto mode at harness level)

### Noted, not landed (candidates for a future wave)

- [ ] Mutation testing as run-over-run missed-count diff ratchet, narrow high-signal targets first (lovesegfault mutants.toml) [M/medium — patrol-lane experiment]
- [ ] Judge hardening: pure judges could add `--disallowed-tools` belt-and-braces (cookbooks: allowed gates prompting, disallowed gates availability) [S/low]
- [ ] Standing friction-log instruction for workers (append harness pain to BRAINSTORM [AI]) [S/low]
- [ ] `input_examples` on mcp_server tool definitions (advanced-tool-use blog: 72%→90% complex-param accuracy) [S/low]
- [ ] Strike-ladder N=4..7 structural-close templates as /audit reference doc (delete-reimplementation, make-function-total, single-emit-chokepoint) [S/low prose]
- [ ] Flake-verdict policy doc for test-loop-real (felixrieseberg: "one SUCCESS = good, three identical failures = content must change") [S/low]

### Wave-1/2 deploy-gap audit (this repo's recurring failure class — checked deliberately)

All 15 spot-checked round-1 adoptions are wired end-to-end: oracle liveness returns `infra_error` flags; tests run BEFORE oracle gate and auto_push (worker.py:800); quiet-run.sh referenced by /verify, /review, loop-runner; rule-injector + mailbox-drain registered in settings-hooks.json; checks.sh called from committer.sh AND ci.yml; validate-skills in ci.yml AND install.sh; ensure_repo_invariants fired from session init; merge --auto + do-not-merge in routes/tasks.py; evals/ present (its README notes it already caught a 17/17 'unreviewed' misparse on day one); MCP compact default-on; commit-body mandate in /commit. **Zero deploy-gaps found.**

### Correction to round 1

domdomegg's npm publishing is NOT npm trusted publishing — it's GCP Workload Identity Federation token brokerage (GitHub OIDC → gcloud secrets access → masked `npm publish`); only his MCP-registry publishing is true OIDC. Still N-A for Clade (no package fleet), but the round-1 ledger term "OIDC secrets" was imprecise.

---

## [Research] 2026-06-12 — Elite workflows study (claude-cookbooks + 5 profiles)

User question: 完整的学习他们的工作流，看看凭什么他们能又高质量又快。 Six sources swept, every practice adversarially verified against Clade's codebase (verdicts: confirmed_gap / parity / different_not_deficient / N-A). 21 adopt-now gaps, 3 bigger bets, 31 parity confirmations, 28 rejections.

> **RESOLVED 2026-06-12** — implemented same day in two waves (~50 commits, `e038bc4..`): wave 1 = 20/21 adopt-now items (26 commits, tests 237→434); wave 2 = path-scoped rules + all 3 bigger bets + 4 completeness-audit additions + fallout fixes (24 commits, tests →499). Zero-gap audit closed the ledger at 87/87 practices accounted; 2 parity verdicts below were overturned with evidence (real-API e2e tier — landed `dac3c47`; mcp-package drift gate — landed `46ad977`). Only deliberate residue: oracle_second_provider wiring (conditional unmet), session-start canary (superseded by the eval harness). Applied-learnings table: [REFERENCES.md](REFERENCES.md). Detailed per-item dispositions remain below for the record.

### Sources surveyed

| Source | Who/What | Key takeaway |
|---|---|---|
| claude-cookbooks | Anthropic's official patterns repo (83 cookbooks, 45.3k stars), Claude itself a tracked commit author | Written rubrics make quality checkable → checkable quality makes review fast → fast review makes same-day merges safe. Deterministic validators gate; LLM only summarizes failures. |
| Mic92 (Jörg Thalheim) | NixOS core/infra, ~48 commits/day in 2026, anthropics org member | Closed loops: bot opens per-input PRs → fast CI → auto-merge → Claude repairs the stragglers. CI duration IS the system's clock speed, so he builds cache/shard/eval infra to shrink it. |
| felixrieseberg | Anthropic eng lead, Claude Code Desktop/Cowork; relic = C99 coding agent for 7 OS targets in 4 days | Agents multiply output — spend the multiplier on depth (tests, gates, release pipeline, docs day one), not breadth. Invariants compiled into the build, not trusted to prose. |
| domdomegg (Adam Jones) | Anthropic; ~172 original repos maintained at near-zero marginal cost | One hub repo fans CI/settings to ~110 repos nightly; bot PRs auto-merge behind CI with a label as the only human opt-in; release = 2 commands. Repo #100 costs what repo #1 did. |
| lovesegfault (Bernardo Meurer) | Anthropic Rust/Nix; rio-build = 3,922 commits/8mo solo, best public .claude/ toolkit observed | Every environment/pipeline is a versioned CI-verified artifact; every repeated judgment becomes a machine gate; Nth-strike on an invariant → structural fix, never another review rule. |
| controversial (Luke Deen Taylor) | Stainless product engineer; Claude-authored upstream PRs merged into zed in 3h42m | AI authors, human grounds and gates: real repro + reviewed diff + regression test + root-cause narrative + disclosure. Minimal diffs with evidence are the highest-trust merge currency. |

### 凭什么又快又好 — the meta-answer

1. **Quality is machine-checkable, so review collapses into verification.** Evidence-forcing rubrics run by a fresh-context grader (cookbooks), invariants compiled into the build — win95 API allowlist fails the link (felixrieseberg), drift checks whose failure message names the fix command (lovesegfault), en-dashes and sentence-final periods as Jest assertions (controversial). Once "good" is checkable, checking is instant.
2. **Verify/CI duration is the system's clock speed — engineered like a product.** Binary caches on free GHA storage, 8-way pytest shards, eval-reuse (mic92); eval-once/warm-trunk CI with a measured cost annotation on every knob (lovesegfault); 90-second dependabot merges (domdomegg). Every automation polls the gate; a fast total gate compounds everything.
3. **Approval economics inverted: default-allow + surgical deny list.** ~10 dangerous verbs behind a regex gate + terminal bell (mic92), sandbox-then-delegate over approval ladders (felixrieseberg), do-not-merge label as the only human opt-in (domdomegg), decide()/escalate() calibration (cookbooks).
4. **Done = merged with green CI, and the loop closes itself.** merge-when-green + repair-PRs re-entering the same gate (mic92); bot-approve + auto-merge fleets (domdomegg); triage-then-batch-delegate (felixrieseberg). Failures route back into the gate, not into a human inbox.
5. **Pay setup/context once, amortize across the fleet.** Hub-repo file-sync + self-deleting setup script (domdomegg); codesigning template stamped onto every app (felixrieseberg); git-state pre-injection and session bootstrap so turn #1 starts informed (mic92, lovesegfault).
6. **Small reversible units with evidence attached are the trust currency.** +45/-1 PR with regression test + root-cause narrative merged into zed in 3.7h (controversial); one PR per flake input so one red never blocks nine green (mic92); mandatory-vs-optional review findings so nothing queues on preferences (domdomegg).
7. **Every failure debugged at most once; repeat offenders get structural closes.** CI-failure-pattern catalog with validated fixes + the Nth-strike rule: "by third strike the review rule existed, was followed, and still broke — restructure so the compiler checks it" (lovesegfault); full attempt-memory in evaluator loops (cookbooks).
8. **AI multiplies output; winners spend the multiplier on depth, not breadth.** 7 repos, all release-grade day one (felixrieseberg); 92% private volume, public output curated to deep merged fixes (controversial); every capability ships with an eval harness and measured numbers (cookbooks).

### Confirmed gaps vs current VISION (确认的差距)

**Cluster A — Oracle integrity (北极星 90% 指标只有验证器是真的才算数)**

1. **[S/high] Oracle rubric: acceptance criteria must reach the grader** (cookbooks). `worker_review.py`: lift `task_description[:400]` truncation (lines 288, 361-364); inject parsed task schema (`config.py _parse_task_schema` — the criteria block `config.py:541` already builds never reaches the oracle); rewrite `_ORACLE_SPEC_PROMPT` per the rubric table: per-criterion verdicts, 'satisfied' must cite file:line evidence, no-fire list. Fixtures in `orchestrator/tests/test_worker_modules.py`.
2. **[S/high] Oracle liveness: fail-open ≠ approved** (lovesegfault). `_oracle_pass`/`_oracle_review_chunk` return a distinct infra_error flag instead of `(True,...)` on timeout/exception (lines 235/247/327); `worker.py` tags `oracle_result='unreviewed'`, counts consecutive infra errors, ≥3 → webhook + blockers.md. Optional known-bad-fixture canary at session start. Today a dead oracle silently approves everything forever.
3. **[M/high] Evidence before verdict** (mic92, nixpkgs-review). `worker.py`: move `_run_project_tests` + `_run_intramorphic_check` BEFORE the oracle gate and auto_push (today post-commit fail-open, 627-655); thread `test_evidence` into the oracle prompts; `/review-pr` checks out the PR into a worktree, runs the CI commands /commit Step 3.6 already discovers, posts an **Evidence** section before the verdict.
4. **[S/medium] Blocking/optional gate on the chunked oracle path** (domdomegg). `_oracle_review_chunk` (309-319) currently accepts any REJECTED with no severity/confidence gate — a style nit on one chunk nukes the commit + re-spends a worker run. Enforce 'REJECTED requires severity:error'; route warning/info to skipped.md/BRAINSTORM [AI] instead of dropping.

**Cluster B — CI tests what ships (deploy-gap class)**

5. **[S/medium] CI executes install.sh + shell-tests becomes a hard gate** (domdomegg + lovesegfault). New `tests/test-install.sh` + 4th ci.yml job: clean-HOME install, idempotency, Cross-Project-Rules survival (ab06c33 regression), symlinks resolve; smoke-run the INSTALLED copy. Same commit: delete `continue-on-error: true` + `|| echo ::warning` from shell-tests (ci.yml:76-83) — today a loop-runner regression merges green and ci_watcher can never see it.
6. **[S/medium] Prose code rules become failing tests** (felixrieseberg). `orchestrator/tests/test_conventions.py`: ≤1500 lines, import-DAG acyclicity, no exception text in 500 responses. History proves prose decays: worker.py blew past 1500, str(e) reached server.py:796.
7. **[S/medium] Repo-invariants preflight** (domdomegg). `github_sync.py ensure_repo_invariants()`: idempotent `gh label create`, permission/squash check; called from ProjectSession init + start.sh health check. Fixes silent-DOA Issues sync on fresh repos.
8. **[S/medium] Skill registry: one schema, one parser** (cookbooks). `configs/scripts/validate-skills.py` in ci.yml + install.sh preflight; shared by install.sh index generation and mcp_server.load_skills(). Kills the live 'description: Skill' drift degrading skill routing across 95+ skills.

**Cluster C — Commit path safety & history as context**

9. **[S/medium] Committer defense-in-depth** (felixrieseberg + lovesegfault). `configs/scripts/checks.sh`: staged-secret scan via `redact.py --check` (fail-closed, CLADE_ALLOW_SECRETS=1 override), shellcheck --severity=error, conventional regex — called from committer.sh AND as a ci.yml step (same code both places). Workers push autonomously overnight; a dev key in a worktree WILL get staged eventually.
10. **[S/medium] History carries the payload** (controversial + felixrieseberg). Fix-intent tasks get a test-presence oracle criterion; `routes/tasks.py` replaces `gh pr create --fill` with a structured body (task, completion summary, oracle verdict, test pointer, authorship note); /commit + loop-runner + worker_taskfile mandate 2-4-line bodies (mechanism/hazard/constraint). commit-archeology and /pickup consume this directly.
11. **[S/low] Attribution trailers on worker commits** (cookbooks). committer.sh appends Co-Authored-By + X-Clade-Task when CLADE_WORKER_TASK_ID is set; auto-audit/commit-archeology segment agent-vs-human stats.

**Cluster D — Autonomous loop hygiene**

12. **[S/medium] CI-failure tasks ship the log tail + bad-fix guardrails** (mic92). scan-ci-failures.sh embeds `gh run view --log-failed | tail -40`; ci_watcher.py includes failed steps; worker_hydrate.py learns actions/runs URLs; guardrails: never blame CI infra, never downgrade deps.
13. **[S/medium] /trim-tests + suite-runtime probe** (mic92). New skill shrinks branch-touched test files (table-driven consolidation, delete mock-only/brittle), reports coverage given up; scan-health probes verify_cmd duration >100s (TEST_SAMPLE_TIMEOUT=120 silently degrades past that).
14. **[S/medium] quiet-run.sh** (lovesegfault). Full log to file, stdout = status + failed names + last 80 lines, mirrored exit code; wired into /verify, /review, loop-runner worker block. Stops raw pytest/build output billing the transcript.
15. **[S/medium] PR auto-merge behind the project's own CI** (domdomegg). `routes/tasks.py`: do-not-merge label check, then `gh pr merge --auto` (project CI becomes the gate) with fallback to immediate merge. Today Clade merges before the target repo's CI reports.
16. **[M/medium] Worktree env bootstrap + per-file post-edit checks** (lovesegfault). run-tasks-parallel.sh symlinks .venv/node_modules into worktrees (today workers can't run the documented test command at all); post-tool-use-lint.sh checks the edited file, not the whole tree, under parallel editors.

**Cluster E — Learning system & context economy**

17. **[S/medium] Nth-strike → structural close + retire the prose rule** (lovesegfault). /audit gains ESCALATE-TO-STRUCTURAL (3+ effectiveness hits → run /generate-hook inline, archive the rule with a pointer); /generate-hook Step 6 retires the source; auto-audit.sh:196 advisory becomes REQUIRED. Caps the Auto-Promoted-Rules bloat already in progress.
18. **[M/medium] Path-scoped rule injection** (lovesegfault). `configs/hooks/rule-injector.sh` (PostToolUse Edit|Write) glob-matches file_path against `paths:` frontmatter in `.claude/rules/*.md` + `~/.claude/rules/*.md`, injects via additionalContext once per session; /audit + /generate-hook write file-domain rules there instead of global CLAUDE.md.
19. **[S/medium] Dependency-bug doctrine** (controversial). /investigate Phase 6b: minimal repro → upstream patch > pin-with-linked-issue > documented workaround — never silent; one Engineering Values bullet; referenced in scan-deps task template.
20. **[S/low] MCP compact mode** (cookbooks). CLADE_MCP_COMPACT=1: 3 tools (list/search/run_skill) instead of ~95 definitions for external clients — the overflow Clade already diagnosed in itself, still shipping to Cursor/Cline.
21. **[S/low] Cross-model second-opinion subagents** (mic92). `configs/agents/second-opinion-{codex,gemini}.md`: haiku + Bash-only, shell out read-only, relay verbatim, explicit-request only; optional `oracle_second_provider` setting for >N-file diffs.

**Bigger bets (need design discussion, 设计后再做)**

- **Prompt eval harness** (cookbooks): `orchestrator/evals/` with ~20 oracle fixtures from real history (incl. known false-approves), `run_oracle_eval.py` replaying through live `_oracle_review`, supervisor structural cases. Run before prompt merges, not per-push (API cost). This is the verifier gating Cluster A — today an oracle prompt edit cannot be shown to move the 90% metric before deploy.
- **Offline recovery e2e** (cookbooks): mock-gh with persistent .gh-state/ + turn-counting mock-claude (attempt 1 fails with planted pytest output, attempt 2 clean); `test_recovery_e2e.py` asserts failure → reflection context → adapted retry → success. Every recovery bug to date was found in paid production runs.
- **Mid-flight worker steering** (cookbooks): `configs/hooks/mailbox-drain.sh` (PostToolUse) drains `.claude/worker-inbox-{CLADE_TASK_ID}.md` as additionalContext; send_message writes the inbox for running tasks. Kills the kill+requeue cost of mid-task corrections. Design: delivery semantics + interplay with spawn-time mailbox injection.

### Parity confirmed (no action) — 证明我们查过了，不是照搬

- Diagnose-then-pick context primitives → condensers.py / worker_taskfile.py:159 / pre-compact.sh / handoff STRUCTURED v2
- Evaluator-optimizer with attempt memory → worker.py:557-584 reflections + :1324-1352 chained requeue + LoopDetectionService
- Runtime decomposition, workers get task+slice → loop-runner.sh:340-447 node_supervisor + /orchestrate + build_task_file
- Deterministic validators first, LLM on failure only → loop-runner [DET]→[LLM] gating + lint reflection + error_classifier.py
- Reviewer as versioned artifact → configs/agents/code-reviewer.md + /review-pr + VERIFY-*.md templates + _score_task
- Skills as tested CLIs with thin SKILL.md → configs/scripts/*.sh + CI shell-tests + mcp_server.py multi-harness
- Context pre-injection → session-context.sh + build_task_file + handoff/pickup
- Default-allow + surgical deny-gate → pre-tool-guardian.sh + permission-request.sh + notify-telegram.sh
- Terse operational CLAUDE.md → configs/templates/CLAUDE.md anchors/recipes
- Worktree fan-out with self-contained prompts → run-tasks-parallel.sh + context_version staleness stamping
- Mock-binary e2e harness → tests/test-loop.sh MOCK_CLAUDE_* + orchestrator/tests/
- Constraints-first frozen seams → OWN_FILES/FORBIDDEN_FILES + task_queue enforcement + DAG rule
- Product-as-skill → configs/skills/ + install.sh + mcp-package/
- Repo-local run config → /init-profile + .claude/orchestrator.json + session-context auto-load
- Depth over breadth → _post_convergence_scan hardening factories + VERIFY convergence + BRAINSTORM human gate
- Hub fan-out of shared automation → configs/ + install.sh + .kit-checksum + sync-setup.sh
- Generic CI contract (--if-present) → CLAUDE.md Test/Verify lines + worker_utils skip-silent
- Self-patching dependency loop → scan-deps.sh + dep_update.py + --patrol
- Self-compacting agent memory → hooks + corrections/rules.md + /audit + /learn --prune + rule re-injection
- Drift checks naming their fix → .kit-checksum + session-context warning + start.sh auto-reinstall
- Eval-once, ship plan to workers → build_task_file TLDR/pre-hydration + plan-once supervisor
- Portable quality kit / meta-tooling / content invariants / earliest-ring gates / visual pipeline review / quantified meters / provenance / micro-commits / budgets / minimal-diff currency → see verdicts (controversial: all parity)

### Rejected (different ≠ deficient / N-A)

- 3 scoped CI reviewers (cookbooks) — placement choice: AI review fires at PR creation; direct pushes would never trigger CI reviewers
- Changed-files-only CI (cookbooks) — Clade CI is free+fast; repo-wide py_compile is load-bearing
- decide()/escalate() tools (cookbooks) — 3-tier decisions/skipped/blockers.md + interventions table is the same calibration
- GH-native dep automerge / merge-when-green babysit / claude.md symlink repo / solo-PRs+merge-queue / CI-speed Nix infra / forge-triage TUI (mic92) — mechanism differences with capability coverage at Clade's topology (local gates, committed context, own task queue)
- CLAUDE.md/DECISIONS.md split, post-merge review, tag-push matrix, codesigning (N/A), VM sandbox (host-product layer), web installer (felixrieseberg) — different placement or no protected surface
- 2-command tag release, OIDC secrets (N/A), setup.js self-registration, standards-as-npm-packages, committed test credential (N/A — GitHub revokes), ship-cadence doctrine (already VISION.md) (domdomegg)
- CI-failure markdown catalog (covered by error_classifier + intervention replay), tracey spec traceability (VERIFY.md equivalent), Renovate fleet automerge (curate-first trust model), generated workflows (premature at 84 lines), signed release gate (N/A — no publish leg) (lovesegfault)
- Colocated notes.md (injection beats colocation for agent consumers), starter template (user-level kit is stronger; no repo-creation flow) (controversial)

### Recommended additions to TODO.md

*(BRAINSTORM is an inbox — these are recommendations for human promotion, grouped by cluster, ordered by impact.)*

- [ ] **Oracle integrity package** (the highest-leverage cluster — all four touch `worker_review.py`/`worker.py` and should land as one phase): (a) criteria-injection + evidence-forcing rubric [S/high]; (b) fail-open → 'unreviewed' + infra-error counter + canary [S/high]; (c) tests run BEFORE oracle/push, evidence threaded into prompts; /review-pr executes the change [M/high]; (d) severity:error gate on the chunked path, optional findings → follow-ups [S/medium]
- [ ] **CI hardening commit**: install-test job (clean-HOME install.sh + assertions) + flip shell-tests continue-on-error to false + optional alls-green-style gate job [S/medium]
- [ ] **test_conventions.py**: 1500-line cap, import-DAG acyclicity, no exception text in 500s — runs in CI pytest AND workers' local test command [S/medium]
- [ ] **checks.sh in committer**: staged-secret scan fail-closed + shellcheck, same script reused as a CI step [S/medium]
- [ ] **CI-failure task hydration**: log tails in scan-ci-failures.sh/ci_watcher.py, actions-run URLs in worker_hydrate.py, anti-infra/anti-downgrade guardrails [S/medium]
- [ ] **/trim-tests skill + scan-health suite-runtime probe** (>100s verify_cmd → trim suggestion task) [S/medium]
- [ ] **/audit ESCALATE-TO-STRUCTURAL** + /generate-hook Step 6 rule retirement [S/medium]
- [ ] **quiet-run.sh** verify wrapper wired into /verify, /review, loop-runner worker block [S/medium]
- [ ] **gh pr merge --auto + do-not-merge label** in routes/tasks.py merge_all_done [S/medium]
- [ ] **ensure_repo_invariants()** preflight in github_sync.py, called at session init + start.sh health check [S/medium]
- [ ] **validate-skills.py**: one frontmatter schema + shared parser for install.sh and mcp_server [S/medium]
- [ ] **Dependency-bug doctrine** in /investigate Phase 6b + Engineering Values bullet [S/medium]
- [ ] **History payload**: fix-task test-presence oracle criterion + structured PR bodies (replace --fill) + commit-body rule in /commit + loop-runner + worker_taskfile [S/medium]
- [ ] **Path-scoped rule-injector hook** (.claude/rules/*.md with paths: frontmatter) [M/medium]
- [ ] **Worktree env bootstrap + per-file post-edit lint** in run-tasks-parallel.sh / post-tool-use-lint.sh [M/medium]
- [ ] Low-priority lane: committer attribution trailers [S/low]; MCP compact mode [S/low]; second-opinion-{codex,gemini} agents [S/low]
- [ ] **Design discussions (bigger bets)**: prompt eval harness (orchestrator/evals/ — gates the oracle rewrite); offline recovery e2e with planted failures; mid-flight worker steering via PostToolUse mailbox drain


## [AI] Friction Log

[2026-06-12] loop-runner: work completed but exit reason read stuck_no_commits — supervisor kept planning after 5/5 criteria met instead of returning CONVERGED / workaround: verified convergence manually via git log + gates
[2026-06-12] loop-runner: commits stay local — no push phase, fleet sync silently deployed stale HEAD / workaround: manual git push before node pulls; consider a [DET] push node after commit_changes
[2026-06-14] browser-verify: `npx playwright install chromium` resolves a different playwright version than `@playwright/mcp` bundles → "Removing unused browser" + version-mismatch box on first setup / workaround: it still lands the right chromium build (verified chromium-1223 present + MCP launched); documented as expected in configuration.md. Cleaner fix: pin the browser install to @playwright/mcp's bundled version.
[2026-06-14] frontend-detect: real projects (scamai-landing) describe their stack in CLAUDE.md prose ("Built with Next.js 15"), not the template's structured `Frontend:` line — _is_frontend_project returned False, visual-verify directive would never inject / FIXED a1e807d: _project_is_frontend now also reads package.json deps. Lesson: don't gate on a doc format real projects don't follow (deploy-gap).
