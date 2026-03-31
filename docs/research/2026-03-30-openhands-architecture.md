---
name: 2026-03-30-openhands-architecture.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "OpenHands: EventStream event sourcing, 9 Condenser types, DockerRuntime warm pool, AgentDelegate nested agents"
integrated_items:
  - "Event sourcing pattern — not implemented (Clade uses direct state updates)"
  - "Warm pool for agents — not implemented (Clade spawns fresh workers)"
needs_work_items:
  - "EventStream architecture — could replace direct state mutations in session.py"
  - "Condenser types for context compression — could enhance worker_tldr.py"
reference_items:
  - "9 Condenser types for different compression strategies"
  - "DockerRuntime with action_execution_server"
---

# OpenHands 深度架构研究

**Date**: 2026-03-30  
**Source**: https://github.com/OpenHands/OpenHands  
**Stars**: 70,000+ | **Funding**: $18.8M Series A (2025.11, Madrona)  
**Purpose**: 深入理解事件溯源架构和多 agent 协调，提炼可移植模式。

---

## 1. 项目概况

OpenHands（原 OpenDevin）是目前规模最大的开源 AI coding agent 平台。当前正处于 **V0 → V1 重大架构迁移**（V0 在 2026-04-01 删除）。

**核心用途**：dependency 升级、单测生成、merge conflict 解决、漏洞扫描。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    OpenHands 架构（2026.3）                       │
│                                                                 │
│  ┌─────────────────────── V1 SDK 层 ──────────────────────┐    │
│  │  openhands-sdk    openhands-tools    openhands-workspace │    │
│  │      │                  │                   │           │    │
│  │  Agent, LLM,       TerminalTool,       LocalWorkspace   │    │
│  │  Conversation,     FileEditorTool,     RemoteWorkspace  │    │
│  │  EventLog,         BrowserTool,        DockerWorkspace  │    │
│  │  Condenser,        TaskTrackerTool                      │    │
│  │  SubAgent Registry                                      │    │
│  │                                                         │    │
│  │  openhands-agent-server (FastAPI，跑在 sandbox 容器内)   │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                            │                                     │
│  ┌─────────────────────────▼──────────────────────────────┐     │
│  │           App Server (bridge 层)                        │     │
│  │  V1 conversation routing ↔ SDK conversations            │     │
│  └─────────────────────────┬──────────────────────────────┘     │
│                             │                                    │
│  ┌──────────────────────────▼────────────────────────────┐      │
│  │           Legacy V0 Server（scheduled for removal）    │      │
│  │  ConversationManager → AgentController → EventStream   │      │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ┌───────────────── Runtime Layer ──────────────────────┐       │
│  │  DockerRuntime → container + action_execution_server  │       │
│  │  RemoteRuntime → remote API → warm pool → container   │       │
│  │  LocalRuntime  → in-process (V1 default)              │       │
│  │  KubernetesRuntime → k8s pod                          │       │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ┌───────────────── Storage Layer ──────────────────────┐       │
│  │  FileStore (local / S3 / GCS)                         │       │
│  │  每个 event → <session_dir>/events/<id>.json           │       │
│  │  每 25 个 events 合并为 cache page                     │       │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 事件溯源架构 — 具体实现

### 3.1 Event 类型体系

```python
Event (base dataclass)
├── _id: int            # 全局单调递增
├── _timestamp: str     # ISO 格式
├── _source: EventSource   # AGENT / USER / ENVIRONMENT
├── _cause: int | None     # 链接 observation → 触发它的 action（因果图）
└── tool_call_metadata, llm_metrics, response_id

Action(Event)   — agent 想执行的操作
├── MessageAction          # 用户/agent 消息
├── CmdRunAction           # bash 命令
├── FileReadAction / FileWriteAction / FileEditAction
├── BrowseURLAction / BrowseInteractiveAction
├── IPythonRunCellAction
├── AgentDelegateAction    # ← 多 agent 协调核心
│   ├── agent: str         # 委托的 agent 类名
│   └── inputs: dict       # task 描述等
├── AgentFinishAction
├── RecallAction           # 触发 microagent 检索
├── CondensationAction     # 压缩历史 + 摘要
└── MCPAction              # MCP 工具调用

Observation(Event)  — 执行结果
├── CmdOutputObservation
├── FileReadObservation / FileEditObservation
├── AgentDelegateObservation   # 委托完成的结果
├── AgentCondensationObservation
├── ErrorObservation
└── RecallObservation          # microagent 检索结果
```

