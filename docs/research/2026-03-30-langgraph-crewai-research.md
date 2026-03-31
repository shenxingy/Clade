---
name: 2026-03-30-langgraph-crewai-research.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "LangGraph StateGraph checkpointing, CrewAI manager_llm, Send API for map-reduce, interrupt() for human-in-loop"
integrated_items:
  - "StateGraph checkpointing — Clade has loop checkpoint in loop-runner.sh (checkpoint after each phase, crash recovery)"
needs_work_items:
  - "Human-in-loop interrupt via interrupt() pattern — LangGraph interrupt() pauses graph for human review at breakpoints; Clade has no equivalent (runs fully autonomous)"
  - "Send API for map-reduce parallelism — could enhance worker pool dispatch (map-reduce pattern for parallel task results)"
reference_items:
  - "LangGraph interrupt() for breakpoint-based human review — not a gap (autonomous operation is a design choice)"
  - "Checkpointing with SQLite/Postgres for state persistence — Clade uses loop-runner.sh checkpoint, not a gap"
  - "CrewAI hierarchical process — not applicable (different agent team architecture)"
---

# LangGraph & CrewAI 深度研究报告

**Date**: 2026-03-30  
**Scope**: LangGraph（状态机多 agent）vs CrewAI（角色团队多 agent）架构深度解析  
**Purpose**: 理解两框架核心设计，提炼对 Clade supervisor/worker 模型的借鉴点

---

## 概览

| 维度 | LangGraph | CrewAI |
|------|-----------|--------|
| GitHub Stars | ~52,000 | ~45,900 |
| 版本 | v0.4.x | v1.10.1 |
| 核心抽象 | StateGraph + Nodes + Edges | Agent + Task + Crew + Flow |
| 编程模型 | **图论**：节点 + 边 + 共享状态 | **角色扮演**：人格 + 目标 + 团队 |
| 持久化 | 内置 Checkpointing（SQLite/Postgres） | LanceDB（向量记忆） + @persist |
| Human-in-Loop | 原生 `interrupt()` + Breakpoints | `human_input=True` on Task |
| 流式输出 | 7 种 stream_mode（values/updates/messages/custom/checkpoints/tasks/debug） | 有限支持 |
| 协议支持 | LangChain 生态深度绑定 | MCP + A2A（Google A2A 协议） |
| 学习曲线 | 陡峭（需理解图论概念） | 平缓（类比真实团队） |
| 生产 Token 成本 | ~$32/万请求 | ~$50/万请求（+56%） |

---

## 第一章：LangGraph 深度解析

### 1.1 状态机模型的核心设计

LangGraph 的核心哲学是：**把 LLM 应用建模成有向图（DAG）**。

- **Nodes（节点）** = 执行步骤，包含 agent 逻辑
- **Edges（边）** = 控制流，决定下一步走哪里
- **State（状态）** = 所有节点共享的数据结构，贯穿整个图的生命周期

每次图的执行周期称为一个 **super-step**：所有并行调度的节点同时运行，完成后产生一个 checkpoint。

### 1.2 StateGraph vs MessageGraph

| 特性 | StateGraph | MessageGraph |
|------|------------|--------------|
| 状态结构 | 用户自定义 TypedDict / Pydantic | 强制为 `list[BaseMessage]`（单一消息列表） |
| 适用场景 | 通用 agent 工作流，复杂多字段状态 | 纯对话 chatbot，只需消息历史 |
| 灵活性 | 高，可定义任意字段 | 低，仅追加消息 |
| 当前状态 | 推荐使用 | 已不推荐，用 `MessagesState` 替代 |

**MessageGraph 的后继者**是 `MessagesState`——一个内置 `messages: Annotated[list, add_messages]` 字段的 StateGraph 便利类：

```python
from langgraph.graph import MessagesState

class State(MessagesState):
    documents: list[str]  # 可在基础 messages 上添加额外字段
```

### 1.3 完整代码示例：核心用法

