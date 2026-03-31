# Mini-SWE-Agent 深度研究

> 研究日期：2026-03-30
> 目标：理解简单性悖论 — 100行Python如何超越复杂框架，提取对 Clade loop 系统的借鉴模式

---

## 一、项目概况

| 指标 | 数值 |
|------|------|
| 核心 agent 代码 | ~150行 (default.py 6.4KB) |
| 整个 src 目录 | ~40个文件，约80KB Python |
| SWE-bench Verified 得分 | >74% (Claude Sonnet 4.5: 75.4%) |
| GitHub Stars | 3,600+ |
| 采用机构 | Meta, NVIDIA, IBM, Anyscale, Stanford, Princeton |
| 版本 | 2.2.8 (v2 于2025年重写) |

**"100行"是营销数字**，指的是 `default.py` 中 `DefaultAgent` 类本身大约100行有效逻辑。整体项目包含完整的 models/environments/config 子系统，但核心循环确实极度简单。

---

## 二、完整源代码架构

### 包结构（src/minisweagent/）

```
agents/
  default.py          # DefaultAgent (核心agent类, ~150行)
  interactive.py      # InteractiveAgent (带human-in-loop, ~180行)
  utils/prompt_user.py

config/
  default.yaml        # 默认system/instance prompt + 观察格式
  mini.yaml           # 生产用config (tool-calling模式)
  mini_textbased.yaml # 传统regex模式
  benchmarks/
    swebench.yaml     # SWE-bench专用config
    swebench_xml.yaml # XML格式变体

environments/
  local.py            # LocalEnvironment (subprocess.run, ~80行)
  docker.py           # DockerEnvironment (~200行)
  extra/
    bubblewrap.py     # 轻量级沙箱
    contree.py        # 树状沙箱
    swerex_docker.py  # SWE-ReX集成
    swerex_modal.py   # Modal云执行

models/
  litellm_model.py    # 主要model实现 (~180行)
  openrouter_model.py
  portkey_model.py
  utils/
    actions_toolcall.py   # BASH_TOOL定义 + 解析
    actions_text.py       # 传统regex解析(v1遗留)
    cache_control.py      # Anthropic prompt caching
    content_string.py
    retry.py

run/
  mini.py             # `mini` CLI入口点
  hello_world.py      # 最简示例
  benchmarks/
    swebench.py       # 批量评测脚本

__init__.py           # Model/Environment/Agent 协议(Protocol)定义
exceptions.py         # 控制流异常
```

### 关键数据流

```
CLI: mini -t "fix bug"
  → run/mini.py::main()
  → get_model() + get_environment() + get_agent()
  → agent.run(task)
    → add_messages(system_prompt, instance_prompt)
    → loop:
        step()
          → query() → model.query(messages) → add_messages(response)
          → execute_actions(response)
            → env.execute(action) → subprocess.run(command)
            → model.format_observation_messages(action, output)
            → add_messages(observation)
        catch InterruptAgentFlow → add exit message
      until messages[-1].role == "exit"
  → save trajectory to JSON
```

---

## 三、核心组件深度解析

### 3.1 DefaultAgent (agents/default.py)

最关键的代码，整个 agent 逻辑的骨架：

```python
class AgentConfig(BaseModel):
    system_template: str      # Jinja2模板
    instance_template: str    # Jinja2模板
    step_limit: int = 0       # 0=无限
    cost_limit: float = 3.0   # $3 默认上限
    output_path: Path | None = None

class DefaultAgent:
    def __init__(self, model, env, **kwargs):
        self.messages: list[dict] = []  # 线性消息历史
        self.model = model
        self.env = env
        self.cost = 0.0
        self.n_calls = 0

    def step(self) -> list[dict]:
        return self.execute_actions(self.query())

    def query(self) -> dict:
        # 检查cost/step限制
        message = self.model.query(self.messages)
        self.cost += message.get("extra", {}).get("cost", 0.0)
        self.add_messages(message)
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        outputs = [self.env.execute(action) 
                   for action in message.get("extra", {}).get("actions", [])]
        return self.add_messages(
            *self.model.format_observation_messages(message, outputs, self.get_template_vars())
        )

    def run(self, task: str = "") -> dict:
        self.messages = []
        self.add_messages(system_msg, instance_msg)
        while True:
            try:
                self.step()
            except InterruptAgentFlow as e:
                self.add_messages(*e.messages)
            if self.messages[-1].get("role") == "exit":
                break
        return self.messages[-1].get("extra", {})
```

