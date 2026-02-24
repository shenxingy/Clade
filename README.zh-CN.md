[English](README.md) | **中文**

# Claude Code Kit

**把 Claude Code 从聊天助手变成自主编码系统。**

一个安装脚本。六个 hooks、四个 agents、六个 skills、一个安全守卫，以及一个纠正学习循环 — 协同工作，让 Claude 编码更好、自动捕获错误、可以在你睡觉时无人值守地跑通宵。

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

## 最大化产出

Claude Code 的瓶颈不是代码生成速度，而是**你输入任务的速度**。以下设置消除这些摩擦。

### 1. 跳过权限确认弹窗

```bash
# 加到 ~/.zshrc 或 ~/.bashrc
alias cc='claude --dangerously-skip-permissions'
```

有了这个 alias，Claude 全程自主运行，无需任何确认对话框。用 `cc` 代替 `claude` 启动。启动前确保 git 干净——这是你的回退保障。

### 2. 批量输入任务（核心习惯）

提前写好所有任务，然后同时启动多个 agent：

```bash
mkdir -p .claude/tasks

# 好的任务文件：指定具体文件、要参考的模式、需要覆盖的边界情况
cat > .claude/tasks/task-001.md << 'EOF'
给所有 /api/auth/* 路由添加速率限制。
使用 lib/middleware.ts 中现有的 rateLimiter。
POST /auth/login 限制 10 次/分，GET 接口 60 次/分。
超限时返回 429，body: {"error": "rate_limit_exceeded", "retry_after": N}。
EOF

cat > .claude/tasks/task-002.md << 'EOF'
在 tests/e2e/checkout.spec.ts 中为结账流程写 E2E 测试。
参考 tests/e2e/cart.spec.ts 的写法。
覆盖：加购、使用优惠券、结账成功、支付失败（card_declined）。
EOF

# 启动多个 agent，每个负责一个任务，全程自主运行
cc -p "$(cat .claude/tasks/task-001.md)"   # Terminal 1（非交互模式）
cc -p "$(cat .claude/tasks/task-002.md)"   # Terminal 2（非交互模式）

# 或者交互式运行（便于监控进度）：
cc   # Terminal 3 → 粘贴任务内容
```

> **好的任务文件的标准：** 写明要编辑/创建的具体文件。引用现有模式（"参考 X 的写法"）。列出边界情况和错误格式。模糊任务（"优化 auth 流程"）只会得到模糊结果。

你的思考和执行解耦——集中一次设计所有任务，让 agent 并行执行，你去做别的事。

### 3. 用 worktree 并行多个 agent

`/worktree` skill 创建隔离的 git worktrees，多个 agent 在同一 repo 里互不干扰：

```
/worktree create feat/auth-rework    # Terminal 1
/worktree create feat/rate-limiting  # Terminal 2
```

每个终端的 agent 在独立目录工作。`committer` 防止 staging 冲突。完成后合并即可。

### 4. 任务队列——顺序任务一次发完

Claude 按顺序处理消息——把所有任务一次发完，然后你就自由了：

```
1. 修复 UserService.getUserById() 里的空指针
2. 给所有 POST 接口加输入校验
3. 更新 README.md 中的 API 文档
```

不用等待，发完第一条你就可以去做别的。

### 5. 编排 Web UI — 聊天规划，并行执行

从想法到并行执行最快的路径。一个 AI 编排会话将你的目标拆解为任务；仪表盘实时展示 N 个 worker 并行执行进度。

```bash
./orchestrator/start.sh
# → 自动打开 http://localhost:8765
```

**工作流：**

