---
title: "Does Clade's harness hold the model back? What Anthropic, OpenAI and Google say, read against Clade"
date: 2026-11-14
review_date: 2027-01-14
status: needs_work
summary: >
  The owner asked three things: can a heavy harness hurt a growing model's
  creativity, what do the large labs advise, and please delete nothing.
  Anthropic, OpenAI and Google all answer yes for one kind of harness:
  prescriptive context. That means always-loaded rules, examples, repeated or
  conflicting instructions, and rigid multi-agent pipelines. Anthropic cut over
  80% of Claude Code's system prompt for Claude 5-generation models, with no
  measurable loss on its coding evals. It says it had been "overconstraining
  Claude Code", through the system prompt, CLAUDE.md files and skills.
  The labs say the opposite about verification, mechanical enforcement and
  safety guards. When they do cut, they remove one component at a time and
  check each removal against evals; they never cut everything at once.
  Clade's deterministic half matches that advice. Its always-loaded prose does
  not. Every Clade session loads 145k characters of always-loaded instructions,
  and two of Clade's own CI gates hold about 40% of the project file there.
  Whether that prose costs Clade quality, and not only tokens, has not been
  measured. Nothing was deleted.
integrated_items:
  - "Research ledger § Run 2026-11-14 (~/.claude/research/known-concepts.md, outside the repo): the first-party sources below, with their scope"
  - "TODO.md § 2026-11-14 harness-weight follow-ups, plus dated notes on the existing half-life and /doctor items"
  - "2026-11-16, on the owner's go-ahead: the CI checklist moved to docs/ci-gates.md and the orchestrator map to docs/orchestrator-architecture.md, with every gate that pins them retargeted; project CLAUDE.md 91,149 -> 54,777 chars; nothing deleted (TODO § 2026-11-14)"
needs_work_items:
  - "Owner: run /doctor and /doctor prompt-audit, Anthropic's own rightsizing tools, and accept or reject each proposal (TODO § 2026-09-28 radar sweep follow-ups)"
  - "Build the one-component-at-a-time ablation that the promoted-rule half-life item has lacked since 2026-10-12 (TODO § 2026-10-12 radar sweep follow-ups)"
reference_items:
  - "ALIGNED: mechanical enforcement (guardian, gates, ci-local, mutation tests), progressive disclosure (skills on demand, 11 path-scoped rules, hub sub-skills listed by name only), little emphatic wording"
  - "DEPARTS: always-loaded prose (1,146 + 535 + 115 lines against a recommended 200 per file), rules repeated across files, about 20k characters of auto-promoted rules never re-tested"
  - "NOT MEASURED: whether Clade's prose changes task outcomes, for better or worse"
---

# Does Clade's harness hold the model back?

## Verdict

**The claim is half right, and the labs say which half.**

- **Prescriptive context: they agree, with numbers.**
  - Anthropic removed "over 80% of Claude Code's system prompt for models like
    Claude Opus 5 and Claude Fable 5 with no measurable loss on our coding
    evaluations". It says "we were overconstraining Claude Code, both through
    our system prompt and in our CLAUDE.md files and skills" [A1].
  - OpenAI's leaner system prompts scored "roughly 10-15%" higher on internal
    coding-agent evals, with 41-66% fewer tokens [O2].
  - Google says Gemini 3 "may over-analyze verbose or overly complex prompt
    engineering techniques used for older models" [G1].
  - On creativity specifically, Anthropic found that examples "constrains them
    to a certain exploration space" [A1]. Rigid multi-agent structures "were
    often what stopped the new model from doing more of the work" [A3].
- **Verification, enforcement and safety: they recommend the opposite.**
  - Anthropic says a rule that "can't have exceptions" belongs in a hook [A6].
    It kept the planner and evaluator agents in its own long-run harness
    because "each continued to add obvious value" [A2].
  - OpenAI enforces its invariants "with custom linters and structural tests"
    and calls them "multipliers" [O1].
  - "The space of interesting harness combinations doesn't shrink as models
    improve. Instead, it moves" [A2].
