---
name: 2026-03-30-swe-agent-research.md
date: 2026-03-30
status: reference
review_date: 2026-03-31
summary:
  - "SWE-agent: ACI design principles (4 principles), 100-line window size, linting guardrail, filemap tool"
integrated_items:
  - "ACI design principles — inform tool design for Claude Code interactions"
  - "Linting guardrail after file edits — not implemented (could be a PostToolUse hook)"
needs_work_items:
  - "Formal filemap tool — could enhance worker_tldr.py codebase understanding"
  - "100-line window size constraint — Clade uses 2000 line truncation"
reference_items:
  - "4 ACI design principles: simple actions, informative feedback, easy monitoring, enabling recovery"
  - "filemap tool for SWE-bench harness"
---

# SWE-agent 深度研究

> 研究日期：2026-03-30
> 来源：NeurIPS 2024 论文 arXiv:2405.15793，官方文档 swe-agent.com，GitHub 源码

---

## 一、项目概况

| 指标 | 数值 |
|------|------|
| 论文 | SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering |
| 发表 | NeurIPS 2024 |
| 机构 | Princeton University + Stanford University |
| SWE-bench 得分 | 12.47%（GPT-4 Turbo，2294个问题） |
| SWE-bench Lite 得分 | 18.00%（vs 之前最佳 4.33%） |
| HumanEvalFix 得分 | 87.7% pass@1 |
| 对比基准 | 之前最佳 RAG 方法：3.8% |
| 当前状态 | Maintenance-only（已被 mini-swe-agent 取代） |
| 代码语言 | Python 94.8% |

**核心贡献**：首次系统化提出 **Agent-Computer Interface (ACI)** 概念，证明专为 LM 设计的接口能大幅提升 agent 性能，不需要改变模型权重。

---

## 二、ACI 理论 — 论文级理论深度

### 2.1 ACI 的定义

> "An Agent-Computer Interface (ACI) is essentially a set of tools and interaction format that allows an agent to interact with a computer-based environment to perform tasks."

ACI 的核心洞察：**LM agent 是新类别的终端用户**，有别于人类用户和传统程序接口（API）。

| 接口类型 | 使用者 | 特点 |
|----------|--------|------|
| UI（图形界面） | 人类 | 视觉渲染、鼠标交互、高信息密度 |
| API | 程序 | 精确类型、机器可解析、无冗余 |
| **ACI** | **LM Agent** | 自然语言友好、容错、结构化反馈、防错设计 |

人类开发者用 IDE（丰富工具链）而非裸终端解决复杂问题；SWE-agent 的核心主张是：**LM agent 同样需要专为其认知模式定制的工具环境**，而不是复用为人类设计的 Linux shell。

### 2.2 四条 ACI 设计原则（论文 Section 3）

论文从实验和分析中归纳出四条核心设计原则，它们在工具、反馈、工作流中反复出现：

#### 原则一：Actions should be simple and easy to understand

- 每个命令只做一件事，参数数量少，文档简洁
- 避免需要 agent 记忆复杂 bash flag 组合（如 `find . -name "*.py" -exec grep -n "foo" {} \;`）
- 设计意图：**减少认知负荷，降低对 demonstrations 或 fine-tuning 的依赖**
- 实现方式：用 YAML 定义工具的 `signature`、`docstring`、`arguments`，清晰标注类型和必选性

#### 原则二：Actions should be efficient

- 重要操作（文件导航、编辑）应尽量在单步完成
- 避免需要多轮才能完成的操作（如用 sed 需要 3 步：查看、删除、插入）
- 设计意图：**让 agent 每一步都能产生实质进展，减少无效 token 消耗**
- 实现方式：`edit <start>:<end>` 一条命令完成多行替换，`open` 可直接跳转到指定行

#### 原则三：Feedback should be informative

- 反馈必须告知 agent：当前环境状态 + 上一步操作的效果
- 反馈要"高质量"：有实质信息但不含冗余细节
- 具体设计：
  - 编辑成功后显示修改后的文件窗口，不仅输出"OK"
  - 空输出时明确说明："Your command ran successfully and did not produce any output"
  - 搜索命中过多时截断（最多 50 条），避免淹没上下文
  - 错误信息精确定位问题所在行