**关键设计：** `step()` = `execute_actions(query())`，整个agent逻辑就是这一行。

### 3.2 LocalEnvironment (environments/local.py)

完全无状态执行：

```python
def execute(self, action: dict) -> dict:
    command = action.get("command", "")
    result = subprocess.run(
        command,
        shell=True,
        text=True,
        cwd=self.config.cwd or os.getcwd(),
        env=os.environ | self.config.env,
        timeout=self.config.timeout,  # 默认30秒
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # stderr合并到stdout
    )
    output = {
        "output": result.stdout,
        "returncode": result.returncode,
        "exception_info": ""
    }
    self._check_finished(output)  # 检查魔法字符串
    return output

def _check_finished(self, output: dict):
    lines = output["output"].lstrip().splitlines()
    if lines and lines[0].strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT":
        raise Submitted(...)
```

**关键设计：**
- `shell=True`：每个命令在全新子shell中执行
- `stderr=STDOUT`：合并输出，LLM看到单一流
- 通过魔法字符串检测任务完成，而不是特殊工具
- 每次执行都是完全独立的进程，无状态

### 3.3 唯一工具：BASH_TOOL

在 `models/utils/actions_toolcall.py` 中定义，整个系统只有**1个工具**：

```python
BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                }
            },
            "required": ["command"],
        },
    },
}
```

**工具数量：1个**。这就是全部。

### 3.4 观察格式（Observation Format）

`mini.yaml` 中的观察模板（JSON格式）：

```jinja2
{%- if output.output | length < 10000 -%}
{
  "returncode": {{ output.returncode }},
  "output": {{ output.output | tojson }}
  {%- if output.exception_info %}, "exception_info": ...{% endif %}
}
{%- else -%}
{
  "returncode": {{ output.returncode }},
  "output_head": {{ output.output[:5000] | tojson }},
  "output_tail": {{ output.output[-5000:] | tojson }},
  "elided_chars": {{ output.output | length - 10000 }},
  "warning": "Output too long."
}
{%- endif -%}
```

**关键设计：**
- 输出 <10KB：完整返回
- 输出 ≥10KB：保留头5KB + 尾5KB，明确标注省略字符数
- 永远包含 returncode
- JSON格式：结构化，LLM解析友好

`default.yaml` 用XML格式（SWE-bench评测用）：

```xml
<returncode>{{output.returncode}}</returncode>
<output>
{{ output.output }}
</output>
```

### 3.5 系统提示（System Prompt）

`default.yaml` 中的完整系统提示（非常短）：

```
You are a helpful assistant that can interact with a computer.

Your response must contain exactly ONE bash code block with ONE command.
Include a THOUGHT section before your command where you explain your reasoning.

<format_example>
[THOUGHT]

```mswea_bash_command
your_command_here
```
</format_example>
```

`mini.yaml`（工具调用模式）更短：
```
You are a helpful assistant that can interact with a computer.
```

就这两句话。其余全在 instance_template 里。

### 3.6 异常驱动的控制流

`exceptions.py`，所有控制流通过异常传递：

```python
class InterruptAgentFlow(Exception):
    def __init__(self, *messages: dict):
        self.messages = messages   # 携带要追加的消息

class Submitted(InterruptAgentFlow): pass   # 任务完成
class LimitsExceeded(InterruptAgentFlow): pass  # 超出预算
class FormatError(InterruptAgentFlow): pass     # LLM格式错误
class UserInterruption(InterruptAgentFlow): pass # 用户中断
```

这个模式极其优雅：异常不只是错误信号，还携带了要添加到对话历史的消息。不需要任何状态机或布尔标志。

