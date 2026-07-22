# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md / TODO.md or acted on, they're cleared.*

## How this file works

- **Add an idea**: append a `## {date}` section with the idea, why it matters, and any sources.
- **Resolve an idea**: strike it through with `~~text~~` + a one-line "RESOLVED / DEFERRED + date + where-it-landed" reason.
- **Periodic cleanup**: when strikethroughs dominate the file, move them to `docs/archive/BRAINSTORM-resolved.md` so the inbox stays focused on live thinking.

Past resolved/deferred items live in [`docs/archive/BRAINSTORM-resolved.md`](docs/archive/BRAINSTORM-resolved.md).

---

## [Research] 2026-07-21 — 弱/便宜模型多轮 vs 强模型高 effort：token、时间、成本的 break-even

用户问题：是否已有研究比较“能力较弱但便宜的模型反复跑多轮”与“强模型单次高
reasoning effort”的总 token 和总时间。**结论：有相邻且相当直接的研究，但没有一个
跨模型、跨 coding-agent 工作流都成立的固定倍率。** 研究一致支持按任务动态分配
test-time compute；不支持“便宜模型多跑几次天然更便宜/更快”。

### 先拆开三种不同方案

| 方案 | token 规律 | 墙钟时间规律 | 什么时候可能赢 |
|---|---|---|---|
| 弱模型独立采样 `k` 次 + verifier 选优 | 总生成 token 近似线性 `k×`；共享 prompt/KV cache 只能降低算力或计费，不能把生成 token 变没 | 全串行近似 `k×`；足够并发时接近 `max(单次延迟)+verifier` | 可自动验证（测试、编译、形式证明），各次尝试有真实多样性，弱模型单次成功率不接近 0 |
| 弱模型串行 critique/revise `k` 轮 | 输出至少线性增长；若每轮重放完整历史，输入 token 最坏呈二次增长 | 必须等待上一轮，延迟相加，通常最慢 | 初稿已接近正确，反馈提供了新证据；适合容易/中等题，不适合模型根本不会的题 |
| 弱→强级联/路由 | 容易题只付弱模型成本；难题付弱+强，路由错误是主要损失 | 容易题快；升级题多一次弱模型延迟，可并行 shadow-call 缓解 | 请求难度分布很宽，能可靠估计置信度/失败，强模型只处理尾部难题 |

“多 agent 互相讨论”是第四种、通常更差的情况：它既不是独立采样，也不一定产生
新证据，还会复制完整 peer rationale，容易形成相关错误和上下文膨胀。

### 研究证据

