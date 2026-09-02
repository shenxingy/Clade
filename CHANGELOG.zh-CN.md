# 更新记录

这里记录 Clade 的重要 release。`clade-mcp` Python package 与公开 tags 使用
semantic versioning。

[English](CHANGELOG.md)

## Unreleased

## [0.3.1] — 2026-09-02

### 安全

- orchestrator 的控制面此前完全不需要认证。所有路由与两个 WebSocket 对任何能
  连上这个 socket 的人开放，而 `start.sh` 一旦检测到 Tailscale 就绑定
  `0.0.0.0` —— 这正是文档推荐的部署方式 —— 所以"它只在 loopback 上"从来
  不成立。任意一个写操作路由都能开出一个 session，其 worker 会以启动服务的
  账户身份、以绕过权限的方式运行；而 `GET /api/settings` 会原样返回
  `webhook_secret` 与 usage hub tokens。现在由 ASGI middleware 强制要求
  bearer token —— 与 `BaseHTTPMiddleware` 不同，它同样能看到 WebSocket scope。
  默认关闭，规则与本仓库对 `webhook_secret` 已有的约定一致：没有配置 token 即
  拒绝，除非显式打开 `api_allow_unauthenticated`。token 在首次启动时生成，写入
  保存逻辑已经 chmod 0600 的设置文件。三个豁免项都在
  `orchestrator/api_auth.py` 中逐条说明：SPA 外壳与版本探测、已签名的 GitHub
  webhook，以及 usage ingest —— 且仅在 `usage_ingest_token` 已设置时豁免，
  从而顺带关掉了该端点原先"为空即开放"的默认行为
- 设置中的 secrets 在返回时按 key 名后缀打码；若保存时回传的仍是掩码，则保留
  已存储的原值。设置面板会整体 round-trip 这个对象，没有这层保护的话，第一次
  保存就会把每个 secret 覆盖成它自己的掩码
- CORS 实际放行了所有来源。`allow_origins` 是精确匹配列表，因此
  `http://localhost:*` 这个默认值谁也匹配不到，而旁边的 regex 自己就把请求放
  行了。现在 regex 覆盖 `https`（TLS 前端不再被静默拦截），并收紧到 Tailscale
  真实使用的 CGNAT 段 `100.64.0.0/10` —— 此前它对整个 `100.0.0.0/8` 授予了
  CORS，而其中大部分是公网可路由地址。配置项在精确比较前会去除首尾空白，
  空格分隔值里的 ` http://b` 不再静默失配
- worktree 只隔离工作树，不隔离 `.git`。在 worker 的 worktree 内，
  `git rev-parse --git-common-dir` 解析到父仓库，因此 agent 可以写入
  `<main>/.git/hooks/pre-commit`，并在操作者下一次提交时执行。现在 worker
  在启动前对父仓库的 hooks 与 config 取快照，若发生变化则拒绝验证与提交
  （`worker_git_surface_guard`，默认开启）
- 这条逃逸现在不只是被检测，而是被阻止：可选的 Landlock ruleset 让共享的
  `.git/hooks` 与 `.git/config` 对 worker 进程本身不可写
  （`worker_sandbox`，默认关闭）
- `install.sh` 升级路径从不写入 deny 规则。`templates/settings.json` 带有
  `Read(~/.ssh/**)`、`Read(~/.aws/**)`、`Read(~/**/.env)`，但合并分支只写
  `.hooks` 与 `.statusLine`，因此所有在 deny 列表出现之前安装过的机器，
  `permissions` 一直是 null —— 而 worker 正是以绕过权限的方式启动的，deny
  规则是最后一道约束。合并只做 deny 的并集，绝不扩大用户自己的 allow 列表
- worktree 隔离失败时静默放行。所有失败路径都丢弃了 git 的 stderr 并让 worker
  留在共享检出上；现在会直接抛错，而不是让未隔离的 agent 在操作者本人的工作树
  里运行（`worker_require_worktree`）
- worker 的 secret denylist 发布时是空的，因此一次都没有生效，持久化的 worker
  输出中从未真正脱敏过任何内容
- 签名只能证明事件来自 GitHub，不能证明事件作者有权指挥一个绕过权限的 worker。
  由 webhook 触发的工作现在要通过 fail-closed 的 actor 校验，且该校验完全从
  payload 本身计算（`orchestrator/webhook_trust.py`）—— 路径上没有任何可能
  fail open 的 API 调用
- 会在 fork PR 上运行的那两个 workflow，恰好就是没有做 SHA pinning 的两个，
  而它们运行时带写权限。现在每个 `uses:` 都是 commit SHA，由
  `configs/scripts/check-action-pinning.py` 强制