```python
from typing import Annotated, Literal
from typing_extensions import TypedDict
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command

# ─── 1. 定义 State Schema ───
class State(TypedDict):
    # 普通字段：新值直接覆盖旧值（默认 reducer）
    query: str
    
    # Annotated + operator.add：追加，不覆盖
    search_results: Annotated[list[str], add]
    
    # 消息历史：专用 add_messages reducer（处理 ID 去重）
    messages: Annotated[list, add_messages]
    
    # 最终输出
    final_answer: str

# ─── 2. 定义 Nodes ───
def search_node(state: State) -> dict:
    """执行搜索，返回部分状态更新（不需要返回完整 State）"""
    results = [f"Result for: {state['query']}"]
    return {"search_results": results}

def analyst_node(state: State) -> dict:
    """LLM 分析节点，可通过 interrupt() 请求人工确认"""
    answer = f"Analysis based on {len(state['search_results'])} results"
    return {"final_answer": answer}

def review_node(state: State) -> Command[Literal["revise_node", END]]:
    """人工审核节点，使用 Command 同时更新状态并控制路由"""
    approved = interrupt({
        "question": "Approve this analysis?",
        "draft": state["final_answer"]
    })
    if approved:
        return Command(goto=END)
    else:
        return Command(
            update={"final_answer": ""},
            goto="revise_node"
        )

def revise_node(state: State) -> dict:
    return {"final_answer": f"Revised: {state['query']}"}

# ─── 3. 条件路由函数 ───
def route_after_search(state: State) -> Literal["analyst_node", END]:
    if state["search_results"]:
        return "analyst_node"
    return END

# ─── 4. 构建图 ───
builder = StateGraph(State)

# 添加节点
builder.add_node("search_node", search_node)
builder.add_node("analyst_node", analyst_node)
builder.add_node("review_node", review_node)
builder.add_node("revise_node", revise_node)

# 添加边
builder.add_edge(START, "search_node")
builder.add_conditional_edges("search_node", route_after_search)
builder.add_edge("analyst_node", "review_node")
builder.add_edge("revise_node", "review_node")

# ─── 5. 编译（必须）───
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")

graph = builder.compile(checkpointer=checkpointer)

# ─── 6. 执行 ───
config = {"configurable": {"thread_id": "session-001"}}

result = graph.invoke(
    {"query": "LangGraph architecture"},
    config=config
)

# 检查是否有 interrupt 待处理
if "__interrupt__" in result:
    print("Interrupted:", result["__interrupt__"])
    # 人工确认后恢复执行
    result = graph.invoke(Command(resume=True), config=config)
```

### 1.4 Map-Reduce 模式：Send API

用于动态扇出（fan-out）场景：

```python
from langgraph.types import Send

def generate_topics(state: State) -> list[Send]:
    """并行处理多个主题"""
    return [
        Send("process_topic", {"topic": t})
        for t in state["topics"]
    ]

builder.add_conditional_edges("generate_topics_node", generate_topics)
```

### 1.5 Persistence / Checkpointing

每个 super-step 后自动保存快照：

```python
# SQLite — 本地开发/实验
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("dev.db")

# Postgres — 生产推荐
from langgraph.checkpoint.postgres import PostgresSaver
checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@localhost/db"
)

# InMemory — 测试专用
from langgraph.checkpoint.memory import MemorySaver
checkpointer = MemorySaver()
```

**Checkpoint 数据结构**（`StateSnapshot`）：

| 字段 | 内容 |
|------|------|
| `values` | 当前通道状态 |
| `next` | 下一个将执行的节点 |
| `config` | thread_id + checkpoint_id |
| `metadata` | step 序号、写入记录 |
| `created_at` | ISO 8601 时间戳 |
| `parent_config` | 上一个 checkpoint 的 config |

**时间旅行**（调试利器）：

```python
# 获取完整历史
history = list(graph.get_state_history(config))

# 从任意历史点重放
past_config = history[2].config
result = graph.invoke(None, config=past_config)

# 修改过去的状态再重放
graph.update_state(past_config, {"query": "new query"})
result = graph.invoke(None, config=past_config)
```

**跨线程记忆**（Memory Store）：

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore(
    index={
        "embed": init_embeddings("openai:text-embedding-3-small"),
        "dims": 1536,
    }
)
graph = builder.compile(checkpointer=checkpointer, store=store)

# 在节点内使用 store
def personalized_node(state: State, runtime: Runtime):
    namespace = ("user", state["user_id"], "preferences")
    memories = await runtime.store.asearch(namespace, query=state["query"])
    return {"context": [m.value for m in memories]}
```

### 1.6 Human-in-the-Loop

**`interrupt()` 函数**（推荐方式）：

```python
from langgraph.types import interrupt

def human_review_node(state: State):
    # 执行暂停，向调用方返回 payload
    decision = interrupt({
        "content": state["draft"],
        "instruction": "Review and approve or reject"
    })
    # 恢复后，decision 是 Command(resume=...) 中传入的值
    return {"approved": decision, "draft": state["draft"]}
```

**Breakpoints**（静态断点，适合调试）：

```python
# 编译时设置
graph = builder.compile(
    interrupt_before=["dangerous_node"],   # 节点执行前暂停
    interrupt_after=["data_node"],          # 节点执行后暂停
    checkpointer=checkpointer,
)

