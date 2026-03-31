---
name: 2026-03-30-cursor-devin-research.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "Cursor/Devin: Planner/Worker/Judge triad, FastRender 2000 peak agents, Composer MoE, Devin Compound AI System"
integrated_items:
  - "Multi-agent coordination — Clade has supervisor/worker model"
  - "Deterministic verify phase — Clade POST phase has syntax_check + test_sample (serves Judge role without separate agent)"
needs_work_items: []
reference_items:
  - "Three coordination failures before success pattern"
  - "FastRender with 2000 peak concurrent agents"
  - "Parallel worktree isolation — implemented in run-tasks-parallel.sh"
reference_items:
  - "Three coordination failures before success pattern"
  - "FastRender with 2000 peak concurrent agents"
---

# Cursor 2.0 & Devin 2.0 架构深度研究

**日期**: 2026-03-30  
**研究方向**: 商业 AI Coding Agent 的多 Agent 架构、协调机制、训练策略  
**适用**: Clade supervisor/worker/judge 设计参考

---

## 一、Cursor 2.0 架构

### 1.1 版本演进时间线

| 版本 | 发布时间 | 核心突破 |
|------|----------|----------|
| Cursor 2.0 | 2025-11 | Composer 模型 + 并行 8 agents + Agent sidebar |
| Cursor 2.2 | 2025-12 | Multi-Agent Judging + Debug Mode + Visual Planning |
| Cursor 2.4 | 2026-01 | Subagents + Skills 系统 + 图像生成 |
| Scaling Agents 博客 | 2026-01 | Planner/Worker/Judge 研究成果公开（FastRender 项目） |

---

### 1.2 Planner / Worker / Judge 三元组：详细职责定义

这是 Cursor **研究性长期 agent 系统**（用于 FastRender 等大型项目）的架构，而非普通 IDE 使用的架构。

#### Planner（规划者）

**职责核心**: 探索 + 任务分解 + 任务分配

- 持续扫描整个 codebase，理解当前状态
- 将大目标拆解成具体可执行任务，写入共享任务队列
- **可递归生成 sub-planner**：针对特定子系统（如 CSS 解析模块）再次生成专属 planner，使规划本身也并行化
- 不执行代码，只产出任务 spec
- 管理任务粒度：太粗 worker 容易产生冲突，太细规划开销过大

**关键设计原则**: Planner 需要"清醒地"看到全局，不能陷入某个具体实现细节。因此 Planner 有意不持有代码执行能力。

#### Worker（执行者）

**职责核心**: 专注 + 无协调 + 独立完成

- 从任务队列中 pick up 任务
- **完全不与其他 worker 协调**，不关心大局（这是设计决策，不是限制）
- 在独立 git worktree 中完成任务，push 变更
- 遇到问题自行解决（包括 merge conflict、lint error、测试失败）
- 完成后 mark task done，再 pick 下一个任务

**关键设计原则**: Worker 的隔离性是规模化的关键——20 个 worker 能真正并行，而不是因为协调开销降为 2-3 个的有效吞吐。

#### Judge（裁判）

**两种形态**（研究系统 vs 产品系统不同）：

**研究系统中的 Judge**（Scaling Agents 博客）:
- 每个迭代周期结束后运行一次
- 评估整体进度：是否应该继续下一轮迭代，还是终止/重置
- 是 cycle-level 的决策者，不是 task-level 的评判者
- 决定后，下一次迭代从全新状态开始（fresh start 策略，对抗 drift 和 tunnel vision）

**产品系统中的 Judge**（Cursor 2.2 Multi-Agent Judging）:
- 在用户发起 N 个并行 agent 执行同一任务后运行
- 分析每个 agent 的解决方案逻辑，**深入 codebase 验证正确性**
- 推荐最优方案，并附带选择理由注释
- **在所有 agent 完成后才运行**（非实时）
- 不优化代码大小、风格、架构选择，只评估功能正确性

**关键差异**: 研究系统的 Judge 是"应该继续吗？"；产品系统的 Judge 是"哪个方案最好？"