### 3.2 EventStream 结构

```
EventStream
├── 持久化层：FileStore（每事件一文件）
│   路径：<conversation_dir>/events/<id>.json
│   缓存：event_cache/<start>-<end>.json（每 25 个事件一页）
│
├── 内存层：_write_page_cache（当前未满的写页）
│
├── 订阅层：_subscribers: dict[subscriber_id, dict[callback_id, Callable]]
│   订阅者：AGENT_CONTROLLER / RUNTIME / SERVER / MEMORY / RESOLVER
│
├── 分发层：单独线程的 asyncio loop 跑 _process_queue()
│   - 事件进入 queue.Queue（线程安全）
│   - 按订阅者 key 排序后依次分发
│   - 每个 subscriber 有独立 ThreadPoolExecutor（max_workers=1）
│
└── 密钥脱敏：add_event() 中自动替换 secrets → '<secret_hidden>'
```

**关键保证**：`add_event()` 同步写文件后才入队，异步分发给订阅者。**持久化先于分发**，崩溃不丢事件。

### 3.3 Clean Replay

```python
# ReplayManager 管理轨迹回放：
ReplayManager(replay_events: list[Event])

# 控制循环中：
if replay_manager.should_replay():
    action = replay_manager.step()  # 按顺序返回下一个历史 Action
    # 直接执行，不调用 LLM
else:
    action = agent.step(state)  # 正常 LLM 推理
```

只重放 Action（用户的或 agent 的），Observation 由 runtime 重新生成（确定性动作结果相同）。

### 3.4 读取优化

```
搜索 1000 个事件 = 40 次文件读（每页 25 个）vs 1000 次文件读
search_events(start_id, end_id, filter) → Iterable[Event]
  ├── 按 cache_size=25 对齐找缓存页
  ├── 缓存命中 → 返回页内事件
  └── 未命中 → 单独读取 <id>.json
```

---

## 4. 多 Agent 协调 — AgentDelegate 详解

### 4.1 V0：树形嵌套 AgentController

```python
# 1. CodeActAgent 返回 AgentDelegateAction
action = AgentDelegateAction(agent="BrowsingAgent", inputs={"task": "..."})

# 2. AgentController 收到后创建子控制器：
async def start_delegate(self, action):
    state = State(
        start_id=event_stream.get_latest_event_id() + 1,  # 隔离起点
        delegate_level=self.state.delegate_level + 1,
        metrics=self.state.metrics,  # 共享全局 token metrics
    )
    self.delegate = AgentController(
        is_delegate=True,              # 不订阅 EventStream
        event_stream=self.event_stream  # 共享同一个 EventStream!
    )

# 3. Parent 收到事件时手动转发给 delegate：
def on_event(self, event):
    if self.delegate is not None:
        if delegate_state not in (FINISHED, ERROR):
            self.delegate._on_event(event)  # 手动转发
            return
        else:
            self.end_delegate()

# 4. Delegate 完成后：
def end_delegate(self):
    obs = AgentDelegateObservation(
        outputs=delegate.state.outputs,
        content="BrowsingAgent finishes task with ..."
    )
    event_stream.add_event(obs, EventSource.AGENT)
    self.delegate = None
```

**核心设计**：
- Parent 和 delegate **共享同一个 EventStream**
- Delegate 的事件 `start_id` 从 parent 最后事件之后开始 → **事件隔离**
- Delegate 不订阅 EventStream，由 parent 手动转发事件
- 全局 token metrics 在 parent/delegate 间**共享积累**
- 支持任意深度的委托树（`delegate_level` 递增）

