[English](README.md) | **中文**

# Claude Code Kit

**把 Claude Code 从聊天助手变成自主编码系统。**

一个安装脚本。五个 hooks、四个 agents、两个 skills，以及一个纠正学习循环 — 协同工作，让 Claude 编码更好、自动捕获错误、跨会话记住你的偏好。

## 安装（30 秒）

```bash
git clone https://github.com/shenxingy/claude-code-kit.git
cd claude-code-kit
./install.sh
```

启动新的 Claude Code 会话即可激活所有功能。

> **依赖：** `jq`（用于合并 settings）。其他一切都是可选的。

## 安装后会发生什么

| 时机 | 触发什么 | 做了什么 |
|------|---------|---------|
| 在 git 仓库中打开 Claude Code | `session-context.sh` | 加载最近提交、分支状态、docker 状态和学到的纠正规则到上下文 |
| Claude 编辑 `.ts`/`.tsx`/`.py` 文件 | `post-edit-check.sh` | **异步**运行类型检查 — 错误以系统消息出现，不阻塞工作 |
| 你纠正 Claude（"错了，用 X"） | `correction-detector.sh` | 记录纠正，提示 Claude 保存可复用的规则 |
| Claude 标记任务完成 | `verify-task-completed.sh` | 自适应质量门禁：始终类型检查，错误率高时额外构建检查 |
| Claude 需要权限 / 空闲 | `notify-telegram.sh` | 发送 Telegram 提醒，不用盯着终端 |
| 会话结束 | Stop hook (settings.json) | 验证所有任务已完成后才退出 |

## 可用命令

| 命令 | 功能 |
|------|------|
| `/batch-tasks` | 解析 TODO.md，自动规划每个任务，通过 `claude -p` 执行（串行或并行） |
| `/batch-tasks step2 step4` | 规划 + 执行指定 TODO 步骤 |
| `/batch-tasks --parallel` | 通过 git worktrees 并行执行 |
| `/sync` | 更新 TODO.md（勾掉完成项）+ 追加会话总结到 PROGRESS.md |
| `/sync --commit` | 同上 + 提交文档更改 |
| `/review` | 当前项目的全面技术债务审查 |

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
- 定期跑一下 — 技术债积累得比你想的快

**`/sync`** — 每次编码会话结束时：
- 勾掉完成的 TODO 项，把经验教训记录到 PROGRESS.md
- `--commit` 把文档更新打包成 git commit
- 这是构建团队记忆的方式 — 跳过它，你就会重复过去的错误

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
| `verify-app` | Sonnet | 运行时验证（API 路由、页面、构建） |
| `type-checker` | Haiku | 快速 TypeScript/Python 类型验证 |
| `test-runner` | Haiku | 测试执行与失败分析 |

Claude 自动选择 agent。Haiku agent 速度快、成本低，用于机械性检查；Sonnet agent 推理更深入，用于审查和验证。

### Skills（斜杠命令）

**`/batch-tasks`** 读取 TODO.md，研究代码库，为每个任务生成详细计划，进行就绪度评分（scout scoring），然后通过 `claude -p` 执行。支持串行和并行（git worktree）执行。

**`/sync`** 审查最近的 git 历史，勾掉已完成的 TODO 项，追加会话总结到 PROGRESS.md，可选提交。

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

错误率追踪在 `~/.claude/corrections/stats.json`：
```json
{
  "frontend": 0.35,  // >0.3 = 严格模式（类型检查 + 构建）
  "backend": 0.05,   // <0.1 = 宽松模式（仅类型检查）
  "schema": 0.2      // 默认模式（仅类型检查）
}
```

### Scripts（任务执行器）

| 脚本 | 功能 |
|------|------|
| `run-tasks.sh` | 串行执行，支持超时、重试和回滚 |
| `run-tasks-parallel.sh` | 基于 git worktrees 的并行执行 |

两者都由 `/batch-tasks` 调用 — 不需要直接运行。

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
  "schema": 0.2
}
```

`> 0.3` 触发严格模式（类型检查 + 构建）。`< 0.1` 触发宽松模式（仅类型检查）。

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
│   │   └── sync/                      # /sync skill
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
- [高级用户研究](docs/research/power-users.md) — 顶级用户的使用模式

## License

[MIT](LICENSE)