# 运行时设置（同等效果）
graph.invoke(inputs, interrupt_before=["dangerous_node"], config=config)
```

**interrupt() 关键规则**：
1. 必须配合 checkpointer 使用
2. interrupt 的 payload 必须 JSON 可序列化
3. 恢复时整个节点从头重跑（interrupt 之前的代码必须是幂等的）
4. 不能放在 try/except 里
5. 同一节点内多次 interrupt，每次恢复时之前的 interrupt 按顺序重放

### 1.7 Streaming

7 种流式模式：

| 模式 | 内容 | 用途 |
|------|------|------|
| `values` | 每步后的完整状态快照 | 监控整体进度 |
| `updates` | 仅变更的状态键 | 增量 UI 更新 |
| `messages` | LLM token 逐字流出 + 元数据 | 实时文字输出 |
| `custom` | `get_stream_writer()` 自定义数据 | 任意中间结果 |
| `checkpoints` | checkpoint 事件 | 调试持久化 |
| `tasks` | 任务开始/结束事件 | 工作流监控 |
| `debug` | checkpoints + tasks + 额外元数据 | 深度调试 |

```python
# 流式 LLM token
for chunk in graph.stream(inputs, stream_mode="messages", version="v2"):
    if chunk["type"] == "messages":
        token, metadata = chunk["data"]
        print(token.content, end="", flush=True)

# 多模式同时流
for chunk in graph.stream(
    inputs,
    stream_mode=["updates", "custom"],
    version="v2"
):
    if chunk["type"] == "updates":
        print("State update:", chunk["data"])
    elif chunk["type"] == "custom":
        print("Custom event:", chunk["data"])

# 自定义数据发送
from langgraph.config import get_stream_writer

def my_node(state: State):
    writer = get_stream_writer()
    writer({"progress": "50%", "status": "processing"})
    return {"result": "done"}
```

### 1.8 Subgraphs

两种嵌套模式：

**模式 A：共享 State Key（直接作为 node 添加）**

```python
# 父子 State 有相同的 key（如 "messages"）
builder.add_node("subgraph_node", compiled_subgraph)
```

**模式 B：不同 State Schema（通过包装函数转换）**

```python
def call_subgraph(state: ParentState) -> dict:
    # 把父 State 的字段映射成子图的输入
    subgraph_out = subgraph.invoke({"bar": state["foo"]})
    # 把子图输出映射回父 State
    return {"foo": subgraph_out["bar"]}

builder.add_node("subgraph_node", call_subgraph)
```

子图的三种持久化模式：
- 默认（per-invocation）：每次调用从头开始，继承父图的 checkpointer
- `checkpointer=True`（per-thread）：跨调用累积状态
- `checkpointer=False`（stateless）：无持久化，不支持 interrupt

### 1.9 LangGraph Platform（托管服务）

> 2025 年 10 月起改名为 LangSmith Deployment

**超出开源库的额外能力**：

| 能力 | 描述 |
|------|------|
| 1-Click 部署 | GitHub 集成，从仓库直接部署 |
| 后台长任务 | 支持跑小时级 agent，不用保持连接 |
| 横向扩缩容 | 处理突发流量，自动扩容 |
| 内置持久化 | 无需自搭 Postgres，平台托管 checkpointing |
| LangGraph Studio | 可视化 agent 轨迹，断点调试，分支重放 |
| 30+ REST APIs | 用于构建自定义 UI / 集成外部系统 |
| Double-texting 处理 | 用户在 agent 未完成时再次发送消息的处理策略 |
| 部署选项 | Cloud SaaS / Hybrid / Self-hosted 三种 |

---

## 第二章：CrewAI 深度解析

### 2.1 三层抽象：Agent / Task / Crew

```
Crew（团队） ← 协调整体目标
  └── Task（任务） ← 具体工作单元，分配给特定 Agent
        └── Agent（智能体） ← 执行者，有角色/目标/工具
```

**关系规则**：
- 一个 Crew 包含多个 Agent 和多个 Task
- 每个 Task 通常分配给一个特定 Agent
- Task 可以通过 `context` 参数声明对其他 Task 的依赖
- Crew 的 `process` 决定 Task 如何被执行

**Agent 核心属性**：

```python
from crewai import Agent
from crewai_tools import SerperDevTool, WebsiteSearchTool