```
1. 聊天："帮我搭一个有 auth、billing、analytics 的 SaaS"
   → 编排器问 2-3 个问题（技术栈、约束、现有代码）
   → 你回答（打字或系统语音输入）

2. 编排器提出任务拆分方案
   → 写入 .claude/proposed-tasks.md
   → UI 弹出确认框："4 个任务已准备好，全部启动？"

3. 点击"全部启动"
   → worker 并行启动：claude -p "$(cat task.md)" --dangerously-skip-permissions
   → 仪表盘每秒更新：状态、最新 commit、运行时长

4. 监控面板：
   Worker 1 │ running  │ feat: add NextAuth config    │ 2m34s │ [暂停] [聊天]
   Worker 2 │ running  │ feat: create Stripe webhook  │ 1m12s │ [暂停] [聊天]
   Worker 3 │ blocked  │ 需要 Stripe API Key          │ 0m45s │        [聊天]

5. Worker 3 被阻塞 → 点击 [聊天] → 输入 "用测试密钥 sk_test_xxx"
   → Worker 停止，消息作为上下文注入，Worker 重启

6. 全部完成：进度条 100%，用 git log --oneline 查看提交记录
```

**界面布局：**

```
┌─────────────────────────────────┬──────────────────────────────┐
│  编排器聊天（PTY）               │  任务队列                    │
│                                 │  ├ 待执行：实现 auth         │
│  > 帮我搭一个 SaaS...           │  ├ 待执行：接入 Stripe       │
│  < 技术栈是什么？               │  └ [执行] [删除] [+ 添加]    │
│  > Next.js, Prisma, Stripe      ├──────────────────────────────┤
│  < 正在写 4 个任务...           │  Workers                     │
│                                 │  ┌──────────────────────────┐│
│  ┌─ 4 个任务已准备好 ─────────┐  │  │ running │ feat: auth...  ││
│  │ 全部启动？[是]              │  │  │ 2m34s   │ [暂停][聊天]   ││
│  └─────────────────────────────┘  │  └──────────────────────────┘│
│  [输入消息... ]        [发送]    │  ████░░░░░ 35%  预计 ~8 分   │
└─────────────────────────────────┴──────────────────────────────┘
```

**无需构建步骤。** 单 HTML 文件 + FastAPI 后端。需要 Python 3.9+。

#### GUI 设置说明

点击 Web UI 右上角的 **⚙ 设置** 面板进行配置：

| 设置 | 默认 | 效果 |
|------|------|------|
| 自动启动 workers | ON | `proposed-tasks.md` 写入后立即启动 workers |
| 自动推送 | ON | 每次 commit 后自动推送到 feature branch |
| 自动合并 | ON | 自动 squash-merge `orchestrator/task-*` 的 PR |
| 自动审查 | ON | 在每个 PR 上自动发布 AI 代码审查评论 |
| **Oracle 验证** | OFF | Haiku 在推送前独立审查每个 diff — 捕捉"完成了但写错了"的静默错误；审查不通过则阻断推送 |
| **自动模型路由** | OFF | 按 scout 分数自动选模型：≥80 → haiku，50-79 → sonnet，<50 → sonnet + 先提问再写代码 |
| **上下文预算警告** | ON | 每个 worker 卡片显示 token 进度条（绿色 → 120K 变黄 → 160K 变红）；超过 160K 写入 `.claude/context-warning-{id}.md` 包含 `/compact` 指引 |
| **AGENTS.md → 生成** | — | 从 `git log` 构建文件→分支归属图；复制到 `.claude/AGENTS.md` 可防止并行 worker 相互覆盖文件 |

#### 向所有 Workers 广播

运行中途发现所有 worker 都需要某个修正，在 Execute 模式 workers 区域顶部的 **→ All Workers** 输入框中发送消息：

```
例："DB schema 变了 — 字段名从 userId 改成了 user_id"
→ 所有运行中的 workers 停止，接收该消息作为前置上下文，然后重启
```

适用场景：全局约束变了（API 地址改了、依赖更新了），需要让每个 worker 都知道。

#### 迭代循环（自主精炼）

自动完成审查 → 修复 → 验证的闭环，适用于任何需要迭代的制品（论文、代码审计、内容 QA）。

