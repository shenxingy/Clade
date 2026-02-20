[English](README.md) | **中文**

# Claude Code Kit

**把 Claude Code 从聊天助手变成自主编码系统。**

一个安装脚本。五个 hooks、四个 agents、三个 skills，以及一个纠正学习循环 — 协同工作，让 Claude 编码更好、自动捕获错误、跨会话记住你的偏好。

## 安装（30 秒）

```bash
git clone https://github.com/shenxingy/claude-code-kit.git
cd claude-code-kit
./install.sh
```

启动新的 Claude Code 会话即可激活所有功能。

> **依赖：** `jq`（用于合并 settings）。其他一切都是可选的。

## 支持的语言和框架

自动检测 — hooks 和 agents 会适配你的项目类型：

| 语言 | 编辑检查 | 任务门禁 | 类型检查器 | 测试执行器 |
|------|---------|---------|-----------|-----------|
| **TypeScript / JavaScript** | `tsc`（monorepo 感知） | type-check + build | tsc | jest / vitest / npm test |
| **Python** | pyright / mypy | ruff + pyright/mypy | pyright / mypy | pytest |
| **Rust** | `cargo check` | cargo check + test | cargo check | cargo test |
| **Go** | `go vet` | go build + vet + test | go vet | go test |
| **Swift / iOS** | `swift build` | swift build / xcodebuild | swift build | swift test / xcodebuild test |
| **Kotlin / Android / Java** | `gradlew compile` | gradle compile + test | gradle compile | gradle test |
| **LaTeX** | `chktex` | chktex（警告） | chktex | — |

所有检查**按检测自动启用** — 如果工具未安装或项目标记不存在，hook 会静默跳过。

## 安装后会发生什么

| 时机 | 触发什么 | 做了什么 |
|------|---------|---------|
| 在 git 仓库中打开 Claude Code | `session-context.sh` | 加载 git 上下文、纠正规则和模型选择指南到上下文 |
| Claude 编辑代码文件 | `post-edit-check.sh` | **异步**运行语言对应的检查（tsc、pyright、cargo check、go vet、swift build、gradle、chktex） |
| 你纠正 Claude（"错了，用 X"） | `correction-detector.sh` | 记录纠正，提示 Claude 保存可复用的规则 |
| Claude 标记任务完成 | `verify-task-completed.sh` | 自适应质量门禁：检查编译/lint，严格模式额外运行 build + test |
| Claude 需要权限 / 空闲 | `notify-telegram.sh` | 发送 Telegram 提醒，不用盯着终端 |
| 会话结束 | Stop hook (settings.json) | 验证所有任务已完成后才退出 |

## 可用命令

| 命令 | 功能 |
|------|------|
| `/batch-tasks` | 解析 TODO.md，自动规划每个任务，通过 `claude -p` 执行（串行或并行） |
| `/batch-tasks step2 step4` | 规划 + 执行指定 TODO 步骤 |
| `/batch-tasks --parallel` | 通过 git worktrees 并行执行 |
| `/sync` | 更新 TODO.md（勾掉完成项）+ 追加会话总结到 PROGRESS.md |
| `/commit` | 按模块拆分未提交的改动，分多个逻辑 commit 提交并推送 |
| `/commit --no-push` | 同上，但跳过推送 |
| `/commit --dry-run` | 仅展示拆分计划，不实际提交 |
| `/review` | 全面技术债务审查 — 自动将 Critical/Warning 发现写入 TODO.md |
| `/model-research` | 搜索最新 Claude 模型数据，显示变化 |
| `/model-research --apply` | 同上 + 更新模型指南、会话上下文和批量任务配置 |

## 什么时候用什么

**直接对话** — 日常大部分工作：
- 修 bug、小功能、重构、问代码相关的问题
- Claude 自动判断复杂度，需要时自己进入 plan mode
- 技巧：描述要具体。"给 API client 加一个指数退避的重试机制" 比 "优化一下 API client" 好得多

**`/batch-tasks`** — 有结构化的 TODO 列表时：
- 多步骤实现，拆成独立任务
- 任务不冲突时用 `--parallel`
- TODO.md 条目越清晰越好 — 模糊的任务会得到低分，可能被跳过

**`/review`** — 大版本发布前或接手新代码库时：
- 找死代码、类型问题、安全风险、文档过期
- Critical 和 Warning 级别发现会自动写入 TODO.md 的 `## Tech Debt` 区块
- 定期跑一下 — 技术债积累得比你想的快

**`/sync`** — 每次编码会话结束时：
- 勾掉完成的 TODO 项，把经验教训记录到 PROGRESS.md
- 不提交 — 之后跑 `/commit` 把代码 + 文档一起按模块拆分提交
- 这是构建团队记忆的方式 — 跳过它，你就会重复过去的错误

**`/commit`** — 准备提交时：
- 分析所有未提交的改动，按模块（schema、API、前端、配置、文档等）拆分成逻辑清晰的 commits
- 默认推送；`--no-push` 跳过推送，`--dry-run` 仅预览拆分计划

