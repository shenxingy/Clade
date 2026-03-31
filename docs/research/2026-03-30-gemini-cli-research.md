---
name: 2026-03-30-gemini-cli-research.md
date: 2026-03-30
status: integrated
review_date: 2026-03-31
summary:
  - "Gemini CLI: Plan Mode tool-layer isolation, LoopDetectionService, tool distillation, ChatCompressionService"
integrated_items:
  - "Tool distillation — implemented in worker.py _distill_output(). When tool output >200KB, uses haiku to extract key facts (errors, file paths, conclusions), preserves full output in temp file. Significantly better than simple truncation"
needs_work_items:
  - "Behavioral LoopDetectionService — Gemini detects repeated tool+args≥5, content repetition≥10, LLM self-check≥30. Clade has convergence detection (consecutive_no_commits) but not behavioral loop detection within workers"
  - "ChatCompressionService — Gemini has 4-phase proactive compression. Clade has no active context compression service"
  - "Skills with resource bundles — Gemini skills can carry resource folders. Clade skills are text-only"
reference_items:
  - "Plan Mode tool-layer isolation (ApprovalMode enum) — different architecture, not applicable"
  - "LoopDetectionService with 3 detection modes"
---

# Gemini CLI 深度研究报告

**日期**: 2026-03-30  
**版本**: 0.36.0-nightly (Apache 2.0)  
**仓库**: https://github.com/google-gemini/gemini-cli  
**Stars**: ~100K | **Forks**: ~12.7K  
**语言**: TypeScript (Node.js ≥20, React/Ink UI)

---

## 目录

