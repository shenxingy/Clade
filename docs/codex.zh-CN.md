[English](codex.md) | **中文**

← 返回 [README 中文版](../README.zh-CN.md)

# Codex 原生支持

Clade 通过原生 plugin 支持 Codex；对于其他 MCP 客户端，也可以选择 Codex
作为 `clade-mcp` 的 execution runtime。推荐在 Codex 内使用原生 plugin，
因为 skill 会直接在当前 thread 中运行，不会启动嵌套的 agent CLI。

## 从 GitHub 安装

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

安装后启动新的 Codex thread。首次使用时运行 `/hooks`，检查 Clade 的两个
hook definitions，并在内容与仓库一致时信任它们。

从本地 checkout 开发：

```bash
codex plugin marketplace add /absolute/path/to/Clade
codex plugin add clade@clade
```

## 有旧会话时更新

旧 thread 可能继续执行原版本 hook（[上游相关问题](https://github.com/openai/codex/issues/36605)）。
实测 Codex CLI 0.156.1 重装插件会删除旧缓存，其他 thread 因缺失
`pre_tool_guardian.py` 而连 `pwd` 都无法执行。

更新期间先暂停其他会话的工具操作，在 Clade checkout 中运行：

```bash
python3 configs/scripts/codex-plugin-update.py
```

它使用已配置的 `clade@clade` marketplace；本地开发先更新源 manifest 的
cachebuster。脚本将完整旧版本备份到 `~/.clade/codex-plugin-backups/`，调用
官方安装命令，再恢复缺失的旧路径。安装失败或中断也会尝试恢复；校验摘要，
拒绝覆盖不同内容，不修改 hook 逻辑或信任设置。CLI 替换过程仍有短暂窗口，
已失效的缓存别名会报告并跳过；bundle 内或指向有效 bundle 的符号链接会被拒绝。
脚本返回后再恢复其他会话。直接用 CLI/app 更新不受此保护。

旧会话退出前保留备份与旧目录。进程被强制终止时，可在普通终端运行：

```bash
python3 configs/scripts/codex-plugin-update.py --restore /path/to/printed/backup
```

只有确认更新进程已退出，才能手动删除备份目录里的残留 `update.lock`。
无备份时必须从可信的相同版本恢复，不能替换成任意新版 hook 或关闭检查。
新技能仍需新开 thread 加载；恢复旧文件不会刷新技能清单。本工具尚未在原生
Windows 环境实测。

## 原生能力

`plugins/clade/` 包含：

- 27 个核心 workflows：commit、Codex usage pace、安全审查、release 文档、frontend design、
  本地 CI 修复、handoff/pickup、incident、investigation、architecture map、PR review/merge、
  research、retro、项目 review、sync、verification、worktree 与决策辅助流程
- `SessionStart` hook：只读注入 branch、recent commits、dirty tree、handoff、
  repository guidance 和 delivery completion，不修改仓库
- `PreToolUse` safety hook：阻止灾难性删除、破坏性 SQL、数据库 migration 和
  shared branch force push；feature branch force push 会改写为 `--force-with-lease`

Codex 从 `SKILL.md` 加载可执行 workflow；Clade 原来的 Claude distribution
执行 `prompt.md`。Generator 会合并两份 canonical source，并应用 Codex
compatibility rules：

```bash
python3 configs/scripts/regen-codex-plugin.py
python3 configs/scripts/regen-codex-plugin.py --check
```

应修改 `configs/skills/` 下的 canonical skills，而不是直接修改
`plugins/clade/skills/` 的生成文件。发布列表位于 `plugins/clade/skills.list`。

`$clade:green` 可以在 Clade 仓库之外运行。生成后的 skill 会携带一份与
`configs/scripts/ci-local.py` 字节一致的 runner，从已安装 plugin root 解析它，
然后读取目标仓库真正的 GitHub Actions jobs 再进行修复。

## Claude → Codex 迁移契约

Clade 不会把完整 Claude 安装批量导入 Codex。这样会重复安装原生 plugin skills，
也会复制生命周期、信任模型或状态路径不兼容的 hooks、agents 与 output styles。

机器可读的 [`configs/codex-migration.json`](../configs/codex-migration.json)
把每个配置面标记为原生、原生子集、语义适配或明确排除；同时要求每个 canonical
Claude skill 只能有一个 Codex 去向：进入 `plugins/clade/skills.list`，或匹配一个
写明理由的排除组。新增 skill 没有声明 Codex 去向时，CI 会直接失败。

Installer 会把全局策略中 provider-neutral 的部分适配到
`~/.codex/AGENTS.md` 托管区块：原子 PR、本地 CI 优先、完整证据、简洁表达、
配置 wiring 与部署验证。模型、trust、permissions、MCP 认证和个人 plugin 设置
继续由用户自己的 `~/.codex/config.toml` 管理。

Claude output styles 在 Codex 中没有可分发的一一对应 primitive。因此 Evidence
First 与 Terse 的约束以持久 Codex guidance 表达，但不声称与 system prompt
等价。Claude lifecycle orchestration 和 MCP bridge 在拥有真实原生语义前仍不会
装入 native plugin。

## State 与仓库指引

Codex 按作用域解析 agent 指令，同一作用域内第一个命中的文件名胜出，且两者
之间不做合并：`AGENTS.override.md` 在 home scope（`~/.codex/`）与 project
scope 都排在 `AGENTS.md` 之前，因此只要某个目录存在 override，该目录的
`AGENTS.md` 根本不会被读取。`CLAUDE.md` 只是 Clade 自己为旧版 Clade 项目保留
的 legacy fallback，并不是 Codex 会去解析的文件名。托管块合并进
`~/.codex/AGENTS.md`，所以当 `~/.codex/AGENTS.override.md` 会遮蔽它时
`install.sh` 会发出警告：只报告冲突，绝不删除或移动该 override 文件。

新的运行状态写入 `.clade/` 或 `~/.clade/`；迁移已有项目时可以读取 legacy
Claude state，但不会创建新的 vendor-specific state。

每个生成的 native skill 末尾也有同一条 delivery boundary：可写任务不能在
task-owned 改动尚未提交时报告 `DONE`；涉及 live URL 或已部署服务的请求也不能
被静默降级成本地修改。缺少发布或部署权限时必须报告 blocker，不能作为完成后的
附带说明。

显式调用使用 Codex 的 `$skill-name` 形式：

```text
$clade:investigate why the integration test hangs
$clade:verify all behavior anchors
$clade:review the whole project and fix failures until clean
```

自然语言也可以触发相应 workflow。

## Codex Usage 与 Status Line

Clade 0.3 新增原生 `$clade:codex-usage` workflow。它通过已认证的
`codex app-server` protocol 读取 rate-limit snapshot，不会打开或输出
`~/.codex/auth.json`。

```text
$clade:codex-usage
$clade:codex-usage setup minimal
$clade:codex-usage style icon
$clade:codex-usage style detail
$clade:codex-usage theme bird
$clade:codex-usage --json
```

默认 `minimal` 视图刻意保持极简：

```text
xingyushen git:(main)-9% (6d)
```

其中包含 project、branch、相对 95% utilization 目标的节奏与重置时间。
`style icon` 插入所选主题图标，`style detail` 展开所有 Codex limit buckets
与百分比。普通 `setup` 会把原生 `five-hour-limit`、`weekly-limit` 安全合并到
`~/.codex/config.toml`；`setup minimal` 只保留 directory、branch 与 weekly
limit；`setup full` 还显示 model、context 与两个 limit windows。只有显式选择
layout 时才会替换已有 `status_line` array。

Codex 自带 `/usage` 查看 account usage、`/status` 查看当前 session，亦可通过
`/statusline` 交互配置 footer。修改 footer 后请启动新的 Codex session。
Codex 原生 footer 只接受固定 fields，不支持 Claude Code 那种任意 formatter
command；因此完全一致的极简字符串由 `$clade:codex-usage` 输出，常驻 footer 使用
最接近的原生 field 组合。

## MCP 0.2.0 Runtime

如果要在 Cursor、Windsurf 或其他 MCP 客户端中把 Clade skills 委托给
Codex，配置：

```json
{
  "mcpServers": {
    "clade": {
      "command": "uvx",
      "args": ["clade-mcp"],
      "env": {
        "CLADE_RUNTIME": "codex",
        "CLADE_CODEX_SANDBOX": "workspace-write"
      }
    }
  }
}
```

| 环境变量 | 默认值 | 含义 |
|----------|--------|------|
| `CLADE_RUNTIME` | `claude` | `claude`、`codex` 或保守的 `auto` 选择 |
| `CLADE_CODEX_SANDBOX` | `workspace-write` | 委托执行时使用的 Codex sandbox |
| `CLADE_CODEX_BYPASS_PERMISSIONS` | 未设置 | 仅在外部已隔离环境中设为 `1` |

当原生 plugin 已启用时，不要在 Codex 内部再配置这个 MCP server。否则会
重复加载 tool descriptions，并把原生 workflow 变成嵌套 `codex exec` session。

完整 MCP 说明见 [MCP package 中文指南](../mcp-package/README.zh-CN.md)。

## Codex 作为 Orchestrator Worker

FastAPI orchestrator 已能把 `codex exec` 当作一等 worker provider。全局可在
`~/.claude/orchestrator-settings.json` 设置 `worker_provider: "codex"`，单个 task
也可用 `provider` 覆盖，并指定 `effort`。Codex effort 会通过
`model_reasoning_effort` 传入；任务会记录最终 `model`、`provider`、`effort` 与
`route_reason` 供审计。

开启 `auto_model_routing` 后，只有高 readiness 任务才使用默认廉价层
`gpt-5.6-luna`；low readiness 或 critical-path 任务升级到默认强层
`gpt-5.6-sol`。该开关仍默认关闭，需 routing replay eval 证明质量/美元和
质量/总时间都不退化后再考虑默认开启。

`./install.sh` 会把 `clade_cheap_explorer` 与 `clade_cheap_worker` 安装到
`~/.codex/agents/`，并在不覆盖用户内容的前提下幂等合并全局托管规则，其中同时
包含自适应委派与 delivery completion。架构、含糊、高风险或不可机械验收的工作
仍由主模型完成；写入小弟必须有明确文件所有权和 verifier。Spark 因套餐可用性
不同，不作为默认廉价层。

## 兼容边界

完整的 Codex JSONL event streaming、thread resume、structured result 与精确
usage accounting 仍是 Phase 2。跨厂自动委派也没有伪装成已支持：Claude ↔ Codex
目前只走用户显式 task 或只读 second-opinion relay。