## 工作原理

### Hooks（自动行为）

| Hook | 触发时机 | 模型开销 |
|------|---------|---------|
| `session-context.sh` | SessionStart | 无（纯 shell） |
| `post-edit-check.sh` | PostToolUse (Edit/Write) | 无（纯 shell） |
| `correction-detector.sh` | UserPromptSubmit | 无（纯 shell） |
| `verify-task-completed.sh` | TaskCompleted | 无（纯 shell） |
| `notify-telegram.sh` | Notification | 无（纯 shell） |

所有 hooks 都是 shell 脚本 — 零 API 开销，亚秒级执行。

### Agents（专用子代理）

| Agent | 模型 | 用途 |
|-------|------|------|
| `code-reviewer` | Sonnet | 带持久记忆的代码审查 |
| `verify-app` | Sonnet | 运行时验证 — 适配项目类型（Web、Rust、Go、Swift、Gradle、LaTeX） |
| `type-checker` | Haiku | 快速类型/编译检查 — 自动检测语言（TS、Python、Rust、Go、Swift、Kotlin、LaTeX） |
| `test-runner` | Haiku | 测试执行 — 自动检测框架（pytest、jest、cargo test、go test、swift test、gradle、make） |

Claude 自动选择 agent。Haiku agent 速度快、成本低，用于机械性检查；Sonnet agent 推理更深入，用于审查和验证。

### Skills（斜杠命令）

**`/batch-tasks`** 读取 TODO.md，研究代码库，为每个任务生成详细计划，进行就绪度评分（scout scoring），自动为每个任务分配最优模型（haiku 处理机械性任务、sonnet 处理常规任务、opus 处理复杂任务），然后通过 `claude -p` 执行。支持串行和并行（git worktree）执行。

**`/sync`** 审查最近的 git 历史，勾掉已完成的 TODO 项，追加会话总结到 PROGRESS.md。不提交 — 之后跑 `/commit` 统一处理。

**`/commit`** 分析所有未提交改动，按模块分组（schema、API、前端、配置、文档等），生成 commit message，展示计划并确认，然后依序提交并推送。`--no-push` 跳过推送；`--dry-run` 仅展示计划。

**`/model-research`** 搜索最新的 Claude 模型发布、基准测试和定价信息。与当前指南对比并显示变化。使用 `--apply` 时，更新 `docs/research/models.md`、会话上下文中的模型指南和批量任务的模型分配逻辑。

### 纠正学习循环

最独特的功能。工作原理：

```
你纠正 Claude              correction-detector.sh         Claude 保存规则
（"别用相对路径        ──>  通过关键词匹配检测      ──>  到 corrections/
  导入"）                   纠正模式                       rules.md

下次会话启动              session-context.sh              Claude 自动遵循
                      ──>  加载 rules.md 到          ──>  规则，无需再次
                           系统上下文                      告知
```

随着时间推移，Claude 的行为自动对齐你的风格。质量门禁（`verify-task-completed.sh`）也会自适应 — Claude 错误多的领域会自动触发更严格的检查。

错误率按领域追踪在 `~/.claude/corrections/stats.json`：
```json
{
  "frontend": 0.35,  // >0.3 = 严格模式（额外 build + test）
  "backend": 0.05,   // <0.1 = 宽松模式（仅基础检查）
  "ml": 0.2,         // ML/AI 训练代码
  "ios": 0,          // Swift / Xcode
  "android": 0,      // Kotlin / Gradle
  "systems": 0,      // Rust / Go
  "academic": 0,     // LaTeX
  "schema": 0.2
}
```

### Scripts（任务执行器）

| 脚本 | 功能 |
|------|------|
| `run-tasks.sh` | 串行执行，支持超时、重试和回滚 |
| `run-tasks-parallel.sh` | 基于 git worktrees 的并行执行 |

两者都由 `/batch-tasks` 调用 — 不需要直接运行。

### 自动模型选择

Kit 在每个层级优化模型使用：

| 层级 | 工作方式 |
|------|---------|
| **会话启动** | `session-context.sh` 注入模型指南 — Claude 会在遇到复杂重构时建议切换到 Opus |
| **批量任务** | 每个任务根据复杂度和性价比数据自动分配 haiku/sonnet/opus |
| **子代理** | Haiku 处理机械性检查（类型检查、测试），Sonnet 处理推理（审查、验证） |
| **保持最新** | 新模型发布时运行 `/model-research --apply` 更新所有选择逻辑 |

基于基准测试：Sonnet 4.6 在 SWE-bench 上得分 79.6%，Opus 4.6 为 80.8%，但 Sonnet 只需 60% 的成本。Kit 默认使用 Sonnet，仅在任务确实需要时才升级到 Opus。

## 配置

### 必需

无需任何配置。开箱即用，默认设置即可正常工作。

### 可选

在 `~/.claude/settings.json` 的 `"env"` 中设置：

