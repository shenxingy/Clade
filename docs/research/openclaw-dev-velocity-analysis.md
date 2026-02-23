# OpenClaw 开发速度分析报告

> 研究目标：分析 https://github.com/openclaw/openclaw 异常高频的 commit 节奏，找出其背后的工具和方法，供我们借鉴。
> 研究日期：2026-02-22

---

## 一、项目概况

**仓库地址**: https://github.com/openclaw/openclaw

**项目定位**: "Your own personal AI assistant. Any OS. Any Platform. The lobster way."

OpenClaw 是一个**跨平台个人 AI 助手网关框架**，提供统一的 WebSocket 控制平面，将 WhatsApp、Telegram、Discord、Slack、Signal、iMessage、Microsoft Teams、Matrix、Zalo 等 9 种即时通讯平台接入到本地 AI Agent 运行时。

**技术栈**:
- 主语言: TypeScript (Node.js >= 22, ESM)
- 包管理: pnpm
- 测试框架: Vitest
- 构建: tsx
- 移动端: Swift (iOS/macOS), Android
- 即时通讯库: Baileys (WhatsApp), grammY (Telegram), discord.js, Bolt (Slack)
- 语音: ElevenLabs
- 浏览器自动化: Chrome/Chromium CDP

**规模**:
- Stars: 219,322
- Forks: 41,672
- Open Issues: 7,982
- Open PRs: 4,200+
- 总代码库大小: ~217MB
- 创建时间: 2025年11月24日
- 存续时间: 约 **90 天**

---

## 二、Commit 历史分析 — 数字令人震撼

### 2.1 总量与时间跨度

| 指标 | 数值 |
|---|---|
| 项目存续时间 | ~90 天 (2025-11-24 至 2026-02-23) |
| 总 commit 数 (GitHub API) | **约 15,004+** |
| 平均每天 | **~153 commits/天** |
| 平均每周 | **~1,072 commits/周** |

正常的中大型团队全职开发，每天 20-50 commits 已经算高产。**每天 153 commits 相当于每 9 分钟一个 commit，全天 24 小时不间断**。

### 2.2 每周 Commit 数量变化

| 周起始日 | Commits | 每天均值 |
|---|---|---|
| 2025-11-23 | 497 | 71/天 |
| 2025-11-30 | 258 | 37/天 |
| 2025-12-07 | 815 | 116/天 |
| 2025-12-14 | 630 | 90/天 |
| 2025-12-21 | 362 | 52/天 |
| 2025-12-28 | 562 | 80/天 |
| 2026-01-04 | 1,928 | 275/天 ← 第一次爆发 |
| 2026-01-11 | 1,618 | 231/天 |
| 2026-01-18 | 1,511 | 216/天 |
| 2026-01-25 | 817 | 117/天 |
| 2026-02-01 | 659 | 94/天 |
| 2026-02-08 | 1,492 | 213/天 |
| **2026-02-15** | **2,998** | **428/天 ← 绝对峰值** |
| 2026-02-22 | 857 | 122/天（周内不完整）|

**峰值周（2026-02-15）逐日分解**:
- 周日 Feb 15: 602 commits
- 周一 Feb 16: **835 commits（单日最高）**
- 周二 Feb 17: 250 commits
- 周三 Feb 18: 362 commits
- 周四 Feb 19: 334 commits
- 周五 Feb 20: 135 commits
- 周六 Feb 21: 480 commits

**2月16日 835 commits = 平均每 1.7 分钟一个 commit，连续 24 小时。**

### 2.3 Commit Message 格式特征

commit message 风格高度统一，遵循 Angular/Conventional Commits 格式：

```
fix(openrouter): remove conflicting reasoning_effort from payload
test(cron): avoid delivery.mode type widening in isolated announce test
refactor: extract shared dedupe helpers for runtime paths
chore(release): bump versions to 2026.2.23
fix(security): escape user input in HTML gallery to prevent stored XSS
```

**高频词汇统计**（反复出现的模式）：
- `dedupe` / `deduplicate` — 大量 refactor commit 以此为主题
- `harden` — 安全加固
- `fix(security):` — 安全修复专项标签
- `test:` + "consolidate / collapse / merge / table-drive" — 测试优化