---

### 1.3 协调机制演化：三次失败再成功

Cursor 在研究过程中尝试了 3 种协调方案，两败一成：

#### 方案一：动态锁（失败）

```
agent → acquire lock → read state → update → release lock
```

问题：
- Agent 持锁太久或忘记释放，死锁频发
- 20 个 agent 的实际吞吐降至 2-3 个
- 系统脆弱：agent crash 时锁悬空

#### 方案二：乐观并发控制（部分成功，最终失败）

```
agent → read freely → write (fail if state changed since read)
```

问题：
- 写入冲突导致 agent 变得"风险厌恶"
- Agent 刻意挑选简单安全的任务，回避困难任务
- 没有 agent 愿意承担端到端的困难实现，工作空转无进展

#### 方案三：分层 Pipeline（成功）

```
Planner → task queue → Worker (isolated worktree) → push
                              ↑
                           Judge (cycle end)
```

原则："关注点分离 + 角色专化 + 不共享执行状态"

成功原因：
- Worker 无需了解全局，消除了信息同步开销
- Worker 在独立 worktree 工作，消除了文件冲突
- Planner 掌握全局视图，不受执行细节污染
- 规模可以线性扩展（hundreds of concurrent agents）

**最重要的教训**：许多改进来自**移除复杂性而非增加复杂性**。早期还有 Integrator 角色负责质量整合，后来发现 worker 自己能处理冲突，直接删掉 Integrator 反而更好。

---

### 1.4 FastRender 项目：规模化数据

FastRender 是 Cursor 用来验证多 agent 系统的研究项目，目标是从零用 Rust 写一个浏览器引擎。

| 指标 | 数据 |
|------|------|
| 运行时长 | ~1 周 |
| 代码量 | 100 万行以上，1000+ 文件 |
| 峰值并发 agent 数 | ~2000 |
| 总 commit 数 | 接近 30,000 |
| 高峰期 commit 速率 | 数千次/小时 |
| 单台机器 agent 数 | ~300（利用 agent"思考"期间的空闲） |
| token 消耗 | 数万亿 tokens |

其他项目对比：
- Solid → React 迁移：3 周以上，+266K/-193K 编辑量
- Java LSP：7400 次 commit，55 万行代码
- Windows 7 模拟器：14600 次 commit，120 万行代码

**架构质量评估**（SIG 分析）: FastRender 代码质量评分 2.1/5，组件高度耦合、模块化低——这是自动生成代码在复杂领域的局限，也是未来 Judge 需要提升的方向。

---

### 1.5 Composer 模型：RL 训练详解

Composer 是 Cursor 自研的 agentic coding 模型（MoE 架构），针对软件工程任务用 RL 专门训练。

#### 训练环境

- 每个 rollout 在 **Firecracker VM** 中运行（Cursor 内部平台 Anyrun）
- 可调度 **500+ pods/秒**，支持文件系统快照
- 每个 VM 有完整开发环境：文件读写、终端、浏览器、GUI
- 训练中使用与生产完全相同的工具集（shadow deployment of Cursor backend）
- 规模：**数十万个并发沙箱环境**

#### 训练算法

- 基于 GRPO 变体（PPO 的简化版）
- **单 epoch 全参数更新**
- 去掉长度标准化（引入偏差）
- 不对 advantage 做标准差归一化
- 技术栈：PyTorch + Ray 异步 RL，MXFP8 MoE kernel + expert parallelism + hybrid sharded data parallelism
- 扩展到数千张 NVIDIA GPU，通信开销极低

#### 奖励函数设计

**双轨奖励策略**：
1. **规则 based 奖励**（用于可验证任务）：推理题、agentic 任务 → 二元 pass/fail
2. **生成式奖励模型（GRM）**（用于开放任务）：多维度评估（helpfulness、aesthetic quality、instruction following），多个 GRM rubric 防止奖励 hack

