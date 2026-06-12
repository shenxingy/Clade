[English](README.md) | **中文**

<p align="center">
  <img src="assets/banner.svg" alt="Clade" width="800" />
</p>

<p align="center">
  <a href="https://pypi.org/project/clade-mcp/"><img src="https://img.shields.io/pypi/v/clade-mcp?label=MCP%20Server&color=blue" alt="PyPI" /></a>
  <a href="https://github.com/shenxingy/clade/blob/main/CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://github.com/shenxingy/clade/labels/good%20first%20issue"><img src="https://img.shields.io/github/issues/shenxingy/clade/good%20first%20issue" alt="good first issue" /></a>
</p>

# Clade

**自主编码，进化而来。**

123 个 skills、26 个 hooks、34 个 agents、一个安全守卫，以及一个纠正学习循环 — 协同工作，让 Claude 编码更好、自动捕获错误、可以在你睡觉时无人值守地跑通宵。

> 如果它帮你省了时间，点个 star 能帮更多人找到它。出问题了？[提 issue](https://github.com/shenxingy/clade/issues/new/choose)。

> **博客文章：** [Building Clade](https://alexshen.dev/zh/blog/clade) — 项目的动机、设计决策和经验教训。

## 目录

1. [安装](#安装)
2. [MCP Server](#mcp-server--在任何-ai-编辑器中使用-skills)
3. [它做什么](#它做什么)
4. [自学习机制](#自学习机制)
5. [Skills](#skills-124)
6. [支持的语言](#支持的语言)
7. [文档](#文档)
8. [仓库结构](#仓库结构)
9. [贡献](#贡献)
10. [License](#license)

## 安装

### 完整框架（推荐）

```bash
git clone https://github.com/shenxingy/clade.git
cd clade && ./install.sh
```

安装 skills、hooks、agents、scripts 和安全守卫。启动新的 Claude Code 会话即可激活。

> **依赖：** `jq`。**平台：** Linux 和 macOS。

### 仅 MCP Server

如果只想在 Cursor、Windsurf、Claude Desktop 或任意 MCP 客户端里使用 skills：

```bash
pip install clade-mcp
```

配置见下方 [MCP Server](#mcp-server--在任何-ai-编辑器中使用-skills)。

## MCP Server — 在任何 AI 编辑器中使用 Skills

MCP server 通过 [Model Context Protocol](https://modelcontextprotocol.io) 把全部 123 个 Clade skills 暴露为可调用工具。兼容任何 MCP 客户端。

**Claude Desktop / Claude Code：**
```json
{
  "mcpServers": {
    "clade": { "command": "uvx", "args": ["clade-mcp"] }
  }
}
```

**Cursor / Windsurf：**
```json
{
  "mcpServers": {
    "clade": { "command": "clade-mcp" }
  }
}
```

> **前置条件：** 需要安装 [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) — skills 通过 `claude -p` 执行。

## 它做什么

| 时机 | 触发什么 | 效果 |
|------|---------|------|
| 在 git 仓库中打开会话 | `session-context.sh` | 加载 git 上下文、handoff 状态、纠正规则、模型指南 |
| 在 git 仓库中打开会话 | `commit-archeology.sh` | 从 `git log` 挖掘重复修复模式（wiring/deploy/compat gap、Claude-overridden）— 注入 top 4 |
| Claude 执行 bash 命令 | `pre-tool-guardian.sh` | **拦截**危险操作：数据库迁移、`rm -rf`、force push、`DROP TABLE` |
| Claude 编辑代码 | `post-edit-check.sh` | 异步类型检查（tsc、pyright、cargo check、go vet 等） |
| 你纠正 Claude | `correction-detector.sh` | 记录纠正，提示 Claude 保存可复用的规则 |
| Claude 标记任务完成 | `verify-task-completed.sh` | 自适应质量门禁：compile + lint，严格模式额外 build + test |

完整 hook 参考（26 个 hooks）见 [How It Works](docs/how-it-works.md)。

## 自学习机制

两个机制让 Clade 无需人工维护就与现实保持一致：

- **Commit Lessons**（响应式）— `commit-archeology.sh` 从 `git log` 挖掘重复修复模式（wiring-gap、deploy-gap、compat-gap、**claude-overridden**），每次会话启动时注入 top 4。
- **Doc Align**（预防式）— `doc-align.py` 在 `docs/facts.json` 中声明共享事实（从文件系统自动推导），检查/自动修复所有 `*.md` 的漂移。PostToolUse hook 在你编辑文档的瞬间标记漂移，过期数字到不了 commit。

两者对任何运行 Claude Code 的项目都生效（全局，位于 `~/.claude/scripts/`），未启用的仓库静默跳过。

详见 [Self-Learning Mechanisms](docs/learning-mechanisms.md)。

## Skills (124)

### 核心工作流

| Skill | 功能 |
|-------|------|
| `/commit` | 按模块拆分逻辑 commits，默认推送 |
| `/sync` | 勾掉完成的 TODO，追加会话总结到 PROGRESS.md |
| `/review` | 8 阶段覆盖式审查 — 发现并修复问题，循环到干净为止 |
| `/verify` | 验证项目行为锚点（compile、test、lint） |

### 自主运行

| Skill | 功能 |
|-------|------|
| `/start` | 自主会话启动器 — 晨间简报、通宵运行、跨项目巡检 |
| `/loop GOAL` | 目标驱动改进循环 — 主管规划，workers 并行执行 |
| `/iloop TASK` | 会话内迭代循环 — Stop hook 反复喂回提示词直到完成（无后台 workers） |
| `/batch-tasks` | 通过无人值守会话执行 TODO 步骤（串行或并行） |
| `/orchestrate` | 把目标拆解为任务供 workers 执行 |
| `/handoff` | 保存会话状态，供 agent 间上下文接力 |
| `/pickup` | 从上次 handoff 恢复 — 零摩擦重启 |
| `/worktree` | 创建 git worktrees 支持并行会话 |
| `/poke` | 按 `esc` 后的心跳 — 3 行状态汇报，进展正常就继续 |
| `/status` | 会话仪表盘 — 后台 agents、loops、worktrees、未推送 commits |
| `/go` | 直接执行你最近一组 A/B/C 选项中的推荐项 |

### 代码质量

| Skill | 功能 |
|-------|------|
| `/review-pr N` | AI 审查 PR diff — Critical / Warning / Suggestion |
| `/merge-pr N` | Squash-merge PR 并清理分支 |
| `/investigate` | 根因分析 — 假设未确认不动手修 |
| `/incident DESC` | 事故响应 — 诊断、复盘、后续任务 |
| `/cso` | 安全审计（OWASP + STRIDE） |
| `/map` | 生成 ARCHITECTURE.md（模块图 + 文件归属） |

### 调研与规划

| Skill | 功能 |
|-------|------|
| `/research TOPIC` | 深度网络调研，综合保存到 docs/research/ |
| `/model-research` | 最新 Claude 模型数据 + 自动更新配置 |
| `/next` | "下一步做什么" — 默认 1 次直给推荐；`/next deep` 多轮访谈 |
| `/brief` | 早晨简报 — 过夜 commits、成本、下一步 |
| `/retro` | 基于 git 历史的工程复盘 |
| `/frontend-design` | 生产级前端界面生成 |

### 系统

| Skill | 功能 |
|-------|------|
| `/audit` | 清理纠正规则 — 升级、去重、删除过期 |
| `/document-release` | 发布后文档同步（README、CHANGELOG、CLAUDE.md） |
| `/pipeline` | 后台 pipeline 健康检查 |
| `/provider` | 切换 LLM provider |
| `slt` | 切换状态栏配额进度指示器 |

### 博客与内容（30 个 skills）

| Skill | 功能 |
|-------|------|
| `/blog` | 全生命周期 — brief → outline → write → SEO check |
| `/blog-write` | 从零写 SERP-informed 文章 |
| `/blog-rewrite` | 优化已有文章的质量与 SEO |
| `/blog-audit` | 全站健康扫描（薄内容、meta、关键词蚕食） |
| + 26 个 | analyze · audio · brand · brief · calendar · cannibalization · chart · cluster · discourse · factcheck · flow · geo · google · image · locale-audit · localize · multilingual · notebooklm · outline · persona · repurpose · schema · seo-check · strategy · taxonomy · translate |

### SEO（25 个 skills）

| Skill | 功能 |
|-------|------|
| `/seo` | 完整 SEO 审计套件 |
| `/seo-technical` | 可抓取性、可索引性、Core Web Vitals |
| `/seo-page` | 单页深度分析 |
| `/seo-content` | E-E-A-T 与内容质量评分 |
| + 21 个 | audit · backlinks · cluster · competitor-pages · content-brief · dataforseo · drift · ecommerce · flow · geo · google · hreflang · image-gen · images · local · maps · plan · programmatic · schema · sitemap · sxo |

### 付费广告（23 个 skills）

| Skill | 功能 |
|-------|------|
| `/ads` | 多平台广告审计套件 |
| `/ads-google` | Google Ads — Quality Score、PMax、出价 |
| `/ads-meta` | Meta Ads — Pixel/CAPI、素材疲劳、Advantage+ |
| `/ads-create` | 从 brief 创建新广告活动 |
| + 19 个 | amazon · apple · attribution · audit · budget · competitor · creative · dna · generate · landing · linkedin · math · microsoft · photoshoot · plan · server-side-tracking · test · tiktok · youtube |

### 邮件（6 个 skills）

| Skill | 功能 |
|-------|------|
| `/email-write` | 用成熟文案框架（PAS、AIDA、BAB）写高转化邮件 |
| `/email-audit` | 送达率审计 — SPF、DKIM、DMARC、黑名单、健康分 |
| `/email-sequence` | 设计自动化序列（welcome、nurture、re-engagement） |
| + 3 个 | check · plan · review |

每个 skill 的详细使用指南见 [When to Use What](docs/when-to-use-what.md)。

## 支持的语言

自动检测 — hooks 和 agents 适配你的项目：

| 语言 | 编辑检查 | 类型检查器 | 测试执行器 |
|------|---------|-----------|-----------|
| TypeScript / JavaScript | tsc（monorepo 感知） | tsc | jest / vitest |
| Python | pyright / mypy | pyright / mypy | pytest |
| Rust | cargo check | cargo check | cargo test |
| Go | go vet | go vet | go test |
| Swift / iOS | swift build | swift build | swift test |
| Kotlin / Android / Java | gradlew | gradlew | gradle test |
| LaTeX | chktex | chktex | — |

所有检查按检测自动启用 — 工具未安装时 hook 静默跳过。

## 文档

详细文档暂为英文，欢迎 PR 翻译。

| 指南 | 内容 |
|------|------|
| [最大化产出](docs/throughput.md) | 跳过权限确认、批量任务、并行 worktrees、终端与语音 |
| [编排 Web UI](docs/orchestrator.md) | 聊天规划、worker 仪表盘、设置、迭代循环 |
| [通宵自主运行](docs/autonomous-operation.md) | 任务队列、并行会话、上下文接力、安全保障 |
| [工作原理](docs/how-it-works.md) | Hooks、agents、skills 内部机制、纠正学习、模型选择 |
| [配置](docs/configuration.md) | 设置、阈值、添加自定义 hooks/agents/skills |
| [什么时候用什么](docs/when-to-use-what.md) | 每个 skill 的详细使用指南 |

## Dotfile 同步

让 `~/.claude/` 跨机器保持一致 — 记忆、纠正规则、skills、hooks、scripts。

```bash
~/.claude/scripts/sync-setup.sh            # 自动检测 NFS 或 GitHub
~/.claude/scripts/sync-setup.sh --github   # 显式指定 GitHub 后端
```

配置后完全自动。详见 [配置](docs/configuration.md)。

## 仓库结构

```
clade/
├── install.sh               # 一键部署
├── uninstall.sh             # 干净卸载
├── mcp-package/             # PyPI 包（clade-mcp）
├── orchestrator/            # FastAPI Web UI + worker 池 + 任务队列
│   ├── server.py            # 应用、路由、WebSocket
│   ├── worker.py            # Worker、WorkerPool
│   ├── task_queue.py        # SQLite 任务 CRUD
│   ├── mcp_server.py        # MCP server（本地开发版）
│   └── web/                 # React + Vite 仪表盘（web/src/，从 web/dist 提供服务）
├── configs/
│   ├── skills/              # 123 个 skill 定义（SKILL.md + prompt.md）
│   ├── hooks/               # 26 个事件 hooks + lib/
│   ├── agents/              # 34 个 agent 定义
│   └── scripts/             # 38 个 shell + Python 工具
├── adapters/openclaw/       # OpenClaw 集成（手机监控）
├── templates/               # settings、CLAUDE.md、corrections 模板
└── docs/                    # 指南与研究
```

## OpenClaw 集成

通过 [OpenClaw](https://openclaw.ai) 从手机监控和控制通宵循环。

| Skill | 触发语 | 效果 |
|-------|--------|------|
| clade-status | "跑到哪了" | 迭代进度、成本、commits |
| clade-control | "开始 loop 修测试" | 启动/停止自主循环 |
| clade-report | "昨晚干了什么" | 会话报告、成本明细 |

安装见 [`adapters/openclaw/README.md`](adapters/openclaw/README.md)。

## 贡献

欢迎贡献 — 代码、文档、issue 分类、bug 报告。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

### 已知限制

1. **Loop 处理非代码任务**（调研/文档）时静默失败 — workers 没有 diff，loop 报告失败
2. **Workers 继承父环境** — 项目特定的环境变量会泄漏到 worker shell；通宵运行前请清理
3. **上下文预算按会话计** — 多天运行可能耗尽上下文；用 `/handoff` + `/pickup`

## License

[MIT](LICENSE)