### 4.2 V1：Sub-agent as Tool（更干净）

```markdown
# AgentDefinition（Markdown frontmatter 定义）
---
name: "WebResearcher"
description: "Search the web and summarize findings"
tools: ["browser", "file_editor"]
model: "inherit"
permission_mode: "never_confirm"
max_iteration_per_run: 20
---
You are a web research specialist...
```

Sub-agent 被实现为普通工具，继承 parent 的 workspace context，无需特殊框架。

---

## 5. SDK 四包职责

| 包 | 职责 | 关键类 |
|----|------|--------|
| `openhands-sdk` | 核心抽象，无重依赖 | Agent, Conversation, LLM, Tool, EventLog, Condenser |
| `openhands-tools` | 具体工具实现 | TerminalTool, FileEditorTool, BrowserTool, TaskTrackerTool |
| `openhands-workspace` | 执行环境抽象 | LocalWorkspace, RemoteWorkspace, DockerWorkspace |
| `openhands-agent-server` | FastAPI 沙盒服务器 | conversation_service, pub_sub, event_service |

**依赖 DAG（严格单向）**：
```
openhands-sdk (leaf)
    ↑
openhands-tools
    ↑
openhands-workspace ← openhands-agent-server
```

---

## 6. Runtime 与沙盒

| Runtime | 隔离方式 | 用途 |
|---------|---------|------|
| LocalRuntime | 无隔离（进程内） | 开发调试（V1 默认）|
| DockerRuntime | Docker 容器 | 本地生产 |
| RemoteRuntime | 远程容器（API 协调）| SaaS/企业 |
| KubernetesRuntime | k8s Pod | 大规模集群 |
| ModalRuntime | Modal serverless | Serverless |

**Docker Runtime 工作流**：
```
1. 构建镜像：base image + 用户代码 + action_execution_server
2. 启动容器，分配端口：
   - 30000-39999：执行端口
   - 40000-49999：VSCode Web
   - 50000-59999：App 端口
3. PortLock 文件锁防端口竞争
4. Runtime.on_event() 订阅 EventStream
5. 收到 Action → HTTP POST 到容器内 action_execution_server
6. 容器执行 → 返回 Observation → 写入 EventStream
```

---

## 7. Memory 系统

### 三层记忆架构

```
Level 1：EventStream（完整历史，永久持久化）
  - 所有事件永久保存，不因压缩删除
  - 从 LLM View 中隐藏，但始终存在于磁盘

Level 2：View（LLM 上下文窗口的视图）
  - State.view → View.from_events(history)
  - CondensationAction 指定哪些 event_ids 被"遗忘"
  - 遗忘的事件不传给 LLM，但在 EventStream 中永久存在
  - summary 插入到 View 的指定 offset 位置

Level 3：MicroAgents（项目知识注入）
  - .openhands/microagents/*.md（Markdown + frontmatter）
  - type: repo（项目知识）/ knowledge（触发词匹配）
  - RecallAction 触发检索 → RecallObservation 注入上下文
```

### Condenser 体系

```python
Condenser (abstract)
├── NoOpCondenser                    # 不压缩
├── RecentEventsCondenser            # 只保留最近 N 个事件
├── ObservationMaskingCondenser      # 压缩大型 observation 内容
├── BrowserOutputCondenser           # 专门压缩浏览器输出
├── AmortizedForgettingCondenser     # 渐进式遗忘
├── LLMSummarizingCondenser          # LLM 生成摘要（默认，2x cost reduction）
├── LLMAttentionCondenser            # 基于重要性选择保留
├── StructuredSummaryCondenser       # 结构化摘要
├── ConversationWindowCondenser      # 对话窗口截断
└── CondenserPipeline                # 组合多个 condenser
```

触发时机：检测到 token 超限 → 生成 CondensationAction 写入 EventStream → 下次 View 构建时自动排除被遗忘事件。

---

## 8. 架构演进

