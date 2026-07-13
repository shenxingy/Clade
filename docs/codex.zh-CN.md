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

- 20 个核心 workflows：commit、安全审查、release 文档、frontend design、
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

## 兼容边界

完整 overnight orchestrator、Claude-specific agents、status line、provider
switcher、quota integrations 与 correction-learning hooks 仍依赖 Claude CLI
layer。首个原生 plugin release 刻意不包含这些能力，避免表面原生、实际偷偷
调用 Claude。

MCP package 已具备真正的 Codex runtime，但 FastAPI worker orchestrator
仍使用 Claude-specific session streaming 和 model routing。未来的 runtime
adapter 必须同时覆盖 command construction、resume semantics、JSONL events、
model aliases、usage accounting 与 cancellation，才能称为 provider-neutral。