researcher = Agent(
    # 三个必填的"人格"字段
    role="Senior AI Researcher",
    goal="Uncover breakthrough developments in {topic}",
    backstory="""You're a renowned researcher with 15 years of experience
                 in machine learning and NLP. You have a talent for finding
                 the most impactful papers and distilling key insights.""",
    
    # 工具（可以在 task 级别覆盖）
    tools=[SerperDevTool(), WebsiteSearchTool()],
    
    # LLM 配置
    llm="gpt-4o",                      # 或 "claude-3-5-sonnet"
    function_calling_llm="gpt-4o-mini", # 更便宜的模型用于工具调用
    
    # 执行控制
    max_iter=20,           # 最大迭代次数（默认 20）
    max_execution_time=300, # 超时秒数
    max_rpm=10,            # 速率限制
    max_retry_limit=2,     # 出错重试次数
    
    # 高级功能
    allow_delegation=True,  # 允许把子任务委托给其他 agent
    memory=True,            # 维护跨任务记忆
    reasoning=True,         # 执行前先做规划（ReAct 风格）
    allow_code_execution=True,  # 启用代码执行
    code_execution_mode="safe", # "safe"=Docker, "unsafe"=直接执行
    
    verbose=True
)
```

**Task 核心属性**：

```python
from crewai import Task
from pydantic import BaseModel

class ResearchOutput(BaseModel):
    summary: str
    key_findings: list[str]
    sources: list[str]

research_task = Task(
    description="""Research the latest developments in {topic} from 2025-2026.
                   Focus on practical applications and benchmark results.""",
    expected_output="A structured research summary with key findings and sources",
    
    # 分配给特定 agent
    agent=researcher,
    
    # 工具（覆盖 agent 的默认工具）
    tools=[SerperDevTool()],
    
    # 依赖其他 task 的输出作为 context
    context=[],  # 填入其他 Task 对象
    
    # 异步执行（不阻塞后续任务）
    async_execution=False,
    
    # 输出类型
    output_pydantic=ResearchOutput,  # 强类型输出
    output_file="research.md",       # 同时保存到文件
    markdown=True,                   # 要求 Markdown 格式
    
    # 输出验证
    guardrail="Must contain at least 5 key findings",
    guardrail_max_retries=3,
    
    # 需要人工审核
    human_input=True,
    
    # 完成后回调
    callback=lambda output: print(f"Task done: {output.raw[:100]}")
)
```

### 2.2 完整 Crew 代码示例

```python
from crewai import Agent, Task, Crew, Process
from crewai.project import CrewBase, agent, task, crew, before_kickoff
from crewai_tools import SerperDevTool
from langchain_openai import ChatOpenAI
from datetime import datetime

# ─── YAML 配置方式（推荐生产使用） ───
# 在 config/agents.yaml:
# researcher:
#   role: "{topic} Research Analyst"
#   goal: "Uncover latest developments in {topic}"
#   backstory: "..."

@CrewBase
class ResearchWritingCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @before_kickoff
    def prepare_inputs(self, inputs):
        inputs["timestamp"] = datetime.now().isoformat()
        return inputs

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["researcher"],
            tools=[SerperDevTool()],
            verbose=True
        )

    @agent
    def writer(self) -> Agent:
        return Agent(
            config=self.agents_config["writer"],
            verbose=True
        )

    @task
    def research_task(self) -> Task:
        return Task(config=self.tasks_config["research"])

    @task
    def write_task(self) -> Task:
        return Task(
            config=self.tasks_config["writing"],
            context=[self.research_task()],  # 依赖 research 完成
            output_file="output/article.md"
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,  # 顺序执行
            memory=True,
            verbose=True,
            output_log_file="logs/execution.json"
        )

# ─── 代码方式（灵活调试） ───
def build_analysis_crew_hierarchical():
    """Hierarchical: manager 自动分配和验证任务"""
    data_analyst = Agent(
        role="Data Analyst",
        goal="Provide accurate statistical analysis",
        backstory="Expert in quantitative analysis",
        verbose=True
    )
    
    qa_validator = Agent(
        role="QA Engineer",
        goal="Validate analysis for correctness",
        backstory="Meticulous quality assurance specialist",
        verbose=True
    )
    
    analyze_task = Task(
        description="Analyze the sales dataset",
        expected_output="Statistical report with key metrics",
        agent=data_analyst
    )
    
    validate_task = Task(
        description="Validate the analysis report",
        expected_output="Validation report with approval status",
        agent=qa_validator,
        context=[analyze_task]
    )
    
    return Crew(
        agents=[data_analyst, qa_validator],
        tasks=[analyze_task, validate_task],
        process=Process.hierarchical,
        manager_llm=ChatOpenAI(model="gpt-4o"),  # hierarchical 必填
        verbose=True
    )