- 设计意图：**让 agent 能自我校正，形成有效的反馈闭环**

#### 原则四：Guardrails mitigate error propagation

- LM 会犯错，且不擅长从错误状态中恢复
- 内建防错机制，在错误扩散之前拦截
- 具体设计：
  - 编辑命令集成 flake8 linter：新引入语法错误 → 自动撤销编辑 → 返回详细错误信息 + 修改前/后对比窗口
  - 文件不存在时给出明确提示而非空输出
  - 命令执行前进行参数校验
- 设计意图：**把错误检测前移，不等 test 失败才发现问题**

### 2.3 ACI 与 UI/API 的本质区别

```
人类用 UI → 大量视觉上下文，鼠标交互，信息丰富
程序调 API → 精确类型，机器可解析，无容错
LM 用 ACI → 自然语言 docstring，适度信息密度，内建防错，结构化反馈
```

论文核心论点：**同一个 LM，配以不同 ACI，性能差异极大**（ablation 显示 +10.7 百分点）。接口设计的重要性不亚于模型本身的能力。

---

## 三、完整工具集

SWE-agent 的工具分布在 `tools/` 目录的 15 个子目录中，按功能分组使用。

### 3.1 文件查看工具（tools/windowed/）

#### `open <path> [<line_number>]`
- 打开文件并显示 100 行窗口
- 可直接跳转到指定行号
- **设计理由**：替代 `cat`，避免将整个大文件倾倒入上下文；100 行是实验得出的最优窗口大小（太少则信息不足，太多则 LM 混乱）

#### `goto <line_number>`
- 将视窗移动到指定行（定位到窗口顶部 + 1/6 偏移）
- **设计理由**：搜索找到行号后，快速定位查看上下文

#### `scroll_up` / `scroll_down`
- 按整窗大小滚动，支持 overlap 配置（避免完全丢失上下文）
- **设计理由**：文件导航的基础操作，比 `head -n 200` 更符合 agent 的逐步浏览习惯

#### `create <filename>`
- 创建新文件并立即打开
- **设计理由**：创建后的下一步通常是编辑，合并两步

**状态管理**：通过 registry 持久化 `CURRENT_FILE`、`FIRST_LINE`、`WINDOW` 大小，跨命令共享状态。

### 3.2 文件编辑工具（tools/windowed_edit_linting/）

#### `edit <start_line>:<end_line>`
```
edit 42:48
    new code here
    more new code
end_of_edit
```
- 替换指定行范围，集成 flake8 linting
- 编辑前检查现有 lint 错误，编辑后比对新增错误
- 若引入新语法错误：自动撤销 + 返回错误信息 + 展示修改前/后对比
- **设计理由**：把"写代码+验证"合并为原子操作；用 `end_of_edit` 终止符避免多行参数解析问题；linting 即时反馈比等测试失败更快

#### `str_replace_editor`（tools/edit_anthropic/）
- Anthropic 模型专用编辑器（与 Claude 的 str_replace 风格一致）
- 支持：`view`、`create`、`str_replace`、`insert`、`undo_edit`
- `str_replace` 要求精确匹配唯一上下文字符串，然后替换
- **设计理由**：与 Anthropic 模型的原生工具调用接口对齐，减少格式适配成本

### 3.3 搜索工具（tools/search/）

#### `find_file <file_name> [<dir>]`
- 支持 shell 通配符（`*.py`, `test_*`）
- 在指定目录或当前目录递归搜索
- 只输出文件路径列表，不显示内容
- **设计理由**：替代 `find . -name`，输出格式对 LM 友好；避免混入无关 `-exec` 语法

#### `search_dir <search_term> [<dir>]`
- 在目录中所有文件搜索字符串
- 输出截断到最多 50 条匹配
- 只显示"文件名:行号"，不显示上下文行
- **设计理由**：论文实验发现，显示过多上下文（如 grep 默认输出）会干扰模型；纯文件列表信噪比更高

#### `search_file <search_term> [<file>]`
- 在当前打开文件（或指定文件）中搜索
- **设计理由**：定位到当前文件内特定位置，配合 goto 使用