**关键发现**: 多个 merge commit 的 body 中含有：

```
Merged via /review-pr -> /prepare-pr -> /merge-pr.
Prepared head SHA: cc8ef4bb05a71626152109ca0d70f3c17cb0100c
Co-authored-by: tenequm <22403766+tenequm@users.noreply.github.com>
Reviewed-by: @gumadeiras
```

`/review-pr -> /prepare-pr -> /merge-pr` 是一套**自定义 slash 命令工作流**，说明 PR 合并过程本身是被自动化工具（极可能是 Claude Code 的 slash skills）驱动的。

---

## 三、主力开发者分析

### 3.1 贡献者概况

| 开发者 | GitHub 用户 | 角色 | 典型 commit 频率 |
|---|---|---|---|
| Peter Steinberger | steipete | 创始人/主力 | 单日最高 24+ commits |
| Vignesh Natarajan | vignesh07 | 核心开发 | 约 4-10/天 |
| Tak Hoffman | Takhoffman | 核心开发 | 约 2-6/天 |
| Ayaan Zaidi | obviyus | 核心开发 | 约 4-8/天 |
| Vincent Koc | vincentkoc | Release 管理/CI | 约 2-5/天 |
| Aether AI Agent | aether-ai-agent | **AI Bot** | 1-3/天 |
| clawdinator[bot] | clawdinator | **自动化 Bot** | 间歇性 |

### 3.2 Peter Steinberger (steipete) 深度分析

**背景**:
- 前 PSPDFKit 创始人（PDF SDK 公司），13 年经验后退出
- 2025 年重归技术一线，专注 AI 开发工具
- 2026 年 2 月宣布加入 OpenAI 负责"将 agents 带给所有人"
- 博客 bio：**"Came back from retirement to mess with AI"**
- 维护工具 CodexBar（6.3k stars）：追踪 Claude、Codex、Cursor 等 AI 编程工具的 quota 使用情况

**2026年2月21日单日提交序列（部分）**:

```
18:40:59  refactor(test): use env helper in workspace skills prompt gating
18:41:28  refactor(test): reuse env helper in workspace skill status tests
18:41:57  refactor(test): reuse env helper in workspace skill sync gating
18:42:27  refactor(test): snapshot deprecated auth profile env in e2e
18:42:56  refactor(test): snapshot bundled hooks env in loader tests
18:43:58  refactor(test): snapshot env in shell utils e2e
```

**每 30-60 秒一个 commit**，内容为系统性的"将环境变量设置提取为共享 helper"的重构。这是典型的 AI agent 自动批量重构模式：给 AI 一个任务，AI 逐文件处理，每改完一个文件就 commit。

**最极端案例 — 2026年2月16日 23:47 的 5 秒级 commit 序列**:

```
23:47:20  extract shared session dir resolver
23:47:27  share system prompt bundle for context and export
23:47:35  share draft stream loop across slack and telegram
23:47:40  dedupe user bin path assembly helpers
23:47:48  dedupe schema and command parsing helpers
```

**28 秒内 5 个不同 commit，平均间隔 5.6 秒。** 人类无论多快都不可能在 5-7 秒内：理解代码、修改、stage、commit —— 这是自动化的铁证。

**steipete 自述的工作流**（来自其博客文章）：
- 主工具：**Claude Code**（"my main driver"）
- 终端：Ghostty
- 同时运行 **1-8 个并行 AI agents**，清理/测试/UI 工作分给不同 agent
- 使用 plan mode，小任务直接让 agent 做，大任务写到文件让 AI review
- 不用 git worktree，直接让多个 agent 并行工作在同一目录

### 3.3 Aether AI Agent — 确认的 AI Bot

**证据清单**：
1. 用户名明确含 `-agent` 后缀
2. 账号创建于 2026 年 2 月 13 日（仅 9 天历史）
3. 官网链接：tryaether.ai（AI 公司产品）
4. 获得 GitHub 成就 "Pair Extraordinaire"（说明被作为 Co-Author）
5. 所有 commit 主题 100% 是安全漏洞修复，格式为 `fix(security): OC-XX [vulnerability type]`，包含 CVSS 评分和 CWE 编号
6. 已获得 9 项 GitHub Security Advisory 认证