# 执行
crew = ResearchWritingCrew().crew()
result = crew.kickoff(inputs={"topic": "LangGraph architecture"})
print(result.raw)
print(f"Token usage: {result.token_usage}")
```

### 2.3 Process 类型详解

| Process | 执行方式 | Manager | 适用场景 |
|---------|----------|---------|----------|
| `sequential` | Task 按列表顺序逐一执行 | 无 | 线性流水线（研究→写作→审校） |
| `hierarchical` | Manager LLM 自动分配任务，验证后才推进 | 必须提供 `manager_llm` | 复杂业务流，需要质量控制 |

> **Consensual Process**：文档中曾提及但尚未正式发布，未进入稳定 API。

**Hierarchical 的实际工作流**：
1. Manager LLM 接收整体目标
2. 分析所有 Agent 的能力（role/goal）
3. 将 Task 委托给最合适的 Agent
4. Agent 完成后，Manager 验证结果质量
5. 如不满足，要求重做；满足则推进到下一个 Task

### 2.4 Memory 系统

CrewAI v1.x 将记忆统一为单一 `Memory` 类，通过 **LLM 自动分析**决定内容的存储位置（scope）和重要性权重。

**存储层次**：

```
/（根）
  /agent/researcher      ← agent 私有记忆
  /agent/writer
  /project/current       ← 项目共享知识
  /company/knowledge     ← 组织级持久知识
```

**配置示例**：

```python
from crewai.memory import Memory

# 快速原型：默认配置（OpenAI embeddings + LanceDB 本地存储）
crew = Crew(agents=[...], tasks=[...], memory=True)

# 生产配置：自定义权重 + 本地 LLM（完全私有）
memory = Memory(
    llm="ollama/llama3.2",   # 本地 LLM 做分析
    embedder={
        "provider": "ollama",
        "config": {"model_name": "mxbai-embed-large"}
    },
    # 调整检索权重
    semantic_weight=0.5,     # 语义相似度
    recency_weight=0.3,      # 时间衰减
    importance_weight=0.2,   # 重要性评分
    recency_half_life_days=30,
    consolidation_threshold=0.85  # 超过此相似度自动去重
)

crew = Crew(agents=[...], tasks=[...], memory=memory)
```

**记忆检索深度**：
- `depth="shallow"`：纯向量搜索（~200ms，无 LLM 调用）
- `depth="deep"`（默认）：多步智能检索（LLM 分析查询意图）

### 2.5 Flows：新一代编排层

> Flows 是 2024 年底引入的**事件驱动工作流层**，定位在 Crew（团队执行）之上。

**Flow vs Crew 的关系**：

```
Flow（流程控制层）
  ├── @start()  → 定义入口点
  ├── @listen() → 监听其他方法完成
  ├── @router() → 条件路由
  └── Crew.kickoff()  ← Flow 内部调用 Crew 处理复杂子任务
```

**完整 Flow 示例**：

```python
from crewai.flow.flow import Flow, listen, start, router, or_, and_
from crewai import Crew, Agent, Task
from pydantic import BaseModel

class ResearchState(BaseModel):
    query: str = ""
    research_complete: bool = False
    quality_score: float = 0.0
    final_report: str = ""

class ResearchFlow(Flow[ResearchState]):
    
    @start()
    def validate_input(self):
        """入口：验证输入"""
        if len(self.state.query) < 10:
            self.state.query = f"Detailed research on: {self.state.query}"
        return self.state.query
    
    @listen(validate_input)
    def run_research_crew(self, query: str):
        """调用 Crew 执行具体研究任务"""
        crew = build_research_crew()
        result = crew.kickoff(inputs={"query": query})
        self.state.final_report = result.raw
        self.state.quality_score = self._score_quality(result.raw)
        return result.raw
    
    @router(run_research_crew)
    def quality_gate(self) -> str:
        """质量路由：高质量直接发布，低质量重新研究"""
        if self.state.quality_score >= 0.8:
            return "publish"
        elif self.state.quality_score >= 0.5:
            return "enhance"
        else:
            return "retry"
    
    @listen("publish")
    def publish_report(self):
        print(f"Publishing: {self.state.final_report[:100]}")
        self.state.research_complete = True
    
    @listen("enhance")
    def enhance_report(self):
        """低于 0.8 但高于 0.5：补充增强"""
        self.state.final_report += "\n\n[Enhanced with additional context]"
        self.state.research_complete = True
    
    @listen("retry")
    def retry_research(self):
        """质量太低：扩展 query 重试"""
        self.state.query = f"Comprehensive and detailed: {self.state.query}"
        return self.validate_input()  # 重新触发流程
    
    def _score_quality(self, report: str) -> float:
        return min(len(report) / 1000, 1.0)

