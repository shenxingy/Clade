# Agentic Coding Landscape — 系统研究报告

**Date**: 2026-03-30  
**Scope**: AI Coding Agents 全景扫描 — 并行编排、框架、上下文管理、沙盒、MCP 生态  
**Purpose**: 提炼可借鉴模式，指导 Clade 下一阶段设计

---

## 概览：这个领域在发生什么

2025–2026 是 AI coding agents 从"有趣演示"到"生产基础设施"的临界点：

- Stripe Minions：每周合并 1,300+ AI 写的 PR，几乎零人工代码
- OpenHands：18.8M Series A，Fortune 500 客户大规模部署
- SWE-bench Verified 榜首：78.8%（Gemini 3.1 Pro Preview）
- E2B：每月 1500 万个沙盒 session（从 2024 年 3 月的 40k 增长 375 倍）
- MCP：从发布到 800 万次下载仅用 5 个月

**工程师的角色正在转变**：从写代码 → 协调代理。Multi-agent coordination 是新的 scalability 前沿。

---

## 第一章：并行 Agent 编排工具

### superset-sh/superset ★8,300
> "Code Editor for the AI Agents Era"

Electron 桌面应用，统一管理多个 AI coding agent（Claude Code、Codex、Gemini CLI、Cursor Agent、OpenCode、Copilot），每个 agent 跑在独立 git worktree 里。

**核心创新**：
- **Universal Hook Injection**：启动时自动 patch 所有 AI 工具的 hook 配置，全部指向本地同一 Express endpoint。用户零配置。
- **Shell Ready Marker**：注入 shell wrapper 等待 rc 加载完毕后再发命令，buffer 用户输入最多 15 秒
- **Server-side headless terminal emulator**：xterm 状态在 server 端维护，pane 切换瞬间恢复
- **Priority semaphore**：限制并发 attach 数 = 3，防止 daemon 过载

> 详见：`docs/research/2026-03-30-superset-sh-research.md`

---

### ComposioHQ/agent-orchestrator ★5,600

Fleet 管理工具，八个可插拔抽象槽：runtime（tmux/Docker）、agent（Claude Code/Codex/Aider）、tracker（GitHub/Linear）、SCM、通知、生命周期管理器。

**核心创新**：
- **Agent-agnostic, runtime-agnostic, tracker-agnostic** 三维解耦
- **CI 反馈闭环**：CI 失败时自动把日志注入回 agent session；agent 只有一次重试机会，第二次失败才升级人工
- 40k 行 TypeScript，3,288 个测试 — 大部分由它自己编排的 agent 写的

---

### Cursor 2.0 Multi-Agent（2025 年 10 月）

IDE 原生并行 agent 执行，最多 8 个同时运行。

**核心创新**：
- 自研 Composer 模型在 agent 环境中用 RL 训练，大多数 turn 在 30 秒内完成（比 1.x 快 4 倍）
- **Planner/Worker/Judge 三元组**：Planner 持续探索 codebase，Worker 并行执行不互相协调，Judge 决定是否继续
- DOM 读取 + E2E 前端测试在编辑器内直接运行，agent 可以验证自己的输出
- Sidebar 里 agent 作为"进程对象"可见

---

## 第二章：Agent 编码框架与运行时

### SWE-agent（Princeton/Stanford，NeurIPS 2024）
**GitHub**: https://github.com/SWE-agent/SWE-agent

提出 **Agent-Computer Interface (ACI)** 概念 — 专为 LLM 设计的命令集和反馈格式，用于浏览/查看/编辑/测试代码。

**核心洞察**：界面设计对 benchmark 性能的影响不亚于模型能力本身。

**配套产品**：
- **SWE-ReX**：快速、大规模并行代码执行后端
- **mini-swe-agent**：100 行 Python，只用 bash 工具（不用 tool-calling API），SWE-bench Verified 得分 >74%

> mini-swe-agent 的教训：激进的简单性 + 正确的 ACI 设计，能超越复杂框架。

---

### OpenHands（原 OpenDevin）★60,000+
**GitHub**: https://github.com/OpenHands/OpenHands  
**融资**: 1880 万美元 Series A（2025 年 11 月，Madrona 领投）

企业级开放平台，用于运行和扩展 coding agents。