这是一个**AI 驱动的安全扫描和自动修补 bot**，发现漏洞、生成 PR、推送修复，全程无需人工介入。

---

## 四、代码质量与变更模式

### 4.1 Commit 粒度

项目以**极细粒度 commit** 为主，平均每个 commit 改动量约为 30-100 行：

```
refactor: extract shared dedupe helpers for runtime paths
Files: 4 files, 86 added, 40 deleted

test: dedupe fixtures and test harness setup
Files: 2 files, 47 added, 63 deleted
```

这是典型的 AI 辅助开发模式：AI agent 每完成一个最小可验证单元就 commit，而不是人工积累后一次性提交大功能。

### 4.2 AI 生成代码的直接证据

1. **`/review-pr -> /prepare-pr -> /merge-pr` 命令链** — 多个 merge commit 的 message body 中明确记录了这个命令序列，这是 Claude Code slash command workflow 的特征，说明 PR 的 review、准备和合并都由 AI agent 完成。

2. **CONTRIBUTING.md 明确欢迎 AI 贡献**:
   ```
   AI PRs are first-class citizens here.
   Please disclose: AI tool used (Claude, Codex, etc.),
   level of testing, prompt/session log if available
   ```

3. **CLAUDE.md 文件存在**（符号链接到 AGENTS.md） — 项目专门维护了 Claude Code 的 agents 配置文档，包含详细的代码规范、发布流程、multiagent safety 注意事项。

4. **28 秒内 5 个 commit** — 人工不可能，已分析见 §3.2。

---

## 五、CI/CD 和工作流分析

### 5.1 GitHub Actions 工作流清单

| 文件 | 功能 |
|---|---|
| ci.yml | 多平台 CI（Node/Windows/macOS/Android），push 和 PR 触发 |
| auto-response.yml | 自动回复 issue/PR 标签，自动关闭无效 issue |
| docker-release.yml | Docker 镜像发布 |
| install-smoke.yml | 安装冒烟测试 |
| labeler.yml | 自动打标签 |
| stale.yml | 处理过期 issue/PR |
| workflow-sanity.yml | 工作流健全性检查 |

**关键发现**：auto-response.yml 中有逻辑：
- 自动关闭带特定标签的 issue（support/testflight/third-party-extension）
- 自动关闭超过 20 个 label 的 PR
- 自动关闭标为 `dirty` 的 PR

这说明维护者面临如此巨大的 PR 量，必须用自动化来处理。项目维护者自述：**"We're getting approximately one PR every two minutes."**

### 5.2 PR 自动化流程

```
外部贡献者 / AI agent 提交 PR
         ↓
clawdinator[bot] 自动打标签
         ↓
维护者用 /review-pr 让 Claude Code 做 AI 代码审查
         ↓
维护者用 /prepare-pr 让 Claude Code 准备 merge
         ↓
维护者用 /merge-pr 执行 merge
```

整个 PR 流程中，AI 几乎参与了每一步。

---

## 六、综合判断

### 6.1 "不正常"程度量化

| 对比基准 | 正常范围 | OpenClaw 实际 | 倍数 |
|---|---|---|---|
| 普通开源项目 commit/天 | 1-5 | 153 | 30-150x |
| 活跃商业项目 commit/天 | 10-30 | 153 | 5-15x |
| 峰值单日 | — | 835 | — |
| 28秒内 commit 数 | 1（人工极限） | 5 | 5x（物理不可能手工） |

### 6.2 证据链汇总

**A 级证据（直接证明 AI agent 驱动）**:
1. commit body 明确出现 `Merged via /review-pr -> /prepare-pr -> /merge-pr`
2. 项目存在 `CLAUDE.md` (symlink → `AGENTS.md`)
3. `aether-ai-agent` bot 账号在主分支上有 commit 记录
4. `clawdinator[bot]` 在贡献者列表中
5. CONTRIBUTING.md："AI PRs are first-class citizens"
6. 28 秒内 5 个 commit（2026-02-16 23:47:20~23:47:48）

