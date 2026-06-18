**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

← Back to [README](../README.md)

# Who to Learn From — The Agentic-Coding Frontier

A curated, **vetted** watch-list of the people, companies, blogs, and repos worth studying to keep Clade at the frontier of agentic coding. This is an *index*, not a dump — every entry is here because it directly improves how we build loops, orchestration, skills, and harnesses. Where we already have a deep-dive, it links to `docs/research/`.

> **Companion doc:** [`docs/research/README.md`](research/README.md) is the other half — the **deep-dives we've already completed** plus a consolidated, effort-sorted **gap backlog**. This file = *who to study*; that file = *what we've studied + what's left to build*.

> **三人行必有我师** — everyone on this list has *something*. But the tiers below are an honest editorial call about who is a **benchmark** for Clade's specific niche (autonomous loop + supervisor/worker orchestration on top of Claude Code) versus who is good-but-adjacent. Read Tier 1 first.

- **Last reviewed:** 2026-06-13
- **Review cadence:** re-sweep quarterly, or whenever a frontier model drops. Update "Last reviewed", append to the [Changelog](#changelog), and re-tier as the field moves.
- **How to use it:** pick one Tier-1 entry per session, read its canonical piece, then ask *"what does Clade do here, and is it deficient or just different?"* (see [How we vet what we absorb](#how-we-vet-what-we-absorb)). Confirmed gaps → fix in code immediately, don't TODO them.

**Status legend:** 📋 to-read · ✅ deep-dived (link) · 🔄 recurring (re-read on new model) · ⚠️ dead/changed since last review

## Table of Contents

- [Tier 1 — Shapes Clade's design (read first)](#tier-1--shapes-clades-design-read-first)
- [Tier 2 — Peers & craft to study](#tier-2--peers--craft-to-study)
- [Tier 3 — Foundational & on-radar](#tier-3--foundational--on-radar)
- [Bot behavior in the wild (high-commit repos)](#bot-behavior-in-the-wild-high-commit-repos)
- [The multi-agent debate](#the-multi-agent-debate)
- [Currency notes — dead or changed](#currency-notes--dead-or-changed)
- [Actionable gaps for Clade](#actionable-gaps-for-clade)
- [How we vet what we absorb](#how-we-vet-what-we-absorb)
- [Changelog](#changelog)

---

## Tier 1 — Shapes Clade's design (read first)

These map 1:1 onto decisions in `worker.py`, `loop-runner.sh`, the `/loop` skill, and `worker_taskfile.py`. If a Tier-1 piece contradicts what we do, that's a same-turn investigation.

| Source | The one piece | Steal for Clade |
|--------|---------------|-----------------|
| ✅🔄 **Anthropic Engineering** | [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (Nov 2025) → [deep-dive](research/2026-06-18-anthropic-effective-harnesses.md) | **Highest-relevance external doc that exists.** Deep-dived 2026-06-18: most primitives already covered; 1 deferred gap (iteration-start health check). 🔄 re-read on new model. |
| 🔄 **Anthropic Engineering** | [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) · [Multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system) | Workflows-vs-agents taxonomy; context curation → our `build_task_file` + condensers; orchestrator-worker w/ parallel subagents → our swarm/worker-pool. |
| ✅ **Geoffrey Huntley** | [Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) + [CURSED](https://ghuntley.com/cursed/) (3-month bash-loop built a compiler) → [deep-dive](research/2026-06-18-huntley-ralph-cursed.md) | *The* canonical "the loop IS the program." Deep-dived 2026-06-18: **confirms Ralph ≈ /loop**; Clade's convergence detection is stronger. 0 gaps. |
| ✅ **Dexter Horthy / HumanLayer** | [12-Factor Agents](https://github.com/humanlayer/12-factor-agents) → [deep-dive](research/2026-06-18-12-factor-agents.md) | The reliability checklist for worker/supervisor systems. Deep-dived 2026-06-18: **11/12 covered + bonus factor 13**; Factor-7 inline human-contact is different-by-design. 0 gaps. |
| 📋 **Addy Osmani (Google)** | [Loop Engineering](https://addyosmani.com/blog/loop-engineering/) · [Long-running Agents](https://addyosmani.com/blog/long-running-agents/) | Coined "loop engineering": *stop prompting the agent, start designing the system that prompts it.* Literally Clade's thesis stated by someone else — single most on-target read. |
| 📋 **Boris Cherny (Claude Code creator)** | ["I write loops that prompt Claude"](https://howborisusesclaudecode.com/) | The person who built Claude Code, on running Opus autonomously for hours/days. Primary source is social posts → treat as a living reference, not one essay. |
| 📋 **Thorsten Ball (Amp)** | [How to Build an Agent](https://ampcode.com/how-to-build-an-agent) | "An LLM, a loop, and enough tokens." Clearest mental model of the engine at the core of `worker.py`. |
| 🔄 **Simon Willison** | [simonwillison.net](https://simonwillison.net/) — start w/ [The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) | Best continuous observer in the field — subscribe. Lethal trifecta (private data + untrusted content + exfil channel) is the security frame every tool-wielding loop must defend. |
| 📋 **Cognition (Walden Yan)** | The multi-agent debate → see [section below](#the-multi-agent-debate) | Read *against* Anthropic's multi-agent piece. We run supervisor+worker — we need both sides to know our risk surface. |

## Tier 2 — Peers & craft to study

Closest-architecture peers and adjacent craft (evals, PR hygiene, TUI). Many already deep-dived locally.

**Peer harnesses / tools**
- ✅ **SST opencode** ([opencode.ai](https://opencode.ai) · [deep-dive](research/2026-06-18-sst-opencode.md)) — **most architecturally similar project to Clade.** Deep-dived 2026-06-18: client/server split + session model already present; its judge-hardening idea drove wiring `DISALLOWED_TOOLS_JUDGE` to 5 read-only judges (now built). Interactive-first vs our autonomous-first → most headline features different-not-deficient.
- ✅ **OpenHands / All Hands AI** ([deep-dive](research/2026-03-30-openhands-architecture.md)) — open supervisor + Plan/Code-mode split, cloud. Also see its **bot PR stream** below.
- ✅ **Aider** ([deep-dive](research/2026-03-30-aider-research.md)) — repo-map + git-native commit-per-change. Self-reports AI-authorship % (see bot section).
- ✅ **Cursor / Devin** ([deep-dive](research/2026-03-30-cursor-devin-research.md)) — agent-IDE UX gradient; Devin = own-the-orchestration-layer-above-the-model. Devin now also absorbs Windsurf (see currency notes).
- ✅ **SWE-agent / mini-swe-agent** ([swe-agent](research/2026-03-30-swe-agent-research.md) · [mini](research/2026-03-30-mini-swe-agent-deep-dive.md)) — minimal scaffolds; the ACI (agent-computer interface) idea.
- ✅ **Agentless / AutoCodeRover / Moatless** ([agentless](research/2026-04-07-agentless.md) · [autocoderover](research/2026-04-07-autocoderover.md) · [moatless](research/2026-04-08-moatless-tools.md)) — localize→patch→test without heavy agency. NB: the ex-AutoCodeRover team now leads **Sonar Foundation Agent** (top open SWE-bench scaffold, see bot section).
- ✅ **LangGraph / CrewAI** ([deep-dive](research/2026-03-30-langgraph-crewai-research.md)) · ✅ **Composio** ([deep-dive](research/2026-03-30-composio-orchestrator-research.md)) · ✅ **Kiro** ([deep-dive](research/2026-03-30-aws-kiro-deep-research.md)) — orchestration framework design choices.
- 📋 **Block Goose** ([block.github.io/goose](https://block.github.io/goose/)) — extension/recipe architecture (≈ our skills); now governed by the Linux Foundation's Agentic AI Foundation.
- 📋 **Factory.ai** ([factory.ai](https://factory.ai)) — "agent-native, not IDE-native"; parallel specialized droids across CLI/SDK/desktop; #1 Terminal-Bench.
- 📋 **Warp "Oz"** ([warp.dev](https://www.warp.dev)) — **event-triggered headless agents** (webhook / CI / Slack). Direct extension idea for our orchestrator.
- 📋 **Vercel AI SDK 7 "HarnessAgent"** ([ai-sdk.dev](https://ai-sdk.dev)) — one API wrapping Claude Code / Codex / Pi. Study how others abstract *our* layer (skills, sandboxes, sessions, sub-agents).

**Craft: evals, PR hygiene, workflow**
- 📋 **Hamel Husain** — [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/) — error-analysis-driven evals; the oracle-gate / VERIFY side of the loop.
- 📋 **Eugene Yan** — [What we learned from a year of building with LLMs](https://www.oreilly.com/radar/what-we-learned-from-a-year-of-building-with-llms-part-i/) — guardrails/ops.
- 📋 **Armin Ronacher** — [Agentic Coding Recommendations](https://lucumr.pocoo.org/2025/06/12/agentic-coding/) · [Agent Design Is Still Hard](https://lucumr.pocoo.org/2025/11/21/agents-are-hard/) — full-permission agents + self-checking harnesses.
- 📋 **Mitchell Hashimoto** — [Vibing a Non-Trivial Ghostty Feature](https://mitchellh.com/writing/non-trivial-vibing) — 16 annotated real sessions; "build a self-check harness, then write it into CLAUDE.md" = our reflection model. *(ghostty is a sibling repo on this host — high transfer.)*
- 📋 **Peter Steinberger** — [Essential Reading for Agentic Engineers](https://steipete.me/posts/2025/essential-reading) — a curated reading list itself (meta-source).
- 📋 **Steve Yegge + Gene Kim** — [*Vibe Coding* (book)](https://itrevolution.com/product/vibe-coding-book/) — supervised-autonomy / FAAFO framing at enterprise scale.

## Tier 3 — Foundational & on-radar

Broad framing, foundational taxonomy, and culture. Valuable, not loop-design-critical.

- 🔄 **Andrej Karpathy** — [Software 3.0 keynote](https://www.youtube.com/watch?v=LCEmiRjPEtQ) (coined "vibe coding") — LLM-as-interpreter, human-as-supervisor.
- 📋 **Lilian Weng** — [LLM Powered Autonomous Agents](https://lilianweng.github.io/posts/2023-06-23-agent/) — the planning/reflection/memory/tool-use taxonomy everyone still cites (2023, canonical).
- 📋 **swyx / Latent Space** — [The Rise of the AI Engineer](https://www.latent.space/p/ai-engineer) — role/vocabulary anchor.
- 📋 **Chip Huyen** — [Agents](https://huyenchip.com/2025/01/07/agents.html) · **Jason Liu** — [Instructor](https://python.useinstructor.com/) (structured outputs) · **Harrison Chase** — [How to think about agent frameworks](https://blog.langchain.com/how-to-think-about-agent-frameworks/).
- **Culture / "AI as baseline":** Shopify (Tobi Lütke memo), Anthropic (dogfoods Claude Code), Cloudflare (Agents + Code Mode, Kenton Varda), Stripe; **Gergely Orosz / Pragmatic Engineer** for real-team adoption reporting.

---

## Bot behavior in the wild (high-commit repos)

*The "study what the robots actually do" angle.* Repos where AI agents author a large share of commits/PRs — read these for commit granularity, PR-description structure, failure recovery, and loop-convergence signals.

- **Aider self-authorship metric** — [HISTORY.html](https://aider.chat/HISTORY.html): each release reports the % written by aider itself (current main **~62%**, peaks **88–93%** on tagged releases), computed from git-blame at release-cut. **Steal:** a reproducible "agent-authorship %" — and note Clade *already* tracks agent-vs-human fix-rate (session hook shows `agent fix-rate 0% (0/7) vs human 23%`); this is the same instinct, extend it.
- **OpenHands resolver — [PR #5451](https://github.com/OpenHands/OpenHands/pull/5451)** (bot author `openhands-agent`). **Steal:** clean PR template ("Fix issue #N: …" + issue link + reviewer-facing rationale + **test plan as a runnable Docker command**); and a *separate* `🤖 Auto-fix linting` commit rather than amending — self-correction as its own visible commit. Compare to our `worker_review.py` PR bodies.
- **Claude Code GitHub Action** — [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action). **Steal:** interactive (`@claude`) vs automation (`prompt:` + `--max-turns`) split; `--max-turns` is the direct analog of our loop max-iter guard.
- **Google Jules** — [jules.google](https://jules.google/) — plan-before-implement; PRs "look human" (descriptive commits + descriptions), follows user branch-naming conventions.
- **OpenAI Codex cloud agent** — [openai/codex/pulls](https://github.com/openai/codex/pulls) — verbose multiline commit messages, high commit-count-per-PR; behavior configurable via `AGENTS.md`.
- ✅ **Agent Fingerprint study (MSR '26)** — [writeup](https://codex.danielvaughan.com/2026/04/30/agent-fingerprints-pull-requests-codex-cli-git-hygiene/) · [deep-dive](research/2026-06-18-agent-fingerprint.md) — analyzed **33,580 PRs from 5 agents**, 97.2% F1 agent-ID; **commit-message style alone = ~45% of feature importance**. Deep-dived 2026-06-18: **caught a real bug** — the worker hardcoded `feat:` for every commit, zeroing Clade's own fix-rate metric; **fixed** (commit-type classifier) + built the test-inclusion signal (PR body + commit-archeology dimension).
- ✅ **Sonar Foundation Agent** (ex-AutoCodeRover team) — [repo](https://github.com/AutoCodeRoverSG/sonar-foundation-agent) · [deep-dive](research/2026-06-18-sonar-foundation-agent.md) — **79.2% SWE-bench Verified**, ~10.5 min / ~$1.26 per issue. Deep-dived 2026-06-18: 0 gaps — they dropped rigid scaffolding for 1 agent + 3 tools, **endorsing Clade's iterating-loop design** ("give strong models more autonomy").
- **Ralph-loop implementations as code** — [snarktank/ralph](https://github.com/snarktank/ralph) (loop until all PRD items done) · [vercel-labs/ralph-loop-agent](https://github.com/vercel-labs/ralph-loop-agent) · [anthropics ralph-wiggum plugin](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md). **Steal:** how each encodes the explicit *completion check* — our VERIFY.md-anchor convergence problem, three other ways.

## The multi-agent debate

Clade runs supervisor + parallel workers. The strongest external critique of exactly that is worth holding in tension:

1. **Anthropic — [Multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system)** — *for* orchestrator-worker w/ parallel subagents (reads fan out well).
2. **Cognition — [Don't Build Multi-Agents](https://cognition.ai/blog/dont-build-multi-agents)** — *against*: parallel actions carry implicit decisions that fragment across contexts → incoherence.
3. **Cognition follow-up — [Multi-Agents: What's Actually Working](https://cognition.ai/blog/multi-agents-working)** — the walk-back: fan out **reads**, keep **writes single-threaded**.

**Clade's position to defend:** our workers write in isolated worktrees and `run-tasks-parallel` aborts+reruns serially on conflict (deterministic, never LLM-guessed merges) — which is closer to Cognition's "writes single-threaded" than to naive parallel writes. Re-check this every time we touch swarm/merge logic.

## Currency notes — dead or changed

Things my training memory (≤2026-01) had wrong, confirmed via web June 2026:

- ⚠️ **Roo Code — DEAD** (archived 2026-05-15; team pivoted to cloud "Roomote"). Cut from active list; keep only as an OSS→cloud-pivot cautionary tale. Migration path was Cline.
- ⚠️ **Windsurf → "Devin Desktop"** (Cognition acquired it from Codeium, ~$250M; Cascade local agent EOL 2026-07-01). Folded under Devin.
- ⚠️ **Gemini CLI → superseded by "Antigravity CLI"** (Google I/O 2026). Existing CLI still works; new features flow to Antigravity. Default model Gemini 3.1 Pro.
- ⚠️ **Goose → Linux Foundation / Agentic AI Foundation** governance (was block/goose).
- ⚠️ **Warp open-sourced** its client (May 2026) + shipped "Oz" cloud orchestrator.
- **New structural facts:** **ACP (Agent Client Protocol)** is becoming "the LSP for coding agents" (Zed, JetBrains, Google, GitHub, 25+ agents; registry Jan 2026) — consider whether Clade should speak it for editor portability. **MCP/A2A/ACP all now under Linux Foundation.** **AGENTS.md** is the AAIF-endorsed lightweight config standard. Anthropic shipped native **Dynamic Workflows** (up to 1,000 parallel subagents) + **Agent Teams** — first-party competition to our loop; track closely.

## Actionable gaps for Clade

Concrete, reversible things this study program surfaced. For the **full record** distilled from all 22 deep-dives, see [`research/README.md` → Open-gap backlog](research/README.md#open-gap-backlog-by-effort). **As of 2026-06-18 the backlog is empty — 0 open gaps across all 23 deep-dives.** The last 4 (iteration-start health check · test-inclusion signal · Fix-Rate per-iteration metric · read-only judge hardening) were built in commits `32556fd`/`49af13e`; everything else is built or different-not-deficient.

1. **PR-body craft** — adopt OpenHands' pattern in `worker_review.py`: reviewer-facing rationale + **runnable test-plan command** in the body, and emit self-corrections (lint fixes) as a *distinct labeled commit* rather than amending.
2. **Agent-authorship metric** — extend the existing fix-rate tracking into an Aider-style "% of release written by Clade workers" (git-blame at merge), surfaced in PROGRESS.md.
3. ✅ **Long-running-harness diff** — DONE 2026-06-18 ([deep-dive](research/2026-06-18-anthropic-effective-harnesses.md)): diffed Anthropic's "Effective harnesses" against our VERIFY.md + loop-runner + TLDR. Most primitives already covered; the one missing — an iteration-start health check — is the lone deferred 🟡.
4. **Multi-agent write-path audit** — confirm (and document) that our parallel workers never do LLM-guessed merges, per Cognition's walk-back.
5. **ACP scoping** — decide if speaking ACP makes Clade's skills/agents editor-portable enough to be worth it.

## How we vet what we absorb

*(Answering "the research tool itself — won't we learn crooked things?")* Output quality is driven by **scope-in and source-discipline**, which we control regardless of harness:

- **`/deep-research` is Claude Code's built-in, not ours** — we can't edit its internals, and don't need to. For a fully-owned, tunable harness we already have our own `/research` skill (writes to `docs/research/`).
- **Scope before mechanics** — a vague question yields a skewed report. State the decision the research must inform.
- **Source tiers** — prefer primary (the lab's own engineering blog, the repo, the PR) over secondary tech-press. Mark every unverified number `(unverified)` — see the flags throughout this doc.
- **Different ≠ deficient** — the absorption gate (from our auto-promoted rules): before marking anything a "gap," verify Clade's approach is demonstrably *deficient*, not merely *different*; compare mechanisms, not names (Ralph ≈ `/loop`). Confirmed gap → fix in code that turn.

## Changelog

- **2026-06-13** — Initial list created and web-verified (3 parallel research agents, June 2026). Added Tier structure, bot-behavior section, multi-agent debate, currency notes. Corrected: Roo Code dead, Windsurf→Devin, Gemini CLI→Antigravity, Goose→LF. New entries: Addy Osmani (Loop Engineering), Boris Cherny, Peter Steinberger, Anthropic "Effective harnesses for long-running agents", Agent Fingerprint study, Sonar Foundation Agent.
