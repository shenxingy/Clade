[English](README.md) | **中文**

# Claude Code Kit

**把 Claude Code 从聊天助手变成自主编码系统。**

一个安装脚本。十个 hooks、五个 agents、十五个 skills、一个安全守卫，以及一个纠正学习循环 — 协同工作，让 Claude 编码更好、自动捕获错误、可以在你睡觉时无人值守地跑通宵。

## 目录

1. [安装](#安装30-秒)
2. [支持的语言和框架](#支持的语言和框架)
3. [安装后会发生什么](#安装后会发生什么)
4. [可用命令](#可用命令)
5. [什么时候用什么](#什么时候用什么)
6. [文档](#文档)
7. [仓库结构](#仓库结构)
8. [卸载](#卸载)
9. [贡献](#贡献)
10. [已知限制](#已知限制)
11. [License](#license)

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
| 在 git 仓库中打开 Claude Code | `session-context.sh` | 加载 git 上下文、上次 handoff、纠正规则和模型指南到上下文 |
| Claude 尝试执行 Bash 命令 | `pre-tool-guardian.sh` | **拦截**数据库迁移（会超时）、危险 rm -rf、force push to main、SQL DROP |
| Claude 编辑代码文件 | `post-edit-check.sh` | **异步**运行语言对应的检查（tsc、pyright、cargo check、go vet、swift build、gradle、chktex） |
| 你纠正 Claude（"错了，用 X"） | `correction-detector.sh` | 记录纠正，提示 Claude 保存可复用的规则 |
| Claude 标记任务完成 | `verify-task-completed.sh` | 自适应质量门禁：检查编译/lint，严格模式额外运行 build + test |
| Claude 需要权限 / 空闲 | `notify-telegram.sh` | 发送 Telegram 提醒，不用盯着终端 |
| 会话结束 | Stop hook (settings.json) | 验证所有任务已完成后才退出 |

## 可用命令

| 命令 | 功能 |
|------|------|
| `/handoff` | 保存会话状态到 `.claude/handoff-*.md` — 支持通宵运行和 agent 间上下文接力 |
| `/pickup` | 加载最新 handoff 并立即恢复工作 — 新会话零摩擦启动 |
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
| `/orchestrate` | 切换到编排模式 — 提问澄清需求、拆解目标为任务、写入 `proposed-tasks.md`（供 Web UI 使用） |

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

**`/handoff`** — 上下文快满时（约 80%）或停止工作前：
- 将会话完整状态保存到 `.claude/handoff-{时间戳}.md`
- 包含：做了什么、待做什么、git 状态、精确的下一步、坑点提示
- 让下一个会话（或者通宵跑的 agent）无需人工交代背景就能接着干

**`/pickup`** — 新会话开始时：
- 读取最新 handoff，展示简洁摘要，立即执行 Next Steps 第一条
- 不需要用户再说一遍背景

**`/sync`** — 每次编码会话结束时：
- 勾掉完成的 TODO 项，把经验教训记录到 PROGRESS.md
- 不提交 — 之后跑 `/commit` 把代码 + 文档一起按模块拆分提交
- 这是构建团队记忆的方式 — 跳过它，你就会重复过去的错误

**`/commit`** — 准备提交时：
- 分析所有未提交的改动，按模块（schema、API、前端、配置、文档等）拆分成逻辑清晰的 commits
- 默认推送；`--no-push` 跳过推送，`--dry-run` 仅预览拆分计划

## 文档

详细文档暂为英文，欢迎 PR 翻译。

| 指南 | 内容 |
|------|------|
| [最大化产出](docs/throughput.md) | 跳过权限确认、批量任务输入、并行 worktrees、任务队列、终端和语音设置 |
| [编排 Web UI](docs/orchestrator.md) | 聊天规划流程、worker 仪表盘、设置说明、广播、迭代循环 |
| [通宵自主运行](docs/autonomous-operation.md) | 任务队列模式、并行会话、上下文接力、安全保障 |
| [工作原理](docs/how-it-works.md) | Hooks、Agents、Skills 内部机制、纠正学习循环、状态栏、模型选择 |
| [配置与自定义](docs/configuration.md) | 必需/可选设置、调整阈值、添加 hooks/agents/skills |
| [Hooks 研究](docs/research/hooks.md) | Hook 系统深入研究 |
| [模型选择指南](docs/research/models.md) | 性价比分析与选择规则 |
| [高级用户研究](docs/research/power-users.md) | 顶级用户的使用模式 |

## 仓库结构

```
claude-code-kit/
├── install.sh                         # 一键部署
├── uninstall.sh                       # 干净卸载
├── orchestrator/                      # 并行 agent 编排 Web UI
│   ├── start.sh                       # 启动脚本（自动安装依赖、打开浏览器）
│   ├── server.py                      # FastAPI 服务（PTY 编排器 + worker pool）
│   ├── requirements.txt               # Python 依赖（fastapi、uvicorn、ptyprocess、watchfiles）
│   └── web/index.html                 # 单文件 vanilla JS UI（聊天 + 仪表盘）
├── configs/
│   ├── settings-hooks.json            # Hook 定义（合并到 settings.json）
│   ├── hooks/
│   │   ├── session-context.sh         # SessionStart: 加载 git 上下文 + handoff + 纠正规则
│   │   ├── pre-tool-guardian.sh       # PreToolUse: 拦截迁移/rm-rf/force-push/DROP
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
│   │   ├── handoff/                   # /handoff skill — 会话结束上下文存档
│   │   ├── pickup/                    # /pickup skill — 会话开始上下文恢复
│   │   ├── batch-tasks/               # /batch-tasks skill
│   │   ├── sync/                      # /sync skill
│   │   ├── commit/                    # /commit skill
│   │   ├── worktree/                  # /worktree skill — 创建并行 git worktrees
│   │   ├── orchestrate/               # /orchestrate skill — Web UI 的 AI 编排器人格
│   │   └── model-research/            # /model-research skill
│   ├── scripts/
│   │   ├── committer.sh               # 多 agent 安全提交（禁止 git add .）
│   │   ├── run-tasks.sh               # 串行任务执行器
│   │   └── run-tasks-parallel.sh      # 并行执行器（git worktrees）
│   └── commands/
│       └── review.md                  # /review 技术债务审查命令
├── templates/
│   ├── settings.json                  # settings.json 模板（不含密钥）
│   ├── CLAUDE.md                      # Agent Ground Rules 模板（自动部署到 ~/.claude/）
│   ├── README.md                      # 新项目 README 起始模板
│   └── corrections/
│       ├── rules.md                   # 纠正规则初始模板
│       └── stats.json                 # 领域错误率初始值
└── docs/
    ├── throughput.md                  # 最大化产出指南
    ├── orchestrator.md                # 编排 Web UI 指南
    ├── autonomous-operation.md        # 通宵自主运行指南
    ├── how-it-works.md                # Hooks、Agents、Skills 原理
    ├── configuration.md               # 配置与自定义指南
    └── research/
        ├── hooks.md                   # Hook 系统深入研究
        ├── subagents.md               # 自定义 Agent 模式
        ├── batch-tasks.md             # 批量执行研究
        ├── models.md                          # 模型对比与选择指南
        ├── power-users.md                     # 顶级用户的使用模式
        ├── openclaw-dev-velocity-analysis.md  # steipete 开发速度分析
        └── solo-dev-velocity-playbook.md      # 可操作的 solo 开发提速手册
```

## 卸载

```bash
./uninstall.sh
```

移除所有已部署的 hooks、agents、skills、scripts 和 commands。保留：
- `~/.claude/corrections/`（你的学习规则和历史）
- `~/.claude/settings.json`（环境变量和权限 — 仅移除 hooks）
- 非本仓库管理的 skills

## 贡献

欢迎贡献 — 代码、文档、问题分类和 bug 报告都算。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

### 已知限制

这些是真实存在的粗糙边缘 — 适合贡献：

1. **Loop skill 处理非代码任务**（研究/文档）时静默失败 — workers 没有 diff、没有 commit，loop 报告失败但没有有用的错误信息
2. **GUI loop 控制粗糙** — 生产运行请用 CLI `/loop`；Web UI loop 更适合实验
3. **Worktree 中的 workers 继承父环境** — 项目特定的环境变量（数据库 URL、API 密钥）会泄漏到 worker shell；通宵运行前请清理环境变量
4. **上下文预算按会话追踪** — 多天通宵运行可能在没有重启的情况下耗尽上下文；长任务请用 `/handoff` + `/pickup`

## License

[MIT](LICENSE)