**B 级证据（强力间接证明）**:
1. steipete 博客："Claude Code is my main driver"，同时运行 1-8 个并行 AI agents
2. steipete 维护 CodexBar（追踪 Claude/Codex quota 使用），是重度 AI 工具用户
3. steipete 2026 年加入 OpenAI，深度绑定 AI agent 生态
4. 大量 `dedupe`/`consolidate`/`harden` commit 批次，是 AI 系统性重构的典型产出
5. commit 频率在凌晨不减反增，人类无法持续，AI agent 可以

### 6.3 使用的具体工具和方法（推测，有证据支撑）

**1. Claude Code（主力工具）**
- steipete 亲口说明是"main driver"
- `/review-pr /prepare-pr /merge-pr` 是 Claude Code slash commands 的特征
- `CLAUDE.md` 的存在
- 运行多个并行 Claude Code agent sessions

**2. 并行 Agent 工作流**
- 同时运行 4-8 个 agent 处理不同任务（test/refactor/security/docs）
- 每个 agent 独立 commit，导致 commit 数量爆炸性增长
- Agent 在凌晨/夜间持续工作，人类不需要在线

**3. Aether AI（专项安全 bot）**
- 专门的 AI 安全扫描 bot，自动发现和修复安全漏洞
- 在主分支直接有 commit 记录（非 PR 方式）

**4. clawdinator（项目自建 bot）**
- 自动 PR 标签分类，自动关闭无效 PR

**5. 自定义 Claude Code Slash Skills**
- `/review-pr -> /prepare-pr -> /merge-pr` 命令链
- 将整个 PR 流程 AI 化

---

## 七、可借鉴的实践清单

以下是 OpenClaw 的具体实践，按可行性排序：

### 立即可用（低成本高收益）

- [ ] **用 Claude Code 做小粒度 commit**：让 agent 每完成一个最小单元就 commit，而不是积累再提交。好处：更清晰的 git history，更容易 review，agent 出错时回滚成本低。
- [ ] **`CLAUDE.md` / `AGENTS.md` 文件**：在每个项目根目录维护一份给 Claude Code 看的项目说明，包含代码规范、禁止事项、架构说明。减少每次 context 传递的成本。
- [ ] **Conventional Commits 格式**：统一 commit message 格式，让 AI 生成的 commit message 更容易筛选和分析。
- [ ] **自定义 Slash Skills**：参考 OpenClaw 的 `/review-pr /prepare-pr /merge-pr`，为我们的常见工作流建立 slash skill（我们已有 `/commit`, `/sync`, `/review`，可继续扩展）。

### 中期投入（需要设计工作流）

- [ ] **并行 Agent 策略**：将任务分解为独立模块，同时开多个 Claude Code session。例如：一个 agent 写功能，一个 agent 写测试，一个 agent 做文档更新，互不阻塞。
- [ ] **AI 驱动的 PR review 流程**：在 PR 合并前，用 Claude Code 做初步 review，降低人工 review 的认知负担，加快合并速度。
- [ ] **Agent 夜间批量任务**：将系统性重构任务（dedupe、cleanup、test consolidation）交给 agent 在夜间/非工作时间执行，早上看结果。

### 长期基础设施（高投入）

- [ ] **专项自动化 Bot**（类似 Aether AI）：为特定领域（安全扫描、依赖更新、测试覆盖）建立专门的 AI bot，持续后台运行。
- [ ] **自动化 Issue/PR 分类 Bot**（类似 clawdinator）：用 GitHub Actions + LLM 自动分类 issue/PR，减少维护负担。

---

## 八、结论

OpenClaw 是**目前最典型的 AI-native 开发节奏项目之一**。每天 153 commits 的数字，本质上反映的是：**当一个熟练的 AI 工程师同时调度 4-8 个 AI agent，配合专项 bot，在没有传统代码审查瓶颈的情况下连续工作 18+ 小时，现代 AI 辅助开发能达到的理论上限。**

核心秘密不是某个神奇的工具，而是**工作流的彻底 AI 化**：
1. 写代码 → AI agent 写
2. 写测试 → AI agent 写
3. Review PR → AI agent review
4. 合并 PR → AI agent 辅助合并
5. 安全扫描 → AI bot 自动修复
6. Issue 分类 → bot 自动处理

人类的角色变成了：**设定方向、拆分任务、验收结果**。
