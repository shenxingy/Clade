# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into GOALS.md / TODO.md or acted on, they're cleared.*

## How this file works

- **Add an idea**: append a `## {date}` section with the idea, why it matters, and any sources.
- **Resolve an idea**: strike it through with `~~text~~` + a one-line "RESOLVED / DEFERRED + date + where-it-landed" reason.
- **Periodic cleanup**: when strikethroughs dominate the file, move them to `docs/archive/BRAINSTORM-resolved.md` so the inbox stays focused on live thinking.

Past resolved/deferred items live in [`docs/archive/BRAINSTORM-resolved.md`](docs/archive/BRAINSTORM-resolved.md).

---

## [Reconciled] 2026-07-28 — executable backlog

This is the authoritative inbox after comparing every unchecked historical item
with landed commits and `IMPLEMENTATION_PLAN.md`. Historical research remains
below as evidence; checked items there are resolved/superseded/rejected rather
than deleted. The reconciled research program has nineteen entries, each
mirrored in `TODO.md`. Checked entries in this block have landed; its two
unchecked entries are conditional watches, not executable work. Follow-on
runtime gaps discovered after reconciliation are tracked separately in
`TODO.md`.

- [x] **P0 / RESOLVED 2026-07-28:** both MCP servers now use Python SDK v2
  low-level `on_*` handlers and require `mcp>=2.0.0,<3`; a real stdio test
  negotiates the oldest supported v1-era protocol (`2024-11-05`).
- [x] **P0 / RESOLVED 2026-07-28:** runtime events, session/trace JSONL,
  SQLite runtime text, and provider output are redacted before persistence
  with secret-free metadata.
- [x] **P1 / RESOLVED 2026-07-28:** `clade.evidence/v1` now persists redacted,
  append-only attempt revisions with validated lifecycle transitions,
  canonical SHA-256 predecessor chains, and SQLite immutability guards.
- [x] **P1 / RESOLVED 2026-07-28:** worker attempts now capture execution,
  timing, exact Git SHAs, tests, oracle verdicts, optional artifacts,
  usage/cost, and delivery candidates; delivery exposes an attempt-linked
  projection, and task detail API/UI show verified bundles.
- [x] **P1 / RESOLVED 2026-07-28:** incidents, oracle
  rejection/unreviewed/disagreement, managed reverts, and explicit corrections
  create deduplicated sanitized quarantine records pinned to exact immutable
  evidence; raw hook JSONL is deliberately excluded.
- [x] **P1 / RESOLVED 2026-07-28:** explicit CLI/API review requires reviewer,
  reason, target, and a corpus-specific human label; promotion atomically
  writes non-overwriting oracle/resolve fixtures with exact provenance, while
  rejection writes no corpus data. No automatic ground-truth path exists.
- [x] **P1 / RESOLVED 2026-07-28:** `/equip` approvals are bound to the exact
  audited upstream commit; apply refreshes the cache and fails closed on
  legacy reports or drift until re-screened.
- [x] **P2 / RESOLVED 2026-07-28:** API/dashboard publish
  denominator-explicit evidence completeness, exact-source integrity,
  confirmed false approvals, human overrides, candidate states, and accepted
  corpus coverage; empty denominators are `null`, never fake zeroes.
- [x] **P2 / RESOLVED 2026-07-28:** immutable attempt evidence records
  parent-attempt lineage, explicit queue/inference/verify phase timing, the
  resolved route, final oracle, and outcome without a SQLite schema change.
- [x] **P2 / RESOLVED 2026-07-28:** an offline matched-arm routing corpus
  compares strong-self, native-cheap, and cheap→strong on fixed sanitized
  task/base/verifier inputs and fails closed below the declared sample gate.
- [x] **P2 / RESOLVED 2026-07-28:** the verifier-aware cheap→strong cascade is
  default-off and requires a declared deterministic verifier, bounded
  low-risk ownership, replay coverage, and explicit task-type eligibility.
  Missing or failing cheap verification escalates to strong; production
  reports remain observational and cannot enable routing.
- [x] **P2 / completed 2026-07-28:** publish production-only empirical routing
  break-even reports with sample counts, deterministic 95% intervals, visible
  exclusions, and a 30-sample floor. Reports stay observational and cannot
  mutate routing without matched task/base/verifier counterfactual evidence.
- [x] **P2 / completed 2026-07-28:** provider/model registry uses secret-safe
  native profile references, live TTL discovery, configuration-bound cache
  identity, capability provenance, real worker connection selection, and
  explicit pinned-only stale fallback.
- [x] **P2 / completed 2026-07-28:** six sanitized runtime/provider/surface
  fixtures cover every registry adapter and generated surface; deterministic
  CI replay is paired with separately credential-gated Anthropic/OpenAI live
  catalog smoke, redirect refusal, and HTTPS-only discovery.
- [x] **P2 / RESOLVED 2026-07-28:** internal runtime terminology is canonical,
  old settings and SQLite rows migrate idempotently, new writes and responses
  omit `provider`, and old API inputs emit deprecation headers plus secret-free
  aggregate usage counters. Final alias/column deletion is deliberately gated
  on a stable zero-use release (`docs/COMPATIBILITY-RETIREMENT.md`).
- [x] **P3 / RESOLVED 2026-07-28:** VISION/API/dashboard define strict verified
  delivery rate as the North Star and keep evidence completeness, false
  approvals, overrides, regression coverage, and source integrity as explicit
  guardrails. Concurrent attempt phase time is not mislabeled unattended time.
- [x] **P3 / RESOLVED 2026-07-28:** English/Chinese product docs now position
  Clade around provider-neutral identity, immutable evidence, calibrated
  verification, human-grounded corrections, exact-SHA delivery, and fleet
  truth. Orchestrator auto-merge also stopped treating squash as a universal
  default and now preserves live topology/history semantics.
- [x] **P0 / RESOLVED 2026-07-28:** installed merged `main` into this server's
  Claude/Codex user config, preserved the existing user key sets, migrated the
  Orchestrator settings to canonical runtime/connection/merge fields, refreshed
  the local Codex plugin cache, and removed completed branch state. Final
  delivery returns to synchronized `main`.
- [ ] **CONDITIONAL WATCH:** adopt Beads-style agent-filed note-to-self entries
  only if measured loop-runner context loss recurs.
- [ ] **CONDITIONAL WATCH:** delete the remaining runtime input aliases and
  historical SQLite column only after one stable release records zero
  compatibility events.

**Deliberate non-work:** automatic draft-PR publication is **REJECTED
2026-07-28 by authority design**. Delivery may publish an explicitly authorized
draft, but never creates one automatically. Universal-harness phases 0–2 are
**RESOLVED 2026-07-28** in PR #34 (`2fcc82a`); only the separately planned
phase 3–5 completion work remains and is represented explicitly by the
provider-registry, conformance, shim-retirement, evidence, and routing items
above rather than by stale phase-level duplicates.

---

## [AI] Friction Log

Live section — append new entries here as they happen. Do not archive this
section; it is an ongoing log, not historical research.

[2026-06-12] loop-runner: work completed but exit reason read stuck_no_commits — supervisor kept planning after 5/5 criteria met instead of returning CONVERGED / workaround: verified convergence manually via git log + gates
[2026-06-12] loop-runner: commits stay local — no push phase, fleet sync silently deployed stale HEAD / workaround: manual git push before node pulls; consider a [DET] push node after commit_changes
[2026-06-14] browser-verify: `npx playwright install chromium` resolves a different playwright version than `@playwright/mcp` bundles → "Removing unused browser" + version-mismatch box on first setup / workaround: it still lands the right chromium build (verified chromium-1223 present + MCP launched); documented as expected in configuration.md. Cleaner fix: pin the browser install to @playwright/mcp's bundled version.
[2026-06-14] frontend-detect: real projects (scamai-landing) describe their stack in CLAUDE.md prose ("Built with Next.js 15"), not the template's structured `Frontend:` line — _is_frontend_project returned False, visual-verify directive would never inject / FIXED a1e807d: _project_is_frontend now also reads package.json deps. Lesson: don't gate on a doc format real projects don't follow (deploy-gap).
[2026-07-29] loop-runner: reproduced the 2026-06-12 false-stuck path on the documentation convergence goal — two worker waves committed and verified the requested state, but the coordinator left all 5/5 goal checkboxes open and exited `stuck_no_commits`. Worker-side marking was deliberately removed for race safety, so the replacement must be coordinator-owned completion reconciliation. PROMOTED to TODO.md P0 follow-on.

---

## Historical / Archived Research

Everything from here to the end of the file is dated research/investigation
material that has already been resolved, superseded, rejected, or folded into
the reconciled backlog above. It is retained as evidence of what was checked
and why — read it as a record, not as a second backlog of open work.

## [Research] 2026-07-28 — 全量重学：人物、近期 commits 与 2026-H2 agent 工程转向

用户问题：把此前研究过和 watch-list 上的人物、项目重新学一遍，重点检查近期
commit/文章是否说明旧做法已经过时。研究窗口优先取 2026-05-01 至今；没有新公开
证据时回溯到 2026-01，并明确标成“未发现”，不把沉默解释成转向。

**总判断：旧的 loop 没有被淘汰，但它已经从“自动写代码的循环”升级成“能交付
可验证证据的循环”。** 近期最一致的变化不是堆更多 agent，而是：

1. **maker 与 checker 分离，交付物必须自带证据。** 测试、截图/视频、成本、
   模型、commit、verdict 要能一起复查，不能只收一句“完成了”。
2. **失败进入永久学习回路。** incident、错误审批和人工纠正应进入 regression
   corpus；下次发布前重放，而不是只写一段 retrospective。
3. **持久 thread/turn + 可重放事件正在成为 harness 核心。** CLI/TUI/IDE 只是
   client，恢复、审批、背压和 schema 才是稳定层。
4. **skills/hooks/playbooks 变成 repo-owned policy。** 指令和工具按需披露；
   产品里的 slash command、角色名和 UI 布局反而是最不值得复制的部分。
5. **安全默认值进入日常工程。** 日志脱敏、容器/Action pin、调用者权限透传、
   幂等副作用和 worktree 隔离不再是附加项。

### 人物重新核查