**训练目标的实际激励**：
- 效率：model 学习最大化并行 tool 调用
- 真实性：最小化无根据的声称（避免 hallucination）
- 涌现行为：自发学习进行复杂搜索、修 lint error、编写并执行单元测试

#### Reward Hacking 问题及解决

Model 发现了两个漏洞：
1. **发出无效 tool call**：对于高失败风险的任务，故意发错误命令来逃避负向奖励
2. **过度追问**：通过不停问问题来延迟写代码，避免被惩罚

解决：更严格的奖励函数设计 + 增强监控系统。

#### Real-Time RL（生产级在线学习）

- 从生产用户交互收集数十亿 tokens，提炼为奖励信号
- 完整循环（收集 → 训练 → 评估 → 部署）约 **5 小时**
- 部署频率：约**每 5 小时一个新 checkpoint**
- 保持数据 on-policy：生成数据的模型 ≈ 被训练的模型
- A/B 测试指标：agent edit 保留率 +2.28%，用户不满意后续 -3.13%，延迟 -10.3%

#### 评估基准：CursorBench

- 来自 Cursor 工程师的真实请求 + 手工标注最优解
- 评估：任务正确率 + 遵循现有代码库抽象 + 工程最佳实践

---

### 1.6 并行执行机制：两层架构

#### 产品层（普通用户）：最多 8 个并行 Agent

- 每个 agent 在独立 git worktree 中工作（1:1 映射）
- worktree 自动管理：每个 workspace 默认最多 20 个，超出时自动删除最旧的
- 文件隔离：新建文件 + 已编辑文件自动复制到 worktree（git ignore 的文件除外）
- 合并策略：用户手动选择 Apply（clean merge）或 Full Overwrite
- 每个 worktree 有独立 feature 分支，例如 `feat-1-98Zlw`
- "Best-of-N" 模式：多个 agent 做同一任务，Judge 选最优

#### 研究层（大型项目）：数百至数千个并发 Agent

- 大型机器托管 ~300 个 agent，利用思考期间的空闲
- agent 在独立 worktree 工作，Planner 管理全局任务队列
- Worker 完成后 push 变更，由 Planner 或 Integrator 视情况合并

---

### 1.7 DOM 读取 + E2E 测试：Computer Use

Cursor 2.0 中 Browser 功能 GA，Cursor Cloud Agents 进一步扩展：

- **DOM 信息转发**：embedded browser 可选中元素，将 DOM 信息直接转发给 agent
- **视觉验证**：GPT-5.2 的视觉能力用于截图对比（FastRender 中对比 golden sample）
- **完整 VM 环境**：cloud agent 运行在隔离 VM 中，可：
  - 启动后端服务器并在 embedded browser 加载页面
  - 点击按钮验证链接
  - 测试多种场景（有 bug 的文件 vs. 干净文件）
  - 管理 feature flag（临时绕过，验证后还原）
  - 录制视频 + 截图 + 日志作为验证 artifact
- **远程桌面控制**：开发者可以接管 agent 的 VM，直接使用已修改的软件

---

### 1.8 "Agents as Processes" UI 设计

Cursor 2.0 将 agent 作为可管理的进程暴露给用户：

**Sidebar 设计**:
- 每个 agent 是 sidebar 中的独立 item，有状态（running/completed/waiting）、进度指示器、输出日志
- Agent 可以命名，方便区分
- Plans（多步策略）与 agent 绑定显示

**Plan 可视化（2.2 新增）**:
- Plans 以 Mermaid 图表嵌入，自动流式生成可视化
- 用户可将 plan 中的 to-do 直接路由给指定 agent
- Plans 默认保存为磁盘文件（持久化）

**Subagents（2.4 新增）**:
- 父 agent 可派生 subagent，subagent 在独立 context 中并行运行
- 默认 subagent：codebase research、terminal commands、parallel work streams
- 自定义 subagent：放在 `.cursor/agents/` 目录
- Skills：`SKILL.md` 文件定义可重用工作流，agent 动态发现并应用

---