### 3.4 文件地图工具（tools/filemap/）

#### `filemap <file_path>`
- 打印 Python 文件内容，**跳过冗长的函数/方法体**
- 只显示函数签名、类定义、模块级代码
- **设计理由**：理解大型 Python 文件结构时，agent 不需要看全部实现，只需要看"骨架"；大幅节省上下文 token

### 3.5 差异状态工具（tools/diff_state/）

- 无工具（`tools: {}`），只有 `_state_diff_state` 状态命令
- 在每个观察中注入当前 git diff
- **设计理由**：让 agent 在每步都能感知自己已经做了哪些修改，避免重复编辑或遗漏

### 3.6 提交工具（tools/submit/）

#### `submit`
- 创建 git diff patch（`git add -A && git diff --cached`）
- 撤销测试 patch（`git apply -R < /root/test.patch`）
- 输出 `<<SWE_AGENT_SUBMISSION>>` 包裹的 patch
- **设计理由**：标准化提交流程，确保干净的 diff；测试 patch 撤销防止污染评测结果

#### 配套：`review_on_submit_m`（tools/review_on_submit_m/）
- 提交前触发多步自检：重新运行复现脚本、删除临时测试文件、还原被修改的测试文件
- **设计理由**：提交前的"代码审查"工作流，防止提交临时调试代码

### 3.7 浏览器工具（tools/web_browser/）

完整浏览器操控工具集（EnIGMA 扩展引入）：

| 工具 | 功能 |
|------|------|
| `open_site <url>` | 打开网页或本地文件 |
| `close_site` | 关闭浏览器窗口 |
| `screenshot_site` | 截图（用于 multimodal 模型） |
| `click_mouse <x> <y>` | 点击指定坐标 |
| `double_click_mouse <x> <y>` | 双击 |
| `move_mouse <x> <y>` | 移动鼠标 |
| `drag_mouse <path>` | 拖拽（JSON 坐标数组） |
| `type_text <text>` | 在焦点元素输入文字 |
| `scroll_on_page <x> <y>` | 滚动页面 |
| `execute_script_on_page <script>` | 执行 JavaScript |
| `navigate_back / forward` | 浏览器前进后退 |
| `reload_page` | 刷新页面 |
| `press_keys_on_page <keys>` | 按键（JSON 数组，支持组合键） |
| `set_browser_window_size <w> <h>` | 设置窗口尺寸 |
| `get_console_output` | 获取浏览器控制台输出 |
| `wait_time <ms>` | 等待指定毫秒 |

**设计理由**：CTF/网络安全任务经常需要与 web 界面交互；multimodal LM 可通过截图感知页面状态。

### 3.8 放弃工具（tools/forfeit/）

#### `exit_forfeit`
- 放弃当前任务，终止会话
- **设计理由**：当 agent 无法解决问题时，给出明确的"放弃"信号比无限循环更好；在 CTF 场景中避免无效消耗

### 3.9 工具分组汇总

```
工具包名称                 包含工具
─────────────────────────────────────────────
windowed                   open, goto, scroll_up, scroll_down, create
windowed_edit_linting      edit（含 flake8 linting）
windowed_edit_replace      str_replace 风格编辑
windowed_edit_rewrite      整块代码重写
edit_anthropic             str_replace_editor（Anthropic 原生格式）
search                     find_file, search_dir, search_file
filemap                    filemap（Python 骨架视图）
diff_state                 git diff 状态注入
submit                     submit
review_on_submit_m         submit（含提交前审查工作流）
forfeit                    exit_forfeit
web_browser                完整浏览器操控（16个工具）
registry                   工具注册表管理
image_tools                图像处理（multimodal）
multilingual_setup         多语言环境配置
```

**默认配置（default.yaml）**加载的工具包：
- `tools/registry`
- `tools/edit_anthropic`（Anthropic 模型的 str_replace_editor）
- `tools/review_on_submit_m`

---

## 四、ACI 设计原则的三个维度

论文指出这四条原则在三个维度中反复体现：

### 维度一：Actions（工具设计）