# 执行 Flow
flow = ResearchFlow()
flow.state.query = "LangGraph production patterns"
result = flow.kickoff()
print(f"Complete: {flow.state.research_complete}")

# 持久化：自动从上次中断处恢复
from crewai.flow.flow import persist

@persist
class PersistentFlow(Flow[ResearchState]):
    pass  # 状态自动保存到 SQLite
```

### 2.6 工具系统

```python
from crewai.tools import BaseTool, tool
from pydantic import BaseModel, Field

# ─── 方式 1：@tool 装饰器（简单函数） ───
@tool("Search Wikipedia")
def wikipedia_search(query: str) -> str:
    """Search Wikipedia for information about a topic."""
    import wikipedia
    return wikipedia.summary(query, sentences=3)

# ─── 方式 2：BaseTool 子类（复杂工具，有类型验证） ───
class DatabaseQueryInput(BaseModel):
    sql: str = Field(..., description="SQL query to execute")
    limit: int = Field(default=100, description="Max rows to return")

class DatabaseQueryTool(BaseTool):
    name: str = "Database Query"
    description: str = "Execute SQL queries against the production database"
    args_schema: type[BaseModel] = DatabaseQueryInput
    
    def _run(self, sql: str, limit: int = 100) -> str:
        # 执行逻辑
        return f"Executed: {sql} (limit={limit})"
    
    # 智能缓存：只缓存 SELECT 语句
    def cache_function(self, args, result):
        return args.get("sql", "").strip().upper().startswith("SELECT")

# ─── 工具共享 ───
# 工具可以在多个 agent 之间共享（引用同一实例）
search = SerperDevTool()

researcher = Agent(role="...", tools=[search, DatabaseQueryTool()])
analyst = Agent(role="...", tools=[search])  # 同一 search 实例

# ─── 与 LangChain 工具的关系 ───
# CrewAI 原生支持导入 LangChain tools：
from langchain.tools import DuckDuckGoSearchRun
langchain_tool = DuckDuckGoSearchRun()
agent = Agent(role="...", tools=[langchain_tool])  # 直接传入，自动适配
```

### 2.7 A2A 协议支持

CrewAI 将 Google A2A（Agent-to-Agent）协议作为一级原语，支持跨框架 agent 委托。

```python
from crewai import Agent
from crewai.a2a import A2AClientConfig, A2AServerConfig

# ─── 客户端：委托给远程 agent ───
remote_specialist = Agent(
    role="Remote Specialist",
    goal="Handle specialized tasks via A2A",
    backstory="External specialist agent",
    a2a_client_config=A2AClientConfig(
        endpoint="https://specialist.example.com/.well-known/agent-card.json",
        timeout=120,
        max_turns=10,
        fail_fast=False,
        # 认证
        auth={"type": "bearer", "token": os.getenv("SPECIALIST_TOKEN")}
    )
)

# ─── 服务端：暴露当前 agent 为 A2A 服务 ───
my_agent = Agent(
    role="Data Analyst",
    goal="Provide data analysis as a service",
    backstory="Expert analyst available via A2A",
    a2a_server_config=A2AServerConfig(
        name="DataAnalystAgent",
        version="1.0.0",
        skills=["data_analysis", "visualization", "statistics"]
    )
)
# 同时配置 client + server：该 agent 既能委托出去也能接受委托
```

---

## 第三章：横向对比

### 3.1 核心哲学差异

| 维度 | LangGraph | CrewAI |
|------|-----------|--------|
| **比喻** | 流程图设计师 | 团队经理 |
| **思维模型** | 节点 + 边 + 状态流 | 角色 + 目标 + 任务分工 |
| **控制力** | 极高（完全显式控制每步） | 中等（框架自动协调） |
| **灵活性** | 任意拓扑（DAG/循环/并行） | Sequential 或 Hierarchical |
| **上手速度** | 慢（需理解图论抽象） | 快（类比真实团队） |
| **调试可观测性** | 极高（完整 checkpoint 历史，时间旅行） | 低（只有 stdout 日志） |
| **Token 效率** | 高（状态 schema 精确控制传递内容） | 低（每 agent 携带完整 system prompt） |
| **生态依赖** | 深度依赖 LangChain | 相对独立（支持 LangChain tools） |
| **协议支持** | 无原生 MCP/A2A | MCP + A2A 原生支持 |

### 3.2 性能数据对比

```
场景：3 agent 并行任务，各输出 500 token

