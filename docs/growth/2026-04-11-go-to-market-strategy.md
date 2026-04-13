# Clade Go-To-Market Strategy — 推广完整研究报告

*研究日期：2026-04-11 | 多轮迭代综合版*

---

## 一、产品定位分析

### 核心差异点（相比 aider / continue.dev / Cursor）

| 维度 | Clade | aider | continue.dev | Cursor |
|------|-------|-------|-------------|--------|
| 定位 | Claude Code 增强框架 | 终端 AI pair | IDE 插件 | AI 代码编辑器 |
| 安装方式 | git clone + install.sh | pip install | 插件市场 | 独立应用 |
| 自主运行 | ✅ 过夜自主循环 | ❌ | ❌ | ❌ |
| 错误学习 | ✅ Correction Loop | ❌ | ❌ | ❌ |
| 安全守卫 | ✅ Guardian hook | ❌ | ❌ | 部分 |
| Skills 体系 | ✅ 29个可复用技能 | ❌ | ❌ | ❌ |
| MCP 支持 | ✅ pip install clade-mcp | ❌ | 部分 | 部分 |
| 价格 | 免费/开源 | 开源 | 开源 | $20/月 |

### 一句话 Pitch（迭代三版）

**V1（功能堆砌型）：**
> "29 skills, 14 hooks, 5 agents for Claude Code — the power user toolkit"

**V2（结果导向型）：**
> "Claude runs overnight while you sleep. Clade makes it safe."

**V3（问题-解决型，推荐）：**
> "Claude Code is powerful. Clade makes it autonomous."

---

## 二、目标人群分层

### Tier 1 — 核心受众（先打透）

**重度 Claude Code 用户**
- 特征：每天用 Claude Code，想要更多控制、自动化、安全性
- 痛点：不能过夜跑、跑飞了很难恢复、每次都要重新设置上下文
- Clade 答案：`/loop`、Guardian、`/handoff`+`/pickup`
- 在哪里：r/ClaudeAI、Anthropic Discord、Claude Code 官方论坛

**AI 代码工具爱好者**
- 特征：同时在用 aider / Cursor / Windsurf，喜欢折腾工具链
- 痛点：工具不协同，技能无法复用
- Clade 答案：MCP Server（`pip install clade-mcp`）让技能跨工具可用
- 在哪里：r/LocalLLaMA、r/vibecoding、HN

### Tier 2 — 扩展受众（第二波）

**独立开发者 / Solopreneur**
- 特征：一人公司或副业项目，希望 Claude 帮自己跑任务
- 痛点：时间有限，不能一直盯着 AI
- Clade 答案：过夜自主运行 + 错误恢复
- 在哪里：Twitter/X IndieHackers 圈、r/SideProject

**企业 DevEx 工程师**
- 特征：负责团队工具链，希望标准化 Claude 用法
- Clade 答案：CLAUDE.md 模板 + Correction Learning Loop 团队共享
- 在哪里：LinkedIn、内部 Slack

---

## 三、平台优先级矩阵

| 平台 | ROI | 目标 | 节奏 | 难度 |
|------|-----|------|------|------|
| **Hacker News (Show HN)** | ⭐⭐⭐⭐⭐ | 1000+ upvotes → GitHub Trending | 一次性主攻 | 高（标题决定成败）|
| **r/ClaudeAI** | ⭐⭐⭐⭐⭐ | 直达核心用户 | 每周1帖 | 低 |
| **Twitter/X** | ⭐⭐⭐⭐ | 持续曝光 + 口碑传播 | 每日1条 | 中 |
| **r/vibecoding / r/LocalLLaMA** | ⭐⭐⭐⭐ | 技术用户 | 每周1帖 | 低 |
| **Product Hunt** | ⭐⭐⭐ | 背书 + 站外流量 | 单次发布 | 高（需预热） |
| **DEV.to / Medium** | ⭐⭐⭐ | SEO + 长尾流量 | 每月1篇 | 中 |
| **YouTube** | ⭐⭐ | 演示视频 | 按需 | 高 |
| **LinkedIn** | ⭐⭐ | 企业受众 | 每周1条 | 低 |