- **How they cut: never radically.**
  - Anthropic's own engineer first "cut the harness back radically … but I
    wasn't able to replicate the performance of the original". After that he
    switched to "removing one component at a time and reviewing what impact it
    had" [A2].
  - OpenAI's guidance is the same: "Remove one group of instructions, examples,
    or tools at a time, then rerun the same evals" [O2].
  - Anthropic now ships `/doctor` and `/doctor prompt-audit` to propose these
    cuts [A1, A6].
- **Clade.** Its deterministic half is what the labs recommend: the guardian,
  the gates, `ci-local.py`, mutation-tested self-tests and `committer`. Its
  always-loaded prose is where it departs from them:
  - Every Clade session starts with **145,352 characters** of always-loaded
    instructions (1,146 + 535 + 115 lines of CLAUDE.md). Anthropic recommends
    "under 200 lines per CLAUDE.md file" [A6].
  - **About 40% of the project file is pinned there by two of Clade's own CI
    gates**: the CI checklist, and an architecture map of the dormant
    orchestrator. `/doctor` is built to cut exactly that kind of "architecture
    overview" [A6]. An independent study found that repository overviews "are
    not helpful" [P1].
  - Whether the prose costs Clade *quality*, and not just tokens, is
    **not measured**. The controlled studies disagree (see below).
- **Recommendation: delete nothing now.** Three steps, none of them a deletion:
  1. You run `/doctor prompt-audit`. It proposes cuts and you accept or reject
     each one.
  2. Relocate, don't remove: turn CLAUDE.md into a table of contents and
     retarget the gates. Their strength stays the same.
  3. Build the one-at-a-time ablation the half-life item has been waiting for.
     Let measured results decide every retirement.

## What the labs actually say

All sources were retrieved 2026-11-14 and read in full or by targeted passage.
Quotes are verbatim.

### 1. Prescriptive context shrinks as models improve

| Lab | What they did or advise | Scope |
|---|---|---|
| Anthropic [A1] | "We removed over 80% of Claude Code's system prompt for models like Claude Opus 5 and Claude Fable 5 with no measurable loss on our coding evaluations." The post's summary figure lists six shifts: "give Claude rules → give Claude judgement; give Claude examples → design interfaces; put it all upfront → use progressive disclosure; repeat yourself → simple tool descriptions; memory in CLAUDE.md files → auto-memory; simple specs → rich references". | Anthropic's internal coding evals, unpublished; Claude Opus 5 and Fable 5 |
| Anthropic [A1] | "while these constraints were once needed to avoid worst case scenarios, we have since found we can delete many of them and let the model use surrounding context and judgement instead." | Same post |
| Anthropic [A1] | Conflicting guidance has a cost. Given overlapping instructions, "Claude must think more carefully about these overlapping and conflicting messages before deciding what to do." | Read from Anthropic's internal transcripts |
| Anthropic [A1] | CLAUDE.md: "Keep your CLAUDE.md lightweight … spend most of the tokens on gotchas". "Avoid stating 'the obvious' things". "Use progressive disclosure heavily". Skills: "Avoid making them overconstrained, except in highly important areas." | Product guidance |
| Anthropic [A6] | "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence." "If Claude keeps ignoring a line that is in `CLAUDE.md`, adding IMPORTANT probably won't fix it. Either the file has grown long enough that the line gets lost, or the line is a rule that can't have exceptions, in which case it belongs in a hook." | Claude Code docs |
| Anthropic [A7] | Newer models "might now overtrigger. The fix is to soften any aggressive language", e.g. "CRITICAL: You MUST use this tool when..." becomes "Use this tool when...". "Remove over-prompting." "If your prompts previously encouraged the model to be more thorough or use tools more aggressively, reduce that guidance." | Platform prompting guide (written for the Claude 4.5/4.6 transition) |
| Anthropic [A8] | "Default assumption: Claude is already very smart". "Does this paragraph justify its token cost?" Match specificity to fragility: high freedom when "Multiple approaches are valid"; low freedom when "Operations are fragile and error-prone". | Skill authoring guide |
| Anthropic [A9] | "Avoid railroading Claude". "State the goal and the constraints, not every step." "A skill that restates what Claude would do by default adds context without adding value." | Claude Code team's skill practices |
| Anthropic [A3] | "a single agent with skills frequently outperformed both the one-prompt-for-everything design and the subagent design on quality". "most of this structure was doing work the model no longer needed done for it". | "several enterprise deployments", no numbers given |
| Anthropic [A10] | A fixed "record only failures" rule removed much of the memory gain for Opus 5 and 4.7. Prompting Sonnet 4.6 to read memory first nearly doubled its score. **The same kind of rule helped the weaker model and hurt the stronger ones.** | CL-Bench 1.0 database task, per Clade's 2026-11-09 note |
| OpenAI [O1] | "give Codex a map, not a 1,000-page instruction manual." The one big AGENTS.md "failed in predictable ways": "Too much guidance becomes non-guidance. When everything is 'important,' nothing is." "It rots instantly." "It's hard to verify." They "treat it as the table of contents", and the repository's knowledge became "the system of record" in `docs/`. | One product team, five months |
| OpenAI [O2] | Leaner system prompts "improved evaluation scores by roughly 10-15% while reducing total tokens by 41-66% and cost by 33-67%". "State each instruction once." Repeating "ask first," "do not mutate," or "wait for approval" "can cause unnecessary approval requests for safe, expected actions". | "a sample of internal coding-agent eval runs"; "treat these ranges as directional" |
| Google [G1] | "Be concise in your input prompts. Gemini 3 responds best to direct, clear instructions. It may over-analyze verbose or overly complex prompt engineering techniques used for older models." | Gemini 3 docs, two Google domains (verified from search snippets; the page body was not re-read) |

