---
title: "What was the field reading? Hacker News by points, read against the radar ledger"
date: 2026-11-16
review_date: 2027-02-16
status: needs_work
summary: >
  The owner asked what is new, how research sources are chosen, and how Clade
  can be sure to learn the methods that matter. Clade's research searched in
  two ways: TinyFish for interactive research and native WebSearch in the
  weekly radar cron. Both rank pages by how well they match a query, so
  neither sees what practitioners upvote. A pass over Hacker News by points for
  2026-10-17 to 11-16 kept 40 stories about coding agents, their tools and
  security, and model releases. The radar ledger held 8 of them. That
  morning's radar sweep had not surfaced three Claude Code security reports, at
  1,616, 1,014 and 627 points. /radar now runs this pass every week. Its eight
  queries returned all 40.
integrated_items:
  - "/radar §1 attention pass (configs/skills/radar/SKILL.md), and tests/test-radar-cron.sh §11, which fails when the skill names a host that the cron's WebFetch allowlist does not grant"
  - "Research ledger § Run 2026-11-16 interactive (~/.claude/research/known-concepts.md, outside the repo): one entry per item examined"
needs_work_items:
  - "TODO.md § 2026-11-16 attention-pass follow-ups: the Claude Code upgrade, a GitHub-stars pass, the overdue watch-list review"
  - "TODO.md § 2026-11-07 housekeeping audit, 'Radar review debt compounds': four radar branches are unlanded and three of them conflict with main"
reference_items:
  - "arXiv:2610.34577 (verification layers L0 to L3): Clade has all four layers"
  - "Watch-list candidates: Jane Street agent_skills, Modern Web Guidance, NVIDIA OpenShell, Pi"
---

# What was the field reading?

## Verdict

- **Clade searched by relevance only.** Interactive research used TinyFish, and
  the weekly radar used native WebSearch. Both return what matches a query. A
  method whose name no query contains is never found, however many people
  upvote it.
- **The gap was measured.** The pass kept 40 stories, listed below. The radar
  ledger held 8 of them. Three of the 32 it lacked were Claude Code security
  reports at 1,616, 1,014 and 627 points. The radar sweep that ran on the same
  morning had not surfaced any of the three.
- **Built:** `/radar` §1 now runs an attention pass. It fetches the newest
  stories above 150 points for eight queries, then sends them through the
  same steps as any probe result. The eight queries returned all 40 stories.
- **Not solved:** no pass guarantees that every method that matters is found.
  This one reads Hacker News only. The watch-list
  ([who-to-learn-from.md](../who-to-learn-from.md)) is a month past its
  quarterly review. Four radar branches still wait for review, so what the
  radar finds does not reach the code.

## Sources, and why each tool was used

| Run | Tool | Why | Sources |
|---|---|---|---|
| 2026-11-14 harness research | TinyFish, through the `web-search` skill's helper | its router sends five or more queries to TinyFish | first-party lab pages first (Anthropic engineering, Claude Code docs, Claude platform docs, OpenAI, Google AI); then papers; a secondary source only to find its primary |
| 2026-11-16 radar cron | native WebSearch and WebFetch | the cron's agent has no Bash, so it cannot call the helper; WebFetch is limited to an allowlist of hosts | probe-shaped queries (§1), arXiv, the Claude Code changelog |
| 2026-11-16 this pass | TinyFish for 12 relevance queries; native WebFetch for `search_by_date` | TinyFish returns a JSON API body as markdown, with escaped underscores, so rows had to be recovered by regex; WebFetch extracted all 50 rows of a page and matched spot checks | the Hacker News Algolia API; `gh search code` |

## Method

- **Population.** Two sets of results were pooled.
  - Twelve relevance-ranked queries to the Algolia `search` endpoint, for
    stories created after 2026-10-17T00:00Z, fetched through TinyFish. Each
    query had its own points floor: `agent`, `agents` and `Codex` above 150;
    `Claude`, `prompt` above 200; `LLM`, `coding`, `Anthropic`, `Gemini` above
    250; `OpenAI` above 300; `MCP` above 100; `harness` above 80. They
    returned 152 stories.
  - Native WebFetch of `search_by_date` for `agent`, `Claude`, `Codex` and
    `MCP`. Those rows were not saved; three kept stories came only from them.
- **Filter, by hand.** Kept: coding agents, their harnesses, tools and
  security, and model releases, within the 30 days to 2026-11-16. One incident
  counts once. Left out, for example: company finance and IPO news, policy,
  general technology, second reports of an incident already kept, two stories
  older than 30 days, and two that were not about coding (an Anthropic
  product page for whiteboards and sheets, and a tax-agent benchmark).