### 3.7 Protocol 定义

`__init__.py` 中三个核心协议（鸭子类型，无需继承）：

```python
class Model(Protocol):
    def query(self, messages: list[dict]) -> dict: ...
    def format_message(self, **kwargs) -> dict: ...
    def format_observation_messages(self, message, outputs, template_vars) -> list[dict]: ...
    def get_template_vars(self) -> dict: ...
    def serialize(self) -> dict: ...

class Environment(Protocol):
    def execute(self, action: dict, cwd: str = "") -> dict: ...
    def get_template_vars(self) -> dict: ...
    def serialize(self) -> dict: ...

class Agent(Protocol):
    def run(self, task: str) -> dict: ...
    def save(self, path: Path | None) -> dict: ...
```

---

## 四、ACI 设计详解

### 4.1 mini-swe-agent 的 ACI（极简版）

| 维度 | 设计 |
|------|------|
| 工具数量 | 1（bash） |
| 工具接口 | 原生 function calling / 或 regex 解析 ```bash...``` |
| 执行模式 | stateless subprocess（每次新shell） |
| 输出截断 | 10KB阈值，保头5KB+尾5KB |
| 错误反馈 | returncode + exception_info |
| 任务提交 | `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 魔法字符串 |
| 历史格式 | 线性 messages 数组，无压缩/截断 |
| 并行工具调用 | 支持（`parallel_tool_calls: true`） |

**关键限制（刻意设计）：**
- 无持久shell session → 目录变化不保留（需每次 `cd /path && ...`）
- 无文件查看器 → 纯bash（`cat`, `head`, `tail`, `nl`）
- 无搜索工具 → 纯bash（`grep`, `find`）
- 无编辑工具 → 纯bash（`sed`, `cat <<EOF > file`）

### 4.2 原始 SWE-agent 的 ACI（复杂版，对比用）

原始 SWE-agent 有专门设计的工具集（tools/ 目录）：

**windowed/ — 文件查看器工具：**
```yaml
open: 'open "<path>" [<line_number>]'   # 打开文件，显示100行窗口
scroll_up/scroll_down                   # 窗口滚动
goto <line_number>                      # 跳转到行
create <filename>                       # 创建新文件
```

**windowed_edit_linting/ — 编辑器+语法检查：**
```yaml
edit <start_line>:<end_line>            # 替换指定行范围
  <replacement_text>                    # 多行文本