The older statement of the same idea comes from Sutton [S1]: building
knowledge into agents "always helps in the short term", but "in the long run it
plateaus and even inhibits further progress".

### 2. Verification, enforcement and safety stay, and move into code

- **Anthropic [A2].** Its full harness ran for 6 hours at $200, against 20
  minutes and $9 for a solo run, on one app-building prompt with Opus 4.5. In
  the solo run, "the central feature of the application simply didn't work". On
  Opus 4.6 the sprint construct was dropped and the evaluator moved to "a single
  pass at the end of the run". Both the planner and the evaluator stayed.
- **Anthropic [A6].** For checks that must hold, use a hook: "A line like
  `Always typecheck before you finish` in this file works most of the time, not
  every time." That job belongs to a Stop hook, and a `prompt` hook "isn't
  deterministic either".
- **Anthropic [A6], the other direction.** "The reverse holds too: if you have
  hooks for things that are only preferences, delete them and let Claude
  decide." So the hooks to keep are the rules without exceptions, not every
  hook.
- **Anthropic [A3].** Subagents "are effective at verification, parallel work,
  and modular permissioning". The single-agent design still keeps "firm output
  guardrails".
- **OpenAI [O1].** Invariants are enforced "with custom linters and structural
  tests", and their error messages "inject remediation instructions into agent
  context". In their words: "enforce boundaries centrally, allow autonomy
  locally".

### 3. How the labs cut

- **Anthropic [A2].** "every component in a harness encodes an assumption about
  what the model can't do on its own, and those assumptions are worth stress
  testing, both because they may be incorrect, and because they can quickly go
  stale as models improve." The radical cut failed. The method that worked was
  one component at a time. When a new model lands: "re-examine a harness,
  stripping away pieces that are no longer load-bearing to performance and
  adding new pieces".
- **OpenAI [O2].** "Start with a prompt and tool set that already works. Remove
  one group of instructions, examples, or tools at a time, then rerun the same
  evals." Keep examples and style guidance "when they encode a product
  requirement or correct a measured gap".
- **Anthropic's tools [A6].**
  - `/doctor` "cuts content Claude can derive from the codebase, such as
    directory layouts, dependency lists, and architecture overviews, and keeps
    pitfalls, rationale, and conventions that differ from tool defaults".
  - `/doctor prompt-audit` "flags instructions that were written for older
    models, point at files that no longer exist, or contradict each other".
    Both ship in the Claude Code installed here (2.1.283).

### 4. Creativity, specifically

The concern you raised has five first-party statements behind it:

