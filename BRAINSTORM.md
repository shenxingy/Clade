# BRAINSTORM — Unprocessed Ideas

*This is the inbox. Ideas go in; once processed into VISION.md/TODO.md, they're cleared.*

---

## 2026-03-03 — 新项目: 中文版 Granola（AI 笔记整理）

**灵感:** Granola (AI meeting notes) 的中文版 + 扩展版

**核心概念:** 录入一次，N 种结构化输出
- 同一段音频/文字输入，按不同"整理方案"生成完全不同的结构
- 会议纪要：决议 + action items + 参会人 + 时间线
- 日记：第一人称叙事 + 情绪标注 + 日期归档
- 作文：起承转合结构 + 修辞润色
- 自传：时间线 + 人物关系图 + 章节
- 论文：论点 + 论据 + 引用格式 + 摘要

**差异化:**
- 中文原生（ASR + LLM 都针对中文优化）
- 多模板系统是核心壁垒（不只是会议笔记）
- 模板可扩展（用户自定义整理方案）

**待明确:**
- 输入方式：实时录音？上传音频？直接打字？多种并存？
- 目标用户：学生？职场？创作者？
- 技术栈：移动端？Web？桌面？
- 商业模式：免费+付费模板？订阅？

**可能的子功能 / 关联项目 → 见下方"老照片整理+回忆录"**

**对 claude-code-kit 的价值:**
- 作为第3个真实测试项目（alongside owlcast, ai-ap-manager）
- 从零开始建项目 → 测试 start.sh 的全流程（不只是修已有代码）
- 涉及 ASR + LLM + 前端 → 覆盖更多 pipeline 类型

---

## 2026-03-03 — 老照片整理 + AI 回忆录

**来源:** 和外公聊天 — 老年人想整理老照片，但手动归纳太费劲

**核心概念:** 扫描/导入照片 → AI 自动整理 → 可选生成回忆录
1. **照片整理层**: 扫描纸质照片 / 导入手机相册 → AI 识别人脸、场景、时间 → 自动分类（按人物、时间线、事件）→ 去重、修复（老照片增强）
2. **回忆录层** (与 Granola 项目交叉): 照片 + 口述录音 → AI 整理成回忆录章节（时间线 + 人物 + 故事）

**用户画像:** 老年人（操作必须极简） + 子女辅助（帮爸妈扫描、设置）

**技术拆解:**
- 照片扫描: 手机摄像头 + 自动裁切矫正（OpenCV / 现成SDK）
- 人脸聚类: face_recognition / InsightFace → 自动按人物分组
- 场景/时间识别: CLIP + EXIF + OCR（照片背面手写日期）
- 老照片修复/上色: 现有模型（CodeFormer, DDColor）
- 回忆录生成: 照片元数据 + 口述转写 → LLM 整理 (复用 Granola 的模板引擎)

**与 Granola 项目的关系:**
- 回忆录 = Granola 的一个模板（输入: 照片+口述 → 输出: 回忆录结构）
- 可以是 Granola 的子功能，也可以是独立 app
- 共享: ASR引擎、LLM整理引擎、模板系统

**风险/待验证:**
- 市场上可能有现成 app（Google Photos 已经做了很多自动整理）
- 老年人 UX 极难做（字要大、步骤要少、容错要高）
- 纸质照片扫描质量参差不齐
- 需要验证: 老年人愿意口述吗？子女愿意帮忙设置吗？

---

## 2026-03-03 — OpenClaw 易用性 + 个人工具链

几个交织的想法，待拆分：

### A. OpenClaw Mac 安装包
- 老板做了 Windows 安装包，缺 Mac 版
- 非技术人员安装太难 → 需要图形化引导安装
- 难点：我自己在 Linux 服务器上开发，本地 Mac 已有 OpenClaw → 没有"从零安装 Mac"的环境来测试
- 可能方案：macOS .dmg / Homebrew tap / 一键脚本 + 图形 setup wizard

### B. OpenClaw Skills 生态
- 现状：啥 skill 也没装，只用最基本功能（Telegram 沟通 + 写日记）
- 不敢随便下载别人的 skill → 需要审核机制
- 可以自己开发、也可以广泛搜索后筛选适合自己的
- 想法：类似 claude-code-kit 的 "OpenClaw Kit" — 自定义 skills + 配置，甚至和 claude-code-kit 联动

### C. OpenClaw 深度使用研究
- 还没研究透它的编辑方式、操作流程
- 目前只用 Telegram 接口，很多功能没碰
- 需要一个系统性的"怎么把 OpenClaw 用好"的研究

### D. 预算约束
- Claude Code Pro $17/month，token 很快用完
- 影响所有需要大量 LLM 调用的方案（kit stress test、新项目开发等）
- 需要考虑：哪些操作用 haiku 省钱、哪些必须用 sonnet/opus

**这些想法之间的关系：**
- B + C 可以合并 → "研究 OpenClaw + 建立个人 skill 工具包"
- A 是独立任务（打包分发）
- D 是所有项目的横切约束

---