- 危险命令 guardian 此前按子串而非命令位置匹配，并且从未真正拦住 `rm -rf ~`。
  现在它还会拦截会杀掉自己启动进程的 `pkill -f` 模式

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
- worker 从它唯一的验证提交到 worktree 被强制删除之间没有任何记录，因此
  "第 14 次调用还对、第 15 次就错了"根本无从观察。现在 `worker-checkpoint.sh`
  在 agent 每次写入后，把整个 worktree 提交到它之外的一个影子仓库；独立的
  `--git-dir` 意味着独立的 index，checkpoint 不会与 worker 自己的提交争用。
  最终 SHA 与次数会在清理删除该仓库前写进 evidence bundle
  （`worker_checkpoint_shadow`）
- attempt evidence 现在是不可变、带版本与摘要链的 `clade.evidence/v1` 记录，
  且增量写入。此前验证结果只在终态一次性写入，一旦崩溃就丢失了"在哪里出错"
- `configs/scripts/red-phase-audit.py` 会把一个 commit *新增* 的测试拿到它的
  父提交上跑：本来就能通过的测试并不需要这次改动。它是诊断而非门禁，在本仓库
  约 17% 的提交上会触发。`--self-test` 用一正一负两个对照问这把尺子还能不能
  变红 —— 一个无法触发的检测器报出的干净 0% 和真正干净的代码库一模一样，而本
  仓库确实发布过这种情况 —— CI 每次 push 都会跑这组对照
- reward hacking 的缺口现在是被测量而不是被声称的：test-integrity 检测器针对
  带标注的对抗语料（`evals/hack_cases/`）打分，召回率 60% → 100%、误报
  27% → 7%；各信号计数交给 oracle 判断而不是直接判失败；resolve eval 会重跑
  held-out 测试，因此只糊弄可见测试集的补丁会被报为 GAMED 而不是 RESOLVED
- output styles（`configs/output-styles/`）—— 唯一一个修改 *system* prompt 而
  非追加用户消息的原语，因此能触及 `CLAUDE.md` 到不了的轮次。全部带
  `keep-coding-instructions: true`，且 `install.sh` 不会激活其中任何一个，
  选择权仍在用户
- `/radar` —— 三条泳道的 unknown-unknowns 发现（领域、从业者、自身使用），
  外加用于无人值守周度扫描的 `radar-cron.sh`
- `/outbound` —— 在产出物离开之前先验证它
- `/loop` 现在同时受挂钟时间（`--max-runtime`，默认 8 小时）与花费
  （`--max-cost`）约束，二者都在迭代之间检查；并新增 crash-safe phase
  recovery：只有显式、身份匹配的 `--resume` 才会恢复，普通启动忽略旧
  checkpoint，`--help` 不产生副作用
- 以 MIT 协议吸收 Müller-Brockmann 栅格与 Vignelli canon 两个设计 skill，
  以及 `design-lint` —— 一个针对渲染结果的校验器，会先解析 CSS 自定义属性
  再做对比度检查，并能捕捉跨反色区块的继承色对比度问题
- `frontend-design` 升级为平台感知的界面流水线，覆盖 web、Apple、Android、
  Windows、跨平台与演示文稿等目标
- 一批"跑真东西再断言"的闸：`check-cc-plugin-components.sh` 真实加载插件并把
  解析结果与代码树比对；`check-ci-checklist.py` 把文档化的提交前清单与 CI 实际
  调用的闸比对，并拒绝无法执行的命令；`regen-settings-example.py` 从
  `_SETTINGS_DEFAULTS` 生成设置参考；`check-references.py` 解析每一个 markdown
  链接、锚点与路径；`check-arch-map.py` 在架构图缺少某个 orchestrator 模块时
  失败；`doc-align.py verify` 为文档中由代码树推导出的计数把关
- correction-pairing 流水线新增 arXiv:2605.29442 测量出的协作类根因 ——
  自我汇报不实与违反约束现在可被提升 —— 且提升进全局 `CLAUDE.md` 的门槛改为
  按根因严重度判断，而不是按规则存活了多久
- Windows Git Bash 全新安装现在会把所有 hooks 与 status-line commands
  包装为经 `bash.exe` 执行，与已有 settings 的迁移路径保持一致
- `delivery abandon` 新增放弃过渡：面向已被取代、尚未发布的工作，要求精确的
  HEAD lease 与非空理由；已发布的 GitHub PR 只有在实时检查证明其在该精确
  head 上已 closed 后才能放弃
- 原生 `$codex-usage` workflow，显示 Clade 的 95% 目标使用节奏；通过已认证的
  Codex app-server 安全读取 rate limits；幂等配置 Codex 原生 five-hour 与
  weekly status-line fields；以及极简、可选图标、详细三种 styles，十种
  themes 与 JSON 输出

