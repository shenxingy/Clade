[English](getting-started.md) | [中文](getting-started.zh-CN.md)

← 返回 [README](../README.zh-CN.md)

# 上手指南

本指南区分 shell 命令和 agent 聊天中的命令。先选择一个原生入口；只有需要任务、
证据或 fleet API 时才安装可选的 Orchestrator。

## 目录

- [前置条件](#前置条件)
- [Claude Code](#claude-code)
- [Codex](#codex)
- [MCP](#mcp)
- [可选 Orchestrator](#可选-orchestrator)
- [第一次工作流](#第一次工作流)
- [更新](#更新)
- [排障](#排障)
- [继续阅读](#继续阅读)

## 前置条件

- macOS 或 Linux；Windows 使用 Git Bash 才支持完整框架。
- Claude 完整框架需要已安装并登录的 Claude Code CLI，以及 Git、Bash、Python 3 和 `jq`；
  仓库 helper 推荐 Python 3.11。
- Codex 需要支持 plugin 的 CLI 和 Python 3（生成的 hooks 使用）。
- MCP 需要 Python 3.10+、`uv`，以及客户端 `PATH` 中已登录的 Claude 或 Codex CLI。
- 只有手动构建 Orchestrator web UI 时才需要 Node/npm。

在 shell 中先检查：

```bash
python3 --version
jq --version
claude --version   # 使用 Claude Code 时
codex --version    # 使用 Codex 时
uv --version       # 使用 MCP 时
```

没有 `jq` 时文件仍可能复制成功，但安装器无法把 hooks 合并到 `~/.claude/settings.json`。
安装 `jq` 后重新运行安装器。

## Claude Code

在 clone 目录的 shell 中运行：

```bash
./install.sh
python3 configs/scripts/validate-skills.py configs/skills --quiet
```

安装器会把框架写入 `~/.claude/`，更新 `~/.codex/AGENTS.md` 中的 Clade 托管区块，
把 provider-neutral guidance 写入 `~/.agents/AGENTS.md`，并在检测到 Kimi Code 时适配其文件；
有 `jq` 时会替换 `~/.claude/settings.json` 的 `hooks` 和 `statusLine` 字段，追加 deny rules，
并更新 skill 设置。如果需要保留自定义 hooks 或状态栏，先保存当前配置，并在运行前检查 `install.sh`。

安装后在你要处理的项目中开启新的 Claude Code 会话。在 agent 聊天里粘贴：`Use Clade verify to run one documented check in this repository. Report
which command ran, its result, and anything you could not check.` 然后运行 `/verify`。确认 `~/.claude/` 中有安装文件，并在新会话中查看 hooks；
`validate-skills.py` 只检查 source tree，不代表已安装副本正确。

## Codex

需要支持 plugin 的 Codex CLI 和 Python 3（生成的 hooks 使用）。在 shell 中运行：

```text
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

在你要处理的项目中新建 Codex thread，在 Codex 聊天中运行 `/hooks`，检查 Clade 的两个 hook 定义后再信任。
然后用 `$clade:verify` 试一个小任务。维护者可以用下面的命令检查生成物：

```bash
python3 configs/scripts/regen-codex-plugin.py --check
```

已有 thread 可能仍在使用旧插件 bundle；并行工作时先按 [Codex 原生支持](codex.zh-CN.md)
的更新和恢复流程操作。

## MCP

需要 Python 3.10+、`uv`，以及 MCP 客户端 `PATH` 中已登录的 Claude 或 Codex CLI。把下面配置加入客户端：

```json
{
  "mcpServers": {
    "clade": {
      "command": "uvx",
      "args": ["clade-mcp"],
      "env": { "CLADE_RUNTIME": "codex" }
    }
  }
}
```

此示例使用 Codex，默认 sandbox 为 `workspace-write`。在客户端启动配置中把 MCP 服务器的
工作目录设为目标仓库；服务器使用启动时的当前目录，不会协商客户端 workspace。具体设置方法
取决于客户端。

省略 `CLADE_RUNTIME` 时默认使用 Claude；`auto` 在安装了 Claude 时优先选择它。
Claude runtime 使用 `--dangerously-skip-permissions`，应在自行隔离的环境中使用；
客户端审批不能为启动的 CLI 提供 sandbox。Codex 也有显式 bypass 选项，本示例保持未设置。
见[运行时选项](../mcp-package/README.md#runtime-selection)。

在客户端的 MCP 工具面板调用
`clade_list_skills`；响应应列出 skills 和选中的 runtime。这只是发现 smoke test，不代表
编码任务或仓库权限已经验证。若客户端已有原生入口，不要再挂载 MCP。

## 可选 Orchestrator

Orchestrator 是独立的 FastAPI 和 web 应用，Claude、Codex 原生使用不需要它。需要控制平面时，
请按 [Orchestrator 指南](orchestrator.md) 操作，包括不同的启动端口和 web 构建步骤。web 页面
能打开不代表 worker 已执行或验证任务；请检查 task 和 evidence 记录。

## 第一次工作流

在临时 branch 上选一个已有测试的小任务。让 agent 检查仓库、提出改动、实现并运行仓库文档中
规定的检查。决定 commit 或开 PR 前，审阅 diff 和证据。Clade 的交付检查不会授予 push、merge
或 release 权限。

## 更新

- Claude 框架：拉取经过审阅的 Clade checkout，重新运行 `./install.sh`，再开启新会话。
- Codex：其他 thread 运行时按 [插件更新辅助工具](codex.zh-CN.md#有旧会话时更新) 操作；更新后新建 thread。
- MCP：保留 `"command": "uvx"`，临时把 `args` 改为 `["--upgrade", "clade-mcp"]`，
  然后重启客户端以允许升级。检查新版本后恢复 `["clade-mcp"]`，避免每次启动都请求升级。

## 排障

**找不到 skill。** 开启新的 agent session。Claude 重新运行安装器并查看 `~/.claude/skills/`；
Codex 检查 marketplace 和 `/hooks`；MCP 调用 `clade_list_skills` 并检查 `CLADE_RUNTIME`。

**没有出现 hooks。** 确认已安装 `jq`，重新运行 `./install.sh`，检查 `~/.claude/settings.json` 中
的托管区块。不要用复制的示例覆盖整个 settings 文件。

**运行了错误 runtime。** MCP 使用 `CLADE_RUNTIME`；`auto` 在可用时优先 Claude。原生入口不
需要 MCP，不要把两者叠加。

**Orchestrator 页面返回 503。** 按 [其指南](orchestrator.md) 构建前端；`orchestrator/start.sh`
和裸 `uvicorn` 使用不同的默认端口。

**任务说完成但结果不确定。** 检查 diff，运行仓库真实检查并审阅证据。看起来绿色的报告不能
替代仓库自己的验收标准。

## 继续阅读

[When to Use What](when-to-use-what.md) 将目标映射到 skills；[How It Works](how-it-works.md)
解释 hooks 和证据；[CONTRIBUTING](../CONTRIBUTING.md) 说明源码修改、测试和社区报告。