延迟：
  LangGraph（真正并行）    : 4.2 秒
  CrewAI hierarchical      : 7.8 秒（manager 决策额外 LLM 调用）
  CrewAI sequential        : 13.1 秒（串行）

Token 成本（10,000 请求/天，GPT-4o）：
  LangGraph   : ~$32/天   （~800 tokens/请求）
  CrewAI      : ~$50/天   （~1,250 tokens/请求，+56%）
  
开销来源：CrewAI 每个 agent 携带 ~450 token 的 system prompt（role/goal/backstory）
```

### 3.3 适用场景矩阵

| 场景 | 推荐框架 | 理由 |
|------|----------|------|
| 生产级 agent，需要故障恢复 | **LangGraph** | Checkpoint + 幂等重试 |
| 复杂状态机（条件分支多） | **LangGraph** | 显式图结构，条件边精确控制 |
| 长时运行 agent（小时级） | **LangGraph** | Persistence + Platform 支持 |
| 需要时间旅行调试 | **LangGraph** | StateSnapshot 历史可查 |
| 快速原型，角色明确的团队 | **CrewAI** | 直觉式定义，40% 更快上手 |
| 研究/内容生产流水线 | **CrewAI** | Sequential 流程清晰 |
| 需要跨框架 agent 互操作 | **CrewAI** | A2A 协议原生支持 |
| 私有部署全栈 AI 系统 | **CrewAI** | 本地 LLM + 本地向量库 |

### 3.4 SWE-bench 及基准数据

目前缺乏两框架对 SWE-bench 的系统对比（SWE-bench 主要评测单 agent 编码能力，而非框架）。

**关键生产指标**（来自各框架报告）：
- CrewAI：每日 1200 万 agent 执行，GitHub 45,900+ stars
- LangGraph：LangSmith Platform 有大型企业生产客户，托管版已 GA

---

## 第四章：对 Clade Supervisor/Worker 模型的借鉴

### 4.1 Clade 当前架构

```
Orchestrator (FastAPI)
  └── supervisor → plans tasks
        └── workers → execute tasks (parallel, git worktrees)
              └── task_queue (SQLite)
```

### 4.2 可借鉴：LangGraph 的 Checkpoint 思路

**问题**：Clade worker 失败后需要重头执行，没有细粒度恢复点。

**LangGraph 做法**：每个 super-step 后保存完整 state snapshot，失败时从上一个有效 checkpoint 恢复，不重跑已成功的步骤。

**可借鉴点**：

```python
# Clade 可以在 task_queue 里记录 worker 的执行阶段
# 类似 LangGraph 的 checkpoint_ns 概念
task_phases = {
    "plan": "completed",
    "code": "completed",
    "test": "failed",      # 从这里重试，不重跑 plan/code
    "review": "pending"
}
```

**具体建议**：
1. 在 `tasks` 表增加 `phase` 字段（plan/implement/test/review）
2. 每个 phase 完成后单独更新状态
3. 重试时从上次失败的 phase 继续，而不是整个 task 重来

### 4.3 可借鉴：LangGraph 的 interrupt() 机制

**问题**：Clade 的 human-in-loop 目前依赖 interventions 表轮询，不够优雅。

**LangGraph 做法**：
- `interrupt(payload)` 将 payload 返回给调用方并暂停执行
- `Command(resume=value)` 恢复执行，value 成为 `interrupt()` 的返回值
- 整个节点在恢复时重跑，但 interrupt 之前的代码需要幂等

**可借鉴点**：Worker 执行中遇到需要审批的操作（如执行危险命令），可以通过类似 interrupt 的机制暂停，等待用户通过 WebSocket 确认后继续。

### 4.4 可借鉴：LangGraph 的 Send（Map-Reduce）

**问题**：Clade 的 supervisor 分发任务时需要动态创建 N 个并行 worker。

**LangGraph 做法**：`Send` API 允许动态扇出——根据当前状态决定要并行启动多少个子任务，每个子任务有独立的状态副本。

```python
# LangGraph 模式
def supervisor_node(state: State) -> list[Send]:
    return [
        Send("worker_node", {"task": t, "context": state["context"]})
        for t in state["pending_tasks"]
    ]