**核心创新**：
- **事件溯源、无状态架构**：agent 状态与环境完全解耦
- **AgentDelegateAction**：任务自动交接 + 动态 agent 组合
- **OpenHands Cloud**：支持数千个并行 agent，含完整治理
- **组合式 Python SDK**：四个包 — SDK、Tools、Workspace、Server

常见用途：dependency 升级、单测生成、merge conflict 解决、漏洞扫描

---

### Devin 2.0（Cognition AI，2025 年 4 月）
**URL**: https://cognition.ai/blog/devin-2

从"自主软件工程师"重新定位为"agent-native IDE"。

**核心创新**：
- **复合 AI 系统**：多个专用模型协调工作流，而非单一大模型
- 每个任务一个独立 VM 的并行云 IDE session
- **Devin Search**：agentic codebase 探索，自动索引 repo 并生成架构 wiki
- 价格从 $500/月降至 $20/月（大规模普及的关键）
- 内部 benchmark：每 Agent Compute Unit 完成的初级任务量提升 83%

---

### OpenAI Codex CLI
**GitHub**: https://github.com/openai/codex

基于 Rust 的终端 coding agent。

**核心创新**：
- 自身暴露为 **MCP server** — 可被 Agents SDK 编排，形成多 agent pipeline
- 默认网络隔离沙盒（本地和云端均适用）
- 每个任务一个预加载了 repo 的云沙盒

---

### Gemini CLI（Google，2025 年 7 月）
**GitHub**: https://github.com/google-gemini/gemini-cli（Apache 2.0）

开源终端 agent，内置 Google Search grounding，1M token 上下文窗口。

**核心创新**：
- **Plan Mode**：只读规划阶段，在变更前明确计划
- ReAct 循环 + Google Search grounding 内置
- 与 Gemini Code Assist（VS Code 扩展）共享后端
- 免费额度：60 req/min，1,000 req/day
- MCP 支持通过 `~/.gemini/settings.json`

---

### Goose（Block/Square，2025 年 1 月）
**GitHub**: https://github.com/block/goose

Rust + Electron 的开源 agent 框架，Stripe Minions 基于其 fork 构建。

**核心创新**：
- **MCP-native 设计**：主要扩展机制就是 MCP servers，无专有插件格式
- 已捐赠给 Linux Foundation 的 **Agentic AI Foundation (AAIF)**（MCP 也归于此基金会）
- 引入 **`AGENTS.md`**：CLAUDE.md 的正式开放标准等价物

---

### AWS Kiro（2025）
**URL**: https://kiro.dev/

Spec 驱动的 agentic IDE，解决"vibe coding"的无结构问题。

**核心创新**：
- **三文件规范系统**：
  - `requirements.md`（EARS 格式用户故事）
  - `design.md`（架构设计）
  - `tasks.md`（依赖有序的任务清单）
- **Hooks**：文件保存等生命周期事件触发的轻量自动化
- 原生 AWS 服务集成，从 spec 生成 Lambda/S3/DynamoDB IaC

---

### Aider
**GitHub**: https://github.com/Aider-AI/aider

终端 AI pair programmer，深度 git 集成。

**核心创新**：
- **Repository Map**：函数签名 + 文件结构送给 LLM，实现全 codebase 感知
- 每次变更自动提交 + 描述性 commit message，`/undo` 回滚最近 commit
- **Architect Mode**：先讨论设计，再动文件
- 模型无关（GPT-4o、Claude、DeepSeek）

---

## 第三章：上下文管理策略

### Anthropic：有效上下文工程（2025 年 9 月）
> 把上下文当作有限资源，边际回报递减（"context rot"）。目标是最小化高信号 token 集合。

**五大模式**：

| 模式 | 描述 |
|------|------|
| **JIT 检索** | 上下文只放路径/URL，工具调用时再加载实际内容。永远不要预加载所有文件 |
| **结构化记录** | Agent 把信息写入上下文窗口外的持久存储，按需选择性读回 |
| **Compaction** | 压缩旧对话时保留架构决策和未解决问题 |
| **Sub-agent 委托** | 专用子 agent 处理聚焦任务，只返回压缩摘要给协调者 |
| **工具设计** | 非重叠工具集；工具返回 token 高效信息 |

---

### CLAUDE.md / AGENTS.md 模式

每轮都重新注入的系统 prompt，能在 compaction 中存活。