| 变量 | 用途 |
|------|------|
| `TG_BOT_TOKEN` | Telegram 机器人 token（用于通知） |
| `TG_CHAT_ID` | Telegram 聊天 ID（用于通知） |

### 调优

| 文件 | 可调内容 |
|------|----------|
| `~/.claude/corrections/rules.md` | 直接添加/编辑纠正规则 |
| `~/.claude/corrections/stats.json` | 调整各领域错误率（0-1）以控制质量门禁严格度 |

## 自定义

### 手动添加纠正规则

编辑 `~/.claude/corrections/rules.md`：
```
- [2026-02-17] imports: Use @/ path aliases instead of relative paths
- [2026-02-17] naming: Use camelCase for TypeScript variables, not snake_case
```

### 调整质量门禁阈值

编辑 `~/.claude/corrections/stats.json`：
```json
{
  "frontend": 0.4,
  "backend": 0.05,
  "ml": 0.2,
  "ios": 0,
  "android": 0,
  "systems": 0,
  "academic": 0,
  "schema": 0.2
}
```

`> 0.3` 触发严格模式（额外 build + test 检查）。`< 0.1` 触发宽松模式（仅基础检查）。领域分类：`frontend`、`backend`、`ml`、`ios`、`android`、`systems`（Rust/Go）、`academic`（LaTeX）、`schema`。

### 添加新 Hook

1. 在 `configs/hooks/your-hook.sh` 创建脚本
2. 在 `configs/settings-hooks.json` 中添加 hook 定义
3. 运行 `./install.sh`

### 添加新 Agent

1. 在 `configs/agents/your-agent.md` 创建 markdown 文件，包含 frontmatter（name、description、tools、model）
2. 运行 `./install.sh`

### 添加新 Skill

1. 创建 `configs/skills/your-skill/SKILL.md`（frontmatter + 描述）
2. 创建 `configs/skills/your-skill/prompt.md`（完整 skill prompt）
3. 运行 `./install.sh`

## 仓库结构

```
claude-code-kit/
├── install.sh                         # 一键部署
├── uninstall.sh                       # 干净卸载
├── configs/
│   ├── settings-hooks.json            # Hook 定义（合并到 settings.json）
│   ├── hooks/
│   │   ├── session-context.sh         # SessionStart: 加载 git 上下文 + 纠正规则
│   │   ├── post-edit-check.sh         # PostToolUse: 编辑后异步类型检查
│   │   ├── notify-telegram.sh         # Notification: Telegram 提醒
│   │   ├── verify-task-completed.sh   # TaskCompleted: 自适应质量门禁
│   │   └── correction-detector.sh     # UserPromptSubmit: 从纠正中学习
│   ├── agents/
│   │   ├── code-reviewer.md           # Sonnet 代码审查器（带记忆）
│   │   ├── test-runner.md             # Haiku 测试执行器
│   │   ├── type-checker.md            # Haiku 类型检查器
│   │   └── verify-app.md              # Sonnet 应用验证器
│   ├── skills/
│   │   ├── batch-tasks/               # /batch-tasks skill
│   │   │   ├── SKILL.md
│   │   │   └── prompt.md
│   │   ├── sync/                      # /sync skill
│   │   │   ├── SKILL.md
│   │   │   └── prompt.md
│   │   ├── commit/                    # /commit skill
│   │   │   ├── SKILL.md
│   │   │   └── prompt.md
│   │   └── model-research/            # /model-research skill
│   │       ├── SKILL.md
│   │       └── prompt.md
│   ├── scripts/
│   │   ├── run-tasks.sh               # 串行任务执行器
│   │   └── run-tasks-parallel.sh      # 并行执行器（git worktrees）
│   └── commands/
│       └── review.md                  # /review 技术债务审查命令
├── templates/
│   ├── settings.json                  # settings.json 模板（不含密钥）
│   └── corrections/
│       ├── rules.md                   # 纠正规则初始模板
│       └── stats.json                 # 领域错误率初始值
└── docs/
    └── research/
        ├── hooks.md                   # Hook 系统深入研究
        ├── subagents.md               # 自定义 Agent 模式
        ├── batch-tasks.md             # 批量执行研究
        ├── models.md                  # 模型对比与选择指南
        └── power-users.md             # 顶级用户的使用模式
```

## 卸载

```bash
./uninstall.sh
```

移除所有已部署的 hooks、agents、skills、scripts 和 commands。保留：
- `~/.claude/corrections/`（你的学习规则和历史）
- `~/.claude/settings.json`（环境变量和权限 — 仅移除 hooks）
- 非本仓库管理的 skills

## 了解更多

- [Hooks 研究](docs/research/hooks.md) — Hook 系统深入研究
- [Subagents 研究](docs/research/subagents.md) — 自定义 Agent 模式
- [批量任务研究](docs/research/batch-tasks.md) — 批量执行改进
- [模型选择指南](docs/research/models.md) — 性价比分析与选择规则
- [高级用户研究](docs/research/power-users.md) — 顶级用户的使用模式

## License

[MIT](LICENSE)