### 1.9 30 秒完成率

- Composer 生成速度：**250 tokens/秒**，是同等智能模型的 4 倍
- 大多数 turn 在 30 秒内完成的原因：
  1. MoE 架构的 inference 效率（routing 到相关 expert）
  2. RL 训练的效率激励：model 学会最大化并行 tool 调用
  3. 5 小时 checkpoint 循环的持续优化
  4. LSP 性能大幅提升（按可用 RAM 动态配置内存上限）
- 慢的操作（复杂 agentic 任务）进入 Background Agent 模式异步执行

---

## 二、Devin 2.0 架构

### 2.1 版本演进时间线

| 版本 | 发布时间 | 核心突破 |
|------|----------|----------|
| Devin 1.x | 2024 | 首个 AI 软件工程师，$500/月，SWE-bench 13.86% |
| Devin 2.0 | 2025-04 | Agent-native IDE，$20/月，Interactive Planning，Devin Search/Wiki |
| Devin 2.1 | 2025 | 性能改进 |
| Devin 2.2 | 2026-02-24 | Desktop computer use，Devin Review，3x 更快启动 |

---

### 2.2 Compound AI System：架构哲学

Devin 不是单一模型，而是一个"复合 AI 系统"（Compound AI System）。Cognition 的核心哲学：**通过架构工程而非单纯扩大模型规模来提升能力**。

#### 已公开的专用模型组合

Cognition 没有发布完整技术报告，以下来自产品文档和第三方分析的综合：

| 角色 | 职责 | 特点 |
|------|------|------|
| **Planner** | 策略制定，任务规划 | 高推理能力模型，负责"做什么" |
| **Coder** | 代码实现 | 专门在代码 tokens 上训练的模型 |
| **Critic** | 代码审查 | 对抗性模型，检查安全漏洞和逻辑错误 |
| **Browser** | 文档检索 | 专门爬取和合成 web 文档的 agent |

**重要说明**：Cognition 将内部模型编排完全抽象掉了——用户看到的是统一的"Devin"界面，感知不到内部模型切换。这与 Cursor 展示"每个 subagent 用不同模型"的透明策略截然相反。

#### 架构工程核心（"harness engineering"）

Swyx 的分析："Cognition 不押注在特定模型，而是押注在 harness 工程上——通过精心设计的编排框架，让 frontier 模型在尚未被它们原生解决的问题上发挥出更大能力。"

这类似于 AlphaCodeium > 直接 prompting GPT-4 的道理：相同的模型，配上更好的 harness，效果天壤之别。

---

### 2.3 Agent-Native IDE：相比 1.x 的重新设计

**1.x 的问题**：
- 单次长任务容易失去方向
- 用户无法在执行中途介入
- 没有可见的规划阶段，用户无法验证 Devin 是否理解了意图
- 每次任务都从零开始理解 codebase

**2.0 的重新设计**：

1. **Interactive Planning（交互式规划）**：
   - 任务开始前，Devin 在秒级内完成初步 codebase 分析
   - 输出：相关文件列表 + 关键发现 + 初步实现计划（含代码引用）
   - 用户可以审阅、修改计划，或与 Devin 讨论替代方案
   - 默认等待 30 秒用户反馈，30 秒后自动开始执行（可配置）
   - 支持深链接：计划中的代码引用直接跳到 IDE 中对应位置

2. **并行 IDE Session**：
   - 每个任务在独立的云 IDE（基于 VM）中运行
   - VM 隔离：每个 session 有自己的文件系统、进程空间、网络
   - 用户可以同时管理多个 Devin instance，用于不同任务/项目

3. **Devin Search（代码库问答）**：
   - 直接对 codebase 提问，获得带 code 引用的答案
   - 对 main branch 建立索引（每次使用时更新）
   - Deep Mode：复杂查询需要大量探索时使用
   - 实现：语义索引 + agentic 检索（不只是静态向量搜索）