- **Examples constrain exploration.** "giving examples actually constrains them
  to a certain exploration space" [A1]. In the talk version, examples "tend to
  constrain it because it's actually more imaginative than the examples we give
  it" (The Decoder's report of the talk, a secondary source [A11]).
- **Grading the path punishes valid approaches.** "agents regularly find valid
  approaches that eval designers didn't anticipate. So as not to unnecessarily
  punish creativity, it's often better to grade what the agent produced, not
  the path it took" [A4].
- **Rigid structure caps the new model.** Rigid multi-agent structures "were
  often what stopped the new model from doing more of the work" [A3].
- **"How" rules hurt stronger models.** "Say what memory is for, not how" [A10].

The common thread: the harness that constrains creativity prescribes **how**.
A harness that checks **what** came out (tests, gates, outcome graders) does
not, and the labs keep it.

### Independent evidence, and where it disagrees

- **arXiv:2602.11988 v3** [P1]. Context files "does not generally improve task
  success rates, while increasing inference cost by over 20% on average". This
  held "across different LLMs, coding agents", for both LLM-generated and
  developer-committed context files. Instructions "are well followed by coding
  agents", but "repository overviews, although popular and recommended by model
  providers, are not helpful". Its advice: "any attempts to improve performance
  should be rigorously evaluated before deployment".
- **arXiv:2605.10039** [P2], which Clade's CLAUDE.md already cites. This is
  counter-evidence on size. Across 1,650 Claude Code sessions (16,050
  function-level observations; primarily Sonnet 4.6), file-structure
  variables, among them file size, instruction position and contradictions,
  "did not produce detectable contrasts". The measure was compliance with one
  trivial annotation, not task quality. **Lab product guidance and this
  controlled study disagree on whether size alone hurts adherence.** Neither
  measured creativity.
- **IFScale, arXiv:2507.11538** [P3]. With 500 keyword-inclusion instructions,
  "even the best frontier models only achieve 68% accuracy", with a "bias
  towards earlier instructions". Twenty models from July 2025, on a narrow task.
- **arXiv:2610.32578** [P4]. One repository over six weeks, 118 failures, five
  replays with three runs each; the author calls it exploratory. On Sonnet 5.5,
  "In three of those four, the failure did not happen, with or without its fix".
  Only the stale-count failure came back without its check, and the check
  stopped it in every run. "A written rule on run-time estimates did not change
  Sonnet 4.5's overestimates." The conclusion: tools "add lessons faster than
  they retire them, so they should re-test their rules from time to time and
  retire the obsolete ones".
- **Vercel** [V1]. They replaced a tool-heavy text-to-SQL agent with one bash
  tool. Over 5 representative queries, success went from 4/5 to 5/5 and time
  from 274.8 s to 77.4 s, with 37% fewer tokens. The sample is small.
- **Already in the research ledger, not re-read today.**
  - Faros AI, 2026-08-19 [L1]: the largest cluster, 247 of about 4,000 rubric
    failures, was agents obeying harness boilerplate ("DO NOT MODIFY: Tests")
    and refusing required test changes.
  - arXiv:2601.20404 [P5]: across 10 repos and 124 PRs, AGENTS.md cut median
    runtime by 28.64% and output tokens by 16.58%, with comparable completion.
  - So a context file can be an efficiency lever even where it does not raise
    success rates.

## Clade, measured (the author's host, 2026-11-14, Claude Code 2.1.283)

### Always-loaded text in a Clade session

| File | Characters | Lines | Loaded in |
|---|---:|---:|---|
| `~/.claude/CLAUDE.md` (from `configs/CLAUDE.md`, 30,196 chars, plus a private tail) | 45,907 | 535 | every session, every project |
| `~/CLAUDE.md` (home routing) | 8,197 | 115 | every session under `~` |
| `CLAUDE.md` (this repository) | 90,726 | 1,146 | every Clade session |
| `~/.claude/rules/clade-web-search.md` (the only rule with no `paths:`) | 522 | — | every session |
| **Total** | **145,352** | | roughly 36k tokens at ~4 chars/token |

The project MEMORY.md index adds 5,065 characters. Claude Code's startup check
on this host has warned at "the 150.0k-char total limit" before (TODO.md
§ 2026-10-18).