```
2024 早期：OpenDevin
  └── 单 agent，Docker 沙盒，基础事件流（研究原型）

2024 中：改名 OpenHands
  ├── 多 agent（AgentDelegate 嵌套）
  ├── BrowsingAgent
  └── MicroAgents 系统

2025 Q1-Q2：V0 成熟
  ├── 完整 EventStream + Condenser 体系
  ├── 企业版（Keycloak 路线图）
  └── Runtime API + Warm Pool

2025 Q3-Q4：V1 发布（software-agent-sdk）
  ├── 四包拆分，解耦核心/工具/沙盒/服务器
  ├── LocalConversation（无需 Docker）
  ├── Sub-agent as Tool（无特殊框架）
  ├── Pydantic frozen 事件（immutable + 类型安全）
  └── arXiv:2511.03690 论文发布

2026 Q1：V0 全面退出
  └── V0 标注 Legacy，April 1 删除
```

**V0 痛点 → V1 解法**：
- 必须 Docker → 可选隔离（LocalRuntime）
- 140+ 配置字段 → 简化配置
- 状态分散 → 单一可变状态（ConversationState）
- Sub-agent 需特殊框架 → 纯工具化

---

## 9. OpenHands Cloud 扩展架构

```
用户请求
    ↓
App Server（水平扩展，多实例）
  ├── OAuth GitHub 认证
  ├── SaaSConversationManager
  └── API Gateway

Runtime API Service（独立扩展）
  ├── Warm Pool（预热容器池，秒级分配）
  ├── 容器调度（按用户/组织隔离）
  └── 安全加固：sysbox / gVisor

Sandbox Containers（每 conversation 独立）
  ├── Agent Server（SDK V1）
  ├── Action Execution Server
  └── 用户 WebSocket 直连（bypass App Server）

Storage（用户隔离）
  ├── S3/GCS：EventStream 持久化
  └── PostgreSQL：用户/组织/配额管理
```

**关键扩展策略**：
- App Server 不在热路径 — 用户 WebSocket 直达 sandbox
- Warm Pool 解决冷启动（类似 Stripe Minions 的 EC2 预热池）
- sysbox/gVisor 作为 Docker 安全替代（容器内运行容器）

---

## 10. 与 Clade 的对比

### 相似处

| 维度 | OpenHands V0 | Clade |
|------|-------------|-------|
| 任务持久化 | FileStore + JSON | SQLite (tasks.db) |
| Worker 抽象 | AgentController | Worker class |
| 多 agent | AgentDelegate（嵌套） | SwarmManager（并行 worktrees）|
| 状态机 | AgentState enum | status 字符串 |

### OpenHands 更成熟的地方

| 维度 | OpenHands | Clade 现状 | 差距 |
|------|-----------|-----------|------|
| **事件溯源** | 全量不可变事件日志，因果链 | 依赖日志文件 | 大 |
| **崩溃恢复** | 从 EventStream 完全重放 | 重启丢失运行时状态 | 大 |
| **Context 管理** | 多层 Condenser，遗忘+摘要 | 无 | 大 |
| **安全** | SecurityAnalyzer，操作风险评分 | 无 | 中 |
| **沙盒** | Docker/gVisor 彻底隔离 | 依赖 claude 进程 | 中 |
| **Replay** | 完整轨迹回放 | 无 | 中 |

### Clade 的优势

| 维度 | Clade 做得好的地方 |
|------|-----------------|
| **Git 工作流** | committer 脚本，原子化提交；OpenHands 无内置 git 工作流 |
| **Loop 架构** | supervisor+worker 迭代收敛；OpenHands 单轮任务为主 |
| **成本控制** | 内置 budget gate；OpenHands 通过 LLM Proxy 控制 |

---

## 11. 可移植到 Clade 的具体模式

### 11.1 因果事件链（`_cause` 字段）

在 TaskQueue 中添加事件表，实现 action → observation 因果追踪：