end_of_edit                             # 结束标记
```
编辑后自动运行 flake8/pylint，语法错误时拒绝编辑并显示错误。

**search/ — 搜索工具：**
```yaml
find_file <name> [<dir>]               # 文件名搜索
search_dir <term> [<dir>]              # 目录内容搜索（限50条结果）
search_file <term> [<file>]            # 单文件内容搜索
```

**其他工具：**
- `submit` — 提交patch
- `forfeit` — 放弃任务
- `web_browser` — 浏览器工具（可选）
- `registry` — 状态注册表（跨工具共享状态）

**原始 ACI 的关键设计原则（来自论文 arXiv:2405.15793）：**
1. **简单性**：命令简单，少选项，文档简洁
2. **效率**：每步操作尽量有意义的进展
3. **信息性反馈**：空输出明确提示"命令成功无输出"
4. **防错**：语法检查阻止无效编辑进入历史

### 4.3 mini vs 原版 ACI 的差异

| 特性 | 原版 SWE-agent | mini-swe-agent |
|------|---------------|----------------|
| 工具数量 | 10-15个 | 1个（bash）|
| 文件查看 | 100行窗口+滚动 | bash (cat/head/tail) |
| 文件编辑 | 专用edit命令+linter | bash (sed/heredoc) |
| 搜索 | 专用search命令 | bash (grep/find) |
| 状态管理 | 持久shell session | stateless subprocess |
| 目录跟踪 | CURRENT_FILE 注册表 | 无（每次重设） |
| 语法检查 | 实时linting | 无 |
| 历史压缩 | 支持（history processors） | 无（完整历史） |
| 配置复杂度 | YAML + bash scripts | 单一YAML |

**为什么原版被 mini 超越？**

2024年原版时代（GPT-4-turbo, 12.5%），LLM本身能力弱，需要脚手架辅助。2025年（Claude Sonnet 4.5, 75%+），LLM已经懂得如何用bash完成所有事情，脚手架反而成为障碍：
- 工具定义占用 context
- 工具格式错误需要重试
- 工具限制（如搜索最多50条）限制LLM发挥
- 持久 session 状态管理引入 bug

---

## 五、为什么简单反而更好 — 理论分析

### 5.1 Context 效率假说

每个工具定义（名称、描述、参数schema）占用数百个token。10-15个工具 = 1000-3000 token context overhead。

相比之下，mini-swe-agent 的 BASH_TOOL 定义：~50 tokens。

这1000-3000 token 如果用来放更长的代码片段、更完整的错误信息，效果更好。

### 5.2 工具调用错误级联假说

每次工具调用都有格式错误的概率（名称错误、参数缺失、引号问题）。
- 10个工具 → 10种出错方式
- 1个工具 → 1种出错方式（command字段）

错误触发 FormatError → 消耗步骤 → 打断推理链 → 连锁影响后续步骤。

### 5.3 LLM 已内化 Bash 知识假说

Claude/GPT 在训练中见过大量 bash 代码、Shell scripting 教程、Linux 文档。它已经知道怎么用 `sed -i 's/old/new/g'` 编辑文件，知道 `grep -r "pattern" .` 搜索代码，知道 `git diff` 查看变更。

专用工具本质是对这些知识的封装，但 LLM 不需要这层封装——直接 bash 更自然。

### 5.4 训练数据偏差假说（来自 HN 讨论）

现代 LLM 大量通过 human-in-loop RLHF/SFT 训练 coding 能力。训练数据的人类示范多数直接用 bash，而不是各种 agent 框架的自定义工具。

→ bash 接口与训练分布对齐，自定义工具接口与训练分布偏离。

### 5.5 无状态的可靠性优势

持久 shell session 的问题：
- LLM 可能产生 `exit 1` 导致 session 崩溃
- 长时间运行的命令可能 hang
- Shell 状态可能被意外污染（别名、函数定义等）

`subprocess.run` 的优势：
- 每次都是干净环境
- 崩溃不传播
- 超时由 Python 层管理，不依赖 shell

代价：目录变化不保留，但LLM可以通过前缀 `cd /path && command` 处理。

### 5.6 调试 & 微调友好性

线性 messages 数组 → 完整 trajectory 就是一个 JSON 文件。无隐藏状态、无副作用：
- 调试：直接看 messages 数组
- 微调：直接把 trajectory 当训练数据，格式天然对齐
- 重放：messages 数组 replay 即可

---

## 六、SWE-ReX 并行执行后端架构

SWE-ReX 是 SWE-agent 团队从 SWE-agent 经验中提取的独立包，用于解决 agent 评测中的并行执行问题。

### 架构层次

```
用户代码 (Agent)
    ↓
AbstractRuntime (接口层)
    ├── LocalRuntime  - 本地直接执行
    └── RemoteRuntime - 代理到远程
            ↓
        HTTP (FastAPI server in container)
            ↓
        LocalRuntime (container内)

AbstractDeployment (容器生命周期)
    ├── DockerDeployment
    ├── ModalDeployment  
    ├── AWSFargateDeployment
    └── BubblewrapDeployment