```
1. 切换到 Execute 模式 → 展开 Loop 区块
2. 输入：制品路径 = paper.tex  （或 server.py、README.md 等）
          代码库目录 = ./src     （可选，供 DATA_CHECK workers 核实论断用）
          K = 2，N = 3          （连续 3 轮变更数 ≤2 则视为收敛）

3. ▶ 开始循环 — 监督模型每轮：
     FIXABLE   → 自动生成任务并启动 worker 修复
     DATA_CHECK → 启动只读 worker 对照代码库核实某个论断
     DEFERRED  → 加入下方折叠栏（需人工判断 — 永不自动修复）
     CONVERGED → 循环结束，弹出提示

4. 所有 workers 完成 → 统计变更数 → 检查收敛 → 重复
5. 收敛后？查看折叠栏中的延迟项。
```

循环完全无需人工介入。在设置中配置 `max_iterations` 作为安全上限。

---

## 工作原理

### Hooks（自动行为）

| Hook | 触发时机 | 模型开销 |
|------|---------|---------|
| `session-context.sh` | SessionStart | 无（纯 shell） |
| `pre-tool-guardian.sh` | PreToolUse (Bash) | 无（纯 shell） |
| `post-edit-check.sh` | PostToolUse (Edit/Write) | 无（纯 shell） |
| `post-tool-use-lint.sh` | PostToolUse (Edit/Write) | 无（纯 shell） |
| `correction-detector.sh` | UserPromptSubmit | 无（纯 shell） |
| `verify-task-completed.sh` | TaskCompleted | 无（纯 shell） |
| `notify-telegram.sh` | Notification | 无（纯 shell） |

所有 hooks 都是 shell 脚本 — 零 API 开销，亚秒级执行。

**`post-tool-use-lint.sh`** 在每次文件编辑后运行项目的 `verify_cmd`。失败时写入 `.claude/lint-feedback.md` 并以 exit code 2 退出 — Claude 在下一轮看到错误输出并自动修复。通过 `.claude/orchestrator.json` 配置：

```json
{
  "verify_cmd": "python3 -m py_compile src/main.py"
}
```

常用值：`"tsc --noEmit"`（TypeScript）、`"python3 -m py_compile <文件>"`（Python）、`"cargo check"`（Rust）、`"go build ./..."`（Go）。不设置则禁用。

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

**`/orchestrate`** 现在包含：
- **Step 0**：规划前先读 `PROGRESS.md`（最近 3000 字符）和 `.claude/AGENTS.md` — 避免重蹈历史错误，遵守已有文件归属
- **增强的任务模板**：每个任务自动包含 `verify_cmd`、`own_files`、`forbidden_files`、验收检查清单、上下文管理（75% 时 `/compact`）和提交规则
- **Step 3.5**：写完 `proposed-tasks.md` 后从 `own_files` 自动生成 `.claude/AGENTS.md` — workers 启动前就知道谁负责哪些文件

**`/batch-tasks`** 现在：
- **读取 AGENTS.md**：规划阶段注入文件归属信息；标记出现文件冲突的任务供人工确认
- **可配置 scout 阈值**：在 `.claude/orchestrator.json` 中设置 `"scout_threshold": 50` — 低于阈值的任务写入 `.claude/low-score-tasks.md` 而非直接执行

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
│   │   ├── frontend-design/           # /frontend-design skill — 生产级 UI 生成
│   │   ├── orchestrate/               # /orchestrate skill — Web UI 的 AI 编排器人格
│   │   ├── companyos-update/          # /companyos-update skill — 同步任务到 Company OS
│   │   ├── companyos-wiki/            # /companyos-wiki skill — 创建/更新 Company OS wiki
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
│   └── corrections/
│       ├── rules.md                   # 纠正规则初始模板
│       └── stats.json                 # 领域错误率初始值
└── docs/
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

## 了解更多

- [Hooks 研究](docs/research/hooks.md) — Hook 系统深入研究
- [Subagents 研究](docs/research/subagents.md) — 自定义 Agent 模式
- [批量任务研究](docs/research/batch-tasks.md) — 批量执行改进
- [模型选择指南](docs/research/models.md) — 性价比分析与选择规则
- [高级用户研究](docs/research/power-users.md) — 顶级用户的使用模式

## License

[MIT](LICENSE)