The global file was consolidated from 73,577 to 38,458 characters on
2026-10-18 (TODO.md, the half-life item). It is 45,907 today. That is
[P4]'s finding in Clade's own history: lessons are added faster than they are
retired.

Here is what the project file holds, by `##` section:

| Section | Chars | Share | Pinned by a gate? |
|---|---:|---:|---|
| CI (GitHub Actions) | 24,569 | 27.1% | yes: `check-ci-checklist.py` reads the checklist (an 18,260-char code block) and the job counts from CLAUDE.md |
| Architecture — Surfaces and Layers | 20,995 | 23.1% | partly: `check-arch-map.py` (`--doc CLAUDE.md`) requires every module of the **dormant** orchestrator; its two subsections (Orchestrator Layer, Key File Map) are 12,191 chars |
| Key Commands | 12,871 | 14.2% | no |
| Auto-Promoted Rules | 10,670 | 11.8% | no; promoted 2026-04-15 to 2026-09-17 |
| Code Rules | 5,713 | 6.3% | no |
| The dotfiles sync store | 5,420 | 6.0% | no |
| Path-scoped rules | 3,822 | 4.2% | no |
| Seven smaller sections, plus the title line | 6,666 | 7.3% | no |

The two pinned blocks total 36,760 characters, 40.5% of the file. Most of the
CI and Architecture text is provenance: why a gate exists and what it caught.
That is valuable to a reviewer. A model writing code rarely needs it.

Repetition, which [O2] warns against, is present:

- The project file says the general architecture rules "are NOT repeated here".
  Its Code Rules then repeat the 1500-line cap with the reason "(Read tool
  default = 2000 lines)", which the global file explicitly retires ("The old
  reason … was a harness constant").
- The `pipeline()`-over-`parallel()` rule appears in both files.

Auto-promoted rules are about 20k characters of every session: 10,670 in the
project file and 9,902 in the global one (its largest section, 21.6%). Nothing
re-tests a rule once it is in.

Emphatic wording is already low, as [A7] asks: NEVER 2 / 1 / 0, MUST 0 / 1 / 0,
CRITICAL and IMPORTANT 0 in the global, project and home files. Bold spans are
88 / 37 / 7.

### Hooks by role

From `harness-usage.py --since 30`: main thread, 467 transcripts, 2026-10-16 to
2026-11-14, 36 hooks wired. Its own caveats apply: a fire means the hook ran,
not that behaviour changed, and an async hook can run without leaving a trace.

| Role | Hooks (30-day count) | Lab position |
|---|---|---|
| Deterministic guards | `pre-tool-guardian` 95 denies; `workflow-preflight` 3 denies; `secret-scanner` 2; `post-edit-check` 1 block; `linter-config-guard` and `ask-while-live` 0 (preventive) | keep [A6, O1] |
| Context injectors | `post-tool-use-failure` 1,315; `rule-injector` 1,076; `post-compact-reinject` 355; `session-context` 176; `correction-detector` 108; `skill-suggest` 86; `workflow-preflight` 68; `prompt-tracker` 41 | where any "preference" hook [A6] would be; **measure** before judging |
| Every turn end | Stop prompt hook (a model judges whether the turn may end), `iloop-hook`, `stop-check`: 3,140 fires each | verification, which labs keep; but a prompt hook "isn't deterministic either" [A6], and [A7] says to reduce "be more thorough" guidance written for older models; **measure** |
| Observers with no context traced | `memory-sync`, `sync-pull`, `commit-archeology`, `permission-request`, `sync-health`; async `edit-shadow-detector`, `revert-detector`, `worker-checkpoint` (no traces) | no context cost observed; out of scope |

`memory-sync`'s 3,723 errors all predate the #193 fix (last on 2026-11-06).

### Skills and agents

- **Skills: progressive disclosure already works the way [A1] and [A8]
  describe.**
  - 148 skills ship, 67 of them top level. Hub sub-skills are listed by name
    only.
  - 12 top-level skills were invoked on the main thread in 30 days, led by
    `create-pr` 78, `artifact` 23 and `web-search` 22.
  - The most-used skills keep a short `SKILL.md` and load references on demand
    (`create-pr` 832 chars, `artifact` 3,355, `delivery` 1,754).
  - The long single-file skills are `radar` (19,203 chars), `compute` (10,975)
    and `web-search` (8,195). They are the first place to look for
    "railroading" [A9].
