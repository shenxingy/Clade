# 更新记录

这里记录 Clade 的重要 release。`clade-mcp` Python package 与公开 tags 使用
semantic versioning。

[English](CHANGELOG.md)

## Unreleased

### 新增

- Loop 新增 crash-safe phase recovery：只有显式、身份匹配的 `--resume` 才会
  恢复；普通启动忽略旧 checkpoint，`--help` 不产生副作用
- 原生 `$codex-usage` workflow，显示 Clade 的 95% 目标使用节奏
- 通过已认证的 Codex app-server 安全读取 rate limits，不打开凭证文件
- 幂等配置 Codex 原生 five-hour 与 weekly status-line fields
- 极简、可选图标、详细三种 styles，十种 themes，以及 JSON 输出

## [0.2.0] — 2026-07-13

### 新增

- 带 20 个生成式核心 workflows 的 Codex 原生 plugin
- Codex `SessionStart` context hook 与危险命令 `PreToolUse` guardian
- 通过 `CLADE_RUNTIME=claude|codex|auto` 选择的 provider-neutral MCP runtime
- 可配置 Codex sandbox，以及必须显式开启的 permission bypass
- 确定性的 Codex skill generator 与 CI drift gate
- Codex 和 `clade-mcp` 0.2.0 的完整中英文文档

### 变更

- `clade-mcp` 内置 workflows 从 0.1.0 的 29 个增加到 32 个
- MCP server、Python package 与 registry metadata 统一为 0.2.0
- `clade_list_skills` 会显示当前 execution runtime
- Root README 明确区分 Claude Code、Codex plugin 和 MCP 三种使用入口

### 兼容性

- 已有 MCP 配置仍默认使用 Claude runtime
- Codex 用户应安装原生 plugin，不应在 Codex 内部重复挂载 `clade-mcp`
- FastAPI multi-worker orchestrator 在此版本中仍为 Claude-specific

### 升级

```bash
pip install --upgrade clade-mcp
```

Codex 原生安装：

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

## [0.1.0] — 2026-04-02

### 新增

- Clade 首个公开 release
- 初版 `clade-mcp`，包含 29 个 coding workflows，通过 Claude 执行
- Claude Code skills、hooks、agents、scripts 与 FastAPI orchestrator

[0.2.0]: https://github.com/shenxingy/Clade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/shenxingy/Clade/releases/tag/v0.1.0