```

### 关键特性

1. **接口透明**：`LocalRuntime` 和 `RemoteRuntime` 实现相同接口，agent代码无需感知在哪执行
2. **多会话并发**：`run_in_session(session_name, command)` 支持在同一container内并发多个shell session
3. **异常透明传递**：container内 `LocalRuntime` 的异常透明传递到外部 `RemoteRuntime`
4. **快速启动**：避免 Docker 镜像 push/pull，支持 bubblewrap（纯进程隔离）

### Anyscale Ray 集成

Ray + mini-swe-agent 规模化评测数据（5,500个CPython任务）：

| 集群规模 | CPU数 | 执行时间 |
|---------|------|---------|
| 2节点 | 256 | 10小时21分 |
| 4节点 | 512 | 5小时9分 |
| 8节点 | 1024 | 2小时31分 |

**近似线性扩展**。模型采用本地 vLLM/SGLang，避免外部API限速。

选择 mini-swe-agent 的理由："极度简单可黑客，不引入额外复杂度，支持多种隔离后端（podman/bubblewrap/apptainer）"。

---

## 七、v1 → v2 关键变化

| 变化 | v1 | v2 |
|------|-----|-----|
| 动作解析 | regex (```` ```bash ``` ````) | 原生 tool calling（默认） |
| completion信号 | `echo MINI_SWE_AGENT_FINAL_OUTPUT` | `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` |
| Anthropic支持 | 专用AnthropicModel类 | 通过 litellm 统一 |
| cost追踪 | 在 Model 内 | 移到 Agent 层 |
| 并行工具调用 | 不支持 | 支持 (`parallel_tool_calls: true`) |
| 旋转API Keys | 支持 (`::` 分隔) | 移除 |
| 视觉CLI模式 | 支持 (`-v` flag) | 移除（维护成本高）|
| 返回值 | `submission, exit_status = agent.run()` | `result = agent.run(); result["submission"]` |

---

## 八、对 Clade Loop 系统的具体借鉴

### 8.1 异常驱动的控制流（直接可用）

mini-swe-agent 的异常模式比 Clade 现有的 flag/返回值方式更优雅：

```python
# mini-swe-agent 模式
class InterruptWorkerLoop(Exception):
    def __init__(self, *messages):
        self.messages = messages

class TaskCompleted(InterruptWorkerLoop): pass
class BudgetExceeded(InterruptWorkerLoop): pass
class NeedsReview(InterruptWorkerLoop): pass
class BlockedOnDependency(InterruptWorkerLoop): pass

# worker 主循环
while True:
    try:
        step()
    except InterruptWorkerLoop as e:
        handle(e.messages)
    if is_terminal(messages[-1]):
        break
```

好处：扩展不需要修改主循环，每种中断类型天然携带上下文消息。

### 8.2 线性 Messages 数组作为 Task Trajectory

当前 Clade 把 worker 输出存储在 SQLite 中（多个字段）。可以考虑同时存储 `messages: list[dict]` JSON：

```python
# 每个 task 的完整轨迹
task_trajectory = {
    "info": {
        "instance_cost": 2.34,
        "api_calls": 15,
        "exit_status": "Submitted",
    },
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "task description..."},
        {"role": "assistant", "content": "...", "extra": {"actions": [...]}},
        {"role": "tool", "content": "output...", "extra": {"returncode": 0}},
        ...
        {"role": "exit", "content": "...", "extra": {"submission": "..."}},
    ]
}
```

好处：
- 完整可重放
- 天然微调数据格式
- 调试时直接看 messages
- Inspector UI 可以复用 mini 的 trajectory viewer

### 8.3 Protocol-based 设计（模块替换）

mini-swe-agent 的三协议（Model/Environment/Agent）让替换任意组件不需要修改其他：

```python
# Clade 可以类似定义 Worker protocol
class Worker(Protocol):
    def run(self, task: Task) -> WorkerResult: ...
    def get_cost(self) -> float: ...
    def serialize(self) -> dict: ...

# 然后可以有不同 Worker 实现：
# - ClaudeCodeWorker（当前实现）
# - MiniSWEAgentWorker（mini-swe-agent引擎）
# - HumanWorker（人工review）
```

### 8.4 Observation 格式：结构化 + 截断

Clade 的 worker 输出返回给 supervisor 时，可以采用类似的截断策略：

```python
def format_worker_output(output: str, max_len: int = 10000) -> dict:
    if len(output) < max_len:
        return {"output": output, "truncated": False}
    return {
        "output_head": output[:5000],
        "output_tail": output[-5000:],
        "elided_chars": len(output) - 10000,
        "truncated": True,
        "warning": "Output too long. Showing head and tail only."
    }