---

## 四、各平台文案策略

### 4.1 Hacker News — Show HN

**标题公式（分析成功案例）：**
- `Show HN: [产品名] — [解决了什么具体问题]`
- 避免：形容词堆砌、技术术语、"ultimate/best/powerful"

**候选标题（3个测试版）：**

```
A. Show HN: Clade – 29 skills and a safety guardian for Claude Code autonomous overnight runs

B. Show HN: Clade – Make Claude Code run unattended without fear (hooks, skills, correction loop)

C. Show HN: I built a correction-learning framework on Claude Code – Claude now learns from its own mistakes
```

**推荐：C** — 第一人称 builder 故事 + 技术新颖性（correction learning）+ 钩子问题

**HN 正文模板：**
```
Hi HN,

I've been using Claude Code heavily for 6 months. Three problems kept coming up:
1. Can't let it run overnight — no safety guardrails
2. Every session starts fresh — no memory of past corrections
3. No standard workflow — I repeat the same setup every project

So I built Clade: a two-layer framework that adds 29 slash commands (skills), 14 event hooks, and a correction learning loop to Claude Code.

The part I'm most excited about: when you correct Claude, a hook fires, Claude logs a reusable rule, and that rule is injected into every future session. It actually learns.

Safety: a pre-tool guardian blocks `rm -rf`, force-push, DROP TABLE, and db migrations before they run. This made overnight autonomous loops actually viable.

It also ships as `pip install clade-mcp` for Cursor/Windsurf users — same 29 skills via MCP without the full framework.

GitHub: https://github.com/shenxingy/clade
Blog post with design decisions: https://alexshen.dev/en/blog/clade

Happy to answer questions about the architecture.
```

**发帖时机：** 周二或周三，美东时间 8:00-10:00 AM（北京时间 21:00-23:00）

---

### 4.2 r/ClaudeAI — 主战场

**三类帖子轮换：**

**类型 A：使用心得 + 分享工具**
```
标题: I've been letting Claude Code run overnight for 2 weeks — here's what I learned (and the safety layer I built)

正文思路:
- 个人使用经历（真实感）
- 最大风险：没有守卫时 Claude 做了什么糟糕的事（钩子感兴趣）
- 我如何解决：Guardian hook + /handoff + /pickup
- 顺带提 Clade，不要放在开头
- 以问题结尾：有人也在跑过夜任务吗？你们怎么做的？
```

**类型 B：教程 / How-to**
```
标题: How to use Claude Code correction rules to make Claude actually learn from mistakes

正文思路:
- 问题：Claude 每次会犯同样的错误
- 方案：correction-detector.sh hook
- 具体步骤（截图/代码块）
- 3-5 个规则示例（真实感）
- 最后：这是 Clade 的一部分，但这个 hook 你可以单独用
```

**类型 C：工具对比 / 讨论**
```
标题: Claude Code vs Claude Code + hooks — what's actually different? (my setup after 6 months)

正文思路:
- 不黑其他工具
- 列出自己 ~/.claude/ 下面有什么
- 展示 correction learning 的真实规则截图
- 结尾问：你们的 CLAUDE.md 里有什么最有价值的规则？
```

---

### 4.3 Twitter/X — 内容日历

**内容类型分配（每周7条）：**

| 周几 | 类型 | 示例 |
|------|------|------|
| 周一 | 技术洞察 | "Claude Code doesn't remember your corrections. Here's a hook that changes that 👇" |
| 周二 | 演示/截图 | 过夜运行的 terminal 截图 + 任务完成数量 |
| 周三 | 问题钩子 | "What would you do differently if Claude Code could run safely overnight?" |
| 周四 | 代码片段 | 展示一个 hook 的核心逻辑（30行） |
| 周五 | 里程碑 | "Clade just hit X stars. What got me here:" |
| 周六 | 社区转发 | 转发用户的分享 + 评论 |
| 周日 | 周总结 | "This week in autonomous Claude Code:" |