| 原则 | 体现 |
|------|------|
| 简单 | 每个工具只做一件事，1-3 个参数 |
| 高效 | `edit` 合并查看+修改+验证；`open` 合并打开+定位 |
| 可发现性 | YAML docstring 清晰说明工具目的和使用场景 |

### 维度二：Feedback（反馈设计）

| 情形 | 反馈设计 |
|------|---------|
| 编辑成功 | 展示修改后的文件窗口（非仅"OK"） |
| 编辑有语法错误 | 展示错误详情 + 修改前后对比 + 拒绝应用 |
| 命令无输出 | 明确说明"ran successfully, no output" |
| 搜索过多结果 | 截断到 50 条，告知截断原因 |
| 文件未打开 | 明确说明"Use the open command first" |

### 维度三：Workflows（工作流设计）

- **ReAct 框架**：Agent 每步生成 thought（分析）+ action（执行），不允许只有 action
- **上下文压缩**：超过最近 5 步的观察压缩为单行摘要，保留历史感知但不爆炸上下文
- **提交前审查**：`SUBMIT_REVIEW_MESSAGES` 定义多步自检流程
- **环境变量控制**：`PAGER=cat`、`TQDM_DISABLE=1` 等，去除对 agent 无用的输出格式

---

## 五、SWE-ReX 并行执行架构

### 5.1 项目定位

SWE-ReX（Sandboxed Code Execution for Remote Execution）是 SWE-agent 的执行层，从 SWE-agent 主项目中解耦出来，成为独立 package。

**核心价值主张**：让 agent 代码在任何环境运行（本地/Docker/云端），代码不需要任何改变。

### 5.2 架构分层

```
┌─────────────────────────────────────────────┐
│                Agent Logic                   │
│          (sweagent / mini-swe-agent)         │
└────────────────────┬────────────────────────┘
                     │ 统一接口
┌────────────────────▼────────────────────────┐
│              SWEEnv (薄包装层)               │
│         ← 调用 SWE-ReX Deployment            │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│           Deployment 类（基础设施层）         │
│  Local | Docker | Remote | Modal | Fargate  │
│                   Dummy                      │
└────────────────────┬────────────────────────┘
                     │ 启动容器/实例
┌────────────────────▼────────────────────────┐
│           Runtime 类（执行层）               │
│   RemoteRuntime ←→ FastAPI Server            │
│                      ↕                       │
│                LocalRuntime                  │
│         （在容器/实例内部执行命令）           │
└─────────────────────────────────────────────┘
```

### 5.3 核心组件

**Deployment 类**（入口点）：
- `LocalDeployment` — 本机直接运行
- `DockerDeployment` — 启动本地 Docker 容器
- `RemoteDeployment` — 远程机器
- `ModalDeployment` — Modal serverless 平台
- `FargateDeployment` — AWS Fargate
- `DummyDeployment` — 测试用虚拟部署

**Runtime 类**（执行接口）：
- `RemoteRuntime` — agent 侧的主接口，调用容器内 FastAPI server
- `LocalRuntime` — 容器内实际执行命令，与 RemoteRuntime 接口完全相同（可互换）

**核心操作**：
- `execute(Command)` — 一次性命令执行
- `run_in_session(SessionCommand)` — 在持久 shell session 中执行（保持状态）
- 读写文件、管理多个并发 shell session

### 5.4 并行执行能力

SWE-ReX 的设计目标之一是**大规模并行评测**：
- 同时运行 30 个 SWE-bench 实例（文档中的示例数字）
- 每个实例独立的 Docker 容器，隔离执行
- 无状态设计：每个实例独立启动/销毁，不互相干扰
- 支持 Modal/Fargate 等云端弹性扩展

**异步设计**：所有操作都是 `async/await`，Python asyncio 驱动，天然支持并发。

### 5.5 ACI 安装机制

SWE-ReX 在启动 Docker 容器后：
1. 在容器内安装 `swerex-remote`（小型 FastAPI server）
2. 将 ACI 工具（`tools/` 目录）安装到 shell session 的 PATH 中
3. Shell session 内的 `edit`、`open` 等命令因此可用

这意味着 ACI 工具是普通的 shell 脚本/Python 脚本，不是 LM function calling，而是通过 bash 工具调用实现（function calling 格式只是解析 agent 输出的方式）。