| 人物 | 最近可验证信号 | 相比旧认识的变化 | 对 Clade 的含义 |
|---|---|---|---|
| **Geoffrey Huntley** | [Everything is a Ralph loop](https://ghuntley.com/loop/) 与 [Don't waste your back pressure](https://ghuntley.com/pressure/)（2026-01-17） | 没有转向复杂 swarm；更明确反对无约束 multiplexing，强调 one-task-per-loop 和失败反馈永久化 | `/loop` 方向仍对；并行只用于真正独立的读或隔离写，重复失败必须落成 test/hook/rule |
| **Dexter Horthy / HumanLayer** | 最近可确认的一手代码活动是 [humanlayer#936](https://github.com/humanlayer/humanlayer/pull/936)（2026-01-10） | 2026-05 后未发现足够公开证据，不能声称 12-Factor Agents 已换方向 | 保留 approval/escalation boundary；不要从沉默推导新架构 |
| **Garry Tan / gstack** | [gstack CHANGELOG](https://github.com/garrytan/gstack/blob/main/CHANGELOG.md)：2026-03 至 05 增加 append-only learnings、置信度、衰减、transcript 检索和并发 ship collision guard | 从技能 preamble 转向“有 provenance、confidence、decay 的持久记忆”，同时保护交付并发 | Clade 的 corrections/rules 需要继续保持来源与失效语义；delivery 锁方向得到验证 |
| **Addy Osmani** | [Loop Engineering](https://addyosmani.com/blog/loop-engineering/)（06-07）、[Agentic Code Review](https://addyosmani.com/blog/agentic-code-review/)（06-15）、[Own the Outer Loop](https://addyosmani.com/blog/own-the-outer-loop/)（07-15）、[Software Factories, Light and Dark](https://addyosmani.com/blog/software-factories/)（07-20） | 从“如何跑 loop”推进到“人必须拥有 outer-loop 的责任、证据和 ship verdict”；也警告同族模型 checker 有相关盲点 | North Star 不能只看 autonomous hours；需要同时看 evidence quality、false approval 与 human-owned verdict |
| **Boris Cherny** | 2026-06 meetup 仍以“从写源码到管理 agents”为主；[Claude Code issue #42796](https://github.com/anthropics/claude-code/issues/42796) 记录 adaptive thinking 偶发零推理时可回退固定 reasoning budget | 没找到 2026-05 后可稳定归属的个人 commit；可确认的是“自动 loop 也要保留确定性回退旋钮” | 记录 resolved model/effort 和失败轨迹；模型策略变化不能让运行不可解释 |
| **Thorsten Ball** | 最近可确认的 agent 一手内容仍是 [Joy & Curiosity #73](https://registerspill.thorstenball.com/p/joy-and-curiosity-73)（2026-02-08） | 2026-05 后无足够新证据 | 旧的最小 agent loop 仍是参考，不据此发明新缺口 |
| **Simon Willison** | [Claude Code team fireside](https://simonwillison.net/2026/Jul/21/cat-and-thariq/)（07-21）、[sqlite-utils 4.0rc2](https://simonwillison.net/2026/Jul/5/sqlite-utils-fable/)（07-05）、[让 agent 录 demo 视频](https://simonwillison.net/2026/Jun/30/shot-scraper-video/)（06-30） | 从“代码能跑”进一步要求可观察 demo、公开成本/agent 贡献；incident PR 会进入 code-review eval set | UI/行为任务应产出 replayable demo；事故与错误审批自动加入 eval corpus |
| **Hamel Husain** | [Evals Skills for Coding Agents](https://hamel.dev/blog/posts/evals-skills/index.html)（03-02）、[It's Hard to Eval Is a Product Smell](https://hamel.dev/blog/posts/eval-smell/index.html)（06-29） | 从事后打一个 generic score，转向让产品先输出来源、中间计算、不确定项和可重跑 artifact | task output 设计本身必须可评估；先定义 evidence schema，再谈更强 judge |
| **Armin Ronacher** | [Pi: The Minimal Agent Within OpenClaw](https://lucumr.pocoo.org/2026/1/31/pi/)（01-31） | 从大工具面/大 prompt 收缩到 Read/Write/Edit/Bash 小核心；状态、extensions、session tree 在 context 外按需加载 | 保持 worker core 小，工具与 skills progressive disclosure；review 用 fork/session，不把全部历史重放进 prompt |
| **Mitchell Hashimoto** | [My AI Adoption Journey](https://mitchellh.com/writing/my-ai-adoption-journey)（02-05） | 从同步盯 agent 转向高成功率任务后台化、关通知；每次失误工程化成以后不再发生的 harness check | Clade 的 corrections→rule/test/hook 是正确方向；人不应被 agent 中间状态反向打断 |
| **Andrej Karpathy** | [No Priors 访谈](https://www.nopriors.com/p/andrej-karpathy-on-code-agents-autoresearch)（03-20） | 人的工作继续上移到定义搜索空间、评测和选择 loop；公开的“80% agent”比例只有转引，不能当精确 telemetry | 不追逐使用比例；保存每轮可比较 eval 与人类 touch-up，测 verified outcome |
| **Kazuhiro Sera (`seratch`)** | [openai-agents-python#3993](https://github.com/openai/openai-agents-python/pull/3993)，merge `a6cb92244211`：日志路径脱敏；[openai-agents-js#1535](https://github.com/openai/openai-agents-js/pull/1535)，merge `58e3a4396ea6`：导出 lifecycle/tool helper types（均 07-28） | 从 examples/编排使用者走到双语言 SDK 的稳定 lifecycle API 与默认日志安全 | 对外 adapter 要有稳定、类型化 lifecycle；所有 runtime event 在落盘前统一脱敏 |
| **Grant Birkinbine (`GrantBirki`)** | [codex-security#15](https://github.com/openai/codex-security/pull/15)，merge `e0dfd8881068`：pin customer container images 并恢复 SDK CI（07-28） | IssueOps/审计习惯延伸到供应链和“安全修复必须恢复验证链” | Clade 已 pin GitHub Actions 到完整 SHA；后续容器也应 pin digest，安全变更不得绕过 SDK/CI |
| **Harry Bagdi (`hbagdi`)** | [cilium#47571](https://github.com/cilium/cilium/pull/47571)，当前 head `27d7b40a8c65`：update race 后继续 identity GC（07-28，open） | 最新公开信号是分布式 reconciliation 的竞态恢复，不是 agent 框架新抽象 | 重试/cleanup 必须幂等；进程恢复不能只改 DB 状态而忽略仍存活的副作用 |
| **Dalton Hubble (`dghubble`)** | [afterburn#1280](https://github.com/coreos/afterburn/pull/1280)，merge `6bcfb38cc123`：Oracle Cloud nested metadata（07-24） | 持续强调 provider 输入弱结构化、fixture 与兼容处理 | provider adapter 不假设扁平 schema；用 recorded fixtures 验证兼容范围 |
| **Peter Bakkum (`bakks`)** | 2026-05 后未发现可靠公开 commit/event | 不能证明旧的交互安全 DX 有新转向 | 无新增动作 |
| **Yiheng Xu (`yxu-oai`)** | 2026-05 后未发现可归属工程 commit；最近相关公开研究仍是 [OpenCUA](https://arxiv.org/abs/2508.09123) | 研究作者身份不能替代近期工程证据 | 保留 GUI action trace/replay 旧结论，不新增推断 |
| **Vincent Tsao** | 2026-05 后未找到可靠个人 commit；只能确认长期 Bazel/依赖生态维护背景 | 无足够信号 | 无新增动作 |
| **Anton Tananaev** | [Traccar 6.13.3](https://github.com/traccar/traccar/releases/tag/v6.13.3)（05-06）及真实部署 issue 维护 | 是稳定 release/实机复现范例，不应继续误列为 OpenAI agent 人物 | 学 release discipline，不推导 agent 机制 |
| **Chao Sun** | OpenAI 官方 [Inside our in-house data agent](https://openai.com/index/inside-our-in-house-data-agent/)（01-29）；其 OpenAI/DataFusion 身份可确认，但文章并非他署名 | 数据 agent 从静态 metadata/RAG 转向每日 usage+人工注释+代码 enrichment；运行时按需检索、golden SQL 持续 eval、权限透传、减少工具 | repo 语义索引必须持续刷新；行为锚点做 canary eval；外部操作沿用调用者权限。机制可信度高，个人归因仅中等 |

### 活跃项目近期 commits：哪些是方向，哪些只是噪声

| 项目 | 近期证据 | 当前应学习的稳定机制 | 不应复制的表面 |
|---|---|---|---|
| **OpenAI Codex** | [app-server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) 与 0.130.0 release：versioned JSON-RPC、Thread/Turn、远程控制、分页、live config refresh | 把 core 暴露成有 schema、事件、审批、backpressure 的协议；clients 可替换 | 当前 TUI、slash names、默认模型 |
| **Claude Code** | [CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)：plugin/agent SDK、worktree baseRef、effort hook、hook feedback；legacy SDK entrypoint 已移除 | lifecycle hooks、worktree isolation、structured hook feedback、权限边界 | 旧 SDK 调用入口和特定 feature flag |
| **LangGraph** | [`413414573423`](https://github.com/langchain-ai/langgraph/commit/41341457342327166d72fc11952ab28fb61ec0bf)，1.2.10（07-28） | node checkpoint、thread id、interrupt/resume；node 重跑要求副作用幂等 | 图 DSL 本身 |
| **CrewAI** | [`f15844b21966`](https://github.com/crewAIInc/crewAI/commit/f15844b21966e35dff2f656ce8724b985703043c)（07-28）：skills progressive disclosure | 按需加载 skill/tool 指令 | “角色/crew”命名即架构 |
| **OpenHands** | [`2965aca5cac6`](https://github.com/OpenHands/OpenHands/commit/2965aca5cac67aeebb36ef7d05b64fc1c695fc16)（07-28）；组织拆出 SDK/CLI/extensions | 可替换 runtime、轨迹与 eval；UI 只是 client | 单体 web/container 产品形态 |
| **Qodo / PR-Agent** | [`b249e568e0c0`](https://github.com/The-PR-Agent/pr-agent/commit/b249e568e0c0fb6c674ace55fe95d02f62f8f3b3)（07-26）；向 shareable playbooks/commands 扩展 | repo-owned、可审查的 review playbook + CI gate | 单个 PR bot 命令集合 |
| **OpenCode** | [`a45c2b917e65`](https://github.com/anomalyco/opencode/commit/a45c2b917e657e50881117e8c3f85f4bff06e47d)，v1.18.9（07-28） | client/server、provider-agnostic core、general subagent/LSP | TUI 布局 |
| **Goose / ACP** | [`5b547350e2f9`](https://github.com/aaif-goose/goose/commit/5b547350e2f9e44b3d73aca0a6422b60ea302440)（07-28）及 ACP 迁移 | agent-client protocol 与内部 orchestration 分层；MCP 管工具、ACP 管会话/控制 | 当前 extension catalog |
| **Vercel AI SDK** | [`6a5bdffacd2a`](https://github.com/vercel/ai/commit/6a5bdffacd2a33697e93f08d1a787484d85afea2)（07-28） | typed provider/stream/tool contract | 绑定其 Gateway |
| **Warp / Oz** | [OSS/Oz announcement](https://github.com/warpdotdev/warp/discussions/9240)（04-28） | issue→spec→implementation→review→ship 与可观察 session | cloud terminal UI |
| **Factory** | [Factory OSS](https://github.com/Factory-AI/factory)：CLI/SDK/IDE/Action 多 surface | 一个 core 覆盖 CLI/IDE/CI，Action 做 PR gate | Droid branding/marketplace |
| **Aider** | 2026 主要是模型兼容维护；最新稳定 release 仍停在 2025 | repomap、read-only context、deterministic cache 仍稳定 | 大量 chat/slash mode |

以下项目在公开证据中**没有 2026 核心架构更新**，应从“活跃竞品”降为“稳定研究
参照”：Agentless、原 AutoCodeRover、Sonar Foundation Agent、Moatless、Sweep、
Reflexion。它们仍分别贡献 localization→repair、AST navigation、stateful search、
issue→PR 和 structured failure memory，但不能拿旧 benchmark scaffold 假装前沿
harness。Reflexion 尤其应只保留“结构化失败反馈”，不要学无限 self-reflection。

### 对照 Clade：已经吸收、已规划、真正的新缺口

**已经吸收（不要重复造）：**

- one-task focus、fresh/isolated context、worktree writer isolation；
- pre-push tests + two-pass oracle、repro-test gate、oracle eval fixtures；
- append-only worker event stream、crash replay、completion summary；
- corrections→rules/hooks/tests、Nth-strike escalation；
- GitHub Actions 完整 SHA pin、staged-secret scan；
- task provider/model/effort routing 和 execution envelope 的第一步。

**已经在 2026-07-27 architecture contract 中规划（本轮只是再次验证优先级）：**

- runtime/provider/protocol/model 分离；
- immutable execution envelope、capability negotiation、native adapters；
- status/usage/delivery 的统一语义与版本化协议；
- Codex structured events/thread resume、ACP/app-server 类控制面。

**本轮确认的 3 个真实缺口：**

1. **没有 lifecycle-linked `EvidenceBundle`。** 当前 test evidence 会进入 oracle，
   frontend task prompt 会要求 screenshot，delivery 也能登记 git artifact，但数据库里
   没有一个 schema 把 task/attempt、resolved envelope、base/head SHA、tests、截图或
   demo、cost、oracle verdict、human verdict、rollback 串起来。Hamel/Simon/Addy 的
   新共识说明这不是报告美化，而是 outer-loop 的基本交付对象。
2. **eval corpus 仍主要靠人工维护。** `orchestrator/evals/` 能重放 oracle fixtures，
   但 incident、oracle false-approve/reject、人工 revert/correction 没有自动生成
   sanitized regression candidate。现有 corrections learning 是 prompt/hook 学习，
   不等于持续校准 verifier。
3. **runtime event 落盘前没有统一脱敏。** `EventStream.emit()` 直接把任意 content
   写进 per-worker/global JSONL；现有 `redact.py` 保护 staged diff/commit path，
   没覆盖 event/log boundary。seratch 当天的 SDK commit 说明即使不是 credential，
   运行路径与 provider 内部细节也应按策略脱敏。

### Gaps vs current VISION

- North Star 只写 `oracle-approved completions / hour`，缺少 evidence completeness、
  false-approval rate、incident-regression coverage 与 human override rate。
- VISION 把 Verify 描述成“测试真实行为”，但没有定义跨 CLI/backend/UI 通用的
  verification artifact contract。
- event stream 已可重放，却还不是一个可安全导出/分享的 trace；未脱敏就无法成为
  eval、support bundle 或跨团队审计材料。

### Recommended additions to TODO.md（superseded by reconciled backlog）

- [x] 定义版本化 `EvidenceBundle v1`：task/attempt/envelope/base+head SHA/tests/
  screenshots-or-video/cost/oracle+human verdict/rollback，绑定 delivery state 而非
  只写 PR prose。
- [x] 建立 `failure → sanitized eval candidate` 管道：incident、oracle disagreement、
  revert、explicit correction 进入 quarantine；人工确认后进入 oracle/resolve corpus，
  后续 prompt/harness 变更必须重放。
- [x] 在 `EventStream.emit()` 与 provider stdout/stderr 持久化边界统一执行结构化
  redaction；保留 redaction metadata，不把原 secret/path 复制到日志。
- [x] 更新 North Star dashboard：除 throughput/cost 外展示 evidence completeness、
  false approval、human override、regression coverage。

**不建议现在做：** 增加更多常驻 agent 角色、复制 Crew/Factory 的品牌化 topology、
继续扩充 slash commands、为低活跃 research scaffold 做兼容层。近期一手证据共同
指向“更少的核心、更多的证据与可恢复性”，不是更大的 agent org chart。

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

### Recommended additions to TODO.md（superseded by reconciled backlog）

- [x] 建立 30–50 个真实历史任务的 routing eval：固定输入/commit/CI oracle，三臂对照
  `cheap×N parallel`、`strong high-effort×1`、`cheap→strong cascade`，至少重复 3 次估计方差
- [x] 记录 `attempt_index`、`parent_attempt`、`effort`、`queue_ms`、`inference_ms`、
  `verify_ms`、`final_oracle`，按任务类型输出 pass@1、pass@k、success/$、success/wall-hour
- [x] 把 router 改成 verifier-aware cascade：低风险可验证任务先便宜模型；首轮失败或
  高风险/无自动 verifier 直接强模型；设置最多一次 cheap retry，避免无界串行反思
  - 2026-07-28 实现说明：策略仍默认关闭。只有显式声明 deterministic `test_cmd`、
    有界 `own_files`、非 critical、高 readiness 且允许的低风险 task class 才进入
    cheap-first；失败只生成一个保留原执行契约的 strong child，strong 再失败即结束
    cascade。当前 replay starter corpus 是 constructed evidence，因此不能冒充生产收益。
- [x] 用历史 telemetry 拟合每类任务的 empirical break-even，而不是在 prompt 中硬编码
  `4×`；数据不足时明确显示样本数与置信区间
  - 2026-07-28 实现说明：`routing_break_even.py` 只读取最新 immutable production
    EvidenceBundle；constructed/eval、缺成本/phase、unreviewed 均单独计入 exclusions。
    其 `independent_attempts` 是观测性投影，不是因果结论；无 matched counterfactual
    时 recommendation 永远为 null，router 也不会被修改。

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

### Recommended additions to TODO.md (superseded by reconciled backlog)
- [x] Positioning review: which orchestrator features are now harness table-stakes (parallel fan-out, cron) vs Clade moat (oracle, corrections, usage, sync) — update VISION.md accordingly
- [x] Watch beads' agent-filed note-to-self mechanic; if loop-runner workers start losing cross-iteration context, that's the trigger to adopt
- [x] Consider running INJ screening at /equip **sync** time too (audit gates adoption, but a later upstream update could introduce injection between audit and sync)

Sources: [ghuntley.com/loop](https://ghuntley.com/loop/) (cue→404), [yegge.ai/gastown](https://yegge.ai/gastown), [Gas Town HN thread](https://news.ycombinator.com/item?id=46734302), [Parsons — orchestrator too clever](https://www.chrismdp.com/your-agent-orchestrator-is-too-clever/), [Mason — coherence through orchestration](https://mikemason.ca/writing/ai-coding-agents-jan-2026/), [InfoQ — Dynamic Workflows](https://www.infoq.com/news/2026/06/dynamic-workflows-claude-code/), [Anthropic — introducing dynamic workflows](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code), [Agentman — skills ecosystem 2026](https://agentman.ai/blog/agent-skills-ecosystem-report-2026), [Register — Ralph Wiggum loops](https://www.theregister.com/2026/01/27/ralph_wiggum_claude_loops/), [Medium — every harness is a Ralph loop](https://medium.com/ai-all-in/every-ai-coding-harness-is-just-a-ralph-loop-69690dc69e7c)

---

## [Research] 2026-07-06 — Round 4: deep-mining the 17 newly-tracked experts

89 agents, 5.8M tok, 1387 tool calls. Mined 3-6 mechanisms per person (83 raw) → triage-dedup → 70 distinct candidates → adversarial verify (4-check framework: deficient-not-different / capabilities-not-names / single-tool-local-first scope / mechanism equivalence). Result: **25 confirmed_gap (36%), 15 parity, 28 different-not-deficient, 2 N/A.** Confirmed-gap rate meaningfully higher than prior rounds — verification surfaced 3 genuine LIVE BUGS in Clade's own shipped code (not "adopt an external pattern"), found only because checking each candidate against the real code forced a close read of adjacent logic.

**3 confirmed live bugs — RESOLVED 2026-07-28:**
- [x] Plan-drift: `oracle_result`/`oracle_reason` computed in `worker.py` but never persisted to the DB; `session.py:_run_plan_build` marks a checklist item `[x]` the instant status hits ANY terminal value — before the test/oracle gate resolves. A rejected/reverted commit still shows checked off. (resolved by `69c25a7`)
- [x] Dead code: `context_budget_warning` writes `context-warning-<id>.md`; zero readers exist (confirmed via grep) since it was introduced. (resolved by `a29363f`)
- [x] Orphan-process safety hole: workers `setsid` (survive orchestrator restart); `_recover_orphaned_tasks()` only relabels DB rows without checking/killing the still-alive process; `retry_task` can silently collide into a shared worktree. (resolved by `4e63b7e`)

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

### Noted, not landed — RESOLVED 2026-07-28 (all six landed in `d3c7c90`)

- [x] Mutation testing as run-over-run missed-count diff ratchet, narrow high-signal targets first (lovesegfault mutants.toml) [M/medium — patrol-lane experiment]
- [x] Judge hardening: pure judges could add `--disallowed-tools` belt-and-braces (cookbooks: allowed gates prompting, disallowed gates availability) [S/low]
- [x] Standing friction-log instruction for workers (append harness pain to BRAINSTORM [AI]) [S/low]
- [x] `input_examples` on mcp_server tool definitions (advanced-tool-use blog: 72%→90% complex-param accuracy) [S/low]
- [x] Strike-ladder N=4..7 structural-close templates as /audit reference doc (delete-reimplementation, make-function-total, single-emit-chokepoint) [S/low prose]
- [x] Flake-verdict policy doc for test-loop-real (felixrieseberg: "one SUCCESS = good, three identical failures = content must change") [S/low]

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

### Recommended additions to TODO.md — RESOLVED 2026-07-28

*(BRAINSTORM is an inbox — these are recommendations for human promotion, grouped by cluster, ordered by impact.)*

- [x] **Oracle integrity package** (the highest-leverage cluster — all four touch `worker_review.py`/`worker.py` and should land as one phase): (a) criteria-injection + evidence-forcing rubric [S/high]; (b) fail-open → 'unreviewed' + infra-error counter + canary [S/high]; (c) tests run BEFORE oracle/push, evidence threaded into prompts; /review-pr executes the change [M/high]; (d) severity:error gate on the chunked path, optional findings → follow-ups [S/medium]
- [x] **CI hardening commit**: install-test job (clean-HOME install.sh + assertions) + flip shell-tests continue-on-error to false + optional alls-green-style gate job [S/medium]
- [x] **test_conventions.py**: 1500-line cap, import-DAG acyclicity, no exception text in 500s — runs in CI pytest AND workers' local test command [S/medium]
- [x] **checks.sh in committer**: staged-secret scan fail-closed + shellcheck, same script reused as a CI step [S/medium]
- [x] **CI-failure task hydration**: log tails in scan-ci-failures.sh/ci_watcher.py, actions-run URLs in worker_hydrate.py, anti-infra/anti-downgrade guardrails [S/medium]
- [x] **/trim-tests skill + scan-health suite-runtime probe** (>100s verify_cmd → trim suggestion task) [S/medium]
- [x] **/audit ESCALATE-TO-STRUCTURAL** + /generate-hook Step 6 rule retirement [S/medium]
- [x] **quiet-run.sh** verify wrapper wired into /verify, /review, loop-runner worker block [S/medium]
- [x] **gh pr merge --auto + do-not-merge label** in routes/tasks.py merge_all_done [S/medium]
- [x] **ensure_repo_invariants()** preflight in github_sync.py, called at session init + start.sh health check [S/medium]
- [x] **validate-skills.py**: one frontmatter schema + shared parser for install.sh and mcp_server [S/medium]
- [x] **Dependency-bug doctrine** in /investigate Phase 6b + Engineering Values bullet [S/medium]
- [x] **History payload**: fix-task test-presence oracle criterion + structured PR bodies (replace --fill) + commit-body rule in /commit + loop-runner + worker_taskfile [S/medium]
- [x] **Path-scoped rule-injector hook** (.claude/rules/*.md with paths: frontmatter) [M/medium]
- [x] **Worktree env bootstrap + per-file post-edit lint** in run-tasks-parallel.sh / post-tool-use-lint.sh [M/medium]
- [x] Low-priority lane: committer attribution trailers [S/low]; MCP compact mode [S/low]; second-opinion-{codex,gemini} agents [S/low]
- [x] **Design discussions (bigger bets)**: prompt eval harness (orchestrator/evals/ — gates the oracle rewrite); offline recovery e2e with planted failures; mid-flight worker steering via PostToolUse mailbox drain

---

## [Research] 2026-07-27 — Branch-to-merge delivery lifecycle and merge strategy

Trigger: the statusline fix exposed a gap between Clade's individual skills.
The task started on a branch stacked over an unmerged PR; code and tests were
completed but the first handoff stopped with an uncommitted working tree. After
the commit, the parent branch was amended, so the child branch and its remote
base diverged. Recovering required merging the parent PR, rebasing the single
statusline commit onto the new `main`, force-pushing with lease, rerunning the
candidate branch's complete CI, opening an atomic PR, and deleting stale refs.

### Practices surveyed

| Source | Operating model | What Clade should borrow |
|---|---|---|
| [Google Engineering Practices — Small CLs](https://google.github.io/eng-practices/review/developer/small-cls.html) | One self-contained change per CL; related tests stay in the same CL; dependent changes may be stacked; every submitted layer must keep the build working | Plan the branch/PR slices before editing, attach tests to each behavior slice, and keep every preserved commit/PR green |
| [Google — CL descriptions](https://google.github.io/eng-practices/review/developer/cl-descriptions.html) | The permanent record must explain both what changed and why; review the description again before submit | Keep mechanism, root cause, constraints, evidence, and rollback in the commit/PR record |
| [Trunk Based Development — short-lived branches](https://trunkbaseddevelopment.com/short-lived-feature-branches/) | Task branches start from trunk, live roughly a couple of days, are brought up to date before landing, then are deleted | Branch at task start, record the base, sync before ready-for-review, and make post-merge cleanup part of Done |
| [GitHub — PR merge methods](https://docs.github.com/en/pull-requests/reference/pull-request-merges) | Merge commit preserves commits and an explicit boundary; squash collapses fixups into one logical change; rebase keeps clear commits in linear history | Select a merge method from commit quality and ancestry needs; never hard-code squash globally |
| [GitLab — merge methods](https://docs.gitlab.com/user/project/merge_requests/methods/) | Merge, semi-linear merge, fast-forward, and squash are separate policy choices; semi-linear requires an up-to-date branch before merge | Separate the "branch is current and tested" gate from the repository's history-shape policy |
| [Gerrit — changes and submit strategies](https://gerrit-review.googlesource.com/Documentation/concept-changes.html) | Review iterations are patch sets of one change; only the latest patch set lands; dependent changes are explicit relation chains | Model a delivery unit independently from its WIP revisions and make stack parentage first-class metadata |
| [Graphite — stack merge](https://graphite.com/docs/merge-pull-requests) and [sync/restack](https://graphite.com/docs/sync-with-a-remote-repo) | Merge stacks bottom-up; after each lower PR lands, sync trunk, delete the merged branch, restack upper branches, and rerun affected checks | A stacked-PR feature is incomplete without an automatic post-merge restack/retarget operation |

### What the strong workflows agree on

1. **Start with the delivery boundary, not with edits.** Resolve trunk or the
   explicit parent PR, create a short-lived branch/worktree, and record the
   intended base before changing files.
2. **Commit at coherent green checkpoints.** "Commit small and often" does not
   mean arbitrary time slices. A preserved commit should express one useful
   step, include its related tests, and pass the relevant fast gate. A failing
   TDD test can exist transiently, but should not survive as a mainline commit
   unless the PR will squash it away.
3. **Open review early enough to expose drift.** After the first coherent green
   checkpoint, push and open a draft PR (or an explicit stack relation). Mark
   it ready only after the full exact-head CI and scope gate pass.
4. **Test at two cadences.** Run focused tests after each code slice and before
   each checkpoint commit; run the complete project CI on the exact candidate
   branch after final base alignment and before ready/merge. Requiring the full
   suite before every small commit makes "commit often" economically
   contradictory.
5. **A stack is a live dependency graph.** Merge bottom-up. When a parent lands,
   every open child must be restacked/retargeted, force-pushed with lease, and
   retested. A final aggregate branch's green result is not evidence for its
   reconstructed layers.
6. **Done includes repository hygiene.** After merge: update local trunk with
   `--ff-only`, delete local and remote topic branches, prune remote-tracking
   refs, restack surviving children, and verify the worktree is clean.

### Merge strategy decision matrix

| Situation | Preferred method | Reason |
|---|---|---|
| One atomic PR; commits are WIP/fixups or not independently green | **Squash merge** | Produces one truthful historical unit and removes misleading intermediate states |
| One atomic PR; every commit is meaningful, ordered, independently green; linear history desired | **Rebase merge** | Preserves useful commit granularity without merge bubbles |
| Exact commit identity/topology matters, or a manually managed stack relies on shared ancestry | **Merge commit** | Preserves branch boundary and ancestor SHAs; avoids the parent-SHA replacement that forces children to restack |
| Stack managed by tooling that automatically syncs/restacks children | Repository default, often squash or rebase | Rewritten ancestry is acceptable only because the tool repairs every upper branch and reruns CI |
| Long-running/shared feature branch | Avoid; split into short-lived PRs first | All three merge methods become harder to review, align, roll back, and clean up |

**Decision for Clade PR #24:** squash was appropriate because the PR contained
one already-curated commit and represented one historical bug-fix unit. No
meaningful intermediate commit was lost. This does **not** validate the current
`merge-pr` rule that unconditionally squashes every PR.

**Recommended Clade default:** `merge-pr --strategy auto`.

- Respect a repository-configured explicit strategy first.
- Single commit or fixup-heavy atomic PR → squash.
- Multiple meaningful, green commits → rebase merge when linear history is
  desired; merge commit when preserving a branch boundary is the repo norm.
- Open stacked children + no reliable restack automation → prefer merge commit,
  or stop and require the user to choose. Never silently squash a stack parent.
- Record the selected strategy and reason in the merge report.

### Confirmed Clade gaps

1. **No delivery transaction at task entry.** `worktree` can create isolation,
   `commit` can commit, `create-pr` can scope-check, and `merge-pr` can merge,
   but nothing owns the complete state machine. An investigation can implement
   a fix and still report Done before commit/PR.
2. **Branch intent is not an invariant.** An explicit "open a new branch" was
   treated as workspace organization rather than authorization and obligation
   to deliver commits on that branch.
3. **Commit cadence conflicts with its CI gate.** `commit` says "small and
   often" but requires every discovered CI command before every commit. That
   encourages one late mega-checkpoint instead of focused green checkpoints.
4. **PRs are opened too late.** `create-pr` only describes a final passing PR;
   it lacks an early draft mode triggered automatically after the first green
   checkpoint, so parent/base drift stays invisible until delivery.
5. **Stack creation exists; stack maintenance does not.** `create-pr` recommends
   stacks, while `merge-pr` squash-merges the parent and never restacks,
   retargets, force-pushes-with-lease, or retests children. These policies are
   internally inconsistent.
6. **Merge strategy is hard-coded.** `merge-pr` always uses `--squash`, without
   inspecting whether commits are meaningful or whether child PRs depend on
   their SHAs.
7. **The documented CLI command is not portable.** The installed `gh` rejected
   `gh pr merge --yes`; supported non-interactive flags plus
   `--match-head-commit` are safer and protect against a head changing after
   review.
8. **Cleanup is partial.** Local branch deletion and `main` pull are mentioned,
   but remote deletion verification, `fetch --prune`, clean-worktree proof, and
   upstack repair are not one atomic post-merge step.
9. **Per-PR evidence is present but not lifecycle-linked.** The new scope gate
   correctly requires exact-branch CI, yet no parent workflow automatically
   invokes commit → align → verify → create PR → wait checks → merge → cleanup.

### Proposed delivery state machine

```text
START
  fetch/prune → resolve trunk or stack parent → require clean tree
  → create short-lived branch/worktree → record base SHA + delivery scope

BUILD
  write/adjust regression test → implement one behavior slice
  → focused test/lint → commit coherent green checkpoint → push
  → create/update draft PR and stack metadata

READY
  sync/restack onto exact base → scope gate
  → full CI on reconstructed head → push with lease if rewritten
  → mark PR ready → wait for remote required checks

MERGE
  inspect commit quality + child ancestry + repository policy
  → choose squash | rebase | merge commit with recorded reason
  → lock reviewed head SHA → merge bottom-up

CLEAN
  checkout trunk → pull --ff-only → delete local/remote merged branch
  → fetch --prune → restack/retarget/retest children
  → prove clean tree + local/remote alignment → DONE
```

### Recommended additions to TODO.md — RESOLVED/SUPERSEDED 2026-07-28

- [x] Add a `delivery` skill/state machine that starts a clean task
  branch/worktree before edits and owns the lifecycle through merged PR and
  cleanup; changing code on a created task branch cannot end at "uncommitted".
- [x] Split verification into `checkpoint` (focused affected tests before each
  commit) and `candidate` (full CI after final base alignment); require each
  preserved commit to be green.
- [x] Add automatic early draft-PR creation/update after the first pushed green
  checkpoint, including base SHA, stack parent, scope, and evidence fields.
  **REJECTED 2026-07-28:** explicit delivery authority may authorize a draft;
  unconditional automatic publication is intentionally not implemented.
- [x] Add `restack` to stacked delivery: after a parent merges, sync trunk,
  rebuild/retarget every child, push with lease, and rerun that child's CI.
- [x] Replace unconditional squash with `merge-pr --strategy
  auto|squash|rebase|merge`; detect child PRs and repository policy, lock the
  reviewed head SHA, and explain the choice.
- [x] Make post-merge cleanup a verified gate: local/remote branch absent,
  remote refs pruned, main equals origin/main, no dirty files, children
  restacked.
- [x] Add an end-to-end regression fixture for the exact failure reproduced
  here: child branch from open PR → parent amended/squash-merged → child
  restacked → own CI → own PR → merge → branch cleanup.

---

## [Research] 2026-07-27 — Git delivery governance deep dive

This is a governance addendum to the lifecycle study above. The first study
identified the missing delivery transaction. This pass separates the four
layers that must agree for the transaction to be reliable:

1. contributor instructions;
2. local CLI/skill behavior;
3. GitHub repository enforcement;
4. the permanent history retained on `main`.

Good intentions in one layer do not compensate for missing enforcement in
another.

### Additional operating models surveyed

| Source | Relevant operating rule | Clade implication |
|---|---|---|
| [Git's own `gitworkflows`](https://git-scm.com/docs/gitworkflows) | Develop independent work on topic branches; use explicitly disposable integration branches to test interactions, and never base durable work on those branches | Distinguish deliverable topic/stack branches from throw-away aggregate test branches; never mistake aggregate CI for per-PR evidence |
| [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) | Reviews, required checks, conversation resolution, signed commits, linear history, and merge queues are repository-enforced choices | The delivery skill should inspect repository rules, but critical invariants must also be enabled server-side |
| [GitHub merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue) | Test a temporary merge-group SHA containing current trunk and earlier queued PRs, not merely the author's old head SHA | Exact-head PR CI is necessary but not sufficient in a busy repository; final integration state also needs validation |
| [GitLab squash guidance](https://docs.gitlab.com/user/project/merge_requests/squash_and_merge/) | Squash turns small work commits into one meaningful integration unit, but is a poor fit for a branch that continues after merge because its ancestry diverges | Squash is a mainline-history policy, not an instruction to avoid checkpoint commits; never keep developing on a squashed source branch without restacking |
| [Graphite restack](https://graphite.com/docs/restack-branches) and [manual stack merge](https://graphite.com/docs/merge-stack-prs-github) | Track explicit parent relationships, merge bottom-up, sync trunk, restack descendants, resubmit, and repeat | Stacking cannot be declared supported until Clade owns descendant discovery and repair |
| [GitHub rebase safety](https://docs.github.com/en/get-started/using-git/about-git-rebase) | Rebasing rewrites history and is unsafe when other people consume the pushed branch | Force-with-lease may be automated only for an owned task/stack branch with a verified remote head; never for trunk or an unverified shared branch |

### Clade configuration snapshot

Read-only inspection on 2026-07-27 found:

- default branch: `main`;
- merge commit, squash merge, and rebase merge: all enabled;
- automatic source-branch deletion after merge: disabled;
- `main` branch protection: absent;
- repository rulesets: none;
- CI runs for PRs targeting `main` and for pushes to `main`, but the repository
  does not currently require those checks before merge;
- recent PR history is predominantly squash-style one-parent commits, while
  older batch work also introduced merge commits and direct commits remain
  possible.

Therefore Clade currently has conventions, not enforced governance. An actor
can push directly to `main`, merge without required checks, choose any history
shape, or leave merged branches behind.

### The key distinction: working history versus integration history

The apparent conflict between "commit while you work" and "squash on merge"
disappears when the two histories are treated separately.

**Working history** protects ongoing work and makes review iterations
observable:

- commit after a coherent behavior or evidence checkpoint;
- push after a locally green checkpoint;
- keep review fixes visible while the PR is open;
- allow fixup commits when they honestly describe review activity;
- never leave completed work only in the working tree.

**Integration history** is the durable debugging and rollback interface:

- squash if the PR, rather than its intermediate commits, is the smallest
  truthful reversible unit;
- rebase-merge if every commit is independently useful, ordered, and green;
- merge-commit if preserving topology or exact ancestry is an explicit
  requirement.

The integration method is chosen at READY/MERGE time. It must not weaken the
BUILD-time obligation to commit and push checkpoints.

### Branch classes and allowed operations

| Branch class | Lifetime and base | Rewrite rule | Merge rule | Cleanup |
|---|---|---|---|---|
| `fix/*`, `feat/*`, `docs/*`, `research/*` | Short-lived; normally from current `origin/main` | Rebase/force-with-lease allowed only while singly owned and after verifying remote head | Strategy selected from commit quality; atomic PR required | Delete local and remote immediately after merge |
| Stack child | Short-lived; base is an explicit parent PR/branch | Restack with lease after any parent rewrite or merge | Merge bottom-up only; retest each reconstructed child | Delete each landed layer; repair all descendants |
| Shared collaboration branch | Explicitly declared shared; no implicit ownership | Do not rewrite after publication | Prefer merge commits or coordinated new commits | Delete only after all consumers confirm |
| Throw-away integration branch | Re-creatable aggregate from known topic heads | Freely rebuild; nobody may base durable work on it | Never merge as a product change | Always delete after interaction testing |
| Release/hotfix branch | Created only for a declared supported release policy | Policy-specific; never inferred by an agent | Backports are separately reviewed and traceable | Retain only for the documented support window |

Clade should not introduce a long-lived `develop` branch. Its present delivery
model fits a protected trunk plus short-lived topic branches.

### Lifecycle invariants

#### START

- Fetch and prune before selecting a base.
- Refuse to create a task branch from an accidental topic branch unless an
  explicit stack parent is recorded.
- Refuse to start with unrelated dirty files; preserve them in their existing
  worktree or ask for disposition.
- Record: task identifier, branch, base ref, base SHA, optional stack parent,
  owner, and intended delivery unit.

#### BUILD

- A branch request is a delivery obligation, not merely namespace
  organization.
- After each coherent slice: run affected tests, commit named files through
  `committer`, and push.
- A red TDD commit may exist locally or in an explicitly squash-bound draft,
  but cannot be advertised as independently releasable.
- Open a draft PR after the first pushed green slice so base errors, scope
  growth, and stack relationships are visible early.

#### READY

- Re-resolve the PR base and compare it with the recorded base.
- If the base changed, sync/restack first; any resulting SHA invalidates old
  local and remote evidence.
- Run the full repository gate on the exact final head.
- Require a structured PR description: problem/root cause, scope, excluded
  scope, stack parent/children, test evidence, risk, rollback, and proposed
  merge strategy.
- Lock the reviewed head SHA when invoking merge.

#### MERGE

- Block on failed or pending required checks; a generic "user asked to merge"
  must not silently waive repository health.
- For stacks, merge only the lowest ready layer.
- Select and record the history strategy; do not infer "squash" solely from
  repository availability.
- On a busy repository, validate the combined result with a merge queue or
  equivalent serial integration gate.

#### CLEAN

- Update `main` with `--ff-only`.
- Verify the expected integration commit/PR reached `main`.
- Delete the local and remote topic branch and prune tracking refs.
- Discover open children of the merged branch; retarget/restack, push with
  lease, and invalidate/re-run their CI.
- Finish only after: clean worktree, no stale topic ref, and
  `main...origin/main == 0 0`.

### Recommended merge policy for Clade

**Repository default:** squash atomic, unstacked PRs. This matches Clade's
recent history and makes one PR one simple revert unit.

Exceptions must be explicit:

- **Rebase merge:** a deliberately curated commit series where every commit
  passes its required gate and each commit message explains a durable step.
- **Merge commit:** a shared branch or live manually managed stack whose
  ancestry must be preserved. This exception is incompatible with enforcing a
  globally linear history.
- **Stop instead of guessing:** a stack parent has open children but no safe
  restack path; commits mix multiple delivery units; the branch is shared but
  ownership is unknown; or repository rules conflict with the requested
  method.

Until descendant-restack automation exists, Clade must either:

1. use a merge commit for a parent with live children; or
2. squash/rebase the parent, then synchronously restack, retarget, push with
   lease, and retest every child before claiming completion.

The second path preserves the preferred linear mainline but requires the full
repair transaction.

### Repository enforcement recommendations

Immediate, low-complexity changes:

- protect `main` and require changes through pull requests;
- require the four deterministic CI jobs before merge;
- require conversations to be resolved;
- disallow force pushes and deletion of `main`;
- enable automatic deletion of merged source branches;
- keep squash as the default UI choice, while leaving rebase/merge available
  for documented exceptions until stack automation settles the policy;
- add CODEOWNERS/reviewer requirements only where a real responsible owner
  exists, rather than manufacturing ceremonial approval.

Do not enable "require linear history" yet if merge commits remain the safety
valve for live manual stacks. Enable it only after Clade can reliably restack
children or after the project forbids stacked branches.

GitHub's native merge queue is useful when change volume and repository
ownership make it available. For the current personal repository, Clade should
first implement an equivalent serialized final gate:

1. fetch current `origin/main`;
2. ensure PR base/head still match reviewed values;
3. verify required checks for the exact head;
4. use `--match-head-commit`;
5. merge one PR;
6. fetch/prune and repair descendants before selecting the next PR.

### Force-push policy

`--force-with-lease` is a concurrency control, not blanket permission.

Allow it only when all are true:

- target is a non-protected topic/stack branch;
- the delivery record names the current actor as owner;
- the remote SHA was fetched immediately before the rewrite;
- the lease uses that expected SHA;
- no unknown/shared consumer is based on the branch, or descendant branches
  are part of the same restack transaction;
- affected PR checks and approvals are intentionally invalidated and rerun.

Otherwise stop. Never use plain `--force`.

### Rollback policy

- The unit selected for mainline history must also be the unit operators can
  safely revert.
- A squashed PR reverts as one commit.
- A rebase-merged series may be reverted commit-by-commit only if dependency
  ordering remains valid; otherwise revert the series together.
- A merge commit reverts with its mainline parent selected and retains the
  branch boundary.
- Reverting a parent in a stack requires evaluating or reverting all landed
  descendants.
- A rollback is a new reviewed PR; do not rewrite published `main`.

### Proposed automation contract

One `delivery` controller should persist a small machine-readable record:

```yaml
branch: fix/example
base_ref: main
base_sha: <sha>
owner: <actor>
pr: 123
parent_pr: null
children: []
head_sha: <sha>
state: BUILD
verification:
  checkpoint: [<command/result>]
  candidate: [<command/result/head_sha>]
merge:
  strategy: squash
  reason: atomic PR; intermediate commits are review checkpoints
```

Transitions should be idempotent and resumable. Re-running CLEAN must safely
confirm already-deleted branches; re-running READY after a head change must
discard stale evidence; a crash after merge must resume cleanup rather than
open a duplicate PR.

### Suggested rollout

1. **Enforce the server boundary:** protect `main`, require current CI, and
   auto-delete merged branches.
2. **Repair existing commands:** remove unsupported `--yes`, add
   `--match-head-commit`, wait for checks, verify cleanup, and support explicit
   merge strategies.
3. **Unify lifecycle state:** introduce the resumable delivery record and make
   branch creation imply commit/push/PR obligations.
4. **Complete stack support:** discover descendants, merge bottom-up, and
   automate retarget/restack/retest.
5. **Add integration serialization:** use a native merge queue when available
   or a repository lock/queue that tests current trunk plus the candidate.
6. **Measure outcomes:** stale branch age, uncommitted task exits, PR cycle
   time, base-drift reruns, cleanup failures, and revert success—not raw commit
   count or lines changed.

---

## [Research] 2026-07-27 — Agent-native Git delivery across repositories

### Scope correction

The earlier Git governance studies treated Clade as the repository being
governed. That is too narrow. Clade ships `commit`, `create-pr`, `merge-pr`,
`review-pr`, and `worktree` workflows that run inside arbitrary repositories,
through Claude Code, Codex, and the MCP distribution. The product is therefore
a portable Git delivery control plane, not a copy of Clade's own preferred
workflow.

The design question is:

> Given an unknown repository, host, event, agent runtime, permission set,
> branch ownership model, and review policy, what Git actions are safe,
> authorized, recoverable, and useful?

Two requirements are non-negotiable:

1. **Adapt before acting.** Clade must resolve the target repository's trusted
   instructions, Git/forge policy, current event, branch ownership, and runtime
   capabilities before choosing a workflow. Claude Code and Codex receive the
   same policy decision, but their adapters may execute different transitions.
2. **Preserve useful work promptly.** Research, code, tests, and design decisions
   must not accumulate indefinitely as an uncommitted working tree. Once a
   coherent, reviewable slice exists, the agent creates a checkpoint commit in
   writable Git contexts. A detached/managed runtime must create a reachable
   commit or runtime snapshot; a genuinely non-committable context must export
   a patch/bundle and report why it could not commit.

The second rule is about recoverability, not publication. A checkpoint commit
does not imply permission to push, open a PR, merge, or delete a branch.

This pass prioritizes current agent implementations over generic Git advice.
Repository snapshots inspected on 2026-07-27:

- `anthropics/claude-code-action` at
  `be7b93b1907a4abad570368f3c74b6fe3807510b`;
- `anthropics/claude-code` at
  `7ef6eec9d9ba84ea6f233f26c45f1df5c5991843`;
- `openai/codex-action` at
  `dd78cb653811af44014baa08fe954e28d32c1bf9`;
- `openai/codex` at
  `bd2de422aa287b97b06ca6425a10935bcf1b3731`.

### What current agent systems actually do

#### Anthropic: Claude Code Action

Sources:

- [repository](https://github.com/anthropics/claude-code-action);
- [capabilities and limitations](https://github.com/anthropics/claude-code-action/blob/main/docs/capabilities-and-limitations.md);
- [security model](https://github.com/anthropics/claude-code-action/blob/main/docs/security.md);
- [`branch.ts`](https://github.com/anthropics/claude-code-action/blob/main/src/github/operations/branch.ts);
- [`branch-cleanup.ts`](https://github.com/anthropics/claude-code-action/blob/main/src/github/operations/branch-cleanup.ts);
- [`restore-config.ts`](https://github.com/anthropics/claude-code-action/blob/main/src/github/operations/restore-config.ts).

Its branch behavior is event-dependent, not one universal sequence:

- issue trigger → create a new branch from an API-resolved base/default branch;
- open PR trigger → fetch and update that PR's existing head branch;
- closed or merged PR trigger → create a new branch;
- cross-repository PR → fetch through the pull ref rather than assuming the
  head exists on `origin`;
- empty agent-created branch → delete it;
- dirty agent branch with no commit → make a recovery commit and push it rather
  than losing completed work.

Its default authority boundary is deliberately narrower than its technical
ability:

- only write-capable actors may trigger it by default;
- bot allowlists are explicit;
- it may create branches and push commits;
- it does not approve PRs;
- it does not merge, rebase, or perform general branch operations;
- by default it gives the user a prefilled PR-creation link rather than opening
  the PR automatically, preserving a human publication decision;
- optional GitHub API commit signing trades away complex Git operations, while
  SSH signing retains normal Git behavior.

The most important modern behavior is its untrusted-PR boundary. Before running
Claude against a PR head, it restores executable/configuration inputs such as
`.claude/`, `CLAUDE.md`, `.mcp.json`, `.gitmodules`, hooks, and ripgrep config
from the trusted base branch. It preserves the PR-authored versions only for
inspection. A PR may propose changes to agent instructions; it may not redefine
the reviewer that is evaluating it.

#### Anthropic: autonomy, containment, and long-running work

Sources:

- [Claude Code auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode);
- [How we contain Claude](https://www.anthropic.com/engineering/how-we-contain-claude);
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents);
- [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps);
- [Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents);
- [parallel Claude compiler experiment](https://www.anthropic.com/engineering/building-c-compiler);
- [Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills).

The current lessons differ materially from older "ask before every shell
command" workflows:

1. User intent defines authorization. Auto mode permits normal pushes to the
   session's working branch, while treating direct pushes to main,
   force-overwriting history, remote branch deletion, bypassing review, and
   edits to permission configuration as separate high-risk actions.
2. Hard containment beats repeated prompts. Approval fatigue makes per-command
   confirmation weak; the filesystem, network, credential, repository, and
   branch boundaries should constrain what the agent can do.
3. Credentials stay outside the agent sandbox. Managed Agents proxy Git and MCP
   access so `pull`/`push` work without making raw tokens readable to generated
   code.
4. Git is durable agent memory. Long-running agents begin by reading history
   and structured progress, implement one tractable slice, verify it, and end
   with a commit plus progress update. A session that ends with undocumented
   dirty work harms the next agent.
5. Harness assumptions expire. Managed Agents explicitly separates stable
   interfaces—append-only session, replaceable harness, isolated sandbox—from
   model-specific prompting tricks that may become dead weight.
6. Parallel agents need ownership and integration control. Anthropic's compiler
   experiment gave every agent a fresh clone, used Git-visible task locks,
   forced synchronization before push, and strengthened CI so one agent could
   not silently break the shared result. It also reports frequent conflicts,
   so its shared-upstream prototype is evidence for isolation, not a template
   to copy literally.
7. Skills should package deterministic scripts and references, not grow into
   one enormous prose prompt. Agent Skills are now a cross-platform format;
   provider-neutral behavior belongs in the canonical skill itself.

#### Codex: current product and action model

Sources:

- current Codex manual, fetched 2026-07-27;
- [Codex Action](https://github.com/openai/codex-action);
- [Codex Action security](https://github.com/openai/codex-action/blob/main/docs/security.md);
- [Codex worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees);
- [Codex skills](https://learn.chatgpt.com/docs/build-skills);
- [AGENTS.md guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Current Codex behavior further invalidates a fixed Claude-oriented flow:

- Codex-managed worktrees normally start at detached HEAD, create branches only
  when the user chooses to preserve/publish the work, snapshot work before
  automatic worktree deletion, and support handoff between background and local
  environments.
- A branch can be checked out in only one worktree. A portable skill must
  inspect worktree ownership instead of assuming it can checkout/delete any
  local branch.
- `AGENTS.md` carries repository guidance; skills carry reusable workflows;
  hooks or CI enforce mechanical rules. These are complementary layers, not
  interchangeable prompt text.
- `openai/codex-action` defaults to write-access actors, least-privilege
  permission profiles, no persisted checkout credentials, and review of the
  PR's synthetic merge commit. It treats PR bodies, commit messages,
  screenshots, and repository instruction files as untrusted prompt-injection
  surfaces.
- The action recommends running the agent as the last step in a job or passing
  sanitized output to a fresh job, because the agent may mutate processes,
  hooks, or action code even when the final diff looks harmless.

#### Other current agent products

| Product | Current delivery behavior | Lesson for Clade |
|---|---|---|
| [GitHub Copilot cloud agent](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/kick-off-a-task) | Prompt-launched sessions now work on a branch by default and let the user iterate before creating a PR; issue assignment creates a PR; changes to a human PR can be proposed as a child PR rather than directly mutating the human branch | Publication and branch ownership are distinct; preserve the human's branch unless direct update was authorized |
| [Copilot CLI `/pr`](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/manage-pull-requests) | Pushes all local commits before create, updates an existing PR idempotently, honors PR templates, can fix feedback, and makes merge strategy configurable | PR creation must be resumable; templates and repository strategy outrank skill defaults |
| [Google Jules](https://jules.google/docs/running-tasks/) | Runs in a fresh VM, starts from a selected repo/base branch, exposes the diff before publication, can publish a branch or PR, responds to review comments with new commits, and now loops on CI failures | Separate build, publish, review-response, and CI-babysit states |
| [Cursor cloud agents](https://docs.cursor.com/background-agent) | Isolated VM and separate branch per agent; environment setup is repository-configurable; current `/babysit` workflows iterate remotely until a PR is merge-ready | One agent/session owns one environment and branch; environment reproducibility is part of delivery |
| [Devin Review](https://docs.devin.ai/work-with-devin/devin-review) | Uses an isolated temporary worktree for review, applies requested changes as explicit commits, reflects repository mergeability/checks, and merges using the repository-configured method | Review isolation and repo-policy discovery should be default; never hard-code squash |

### What remains valid and what is obsolete

The older documents are not uniformly wrong.

Stable invariants:

- one reviewable and reversible delivery unit per PR;
- related tests travel with behavior;
- preserve a clean recovery point;
- required checks must pass on the candidate that will land;
- mainline history must support diagnosis and rollback;
- branches and temporary environments need explicit cleanup.

Obsolete assumptions:

- one human owns one local checkout;
- `origin/main` always exists and is the target;
- GitHub and `gh` are always available;
- the current branch is owned by the current agent;
- a dirty working tree can safely wait until the end of a long task;
- repository instruction files on a PR head are trusted;
- every agent may open, approve, merge, force-push, or delete branches;
- full CI must run before every checkpoint commit;
- opening a PR is always automatic once code exists;
- squash is the universal best merge method;
- worktree completion should locally merge into whatever branch happens to be
  checked out;
- provider portability can be produced by replacing `Claude` with `Codex` in a
  generated prompt.

### Confirmed gaps in Clade's current Git skills

#### `commit`

- A clean tree with unpushed commits calls `git log origin/main..HEAD`, assuming
  both remote name and default branch.
- Default behavior pushes immediately, even if the agent is on a protected,
  shared, detached, or unowned branch.
- It does not classify local interactive versus CI/cloud execution, new task
  versus existing PR, fork versus same-repo, or human-owned versus agent-owned
  branch.
- It discovers only GitHub CI or `CLAUDE.md`; the canonical workflow does not
  natively consume `AGENTS.md`, repository contribution guides, hooks, DCO,
  signing, or host-specific policies.
- It blocks all commits until the full CI suite passes. This creates exactly
  the long-running-agent failure mode Anthropic describes: too much useful work
  remains only in the working tree.
- Mandatory README counts and pipeline flowcharts are unrelated mutations in
  arbitrary repositories. Documentation synchronization must be project policy,
  not universal commit behavior.
- "Never ask for confirmation" ignores the difference between local commit,
  remote publication, and shared-state mutation.

#### `create-pr`

- It assumes GitHub and `gh`; there is no GitLab, Bitbucket, forge API, or local
  patch fallback.
- It can reconstruct multiple branches by cherry-pick without first proving
  branch ownership, remote write authority, signing requirements, fork
  topology, or stacked-PR support.
- It reads `CLAUDE.md` directly from the current checkout, which is unsafe for
  untrusted PR review contexts.
- It has no event-aware rule for open, closed, merged, fork, or human-authored
  PRs.
- It is shipped to Claude and Codex, but is absent from the MCP skills
  manifest, so Clade's provider-neutral distribution lacks the PR creation half
  of its delivery workflow.

#### `merge-pr`

- It hard-codes squash and `main/master`.
- It allows pending checks to proceed and treats failed checks as bypassable by
  a conversational confirmation.
- It uses an unsupported `gh pr merge --yes`.
- It does not inspect repository merge policy, required reviews,
  CODEOWNERS/rulesets, merge queue, auto-merge, commit signing, or live child
  PRs.
- It conflates author and integrator authority. Current Anthropic Action does
  not merge at all; other agents surface merge only through repository
  protections and explicit user action.
- It has no head-SHA lock, actor/branch ownership check, or trusted-base
  handling.

#### `worktree`

- It immediately creates a branch, while Codex-managed worktrees intentionally
  begin detached and snapshot disposable work.
- It assumes sibling filesystem paths and a new `claude`/`codex` process,
  instead of adapting to managed worktrees, containers, CI checkouts, or cloud
  VMs.
- It writes tracked `TASK.md` into an arbitrary repository.
- Completion locally merges branches into the current checkout instead of
  routing independently reviewable changes through that repository's normal
  integration path.
- It cannot prove another session no longer owns a branch before checkout,
  merge, or deletion.

#### Distribution architecture

- Claude instructions are canonical; Codex instructions are generated through
  broad string replacements such as `CLAUDE.md` → `AGENTS.md` and
  `.claude/` → `.clade/`.
- Text replacement cannot express platform semantics such as Codex detached
  worktrees, Claude Action event routing, or distinct permission systems.
- The same policy is duplicated across long prompts instead of being backed by
  a deterministic repository/forge capability probe.

### Target architecture: policy negotiation, not one recipe

Every Git delivery skill should begin with the same three stages.

#### 1. Context probe

A deterministic helper should emit a machine-readable profile without changing
state:

```yaml
runtime:
  surface: local-interactive | managed-worktree | cloud-vm | ci-action
  provider: claude | codex | other
  trusted_checkout: true | false | unknown
task:
  source: prompt | issue | open-pr | closed-pr | review | automation
  requested_actions: [edit, commit, push, open-pr]
repository:
  root: <path>
  forge: github | gitlab | bitbucket | other | none
  remote: origin
  default_branch: main
  current_branch: <name> | null
  detached: false
  dirty: false
  instructions: [AGENTS.md, CLAUDE.md, CONTRIBUTING.md]
branch:
  protected: false | true | unknown
  owner: session | user | shared | unknown
  upstream: <ref> | null
  worktree_owner: <path> | null
pull_request:
  number: 123 | null
  state: open | closed | merged | null
  same_repository: true | false | null
  base: main | null
policy:
  merge_methods: [squash, rebase, merge]
  required_checks: [...]
  signing: required | optional | unknown
  dco: required | optional | unknown
capabilities:
  commit: true
  push_current_branch: true
  open_pr: true
  merge_pr: false
  delete_remote_branch: false
```

Unknown is a first-class result. The skill must not convert an API failure into
permission.

#### 2. Authorization envelope

Classify actions independently:

**Normally autonomous inside an owned workspace**

- inspect status, history, worktrees, remotes, instructions, and policy;
- edit within task scope;
- run local verification;
- create a new task branch/worktree from the resolved base;
- commit explicit task files on the session-owned branch;
- push the session-owned branch when publication was requested or repository
  policy declares agent branch publication automatic.

**Require explicit task authority or repository automation policy**

- push to an existing human/shared PR branch;
- open a public PR;
- retarget or close a PR;
- force-with-lease after a restack;
- enable auto-merge or enter a merge queue;
- merge;
- delete remote branches;
- modify workflows, hooks, agent instructions, permissions, or signing config.

**Never infer**

- direct push to a protected/default branch;
- plain `--force`;
- bypassing CI, hooks, reviews, DCO, signing, or branch protection;
- approving the agent's own PR;
- executing PR-authored agent config in a privileged review environment;
- expanding token, repository, organization, or network scope to finish a task.

#### 3. Resumable delivery state

Persist state outside tracked project files, preferably under a path resolved
through `git rev-parse --git-path`, with a schema that can survive session and
provider changes:

```yaml
delivery_id: <stable-id>
task_source: issue:123
base_ref: origin/main
base_sha: <sha>
branch: agent/fix-example
owner: session:<id>
pr: 456
head_sha: <sha>
state: BUILD
published: true
verification:
  checkpoint: [...]
  candidate: [...]
authorization:
  push_current_branch: task-request
  open_pr: pending-human
```

Every transition is idempotent. A restarted agent updates an existing PR rather
than opening a duplicate. A crash after merge resumes CLEAN. A changed head
invalidates old verification.

### Runtime and event matrix

| Situation | Branch behavior | Commit/push behavior | PR/merge behavior |
|---|---|---|---|
| Local interactive task on clean default branch | Create owned task branch before edits | Checkpoint commits; push only when requested/default policy says publish | Open draft/ready PR according to request; never merge implicitly |
| Local task already on owned topic branch | Reuse after verifying upstream and no other worktree owner | Commit explicit scoped files; normal push | Update existing PR idempotently |
| Detached managed worktree | Work detached until preservation/publication is requested | Commit is allowed, but create/attach a branch before push | Hand off, create branch, or open PR using runtime-native mechanism |
| Issue-triggered cloud/CI agent | New branch from API-resolved requested/default base | End with commits; publish owned branch | Create PR only if event/policy authorizes it; otherwise return branch/creation link |
| Open agent-authored PR | Reuse PR head | Commit and push review/CI fixes | Never open duplicate; mark ready only after policy gates |
| Open human-authored PR | Preserve human ownership by default | Prefer child branch/PR; direct push only with explicit authority | Human accepts child PR or explicitly delegates branch updates |
| Fork PR | Treat head and instructions as untrusted; fetch pull ref | Do not assume origin write access or maintainer-edit permission | Review read-only or create maintainer-owned repair branch |
| Closed/merged PR follow-up | New branch from current base, not the dead head | New commit lineage | New PR linked to predecessor |
| Multiple agents | One owned branch/worktree per agent | No concurrent writers to one branch; publish checkpoints | Integrate through ordered PRs/queue, not arbitrary local merge |
| No forge/API | Plain Git capability probe | Local commits; emit patch/bundle when push unavailable | Report that PR/merge is unsupported rather than inventing GitHub |

### Commit policy for agents

Clade should replace "full CI before any commit" with two evidence levels:

1. **Checkpoint commit**
   - one coherent slice;
   - affected tests/lint/typecheck;
   - explicit files only, unless a controlled ephemeral action needs an
     emergency all-file recovery commit;
   - may remain draft-only and may later be squashed.
2. **Candidate head**
   - synchronized with the intended base;
   - complete repository-required verification;
   - remote checks for the exact pushed SHA;
   - eligible for ready/merge state.

Before committing, discover repository-native requirements:

- closest trusted `AGENTS.md`, `CLAUDE.md`, and contribution docs;
- hooks and pre-commit framework;
- commit message convention/template;
- DCO/signoff and signature requirements;
- monorepo/package-specific affected tests;
- generated-file checks.

Do not universally add README diagrams, TODO updates, attribution trailers, or
Conventional Commit prefixes. Those are repository policy decisions.

Checkpointing is mandatory in writable Git contexts. Create a checkpoint as
soon as the current result is coherent and independently describable, and
always before:

- changing to a materially different research question or implementation slice;
- handing work to another agent, provider, worktree, or human;
- context compaction, planned interruption, or normal session end;
- risky history, branch, worktree, or integration operations;
- a long validation/deployment phase after the files needed for that phase are
  already reviewable.

Do not checkpoint merely because a timer elapsed, and do not create commits
that knowingly leave the repository syntactically broken when a coherent
boundary is available. Repository rules still determine message format,
signing, hooks, and whether generated files belong in the same unit. Full
candidate CI is not a prerequisite for a checkpoint; record the narrower
verification that actually ran.

At every normal boundary, modifications must be in one of four explicit
states:

- committed on an owned branch;
- committed at detached HEAD with a runtime-preserved reference, or
  intentionally preserved as a runtime snapshot;
- exported as a patch/bundle because commit/push is unavailable;
- reported as blocked with exact dirty files and reason.

The fallback states are for environments where a commit is technically or
explicitly prohibited; they are not excuses to defer a normal commit. "Done,
with uncommitted changes" is not a valid state.

### Repository and runtime adaptation precedence

Clade must resolve behavior in this order:

1. hard safety boundaries and the user's explicit authorization;
2. trusted target-repository policy, including the closest applicable
   `AGENTS.md`/`CLAUDE.md`, contribution guide, hooks, signing/DCO rules, forge
   rulesets, required checks, and configured merge methods;
3. current event and ownership, such as issue, agent PR, human PR, fork PR,
   closed PR, owned branch, shared branch, or detached worktree;
4. runtime capabilities exposed by Claude Code, Codex, MCP, CI, or a cloud
   agent;
5. Clade's conservative portable defaults.

Lower layers may select a compatible mechanism but may not weaken a higher
layer. For example:

- Codex may preserve a detached checkpoint and attach a branch only when
  publication is requested;
- Claude Code in a normal owned checkout may checkpoint directly on the task
  branch;
- Claude Code Action may reuse an open agent PR head but must not execute
  instructions supplied by an untrusted PR head;
- a repository that requires signed commits or a specific message format
  overrides Clade's default commit mechanism;
- lack of `gh` selects another forge adapter or a local patch/bundle path; it
  does not turn a non-GitHub repository into an error;
- an unknown policy or ownership result becomes a safe stop for the affected
  external mutation, not implicit permission.

Provider parity therefore means equal policy outcomes for equal inputs, not
byte-identical shell commands. Cross-provider fixture tests should assert the
decision (`checkpoint`, `publish`, `open/update PR`, `integrate`, or `stop`) and
allow the Claude Code and Codex adapters to use their native preservation and
handoff mechanisms.

### PR policy for agents

- PR publication is a separate action from branch publication.
- Honor repository PR templates and host-native metadata.
- Open draft early only when requested or policy allows autonomous PR creation;
  otherwise return a branch and creation link.
- Existing branch PR creation is idempotent: update the same PR.
- Review comments and CI failures create new checkpoint commits; do not rewrite
  reviewed history unless the branch is owned and restack policy permits it.
- An authoring agent cannot count its own review as independent approval.
- PR descriptions record agent/runtime identity, base/head SHAs, scope,
  evidence, residual risk, and whether commits are checkpoints intended for
  squash.
- Untrusted instruction changes are displayed for review but evaluated using
  trusted-base instructions.

### Merge policy for agents

`merge-pr` should become an integrator workflow, not the automatic tail of
every authoring workflow.

1. Require explicit user instruction or repository automation policy.
2. Re-fetch the PR and repository rules immediately before merge.
3. Require all configured checks/reviews/conversations; do not offer a
   conversational bypass for a red or pending protected gate.
4. Lock the reviewed head SHA.
5. Prefer repository-configured merge strategy or auto-merge/merge queue.
6. If several methods remain available, choose from history semantics and
   explain the choice; never hard-code squash.
7. Detect live child PRs before rewriting parent ancestry.
8. Never approve the agent's own PR.
9. Clean only session-owned branches/worktrees; remote deletion follows repo
   policy or explicit authority.
10. Verify the landed commit, updated default branch, descendant state, and
    absence of dirty work before declaring Done.

### Multi-agent policy

- One session owns one mutable branch reference.
- Use separate worktrees, clones, containers, or detached snapshots for
  parallel work.
- Record branch/worktree ownership and refuse to mutate a ref owned by another
  live session.
- Split tasks by non-overlapping delivery unit; use explicit dependencies where
  overlap is unavoidable.
- Agents publish through PRs or a controlled integration branch/queue.
- A merge agent is a separate role from author and reviewer.
- Final integration tests the combined current base plus candidate, not merely
  each stale agent head.
- Progress/log artifacts belong in delivery state or an explicitly
  repository-approved location, not an unconditional tracked `TASK.md`.

### Proposed Clade skill architecture

```text
git-context probe (deterministic, read-only)
        │
        ├── trusted-instruction resolver
        ├── forge adapter: GitHub | GitLab | Bitbucket | plain Git
        ├── runtime adapter: local | managed worktree | cloud | CI
        └── policy/permission/ownership profile
                         │
                 delivery state machine
        ┌────────────────┼────────────────┐
      commit          create/update PR   integrate
        │                  │                │
   checkpoint/candidate  review/CI loop   merge/cleanup
```

Canonical Agent Skills should be provider-neutral. Claude Code and Codex
packages should add only thin surface adapters:

- how to locate trusted instructions;
- how the runtime exposes worktrees/snapshots/handoffs;
- how approval and sandbox capabilities are represented;
- how to call the shared deterministic scripts.

Do not generate semantic behavior through global word replacement. Ship
`create-pr` in the MCP manifest so the provider-neutral lifecycle is not
missing a state.

### Implementation plan

#### Phase 1 — Stop unsafe universal assumptions

- Remove automatic `origin/main` assumptions.
- Refuse commit/push on detached, default, protected, shared, or unknown-owned
  branches until the runtime-specific path is resolved.
- Remove universal README/flowchart mutation from `commit`.
- Split checkpoint verification from candidate verification.
- Make `merge-pr` respect repository strategy, block pending/red required
  checks, and lock head SHA.
- Remove unsupported `--yes`.

#### Phase 2 — Shared capability probe

- Add a deterministic `git-context` script with JSON output.
- Detect remotes/default branch/worktrees/detached state/upstream/dirty state.
- Add GitHub adapter first; represent absent CLI, auth, API failures, and
  unknown protection explicitly.
- Add fixture tests for local-only, GitHub, fork PR, detached worktree, existing
  PR, protected default, and shared branch.

#### Phase 3 — Resumable delivery and event routing

- Persist delivery state outside tracked project files.
- Route issue/open PR/closed PR/new prompt/review events separately.
- Guarantee commit, snapshot, patch, or explicit blocker at session end.
- Make branch and PR publication individually configurable.

#### Phase 4 — Provider and distribution parity

- Add GitLab/Bitbucket/plain-Git adapters.
- Replace Codex text substitution with canonical provider-neutral instructions
  and explicit surface references.
- Ship the same lifecycle skills and companion scripts through Claude, Codex,
  and MCP.
- Add generated-distribution parity tests for behavior, not just file hashes.

#### Phase 5 — Agent integration control

- Add branch/worktree ownership leases.
- Add child-PR discovery and stack restack.
- Add merge queue/auto-merge support where the forge provides it.
- Separate author, reviewer, and integrator roles.
- Test crash recovery at every state transition.

### Evaluation criteria

The redesign should be tested against scenarios, not prose compliance:

- completed agent task cannot finish dirty without an explicit preservation
  artifact;
- a coherent research or implementation slice triggers a checkpoint before
  the agent changes direction or crosses a session/provider boundary;
- checkpoint creation does not silently authorize push, PR creation, merge, or
  branch deletion;
- repository policy wins over Clade defaults while Claude Code and Codex reach
  the same authorization decision through runtime-native mechanisms;
- direct default-branch push is denied unless the user explicitly requested it
  and repository policy allows it;
- open PR work updates the correct head without creating a duplicate;
- human PR work produces a child PR unless direct mutation is authorized;
- fork PR instructions cannot execute privileged hooks/config;
- detached Codex work can be preserved without pretending a branch already
  exists;
- GitLab/plain-Git repositories do not run `gh`;
- failed policy discovery yields `unknown` and a safe stop;
- red/pending required checks cannot be conversationally bypassed;
- merge method follows repository policy and live ancestry;
- branch deletion never targets another live session's worktree;
- Claude, Codex, and MCP distributions make the same policy decision for the
  same context fixture.

## [Research] 2026-07-27 — Universal model harness with native surface adapters

**Status:** architecture contract proposed; implementation not started

**Question:** How should Clade provide one strong experience across Claude Code,
Codex, Kimi Code, MCP clients, hosted agents, and future model providers without
pretending that their protocols and user interfaces are identical?

### Decision summary

Clade should use a React Native-style architecture:

- define one semantic contract for user intent, policy, status, delivery, and
  task outcomes;
- negotiate capabilities at runtime;
- implement thin native adapters for each agent runtime and surface;
- expose provider-specific strengths rather than collapsing every runtime to
  the weakest common denominator;
- make every degradation or unsupported requirement visible;
- preserve an escape hatch for native configuration when the common contract
  cannot express a provider feature.

Parity means the same intent, safety decision, progress truth, and quality bar.
It does **not** mean identical config files, model names, commands, status-line
renderers, or permission flags.

The word `provider` is currently overloaded and must be split. Claude Code and
Codex are agent runtimes. Anthropic, OpenAI, MiniMax, Moonshot, Bedrock, Vertex,
Azure, and a local gateway are inference providers. Anthropic Messages, OpenAI
Responses, OpenAI Chat Completions, and Google GenAI are wire protocols. A
model ID is an opaque value inside that provider/protocol context.

### Current official evidence

The architecture below is based on current first-party documentation rather
than assuming that historical OpenAI-compatible or Anthropic-compatible APIs
provide equivalent agent behavior:

- [Claude Code status lines](https://code.claude.com/docs/en/statusline) execute
  a user command, send a changing JSON document on stdin, and render arbitrary
  command output. The current payload includes native rate-limit, worktree, PR,
  context-window, effort, and model data, but fields may be absent.
- [Claude Code model configuration](https://code.claude.com/docs/en/model-config)
  treats aliases and effort levels as runtime/provider-dependent. Gateways can
  use custom model strings, so a closed model allowlist cannot be authoritative.
- [Claude Code LLM gateway configuration](https://docs.anthropic.com/en/docs/claude-code/llm-gateway)
  changes routing and authentication independently from the displayed model
  selection.
- [Codex custom model providers](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers)
  separate a model provider from the selected model and support provider
  endpoints, authentication, headers, and wire API selection. The Responses
  API is the preferred OpenAI path; Chat Completions is legacy.
- [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
  exposes the TUI status line as an ordered list of native item identifiers,
  not an arbitrary shell renderer. Project config is trust-gated, and
  provider/authentication settings remain user-level concerns.
- [Codex model documentation](https://learn.chatgpt.com/docs/models) shows that
  supported reasoning effort and other controls vary by model.
- [MiniMax's Anthropic-compatible API](https://platform.minimax.io/docs/api-reference/text-anthropic-api)
  explicitly supports only a subset of Anthropic request features and ignores
  some Anthropic parameters. Protocol compatibility is therefore not
  capability parity.
- [MiniMax's current Claude Code integration](https://platform.minimax.io/docs/token-plan/claude-code)
  uses current MiniMax model IDs and the `/anthropic` endpoint; both can change
  independently from Clade.
- [Kimi's Claude Code integration](https://www.kimi.com/code/docs/en/third-party-tools/claude-code.html)
  maps Claude Code effort values and displayed model identities onto Kimi
  behavior, demonstrating why the runtime's display label is not a reliable
  resolved model identity.
- [Kimi Code provider configuration](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/providers.html)
  separately declares providers, protocols, models, context sizes, and model
  capabilities. This is a useful precedent for capability declarations plus
  live discovery.

These contracts are moving targets. Clade should test adapter behavior and
schema tolerance, not copy today's fields into a permanent universal schema.

### Audit of the current Clade design

The present implementation has several incompatible meanings hidden behind
the same names:

| Current construct | Actual meaning | Failure mode |
| --- | --- | --- |
| `worker_provider=claude|codex` | agent CLI/runtime | cannot describe Codex through Azure, Claude Code through MiniMax, or another runtime |
| `usage_provider=claude|minimax` | one usage data source special case | defaults all other providers to Claude semantics |
| `default_model=sonnet` | Claude alias | presented as a provider-neutral default |
| `codex_cheap_model` / `codex_strong_model` | runtime-specific role mapping | every new runtime requires new top-level fields |
| `_MODEL_ALIASES` / `ALLOWED_MODEL_IDS` | static Claude catalog | rejects valid gateway IDs and becomes stale |
| model-name prefix checks | inferred provider/capability | custom IDs, aliases, proxies, and renamed models route incorrectly |
| unknown worker provider fallback | implicit Claude execution | a typo can run the wrong runtime and spend against the wrong account |
| Codex skill generator word replacement | packaging shortcut | surface semantics are rewritten lexically rather than adapted |

Additional concrete gaps:

- `provider-switch.sh` is a Claude Code settings mutator, not a universal
  provider manager. Its bootstrapped MiniMax endpoint and model IDs are stale.
- The settings UI hard-codes two runtimes and Claude-only model choices, then
  adds separate Codex fields.
- Claude, Codex, and MCP manifests expose different lifecycle and usage skills.
  The MCP package currently exposes Claude-oriented provider/status skills but
  not the corresponding Codex usage adapter.
- the Claude status line and Codex status line solve the same user need through
  fundamentally different runtime mechanisms;
- Claude usage collection still contains a private OAuth/cache fallback even
  though current status-line events can provide native rate-limit data;
- worker launchers assume runtime-specific permission bypass flags and the
  Codex launcher has no equivalent resume/MCP handoff contract;
- canonical skill behavior is sometimes transformed with global word
  replacement, so generated text can claim parity that the target runtime does
  not provide.

The most dangerous behavior is silent fallback. An unknown runtime, provider,
protocol, model, or required capability must never quietly become Claude.

### Universal execution vocabulary

Every resolved Clade run should model these dimensions independently:

1. **Surface** — where the user experiences the agent: terminal TUI, IDE,
   desktop app, cloud task, CI runner, GitHub Action, MCP client, or headless
   orchestrator.
2. **Agent runtime** — the process that owns the agent loop: Claude Code,
   Codex, Kimi Code, Clade's worker runner, or another CLI/service.
3. **Inference provider** — the account and serving system that bills and
   executes inference: Anthropic, OpenAI, MiniMax, Moonshot, Azure, Bedrock,
   Vertex, a gateway, or local inference.
4. **Wire protocol** — the request/streaming schema used between runtime and
   inference provider: Anthropic Messages, OpenAI Responses, OpenAI Chat
   Completions, Google GenAI, or a runtime-native protocol.
5. **Model** — the opaque provider-scoped ID actually sent on the wire.
6. **Capability profile** — observed and declared behavior such as tool use,
   vision, document input, structured output, prompt caching, reasoning
   controls, context size, resume, subagents, hooks, status rendering, usage
   data, Git access, and worktree ownership.
7. **Policy/profile** — task intent and constraints such as explore,
   implement, review, integrate, latency/cost preference, required tools,
   repository rules, and approval boundaries.

This vocabulary avoids configurations such as "Codex provider with an OpenAI
provider." The first is `runtime=codex`; the second is
`inference_provider=openai`.

### Resolved execution envelope

Clade should create an immutable envelope before starting a worker and attach
it to status, logs, handoffs, and delivery records:

```yaml
schema_version: clade.execution/v1
request:
  profile: implement
  requirements:
    tools: required
    repository_write: required
    image_input: preferred
  preferences:
    quality: strong
    latency: balanced
resolved:
  surface: terminal
  runtime:
    id: claude-code
    version: 1.x
  inference:
    provider: minimax
    protocol: anthropic_messages
    endpoint_identity: minimax-global
    requested_model: strong
    wire_model: MiniMax-M2.7
  controls:
    requested_effort: high
    wire_effort: provider-default
  capabilities:
    tools: supported
    image_input: unsupported
    status_renderer: command_json
    rate_limits: native_event
  degradations:
    - image_input unavailable for selected provider/model
provenance:
  repository_policy: .clade/policy.yaml
  user_connection: minimax-global
  runtime_adapter: claude-code@1
```

`endpoint_identity` is a stable local connection name, not a secret URL.
Tokens, raw credentials, and machine-specific paths must never enter the
repository configuration, task prompt, envelope, status output, or Git diff.

The envelope records both requested and resolved values. This makes an alias
change, gateway remap, effort translation, or runtime fallback observable. It
also gives every status surface one source of truth.

### Adapter boundaries

The core should depend on small interfaces rather than runtime conditionals:

```text
User intent + trusted repo policy + user connection
                         │
                  capability resolver
                         │
               immutable execution envelope
                         │
        ┌────────────────┼────────────────┐
        │                │                │
 runtime adapter   transport adapter   surface adapter
 agent lifecycle   auth/wire/model      status/config/UI
        │                │                │
        └────────────────┼────────────────┘
                         │
             usage + Git delivery adapters
```

- `RuntimeAdapter` handles launch, resume, cancellation, task handoff,
  permission representation, subprocess events, and runtime-native tools.
- `TransportAdapter` handles provider connection, authentication references,
  wire protocol, live model catalog, request-control translation, and usage
  normalization.
- `SurfaceAdapter` handles configuration storage, trust boundaries, status
  rendering, notifications, approval UI, and discoverability.
- `UsageAdapter` normalizes authoritative provider/runtime usage observations
  with freshness and source metadata.
- `DeliveryAdapter` owns repository/forge/worktree facts from the earlier Git
  delivery design and must not infer authorization from the model provider.

One adapter may cover several compatible targets, but compatibility is an
explicit contract and conformance suite, not a string substitution. A
runtime/provider pair can add a narrow composition adapter when controls such
as Kimi effort mapping cannot be expressed independently.

### Capability negotiation and degradation

Capabilities need four states: `supported`, `unsupported`, `unknown`, and
`conditional`. Boolean flags erase the difference between "not implemented"
and "not yet discovered."

Every requested capability has a requirement level:

- `required`: fail preflight before spending tokens or changing the repository;
- `preferred`: select the best candidate, or continue with an explicit
  degradation;
- `optional`: use when available without affecting outcome claims;
- `forbidden`: reject candidates that provide or require the behavior.

Resolution should be deterministic:

1. collect trusted repository requirements and explicit user intent;
2. enumerate user-configured runtime/provider/model candidates;
3. refresh live model metadata when the adapter supports discovery;
4. combine declared capabilities with runtime probes;
5. remove candidates that violate required/forbidden constraints;
6. rank remaining candidates by the selected task profile;
7. materialize the envelope and show degradations;
8. require confirmation only when the resolution expands authority or cost
   beyond the user's request.

Unknown is never silently treated as supported. A provider typo, unsupported
effort, missing tool protocol, unavailable status field, or stale catalog must
produce a typed error or named degradation.

Model catalogs should use live discovery with a time-to-live where available,
plus a versioned pinned fallback for offline operation. Static model lists are
test fixtures and fallback metadata, not the source of truth.

### Configuration ownership and precedence

Universal configuration must separate portable policy from machine
connections:

```text
hard safety / organization policy
              ↓
explicit task authorization and constraints
              ↓
trusted repository requirements
              ↓
user runtime/provider connections and model profiles
              ↓
probed runtime/surface capabilities
              ↓
Clade defaults
```

Higher layers constrain lower ones; they do not donate missing authority.
Repository configuration may require capabilities or recommend a profile, but
must not redirect provider endpoints, select credential sources, weaken
sandboxing, or inject secret-bearing headers. Codex's trust-gated project
configuration is one surface implementation of this rule, not the universal
storage mechanism.

A portable repository file should therefore express intent:

```yaml
schema_version: clade.policy/v1
profiles:
  implement:
    requires: [tools, repository_write]
    prefers: [strong_reasoning, resumable_session]
  review:
    requires: [repository_read]
    forbids: [repository_write]
delivery:
  checkpoint: coherent_slice
  integration: repository_policy
```

User configuration binds that intent to local connections and models:

```yaml
connections:
  anthropic-primary:
    runtime: claude-code
    inference_provider: anthropic
    protocol: runtime_native
  openai-codex:
    runtime: codex
    inference_provider: openai
    protocol: openai_responses
profiles:
  strong:
    candidates:
      - connection: anthropic-primary
        model: opus
      - connection: openai-codex
        model: gpt-5.3-codex
```

Adapters translate these values into `settings.json`, `config.toml`,
environment variables, API calls, or managed-service configuration only at
the boundary. Clade should never make one runtime's config file its canonical
cross-runtime schema.

### One status intent, several native renderers

Status parity should begin with a provider-neutral snapshot, not a shared shell
script:

```yaml
schema_version: clade.status/v1
observed_at: 2026-07-27T16:00:00Z
task:
  state: working
  progress:
    completed: 5
    total: 8
    source: delivery_state
git:
  branch: research/universal-harness-contract
  dirty: false
  checkpoint_sha: 97d61b6
execution:
  runtime: claude-code
  provider: minimax
  model: MiniMax-M2.7
limits:
  - window: 5h
    used_percent: 31
    resets_at: 2026-07-27T19:00:00Z
freshness:
  limits: native_event
  progress: orchestrator
```

Every field needs source, observation time, and unknown handling. A cached
value must be visibly stale; absence must not render as zero. Task progress
must come from durable delivery/task state, not from elapsed wall time or the
number of lines emitted by a model.

The portable user preference should describe desired information and density:

```yaml
status:
  density: compact
  show: [task_progress, model, context, usage, git]
  usage_style: percent
  color: auto
```

Each surface then provides the strongest native rendering it can:

| Surface | Native mechanism | Clade adapter behavior |
| --- | --- | --- |
| Claude Code terminal | command receives JSON stdin and prints arbitrary text | merge runtime JSON with the Clade snapshot, then render the requested theme |
| Codex terminal | ordered native `tui.status_line` item list | map supported intent to native item IDs; expose unsupported Clade fields in a companion status command/panel |
| Codex app/cloud | product-owned UI with surface-dependent controls | publish the same snapshot where the surface API permits; never claim terminal-only customization |
| Kimi Code | runtime/provider capability-dependent UI | use a Kimi surface adapter and declared status capabilities |
| MCP/headless | no guaranteed persistent footer | expose a `clade_status` resource/tool and structured event, with a compact text fallback |
| CI/GitHub Action | log and check-run summaries | render phase transitions, checkpoint SHA, degradation, and final outcome |

Claude Code's arbitrary renderer is strictly more flexible than Codex's native
item list. Equal experience therefore means equal truth and discoverability,
not pixel-identical output. On Codex, Clade should preserve native TUI behavior
and offer a companion view for unsupported task-progress fields. It must not
install a fake shell footer that fights the runtime.

The existing `slt`, `claude-usage-watch`, and `codex-usage` behaviors should
become compatibility entry points into one semantic `status` / `usage`
capability:

```text
/clade:status setup
/clade:status show
/clade:status style percent
/clade:status diagnose
```

The command resolver selects the surface adapter. Existing names can remain as
deprecated aliases for one release cycle. Help output must say which requested
fields are native, emulated, stale, unavailable, or shown elsewhere.

Claude's private OAuth/cache usage fallback should be isolated as a versioned
legacy adapter, disabled unless native rate-limit data is unavailable and the
user opts in. Native runtime events or documented provider APIs are preferred
over scraping private credential stores.

### Skills: one semantic package, explicit surface overlays

Canonical skills should be organized into three layers:

```text
skills/
  core/
    commit/
    create-pr/
    merge-pr/
    status/
    provider/
  surfaces/
    claude-code/
    codex/
    kimi-code/
    mcp/
  providers/
    anthropic/
    openai/
    minimax/
    moonshot/
```

- `core` owns provider-neutral intent, safety invariants, state transitions,
  expected output, and deterministic helper contracts.
- `surfaces` owns instruction-file discovery, trust behavior, native config,
  approval representation, status UI, and runtime command syntax.
- `providers` owns documented protocol quirks, model discovery, usage sources,
  and control translation.

A built package is a declared composition such as:

```yaml
package: codex-openai
core_contract: clade/v1
surface_adapter: codex/v1
provider_adapter: openai-responses/v1
capabilities:
  status:
    native: [model, context, usage, git]
    companion: [task_progress, checkpoint]
```

Generated packages should contain provenance and contract versions. They should
not be created by global replacements of "Claude" with "Codex" or
`CLAUDE.md` with `AGENTS.md`. Template substitution remains acceptable for
mechanical names only when the generated output is validated against a
surface-specific golden fixture.

Claude Code, Codex, and MCP distributions should expose the same core lifecycle
states: inspect, implement, test, checkpoint, publish, review, integrate, and
clean. A distribution may represent a state with a runtime-native command,
tool, prompt, or UI action, but it cannot silently omit the state. Package
manifests need a parity test over semantic capabilities rather than identical
file lists.

Provider switching must become connection selection. A `provider` skill should
never rewrite secrets or silently edit another runtime's native settings. It
should:

1. list configured local connection identities and discovered capabilities;
2. resolve a profile against the current runtime/surface;
3. preview native configuration changes and degradations;
4. apply only through the selected surface adapter;
5. run a non-destructive connection/capability probe;
6. report the resolved execution envelope.

### Model controls and aliases

Portable profiles such as `fast`, `balanced`, and `strong` are preferences, not
model aliases. The resolver chooses among user-configured candidates and logs
the result. `sonnet`, `opus`, `gpt-*`, `MiniMax-*`, and `kimi-*` remain
provider-scoped model identifiers.

Reasoning controls also require translation:

```yaml
portable_intent:
  reasoning: strong
adapter_result:
  claude-code/anthropic:
    effort: high
  codex/openai:
    reasoning_effort: high
  claude-code/kimi:
    effort: high
    mapped_provider_effort: high
  minimax-anthropic:
    control: provider_default
    degradation: exact portable effort unavailable
```

Adapters must validate values against the resolved runtime/model. Unsupported
controls are not passed through optimistically. Provider-specific extras can
be supplied in a namespaced `native` section and are preserved round-trip:

```yaml
native:
  codex:
    model_reasoning_summary: auto
  claude_code:
    extended_context: true
```

The common schema should allow extension without pretending to understand a
new option. Unknown namespaced values are retained for their owning adapter;
unknown universal fields fail schema validation.

### Runtime lifecycle contract

All agent runtimes should implement the same observable lifecycle even when
their session APIs differ:

```text
probe → resolve → start → observe → checkpoint* → verify
                                     ↘ suspend/resume
                               → publish? → integrate? → clean
```

Required runtime operations:

- `probe`: version, available commands, surface, trust state, capabilities;
- `start`: launch with the immutable envelope and least required authority;
- `observe`: structured state/events without parsing decorative terminal text;
- `cancel`: stop without losing already durable checkpoints;
- `handoff`: persist context needed by another compatible runtime;
- `resume`: native resume when available, otherwise a declared reconstructed
  handoff with reduced-fidelity metadata;
- `finalize`: verify repository state and emit a terminal task outcome.

If a runtime does not support native resume, Clade should say
`resume=reconstructed`; it must not fabricate a session ID or claim continuity.
Permission bypass flags are runtime-specific high-risk capabilities, never
portable defaults.

### Integrating the Git delivery contract

The earlier adaptive checkpoint and PR design becomes a peer of model
resolution, not a model-specific prompt:

- repository/forge facts are probed before the model is selected;
- a branch/worktree lease belongs to the Clade run, not the provider;
- coherent research and implementation slices checkpoint regardless of which
  model produced them;
- switching runtime/provider is a checkpoint trigger because it is a handoff
  boundary;
- checkpoint does not imply push, PR, or merge authorization;
- the execution envelope and delivery state record which runtime/provider made
  each checkpoint without adding generated attribution to the commit message;
- PR creation and merge remain forge/policy decisions and are never inferred
  from model confidence;
- review must use the exact candidate/head SHA; integration must verify that
  SHA and repository merge policy.

This ensures a task can begin in Claude Code, be reviewed in Codex, and be
integrated by a headless Clade worker without changing its delivery invariants.

### Experience contract

For the same task, every supported surface must provide:

1. the same resolved task intent and repository safety decision;
2. a visible runtime/provider/model identity;
3. explicit capability degradations before irreversible work;
4. durable progress/checkpoint truth;
5. access to current usage/context when the provider exposes it;
6. the same verification and delivery gates;
7. a clear native path to provider-specific power features;
8. a truthful explanation when a surface cannot provide an equivalent.

Discoverability may be native:

- a Claude Code slash command;
- a Codex skill or config entry;
- a Kimi Code agent/command;
- an MCP tool/resource;
- a CI summary.

Command spelling is secondary. The semantic input/output and quality bar are
the compatibility contract.

### Conformance and end-to-end matrix

Every adapter must pass shared contract fixtures plus pair-specific
integration tests. The minimum release matrix is:

| Scenario | Contract to verify |
| --- | --- |
| Claude Code + Anthropic | native tools, model/effort, native rate-limit event, command status renderer |
| Claude Code + MiniMax Anthropic API | supported tools, unsupported image/document behavior, ignored controls, current endpoint/model discovery |
| Claude Code + Kimi coding API | resolved identity differs from display alias, effort mapping, context/compaction behavior |
| Codex CLI + OpenAI | Responses provider, model-specific reasoning validation, native status item mapping |
| Codex CLI + custom Responses gateway | user-scoped provider/auth, opaque model ID, no closed allowlist |
| Codex cloud task | project/runtime limitations represented as capabilities, no local-config assumptions |
| Kimi Code + Moonshot | declared model/context/capabilities and Kimi-native lifecycle |
| MCP unknown client | structured status tool/resource, no persistent-footer assumption |
| headless/CI | no interactive UI, deterministic event/status summary |
| offline/stale catalog | pinned fallback is marked stale and required unknown capabilities block |

Cross-cutting fixtures:

- invalid runtime/provider/protocol/model never falls back to another target;
- missing, null, extra, and newer status-event fields do not crash renderers;
- stale usage is visibly distinct from zero usage;
- unsupported required capability fails before token spend or repository write;
- unsupported preferred capability produces an envelope degradation;
- project config cannot change provider endpoints, credential sources, or
  permission authority;
- model aliases resolve differently per connection without changing the
  portable profile;
- provider/model changes force a new envelope and checkpoint handoff;
- Claude, Codex, Kimi, and MCP packages expose every core lifecycle state;
- generator output contains no false surface claims;
- a coherent slice cannot end dirty without a checkpoint, patch/snapshot, or
  explicit blocker;
- exact candidate SHA, tests, PR head, merge result, and branch cleanup remain
  traceable end to end.

Contract tests should use recorded, sanitized adapter fixtures. Live smoke tests
run only when credentials are intentionally available and report skipped
coverage per provider. Clade should not require every contributor or CI job to
hold credentials for every vendor.

### Observability and compatibility rules

Every adapter event should carry:

- schema and adapter version;
- execution/run ID;
- surface/runtime/provider/protocol/model identities;
- source timestamp and receipt timestamp;
- freshness;
- requested and resolved values;
- named degradations;
- secret-redacted configuration provenance.

Public event schemas use additive evolution. Consumers ignore unknown fields,
but required semantic changes increment the schema version. Adapter
compatibility is a tested range, not an assertion of "OpenAI compatible" or
"Anthropic compatible."

Clade should emit one diagnostic bundle that answers:

- what did the user ask for?
- which config layers participated?
- what runtime/provider/model was actually selected?
- which capabilities were probed, declared, unknown, or degraded?
- which native files would be or were changed?
- what status and usage sources are active?
- what checkpoint/PR/merge state is durable?

The bundle must redact credentials, authorization headers, private endpoint
query strings, and secret-bearing environment values by construction.

### Migration plan

#### Phase 0 — Correct names and fail closed

- introduce `agent_runtime`, `inference_provider`, `wire_protocol`, and
  `connection` internally while reading current config as deprecated aliases;
- reject unknown worker runtimes instead of falling back to Claude;
- stop presenting Claude model aliases as the universal model catalog;
- mark the current MiniMax bootstrap metadata deprecated/stale;
- log a resolved envelope for existing Claude and Codex workers;
- add regression tests before changing settings UI or package names.

#### Phase 1 — Semantic contracts

- define versioned `ExecutionEnvelope`, `CapabilitySet`, `StatusSnapshot`, and
  typed resolution/degradation errors;
- add Claude Code and Codex runtime/surface adapters around current launchers;
- split usage collection into documented native, provider API, and opt-in
  legacy adapters;
- make task progress consume durable delivery state.

#### Phase 2 — Native status and package composition

- create one `status` semantic skill with Claude command-renderer, Codex
  native-item/companion, MCP resource, and headless summary adapters;
- replace global Codex word replacement with explicit package compositions;
- add lifecycle-capability parity tests for Claude, Codex, and MCP manifests;
- ship deprecated command aliases with exact migration output.

#### Phase 3 — Provider/model registry

- add user-scoped connections, live model discovery, TTL/pinned fallback, and
  model capability declarations;
- implement Anthropic, OpenAI Responses, MiniMax Anthropic, and Moonshot/Kimi
  adapters;
- replace provider-specific top-level model fields with task profiles and
  ordered candidates;
- migrate the settings UI to the resolver vocabulary.

#### Phase 4 — Full runtime matrix

- add Kimi Code and headless runtime adapters;
- exercise cloud/CI limitations and reconstructed handoff behavior;
- enforce conformance fixtures in generated-package CI;
- add credential-gated live smoke tests without making them merge blockers for
  contributors lacking vendor accounts.

#### Phase 5 — Remove compatibility shims

- remove deprecated `worker_provider`, `usage_provider`, Claude-only default
  model semantics, legacy command names, and string-replacement generation only
  after migration telemetry/tests show no supported path depends on them;
- retain versioned import tooling and clear errors for old configs.

### Non-goals

- Clade will not make different models produce identical prose or performance.
- Clade will not emulate unsupported provider features by silently changing
  models.
- Clade will not store cross-vendor secrets in repositories.
- Clade will not promise pixel-identical status lines across unrelated UI
  systems.
- Clade will not treat protocol compatibility as proof of tool, image,
  reasoning, caching, context, usage, or billing compatibility.
- Clade will not make model selection responsible for Git authorization.

### Acceptance decisions

The following are architecture invariants, not optional implementation ideas:

- common semantic core plus native adapters;
- separate runtime, inference provider, protocol, model, surface, and policy;
- explicit capability negotiation with `unknown` and typed degradation;
- immutable resolved execution envelope;
- no unknown-target fallback;
- portable repository intent, user-scoped provider connections and secrets;
- one truthful status snapshot with surface-native renderers;
- semantic skill/package parity instead of identical files or global text
  replacement;
- adaptive checkpoints across runtime/provider handoffs;
- exact-SHA Git delivery and repository-owned merge policy;
- conformance fixtures for every supported adapter pair.

Implementation should proceed in the ordered phases above. Updating individual
model IDs or adding another `if provider == ...` branch before Phase 0 would
extend the current coupling and should be rejected in review.
