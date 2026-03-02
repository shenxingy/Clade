# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into VISION.md/TODO.md, they're cleared.*

---

## [AI] /start 竞品调研 — 2026-03-01

调研对象：Open SWE (LangChain)、Kiro (AWS)、OpenHands、Anthropic long-running agent patterns

---

### 已验证的方向（我们做对了）

**Open SWE 的 Manager→Planner→Programmer→Reviewer 架构**，和我们的 `/start → /orchestrate → /loop → /verify` 完全同构。他们的 "Reviewer 把任务打回给 Programmer" = 我们的 verify-fail → 创建 fix tasks → re-loop。架构方向一致，验证正确。

**Kiro 的 steering files** 和我们的 CLAUDE.md 是同一个概念。AWS 单独把它做成产品核心功能。我们的 `# FROZEN` drift prevention 方向正确。

**Anthropic 的 claude-progress.txt 模式** = 我们的 PROGRESS.md 自动生成。他们也在做同样的 session 间状态传递，方向一致。

**Feature pass/fail markers**：Anthropic 建议维护一个 "features: passing/failing" 列表作为跨 session 的状态锚点。这正是我们计划的 `## Features (Behavior Anchors)` 章节 — 进一步确认这个设计是对的，/verify 跑完后应该更新这个列表的状态。

---

### 值得借鉴的新点

**[AI] 一次专注一个 feature（One at a time）**
Anthropic 明确建议："Agents are prompted to work on only one feature at a time"，避免 one-shot 全部。我们的 /loop 是多 worker 并行，更激进。但 /start overnight 的 supervisor 可以加一个 focus 策略：选优先级最高的未完成 feature，完整做完再推进下一个。防止同时推进 N 个 feature 导致互相干扰、测试失乱。

**[AI] 30s 计划审批窗口**
Open SWE 在执行前有人工 plan approval 步骤。我们的 overnight 模式直接跑，没有这个窗口。可以加：/start 写完 proposed-tasks.md 后打印计划、等待 30 秒（可 Ctrl+C 打断），超时自动继续。成本极低，但给人一个 last-chance 介入点，对建立信任有帮助。

**[AI] Session progress 文件**
Anthropic 建议每次 session 开始时写 `.claude/session-progress.md`（当前迭代做了什么、中断在哪），和 morning-review.md 不同 — 这是给 /pickup 用的实时状态，不是给人读的总结。可以在 /start 每轮迭代开始时更新这个文件，context 超限时 /handoff 把它带走。

---

### 我们的差异化优势（竞品没有的）

- **多 worker 并行** + git worktree 隔离：Open SWE 是单线程串行，我们是真并行
- **SQLite 持久化任务队列**：其他工具 session 结束任务就丢了
- **成本追踪 + budget cap**：没有竞品在 skill 层做这个
- **Loop 收敛检测**：其他工具靠人判断"做完了没"，我们有明确收敛条件
