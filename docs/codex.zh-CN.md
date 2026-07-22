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

## 原生能力

`plugins/clade/` 包含：

- 21 个核心 workflows：commit、Codex usage pace、安全审查、release 文档、frontend design、
  handoff/pickup、incident、investigation、architecture map、PR review/merge、
  research、retro、项目 review、sync、verification、worktree 与决策辅助流程
- `SessionStart` hook：只读注入 branch、recent commits、dirty tree、handoff 和
  repository guidance，不修改仓库
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

## State 与仓库指引

原生 Codex workflows 优先读取 `AGENTS.md`，旧项目没有该文件时再读取
`CLAUDE.md`。新的运行状态写入 `.clade/` 或 `~/.clade/`；迁移已有项目时
可以读取 legacy Claude state，但不会创建新的 vendor-specific state。

显式调用使用 Codex 的 `$skill-name` 形式：

```text
$investigate why the integration test hangs
$verify all behavior anchors
$review the whole project and fix failures until clean
```

自然语言也可以触发相应 workflow。

## Codex Usage 与 Status Line

Clade 0.3 新增原生 `$codex-usage` workflow。它通过已认证的
`codex app-server` protocol 读取 rate-limit snapshot，不会打开或输出
`~/.codex/auth.json`。

```text
$codex-usage
$codex-usage setup minimal
$codex-usage style icon
$codex-usage style detail
$codex-usage theme bird
$codex-usage --json
```

默认 `minimal` 视图刻意保持极简：

```text
xingyushen(main)-9% (6d)
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
command；因此完全一致的极简字符串由 `$codex-usage` 输出，常驻 footer 使用
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
`gpt-5.6-terra`；low readiness 或 critical-path 任务升级到默认强层
`gpt-5.6-sol`。该开关仍默认关闭，需 routing replay eval 证明质量/美元和
质量/总时间都不退化后再考虑默认开启。

`./install.sh` 会把 `clade_cheap_explorer` 与 `clade_cheap_worker` 安装到
`~/.codex/agents/`，并在不覆盖用户内容的前提下幂等合并全局委派规则。架构、
含糊、高风险或不可机械验收的工作仍由主模型完成；写入小弟必须有明确文件所有权
和 verifier。Spark 因套餐可用性不同，不作为默认廉价层。

## 兼容边界

完整的 Codex JSONL event streaming、thread resume、structured result 与精确
usage accounting 仍是 Phase 2。跨厂自动委派也没有伪装成已支持：Claude ↔ Codex
目前只走用户显式 task 或只读 second-opinion relay。