---

## 六、配置系统

SWE-agent 通过单一 YAML 文件控制 agent 的全部行为。

### 6.1 配置文件结构

```yaml
# 系统提示（agent 的角色定义）
system_template: |
  You are a helpful assistant that can interact with a computer to solve tasks.

# 实例提示（每个任务的上下文注入）
instance_template: |
  We're currently solving the following issue...
  Repository: {repo}
  Issue: {issue}

# 下一步提示（每次 agent 输出后的格式化）
next_step_template: |
  OBSERVATION:
  {observation}

# 无输出时的专用提示
next_step_no_output_template: |
  Your command ran successfully and did not produce any output.

# 工具包列表
tools:
  bundles:
    - path: tools/registry
    - path: tools/edit_anthropic
    - path: tools/review_on_submit_m

# 工具注册表变量
tools:
  registry_variables:
    USE_FILEMAP: "true"
    SUBMIT_REVIEW_MESSAGES: "..."

# bash 工具是否启用
tools:
  enable_bash_tool: true

# action 解析方式
tools:
  parse_function:
    type: function_calling  # 或 thought_action

# 上下文历史处理
history_processors:
  - type: cache_control
    last_n_messages: 2

# 环境变量注入
env_variables:
  PAGER: cat
  TQDM_DISABLE: "1"
```

### 6.2 可调参数分类

| 类别 | 参数 | 作用 |
|------|------|------|
| 模型 | `agent.model.name` | 选择 LLM（gpt-4o, claude-3-7-sonnet 等） |
| 成本控制 | `agent.model.per_instance_cost_limit` | 单实例最大 token 费用 |
| 工具 | `tools.bundles` | 选择工具包组合 |
| 解析 | `tools.parse_function.type` | function_calling / thought_action / backticks |
| 历史 | `history_processors` | 上下文压缩策略 |
| 环境 | `env.deployment.type` | docker / modal / local |
| 问题 | `problem_statement.*` | github_url / text / path |
| 仓库 | `env.repo.*` | github_url / path |

### 6.3 内置配置变体

```
config/
  default.yaml              # 标准 Anthropic str_replace 工具
  bash_only.yaml            # 纯 bash，无专用工具
  default_backticks.yaml    # 反引号格式解析（旧版兼容）
  default_mm_with_images.yaml  # multimodal + 图像工具
  default_mm_no_images.yaml    # multimodal 但禁用图像
  coding_challenge.yaml     # 竞技编程任务
  benchmarks/               # 各种 benchmark 专用配置
  sweagent_0_7/             # 旧版 0.7 兼容配置
```

---

## 七、Benchmark 方法论

### 7.1 SWE-bench 数据集

- **任务构成**：来自 GitHub 的真实 issue + 修复 commit
- **评测标准**：FAIL_TO_PASS 测试（原本失败、修复后应通过） + PASS_TO_PASS 测试（原本通过、修复后仍通过）
- **规模**：SWE-bench full = 2294 个任务；SWE-bench Lite = 300 个任务

### 7.2 环境隔离

每个任务在独立 Docker 容器中执行，三层镜像设计：
1. **Base image** — 所有评测的公共依赖
2. **Environment image** — 特定 Python 版本环境（约 60 种配置）
3. **Instance image** — 每个任务特定的依赖版本

在实例化容器时，**删除 issue 创建时间点之后的所有 git 历史**，防止模型看到人类解答。

### 7.3 SWE-agent 的评测流程

1. 创建 Docker 容器（通过 SWE-ReX）
2. clone 目标仓库（截断到 issue 时间点的 commit）
3. 安装 ACI 工具到 shell 环境
4. 向 agent 提供：仓库路径 + issue 描述
5. Agent 在容器内执行修改（edit/search/bash 工具）
6. `submit` 工具生成 git diff patch
7. 评测框架用 patch 还原到干净环境，运行测试套件
8. FAIL_TO_PASS 全通过 = resolved

### 7.4 模型评测结果（原始论文）

| 方法 | SWE-bench Full | SWE-bench Lite |
|------|----------------|----------------|
| 之前最佳（RAG） | 3.8% | 4.33% |
| SWE-agent (GPT-4 Turbo) | 12.47% | 18.00% |
| SWE-agent (Claude 3 Opus) | ~11% | ~17% |