```

**可借鉴点**：Clade 的 `SwarmManager` 已经实现了类似逻辑，但可以参考 LangGraph 的 `Send` 让状态传递更显式、可追踪。

### 4.5 可借鉴：CrewAI 的 Task guardrails

**问题**：Clade worker 完成任务后，缺乏系统性的输出质量验证。

**CrewAI 做法**：Task 支持 `guardrail` 参数，可以是 LLM prompt 或 Python 函数，输出不满足时自动重试（最多 `guardrail_max_retries` 次）。

**可借鉴点**：

```python
# 类似 guardrail 的 task 验收逻辑
def validate_task_output(task_output: str, task_spec: dict) -> tuple[bool, str]:
    """
    Returns (passed, feedback)
    如果 passed=False，worker 应使用 feedback 重新执行
    """
    # 检查 expected_output 是否满足
    if task_spec.get("required_files"):
        for f in task_spec["required_files"]:
            if not os.path.exists(f):
                return False, f"Missing required file: {f}"
    return True, ""
```

### 4.6 可借鉴：CrewAI Flows 的事件驱动模式

**问题**：Clade 的 supervisor/worker 循环是轮询式的，不够事件驱动。

**CrewAI 做法**：`@listen()` 装饰器让方法在另一个方法完成后自动触发，`@router()` 根据结果动态路由，无需显式调度。

**可借鉴点**：Clade 的 session 状态更新可以触发下一步逻辑（worker 完成 → supervisor 自动规划下批任务），而不是 supervisor 轮询检查 worker 状态。

### 4.7 可借鉴：LangGraph 的 stream_mode="updates"

**问题**：Clade 的 WebSocket 目前推送粒度较粗。

**LangGraph 做法**：`stream_mode="updates"` 只推送变更的状态键，而不是完整状态，减少网络传输量。自定义 `stream_mode="custom"` 允许在节点执行中途推送任意数据。

**可借鉴点**：Clade 的 WebSocket handler 可以区分：
- `updates` 类型：只推送 task status 变化
- `messages` 类型：实时推送 worker 的 stdout 流
- `custom` 类型：推送 progress percentage 等中间状态

### 4.8 优先级建议

| 优先级 | 借鉴点 | 实现难度 | 价值 |
|--------|--------|----------|------|
| P0 | Task phase checkpointing（恢复粒度） | 中 | 高 |
| P0 | Task output guardrails（质量验证） | 低 | 高 |
| P1 | WebSocket stream 分 type（updates/messages） | 低 | 中 |
| P1 | interrupt 风格的 human approval 机制 | 中 | 中 |
| P2 | 事件驱动 supervisor（listener 替代轮询） | 高 | 中 |
| P2 | Map-reduce Send 显式状态传递 | 中 | 低 |

---

## 附录：快速参考

### LangGraph 关键 API

```python
# 图构建
StateGraph(State)                    # 创建状态图
builder.add_node("name", fn)         # 添加节点
builder.add_edge("a", "b")           # 普通边
builder.add_conditional_edges(       # 条件边
    "a", routing_fn, {"x": "b", "y": "c"}
)
builder.compile(checkpointer=...)    # 必须编译

# 执行
graph.invoke(inputs, config)         # 同步执行
graph.stream(inputs, stream_mode=...)  # 流式执行
graph.astream(...)                   # 异步流式

# 状态管理
graph.get_state(config)              # 获取当前状态
graph.get_state_history(config)      # 获取完整历史
graph.update_state(config, values)   # 修改状态（注入 checkpoint）

# 控制流
interrupt(payload)                   # 暂停执行，等待人工输入
Command(resume=value)                # 恢复执行
Command(update=dict, goto="node")    # 同时更新状态和路由
Send("node", state_dict)             # 动态扇出
```

### CrewAI 关键 API

```python
# 核心对象
Agent(role, goal, backstory, tools, llm, ...)
Task(description, expected_output, agent, context, ...)
Crew(agents, tasks, process, memory, ...)

# Process 类型
Process.sequential        # 顺序
Process.hierarchical      # 层级（需要 manager_llm）

# 执行
crew.kickoff(inputs={})          # 同步执行
crew.akickoff(inputs={})         # 原生异步
crew.kickoff_for_each(inputs=[]) # 批量执行

# Flow 装饰器
@start()                  # 入口点
@listen(method)           # 监听方法完成
@router(method)           # 条件路由（返回字符串标签）
@persist                  # 自动持久化状态

# 逻辑运算
or_(method_a, method_b)   # 任意一个完成即触发
and_(method_a, method_b)  # 全部完成才触发
```

---

*研究完成于 2026-03-30。数据来源：LangGraph 官方文档（docs.langchain.com/oss/python/langgraph）、CrewAI 官方文档（docs.crewai.com）、OpenAgents 框架对比报告、MarkAICode 生产性能评测。*