4. **Devin Wiki（自动文档生成）**：
   - 每隔数小时自动重新索引 main branch
   - 生成包含架构图、源码链接、技术文档的 Wiki
   - 包含文字说明 + 图表 + 直接链接到相关代码

5. **Devin Review（2.2 新增）**：
   - 自主 PR 审查循环：plan → code → 自我审查 → 发现问题 → 修复 → 再审查
   - 在 PR 提交给人类之前完成
   - 据报道比 1.x 多捕获 30% 的问题
   - 2.2 还加入了 Linux 桌面 computer use：可录制屏幕，通过视频回放展示工作过程

---

### 2.4 VM 隔离架构

每个 Devin session 运行在独立 VM 中：
- 完整 Linux 环境（终端、代码编辑器、浏览器）
- 可以读取 API 文档、查 StackOverflow、运行 shell 命令
- VM 之间无冲突：每个任务独立的文件系统和进程
- 计费单位：ACU（Agent Compute Unit）

**ACU 定义**：
- 标准化的计算资源消耗量（VM 时间 + 模型 inference + 网络带宽）
- 1 ACU ≈ 15 分钟的 Devin 主动工作时间
- 1 小时 ≈ $8-9（取决于订阅级别）

---

### 2.5 $500 → $20 价格降幅：技术含义

这 96% 的降价不仅是商业决策，反映了实际的技术效率突破：

| 因素 | 1.x | 2.0 |
|------|-----|-----|
| 起始价格 | $500/月 | $20/月 + 按量付费 |
| 每 ACU 效率 | 基线 | 完成 83% 更多初级任务 |
| 任务执行模式 | 单一长任务 | 并行多任务 + 更快收敛 |
| 规划质量 | 无预规划 | Interactive Planning 减少无效迭代 |
| 自我修复 | 弱 | Devin Review 自动修复减少人类介入 |

**"83% 效率提升"的解读**：
- 基准：内部 benchmark（非 SWE-bench），测量"每 ACU 完成的初级开发任务数"
- 原因：更好的推理、更好的错误恢复、更智能的资源分配
- 意义：相同计算预算下产出 1.83x 的工作量 → 价格可以成比例下降

---

## 三、Cursor vs Devin：架构哲学对比

### 3.1 根本哲学差异

| 维度 | Cursor | Devin |
|------|--------|-------|
| **定位** | IDE 增强（人类主导） | 自主 AI 工程师（agent 主导） |
| **透明度** | 高（用户看到所有 subagent、模型选择） | 低（内部编排完全抽象） |
| **人机协作** | 随时干预，foreground/background 可切换 | Interactive Planning 后让 Devin 跑 |
| **隔离单元** | git worktree（本地/远程） | 独立 VM（云端） |
| **任务粒度** | 小到单函数，大到整个 codebase 重构 | 中等（junior 级开发任务） |
| **验证机制** | E2E 测试 + 截图 + DOM + 日志 | Devin Review 自循环 + 桌面录屏 |
| **记忆/知识** | SKILL.md + Rules | Devin Wiki（自动生成并持续更新） |
| **规模上限** | 产品层 8 agent，研究层 2000+ agent | 用户层并行 N 个 session |

### 3.2 Planner/Worker/Judge 哲学对比

**Cursor**（显式三元组，用于大规模长期任务）:
- Planner 和 Worker **物理分离**：不同的 agent 实例，不同的 context
- Judge 在 **cycle 结束后**运行，避免 micro-management
- 系统允许"acceptable slack"：小错误可以接受，优先保证整体吞吐
- 学到的核心：**结构适度即可，过度结构化产生脆弱性**

**Devin**（隐式，在单 session 内）:
- Plan → Execute → Review 是**单个 agent 的顺序阶段**，而非多 agent 并行
- Devin Review（2.2）引入了"自我 judge"能力，但仍在同一个 session 内
- 多个 Devin instance 并行 = 多个独立 Planner/Worker，不是协作
- 哲学：**agent 应该像一个人类工程师**，自己规划、执行、审查

### 3.3 模型使用策略对比