- **Claude Code**：自动重注入 CLAUDE.md、最近读取的文件、活跃 plan、已调用 skills
- **Stripe Minions**：**目录作用域 rule 文件** — agent 遍历文件系统时自动附加，避免单一全局 context 溢出
- **AGENTS.md（Block/Linux Foundation）**：正式开放标准等价物，目标是跨 Codex CLI/Gemini CLI/Goose 通用

---

### Amp/Sourcegraph：Handoff 取代 Compaction

**URL**: https://sourcegraph.com/amp

> OpenAI 内部发现自动 compaction 在 GPT-5 Codex 发布后导致性能持续衰减（2025 年 9 月）。

**解法**：`/handoff` 命令分析当前 thread，生成结构化 prompt 供下一阶段使用，然后开新 thread。

**核心洞察**：交接*下一个 agent 可以查询的结构化知识*，而非有损摘要。Thread Map 可视化追踪交接关系。

> Clade 的 `/handoff` skill 已经实现了这个模式 — 这是一个有意的架构选择，不只是技巧。

---

### Windsurf Cascade Memories

自动在对话间生成 memories；长周期任务的规划 agent 维护独立的长期 plan，执行模型处理短期动作。

---

## 第四章：Multi-Agent 协调模式

### Anthropic：构建有效 Agent（2024 年 12 月）

**核心分类**：

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| **Workflow** | 预定义代码路径编排 LLM | 可预测流程，需要确定性 |
| **Agent** | LLM 动态决定工具使用和流程 | 开放性任务 |
| **Orchestrator-Workers** | 中央 LLM 分解任务，委托 worker，综合结果 | 复杂多步骤任务 |
| **Parallelization** | 投票（同任务聚合）或分片（按领域拆分）| 需要并行性或多视角 |

**关键建议**：使用简单的可组合模式；除非确实需要特定抽象，否则避免复杂框架。

---

### OpenAI Agents SDK 两大协调模式

**Manager pattern（agents-as-tools）**：
```
中央 LLM
  ├─ call refund_agent()
  ├─ call order_agent()
  └─ synthesize results
```

**Decentralized handoffs**：
```
agent_A → transfer_to_agent_B (one-way)
agent_B → transfer_to_agent_C (one-way)
```
Handoff 被表示为 LLM 的工具调用（`transfer_to_refund_agent`）。

---

### LangGraph vs CrewAI

| 维度 | LangGraph | CrewAI |
|------|-----------|--------|
| 核心抽象 | 显式状态机（节点、边、状态 schema） | "Crew"——有角色的 agent 团队 |
| 控制粒度 | 高（开发者控制每个状态转移） | 低（框架管理协作） |
| 设置复杂度 | ~60 行 | ~20 行 |
| 适用场景 | 复杂分支业务逻辑、需要可调试性 | 角色协作为主轴的多 agent |

---

## 第五章：DevBox / 环境隔离

### Stripe Minions 的 DevBox 架构

> 每周 1,300+ PR，全部 AI 编写（2026 年初数据）

```
池化的暖 AWS EC2 实例（<10秒启动）
    ↓
完整源码树 + 预热的 Bazel + 类型检查缓存
    ↓
代码生成服务
    ↓
CI（最多 2 轮，无互联网访问，无生产访问）
```

**Blueprint 架构**：确定性节点（lint、push、format）+ Agentic 节点（"实现任务"、"修复 CI 失败"）的混合图。不是纯 workflow，不是纯 agent。

**CI 纪律**：agent 在 CI 失败后只有**一次重试**机会，第二次失败立即升级人工。防止无限修复循环。

**Toolshed**：内部中心化 MCP server，~500 个工具，覆盖所有内部系统和 SaaS 平台。Agent 按任务类型接收精选子集。

---

### E2B — AI Agent 云运行时

**GitHub**: https://github.com/e2b-dev

基于 **Firecracker microVM** 的云沙盒，SDK 优先（Python + JS）。

**增长**：40k session/月（2024.3）→ 1500 万 session/月（2025.3）= **375 倍**

**用户**：Claude Code、Codex、Cursor 团队都在用。约 50% 的 Fortune 500 运行 agent 工作负载通过 E2B。

---

### Firecracker microVM

**GitHub**: https://github.com/firecracker-microvm/firecracker

硬件级隔离（KVM）。冷启动 125ms，单台主机每秒最多 150 个 microVM。

