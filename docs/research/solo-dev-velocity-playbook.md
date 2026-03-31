# Solo 开发提速 Playbook

> 基于 steipete (Peter Steinberger) 的公开工具和博客提炼
> 适用场景：solo 开发，直接 commit main，没有 PR 流程，瓶颈在 prompt 输入
> 研究日期：2026-02-22

---

## 诊断：你的瓶颈在哪里

steipete 原话（和你的问题几乎一样）：

> "The amount of software I can create is now mostly limited by inference time and hard thinking."
> "The bottleneck has moved from code generation to **strategic decision-making**."

你说的"prompt 输入是上限"是正确诊断。你已经在做正确的事（6 个 terminal 并行），缺的是：
1. **工具**来降低"任务输入"的摩擦
2. **机制**让 agent 在你不看的时候自己跑
3. **上下文管理**避免每个 session 都重新交代背景

---

## 立即可用的工具（按收益排序）

### 1. `--dangerously-skip-permissions` — 去掉所有确认弹窗

**核心收益**：agent 不再每步问你"我可以执行这个命令吗"，全程自主跑完

```bash
# 加到 ~/.zshrc 或 ~/.bashrc
alias cc="claude --dangerously-skip-permissions"
alias cly="claude --dangerously-skip-permissions"  # steipete 的命名

# 用法
cc  # 进入完全自主模式，直接告诉它任务
```

**风险**：agent 可能删文件、改配置。对策：
- 确保 git 干净（commit 后再启动）
- 大任务前打一个 `git stash` 或 tag 作为检查点

---

### 2. `committer` 脚本 — 多 agent 并行时不互相干扰

当你同时跑 3-4 个 agent 在同一个 repo，普通 `git add .` 会 stage 所有文件，agent 会互相干扰。`committer` 强制精确指定文件。

把这个脚本放到 `~/.local/bin/committer`（或者 clade 的某个公共位置）：

```bash
#!/usr/bin/env bash
# committer "commit message" file1 file2 ...
# 不允许 "." 作为路径

set -euo pipefail

MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  echo "Usage: committer <message> <file>..." >&2
  exit 1
fi
shift

if [[ $# -eq 0 ]]; then
  echo "Error: must specify files explicitly, not '.'" >&2
  exit 1
fi

for f in "$@"; do
  if [[ "$f" == "." ]]; then
    echo "Error: '.' not allowed. Specify files explicitly." >&2
    exit 1
  fi
done

# 清空暂存区，只 stage 指定文件
git restore --staged :/ 2>/dev/null || true
git add -- "$@"
git commit -m "$MSG"
```

```bash
chmod +x ~/.local/bin/committer
```

写进全局 `CLAUDE.md`：
```
Use `committer "message" file1 file2` for all commits. Never use `git add .`
```

---

### 3. VibeTunnel — 浏览器里一眼看所有 agent 状态

GitHub: https://github.com/amantus-ai/vibetunnel

**作用**：你不用在 6 个 terminal tab 间反复切换，打开一个浏览器窗口就能看到所有 agent 在干什么。

安装（macOS）：从 GitHub releases 下载 .dmg

安装后，写入全局 `~/.claude/CLAUDE.md`：
```markdown
When starting any task, switching focus, or reaching a milestone, update the terminal title:
  vt title "Current action - project context"

Examples:
  vt title "Implementing auth token refresh - backend"
  vt title "Writing tests for session manager - api"
  vt title "Debugging CI failures - frontend"
  vt title "WAITING - blocked on database migration"
  vt title "DONE - auth complete, awaiting review"
```

这样 agent 自己汇报进度，你不用问它。

---

### 4. Task Queue 模式 — 一次性投喂多个任务

steipete 发现：agent 能处理 message queue——你在它跑任务时继续发消息，它会排队处理，不会丢失。

**实践**：
```
你打开 cc，告诉它 4 件事：
1. "先做这个 bug fix"
2. "然后给这个函数写测试"
3. "然后把这个变量重命名到整个 codebase"
4. "最后更新 README"

全部发完，你去开另一个 terminal 处理另一个项目
```

关键：每个任务之间加 `---` 或明确说"完成后再做下一个"，避免 agent 并发做。

---

### 5. `/handoff` + `/pickup` 命令 — 跨 session 的上下文接力

**问题**：context window 满了，或者你中途停掉了 agent，重新开一个要重新交代所有背景。

在你的 clade 的 skills 里加入这两个：

**`/handoff`** — 当前 agent 在结束前输出状态快照：
```markdown
Output a handoff document with:
1. What was accomplished (with file paths)
2. What's still pending and why
3. git status -sb
4. Current blockers
5. Exact next steps (ordered, concrete)
6. Any gotchas or traps to avoid

Save to: .claude/handoff-{timestamp}.md
```