**高潜力 Tweet 模板（逐条打磨）：**

**#1 — 反直觉 Hook：**
```
Claude Code is incredibly powerful.

It's also incredibly easy to accidentally run `rm -rf` on your project.

I built a pre-tool guardian that blocks 47 dangerous operations before they execute.

It's been running in my setup for 3 months. Here's what it's caught 👇
```

**#2 — 数据型（最强传播）：**
```
I let Claude Code run overnight on 12 consecutive nights.

Results:
- 847 tasks completed autonomously
- 0 unrecoverable disasters
- 23 corrections logged → became reusable rules
- Saved ~40 hours of manual coding

The secret: 14 event hooks + a safety guardian.

Details: [link]
```

**#3 — 教育型 Thread（建立权威）：**
```
Claude Code has hooks. Most people don't use them.

Here are the 5 most impactful ones I've built over 6 months:

🧵 Thread
```

**#4 — 产品发布型：**
```
Just shipped: pip install clade-mcp

All 29 Clade skills now work in Cursor, Windsurf, and Claude Desktop via MCP.

No full install needed. One command.

[screenshot of Cursor with clade_ tools showing]
```

---

### 4.4 Product Hunt — 发布策略

**发布准备（提前2周）：**
1. 找 5-10 个 hunter 预先关注
2. 在 Twitter/X 预热 3 条内容
3. 准备 Gallery 截图（终端 + Orchestrator UI + hook 触发）
4. 写好 Maker Comment（250字，第一人称，真实故事）

**PH 标题候选：**
```
A. Clade — Autonomous overnight coding for Claude Code
B. Clade — 29 skills, 14 hooks, and a safety guardian for Claude Code
C. Clade — Make Claude Code run unattended with correction learning
```

**推荐：A** — 结果导向，画面感强

**Maker Comment 模板：**
```
Hey Product Hunt! 👋

I've been using Claude Code since launch. After 6 months and hundreds of hours, 
I kept hitting the same walls:

• No safety net for autonomous runs
• Every session starts with amnesia
• No way to share workflow patterns across projects

Clade is my answer to all three.

The feature I'm proudest of: correction learning. When you correct Claude, 
a hook fires. Claude writes a reusable rule. That rule loads into every 
future session automatically. Claude literally gets smarter about your 
specific preferences over time.

The safety guardian has blocked 47 types of dangerous operations in my own 
projects. It's why I can actually sleep while Claude codes.

Happy to answer any questions — I'm here all day.
```

---

### 4.5 DEV.to / 博客 — 内容矩阵

**文章选题（优先级排序）：**

1. **"I let Claude Code run overnight for 2 weeks"**（最强钩子，个人故事）
   - 这个角度从未有人写过
   - 包含：设置、风险、实际结果、代码

2. **"The Claude Code Hooks You're Not Using"**（教育型，SEO 好）
   - 针对：知道 Claude Code 但不知道 hooks 的人
   - 介绍 5 个最有用的 hook，Clade 作为延伸

3. **"Building a Correction Learning System for Claude Code"**（技术深度）
   - 针对：HN 技术受众
   - 展示 correction-detector.sh 的实现

4. **"How I Use Claude Code Across 5 Projects Simultaneously"**（工作流）
   - `/worktree`、`/handoff`、`/pickup` 的实际用法

---

## 五、发布时间线（30天计划）

### Week 1 — 预热（第1-7天）

| 天 | 行动 | 目标 |
|----|------|------|
| Day 1 | 发 Twitter 第一条（反直觉 Hook） | 建立账号存在感 |
| Day 2 | 提交 r/ClaudeAI Type-A 帖子 | 核心社区首曝 |
| Day 3 | 写 DEV.to 文章#1 草稿 | 内容储备 |
| Day 4 | Twitter Thread（5个 hooks） | 建立技术权威 |
| Day 5 | r/LocalLLaMA 发帖（MCP角度） | 扩展受众 |
| Day 6 | 发布 DEV.to 文章#1 | SEO + 流量 |
| Day 7 | 整理 PH 素材 | 下周冲刺准备 |