| 研究 | 主要结果 | 对本问题的含义 |
|---|---|---|
| [Snell et al., *Scaling LLM Test-Time Compute Optimally*](https://arxiv.org/abs/2408.03314) | 按题目难度动态选 revision/search，能以最多约 `4×` 更少 test-time compute 超过朴素 best-of-N；在基座模型已有非平凡成功率时，小模型可在 FLOPs-matched 条件下胜过约 `14×` 大模型；最难题上追加 inference compute 收益很小 | “小模型多算”可以赢，但前提是**按难度分配 + 有 verifier/受训 revision**，不是盲目重试；模型能力地板仍存在 |
| [Brown et al., *Large Language Monkeys*](https://arxiv.org/abs/2407.21787) | DeepSeek-Coder-V2 在 SWE-bench Lite 从单样本 `15.9%` 提升到 250 样本覆盖率 `56%`，超过当时单样本 SOTA `43%`；无自动 verifier 时，投票/奖励模型在数百样本后平台化 | coding 有测试时 repeated sampling 很强，但这个胜利付出了最多 250 份候选的生成计算；“any sample solved”不等于现实中能低成本选出它 |
| [Zhu et al., *Scaling Test-time Compute for LLM Agents*](https://arxiv.org/abs/2506.12928) | agent 的并行采样、串行 revision、verifier、trajectory merge 都能扩展；关键是只在合适时 reflect、使用 list-wise 选择，并增加 rollout 多样性 | Clade 应优化“何时重试、怎样合并、怎样制造独立性”，而不是固定轮数 |
| [Bertalanič & Fortuna, *The Cost of Consensus*](https://arxiv.org/abs/2605.00914) | 10 个同质 7–8B agent、3 轮 debate 比独立 self-correction 多耗 `2.1–3.4×` token（最高每题 28,631），准确率相同或更低；观察到从众、正确答案被推翻等相关失败 | 烂模型互相讨论不会把十个弱判断变成一个强判断；无结构同质多轮应默认禁用 |
| [RouteLLM](https://arxiv.org/abs/2406.18665) | 学习型 router 在部分设置下保持质量同时把成本降低 `>2×` | 更稳健的省钱方式是“默认便宜，预测困难才升级强模型”，不是让弱模型无限自救 |
| [FrugalGPT](https://arxiv.org/abs/2305.05176) | 模型 cascade 在其 benchmark 上可匹配最佳单模型并最多降本 `98%`，或同成本准确率高 4% | 证明级联有巨大潜力，但数字来自较早的 QA/API 组合，不能直接外推到长时 coding agent |
| [Chen et al., *The Price Reversal Phenomenon*](https://www.microsoft.com/en-us/research/publication/the-price-reversal-phenomenon-when-cheaper-reasoning-models-end-up-costing-more/) | 8 个 2026 frontier reasoning models、9 类任务中，`21.8%` 的模型对出现“标价更低但总成本更高”，反转最高 `28×`；thinking-token 差异最高 `900%`，同题重复运行 thinking token 可差 `9.7×` | 不可用“每百万 token 单价”或模型档位代替实测总成本；高-effort 强模型也可能因更短、更少重试而更便宜 |

### 可计算的 break-even（比“便宜/贵”标签可靠）

设弱模型单次通过率为 `p_w`，强模型高-effort 通过率为 `p_s`。若弱模型的 `k` 次
尝试近似独立、且 verifier 能识别正确结果，则弱方案达到强方案成功率所需：

```text
k >= ceil(log(1 - p_s) / log(1 - p_w))

weak total tokens = k * (fresh input + output) + verifier tokens
strong total tokens = strong input + reasoning/output tokens
```

例如 `p_w=0.30`、`p_s=0.80`，至少要 `k=5` 才能达到 `83.2%` 的“至少一次成功”
覆盖率。弱方案只有在“单次全量成本 + verifier 摊销”小于强方案约五分之一时才更
便宜。若五次错误高度相关，独立假设失效，真实收益会远低于 `83.2%`；若 verifier
分不出对错，覆盖率也无法转化为最终正确率。

时间必须与 token 分开算：

```text
serial latency   ~= sum(all attempts) + verifier
parallel latency ~= max(all attempts) + verifier + queue/startup overhead
```

所以并行弱模型可能“墙钟更快、总 token 更多”；串行多轮通常“墙钟更慢、总 token
也更多”。这是 #21 中“只有异步/并行才有 speedup”的机制基础，但公开论文大多报告
accuracy-vs-compute/token，**很少报告真实 coding workflow 的端到端 elapsed time**。

### 对 Clade 当前成本模型的校正

- `codex-orchestrate` 的“实测总 token ~4×、orchestrator context ~3× less”可以保留为
  一次真实运行的 telemetry，不能升级成普适 scaling law。文献支持方向，不支持固定倍率。
- Clade 的目标函数不应是 token 最少，而应是
  `oracle-approved completions / wall-clock hour / dollar`，并同时记录失败重试和人类接管。
- CI/test 是天然低价 verifier：可验证 coding task 最适合 `N` 个独立候选并行；设计、
  架构和模糊需求没有可靠 verifier，更应直接用强模型，避免弱模型多轮共识幻觉。
- 最优默认不是二选一，而是 **cascade**：弱模型先做低风险/高可验证任务；一次失败、
  低置信度、无进展或高风险任务立即升级强模型。不要让弱模型连续自我解释 3–5 轮。
- 需要“多样化重试”而非“重复重试”：不同 decomposition/prompt/tool evidence，隔离上下文；
  否则错误相关性使 `1-(1-p)^k` 的理论收益不存在。

### Follow-up：让 Codex / Claude Code 高阶主 session 自主选择“自己做还是叫小弟”

**Verdict：两边原生都可行，值得拿进 Clade；但应采用“高阶 lead 做一次受约束的
route decision + policy/CI 硬边界”，不能让 lead 无限制自由 fan-out。** 先用原生
subagent profile 落地，再把相同 decision contract 接入 Clade 的跨 provider worker。

#### 2026-07-21 官方能力核对

| 主 session | 已有原生能力 | 可指定的小弟配置 | 关键限制 |
|---|---|---|---|
| Codex | Work mode 的 Ultra 能在并行确实改善速度/质量时主动委派；普通本地 Codex 在用户、`AGENTS.md` 或 skill 要求委派时执行 | `.codex/agents/*.toml` 可分别指定 `model`、`model_reasoning_effort`、tools/sandbox；未 pin 时 Codex 也可按任务平衡 intelligence/speed/price | subagent 总 token 高于单 agent；Spark 是 Pro-only research preview、偏 near-instant text-only，不应作为通用写代码 worker；本地普通档位不是无条件 proactive router |
| Claude Code | 内置 Explore 已自动用 Haiku 做便宜只读搜索；custom subagent 会按 request、`description` 和当前上下文自动触发，`use proactively` 可增强主动委派；`ultracode` 会对 substantive task 编排 dynamic workflow | subagent frontmatter 支持 `model`、`effort`、`background`、`maxTurns`、`isolation: worktree`；每次调用也可覆盖 model | Haiku 不支持当前 effort 档位，不要给它伪造 effort；agent teams 仍是 experimental、显著多耗 token，而且创建 team 需要用户确认；日常自动路由应优先 subagent，不是 team |

Sources: [Codex Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Codex Speed / Spark](https://learn.chatgpt.com/docs/agent-configuration/speed),
[Claude Code subagents](https://code.claude.com/docs/en/sub-agents),
[Claude Code model/effort](https://code.claude.com/docs/en/model-config),
[Claude Code agent teams](https://code.claude.com/docs/en/agent-teams).

#### 推荐的统一 routing contract

主模型只接收 task brief、风险标签、可用 verifier、预估文件范围，不先通读整个 repo；
否则它读完十个文件再委派，节省上下文/时间的 option value 已经消失。

```json
{
  "action": "self | delegate | fanout",
  "reason_code": "ambiguous | bounded | parallelizable | verifier_available | high_risk",
  "provider": "native | codex | claude",
  "role": "explorer | implementer | tester | reviewer",
  "model": "provider model id or alias",
  "effort": "low | medium | high | xhigh | max",
  "parallelism": 1,
  "verifier": "test command / CI / oracle / none",
  "escalate_on": ["no_diff", "test_fail", "same_error_twice", "scope_expansion"]
}
```

同一个 contract 在两个交互式主 session 中由主模型自己输出/执行；在 unattended
orchestrator 中先经过 deterministic guardrail，再转成 task 的 provider/model/effort。

#### 决策边界（lead 可判断，policy 不可绕过）

| Action | 适用条件 | 默认 worker |
|---|---|---|
| `self` | 需求含糊、架构/接口决策、跨层强耦合、没有可靠 verifier、安全/迁移/数据风险、只有一个很短的 critical path | 当前高阶模型，high/xhigh；真正极难才 max |
| `delegate` | 边界清楚、低风险、可运行 test/CI、只读搜索、日志归纳、机械变换、已有明确 repro | 同厂原生小弟优先：Codex Terra low/medium（Spark 仅显式 opt-in）；Claude Explore/Haiku，或 Sonnet medium 写代码 |
| `fanout` | 至少 2 个独立只读假设/审查维度，并行时间收益大于协调成本 | 2–3 个有不同任务/证据源的只读小弟；v1 不允许同一任务多写者，也不声称 orchestrator 已有候选合并 |

强制升级到 lead 的条件：cheap worker 无 diff、CI/测试失败、连续两次同类错误、发现
scope 比 brief 大、verifier 不可靠、触及 forbidden/high-risk 文件。**最多一次 cheap retry**；
第二次不是“再想一遍”，而是换强模型或换独立解法。

#### 同厂原生 vs 跨厂调用

- 主 session 默认叫**同厂原生 subagent**：启动/回传开销低，权限、thread、steering、
  background completion 都由各自 harness 管理。
- Codex 主 session 叫 Claude、或 Claude 主 session 叫 Codex 时，v1 只允许用户显式创建
  Clade task/调用现有 second-opinion relay；不把跨厂 lifecycle 假装成原生自动委派。
  `WorkerProvider` + worktree + oracle/CI gate 可执行显式 provider task，但 native session →
  cross-provider task 的自动桥接仍是后续工作。
- 不让小弟递归叫小弟：第一版 depth=1。递归 fan-out 会让成本归因、取消、文件所有权和
  convergence 都变得不可预测。

#### Clade 当前差距（代码核对）

- `tasks.provider` 和 `WorkerProvider(claude|codex)` 已有，完成结果/工作树/oracle 也已
  provider-neutral；这是很好的底座。
- `auto_model_routing` 目前只是 worker spawn 前按静态 `score`/critical-path 换
  haiku/sonnet/opus；不判断 `self/delegate/fanout`，也不根据 verifier/risk/失败历史决策。
- task schema 没有 `effort`/`delegation_action`；`ClaudeProvider` 未传现成的 `--effort`，
  `CodexProvider` 也未用 CLI 已支持的 `-c model_reasoning_effort=...`。
- `CodexProvider` retry 仍是 fresh session，尚未持久化 thread id；在此之前不应给 cheap
  Codex worker 多轮 retry，否则每轮冷读上下文抵消省下的模型成本。
- 现有 `test_routing_eval.py` 测的是“用户 query → skill 搜索”而非模型/provider/effort
  routing；不能当成本方案的 eval。

#### 2026-07-22 实现复核与落地

原计划不能原样实现：WorkerPool 明确禁止同一 task 同时启动第二个 worker，现有
`parallel_fix_samples` 只在 oracle plateau/critical path 上创建独立 retry task；因此若直接增加
`fanout` 字段，只会产生“schema 说支持、runtime 不执行”的 deploy gap。v1 已收敛并实现为：

1. Claude 全局规则 + `bounded-implementer`，以及 Codex 全局 `AGENTS.md` managed block +
   `clade_cheap_{explorer,worker}` profiles，让正在跑的高阶 session 在广泛读 repo 前做同厂决策。
2. 只读任务最多 3 个真正独立小弟；写任务必须单一文件 owner。小弟禁止递归委派，lead
   强制 review diff/verifier，cheap retry 最多一次。
3. task/worker/SQLite/API/UI 已贯通 `provider`、`model`、`effort`、`route_reason`；Claude 透传
   `--effort`（Haiku 自动省略），Codex 透传 `model_reasoning_effort`。所有 requeue/handoff 保留
   provider/effort。
4. `auto_model_routing` 现在 provider-aware：高 readiness 才进 Claude Haiku / Codex Terra；
   low readiness 或 critical path 进强 tier。默认仍关闭，等 replay eval 后才考虑 default-on。
5. 没有加入无运行语义的 `delegation_action` / `parent_session_provider`，也没有自动跨厂 bridge、
   同任务多写者或 Spark 默认。它们分别需要 lifecycle、候选选择/合并和 entitlement 检测。

#### 后续实施顺序

1. **Eval before default-on**：用前述 30–50 个历史任务比较 high-self、high→native-cheap、
   high→cross-provider；只有 success/$ 和 success/wall-hour 都不退化的 task class 才自动开启。
2. **Learned routing last**：先收真实 telemetry；样本不足时使用明确规则，不让一个未经校准的
   LLM confidence 直接决定成本和质量。

### Gaps vs current VISION

- 已有 task token/cost/duration 字段，但还不能按 `(task class, model, effort, attempt index)`
  计算首次通过率、级联升级率、verified success per dollar/hour；因此当前 router 无法学习
  真正的 break-even。
- 当前 model routing 主要按静态 task score 选 tier，缺少运行时升级条件：测试失败、
  无 diff、重复同类错误、verifier disagreement、首轮置信度低。
- 没有 A/B replay corpus 比较 `cheap×N`、`strong/high-effort×1`、`cheap→strong cascade`；
  只看某次运行的 token 倍率会把任务难度差误认为模型差。
- session report 应同时展示 total tokens、wall-clock critical path、并发度、美元成本和
  oracle-approved completion；任何单指标都会误导。

### Recommended additions to TODO.md（不自动添加）

- [ ] 建立 30–50 个真实历史任务的 routing eval：固定输入/commit/CI oracle，三臂对照
  `cheap×N parallel`、`strong high-effort×1`、`cheap→strong cascade`，至少重复 3 次估计方差
- [ ] 记录 `attempt_index`、`parent_attempt`、`effort`、`queue_ms`、`inference_ms`、
  `verify_ms`、`final_oracle`，按任务类型输出 pass@1、pass@k、success/$、success/wall-hour
- [ ] 把 router 改成 verifier-aware cascade：低风险可验证任务先便宜模型；首轮失败或
  高风险/无自动 verifier 直接强模型；设置最多一次 cheap retry，避免无界串行反思
- [ ] 用历史 telemetry 拟合每类任务的 empirical break-even，而不是在 prompt 中硬编码
  `4×`；数据不足时明确显示样本数与置信区间

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
