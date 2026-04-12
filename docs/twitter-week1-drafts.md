# Twitter Week 1 Drafts — Clade Launch

*基于 2026-04-11 GTM 策略 | 发布节奏：Day 1 → Day 4 → Day 6*

---

## Day 1 — 反直觉 Hook（打第一炮）

**发布时机：** 周二/周三，美东时间 8-10 AM（北京时间 21:00-23:00）

```
Claude Code is incredibly powerful.

It's also incredibly easy to accidentally run `rm -rf` on your project.

I built a pre-tool guardian that blocks 47 dangerous operations before they execute.

It's been running in my setup for 3 months. Here's what it's caught 👇

[thread follows]
```

**Thread 继续（可选展开）：**

```
The most common catches in my logs:

1. `rm -rf` on wrong directory — 3x
2. `git push --force` to main — 5x
3. `DROP TABLE` in migration — 2x
4. Force-overwriting .env files — 4x

Each one would have been a bad day without the hook.

The guardian runs as a PreToolUse hook. It intercepts every Bash/Edit/Write
call and pattern-matches against 47 blocked operations.

Code: github.com/shenxingy/clade
```

---

## Day 4 — Thread（5 个最有用的 Claude Code Hooks）

**发布时机：** Day 1 发出后第3天

```
Claude Code has hooks. Most people don't use them.

Here are the 5 most impactful ones I've built over 6 months:

🧵 Thread
```

**1/6**
```
Hook #1: Pre-Tool Guardian

Blocks 47 dangerous operations before they execute.
`rm -rf`, force-push to main, `DROP TABLE`, `.env` overwrites.

This is why I can let Claude run overnight without babysitting it.

PreToolUse hook, 80 lines of bash.
```

**2/6**
```
Hook #2: Correction Detector

Every time you correct Claude's behavior, this hook fires.
Claude writes a reusable rule to corrections/rules.md.
That rule gets injected into every future session.

Claude literally learns from its mistakes across sessions.

PostToolUse hook + memory injection.
```

**3/6**
```
Hook #3: Stop Check

Blocks Claude from declaring "done" when:
- There are uncommitted staged files
- .claude/blockers.md has open items

Prevents false-done responses that waste your review time.

Stop hook, 30 lines.
```

**4/6**
```
Hook #4: Post-Edit Lint

Runs linter/formatter immediately after every file edit.
Claude sees the output and fixes issues inline — no manual lint loop.

Works with ruff, eslint, prettier, whatever your stack uses.

PostToolUse hook.
```

**5/6**
```
Hook #5: Session Context Loader

On session start, injects:
- Recent corrections and rules
- Current project status
- Active blockers

Zero-context-loss between sessions. Works especially well with
/handoff → /pickup for overnight runs.

SessionStart hook.
```

**6/6**
```
All 5 hooks are part of Clade — a framework I built to make
Claude Code actually autonomous.

29 slash commands + 14 hooks + correction learning loop.

github.com/shenxingy/clade

What hooks are you running? Always looking for new ideas 👇
```

---

## Day 6 — 数据帖（过夜运行结果）

**发布时机：** DEV.to 文章发布同天，互相引流

```
I let Claude Code run overnight for [X] consecutive nights.

Results:
- [N] tasks completed autonomously
- 0 unrecoverable disasters
- [M] corrections logged → became reusable rules
- Saved ~[H] hours of manual coding

The secret: 14 event hooks + a safety guardian.

Here's exactly how I set it up 👇

[link to DEV.to article or GitHub]
```

> ⚠️ **填写前替换：**
> - `[X]` → 实际连续过夜运行天数
> - `[N]` → 实际完成任务数（可从 orchestrator DB 查）
> - `[M]` → 实际 corrections/rules.md 条目数
> - `[H]` → 估算节省时间

**查询实际数据的命令：**
```bash
# 总完成任务数
sqlite3 ~/.claude/orchestrator.db "SELECT COUNT(*) FROM tasks WHERE status='done'"

# corrections 条目数
grep -c "^\- " ~/.claude/corrections/rules.md 2>/dev/null || echo 0
```

---

## 备用：产品发布帖（MCP 发布时用）

```
Just shipped: pip install clade-mcp

All 29 Clade skills now work in Cursor, Windsurf, and Claude Desktop via MCP.

No full install needed. One command.

[screenshot of Cursor with clade_ tools visible]
```

---

## 注意事项

- **不要同一天发 HN + PH**，流量会分散
- **每条帖子结尾留问题**，触发评论（算法加权）
- **Day 1 帖子发出后**，主动在 r/ClaudeAI 相关帖子下留言，带流量过来
- **Thread 帖**比单条帖子平均触达高 2-3x，优先用 Thread 格式