### 变更

- `opus` 与 `sonnet` 别名解析到 Opus 5 与 Sonnet 5；被取代的旧 ID 继续被接受，
  以保证既有 task 行与 evidence bundle 仍可解析。`configs/models.env` 现在会被
  `loop-runner.sh` source，而不再被硬编码的 `claude-sonnet-4-6` 覆盖
- orchestrator 的 worktree 迁出 `.claude/worktrees/` —— Claude Code 把该目录
  声明为自己的托管池，并会随 session 一起删除
- `task_queue.py` 与 `worker.py` 都已顶到 1500 行上限。DDL 拆到
  `task_schema.py`，worker 调度拆到 `worker_pool.py`（`worker.py` 继承它以绑定
  自己的 `Worker`）。行为不变
- 自动提交使用操作者本人的身份，并关闭 Claude co-author 署名
- README 把参考性内容移入 `docs/`，重新回到自己定的 300 行以内
- 生成的 MCP skill catalogs 现在与 manifest 对齐；生成的 Codex plugin 内容
  变化时会同步刷新 plugin cache version
- 所有分发面统一到同一个版本号。Codex plugin manifest 是唯一权威，
  `.claude-plugin/plugin.json` 由它生成，`clade-mcp` 的 `pyproject.toml`、
  `server.json` 与 `__version__` 全部报告 0.3.1 —— 此前该 package 在两个
  plugin manifest 都写着 0.3.1 的情况下，被钉在 0.2.0 长达 241 个提交

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
- 已经放弃的 `/loop` 运行此前被报成成功。现在会先判断是否收敛再判断上限，
  且目标项仍有剩余时 runner 以 2 退出
- Routing settings 会拒绝 `NaN` 与无限阈值，避免持久化无法通过 JSON
  round-trip 的数值
- `delivery abandon` 现在按分支发现 PR，而不是信任可能过期的 `published`
  标记——未记录的 open PR 会阻止放弃，在记录 head 上已 merged 的 PR 会被
  reconcile 而不是被误标为 abandoned
- Task 更新会在写入前，针对生效的 runtime 重新校验生效的已持久化 connection，
  而不是等到执行时才失败
- correction-history 的追加写不是原子的：并发写入者会把彼此的记录交错拼接，
  并让所有读取方读到被截断的内容
- PreCompact 的 prompt hook 因为缺少 `statusMessage`，把整个 prompt 打进了
  UI；auto-audit 则会把原始 prompt 片段提升进全局 `CLAUDE.md`
- 三条验证路径在非 Linux 上静默地什么都没测；PID 复用的保护在 macOS 上则
  从来就不存在
- pytest 输出现在只经由一份不受颜色影响的契约读取
  （`orchestrator/pytest_report.py`）；此前 resolve eval 与回归检测器在结构上
  都对带颜色的输出视而不见
- 设置参考文件声称覆盖所有 key，实际只有 75 个中的 33 个，其中一个还已经不是
  设置项
- CI 清单闸放过了一条会以 126 退出的文档化命令；另一个 syntax-check 闸在不安装
  依赖的 job 里 import 了 `aiosqlite`
- flow-skill 吸收留下的 135 条失效交叉引用、18 条指向同步从未拉取的上游文件的
  链接，以及吸收时被 1024 字符上限截断的 skill descriptions
- oracle 曾被交给一条对 86% 测试流量根本不适用的评审规则
- 文档曾要求用户运行一个从来不存在的 flow-skill 同步脚本

### 兼容性

- 从本版本起，控制面默认关闭。此前依赖免认证 socket 的部署，要么发送首次启动时
  写入 `~/.claude/orchestrator-settings.json` 的 bearer token，要么显式设置
  `api_allow_unauthenticated`
- `usage_ingest_token` 为空不再等于开放。向 hub 上报用量的节点需要在两端都配置
  该 token
- 被取代的模型 ID 仍被接受，既有 task 行与 evidence bundle 继续可解析
- `worker_sandbox`（Landlock）与 `worker_checkpoint_shadow` 默认关闭；
  `worker_git_surface_guard` 与 `worker_require_worktree` 默认开启
- FastAPI multi-worker orchestrator 仍为 Claude-specific

### 升级

```bash
pip install --upgrade clade-mcp
./install.sh          # 同步 skills、hooks、scripts —— 以及 deny 规则
```

Codex 原生安装：

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

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

[0.3.1]: https://github.com/shenxingy/Clade/compare/v0.2.0...v0.3.1
[0.2.0]: https://github.com/shenxingy/Clade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/shenxingy/Clade/releases/tag/v0.1.0