**Microsandbox 创新**：通过 Firecracker 内存快照（snapshot-restore，非冷启动）实现 **28ms** 启动。

---

## 第六章：MCP 生态

### 协议现状

- Anthropic 2024.11 发布 → OpenAI（2025.3）、Google DeepMind、Microsoft、AWS 采用
- 现由 **Linux Foundation 的 Agentic AI Foundation (AAIF)** 治理（Goose 也归于此）
- 下载量：10 万（2024.11）→ 800 万（2025.4）

**2026 路线图**：传输层可扩展性、Agent-to-Agent (A2A) 通信、多模态（图片/视频/音频）、企业治理

---

### 关键 MCP Servers

| Server | 说明 |
|--------|------|
| **Stripe Toolshed** | ~500 个内部工具，规模最大的生产级 MCP 部署 |
| **Playwright/mcp-selenium MCP** | UI 测试工具，让 agent 可以测试前端变更 |
| **GitHub MCP** | Issues、PR、代码搜索；Copilot agent mode 使用 |
| **Codex CLI as MCP server** | Codex CLI 本身暴露为 MCP server，可被 Agents SDK 编排 |

---

### Toolshed 模式（最重要的 MCP 架构洞察）

中心化 MCP server 成为 agent 与整个内部工具生态系统的**统一接口**。Agent 不需要知道每个系统如何工作 — 它们只调用 MCP 工具。

**双向 MCP 架构**（Superset 的做法）：
- **出站**：agent 通过 MCP 工具使用外部系统
- **入站**：远端 AI agent 通过 MCP 控制本地 Superset 实例

---

## 第七章：关键论文与博文

### 论文

| 论文 | 核心贡献 |
|------|----------|
| **SWE-agent: ACI Enable Automated SE** (NeurIPS 2024) | 提出 ACI 概念；界面设计驱动 benchmark 性能超过模型大小 |
| **The OpenHands Software Agent SDK** (2025.11) | 事件溯源、组合式生产级 agent SDK 架构 |
| **Mem0: Production-Ready AI Agents with Scalable Long-Term Memory** (2025) | 外部 memory provider 实现零停机 context compaction |

### 重要博文

| 博文 | 来源 | 核心洞察 |
|------|------|----------|
| **Building Effective Agents** (2024.12) | Anthropic | 六种可组合 agent 模式；优先选简单 workflow 而非复杂框架 |
| **Effective Context Engineering for AI Agents** (2025.9) | Anthropic Engineering | Context 是稀缺资源；JIT 检索、compaction、结构化记录 |
| **Stripe Minions Part 2** (2026) | Stripe Dev Blog | Blueprint 混合模式；Toolshed MCP；cattle devboxes；2-strike CI 纪律 |
| **Eight Trends Defining How Software Gets Built in 2026** | Anthropic/Claude Blog | 工程师从写代码转向协调 agent；multi-agent coordination 是新 scale 前沿 |
| **Amp drops compaction for handoff** (2025) | Sourcegraph | 压缩导致性能漂移的证据；结构化交接是更优替代方案 |
| **Agentic Engineering Patterns** (2026.2) | Simon Willison | 社区总结的实用 agentic 模式目录 |

### SWE-bench 排行榜现状（2026.3）

| 模型 | SWE-bench Verified |
|------|-------------------|
| Gemini 3.1 Pro Preview | 78.8% |
| Claude Opus 4.6 Thinking | 78.2% |
| GPT-5 | 78.2% |
| mini-swe-agent（100行Python）| 74% |

> SWE-bench Pro（harder，训练截止后）：最强模型只有 ~23%。真实世界难度远高于 benchmark。

---

## 综合分析：可借鉴给 Clade 的模式

### 高优先级

| 模式 | 来源 | Clade 应用 |
|------|------|------------|
| **Blueprint 混合图** | Stripe Minions | 用确定性节点（lint、verify、format）+ Agentic 节点（实现、修 CI）替代纯 agent loop。loop-runner.sh 已部分实现这个思路，可以显式化 |
| **2-strike CI 纪律** | Stripe Minions | Agent 在 CI/verify 失败后只有一次重试；第二次失败记录到 blockers.md 并停止。防止无限修复循环 |
| **Universal Hook Injection** | Superset | 扩展 install.sh 支持 patch Gemini CLI、Codex、OpenCode 的 hook 配置，全部指向 Clade 本地端点 |
| **Toolshed MCP 模式** | Stripe | 将 Clade orchestrator 暴露为 MCP server：`create_task`、`list_tasks`、`get_worker_status`、`run_loop`，让其他 Claude Code 会话可以直接向 Clade 队列提交工作 |