```

### 8.5 Stateless Task Execution（隔离性改进）

当前 Clade worker 可能共享某些全局状态。mini-swe-agent 的模式：每个 task 完全独立，在独立 Docker/sandbox 中运行。

对 Clade 的意义：
- 每个 worker iteration 应该在 git worktree 或 Docker 中隔离
- 这样多个 worker 可以真正并行不冲突
- 失败的 iteration 不污染全局状态

### 8.6 Cost 跟踪的层次结构

mini-swe-agent 有两层 cost 追踪：
- `GLOBAL_MODEL_STATS`：全局单例，线程安全，可设置全局限额
- `Agent.cost`：单个 agent 实例级别

Clade 可以类似设计：
```python
# 全局层：所有 worker 的总成本
GLOBAL_WORKER_STATS = WorkerStats()

# session 层：单个 ProjectSession 的成本
session.cost = sum(worker.cost for worker in session.workers)

# task 层：单个 task 的成本（已有）
task.cost = ...
```

### 8.7 Jinja2 模板系统（Supervisor prompt 动态化）

mini-swe-agent 用 Jinja2 渲染所有 prompt，模板变量来自：
- `config.model_dump()`
- `env.get_template_vars()`（包含 OS info, 工作目录等）
- `model.get_template_vars()`（包含 model name）
- 运行时变量（`n_calls`, `cost`, `task`）

Clade 的 supervisor prompt 可以类似做：
```yaml
# supervisor_config.yaml
system_template: |
  You are a supervisor managing workers on project: {{project_name}}.
  Current budget: ${{budget_remaining:.2f}} remaining.
  Workers available: {{n_workers}}.
  
instance_template: |
  ## Goal
  {{goal}}
  
  ## Completed tasks
  {{completed_tasks | join('\n')}}
  
  ## Failed tasks  
  {{failed_tasks | join('\n')}}
  
  Plan the next batch of tasks.
```

### 8.8 并行工具调用模式（SWE-bench 配置参考）

`swebench.yaml` 中：
```yaml
model:
  model_kwargs:
    parallel_tool_calls: true
    temperature: 0.0
```

Clade 如果 supervisor 需要规划多个 task，可以让它并行调用多次：
```yaml
model_kwargs:
  parallel_tool_calls: true   # 一次 LLM 调用规划多个 task
```

---

## 九、关键数字速查

| 指标 | 数值 |
|------|------|
| DefaultAgent 代码行数 | 149行（含注释和空行） |
| 工具数量 | 1（bash） |
| 默认 cost 上限 | $3.00/任务 |
| 默认 step 上限 | 0（无限） |
| 命令超时 | 30秒（local），60秒（swebench docker） |
| 输出截断阈值 | 10,000字符 |
| 截断后保留 | 头5000 + 尾5000 字符 |
| SWE-bench Verified (Gemini Pro) | ~74% |
| SWE-bench Verified (Claude Sonnet 4.5) | 75.4% |
| SWE-bench Verified (原版 SWE-agent, 2024) | 12.5% (GPT-4-turbo) |
| Ray 并行评测 (1024 CPU) | 2.5小时 跑5500任务 |
| 当前版本 | 2.2.8 |

---

## 十、延伸阅读

- 原始 SWE-agent 论文：[arXiv:2405.15793](https://arxiv.org/abs/2405.15793)
- mini-swe-agent 文档：[mini-swe-agent.com](https://mini-swe-agent.com/latest/)
- Ray 并行化博文：[Anyscale Blog](https://www.anyscale.com/blog/massively-parallel-agentic-simulations-with-ray)
- SWE-ReX 架构：[swe-rex.com](https://swe-rex.com/latest/architecture/)
- Agent 入门教程（mini-swe-agent团队）：[minimal-agent.com](https://minimal-agent.com)
- HN 讨论：[Show HN: 65% in 100 lines](https://news.ycombinator.com/item?id=44682897)