1. [整体架构](#1-整体架构)
2. [ReAct 循环实现](#2-react-循环实现)
3. [Plan Mode 设计](#3-plan-mode-设计)
4. [工具系统](#4-工具系统)
5. [MCP 集成](#5-mcp-集成)
6. [Memory 与上下文管理](#6-memory-与上下文管理)
7. [Google Search Grounding](#7-google-search-grounding)
8. [Checkpointing / 会话持久化](#8-checkpointing--会话持久化)
9. [与 Gemini Code Assist 的关系](#9-与-gemini-code-assist-的关系)
10. [对 Clade 的借鉴模式](#10-对-clade-的借鉴模式)

---

## 1. 整体架构

### 1.1 Monorepo 包结构

```
gemini-cli/
├── packages/
│   ├── cli/               @google/gemini-cli          — 终端 UI 入口 (React/Ink)
│   ├── core/              @google/gemini-cli-core     — 核心业务逻辑
│   ├── a2a-server/        @google/gemini-cli-a2a-server — 实验性 Agent-to-Agent 服务器
│   ├── sdk/               @google/gemini-cli-sdk      — 嵌入式编程 SDK
│   ├── devtools/          @google/gemini-cli-devtools — 调试 / 网络检查工具
│   ├── vscode-ide-companion/  gemini-cli-vscode-ide-companion — VS Code 扩展
│   └── test-utils/        @google/gemini-cli-test-utils (private)
├── bundle/gemini.js        — esbuild 打包产物（单文件可执行）
└── esbuild.config.js       — 将 cli + core 打包为单文件
```

### 1.2 核心包层次（packages/core）

```
packages/core/src/
├── core/                  — 循环引擎
│   ├── client.ts          GeminiClient — ReAct 循环主控
│   ├── geminiChat.ts      GeminiChat   — 历史管理 + API 流式
│   ├── turn.ts            Turn         — 单次 LLM 调用 + 工具收集
│   ├── contentGenerator.ts  内容生成器装饰器
│   ├── tokenLimits.ts     token 预算计算
│   └── prompts.ts         系统 prompt 入口
├── config/
│   ├── config.ts          Config — Service Locator（核心）
│   └── auth.ts            认证方式（API Key / OAuth / OIDC）
├── tools/                 内置工具（见 §4）
├── services/              支撑服务（见各节）
├── policy/                策略引擎
│   ├── policy-engine.ts   PolicyEngine
│   └── types.ts           ApprovalMode enum
├── prompts/
│   └── promptProvider.ts  PromptProvider — 系统 prompt 组装
└── extensions/
    └── extensionManager.ts  ExtensionManager — 技能 / 扩展加载
```

### 1.3 架构图（包级 + 核心类）

```
┌─────────────────────────────────────────────────────────────┐
│                    packages/cli  (React/Ink UI)             │
│                                                             │
│  App  ──→  useGeminiStream hook                            │
│              │                                              │
│              ├── useToolScheduler (tool状态机)              │
│              └── handleApprovalModeChange (模式切换)        │
└────────────────────────┬────────────────────────────────────┘
                         │ GeminiClient API
┌────────────────────────▼────────────────────────────────────┐
│                    packages/core  (业务逻辑)                │
│                                                             │
│  Config (Service Locator)                                   │
│    ├── GeminiClient      ← ReAct 循环主控                   │
│    │     ├── GeminiChat  ← 历史 + 流式 API                  │
│    │     │     └── Turn  ← 单次 LLM 调用                    │
│    │     ├── LoopDetectionService                           │
│    │     ├── AgentHistoryProvider / ChatCompressionService  │
│    │     └── ModelConfigService (Pro/Flash 路由)            │
│    ├── ToolRegistry      ← 工具注册中心                     │
│    │     ├── BuiltinTools (15+)                             │
│    │     ├── McpClientManager → MCPTools                   │
│    │     └── SkillManager → ActivateSkillTool              │
│    ├── PolicyEngine      ← 权限控制                        │
│    ├── PromptProvider    ← 系统 prompt 组装                 │
│    └── ExtensionManager  ← 扩展加载                        │
└─────────────────────────────────────────────────────────────┘
```

### 1.4 启动序列

1. 加载分层 settings（system → user → workspace → CLI args）
2. 解析命令行参数
3. 创建 `Config` 实例（初始化所有服务）
4. 验证认证（API Key / OAuth / OIDC）
5. 渲染 React/Ink UI（交互模式）或直接执行命令（非交互模式）

---

## 2. ReAct 循环实现

ReAct 循环分布在三个类中：`GeminiClient`（主控）、`GeminiChat`（API 层）、`Turn`（单次执行）。

### 2.1 循环架构

```
User Prompt
     │
     ▼
GeminiClient.sendMessageStream()
     │
     ├── 预处理: hooks 校验 / 上下文注入
     │
     ▼
GeminiClient.processTurn()  ◄──────────────────────┐
     │                                              │
     ├── 1. 会话限制检查 (sessionTurnCount)         │
     ├── 2. 上下文管理 (AgentHistoryProvider)       │
     ├── 3. IDE 上下文注入 (editor state JSON)      │
     ├── 4. 循环检测 (LoopDetectionService)        │
     ├── 5. 模型路由 (ModelConfigService)           │
     └── 6. Turn.run()                             │
                │                                  │
                ▼                                  │
       GeminiChat.sendMessageStream()              │
                │                                  │
                ▼ (Stream events)                  │
       ┌────────────────────┐                      │
       │  CHUNK             │ → yield Content      │
       │  RETRY             │ → yield Retry        │
       │  function_call     │ → yield ToolCallRequest
       └────────────────────┘                      │
                │                                  │
      (function_call detected)                     │
                │                                  │
                ▼                                  │
       PolicyEngine.evaluate()                     │
                │                                  │
         ALLOW / ASK_USER / DENY                   │
                │                                  │
                ▼                                  │
       Tool.execute()  → functionResponse          │
                │                                  │
       加入 History                                │
                │                                  │
                └──────────────────────────────────┘
                       (continue loop)

loop 终止条件:
  - turn.pendingToolCalls.length === 0 && model 停止
  - sessionTurnCount >= maxSessionTurns (默认 100)
  - loopDetected = true
  - 用户取消 (AbortSignal)
```

### 2.2 Turn 类 — 单次 LLM 调用

`Turn` 是每个 ReAct 迭代的执行单元：

```typescript
class Turn {
  pendingToolCalls: ToolCallRequestInfo[]
  
  async run(): AsyncGenerator<TurnEvent> {
    // 1. 调用 chat.sendMessageStream()
    // 2. 遍历流式事件
    //    - thought parts → yield Thought
    //    - text parts    → yield Content
    //    - function_call → handlePendingFunctionCall()
    //                       → push to pendingToolCalls
    //                       → yield ToolCallRequest
    // 3. 收集 citations
    // 4. 检查 finishReason
  }
}
```

### 2.3 循环继续机制

`sendMessageStream` 在 `processTurn` 完成后执行两个检查：

1. **Next Speaker Check**: 如果没有 pending tools 且模型应继续，递归调用 `sendMessageStream("Please continue.")`
2. **After-agent Hooks**: 钩子可请求清除上下文并以新消息继续

### 2.4 循环检测（LoopDetectionService）

三种检测模式：

| 模式 | 触发条件 | 阈值 |
|------|----------|------|
| 连续相同工具调用 | 同工具同参数连续调用 | ≥5 次 |
| 内容复诵检测 | 相同文本块密集出现 | ≥10 次，窗口 ≤250 字符 |
| LLM 自检 | 轮次过多时 LLM 分析历史 | ≥30 轮，置信度 ≥0.9 |

检测到循环时注入引导语：`"Potential loop detected...Please take a step back and confirm you're making forward progress"`

### 2.5 Thought Signatures（思考签名）

模型在活跃循环的第一次 function call 上必须有 `thoughtSignature`。`GeminiChat.ensureActiveLoopHasThoughtSignatures()` 会在缺失时注入合成签名 `"skip_thought_signature_validator"` 以通过 API 校验。

### 2.6 Invalid Stream 恢复

API 调用失败时，对 Gemini 2 模型注入：`"System: Please continue."` 触发流恢复。

---

## 3. Plan Mode 设计

Plan Mode 是 Gemini CLI 最具特色的功能之一，体现了"先规划后执行"的工程理念。

### 3.1 核心设计原则

**Plan Mode 不是通过系统 prompt 约束 LLM，而是通过工具层白名单实现硬隔离**：

- 进入 Plan Mode → `config.setApprovalMode(ApprovalMode.PLAN)` → 重新生成工具注册表
- 工具注册表在 Plan Mode 下**只暴露只读工具**给 LLM
- `write_file` / `edit_file` 被限制为**只能写入 plans 目录的 .md 文件**
- LLM 物理上无法调用文件修改工具（工具不在 function declarations 列表里）

### 3.2 ApprovalMode 枚举

```typescript
enum ApprovalMode {
  DEFAULT  = 'default',   // 标准确认流程
  AUTO_EDIT = 'autoEdit', // 自动批准编辑类工具
  YOLO     = 'yolo',      // 全部自动批准（不可信目录禁用）
  PLAN     = 'plan',      // 只读规划模式
}
```

### 3.3 Plan Mode 完整流程

```
用户: "用 Plan Mode 帮我重构这个模块"
         │
         ▼
LLM 调用 enter_plan_mode 工具
         │
         ▼
PolicyEngine 检查 → 显示确认对话框:
  "This will restrict the agent to read-only tools to allow for safe planning."
         │
    用户确认
         │
         ▼
config.setApprovalMode(ApprovalMode.PLAN)
         │
         ├── GeminiClient 清除 currentSequenceModel
         ├── ToolRegistry 重新生成（只暴露只读工具 + 受限写入）
         └── PromptProvider 切换到 planningWorkflow 系统 prompt
                 │
                 ▼ (规划阶段)
       LLM 读取文件 / 搜索 / 分析
       LLM 调用受限 write_file → 只能写 plans/*.md
                 │
                 ▼
       LLM 调用 exit_plan_mode(plan_filename="plans/refactor-plan.md")
                 │
                 ├── 验证 plan 文件路径（防路径遍历）
                 ├── 验证 plan 内容合法性
                 └── 显示确认对话框（用户审批 plan）
                         │
                    用户批准
                         │
                         ▼
       config.setApprovalMode(AUTO_EDIT 或 DEFAULT)
       发送消息给 LLM:
         "The approved implementation plan is stored at: [path].
          Read and follow the plan strictly during implementation."
                         │
                         ▼ (执行阶段)
               LLM 严格按 plan 执行
```

### 3.4 Plan Mode 系统 Prompt 差异

PromptProvider 根据 `approvalMode === ApprovalMode.PLAN` 切换：

| 内容块 | Plan Mode | 正常模式 |
|--------|-----------|----------|
| `planningWorkflow` | ✅ 包含 | ❌ 排除 |
| `primaryWorkflows` | ❌ 排除 | ✅ 包含 |
| `planModeToolsList` | ✅ 显示可用工具及来源 | ❌ |
| plans 目录配置 | ✅ 传入 | ❌ |
| approved plan path | ✅ 传入（供执行引用） | ❌ |

### 3.5 Plan 审批 / 拒绝机制

```
Plan 被批准:
  → "The approved implementation plan is stored at: [path].
     Read and follow the plan strictly during implementation."

Plan 被拒绝（有反馈）:
  → "Plan rejected. User feedback: [feedback].
     The plan is stored at: [path]. Revise the plan based on the feedback."

Plan 被拒绝（无反馈）:
  → "Ask the user for specific feedback on how to improve the plan."
```

### 3.6 Plan Mode 配置

```json
// settings.json
{
  "general": {
    "plan": {
      "directory": "/custom/plans/dir",    // 可选，默认系统临时目录
      "modelRouting": true                  // Pro/Flash 自动切换
    },
    "defaultApprovalMode": "plan"          // 默认进入 Plan Mode
  },
  "experimental": {
    "plan": true                           // 启用 Plan Mode 功能
  }
}
```

---

## 4. 工具系统

### 4.1 完整内置工具列表

```
文件操作:
  read_file           — 读取文件（原生处理大文件，豁免蒸馏）
  read_many_files     — 批量读取（豁免蒸馏）
  write_file          — 创建/覆写文件
  edit_file           — 精确文本替换
  replace             — 目标文本替换

目录/搜索:
  ls                  — 目录列表
  glob                — 文件模式匹配
  grep                — 正则内容搜索
  ripGrep             — 基于 ripgrep 的高速搜索

Shell & Web:
  run_shell_command   — 执行 shell 命令（PTY 支持、沙箱可选）
  web_fetch           — 获取 URL 内容
  google_web_search   — Google Search grounding

规划 & 工作流:
  enter_plan_mode     — 切换到只读规划模式
  exit_plan_mode      — 提交计划并切换回执行模式
  write_todos         — 写入/更新 TODO 列表（单任务 in_progress 约束）
  ask_user            — 向用户提问

记忆 & 上下文:
  memory              — 向 GEMINI.md 写入记忆条目
  jit-context         — 即时上下文加载
  get_internal_docs   — 获取内部文档

技能:
  activate_skill      — 激活命名技能（加载指令 + 资源）

MCP 动态工具:
  (通过 McpClientManager 动态注册)
```

### 4.2 工具接口设计

```typescript
// 工具定义接口
interface ToolBuilder<TParams, TResult> {
  name: string
  displayName: string
  description: string
  kind: ToolKind
  getSchema(): FunctionDeclaration  // Zod → JSON Schema
  build(params: unknown): ToolInvocation<TParams, TResult>
}

// 工具调用接口
interface ToolInvocation<TParams, TResult> {
  getDescription(): string           // markdown 描述（UI 显示）
  shouldConfirmExecute(): Promise<ConfirmationDecision>
  execute(signal: AbortSignal): Promise<TResult>
  toolLocations(): string[]          // 受影响的文件路径
}
```

### 4.3 工具执行流水线

```
LLM function_call
      │
      ▼
ToolRegistry.lookup(name)
      │
      ▼
ToolBuilder.build(args)    ← 参数验证 (Zod)
      │
      ▼
PolicyEngine.evaluate()
      │
  ┌───┴───┐
ALLOW   ASK_USER            DENY
  │       │                  │
  │   UI 确认对话框          报错
  │       │
  └───────┤
          ▼
Tool.execute() → Result
          │
          ▼
ToolDistillationService     ← 大输出截断 + LLM 摘要
          │
          ▼
functionResponse → History → 下一轮 LLM
```

### 4.4 PolicyEngine 规则匹配

规则匹配优先级（高→低），决策类型：

- `ALLOW` — 直接执行
- `ASK_USER` — 弹确认框（默认对修改类工具）
- `DENY` — 直接拒绝

Shell 命令有额外启发式规则：
- 已知危险命令 → 强制 `ASK_USER`
- 已知安全命令 → 可覆盖 `ASK_USER` 为 `ALLOW`
- 包含输出重定向 → 降级为 `ASK_USER`

### 4.5 工具输出蒸馏（ToolDistillationService）

处理大输出以保护 context window：

1. **豁免**: 文件读取工具原生处理大文件，不走蒸馏
2. **阈值评估**: 超过 token 限制触发蒸馏
3. **全蒸馏流程**:
   - 保存原始完整输出到临时文件（供人类查看）
   - 超大输出调用辅助 LLM 提取关键事实（错误信息、文件路径、结果）
   - 按比例截断原始输出，保留结构，追加临时文件位置
4. **超时保护**: 摘要生成 15 秒超时，失败时降级为纯截断

### 4.6 沙箱（SandboxManager）

可选沙箱隔离，两种实现：
- `NoopSandboxManager` — 透传，仅清理环境变量
- `LocalSandboxManager` — 完整沙箱（尚未完全实现）

沙箱规则：
- 工作区（workspace）：完整读写
- 禁止路径（forbidden）：覆盖白名单
- 治理文件（`.git`, `.gitignore`, `.geminiignore`）：写保护
- 机密文件（`.env`, `.env.*`）：完全隐藏
- 环境变量：清理敏感凭证（可配置策略）
- Symlink 解析防沙箱逃逸

---

## 5. MCP 集成

### 5.1 settings.json 完整格式

```json
// ~/.gemini/settings.json 或工作区 .gemini/settings.json
{
  "mcpServers": {
    "server-name": {
      // --- Stdio 传输（本地进程）---
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
      "env": {
        "NODE_ENV": "production"
      },
      
      // --- SSE 传输（服务器推送）---
      // "url": "http://localhost:3001/sse",
      // "type": "sse",
      
      // --- HTTP 传输（REST）---
      // "url": "http://localhost:3001/mcp",
      // "type": "http",
      
      // --- 通用选项 ---
      "timeout": 600000,            // ms，默认 10 分钟
      "trust": false,               // true = 自动批准该服务器的工具
      "includeTools": ["tool_a"],   // 工具白名单（空 = 全部）
      "excludeTools": ["tool_b"],   // 工具黑名单（优先于 includeTools）
      
      // --- OAuth（企业）---
      "authProviderType": "oauth",
      "oauth": { ... }
    }
  },
  
  "general": {
    "defaultApprovalMode": "default",   // default|auto_edit|plan|yolo
    "devtools": false,
    "plan": {
      "directory": "/path/to/plans",
      "modelRouting": true
    }
  },
  
  "experimental": {
    "plan": true,
    "extensionReloading": true,
    "modelSteering": true,
    "memoryManager": true,
    "topicUpdateNarration": true
  },
  
  "security": {
    "toolSandboxing": false
  }
}
```

### 5.2 传输协议支持

| 传输类型 | 配置字段 | 适用场景 |
|----------|----------|----------|
| stdio | `command` + `args` | 本地进程，要求 trusted folder |
| SSE | `url` + `type: "sse"` | 远程服务器实时推送 |
| HTTP | `url` + `type: "http"` | RESTful JSON，支持 OAuth |

### 5.3 工具发现流程

```
McpClientManager 初始化
      │
      ├── 遍历 settings.mcpServers
      │
      ▼ 对每个 server:
McpClient.connect()
      │
      ├── 选择传输 (stdio/SSE/HTTP)
      ├── 执行 listTools()
      ├── 过滤 (excludeTools > includeTools)
      └── 包装为 DiscoveredMCPTool 注册到 ToolRegistry

动态更新:
  - server 发出 listChanged 通知 → 合并刷新（防抖）
  - 避免快速连续通知导致过度请求
```

### 5.4 信任模型

- `trust: false`（默认）：该服务器的工具需要用户确认
- `trust: true`：自动批准
- 不可信目录下：MCP stdio 服务器**无法连接**（安全限制）

### 5.5 OAuth 自动处理

1. 捕获 401 错误
2. 解析 `www-authenticate` 头
3. 从服务器元数据发现 OAuth 配置
4. 执行 OAuth 流程，存储 token（`MCPOAuthTokenStorage`）
5. 用 Bearer token 重试连接

### 5.6 settings.json 分层加载

```
system settings (内置默认值)
      ↓ (SHALLOW_MERGE)
user settings (~/.gemini/settings.json)
      ↓ (SHALLOW_MERGE)
workspace settings (.gemini/settings.json)
      ↓ (SHALLOW_MERGE)
CLI args (--yolo, --model 等)
      ↓
最终 Config
```

合并策略：`REPLACE`（覆盖）| `CONCAT`（数组追加）| `UNION`（去重合并）| `SHALLOW_MERGE`（对象浅合并）

---

## 6. Memory 与上下文管理

### 6.1 Memory 存储（GEMINI.md）

Memory Tool 将事实存入 Markdown 文件：

```
存储位置:
  全局:   ~/.gemini/GEMINI.md
  项目:   <project>/.gemini/GEMINI.md
  扩展:   <extension-dir>/GEMINI.md

存储格式 (Markdown 列表):
  ## Gemini Added Memories
  - 用户偏好：使用 TypeScript strict 模式
  - 项目约定：所有 API 返回标准 Result<T, E> 类型
  - ...

安全措施:
  - 防止 Markdown 注入（折叠为单行，移除开头破折号）
  - 写入前展示 diff 供用户确认
  - allowlist 防止同文件重复确认
```

### 6.2 上下文加载层次（ContextManager）

分层加载，4 个作用域：

```
Global Memory     → 系统级指令
      ↓
Extension Memory  → 插件专用上下文
      ↓
Environment/Project Memory → 工作区专用数据
      ↓
User Project Memory → 用户创建的指令（仅 trustedFolder）
```

**JIT（Just-In-Time）加载**：`discoverContext()` 从访问路径向上遍历，而非预先加载全部内容，降低启动时 token 消耗。

**去重**：通过文件 identity 去重，处理大小写不敏感文件系统。

### 6.3 Context Window 压缩（ChatCompressionService）

**压缩触发**: 历史超过模型 token 上限的 **50%**

**多阶段策略**:

```
阶段 1: Tool Response 截断
  - 倒序遍历 function responses
  - 超过 50,000 token 预算的旧响应被截断
  - 保留近期响应的完整性

阶段 2: 历史分割
  - findCompressSplitPoint() 找到分割点
  - 保留最近 30% 的对话完整
  - 压缩前 70%

阶段 3: LLM 摘要
  - 将旧历史发给 Gemini 请求生成 <state_snapshot>
  - 摘要包含：主要目标 / 已验证事实 / 当前文件路径 / 活跃阻塞点

阶段 4: 自校正
  - 第二次 LLM 检查摘要是否遗漏细节
  - 如有遗漏，生成改进版本
  
安全保障:
  - 压缩后 token 必须 < 压缩前，否则拒绝结果
  - 之前摘要失败 → 仅执行截断，不重试 LLM（避免重复成本）
```

### 6.4 AgentHistoryProvider（高水位标记策略）

```
Token 高水位触发 → manageHistory()
      │
      ├── 近期消息: 高 token 限制（maximumMessageTokens）
      ├── 旧消息: 降低为正常限制（normalMessageTokens）
      └── 保持 function call/response 对不被拆分（结构完整性）

摘要标签:
  <intent_summary>
    当前目标: ...（最多 15 行）
    已验证事实: ...
    工作文件: ...
    活跃阻塞: [精确错误信息]
  </intent_summary>
```

### 6.5 Session Summary（会话摘要）

`SessionSummaryService` 为历史记录生成 80 字符以内的单行摘要：

- 过滤系统消息，仅保留 user/assistant 对话
- 超过 20 条消息时取"前 N + 后 N"滑动窗口
- 单条消息超 500 字符截断
- 5 秒超时保护，失败返回 `null`（不抛异常）
- 使用 Gemini Flash Lite（最轻量模型）

---

## 7. Google Search Grounding

### 7.1 实现机制

**不是通过外部 API Key**，而是通过 Gemini API 的内置搜索能力：

```typescript
// web-search.ts 关键逻辑
const response = await geminiClient.generateContent({
  model: 'web-search',   // 特殊模型标识
  contents: [{ text: query }]
})

// 响应包含 groundingMetadata:
// {
//   groundingChunks: [{ uri, title }],    // 来源列表
//   groundingSupports: [{
//     segment: { startIndex, endIndex },  // UTF-8 字节位置
//     groundingChunkIndices: [0, 2]       // 引用来源索引
//   }]
// }
```

### 7.2 Citation 注入流程

```
1. 获取 groundingSupports（倒序处理避免索引偏移）
2. 在文本字节位置插入 [n] 引用标记
3. 末尾追加格式化来源列表
4. 返回带 citation 的完整文本
```

### 7.3 Model 路由

`google_web_search` 工具使用 `'web-search'` 作为 model 参数调用 `generateContent()`。这意味着搜索能力是 Gemini API 的原生功能，CLI 仅作透传。这是与 Claude Code（集成外部 Brave Search API）的根本性差异。

---

## 8. Checkpointing / 会话持久化

### 8.1 SessionSummaryService 作为轻量 Checkpointing

Gemini CLI **没有完整的会话保存/恢复机制**（类似 Claude Code 的 `/handoff`），但有以下支撑机制：

- `SessionSummaryService`：为每次会话生成摘要（支持会话历史展示）
- `ChatRecordingService`：记录完整对话（含工具调用元数据）
- `WorktreeService`：通过 git worktree 实现并行会话隔离

### 8.2 Plan Mode 的隐式 Checkpointing

Plan Mode 的 `exit_plan_mode(plan_filename)` 本质上是一种人工检查点：

1. Plan 文件持久化到磁盘（`.md` 文件）
2. 执行阶段收到 `"Read and follow the plan strictly"` 指令
3. 即使会话中断，plan 文件仍在磁盘，可重新引用

### 8.3 Worktree 隔离（并行 Agent 支持）

```
WorktreeService:
  - 路径: .gemini/worktrees/{name}
  - 分支: worktree-{name}
  - baseSha 快照：用于 hasWorktreeChanges() 检测
  - maybeCleanup()：清理未修改的 worktree
  - 注意: 无显式锁机制，同 worktree 并发有竞态风险
```

---

## 9. 与 Gemini Code Assist 的关系

### 9.1 认证共享

Gemini CLI 支持多种认证方式：

| 方式 | 场景 |
|------|------|
| `GEMINI_API_KEY` 环境变量 | 个人 / 免费层 |
| OAuth（Google 账号）| Google One / 付费层 |
| OIDC + Service Account | 企业 / GCP 环境 |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI 后端 |

企业模式下可使用 Service Account Impersonation，这与 Gemini Code Assist 共享相同的 GCP 认证体系。

### 9.2 后端共享推断

- 都使用 `@google/genai` SDK
- 都支持 Vertex AI 后端（`GOOGLE_CLOUD_PROJECT` 环境变量）
- 共享 OAuth / OIDC 认证流程
- 共享 MCP 协议支持

**但两者是独立产品**：Code Assist 是 IDE 插件（VS Code / JetBrains），Gemini CLI 是终端工具。CLI 包含实验性 `vscode-ide-companion` 包，可与 VS Code 的 Gemini Code Assist 扩展配对，共享 IDE 上下文（打开文件、光标位置等）。

### 9.3 VS Code 集成

`packages/vscode-ide-companion` 与 `packages/cli` 通信，在 `processTurn` 中注入 IDE 上下文：

```
"Here is the user's editor context as a JSON object."
{
  openFiles: [...],
  activeFile: "...",
  cursorPosition: {...},
  selection: "..."
}
```

---

## 10. 对 Clade 的借鉴模式

### 10.1 Plan Mode — 最值得借鉴的设计

**核心洞察**: Plan Mode 的力量不来自 prompt 约束，而来自工具层隔离。

**借鉴方案**：

```python
# 在 Clade 的 worker.py 中
class ApprovalMode(Enum):
    DEFAULT = "default"
    PLAN = "plan"      # 只读规划
    YOLO = "yolo"      # 全部自动批准

# Worker 启动时根据模式选择工具集
def get_tools_for_mode(mode: ApprovalMode) -> list[Tool]:
    if mode == ApprovalMode.PLAN:
        return READ_ONLY_TOOLS + [write_plan_tool]  # 只暴露只读工具
    return ALL_TOOLS
```

**Plan 文件审批循环**：
```
LLM 生成 plan → 写入 plans/*.md → 用户审批 → 
  批准 → 切换到执行模式 + 注入"严格按 plan 执行"
  拒绝 + 反馈 → LLM 修订 plan
```

这对 Clade 的 `/loop` 改进非常有价值：当前 loop 缺少"规划 → 审批 → 执行"的安全门控。

### 10.2 循环检测（LoopDetectionService）

Clade 的 loop-runner 目前没有循环检测。借鉴 Gemini 的三层策略：

1. **浅层检测**：相同工具相同参数连续 5+ 次 → 注入引导语
2. **LLM 自检**：每 N 轮让 LLM 分析自己是否在空转
3. **计数限制**：`MAX_TURNS = 100`（Clade 已有类似机制）

### 10.3 工具输出蒸馏

当工具输出过大时，用辅助 LLM 提取关键事实而非简单截断：

```python
# 借鉴 ToolDistillationService
async def distill_tool_output(output: str, intent: str) -> str:
    if token_count(output) < THRESHOLD:
        return output
    # 1. 保存完整输出到临时文件
    # 2. 用轻量模型提取关键信息
    summary = await llm_summarize(output, 
        prompt="提取关键事实：错误信息、文件路径、确定性结论")
    return summary + f"\n[完整输出: {tmp_path}]"
```

### 10.4 Context 压缩策略

Gemini 的 `ChatCompressionService` 提供了比 Clade 目前更精细的策略：

| 策略 | Gemini | Clade 现状 |
|------|--------|-----------|
| 压缩触发阈值 | 50% token 上限 | 无 |
| Tool response 截断 | 50K token 预算 | 无 |
| LLM 摘要 | `<state_snapshot>` | TLDR（部分） |
| 自校正验证 | 二次 LLM 检查 | 无 |
| 保留比例 | 最近 30% 完整 | 无 |

**建议**: Clade 的 `worker_tldr.py` 可以升级为类似的 `ChatCompressionService`。

### 10.5 技能系统对比

Gemini 的 Skills 与 Clade 的 Skills 高度相似：

| 特性 | Gemini CLI | Clade |
|------|-----------|-------|
| 存储格式 | 目录 + 描述文件 | `.md` 文件 |
| 激活方式 | `activate_skill` 工具调用 | `/skill-name` slash command |
| 动态加载 | 运行时激活 | 安装时复制 |
| 资源打包 | 技能目录随 workspace | 无 |
| 确认要求 | 非内置技能需确认 | 无 |

**借鉴**：Gemini 的技能可以包含**资源文件夹**，随技能激活加入 workspace 上下文。这让技能可以携带模板、示例、配置文件等。Clade 目前技能只有 prompt 文本。

### 10.6 Google Search Grounding vs. Claude Code 外部搜索

| 维度 | Gemini CLI | Claude Code |
|------|-----------|-------------|
| 实现方式 | Gemini API 原生能力 | 外部 Brave Search API |
| 配置复杂度 | 零配置 | 需要 API Key |
| 结果质量 | Google 搜索 | Brave 搜索 |
| Citation | 自动注入 `[n]` 标注 | 手动处理 |
| 成本 | 包含在 API 调用中 | 额外 API 费用 |

Clade 不直接涉及搜索，但 Grounding 的 citation 注入模式值得参考。

### 10.7 WorktreeService — 并行 Worker 隔离

Gemini 用 git worktree 实现并行 agent 隔离，与 Clade 的 loop-runner.sh 思路相同。

Gemini 的改进点：
- 基于 `baseSha` 的精确变更检测（Clade 目前用目录存在性判断）
- `maybeCleanup()` 自动清理无变更的 worktree（Clade 缺少此功能）

### 10.8 A2A（Agent-to-Agent）协议

`packages/a2a-server` 实现了标准 A2A HTTP 协议，让多个 Gemini CLI 实例互相调用。这对 Clade 未来的多 agent 编排有参考价值（目前 Clade 通过 `SwarmManager` 实现，但无标准协议）。

---

## 附录：关键源文件路径

```
packages/core/src/core/client.ts           — ReAct 循环主控
packages/core/src/core/geminiChat.ts       — 历史管理 + API 流式
packages/core/src/core/turn.ts             — 单次 LLM 调用
packages/core/src/tools/enter-plan-mode.ts — Plan Mode 入口
packages/core/src/tools/exit-plan-mode.ts  — Plan Mode 出口 + 审批
packages/core/src/tools/web-search.ts      — Google Search grounding
packages/core/src/tools/memoryTool.ts      — GEMINI.md 记忆写入
packages/core/src/tools/tool-registry.ts   — 工具注册 + 模式过滤
packages/core/src/services/chatCompressionService.ts   — 历史压缩
packages/core/src/services/agentHistoryProvider.ts     — 上下文管理
packages/core/src/services/loopDetectionService.ts     — 循环检测
packages/core/src/services/toolDistillationService.ts  — 输出蒸馏
packages/core/src/services/worktreeService.ts          — 并行隔离
packages/core/src/services/sessionSummaryService.ts    — 会话摘要
packages/core/src/policy/policy-engine.ts  — 权限策略引擎
packages/core/src/policy/types.ts          — ApprovalMode enum
packages/core/src/prompts/promptProvider.ts — 系统 prompt 组装
packages/core/src/config/config.ts         — Service Locator
packages/cli/src/ui/hooks/useGeminiStream.ts — 前端工具调度
packages/cli/src/config/settingsSchema.ts  — settings.json schema
```

---

*研究基于 google-gemini/gemini-cli main 分支，版本 0.36.0-nightly.20260317*