---

## 八、Ablation 研究：接口设计的量化影响

在 300 个 SWE-bench 实例上的 ablation（Section 5 of paper）：

### 核心发现

**完整 SWE-agent ACI vs 纯 Linux shell：+10.7 个百分点**

这个数字意味着：通过精心设计接口（不改变任何模型权重），解决率从 ~7% 提升到 ~18%，**提升超过 150%**。

### 关键 ablation 结论

| 实验设置 | 性能变化 | 结论 |
|---------|---------|------|
| 无文件编辑器（仅 shell） | 显著下降 | 专用编辑器是核心 |
| 文件窗口 30 行（太小） | -3.7pp | 信息不足 |
| 文件窗口 全文件（太大） | -1.3pp | 信息过载 |
| 无 linting guardrail | -3.0pp | 防错机制关键 |
| 迭代搜索（vs 并发搜索） | -6.0pp | 搜索效率影响大 |

**窗口大小实验**揭示 agent 对上下文量敏感：100 行是经实验验证的最优值，偏少和偏多都会降低性能。

---

## 九、与 mini-swe-agent 的对比和演化

### 9.1 工具数量对比

| 系统 | 工具数量 | 工具特点 |
|------|---------|---------|
| SWE-agent 原版 | 10-15 个专用工具 | 每个工具有明确设计理由 |
| mini-swe-agent | 1 个（bash） | 无任何 ACI 工具 |
| mini-swe-agent 得分 | >74% SWE-bench Verified | 远超 SWE-agent 原版 |

### 9.2 论文作者的解释

官方 FAQ 直接陈述：

> "SWE-agent originally placed a lot of emphasis on tools and special interfaces for the agent. However, **one year later, as LMs have become more capable, a lot of this is not needed at all** to build a useful agent."

关键洞察：
- 2024 年的 GPT-4 Turbo 需要专用 ACI 辅助才能处理大文件、避免语法错误
- 2025 年的 Claude Sonnet 4.5 已有足够的代码理解能力，不需要 windowed viewer 和 linting guardrail
- **ACI 原则仍然有效，但实现形式变了**：现代 LM 已内化了部分 ACI 的功能

### 9.3 ACI 原则的持久性

mini-swe-agent 的 bash-only 设计不是否定 ACI 原则，而是：
- 原则不变：简单、高效、informative feedback、防错
- **现代 LM 本身实现了部分原则**：更好地理解 bash 输出、更少犯语法错误
- 剩余价值：system prompt 的精心设计（ACI 的软件层），而非硬件层工具

### 9.4 LIVE-SWE-AGENT 的发现

动态工具创建（让 agent 自己创建工具）在某些场景仍有价值：
- 静态工具数量对性能影响有限
- 动态工具创建 + 反思（每步评估是否需要新工具）= 最高解决率
- 结论：工具价值在于"对当前任务的适配性"，而非"工具本身的存在"

---

## 十、对 Clade Worker 设计的启发（可操作建议）

### 10.1 ACI 原则映射到 Worker 工具设计

**当前 Clade worker 状态**：worker 通过 Claude Code CLI 执行任务，CLI 本身已有强大工具（Read、Edit、Bash 等）。

**可借鉴的 ACI 原则**：

#### A. Informative Feedback — 观察质量

SWE-agent 的每次工具调用都产生"状态感知"输出，而不只是 "OK"。

**建议**：在 worker 的 system prompt 中明确要求：
```
After each tool call, explicitly state:
1. What you observed
2. What it tells you about the current state
3. What your next step will be
```

这强制 worker 在每步后做显式推理，复现 ACI 的 informative feedback 效果。

#### B. Guardrails — 防止错误传播

SWE-agent 的 linting 防止语法错误静默传播。

**建议**：在 worker 的任务规范中加入：
- 要求 worker 修改代码后立即运行 `python -m py_compile` 验证
- 要求 worker 在每个逻辑单元完成后跑相关测试
- 在 loop supervisor 中检测 worker 是否有"无进展重复循环"

#### C. Compact and Efficient — 减少无效步骤