- **Agents.** 40 definitions carry 8,218 characters of `description:` text,
  which the Agent tool lists in every session. 28 of them are marketing
  specialists (13 SEO, 6 ad-audit, 5 blog, 4 ad-creative).

## Lab guidance mapped onto Clade

| Guidance | Clade today | Status |
|---|---|---|
| Lean always-loaded instructions; the file as a table of contents [A1, A6, O1] | 145k chars, 1,796 lines across three files | **departs**, the largest gap |
| Progressive disclosure [A1, A8] | skills on demand, 11 path-scoped rules, hub sub-skills by name | aligned |
| Rules without exceptions go in hooks and linters [A6, O1] | guardian, preflight, `ci-local.py`, mutation-tested self-tests, `committer` | aligned; this is Clade's core |
| Hooks for mere preferences: delete them [A6] | the context injectors above; nobody has sorted them into rule vs preference | **not measured** |
| Soften aggressive language [A7] | NEVER/MUST counts above | aligned |
| State each instruction once [O2] | 1500-line and `pipeline()` rules repeated, one with a retired reason | departs (small) |
| Re-examine the harness when a model lands; one component at a time [A2, O2] | `retire-when` headers and `harness-usage.py` measure *use*; nothing measures a component's effect on outcomes | **partial**: the ablation is missing |
| Grade outcomes, not paths [A4] | `/loop` converges only when the verify command and every `--holdout` scenario pass; success criteria are never ticked by hand | aligned |
| Fewer subagents, more skills [A3] | a hand-rolled fan-out is capped at three agents | aligned; but 2,853 chars of Workflow-script rules sit in the always-loaded global file, and they matter only while writing a workflow |
| Avoid conflicting guidance [A1] | deliberate overrides of Claude Code defaults, e.g. Claude Code says "Commit or push only when the user asks", while Clade's global file has `committer` commit and push without asking | **not measured**; `/doctor prompt-audit` flags these |
| Rules written for older models [A1, A7, P4] | about 20k chars of auto-promoted rules, the oldest promoted 2026-04-15 | **not measured**: the half-life item |

## What to do, and what not to

In order. None of these deletes anything.

1. **You run `/doctor` and `/doctor prompt-audit`.** This is Anthropic's
   instrument for this exact question, and both ship in the installed 2.1.283.
   They propose; you accept or reject. The TODO item has been open since
   2026-09-28 and covers the global file, `configs/CLAUDE.md` and the skills.
   Add this repository's CLAUDE.md to that list.
2. **Relocate rather than delete (your decision).**
   - Move the CI checklist and the orchestrator architecture map to `docs/`,
     leaving a one-line pointer in CLAUDE.md.
   - Point the gates that read them at the new files:
     - `check-ci-checklist.py`: its `CLAUDE_MD` constant and the prose job
       counts;
     - `check-arch-map.py`: it already takes `--doc`;
     - `check-asserted-numbers.py`: three judge-diversity figures are pinned
       to CLAUDE.md.
     - `check-runnable-paths.py` already scans `docs/`.
   - Every gate keeps its strength and no text is lost. The two blocks are
     36,760 characters, so the project file would drop from 90.7k to about
     54k.
   - This is the layout both [A1] and [O1] describe.
3. **Build the ablation, then let it decide.**
   - A replay set exists: the 8 known-answer fixes the queued model-tier A/B
     already replays (`docs/research/2026-10-23-workflow-effort-and-reader-ab.md`).
   - Arms: the full layer, then the layer minus **one** group at a time:
     auto-promoted rules; the context-injecting hooks; the Stop prompt hook.
   - Measure hidden-check pass, tokens, turns and invariant violations, against
     a pre-set floor (the Gorokh floor already ledgered: two net solves).
   - Opt in only, per the paid-API rule. Re-run it when the next frontier model
     lands [A2].

**Do not:**