### 中优先级

| 模式 | 来源 | Clade 应用 |
|------|------|------------|
| **Shell Ready Marker** | Superset | 替换 loop-runner.sh 里的 fixed sleep，注入 shell wrapper 等待 rc 加载完毕信号 |
| **目录作用域 rule 文件** | Stripe Minions | 项目子目录可以有自己的 rule 文件，agent 遍历时自动附加，避免一个 CLAUDE.md 溢出 context |
| **JIT 上下文检索** | Anthropic | 上下文只放文件路径，工具调用时再读内容。不要在 plan 文件里预加载代码片段 |
| **AGENTS.md 对齐** | Block/Linux Foundation | Clade 的 CLAUDE.md 惯例与 AGENTS.md 开放标准对齐，提升跨 agent 工具的可移植性 |
| **Planner/Worker/Judge 三元组** | Cursor FastRender | 当前 supervisor+worker 模式可扩展 Judge 角色：专门决定是否继续还是升级人工 |
| **Priority Semaphore** | Superset | WorkerPool 的 worktree 并发创建用优先队列 + 信号量，解决多 worker 同时 `git worktree add` 的竞争 |

### 长期方向

| 模式 | 来源 | 说明 |
|------|------|------|
| **Firecracker microVM 沙盒** | E2B / AWS | 完整硬件级隔离，28ms 启动。Clade 当前用 git worktree 隔离文件系统，这是更完整的执行环境隔离 |
| **事件溯源架构** | OpenHands | Agent 状态与环境完全解耦，clean replay 和 debug 能力。当前 SQLite 状态机可以往这个方向演进 |
| **Thread Map / 交接可视化** | Amp/Sourcegraph | Handoff 链可视化——当前 handoff 文件是线性的，图结构追踪更强大 |

---

## 关键洞察总结

1. **Git worktree 隔离是行业共识** — Superset、Cursor、Clade、ComposioHQ 独立收敛到了同一原语。

2. **Blueprint > 纯 Agent Loop** — 把可预测步骤（lint、format、push）设计成确定性节点，只有创造性工作才用 LLM 节点。Stripe 的 1,300+ PR/周就是靠这个做到的。

3. **ACI 设计 > 框架复杂度** — mini-swe-agent 100 行 Python + 只用 bash，打败了几乎所有复杂框架。界面设计是关键，不是行数。

4. **MCP 将成为双向标准** — 不只是 agent 使用工具的出站接口，也是外部系统控制 agent 的入站接口。Superset 和 Stripe 都在同时做两件事。

5. **Compaction 有损，Handoff 更好** — Amp 放弃 compaction 的实验性证据不是边缘案例，OpenAI 内部也发现了同样的性能漂移问题。Clade 的 `/handoff` skill 是正确方向。

6. **工具生态正在标准化** — MCP 从 Anthropic 专有协议演变为 Linux Foundation 开放标准，800 万次下载，Fortune 500 生产采用。基于 MCP 构建比基于专有 API 更有前途。

---

## 参考来源

- https://github.com/superset-sh/superset
- https://github.com/ComposioHQ/agent-orchestrator
- https://github.com/SWE-agent/SWE-agent
- https://github.com/SWE-agent/mini-swe-agent
- https://github.com/OpenHands/OpenHands
- https://github.com/openai/codex
- https://github.com/google-gemini/gemini-cli
- https://github.com/block/goose
- https://github.com/Aider-AI/aider
- https://github.com/firecracker-microvm/firecracker
- https://github.com/e2b-dev
- https://github.com/modelcontextprotocol/servers
- https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2
- https://www.anthropic.com/research/building-effective-agents
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://cognition.ai/blog/devin-2
- https://kiro.dev/
- https://sourcegraph.com/amp
- https://windsurf.com/cascade
- https://openai.github.io/openai-agents-python/
- https://langchain-ai.github.io/langgraph/
- https://arxiv.org/abs/2405.15793
- https://arxiv.org/abs/2511.03690
- https://arxiv.org/pdf/2504.19413
- https://simonwillison.net/2026/Feb/23/agentic-engineering-patterns/
- https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation
