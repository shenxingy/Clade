[English](README.md) | **中文**

# Claude Code Kit

**把 Claude Code 从聊天助手变成自主编码系统。**

一个安装脚本。十个 hooks、五个 agents、二十三个 skills、一个安全守卫，以及一个纠正学习循环 — 协同工作，让 Claude 编码更好、自动捕获错误、可以在你睡觉时无人值守地跑通宵。

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
| Claude 尝试执行 git revert/reset | `revert-detector.sh` | 检测隐式纠正（撤回 Claude 自己的工作），记录为学习事件 |
| Claude 编辑代码文件 | `post-edit-check.sh` | **异步**运行语言对应的检查（tsc、pyright、cargo check、go vet、swift build、gradle、chktex） |
| Claude 编辑代码文件 | `post-tool-use-lint.sh` | 运行项目的 `verify_cmd`（来自 `.claude/orchestrator.json`）|
| Claude 编辑代码文件 | `edit-shadow-detector.sh` | 追踪被编辑的文件，供纠正学习系统使用 |
| 你纠正 Claude（"错了，用 X"） | `correction-detector.sh` | 记录纠正，提示 Claude 保存可复用的规则 |
| Claude 标记任务完成 | `verify-task-completed.sh` | 自适应质量门禁：检查编译/lint，严格模式额外运行 build + test |
| Claude 需要权限 / 空闲 | `notify-telegram.sh` | 发送 Telegram 提醒，不用盯着终端 |
| 每次发送提示词 | `prompt-tracker.sh` | 追踪提示词特征，发现重复模式 |

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
| `/loop GOAL_FILE` | 目标驱动的自主改进循环 — 主管每轮规划任务，workers 并行执行 |
| `/loop --status` | 查看当前循环状态（迭代次数、收敛情况、worker 结果） |
| `/loop --stop` | 停止运行中的循环 |
| `/audit` | 审查 `corrections/rules.md` — 找出该升级到 CLAUDE.md 的规则，删除冗余或矛盾条目 |
| `/model-research` | 搜索最新 Claude 模型数据，显示变化 |
| `/model-research --apply` | 同上 + 更新模型指南、会话上下文和批量任务配置 |
| `/worktree` | 创建和管理 git worktrees，支持并行 Claude Code 会话 |
| `/research` | 对某个主题深度调研 — 网络搜索、综合信息、保存到 `docs/research/` |
| `/map` | 生成代码库地图 — 文件归属、模块依赖图、入口点 |
| `/incident` | 事故响应模式 — 诊断生产问题、写复盘、添加后续任务到 TODO |
| `/minimax-usage` | 查看 Minimax Coding Plan 用量 — 由 `/usage` 自动检测调用 |
| `/review-pr` | AI 审查 PR diff，发布结构化审查评论 |
| `/merge-pr` | Squash merge PR 并清理分支 |
| `/brief` | 早晨简报 — 过夜 commits、队列状态、最近教训、下一步 3 个 TODO |
| `/start` | 自主会话启动器 — 晨间简报、通宵运行、跨项目巡检、自动调研 |
| `/start --run` | 完整自主会话：规划 → 循环 → 验证 → 重复，直到完成/阻塞/预算耗尽 |
| `/start --goal FILE` | 定向运行：使用目标文件（跳过 orchestrate，直接进入 loop） |
| `/start --patrol` | 跨项目扫描所有 `~/projects/` 中有 CLAUDE.md 的项目（仅报告，不启动 workers） |
| `/start --research` | 基于项目 TODO/GOALS/BRAINSTORM 上下文自动调研 |
| `/start --resume` | 恢复中断的自主会话 |
| `/start --stop` | 写入停止信号，优雅结束运行中的会话 |

## 什么时候用什么

**直接对话** — 日常大部分工作：
- 修 bug、小功能、重构、问代码相关的问题
- Claude 自动判断复杂度，需要时自己进入 plan mode
- 技巧：描述要具体。"给 API client 加一个指数退避的重试机制" 比 "优化一下 API client" 好得多

**`/research TOPIC`** — 开始复杂功能或选型前：
- 网络搜索、综合调研结果，保存到 `docs/research/<topic>.md`
- 适合竞品分析、API 评估、架构决策
- 在 `/orchestrate` 之前跑一下，让计划有真实数据支撑

**`/model-research`** — 新 Claude 模型发布时或定期维护：
- 搜索最新 benchmark、定价和能力变化
- `--apply` 自动更新模型指南、会话上下文和批量任务配置

**`/orchestrate`** — 用编排 Web UI 规划大型工作时：
- 提问澄清需求、拆解目标为任务、写入 `proposed-tasks.md`
- Workers 从中领取任务；在 Web UI 里效果最好
- 比 `/batch-tasks` 更适合范围还不完全清晰的情况

**`/map`** — 接手陌生代码库或派发 agents 之前：
- 生成文件归属图（来自 git log）、模块依赖图、入口点
- 保存为 `.claude/AGENTS.md` — workers 读取后避免踩到彼此的文件
- 项目启动时跑一次，大重构后重跑

**`/batch-tasks`** — 有结构化的 TODO 列表时：
- 多步骤实现，拆成独立任务
- 任务不冲突时用 `--parallel`
- TODO.md 条目越清晰越好 — 模糊的任务会得到低分，可能被跳过

**`/loop GOAL_FILE`** — 想让 Claude 持续迭代直到达成目标时：
- 主管每轮规划任务，workers 通过 git worktrees 并行执行
- 无人值守运行 — 通宵跑，早上看结果
- 先写清楚目标文件；目标模糊会导致无休止的循环

**`/worktree`** — 在同一个 repo 上并行跑多个 Claude Code 会话时：
- 创建独立的 git worktree + 分支，会话之间不冲突
- 适合同时开发两个功能，或在跑 loop 的同时继续写代码

**`/review`** — 大版本发布前、长期冲刺结束后或接手新代码库时：
- **发现并修复**（不只是报告）：文件大小、lint 错误、死代码、安全漏洞、UI 逻辑、文档过期、功能与目标不一致
- 修完再扫，循环最多 3 轮直到干净
- 无法自动修复的 Critical/Warning 写入 TODO.md 的 `## Tech Debt`
- 8 个阶段：文档健康 → 目标一致 → 代码结构 → Lint → 注释 → Bug → 安全 → UI

**`/review-pr NUMBER`** — 合并 PR 前：
- 读取 PR diff，发布结构化审查评论（Critical / Warning / Suggestion）
- 比完整 `/review` 更快，只针对具体改动

**`/merge-pr NUMBER`** — 合并并清理 PR：
- Squash merge PR 并删除功能分支
- 在 `/review-pr` 通过后执行

**`/incident DESCRIPTION`** — 生产出问题时：
- 诊断问题、提出根因假设、起草复盘文档
- 自动把后续任务添加到 TODO.md
- 比自由式 debug 更快 — 结构化响应在压力下更高效

**`/brief`** — 通宵运行后的早晨：
- 显示过去 18 小时的 commits、编排队列状态、PROGRESS.md 最近教训
- 列出下一步 3 个 TODO，附一条改进建议
- 比分别看 PROGRESS.md + git log + TODO.md 快得多

**`/handoff`** — 上下文快满时（约 80%）或停止工作前：
- 将会话完整状态保存到 `.claude/handoff-{时间戳}.md`
- 包含：做了什么、待做什么、git 状态、精确的下一步、坑点提示
- 让下一个会话（或者通宵跑的 agent）无需人工交代背景就能接着干

**`/pickup`** — 新会话开始时：
- 读取最新 handoff，展示简洁摘要，立即执行 Next Steps 第一条
- 不需要用户再说一遍背景

**`/audit`** — 定期清理纠正学习系统：
- 找出 `corrections/rules.md` 中应升级到 CLAUDE.md 或 hooks 的规则
- 删除随时间累积的冗余或矛盾条目
- 每隔几周跑一次，或当你发现 Claude 忽略某条规则时

**`/sync`** — 每次编码会话结束时：
- 勾掉完成的 TODO 项，把经验教训记录到 PROGRESS.md
- 之后跑 `/commit` 把代码 + 文档一起按模块拆分提交
- 这是构建团队记忆的方式 — 跳过它，你就会重复过去的错误

**`/commit`** — 准备提交时：
- 分析所有未提交的改动，按模块拆分成逻辑清晰的 commits
- 默认推送；`--no-push` 跳过推送，`--dry-run` 仅预览拆分计划

**`/start`** — 自主会话入口：
- 默认（无参数）：晨间简报 — 安全只读，显示发生了什么、下一步做什么
- `--run`：完整自主会话 — 编排任务、并行执行、验证结果、循环直到完成
- `--goal goal.md`：定向模式 — 跳过 orchestrate，直接用目标文件驱动 loop
- `--patrol`：扫描所有项目，找出问题但不做改动
- `--research`：从 TODO/GOALS/BRAINSTORM 自动生成调研主题
- 预算（`--budget 10`）、时间（`--hours 8`）和迭代次数（`--max-iter 5`）限制确保安全
- `--resume` 恢复中断的会话；`--stop` 优雅停止

**`slt`** — 控制状态栏的配额进度指示器：
- `slt` 循环切换模式：symbol → percent → number → off
- `slt theme` 列出全部 9 个 emoji 主题；`slt theme <名称>` 切换
- 指示器显示你与 95% 周配额目标的差距

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
│   ├── server.py                      # FastAPI 服务 — 路由、WebSocket、生命周期
│   ├── session.py                     # ProjectSession、SessionRegistry、状态循环
│   ├── worker.py                      # WorkerPool、SwarmManager、任务执行
│   ├── worker_tldr.py                 # TLDR 生成 + 任务评分（叶节点）
│   ├── worker_review.py               # Oracle + PR 审查（叶节点）
│   ├── task_queue.py                  # SQLite 任务 CRUD
│   ├── config.py                      # 全局设置、模型别名、工具函数
│   ├── github_sync.py                 # GitHub API 封装（issues、push）
│   ├── ideas.py                       # IdeasManager — 异步想法 CRUD + AI 评估
│   ├── process_manager.py             # ProcessPool — start.sh 生命周期控制
│   ├── routes/
│   │   ├── tasks.py                   # 任务 CRUD + 批量操作路由
│   │   ├── workers.py                 # Worker 控制 + 检查路由
│   │   ├── webhooks.py                # GitHub webhook 处理
│   │   ├── ideas.py                   # Ideas API 路由
│   │   └── process.py                 # 进程管理 API 路由
│   ├── requirements.txt               # Python 依赖
│   └── web/
│       ├── index.html                 # SPA 外壳
│       ├── app-core.js                # 核心状态、WebSocket、会话标签
│       ├── app-dashboard.js           # 任务、workers、进程卡片
│       ├── app-viewers.js             # 日志查看器、用量条、历史
│       ├── app-ideas.js               # Ideas 收件箱 UI、评估卡片
│       └── styles.css                 # 样式表
├── configs/
│   ├── settings-hooks.json            # Hook 定义（合并到 settings.json）
│   ├── hooks/
│   │   ├── session-context.sh         # SessionStart: 加载 git 上下文 + handoff + 纠正规则
│   │   ├── pre-tool-guardian.sh       # PreToolUse: 拦截迁移/rm-rf/force-push/DROP
│   │   ├── revert-detector.sh         # PreToolUse: 检测 git revert/reset 作为纠正事件
│   │   ├── post-edit-check.sh         # PostToolUse: 编辑后异步类型检查
│   │   ├── post-tool-use-lint.sh      # PostToolUse: 运行项目 verify_cmd
│   │   ├── edit-shadow-detector.sh    # PostToolUse: 追踪被编辑的文件
│   │   ├── correction-detector.sh     # UserPromptSubmit: 从纠正中学习
│   │   ├── prompt-tracker.sh          # UserPromptSubmit: 追踪提示词特征
│   │   ├── verify-task-completed.sh   # TaskCompleted: 自适应质量门禁
│   │   └── notify-telegram.sh         # Notification: Telegram 提醒
│   ├── agents/
│   │   ├── code-reviewer.md           # Sonnet 代码审查器（带记忆）
│   │   ├── test-runner.md             # Haiku 测试执行器
│   │   ├── type-checker.md            # Haiku 类型检查器
│   │   ├── verify-app.md              # Sonnet 应用验证器
│   │   └── paper-reviewer.md          # 学术论文审查器
│   ├── skills/
│   │   ├── handoff/                   # /handoff — 会话结束上下文存档
│   │   ├── pickup/                    # /pickup — 会话开始上下文恢复
│   │   ├── batch-tasks/               # /batch-tasks — 批量任务执行
│   │   ├── loop/                      # /loop — 目标驱动自主改进循环
│   │   ├── sync/                      # /sync — 更新 TODO + PROGRESS
│   │   ├── commit/                    # /commit — 按模块拆分提交
│   │   ├── audit/                     # /audit — 纠正规则审查
│   │   ├── research/                  # /research — 深度调研
│   │   ├── model-research/            # /model-research — 模型数据更新
│   │   ├── orchestrate/               # /orchestrate — Web UI 编排器
│   │   ├── map/                       # /map — 代码库地图
│   │   ├── worktree/                  # /worktree — 并行 git worktrees
│   │   ├── incident/                  # /incident — 事故响应
│   │   ├── review-pr/                 # /review-pr — PR 审查
│   │   ├── merge-pr/                  # /merge-pr — PR 合并
│   │   ├── brief/                     # /brief — 早晨简报
│   │   ├── start/                     # /start — 自主会话启动器
│   │   ├── verify/                    # /verify — 行为锚点验证（内部使用）
│   │   ├── minimax-usage/              # /minimax-usage — Minimax 用量查看
│   │   ├── slt/                       # slt — 状态栏切换控制
│   │   └── frontend-design/           # /frontend-design — 生产级 UI 生成
│   └── scripts/
│       ├── committer.sh               # 多 agent 安全提交（禁止 git add .）
│       ├── start.sh                   # 自主会话编排器（规划 → 循环 → 验证）
│       ├── loop-runner.sh             # 内部循环执行器（主管 + 并行 workers）
│       ├── run-tasks.sh               # 串行任务执行器
│       ├── run-tasks-parallel.sh      # 并行执行器（git worktrees）
│       ├── statusline-toggle.sh       # slt — 切换状态栏模式/主题
│       ├── claude-usage-watch.py      # 配额进度指示器
│       ├── scan-ci-failures.sh        # 任务工厂：CI 失败扫描
│       ├── scan-coverage.sh           # 任务工厂：测试覆盖率缺口
│       ├── scan-deps.sh               # 任务工厂：依赖更新
│       ├── scan-health.sh             # 任务工厂：代码健康（lint、TODO、大文件）
│       ├── scan-verify-issues.sh      # 任务工厂：验证问题批量反馈
│       ├── minimax-usage.sh            # Minimax Coding Plan 用量查看
│       ├── usage.sh                   # 自动检测订阅类型 + 显示用量
│       ├── scan-todos.sh              # TODO 扫描器 CLI
│       └── tmux-dispatch.sh           # tmux 并行调度器
├── templates/
│   ├── settings.json                  # settings.json 模板（不含密钥）
│   ├── CLAUDE.md                      # Agent Ground Rules 模板（部署到 ~/.claude/）
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
        ├── models.md                  # 模型对比与选择指南
        ├── power-users.md             # 顶级用户的使用模式
        ├── batch-tasks.md             # 批量执行研究
        ├── subagents.md               # 自定义 Agent 模式
        ├── openclaw-dev-velocity-analysis.md  # 开发速度分析
        └── solo-dev-velocity-playbook.md      # solo 开发提速手册
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