**`/pickup`** — 新 session 快速上手：
```markdown
1. Read CLAUDE.md for project context
2. Check .claude/handoff-*.md for previous session state (newest file)
3. Run git status -sb
4. Summarize: what state are we in, what's the next concrete action?
Then proceed.
```

---

### 6. Oracle — 卡住时用第二个模型 review

```bash
npx -y @steipete/oracle -p "why is this failing?" --file "src/auth.ts"

# 多文件
npx -y @steipete/oracle -p "review this refactor for correctness" --file "src/**/*.ts"

# 多模型
npx -y @steipete/oracle --models claude-opus-4-6,gpt-5 -p "any issues?"
```

GitHub: https://github.com/steipete/oracle

**用途**：遇到诡异 bug、大 refactor 前验证思路、agent 给出两个方案选哪个。

---

### 7. Ralph — 批处理长任务的 supervisor loop

适合：把一类重复性任务一次性做完（"把这 20 个组件全部加 loading state"）

GitHub: https://github.com/steipete/agent-scripts/blob/main/docs/subagent.md

```bash
# 启动 tmux 后台 session
tmux new-session -d -s task-runner 'claude --dangerously-skip-permissions'

# Ralph 发送任务序列
bun scripts/ralph.ts start --goal "Add error boundaries to all React components in src/components/"
```

Ralph 会：把大任务拆成子任务 → 分发给 agent → 等 agent 完成 → 分发下一个 → 写进度到 `.ralph/progress.md`。

你去睡觉，早上看结果。

---

## 你的瓶颈的真正解法

你说"commit 量只可能有几十"——这本来就不是对的衡量指标。

真正的问题是：**你的 prompt 输入速度限制了你能同时跑多少个 agent**。

### 解法：把"任务描述"工作提前批量完成

```
每天早上花 30 分钟，给当天要做的事全部写 task 文件：
- .claude/tasks/task-001.md: "Implement dark mode toggle..."
- .claude/tasks/task-002.md: "Fix the auth token refresh bug..."
- .claude/tasks/task-003.md: "Write E2E tests for checkout flow..."

然后同时开 3-4 个 terminal，每个喂一个 task 文件：
  cc < .claude/tasks/task-001.md
  cc < .claude/tasks/task-002.md
  ...

你去做别的，几小时后验收结果。
```

这样你的"prompt 输入"工作从实时变成了异步批处理——你的思考集中在任务设计上，不被执行阻断。

---

## 全局 CLAUDE.md 建议配置

写到 `~/.claude/CLAUDE.md`（所有项目通用）：

```markdown
# Agent Ground Rules

## Commits
- Always use `committer` script, never `git add .`
- Commit message: conventional format (feat/fix/refactor/test/chore)
- Commit small and often — each logical unit gets its own commit

## Communication
- Update terminal title with `vt title "action - context"` at each milestone
- When blocked, write to .claude/blockers.md and stop

## Autonomy
- Proceed without confirmation for file edits, test runs, builds
- Ask before: deleting files, modifying .env, running migrations

## Context Management
- At context ~80% full, run /handoff before starting new tasks
- If you see .claude/handoff-*.md, read it at session start
```

---

## 投入产出评估

| 工具 | 安装成本 | 日常节省 | 优先级 |
|------|----------|----------|--------|
| `--dangerously-skip-permissions` alias | 1 分钟 | 高（消除等待） | ⭐⭐⭐ 立即做 |
| `committer` 脚本 | 5 分钟 | 中（多 agent 必须） | ⭐⭐⭐ 立即做 |
| 全局 CLAUDE.md 配置 | 15 分钟 | 高（每个项目节省背景交代） | ⭐⭐⭐ 立即做 |
| `/handoff` + `/pickup` skills | 10 分钟 | 高（跨 session 不丢失上下文） | ⭐⭐ 本周做 |
| VibeTunnel | 10 分钟 | 中（仅 macOS，监控方便） | ⭐⭐ 本周做（如果用 macOS） |
| Task 文件批处理模式 | 0（改习惯） | 极高（解决 prompt 输入瓶颈） | ⭐⭐⭐ 立即改习惯 |
| Oracle | 5 分钟 | 中（遇到问题时才用） | ⭐ 需要时装 |
| Ralph | 30 分钟 | 高（批处理专用） | ⭐⭐ 有大批处理任务时 |

---

## Sources

- [Commanding Your Claude Code Army](https://steipete.me/posts/2025/commanding-your-claude-code-army)
- [Command your Claude Code Army, Reloaded](https://steipete.me/posts/2025/command-your-claude-code-army-reloaded)
- [Shipping at Inference-Speed](https://steipete.me/posts/2025/shipping-at-inference-speed)
- [Claude Code is My Computer](https://steipete.me/posts/2025/claude-code-is-my-computer)
- [steipete/agent-scripts](https://github.com/steipete/agent-scripts)
- [amantus-ai/vibetunnel](https://github.com/amantus-ai/vibetunnel)
- [steipete/oracle](https://github.com/steipete/oracle)