```sql
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,   -- action / observation
    event_kind TEXT NOT NULL,   -- cmd_run / file_edit / finish / error
    source TEXT NOT NULL,       -- agent / user / environment
    cause_id INTEGER,           -- FK → 触发此事件的 action
    content TEXT,               -- JSON
    timestamp REAL,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (cause_id) REFERENCES task_events(id)
);
```

价值：追溯"为什么这个错误发生了"，完整的 action → observation → action 链条。

### 11.2 Condenser 模式（Context 管理）

```python
class SimpleCondenser:
    """当 history > N tokens 时，用 LLM 摘要替换旧事件"""
    
    def condense(self, events: list[dict]) -> list[dict]:
        if self._token_count(events) < self.threshold:
            return events
        recent = events[-self.keep_recent:]
        summary = self._summarize(events[:-self.keep_recent])
        return [{"type": "summary", "content": summary}] + recent
```

### 11.3 Replay / Checkpoint（从中途恢复）

```python
class TaskCheckpoint:
    """保存任务执行轨迹，支持从最后成功 action 继续"""
    
    def save(self, task_id: str, events: list[dict]) -> None:
        path = Path(f"~/.claude/checkpoints/{task_id}.json")
        json.dump(events, path.open("w"))
    
    def resume_from(self, task_id: str) -> list[dict] | None:
        path = Path(f"~/.claude/checkpoints/{task_id}.json")
        return json.load(path.open()) if path.exists() else None
```

### 11.4 Sub-agent Markdown 定义（增强 skill 路由）

V1 的 AgentDefinition 格式，可以用于增强 Clade skill 的自动路由：

```markdown
---
name: "CodeReviewer"
description: "Reviews code for bugs and security issues."
tools: ["file_editor", "terminal"]
model: "inherit"
permission_mode: "never_confirm"
max_iteration_per_run: 10
examples:
  - "review my PR"
  - "check this code for security issues"
---
You are a senior code reviewer...
```

### 11.5 PubSub 解耦（订阅者隔离）

```python
class PubSub(Generic[T]):
    """类型安全的发布订阅，每个 subscriber 独立失败不影响其他"""
    
    async def __call__(self, event: T) -> None:
        for sub_id, subscriber in list(self._subscribers.items()):
            try:
                await subscriber(event)
            except Exception as e:
                logger.error(f"Subscriber {sub_id} error: {e}")
                # 继续通知其他 subscriber
```

解耦：worker 状态变化 → WebSocket 推送 / GitHub 同步 / DB 更新 各自独立。

### 11.6 Worktree Warm Pool

```python
class WorktreePool:
    """预创建 N 个 worktree，任务到来时立即分配"""
    
    def __init__(self, project_dir: Path, pool_size: int = 3):
        self._available: asyncio.Queue[Path] = asyncio.Queue()
        asyncio.create_task(self._maintain_pool(pool_size))
    
    async def _maintain_pool(self, target_size: int):
        while True:
            for _ in range(target_size - self._available.qsize()):
                wt = await self._create_worktree()
                await self._available.put(wt)
            await asyncio.sleep(5)
    
    async def acquire(self) -> Path:
        return await self._available.get()
```

---

## 12. 核心设计哲学

1. **事件溯源 = 免费的调试 + 恢复能力**：所有状态变化都是事件，不用"记住"当前状态，随时从日志重建。Clade 目前状态在内存中，server 重启后运行中的 worker 状态丢失。

2. **订阅者隔离 = 可组合的副作用**：EventStream 的 subscriber 设计让 Runtime、Server、Memory 完全解耦，各自失败不影响对方。

3. **单一可变状态 + 纯工具化 sub-agent**（V1 原则）：ConversationState 是唯一 mutable 的，其他全 immutable。Sub-agent 不需要特殊框架，就是一个工具。测试极其简单。

---

## 参考来源

- https://github.com/OpenHands/OpenHands
- https://github.com/OpenHands/software-agent-sdk
- https://arxiv.org/abs/2511.03690
- https://openhands.dev/blog/automating-massive-refactors-with-parallel-agents