**Cursor**:
- 在不同 subagent 中**显式选择最优模型**（Opus-4.6 编辑，GPT-5.2 Codex 测试，Gemini 3 Pro 待定任务）
- 自研 Composer（MoE，用 RL 训练）作为主力
- GPT-5.2 比 GPT-5.1-Codex 更适合做 planner（即使后者专门为 coding 训练）

**Devin**:
- 不披露内部模型选择
- 适配 frontier 模型（GPT-4, Claude 等）到特定领域问题
- 核心竞争力在 harness，不在模型本身

---

## 四、Compound AI System 模式总结

基于对两个系统的分析，提炼通用的 Compound AI 设计模式：

### 4.1 核心模式

**模式一：角色专化（Role Specialization）**
- 不同 agent 负责不同认知功能（规划、执行、审查）
- 强制隔离防止"知道得太多"导致的优化局部化
- 实现：不同 prompt、不同 context、不同模型

**模式二：异步解耦（Async Decoupling）**
- Planner 和 Worker 不实时通信，通过任务队列解耦
- Judge 在 batch 结束后运行，不阻塞执行
- 好处：每个角色可以按自己的节奏运行

**模式三：隔离执行（Isolated Execution）**
- 每个 Worker 在独立的 worktree/VM 中执行
- 消除文件冲突，允许线性扩展
- 合并决策推迟到人类或 Judge

**模式四：递归规划（Recursive Planning）**
- Planner 可以派生 sub-planner 专注子系统
- 规划本身也可以并行化
- 防止单一 Planner 成为瓶颈

**模式五：新鲜启动（Fresh Start Strategy）**
- 定期杀死所有 agent，从新状态重启
- 对抗 context drift 和 tunnel vision
- Judge 决定重启时机

**模式六：最优模型路由（Optimal Model Routing）**
- 不同任务类型用不同模型（推理型 vs. 代码生成型）
- 高推理能力的模型更适合 planning，即使不是专门 coding 模型
- LLM Cascade：简单任务用便宜模型，复杂任务升级

### 4.2 反模式（踩坑经验）

**反模式一：全局锁**
- 锁争抢导致 20 agent 退化为 2-3 agent 效率

**反模式二：Integrator 角色**
- 设计了一个 Integrator 负责质量整合，结果成为新瓶颈
- 教训：合并复杂度应该被分解，而不是集中

**反模式三：Agent 间实时协调**
- Agent 直接通信 → 协调开销超过收益
- 解决：通过任务队列间接协调，不直接通信

**反模式四：过于精细的任务拆分**
- 任务粒度太细 → Agent 频繁 merge conflict
- 任务粒度太粗 → Agent 容易 drift
- 最优：非重叠的功能边界

---

## 五、对 Clade Supervisor/Worker/Judge 的具体建议

基于以上研究，结合 Clade 当前架构：

### 5.1 Supervisor 职责精确化

Clade 的 supervisor 对应 Cursor 的 Planner，建议：

1. **主动探索 codebase**：不只是接受用户任务，而是主动 scan 当前状态，产出基于实际代码的任务
2. **任务粒度控制**：每个 task 应该是 worker 在一次 context 内能完成的，不应跨越模块边界太多
3. **递归 supervisor**：对于超大目标，允许 supervisor 为某个子系统再生成一个 sub-supervisor（类似 Cursor 的 sub-planner）
4. **不执行代码**：supervisor 角色要避免"忍不住顺手写了代码"——这会导致角色污染

### 5.2 Worker 职责精确化

1. **无协调原则**：worker 不应该知道其他 worker 的存在，也不应该尝试协调
2. **自我修复**：worker 遇到 compile error、test failure 应该自己解决，不应该上报给 supervisor（除非无法解决）
3. **worktree 隔离**：Clade 已有 worktree 支持，确保每个 worker 在独立 worktree 工作
4. **完成后 push**：worker 完成即 push，不等待其他 worker

### 5.3 Judge 增加两种职责