- **Cut radically.** Anthropic's own attempt failed to keep performance and
  hid which parts were load-bearing [A2].
- **Retire a preventive guard because it fired zero times.** Guards answer
  authority, not capability.
- **Take "less is more" on faith.** [P2] found no size effect, and [P1] found
  instructions well followed. The case for cutting rests on cost and on lab
  evals, not on a Clade measurement.

## Not measured

- Whether Clade's always-loaded prose changes outcomes, task success or
  "creativity" on Clade's own work. Only the ablation in step 3 can say.
- What the conflicts between Clade's instructions and Claude Code's defaults
  cost. No audit has been run.
- Whether the context-injecting hooks change behaviour, and which of them
  encode only a preference. A fire count is not an effect.

## Sources

Anthropic:

- [A1] Thariq Shihipar, "The new rules of context engineering for Claude 5
  generation models", claude.com blog, 2026-07-24:
  https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models
  (read in full from its Markdown mirror on claude.dev).
- [A2] Prithvi Rajasekaran, "Harness design for long-running application
  development", Anthropic Engineering, 2026-03-24:
  https://www.anthropic.com/engineering/harness-design-long-running-apps
- [A3] "Building agents: When to fold subagents into your main agent loop",
  claude.com resources, published 2026-10-22 per the page metadata:
  https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop
- [A4] "Demystifying evals for AI agents", Anthropic Engineering, 2026-01-09:
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- [A5] "Effective context engineering for AI agents", Anthropic Engineering
  (2025):
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
  - "the smallest possible set of high-signal tokens"
  - the "right altitude" between "hardcoding complex, brittle logic" and
    "vague, high-level guidance"
  - "agentic design will trend towards letting intelligent models act
    intelligently, with progressively less human curation"
- [A6] Claude Code docs, "Best practices" and "Memory":
  https://code.claude.com/docs/en/best-practices and
  https://code.claude.com/docs/en/memory
- [A7] Claude platform docs, "Prompting best practices":
  https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- [A8] Claude platform docs, "Skill authoring best practices":
  https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- [A9] "Lessons from building Claude Code: how we use skills", published
  2026-06-03 per the page metadata:
  https://claude.dev/blog/lessons-from-building-claude-code-how-we-use-skills/
- [A10] Lance Martin, "The components of agent memory", 2026-11-06, as read in
  [2026-11-09-agent-memory-components.md](2026-11-09-agent-memory-components.md).
- [A11] The Decoder, 2026-07-02, reporting Shihipar's AI Engineer World's Fair
  talk (secondary):
  https://the-decoder.com/anthropic-says-it-cut-80-percent-of-claude-codes-system-prompt-because-fable-5-models-want-a-smaller-system-prompt

OpenAI:

- [O1] Ryan Lopopolo, "Harness engineering: leveraging Codex in an agent-first
  world", 2026-02-11: https://openai.com/index/harness-engineering/
- [O2] OpenAI API docs, model guidance for GPT-5.6, "Favor leaner prompts":
  https://developers.openai.com/api/docs/guides/prompt-guidance?model=gpt-5.6

Google:

- [G1] "Get started with Gemini 3", "Precise instructions":
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/get-started-with-gemini-3
  The same sentence is in `ai.google.dev/gemini-api/docs/interactions/gemini-3.md.txt`.

Other:

- [S1] Rich Sutton, "The Bitter Lesson", 2019-03-13:
  http://www.incompleteideas.net/IncIdeas/BitterLesson.html
- [P1] arXiv:2602.11988 v3: https://arxiv.org/abs/2602.11988
- [P2] arXiv:2605.10039: https://arxiv.org/abs/2605.10039
- [P3] arXiv:2507.11538: https://arxiv.org/abs/2507.11538
- [P4] arXiv:2610.32578, 2026-10-23: https://arxiv.org/abs/2610.32578
- [P5] arXiv:2601.20404 (research ledger, 2026-11-07).
- [V1] Vercel, "We removed 80% of our agent's tools", 2025-12-22:
  https://vercel.com/blog/we-removed-80-percent-of-our-agents-tools
- [L1] Faros AI, 2026-08-19 (research ledger, 2026-10-10).