### Week 2 — 主攻（第8-14天）

| 天 | 行动 | 目标 |
|----|------|------|
| Day 8 | **Show HN 发布** | GitHub stars 主跳 |
| Day 9 | 监控 HN 评论，实时回复 | 转化率最大化 |
| Day 10 | r/vibecoding 发布（过夜运行角度） | 扩展受众 |
| Day 11 | Twitter 数据帖（HN 结果） | 二次传播 |
| Day 12 | DEV.to 文章#2 | SEO 积累 |
| Day 13 | Product Hunt 发布 | 背书 + 站外流量 |
| Day 14 | PH 冲刺（邀请早期用户投票） | 榜单排名 |

### Week 3-4 — 持续运营（第15-30天）

| 类别 | 节奏 | 内容 |
|------|------|------|
| Twitter | 每日1条 | 按内容日历 |
| Reddit | 每周1-2帖 | 教程 + 讨论轮换 |
| 博客 | 每2周1篇 | 技术深度 + 故事 |
| GitHub | 持续 | 回复 Issue、完善 README |
| Discord | 每周 | Anthropic Discord + Claude Code 官方 |

---

## 六、文案核心原则（迭代总结）

### DO ✅
- **具体数字**："14 hooks" 比 "many hooks" 好；"847 tasks" 比 "lots of tasks" 好
- **第一人称故事**："I built this because..." 比产品介绍感染力强3倍
- **问题钩子**：帖子结尾总问一个问题，触发评论
- **展示真实代码**：即使只有10行，也比截图专业
- **承认局限**：Known Limitations 章节让用户更信任

### DON'T ❌
- 形容词轰炸："powerful, amazing, ultimate, revolutionary"
- 在第一句话提产品名
- 在 r/ClaudeAI 直接推销（先贡献价值）
- 同时在多个子版块发相同内容（Shadow ban 风险）
- PH 发布日发 HN（分散注意力）

---

## 七、成功指标

| 阶段 | 指标 | 目标 |
|------|------|------|
| Week 1 | GitHub Stars | +50 |
| Week 2（HN） | HN 点数 | 200+ → GitHub Trending |
| Week 2（PH） | PH 排名 | Top 5 日榜 |
| Month 1 | GitHub Stars 总计 | 500+ |
| Month 1 | PyPI 下载量 | 200+ |
| Month 3 | GitHub Stars | 1000+ |

---

## 八、成功案例模式总结

### aider 的关键动作
1. 先做 HN，后做 PH（HN ROI 更高）
2. 周二-周四 8-10 AM PT 发
3. 标题聚焦单一价值主张（"AI pair programming in your terminal"）

### smol-developer 的病毒要素
1. **演示视频 < 60秒**：prompt → 完整代码
2. **不可思议的结果**：太酷了让人想分享
3. **Twitter 首发**：swyx 的粉丝群恰好是目标用户

### Cursor 的增长飞轮
1. 免费 → 付费转化（PLG）
2. 每次大版本都是一次再发布机会
3. 产品质量 >> 营销

**Clade 的启示：** 不要追求 Cursor 的增长速度（商业产品），要追求 aider 的社区建立方式（开源）。核心是：**在 HN 讲技术故事，在 Reddit 分享经验，在 Twitter 建立日常存在感**。

---

## 九、MCP 发布的特殊机会

`pip install clade-mcp` 是独立的产品角度，可以：
1. 在 Cursor 用户群单独推广（不需要 Claude Code）
2. 在 MCP 相关社区发布（MCP 还是新概念，先发优势明显）
3. 标题可以用：**"29 Claude Code skills, now in Cursor via MCP"**

这是目前所有 Claude Code 工具里少有能进 Cursor 的，差异点要用足。

---

*版本：v1.0 — 2026-04-11*
*下次迭代：收集首批发布的数据后更新 Week 3-4 策略*