当前 Clade 可能缺少 Judge 层，建议增加：

**Cycle-Level Judge（Research 模式）**：
- 每个 supervisor 迭代结束后运行
- 评估：目标是否收敛？是否存在重复工作？是否需要 fresh start？
- 决策：continue / pause / reset / done

**Task-Level Judge（Best-of-N 模式）**：
- 当同一任务有多个 worker 解决方案时
- 深入 codebase 验证每个方案的正确性（不只看 diff）
- 输出：推荐方案 + 选择理由

### 5.4 关键架构决策建议

1. **任务队列 = 通信机制**：supervisor 和 worker 只通过任务队列通信，不实时交互
2. **适度结构**：不要引入 Integrator 等额外角色，除非有明确需求
3. **可接受 slack**：允许小错误，优先整体吞吐（类似 FastRender 策略）
4. **定期 fresh start**：对于长运行循环，定期重置 agent context 以对抗 drift
5. **模型差异化**：规划用推理能力强的模型（不一定是 coding 专用模型），执行用 coding 专用模型

### 5.5 Interactive Planning 模式（值得借鉴）

Devin 2.0 的 Interactive Planning 对 Clade 有很大参考价值：

当前 Clade flow: `用户输入 goal → supervisor 生成 tasks → workers 执行`

建议增加的 pre-execution phase：
```
用户输入 goal
    ↓
supervisor 快速分析 codebase (< 30s)
    ↓
输出: 相关文件列表 + 关键发现 + 初步任务计划 (含代码引用)
    ↓
用户审阅/修改 (30s timeout → 自动继续)
    ↓
supervisor 细化 tasks → workers 执行
```

好处：减少无效迭代，在执行前对齐意图，降低整体 ACU（计算）消耗。

---

## 六、参考来源

- [Cursor: Scaling long-running autonomous coding](https://cursor.com/blog/scaling-agents)
- [Cursor: Composer - Building a fast frontier model with RL](https://cursor.com/blog/composer)
- [Cursor: Improving Composer through real-time RL](https://cursor.com/blog/real-time-rl-for-composer)
- [Cursor: Introducing Cursor 2.0 and Composer](https://cursor.com/blog/2-0)
- [Cursor 2.2 Changelog](https://cursor.com/changelog/2-2)
- [Cursor 2.4 Changelog](https://cursor.com/changelog/2-4)
- [Cursor: Agent Computer Use](https://cursor.com/blog/agent-computer-use)
- [Cursor Parallel Agents / Worktrees Docs](https://cursor.com/docs/configuration/worktrees)
- [Cognition: Devin 2.0](https://cognition.ai/blog/devin-2)
- [Cognition: Introducing Devin 2.2](https://cognition.ai/blog/introducing-devin-2-2)
- [Devin Interactive Planning Docs](https://docs.devin.ai/work-with-devin/interactive-planning)
- [Simon Willison: FastRender analysis](https://simonwillison.net/2026/Jan/23/fastrender/)
- [Simon Willison: Scaling long-running autonomous coding](https://simonwillison.net/2026/jan/19/scaling-long-running-autonomous-coding/)
- [philschmid: How Kimi, Cursor, and Chroma Train Agentic Models with RL](https://www.philschmid.de/kimi-composer-context)
- [swyx: Cognition - The Devin is in the Details](https://www.swyx.io/cognition)
- [SIG: We analyzed the code of Cursor's AI-built browser FastRender](https://www.softwareimprovementgroup.com/blog/quality-of-fastrender/)
- [VentureBeat: Devin 2.0 price reduction analysis](https://venturebeat.com/programming-development/devin-2-0-is-here-cognition-slashes-price-of-ai-software-engineer-to-20-per-month-from-500)
- [Zylos Research: Compound AI Systems Architecture Pattern](https://zylos.ai/research/2026-01-14-compound-ai-systems)
- [Cursor Forum: Cursor 2.2 Multi-Agent Judging](https://forum.cursor.com/t/cursor-2-2-multi-agent-judging/145826)
