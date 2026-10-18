---
title: Inspiration engines — has anyone built a good one, how should ours work, and where should it live
date: 2026-10-16
review_date: 2026-10-18
status: needs_work
summary: >
  The owner read a ChatGPT answer on "has anyone built a good inspiration generator"
  (verbatim in the appendix) and asked three things: does one exist, how should it work,
  and should it be part of Clade. A 14-agent sweep checked four evidence fronts (the
  answer's own claims, research systems, products, creativity research) and the internal
  assets, produced three competing designs, had them scored, and then had the synthesis
  attacked by two critics. The critics changed the v0. Verdict: partly. Structured tools
  measurably help a person feel supported in a single short session (Scideator, N=22).
  Lab systems close the loop when an expensive verifier sits at the end (Co-Scientist,
  Robin). Nobody has shown that an engine improves what one person or team actually does
  over weeks. The strongest result in the field is a warning: LLM ideas judged more novel
  lost that lead once 43 experts spent 100+ hours each executing them. Home: a Clade
  skill (/spark) beside /radar, incubated as a private personal skill until it beats
  simply asking Claude in a session with the same files. Company memory comes later, as
  a private overlay. UPDATED 2026-10-18: the owner split it in two — (A) project
  breakthrough, where a project's own trail and metric act as the verifier, and (B)
  big-direction collisions between new things in the world and our portfolio. A is built
  first, piloted on the face-swap SaaS; B becomes a lane of /radar.
integrated_items: []
needs_work_items:
  - "A (project breakthrough): round 1 run by hand on the face-swap SaaS (2026-10-18) — trail ledger, bottleneck, experiments. Codify the steps that worked into a private skill only after the round's experiments report back."
  - "B (big-direction collision): add a collision lane to /radar — new concepts from the sweep × the project portfolio, a few notes per month, judged by the owner."
  - "The single-engine /spark v0 below is superseded by the split; its operators, evidence pass and blind arms survive as parts of A and B."
reference_items:
  - "Buy option: InfraNodus MCP, 14-day trial, then paid; no user study. A blinded comparison arm only, and only for public-source questions."
  - "For measurable company problems (e.g. detector evals) the class with objective outcome evidence is verifier-grounded search (AlphaEvolve-style), which is a different project from an inspiration engine."
---

# Inspiration engines

← Back to [Research Index](README.md)

## Verdict

**Has anyone built a good one? Partly.** Three things are true at once:

- **Structure helps in the moment.** Scideator splits papers into
  purpose / mechanism / evaluation, retrieves papers at a chosen distance, and
  recombines them. It beat the same LLM without that structure on the Creativity
  Support Index: median 70.5 vs 61.0, Wilcoxon p<.01. The study had 22 CS
  researchers, each doing two 20-minute sessions. Their self-rated newness of
  their favourite idea moved only +0.5 on a 7-point scale, and no public code was
  found.
- **Lab systems close the loop when a verifier sits at the end.** Google's
  Co-Scientist (Nature 2026) produced drug candidates that experts then tested in
  liver organoids and AML cell lines. Its August 2026 extension (arXiv 2608.26701)
  drove a semi-automated CVD reactor and matched unpublished E. coli swarming
  data. In every case experts chose what to test.
- **Nobody has shown an engine improves what a person or team does over weeks.**
  The strongest evidence is a warning. In Si et al. (2024), 79 blind expert
  reviewers rated LLM ideas more novel than expert ideas (5.64 vs 4.84). In the
  execution study (arXiv 2506.20803), 43 experts then spent 100+ hours each
  executing randomly assigned ideas. LLM-idea scores dropped significantly more
  than human ones on all four metrics (p<0.05), and on many metrics the ranking
  flipped.

**How it should work.** Start from your question and your own first take, never
from a feed. Retrieve sources by *same purpose, different mechanism* at a
controlled distance. Generate with several independent operators, not one chat.
Check mechanically whether the connection already exists in your own material.
Show prior art but never score novelty with an LLM. Attach the cheapest test and
the result that would kill each idea. Count success only after you act.

**Where it should live.** In Clade, as a skill `/spark` next to `/radar`:
- The mechanism is generic tooling, and radar already owns the ledger it reads.
- Incubate v0 as a **private personal skill** in `~/.claude/skills/`, which
  `install.sh` never touches. It moves into `configs/skills/` only after it beats
  the status quo: asking Claude in a session with the same files.
- The company corpus is a later private overlay.
- Not a Mnemo feature now, and not a standalone product.

**Scope — answered 2026-10-18 by splitting it.** See the next section.

## Update 2026-10-18 — two engines, not one

The owner's correction: "inspiration" is two different jobs, and the single
`/spark` design above mixed them, leaning towards the second.

| | **A. Project breakthrough** | **B. Big-direction collision** |
|---|---|---|
| Question | This project is stuck — what moves the metric next? | What do new things in the world make possible for what we already have? |
| Input | The project's own trail: metrics, what changed when, what each change was meant to move, failed attempts | New concepts, papers and products × the project portfolio |
| Verifier | **Yes** — the project's own metric (activation, conversion, revenue, model eval) | None; the owner's judgment, paid back over months |
| Cadence | On demand, when a project plateaus | Low frequency, few notes |
| Evidence class | The only class with objective outcome evidence: verifier-grounded loops (Co-Scientist with a lab, AlphaEvolve with an evaluator) | Little evidence; the most prone to impressive-sounding noise |
| Home | A Clade skill that runs inside any project directory and reads that project's trail through the project's own credentials; no project data in Clade | A collision lane in `/radar`, which already sweeps for new concepts weekly and lacks only the "collide with our projects" step |

**A's loop:**
1. Rebuild the trail as a ledger: change → hypothesis → metric before/after → verdict.
2. Locate the bottleneck by leverage, with the arithmetic shown.
3. Retrieve same-purpose, different-mechanism practice from outside.
4. Propose experiments, each with a predicted effect, a test that is
   detectable at the project's traffic, and a kill criterion.
5. Measure the result and write it back to the ledger.

**What changes from the design below.**
- The single-engine `/spark` is superseded.
- A comes first, piloted by hand before anything is codified.
- B reuses radar's ledger instead of a new one.
- The operators, the evidence pass and the blind comparison arms are kept as
  parts of both.

## What exists, and what is proven

| System | Mechanism | Evidence (population) | Available? | Lesson for us |
|---|---|---|---|---|
| **Scideator** (arXiv 2409.14634 v7, CAIS 2026) | Facets (purpose / mechanism / evaluation); retrieval at near / far / very-far distance; recombination; facet-based novelty check | CSI 70.5 vs 61.0 vs same-LLM paper-level chat, N=22 CS researchers, 2×20 min, p<.01; newness +0.5/7. Participants said the checker called ideas "novel" too often | Research system; no public code found | Typed facets and an explicit distance dial beat free prompting on *felt* support |
| **Google Co-Scientist** (Nature 2026; arXiv 2502.18864) | Generate → review → pairwise tournament → evolve, grounded in literature | Organoid and AML candidates tested by experts. The Aug 2026 extension (2608.26701) ran closed-loop experiments in materials, biology and CS | Gated Labs waitlist for individuals | The loop is credible because an experiment sits at the end |
| **Kosmos / Robin** (FutureHouse / Edison) | Parallel analysis and literature agents; every statement cited | Kosmos: 102 expert-checked statements, synthesis held up 57.9% vs data analysis 85.5%. Robin: claimed 7.5×, humans measured 1.75× on the same data | Kosmos commercial; Robin Apache-2.0 | The "inspiration" step is the least reliable output |
| **InfraNodus** (WWW'19 method paper) | Co-occurrence graph → modularity clusters → distant-cluster "gaps" → AI bridge questions | One worked example; no user study found | 14-day trial, then paid; official MCP | Gap-finding is plain graph code; a gap is an entry point, not a finding |
| **SciMuse** (arXiv 2405.17044) | Knowledge-graph concept pairs → personalised LLM ideas | 100+ group leaders rated 4,400+ ideas: mean 2.40/5, 24.9% rated 4–5. Graph-chosen pairs did **not** beat a titles-only GPT baseline | Preprint | Plain prompting is a real competitor; log ratings from day one |
| **Swanson ABC / AGATHA** | A and C never co-cited but share intermediate B terms | Fish oil → Raynaud's, later an RCT. AGATHA ROC AUC 0.901 vs 0.718 on a post-2015 holdout | Method | The B-term chain *is* the stated reason for a connection |
| **Purpose/mechanism analogy** (Hope 2017; Kang 2022) | Same purpose, different mechanism | 46% good ideas vs 30% for TF-IDF retrieval (crowd workers); 32% vs 12% creative adaptation (8 graduate researchers) | Papers | Retrieve on purpose, require the mechanism to differ |
| **Sakana AI Scientist** | Autonomous idea → paper | v2: 1 of 3 papers scored 6.33 at a workshop with ~70% acceptance. Independent audit of **v1** (Beel et al. 2025): 5 of 12 experiments failed on coding errors in one recommender template, and its novelty check passed known ideas | Custom licence | Stop at "candidate + test"; don't automate execution |
| **Sublime** | Your saves plus other users' related public saves; canvas | No outcome evidence | Free tier; Premium $75/yr; MCP export | Serendipity over *public* material; it cannot read private memory |
| Readwise, Recall, Smart Connections, Mem, Heptabase, Tana | Resurfacing, "related" items | No outcome evidence found | Shipped, mostly with MCP | A habit loop, not inspiration |
| Elicit, Undermind, Semantic Scholar / Asta | Literature search and QA | Vendor-run recall claims | S2 API free with no key | Use for prior art, not for ideas |

## Fact-check of the pasted answer

| Claim | Verdict |
|---|---|
| InfraNodus finds structural gaps between topic clusters and has AI bridge them | Accurate (how-it-works page, WWW'19 paper, MCP `generate_research_ideas`) |
| "Try InfraNodus first" | Partly. 14-day trial, then paid, with commercial use on a higher tier. No user study exists, which the answer's own caveat anticipates |
| Sublime: saves, others' related saves, canvas, web / extension / iOS | Accurate; still active. Omits pricing and that "related" means other users' public saves |
| Scideator facets, distance-controlled retrieval, novelty check | Accurate |
| 22 researchers, CSI 70.5 vs 61.0, strongest on exploration and expressiveness | Accurate (**re-read at the source**). Omits the 20-minute sessions, +0.5/7 newness, and over-eager "novel" labels |
| Co-Scientist: multi-agent tournament, literature grounding, organoid result | Accurate; now Nature 2026 |
| "Propose connections with reasons" as the core of the ideal machine | Misleading as the core. Bridge/connection ideas are the LLM's own default: 47.1–64.2% of LLM ideas vs 12.1% of human ideas (11,683 papers, 9 LLMs, arXiv 2607.01233) |
| Omitted: the execution gap | The biggest omission (above) |
| Omitted: novelty checking is the weak step | Automated novelty judges swing >50 points on a prompt edit (arXiv 2610.02022, **Oct 2026 preprint**). 24% of 50 LLM research documents reused prior work without citation, per 13 experts (arXiv 2502.16487) |

## Why LLM ideas fail, and what the design does about each

| Failure | Evidence (population) | Design response |
|---|---|---|
| **Homogenisation** | Doshi & Hauser: 293 writers, 600 evaluators; 5 AI ideas raised novelty 8.1% but made stories more alike. Holzner meta-analysis: diversity g=−0.86 from only 6 effect sizes with severe heterogeneity (whole review 28 studies, 8,214 people). A second meta-analysis calls the effect small, so the size is disputed | Operators run as separate calls with no shared thread. Dedup against everything ever shown. Within-arm similarity is reported |
| **Novelty ≠ value after execution** | Si et al. execution study, 43 experts × 100+ h (above) | No LLM novelty score anywhere. Prior art is shown, never scored. Every card carries a ≤1-day test and its kill result. The primary metric is *acted on* |
| **Fixation** | Examples pushed at fixed intervals gave fewer ideas than none, while self-requested ones gave the most novel (Siangliulue, N=97). Many or common examples narrow thinking (design-fixation literature) | You write your own first take before any card appears. On request only, never pushed. One operator argues against your first take |
| **Unfalsifiable connections** | Bridge bias (above). SciMuse: graph pairs ≈ titles-only prompting | At most one bridge card per question, with an explicit A→B→C chain and locators. Mechanical "already connected in your material?" check |
| **Noise in synthesis** | Kosmos synthesis statements 57.9% accurate; Robin's 7.5× vs 1.75× | Citation validator: ≥2 real locators, and numbers must appear verbatim in their source |

## Design (v0)

`/spark "<question>"`, on demand only:

1. **First take.** You write 2–3 lines before anything is generated. These are stored.
2. **Inputs**, per question:
   - default: the current repository's README, TODO, BRAINSTORM and docs/research;
   - the radar digests and known-concepts ledger under `~/.claude/research/`;
   - `--corpus` adds paths.
3. **Retrieval** (stdlib TF-IDF). Near / mid / far snippets for the question's
   purpose, with the "same purpose, different mechanism" rule applied by the
   operator prompt. Shape: mostly conventional, one atypical link (Uzzi: 9.11
   hits per 100 vs a background of 5, over 17.9M papers).
4. **Three arms, compute-matched, same files, same output schema:**
   - *spark*: three independent tool-less calls (analogy transfer,
     relax-an-assumption, argue-against-your-first-take);
   - *status quo*: one well-prompted call with the same files and question;
   - *plain*: "give me ideas".
5. **Evidence pass**, identical for every arm:
   - the nearest existing items in your own material ("you may already have this");
   - a rebuttal;
   - the cheapest test and its kill result;
   - the citation validator;
   - one normaliser into a ≤10-line card.
6. **Blind rating.** Six shuffled cards, two per arm. For each card you tick
   new-to-me / valuable / will-test and guess its arm.
7. **Ledger** in `~/.claude/spark/ledger.jsonl`, with a 14-day follow-up:
   acted on (commit, PR or TODO link) or not.

Guards:
- Lines spark originated are tagged and excluded from future inputs, so it never re-derives its own output.
- Cards are never written into TODO.md automatically, because unattended workers read it. You rewrite a card to promote it.
- Cards derived from web or radar material are marked.

What runs where:
- Deterministic stdlib code: register, retrieval, dedup, validator, blinding, ledger.
- Subscription LLM calls, with no API key: generation, rebuttal, normaliser.
- Never added in v0: cron, facet extraction, a graph index. They are added only if v0 earns them.

Owner cost: about 3 minutes per question (first take plus six ticks), and one follow-up line two weeks later.

## Placement

**Decision: a Clade skill beside `/radar`, incubated privately.**

v0 lives in `~/.claude/skills/spark/`. That directory is private, synced by the
dotfiles store, and `install.sh` leaves it alone. Promotion to
`configs/skills/spark/` is a graduation step. Until then it pays none of the
public repo's gate overhead (doc counts, skill-listing budget, routing goldens)
and exposes no half-proven experiment.

| Rejected option | Why it lost |
|---|---|
| A mode inside `/radar` | Different novelty test (relational, not lexical). Radar is a scheduled sweep, spark is on demand. Spark *reads* radar's ledger and digests instead of duplicating them |
| A company-memory feature | Its measured retrieval was the weakest input at the time: 24/100 on 57 real questions (2026-07-02, 3,208 notes; not re-run since). Its body facts reached 15.1% R@5 (2026-08-17, before a 2026-09-02 re-rank that lifted its golden set to 112/176 hits). It delivers through a wiki to a terminal-only owner. Deploying it depends on a teammate. Revisit as an overlay once retrieval is re-measured |
| A standalone repo or product | A third home duplicating radar's cron and ledger, with the largest v0. Off the company's mission, in a crowded space where no product has outcome evidence |
| Buy InfraNodus | No free tier after 14 days, no outcome evidence, and only public-source material may be sent. Kept as an optional blinded arm |

**Public/private boundary:**
- The repository holds code and synthetic fixtures only. State lives in `~/.claude/spark/`.
- A company-memory overlay may show a card only when the viewer can see **every** source it cites (all-sources, not any-source). That rule gets a mutation test.

## Evaluation

- **Primary metric:** acted on within 14 days, with a link.
- **Early signal:** new-to-me AND valuable AND will-test. This is the owner's
  own criterion, and Bridger's two-checkbox test.
- **Baselines:** the status-quo arm, which spark must beat to exist, and the plain arm.
- **Blinding check:** if your arm guesses are more than ~70% correct, the blind
  failed and the comparison is reported as unblinded.
- **Sample and power.** Expect a single-digit to low-teens hit rate. That is an
  inference from SciMuse's 24.9% rated 4–5 by domain leaders. With 24 cards per
  arm, Fisher's exact test at α=.05 has power 0.31 two-sided and 0.43 one-sided
  to see 10%→30% (computed exactly, 2026-10-16), so significance is out of reach. Decide instead on P(spark > status quo) > 0.8 under a
  Beta-Binomial posterior, and print the false-kill and false-pass rates beside
  the threshold.
- **Decision** after ~12 real questions (about 4 weeks at three per week):
  - graduate into `configs/skills/` if the posterior rule passes and at least one acted-on card worked;
  - otherwise kill it and keep the first-take + ledger habit, optionally trialling InfraNodus in a 14-day window.
- **Self-tests:** deleting dedup, the blind key or the rating parser must turn
  them red, or no reported number counts.

A time-split "foresight" test was proposed and **demoted to a diagnostic**:

- Its post-cutoff "trajectory" is mostly commits and ledger entries written by
  the same model family that would generate the candidates.
- So it measures agreement with Claude's own defaults, which is the
  homogenisation problem.
- Any hit is by definition something reached without the engine.

## Open questions

- Scope (company vs own work), above. It is the one decision that changes the corpus.
- Every user study above is a single session of 20–60 minutes. No study measures
  effect on what a person ships over weeks; the ledger has to define that measure itself.
- Whether retrieval-distance seeds beat random ones on a small personal corpus.
  SciMuse says possibly not; v0's arms will show.
- Re-check October 2026 preprints (2610.02022, 2610.17439) before any published
  page. The design depends on neither.

## Provenance

**Re-read at the source on 2026-10-16:**
- arXiv 2506.20803: 43 experts, 100+ h each, significantly larger drops on all
  four metrics, ranking flip on many metrics.
- arXiv 2608.26701: Co-Scientist closed-loop extension, submitted 2026-08-27.
- arXiv 2409.14634 v7: N=22, 2×20 min, CSI 70.5 vs 61.0, Wilcoxon p<.01.

**Everything else** is from a 14-agent sweep that read the cited primary sources,
followed by an adversarial fact-check pass. That pass corrected these
attributions in an earlier draft:
- the Holzner population;
- the Sakana audit belonging to v1, not v2;
- the Si et al. ranges;
- the power figures.

Two numbers did not re-verify: InfraNodus's live prices render client-side, and
whether Scideator's code has since been released could not be determined.

## Appendix — the brief as pasted (2026-10-16)

Verbatim. The owner pasted this ChatGPT answer (from a conversation about memory
systems) and asked: 世界上是否已经有人造了，你觉得这种系统应该怎么样子处理，应该是 clade
的一个子部分还是如何处理.

> 有没有人造过灵感生成机，好用的那种
>
> Worked for 4m 15s
> 有，而且已经有人做出比“让大模型给我列 100 个点子”认真得多的系统了。 有的专门制造知识之间的新连接，有的会跨领域借用方法，还有的会生成假设、查新、反驳，再把候选交给人做实验。后两类已经有用户研究或实验室结果支持。
>
> 结合你刚才对记忆、联想、新颖性的兴趣，我觉得下面几个值得看。不过先说清楚：我没有逐个登录实测，产品推荐依据是公开功能与机制；论文中的效果证据，我会单独说明。
>
> 1. InfraNodus：最接近“从我的知识里挖出新连接”
> 这是我会建议你优先试的一个。
>
> 它不是先问“你想要什么点子”，然后自由发挥，而是让你输入笔记、文章、访谈或其他文本，把其中的概念变成网络：哪些概念经常一起出现、形成哪些主题，以及哪些主题之间很少建立联系。它会突出这些“结构空”，再由你或内置 AI 提出连接它们的新问题。
>
> 用一个我构造的例子说明：
>
> 你的一组笔记在讨论“记忆系统如何判断该保存什么”；另一组在讨论“产品如何根据用户反馈调整方向”。
>
> 系统不是分别总结，而是追问：
> 能不能让记忆的保留策略，也根据它后来是否真正帮助完成任务而调整，而不是只在录入时打一次重要性分？
>
> 这类输出至少有可能把你带到一个原来没探索的方向。
>
> 它吸引我的地方，是把“去哪里找新想法”变成了具体操作，而不只是要求模型“更有创意”。
>
> 但它的边界也很清楚：文本里的两个主题没连起来，不代表连起来就有价值。 也可能只是两件本来就不相关的事。所以我会把它当作“发现思考入口的仪器”，而不是自动发现真理的机器。
>
> 2. Sublime：更像“让你不断偶遇好材料”的灵感环境
> Sublime 的路线比较不同：你保存让自己感兴趣的文字、图片、文章等材料，它会围绕某个材料，找出其他人收藏的相关内容；也支持把收藏带到画布中组织和创作。它有网页端、浏览器扩展和 iOS 入口。
>
> 它提供的体验更接近：
>
> 你保存了一个关“信任”的观点，接着遇到一个建筑设计案例、一种游戏机制、一段产品设计论述。你开始意识到，它们可能在解决相似的问题。
>
> 这里的例子是我的说明，不是它实际给我的推荐。
>
> 我的判断：它适合文章、设计、产品表达这类“我需要一个新的视角”，而不是“请替我证明一个新算法”。
>
> 它没有承诺替你完成最后那步创造。它更像是改善你的灵感原料和相遇方式：让你不必永远从空白聊天框开始，也不只在自己原有收藏里打转。
>
> 3. Scideator：机制上最值得你研究的“新想法生成器”
> 这个和你关心的算法问题最贴近。
>
> 它从你提供的论文出发，把论文拆成几个可操作的部分：想解决什么问题、使用什么机制、如何评估效果。然后检索相关程度不同的其他论文，让人选择这些部分，再通过类比与重组生成研究方向。最后，它还会检索已有文献，检查候选想法与前人的工作有多大重叠。
>
> 可以粗略理解成：
>
> 不只是“总结论文 A、B、C”。
> 而是“论文 A 的问题，能不能借用论文 B 的机制，并用论文 C 的评估方式检验？”
>
> 当然，真正困难的是解释为什么这个方法能迁移过去，不是把三个名词拼成一句话。
>
> 它有没有“好用”的证据？
> 有，但需要准确理解。
>
> 最新版本论文中的研究让 22 位计算机科学研究者分别使用 Scideator 和一个采用同一底座大模型、但没有这套结构化模块的对照工具。Scideator 的“创造力支持指数”中位数为 70.5，对照为 61.0，差异具有统计显著性；优势尤其体现在探索想法和表达思路上。
>
> 这支持的是：
>
> 把检索、交互和生成方式设计好，确实可能比单纯和同一个模型聊天更能启发人。
>
> 但它不是“生成的论文最后更容易发表”或“重大原创成功率更高”的证明。研究测的是短时间内的创意支持体验，不是长期科研产出。它也应先被看作研究系统，而不是默认能随时注册使用的成熟消费级产品。
>
> 4. Google Co-Scientist：不仅要“有想法”，还要经得起检查
> 它更接近一支围绕研究目标运作的小型团队：不同 AI 角色负责提出假设、审查、比较排序、合并改进，再继续迭代。系统还会引入文献和外部数据库，减少想法只在模型内部自说自话的情况。
>
> 它比单纯灵感工具更往前走的一点，是已经有部分候选经过实验检验。 例如，论文报告了肝纤维化方向的候选靶点及药物，其中部分在人体肝类器官实验中显示抗纤维化活性。这里是实验室模型结果，不是已经证明临床治疗有效。
>
> 所以，“机器提出值得认真验证的新方向”不是纯粹的设想；但这也不意味着它已经是一台适用于创业、艺术、科研所有场景的通用灵感机。
>
> 跟你刚才的记忆讨论接起来，最重要的区别是什么？
> 我觉得可以这区分：
>
> 记忆系统：我已经知道什么，什么时候该拿出来？
> 灵感系统：这些知识之间，还有什么值得建立、但尚未建立的联系？
>
> 因此，即使一个记忆系统收录、更新、检索都做得很好，也不能直接推出它会产生好灵感。保存得好和联想得好，是两个需要分别设计、分别评估的能力。
>
> Scideator 有个很值得借鉴的设计：它不只找最相似的论文，而是控制检索距离，让用户同时接触同一主题和不同领域的材料。我的理解是，这比简单地把“不相似程度”当成新颖性分数更有意义：既要跳出原来的范围，又要解释跨过去的理由。
>
> 沿着你的思路，我会把理想的灵感机设计成：
>
> 你真正关心的问题 + 你的记忆 + 外部新材料 → 提出有理由的新连接 → 查重与反驳 → 留下少量值得验证的候选。
>
> 重点甚至不该是“每天给你 100 个点子”，而是它能不能偶尔准确地说：
>
> “这两件你分别考虑过的事情，其实可能用同一种机制解决。这里是连接的理由、已经有人做过的部分，以及剩下那个最值得试的小问题。”
>
> 所以我的结论是：有值得试的产品，也有真正有效的研究路线。对你，我会优先试 InfraNodus，重点研究 Scideator；Sublime 更适合日常积累和偶遇灵感。判断它们是不是‘好用’，我会看它有没有带来一个你原本没想到、且愿意动手验证的方向，而不是输出读起来有多惊艳。