- **Ledger check.** Each kept story was matched against the ledger by regex,
  and every hit was read. Four hits named a different item and were rejected:
  - "GPT-6.1 Terra" matched an earlier entry on a model slug "terra";
  - "Gemini 4 Hydrogen" matched "Gemini 4 Argon";
  - "GPT-6 Astra covertly underperforms" matched two older "covert" entries;
  - OpenAI's "Patch the Planet" matched an entry on Huntley's post of the same
    name.

## The 40 stories, and what the ledger held

Points are as fetched on 2026-11-16. "Returned by" names the queries of the
`search_by_date` pass that returned the story, with typo tolerance on.

| Points | Date | Story | Ledger | Returned by |
|---:|---|---|---|---|
| 1,616 | 2026-11-05 | [Claude Code sends your email address to websites](https://news.ycombinator.com/item?id=50385272) | new | Claude, Codex, Anthropic |
| 1,096 | 2026-10-23 | [Kimi K3.1 Pro and K3.1 Pro Highspeed](https://news.ycombinator.com/item?id=50212065) | held (2026-10-26) | Codex |
| 1,014 | 2026-10-30 | [Backdoor in Claude Code for VS Code extension on the Cursor Marketplace](https://news.ycombinator.com/item?id=50300683) | new | Claude, Codex |
| 1,000 | 2026-11-09 | [Claude Fable 5.2 and Mythos 5.2](https://news.ycombinator.com/item?id=50429906) | held (2026-11-16) | Claude, Anthropic |
| 832 | 2026-11-08 | [Goodbye Claude, hello Pi](https://news.ycombinator.com/item?id=50410107) | new | Claude |
| 718 | 2026-11-10 | [Socratic Tutor](https://news.ycombinator.com/item?id=50438261) | new | agent |
| 679 | 2026-11-10 | [AlphaProof Code](https://news.ycombinator.com/item?id=50439193) | new | Codex |
| 647 | 2026-11-10 | [AI usage generates a fragile codebase](https://news.ycombinator.com/item?id=50438318) | new | Codex |
| 638 | 2026-10-26 | [GPT-6.1 Terra](https://news.ycombinator.com/item?id=50248124) | new | OpenAI |
| 630 | 2026-10-19 | [Ask HN: How to deal with shipping AI-written code you don't understand?](https://news.ycombinator.com/item?id=50151036) | new | Codex |
| 627 | 2026-11-07 | [Claude Code's "Don't Ask Again" exposes passwords in 1,122 public GitHub files](https://news.ycombinator.com/item?id=50407882) | new | agent, Claude, Codex |
| 603 | 2026-11-06 | [A Jev that can ask Opus for help gives Opus accuracy at 4x lower cost](https://news.ycombinator.com/item?id=50397429) | new | LLM |
| 591 | 2026-10-29 | [Claude Code regularly sends each background agent's transcript to its model](https://news.ycombinator.com/item?id=50284255) | held (2026-11-16) | agent, Claude, Codex |
| 573 | 2026-11-04 | [Ask HN: What's your current AI agentic setup?](https://news.ycombinator.com/item?id=50366117) | new | agent, Claude, Codex |
| 572 | 2026-11-12 | [Gemini 4 Hydrogen](https://news.ycombinator.com/item?id=50471431) | new | Gemini |
| 568 | 2026-10-21 | [Claude Duet](https://news.ycombinator.com/item?id=50186037) | held (2026-11-02) | Claude |
| 536 | 2026-11-03 | [OpenAI seems to be silently re-enabling model training on Codex chats](https://news.ycombinator.com/item?id=50352757) | new | Claude, Codex, OpenAI |
| 520 | 2026-10-18 | [Hybrid Reasoning Agents: LLM agents that think in latent space, act through text](https://news.ycombinator.com/item?id=50145337) | held (2026-10-19) | agent, LLM |
| 508 | 2026-10-22 | [OpenShell – A safe, private runtime for fleets of autonomous AI agents](https://news.ycombinator.com/item?id=50198675) | new | agent |
| 491 | 2026-11-04 | [A thousand fewer paths to root](https://news.ycombinator.com/item?id=50372929) | new | OpenAI |
| 476 | 2026-10-22 | [LLMs are making formal software verification feasible at a much larger scale](https://news.ycombinator.com/item?id=50202217) | new | LLM, Anthropic |
| 448 | 2026-11-10 | [Show HN: Get your coding agent off ~2019 JavaScript, onto modern web primitives](https://news.ycombinator.com/item?id=50443812) | new | agent, Claude, Codex, MCP |
| 362 | 2026-10-26 | [OpenAI's agents talked to each other through the CPU Cache](https://news.ycombinator.com/item?id=50251200) | held (2026-11-02) | agent, LLM, OpenAI |
| 348 | 2026-11-05 | [MCP Explained](https://news.ycombinator.com/item?id=50379249) | new | MCP |
| 343 | 2026-11-04 | [Ripple-65B Preview: U.S. Open-Weight SOTA on Agentic Coding](https://news.ycombinator.com/item?id=50369925) | new | agent |
| 342 | 2026-11-05 | [GPT-6 Astra covertly underperforms on safety research](https://news.ycombinator.com/item?id=50376313) | new | OpenAI |
| 303 | 2026-10-18 | [If you don't run your own LLM proxy, how do you know whats going on?](https://news.ycombinator.com/item?id=50145507) | new | LLM |
| 266 | 2026-10-21 | [Patch the Planet: global response coordination as agents uncover vulnerabilities](https://news.ycombinator.com/item?id=50181175) | new | agent, OpenAI |
| 253 | 2026-10-18 | [Show HN: Sphinx – A hook that quizzes you on your AI's code before shipping](https://news.ycombinator.com/item?id=50137950) | held (2026-10-19) | agent |
| 243 | 2026-10-21 | [Qwen3-Coder writes less secure code when told it's for a US persona](https://news.ycombinator.com/item?id=50179706) | new | Codex |
| 241 | 2026-11-11 | [Atuin Threads: All your agent sessions on every machine](https://news.ycombinator.com/item?id=50453637) | new | agent |
| 236 | 2026-10-31 | [ChatGPT and Codex usage limits merging](https://news.ycombinator.com/item?id=50320588) | new | Codex, LLM, OpenAI |
| 221 | 2026-11-09 | [ChatGPT Desktop forwards your SSH agent to remote machines](https://news.ycombinator.com/item?id=50422628) | new | agent, Codex, OpenAI |
| 213 | 2026-10-27 | [Here be monsters: What do you still need to know when agents do the work?](https://news.ycombinator.com/item?id=50258868) | new | agent |
| 191 | 2026-11-08 | [Agent memory needs its OpenTelemetry moment](https://news.ycombinator.com/item?id=50411467) | new | agent |
| 189 | 2026-11-07 | [The Components of Agent Memory](https://news.ycombinator.com/item?id=50402212) | held (2026-11-09) | agent, Anthropic |
| 174 | 2026-10-19 | [Tmux and Claude Code: Sessions, Send-Keys, and the Ceiling](https://news.ycombinator.com/item?id=50148855) | new | agent, Claude |
| 168 | 2026-11-02 | [Launch HN: Momentic (YC W24) – Agents that catch bugs by using your app](https://news.ycombinator.com/item?id=50339913) | new | agent, Claude, Codex, LLM, MCP |
| 163 | 2026-11-09 | [A year after the 100% AI mandate nobody understands our code](https://news.ycombinator.com/item?id=50433079) | new | Claude, Codex |
| 157 | 2026-10-19 | [Superlite: A Faster Alternatie to Superpowers](https://news.ycombinator.com/item?id=50147492) | new | agent |

## What the eight queries return

Each query asked `search_by_date` for 50 stories above 150 points.

- **Five queries** (`agent`, `Claude`, `Codex`, `LLM`, `MCP`) returned 36 of
  the 40. They missed:
  - GPT-6.1 Terra;
  - Gemini 4 Hydrogen;
  - OpenAI's "A thousand fewer paths to root";
  - "GPT-6 Astra covertly underperforms on safety research".
- **Adding `OpenAI`, `Anthropic` and `Gemini`** returned all 40.
- **The eight together** returned 319 distinct stories, 191 of them inside the
  window. Most are general technology news, which the topic filter drops.
- **Typo tolerance stays on.** With `typoTolerance=false` the eight returned 35
  of the 40. Typo matching on `Codex` is how stories about code, coders and
  codebases arrive. The strict version lost five, among them Kimi K3.1 Pro and
  "Qwen3-Coder writes less secure code".
- **Depth of the window.** The 50th hit of each query was dated:

  | Query | 50th hit |
  |---|---|
  | `MCP` | 2026-09-07 |
  | `Anthropic` | 2026-09-23 |
  | `LLM` | 2026-09-28 |
  | `OpenAI` | 2026-09-29 |
  | `Claude` | 2026-10-03 |
  | `agent` | 2026-10-10 |
  | `Codex` | 2026-10-19 |
  | `Gemini` | 2026-04-01 |

  `Codex` stopped two days short of the window, so the skill fetches a second
  page whenever a query's 50th hit is still inside it.

## Limits

- **The 40 are one reader's filter on one day.** Another reader would keep a
  different set. "8 of 40" says how often the ledger held what that reader
  judged relevant. It is not a recall figure for the field.
- **Hacker News only.** GitHub stars, Reddit, X, Lobsters and conference talks
  were not measured.
- **A miss in the ledger is not always a miss in Clade.** The ledger had no
  entry for Gas Town, Beads, OpenClaw, Hermes Agent or Antigravity, but the
  repository mentions all five.
- **The pass has not run unattended yet.** The 2026-11-23 cron is the first
  run that will follow the new step.
