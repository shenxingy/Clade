---
name: EVALUATION-STANDARD.md
date: 2026-03-31
status: methodology
note: "This is the evaluation methodology document, not a research document to be evaluated"
---

# Research Processing Evaluation Standard

**Date**: 2026-03-31
**Last Updated**: 2026-03-31 (添加双向对等比较原则)
**Purpose**: 双向对等评估 — Clade 现有实现和研究建议同等地位，谁更好听谁的

---

## 核心原则：双向对等，不偏不倚

**错误的立场（我之前的做法）：**
- 研究文档 = 正确答案，Clade = 被审查方
- 研究说啥好，Clade 就应该改成啥

**正确的立场：**
- Clade 现有实现和研究建议是平等比较的双方
- 哪个更好，就用哪个的实现
- Clade 设计比研究更详细更好 → 保留 Clade，标记 integrated
- 研究设计比 Clade 更好 → 标记 needs_work，具体规划改动
- 两者差不多 → 选更简单的实现

**判断顺序（每次比较必须按这个来）：**

```
1. Clade 现有实现是什么？（必须具体查到代码，不能猜）
2. 研究的建议是什么？（必须具体，不能泛泛）
3. 两者对比：
   - Clade 明显更好 → integrated（Clade 胜出）
   - 研究明显更好 → needs_work（研究胜出）
   - 两者差不多 → integrated（保留 Clade，简单优先）
   - 研究有趣但和 Clade 场景不匹配 → reference
   - 研究建议和 Clade 目标矛盾 → not_applicable
```

---

## 评估分类

| Category | 含义 | 行动 |
|----------|------|------|
| `integrated` | Clade 实现 ≥ 研究建议（更好或相等） | 记录，附上 commit SHA |
| `needs_work` | 研究建议明显更好，Clade 有具体差距 | 规划具体改动 |
| `reference` | 研究有趣但对 Clade 场景不适用 | 记录，不要求实现 |
| `not_applicable` | 研究和 Clade 目标矛盾 | 解释原因 |

---

## 操作流程（必须逐条执行）

### 第1步：查代码（先查代码，再读研究）

在读研究文档之前或同时：
- 用 Grep/Read 找到 Clade 对应的实现代码
- 确认实现的具体行为，不是"大概有"
- 记录具体文件路径和关键代码片段

**这一步不可跳过。** 不能凭印象说"Clade 有这个功能"。

### 第2步：读研究（全部读，不跳章节）

- 所有章节都要读，尤其是 recommendations / patterns / borrowable sections
- 提取每条建议，包括原文的 impact rating（High/Medium/Low）
- 不要提前下结论

### 第3步：逐项比较（每条建议都要有结论）

对每个 pattern/recommendation：

```
Clade 做了什么？（具体代码）
研究建议什么？（具体方案）
哪个更好？好在哪里？
结论：integrated / needs_work / reference / not_applicable
```

**要写清楚判断依据，不能只写"Clade 已有"。**

### 第4步：gap 存在 → 直接改代码（不是写 TODO，是直接动手）

**发现 gap 后必须立即改代码，不能只记录。**

```
发现 needs_work gap →
  立即动手改代码 →
  改完后对照研究建议验证是否满足要求 →
  如果不满足 → 继续 iterate 改 →
  直到满足研究建议为止 →
  才算处理完毕
```

**gap 判断标准（必须同时满足才是真实 gap）：**
1. 研究建议具体且可操作
2. Clade 现有实现明显更差
3. 改进成本合理，值得投入
4. Clade 场景确实需要这个能力

### 第5步：验证 commit SHA

integrated_items 里引用的 commit 必须用 `git log --oneline --all -- <file>` 验证。
不能写猜的 commit SHA。

### 第6步：输出 frontmatter + 处理结果

```yaml
---
name: filename
date: YYYY-MM-DD
status: integrated | needs_work | reference | not_applicable
review_date: YYYY-MM-DD
summary:
  - "评估了什么"
  - "核心结论"
integrated_items:
  - "Feature X — Clade 更好，代码在 xxx，原因是 yyy"
needs_work_items:
  - "Feature Y — 研究更好，差距是 zzz，已修改为 aa bb"
reference_items:
  - "Pattern Z — 研究有道理但对 Clade 场景不适用，原因是 qq"
not_applicable_items:
  - "Pattern W — 和 Clade 目标矛盾，原因"
---
```

---

## 常见错误清单

| 错误 | 正确做法 |
|------|---------|
| "Clade 有这个" — 凭印象，没查代码 | 必须找到具体代码文件 |
| "研究说 X 更好" — 只读摘要没读细节 | 读完全部章节再判断 |
| commit SHA 瞎写 | 用 git log 验证 |
| 把"类似"当成"等同" | 必须逐项比较具体实现 |
| "差不多" — 研究好一点点就不改 | 必须"明显更好"才标记 needs_work |
| 发现 gap 但只写 TODO 不改代码 | **发现 gap 后直接改代码，改完再验证** |
| 过度设计 — 研究里提到了 Clade 就要学 | 只有"明显更好"才学 |
| 把"有"当"需要" | 先问：Clade 场景是否真的需要这个？ |

---

## 处理顺序

按时间顺序，最早的先处理：

1. `batch-tasks.md` (2026-02-19)
2. `models.md` (2026-02-18)
3. `hooks.md`
4. `solo-dev-velocity-playbook.md` (2026-02-22)
5. `openclaw-dev-velocity-analysis.md` (2026-02-22)
6. `power-users.md`
7. `subagents.md`
8. `2026-03-30-stripe-minions-pi-agent.md`
9. `2026-03-30-agentic-coding-landscape.md`
10. [其余16篇 ...]
