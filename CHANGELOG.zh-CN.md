# 更新记录

这里记录 Clade 的重要 release。`clade-mcp` Python package 与公开 tags 使用
semantic versioning。

[English](CHANGELOG.md)

## Unreleased

### 安全

- worktree 只隔离工作树，不隔离 `.git`。在 worker 的 worktree 内，
  `git rev-parse --git-common-dir` 解析到父仓库，因此 agent 可以写入
  `<main>/.git/hooks/pre-commit`，并在操作者下一次提交时执行。现在 worker
  在启动前对父仓库的 hooks 与 config 取快照，若发生变化则拒绝验证与提交
  （`worker_git_surface_guard`，默认开启）
- `install.sh` 升级路径从不写入 deny 规则。`templates/settings.json` 带有
  `Read(~/.ssh/**)`、`Read(~/.aws/**)`、`Read(~/**/.env)`，但合并分支只写
  `.hooks` 与 `.statusLine`，因此所有在 deny 列表出现之前安装过的机器，
  `permissions` 一直是 null —— 而 worker 正是以绕过权限的方式启动的，deny
  规则是最后一道约束。合并只做 deny 的并集，绝不扩大用户自己的 allow 列表
- worktree 隔离失败时静默放行。所有失败路径都丢弃了 git 的 stderr 并让 worker
  留在共享检出上；现在会直接抛错，而不是让未隔离的 agent 在操作者本人的工作树
  里运行（`worker_require_worktree`）

### 新增

- worker 自报开销：spawn 带 `--output-format stream-json`，
  `orchestrator/agent_output.py` 读回 `total_cost_usd`、按模型的 `modelUsage`
  与真实 token 数，并把事件流投影回纯文本，因此所有既有日志消费方不受影响
- 按模型计价（`config.py:_MODEL_RATES`）取代此前对所有模型套用 Sonnet 单价的
  做法 —— 那让 Opus 低估 1.67 倍、Haiku 高估 3 倍，而 token 预算闸与路由
  break-even 分析都依赖这个数字
- 新增 `quota_exhausted` 错误类别。余额耗尽与用量窗口耗尽都返回 429，此前会以
  30 秒退避一直重试到耗光本次运行的预算；现在两者都直接中止
- 停止 worker 时，先把它写下的内容以 `wip:` 提交保存到它自己的分支，再强制移除
  worktree —— 包括循环检测与卡死超时这些无人值守的自动路径
- 三道"跑真东西再断言"的闸：`check-cc-plugin-components.sh` 真实加载插件并把
  解析结果与代码树比对；`check-ci-checklist.py` 把文档化的提交前清单与 CI 实际
  调用的闸比对，并拒绝无法执行的命令；`regen-settings-example.py` 从
  `_SETTINGS_DEFAULTS` 生成设置参考文件
- `frontend-design` 升级为平台感知的界面流水线，覆盖 web、Apple、Android、
  Windows、跨平台与演示文稿等目标

### 变更

- `opus` 与 `sonnet` 别名解析到 Opus 5 与 Sonnet 5；被取代的旧 ID 继续被接受，
  以保证既有 task 行与 evidence bundle 仍可解析。`configs/models.env` 现在会被
  `loop-runner.sh` source，而不再被硬编码的 `claude-sonnet-4-6` 覆盖
- orchestrator 的 worktree 迁出 `.claude/worktrees/` —— Claude Code 把该目录
  声明为自己的托管池，并会随 session 一起删除

### 修复

- Claude Code 插件宣称提供 37 个 agent 与 14 个 hook，实际一个都没加载：
  `agents` 写成文件路径数组虽然符合 schema，却解析不出任何东西，而
  `plugin validate --strict` 对此照样返回 0
- 内存 watchdog 匹配不到 orchestrator 实际构建的任何命令 —— 它的模式要求
  `claude` 与 `-p` 之间还有一个 token —— 因此在内存压力下从未释放任何内存。
  它还会向 `sh -c` 外壳而非 agent 发信号，并且按 pid 而非存活时长排序
- worker 活跃度启发式读取的是 Claude Code 从未写过的记录路径，而它的测试
  自己构造了同样错误的布局，因此在永远返回 "unknown" 的情况下始终是绿的
- GitHub issue 创建超时会把一个任务分叉成不断增长的重复对；`task_id` 被写入
  每个 issue body，却从未被读回
- `/brief` 探测 `localhost:4000`，而 orchestrator 绑定的是 8765
- 两个消费方把 `.claude/loop-state` 当 KEY=VALUE 解析，而 `loop-runner.sh`
  写的是 `.claude/loop-state.json`，因此 session 启动时的 loop 横幅一直是空的。
  `converged` 现在会被持久化，而不再只是一个 shell 局部变量
- 每次 session 启动都会注入指向已被取代的模型代次的指引

### 新增

- Loop 新增 crash-safe phase recovery：只有显式、身份匹配的 `--resume` 才会
  恢复；普通启动忽略旧 checkpoint，`--help` 不产生副作用
- Windows Git Bash 全新安装现在会把所有 hooks 与 status-line commands
  包装为经 `bash.exe` 执行，与已有 settings 的迁移路径保持一致
- `delivery abandon` 新增放弃过渡：面向已被取代、尚未发布的工作，要求精确的
  HEAD lease 与非空理由；已发布的 GitHub PR 只有在实时检查证明其在该精确
  head 上已 closed 后才能放弃
- 原生 `$codex-usage` workflow，显示 Clade 的 95% 目标使用节奏
- 通过已认证的 Codex app-server 安全读取 rate limits，不打开凭证文件
- 幂等配置 Codex 原生 five-hour 与 weekly status-line fields
- 极简、可选图标、详细三种 styles，十种 themes，以及 JSON 输出

### 修复

- 重装现在会精确镜像每个 repo-managed skill 子树，清除陈旧或意外嵌套的
  内容，同时保留无关的用户自有 skill 目录
- Loop 完成对账现在由 coordinator 独占并 fail-closed：只有 worker、syntax、
  test 与最终 verify 全部通过后，才按精确 task-to-goal 证据勾选；即使
  leftover sweep 为空也会计入 worker 自建 commits，串行/并行 worker 失败
  均会传播非零退出码
- Loop supervisor CLI 失败现在会保留 provider 原始响应，并以独立、可恢复的
  `supervisor_failed` 结果立即停止，不再把失败当成空计划反复执行并误报为
  `max_iterations`；该结果及其他终止性执行失败都会返回非零进程退出码
- Loop planning 现在会保留原始 supervisor 输出、安全提取嵌套 JSON、限制
  planner tools、在 checkpoint 前初始化自定义 log 目录、只验证当前 iteration
  的变更、共享一个 task JSON parser，并以 worker 格式分发恢复任务
- Routing settings 会拒绝 `NaN` 与无限阈值，避免持久化无法通过 JSON
  round-trip 的数值
- `delivery abandon` 现在按分支发现 PR，而不是信任可能过期的 `published`
  标记——未记录的 open PR 会阻止放弃，在记录 head 上已 merged 的 PR 会被
  reconcile 而不是被误标为 abandoned
- Task 更新会在写入前，针对生效的 runtime 重新校验生效的已持久化 connection，
  而不是等到执行时才失败

### 变更

- 生成的 MCP skill catalogs 现在与 manifest 对齐；生成的 Codex plugin 内容
  变化时会同步刷新 plugin cache version

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