SWE-agent 的 `edit` 命令合并查看+修改+验证。

**建议**：在任务分解时，避免过细的子任务（每个任务 ~1-3 个关键步骤），减少 worker 的"查看状态"开销。

#### D. Context Management — 上下文控制

SWE-agent 将 5 步前的观察压缩为单行摘要。

**Clade 的 worker_tldr.py 已实现类似机制**。继续确保：
- TLDR 质量：包含"做了什么"+ "结果是什么"+ "下一步是什么"
- 不要在 handoff 中截断正在进行的推理链

### 10.2 工具设计建议

对于未来可能给 worker 提供的专用工具（如 MCP 工具）：

| SWE-agent 经验 | Clade 场景建议 |
|----------------|----------------|
| 每个工具有清晰的 docstring | MCP 工具 description 要写 LM 友好的使用说明 |
| 工具输出截断到合理上限 | API 调用结果超过 2000 字符时摘要化 |
| 空输出明确说明 | `{"status": "success", "result": null}` 而非 `{}` |
| 错误信息精确定位 | 不要 "Internal error"，要 "Task 42 not found in queue" |
| 防止无效状态传播 | 写入 DB 前验证数据，不要让无效数据静默进入队列 |

### 10.3 loop 架构建议

SWE-agent 的工作流启发：

1. **Supervisor 的 "plan + verify" 模式**（类似 SWE-agent 的 `SUBMIT_REVIEW_MESSAGES`）：
   - Supervisor 在分配任务时同时提供验收标准
   - Worker 完成后自检：是否满足验收标准？

2. **并行隔离**（SWE-ReX 的核心思想）：
   - 每个 worker 在独立 git worktree 执行，完全隔离
   - Clade 已有 worktree 机制，是正确方向

3. **Forfeit 机制**（SWE-agent 的 `exit_forfeit`）：
   - Worker 应能识别"当前任务超出能力"并明确报告
   - 比无限重试更好：尽快报告失败，让 supervisor 重新分配或人工介入

---

## 十一、论文最重要的 5 个实验结论

### 结论 1：接口设计效果量化
**+10.7 个百分点**：完整 ACI 对比纯 Linux shell，在 300 个 SWE-bench 实例上。接口设计的影响量级与模型升级相当。

### 结论 2：LM 是新类别的终端用户
为人类设计的 UI（Linux shell）对 LM 来说是次优接口。论文建立了新的研究方向：**如何为 LM 设计接口**，类比人机交互研究之于人类用户。

### 结论 3：窗口大小的 Goldilocks 效应
文件查看器的最优窗口是 100 行。30 行太少（信息不足），全文件太多（信息过载）。LM 的"有效上下文"有限，不是越多越好。

### 结论 4：防错优于纠错
Linting guardrail 的价值：在错误传播前拦截比在 test 失败后让 agent 回溯更有效（-3pp 差距）。这对所有 agent 系统都有普遍指导意义。

### 结论 5：模型迭代速度快于工具复杂度的必要性
论文发表时（2024 年）需要 10-15 个专用工具的能力，一年后的现代 LM 用单个 bash 工具即可超越。**ACI 的最佳复杂度随模型能力增长而降低**，这意味着 agent 工具设计需要定期重评估。

---

## 十二、参考资料

- 论文：[SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793)（NeurIPS 2024）
- NeurIPS 版本：[proceedings.neurips.cc](https://proceedings.neurips.cc/paper_files/paper/2024/file/5a7c947568c1b1328ccc5230172e1e7c-Paper-Conference.pdf)
- GitHub 仓库：[SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent)
- 官方文档：[swe-agent.com](https://swe-agent.com/latest/)
- SWE-ReX 仓库：[SWE-agent/SWE-ReX](https://github.com/SWE-agent/SWE-ReX)
- SWE-ReX 文档：[swe-rex.com](https://swe-rex.com/latest/)
- mini-swe-agent FAQ：[mini-swe-agent.com/faq](https://mini-swe-agent.com/latest/faq/)
- EnIGMA 论文：[arXiv:2409.16165](https://arxiv.org/abs/2409.16165)
- SWE-bench：[swebench.com](https://www.swebench.com/)
