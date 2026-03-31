# Aider Deep Research

**Date**: 2026-03-30  
**Source**: https://github.com/Aider-AI/aider  
**Commit**: depth-1 clone, March 2026

---

## 1. Repository Map — 核心创新完整原理

### 1.1 技术选型：tree-sitter + PageRank

Aider 的 repo map 不用 ctags（已废弃），也不用向量检索。核心是两层技术叠加：

1. **tree-sitter**（静态语法分析）— 提取所有 `def`（定义）和 `ref`（引用）tag
2. **NetworkX PageRank**（图排名算法）— 对文件按"被引用重要性"打分，适配上下文窗口

### 1.2 Tag 提取：tree-sitter .scm 查询

每种语言有一个 `.scm` 查询文件（`aider/queries/tree-sitter-languages/`），例如 Python：

```scheme
(class_definition
  name: (identifier) @name.definition.class) @definition.class

(function_definition
  name: (identifier) @name.definition.function) @definition.function

(call
  function: [
      (identifier) @name.reference.call
      (attribute
        attribute: (identifier) @name.reference.call)
  ]) @reference.call
```

捕获结果分两类：
- `name.definition.*` → `kind = "def"`：函数名、类名
- `name.reference.*` → `kind = "ref"`：调用点

每个 tag 是一个 `Tag` namedtuple：`(rel_fname, fname, line, name, kind)`

**fallback 机制**：如果某语言的 .scm 只有 `def` 没有 `ref`（如 C++），用 pygments tokenizer 扫描所有 `Token.Name` 作为 ref 补充。

**缓存**：用 `diskcache`（SQLite 底层）存 tags，key 是文件路径，命中条件是 mtime 没变。缓存版本号控制（`CACHE_VERSION = 3/4`），格式变了会自动失效。

### 1.3 图构建：文件依赖图

```python
# 核心数据结构
defines: dict[symbol_name → set[rel_fname]]   # 谁定义了这个符号
references: dict[symbol_name → list[rel_fname]]  # 谁引用了这个符号
definitions: dict[(rel_fname, symbol_name) → set[Tag]]  # 精确 tag 位置

G = nx.MultiDiGraph()
# 边：referencer → definer，表示"referencer 的代码调用了 definer 里的东西"
G.add_edge(referencer, definer, weight=use_mul * sqrt(num_refs), ident=symbol)
```

**权重乘数规则**（影响 PageRank 结果）：

| 条件 | 乘数 |
|------|------|
| 符号在当前 chat 消息中被提及 | ×10 |
| 符号是 snake_case/kebab-case/camelCase 且长度 ≥ 8 | ×10 |
| 符号以 `_` 开头（私有） | ×0.1 |
| 符号被超过 5 个文件定义（过于通用） | ×0.1 |
| referencer 是当前 chat 中的文件 | ×50 |
| num_refs 做平方根压缩（防高频低价值符号主导） | sqrt |

### 1.4 Personalization：偏向用户上下文

PageRank 的 `personalization` 参数让算法偏向特定节点：

```python
personalize = 100 / len(fnames)   # 基础值

# 文件在 chat 中 → 加 personalize
# 文件路径/文件名在消息 idents 中被提及 → 加 personalize
```

最终调用：
```python
ranked = nx.pagerank(G, weight="weight", personalization=personalization, dangling=personalization)
```

### 1.5 大小控制：二分搜索适配 token 预算

这是 repo map 真正精妙之处。最终输出的 map 大小必须接近 `max_map_tokens`，通过**二分搜索**实现：

```python
lower_bound = 0
upper_bound = num_tags           # 全量 tags 数
middle = min(max_map_tokens // 25, num_tags)  # 初始猜测

while lower_bound <= upper_bound:
    tree = self.to_tree(ranked_tags[:middle], chat_rel_fnames)
    num_tokens = self.token_count(tree)
    
    pct_err = abs(num_tokens - max_map_tokens) / max_map_tokens
    if num_tokens <= max_map_tokens and num_tokens > best_tree_tokens:
        best_tree = tree
        best_tree_tokens = num_tokens
    if pct_err < 0.15:  # 15% 误差内就接受
        break
    
    # 标准二分更新 lower/upper bound
    middle = (lower_bound + upper_bound) // 2
```

**自适应 token 预算**：

- 有文件在 chat 中：使用 `max_map_tokens`（默认 1024）
- 没有文件在 chat 中：扩大到 `min(max_map_tokens × 8, context_window - 4096)`

即"空白状态"下 map 最多可扩展 8 倍，给 LLM 更全的仓库视图。

**Token 估算优化**：对大文本用采样估算（抽取 1% 行计算平均密度），避免对每次二分都做完整 tokenize。

### 1.6 Map 渲染：TreeContext 展示函数签名

`to_tree()` 将 ranked tags 渲染成人类可读的代码骨架：

```
aider/repomap.py:
⋮...
class RepoMap:
│    def __init__(self, map_tokens=1024, ...):
│    def get_repo_map(self, chat_files, other_files, ...):
│    def get_ranked_tags(self, chat_fnames, other_fnames, ...):
│    def to_tree(self, tags, chat_rel_fnames):
```

用 `grep-ast` 库的 `TreeContext` 实现：只展示函数签名+头部，不展示函数体。每行截断到 100 字符（防 minified JS 爆炸）。

### 1.7 缓存策略

内存级 map cache，key 包含 `(chat_fnames, other_fnames, max_map_tokens, mentioned_fnames, mentioned_idents)`：

- `refresh = "auto"`（默认）：map 计算 > 1 秒时启用缓存，否则每次重算
- `refresh = "files"`：只要输入文件没变就缓存
- `refresh = "manual"`：用户手动 `/map-refresh` 才重算
- `refresh = "always"`：每次都重算

---

## 2. Architect Mode — 规划与执行分离

### 2.1 两层 Coder 架构

```
ArchitectCoder (edit_format="architect")
    └── 继承自 AskCoder（只问答，不编辑文件）
        系统提示: "Act as an expert architect engineer..."
        输出: 自然语言描述的修改方案，NO代码块
        
        reply_completed() 被触发后:
            └── 创建 EditorEditBlockCoder (edit_format="editor-diff")
                系统提示: "Act as an expert software developer who edits source code..."
                输入: architect 的输出（作为 user message）
                输出: SEARCH/REPLACE 块
                map_tokens = 0（不给 editor 看 repo map）
```

### 2.2 关键实现细节

```python
# architect_coder.py
def reply_completed(self):
    content = self.partial_response_content  # architect 的分析文字
    
    editor_model = self.main_model.editor_model or self.main_model
    
    editor_coder = Coder.create(
        main_model=editor_model,
        edit_format=self.main_model.editor_edit_format,  # e.g. "editor-diff"
        from_coder=self,   # 继承 abs_fnames, done_messages 等上下文
        map_tokens=0,      # editor 不需要 repo map
        cache_prompts=False,
        summarize_from_coder=False,
    )
    editor_coder.run(with_message=content, preproc=False)
    
    self.move_back_cur_messages("I made those changes to the files.")
    self.total_cost = editor_coder.total_cost
```

Architect 的输出直接作为 editor 的 user message 注入，editor 的任务只有一件事：把描述转成 SEARCH/REPLACE 块。

### 2.3 Prompt 设计哲学

**Architect prompt**（战略层）:
```
Act as an expert architect engineer and provide direction to your editor engineer.
...
Explain all needed code changes clearly and completely, but concisely.
Just show the changes needed.
DO NOT show the entire updated function/file/etc!
```

**Editor prompt**（战术层）:
```
Act as an expert software developer who edits source code.
Describe each change with a *SEARCH/REPLACE block*...
ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!
```

注意 editor 的 prompt 不包含 `go_ahead_tip`、`shell_cmd_prompt`、`rename_with_shell`——这些都在 `EditorEditBlockPrompts` 中明确置空。Editor 是纯粹的"执行器"。

### 2.4 Model 配置

典型配置（`model-settings.yml`）：

```yaml
- name: claude-3-5-sonnet-20241022
  edit_format: diff               # 直接用时的格式
  editor_model_name: claude-3-5-sonnet-20241022
  editor_edit_format: editor-diff # architect 模式下 editor 的格式
```

用户选择 `--architect` 时，同一个 Claude 模型扮演两个角色（architect + editor），但使用不同的 system prompt 和不同的 edit_format。

---

## 3. Edit Formats — 设计哲学与变体

### 3.1 格式全览

| Format | Class | Edit_format 字符串 | 用途 |
|--------|-------|---------------------|------|
| SEARCH/REPLACE | `EditBlockCoder` | `diff` | 主力格式，Claude/GPT-4o |
| Unified diff | `UnifiedDiffCoder` | `udiff` | GPT-4-turbo 等旧模型 |
| Whole file | `WholeFileCoder` | `whole` | 弱模型/小文件 |
| Editor SEARCH/REPLACE | `EditorEditBlockCoder` | `editor-diff` | architect 模式下的 editor |
| Editor whole | `EditorWholeFileCoder` | `editor-whole` | architect + 弱 editor |
| Patch (V4A) | `PatchCoder` | `patch` | OpenAI codex 风格 |
| Ask | `AskCoder` | `ask` | 只问答，不修改文件 |
| Architect | `ArchitectCoder` | `architect` | 规划模式 |

### 3.2 为什么用 SEARCH/REPLACE 而不是 unified diff？

官方设计理由（从代码和注释推断）：

**unified diff 的问题**：
1. 行号容易错（模型生成的行号和实际文件对不上）
2. 上下文行必须精确匹配，但模型经常省略注释/空行
3. `UnifiedDiffCoder` 的错误信息更复杂（`UnifiedDiffNoMatch`, `UnifiedDiffNotUnique`）

**SEARCH/REPLACE 的优势**：
1. 不需要行号，只需要精确匹配一段文本
2. 错误可以给出"你是不是想匹配这些行"的 diff 提示（`find_similar_lines`）
3. 模型更容易生成正确格式（大量 few-shot 示例强化）
4. 支持 `...` 省略（`try_dotdotdots`），可以跳过中间不变的代码

### 3.3 SEARCH/REPLACE 的鲁棒性策略

匹配失败时，`replace_most_similar_chunk()` 依次尝试：

1. **精确匹配**（`perfect_replace`）：逐行完全相同
2. **leading whitespace 容错**（`replace_part_with_missing_leading_whitespace`）：模型经常漏掉缩进，统一去掉后再匹配，找到后按原文件缩进补回
3. **`...` 省略展开**（`try_dotdotdots`）：`...` 匹配任意行数的跳过
4. **fuzzy matching**（`replace_closest_edit_distance`，默认被注释掉）：SequenceMatcher 相似度 > 0.8（实验性，不稳定）

文件名查找（`find_filename`）也做模糊匹配：精确匹配 → basename 匹配 → `difflib.get_close_matches(cutoff=0.8)` → 任何带扩展名的结果。

### 3.4 SEARCH/REPLACE 正则

```python
HEAD    = r"^<{5,9} SEARCH>?\s*$"   # <<<<<<< SEARCH（5-9个<，兼容各种模型）
DIVIDER = r"^={5,9}\s*$"            # =======
UPDATED = r"^>{5,9} REPLACE\s*$"   # >>>>>>> REPLACE
```

宽松匹配（5-9个字符）是因为不同 LLM 会生成不同数量的 `<`。

### 3.5 Patch 格式（V4A）

`PatchCoder` 是最新添加的格式，使用 OpenAI 风格的 V4A diff：

```
*** Begin Patch
*** Update File: path/to/file.py
@@ ... @@
 context
-removed line
+added line
 context
*** End Patch
```

比 unified diff 更明确（文件名单独一行，不依赖 `---/+++`），比 SEARCH/REPLACE 更简洁（不需要完整的原始文本）。

---

## 4. 自动 Git 提交机制

### 4.1 完整流程

```
LLM 输出 SEARCH/REPLACE 块
    → apply_edits() 写入文件
    → auto_commit(edited_files, context=chat_history)
        → repo.get_diffs(fnames)        # git diff HEAD
        → repo.get_commit_message(diffs, context)
            → weak_model.simple_send_with_retries(messages)  # 用弱模型生成 message
        → git.commit(-m message --no-verify?)
        → 返回 (commit_hash, commit_message)
    → 把 commit hash 放入下一轮消息: "I committed changes: abc1234 fix: ..."
```

### 4.2 Commit Message 生成

使用 `commit_message_models()`：`[weak_model, main_model]` 列表，先用弱模型，失败再用强模型。

System prompt（`prompts.commit_system`）要求生成一行 conventional commit 格式的 message。Context 包含最近的对话历史，让 commit message 有语义。

### 4.3 /undo 机制

```python
def raw_cmd_undo(self, args):
    last_commit_hash = repo.get_head_commit_sha(short=True)
    
    # 安全检查 1：commit 必须是本 session 由 aider 创建的
    if last_commit_hash not in self.coder.aider_commit_hashes:
        raise Error("The last commit was not made by aider in this chat session.")
    
    # 安全检查 2：不能有 merge commit
    if len(last_commit.parents) > 1:
        raise Error("Merge commit, can't undo.")
    
    # 安全检查 3：已 push 到 origin 则拒绝
    if has_origin and local_head == remote_head:
        raise Error("Already pushed to origin, can't undo.")
    
    # 安全检查 4：只回滚 commit 改动的文件，不碰其他文件
    for file_path in changed_files_last_commit:
        repo.git.checkout("HEAD~1", file_path)  # 只 checkout 特定文件
    
    # 删掉这个 commit（soft reset 等价）
    repo.git.reset("--soft", "HEAD~1")
```

这是**选择性 undo**，不是 `git reset --hard HEAD~1`。只恢复 aider 改动的文件，保留其他工作区改动。

### 4.4 Attribution 控制

Aider 会在 git commit 中修改 author/committer 为 `"User Name (aider)"`，通过 `GIT_AUTHOR_NAME`/`GIT_COMMITTER_NAME` 环境变量实现，用 contextlib.ExitStack 确保 cleanup。

也支持 `Co-authored-by: aider (model-name) <aider@aider.chat>` trailer，通过 `--attribute-co-authored-by` 开启。

---

## 5. 模型无关设计 — LiteLLM 抽象层

### 5.1 架构

```
Coder (业务层)
    ↓ 调用
litellm.completion()   ← 统一 API，支持 100+ 模型
    ↓ 路由到
OpenAI / Anthropic / Gemini / DeepSeek / Bedrock / ...
```

`aider/llm.py` 中的 `LazyLiteLLM` 用 `__getattr__` 实现懒加载（litellm 启动耗时 1.5s，只在第一次 LLM 调用时加载）。

### 5.2 Model 元数据系统

每个模型的行为由 `ModelSettings` dataclass 控制：

```python
@dataclass
class ModelSettings:
    name: str
    edit_format: str = "whole"       # 默认 whole file（最保守）
    weak_model_name: Optional[str]   # 用于 commit message 等低优先级任务
    use_repo_map: bool = False        # 是否启用 repo map
    lazy: bool = False               # 是否在 prompt 中提醒不要偷懒
    overeager: bool = False          # 是否提醒不要改太多
    reminder: str = "user"           # system reminder 放 sys 还是 user 消息
    examples_as_sys_msg: bool = False # few-shot 放 system 还是 messages
    extra_params: Optional[dict]     # 传给 litellm 的额外参数（如 Anthropic beta headers）
    cache_control: bool = False      # 是否加 Anthropic prompt caching headers
    editor_model_name: Optional[str] # architect 模式的 editor
    editor_edit_format: Optional[str]
    reasoning_tag: Optional[str]     # 移除 CoT reasoning 内容的标签名
```

配置来源：`aider/resources/model-settings.yml`，在 import 时加载到 `MODEL_SETTINGS` 列表。

### 5.3 运行时模型选择逻辑

```python
class Model(ModelSettings):
    def configure_model_settings(self, model):
        # 1. 从 MODEL_SETTINGS 列表匹配（精确或前缀）
        # 2. 从 litellm 元数据推断 context window、cost
        # 3. 自动设置 max_chat_history_tokens = min(max(ctx/16, 1k), 8k)
```

### 5.4 模型感知的 Prompt 变体

不同模型需要不同处理：

- `lazy=True`（GPT-4o, Claude Sonnet）：系统提示末尾加"不要省略代码"提醒
- `overeager=True`（Claude 3.7 Sonnet）：加"不要修改没被要求修改的代码"提醒
- `examples_as_sys_msg=True`（Claude 系列）：few-shot 示例放入 system 消息而不是 messages 数组（Anthropic 推荐做法）
- `reminder = "sys"`：把格式提醒作为 system message 发送（GPT 用）
- `reminder = "user"`：把格式提醒附加到最后一条 user message（Claude 用）

---

## 6. Linting 集成 — 自动语法检测

### 6.1 完整 lint 流程

```
apply_edits() 写完文件
    → auto_commit() 提交
    → lint_edited(edited_files)
        for fname in edited_files:
            linter.lint(fname)
                → basic_lint()         # tree-sitter 语法错误检测
                → lint_python_compile()  # Python: compile() 检查
                → flake8_lint()          # Python: flake8 fatal 错误
        返回错误文本 + tree context（显示错误行的上下文代码）
    → 如果有错误: reflected_message = lint_errors
        → 下一轮 run_one() 循环把 lint_errors 作为 user message 发给 LLM
        → LLM 修复，最多 3 次反射（max_reflections = 3）
```

### 6.2 多层 Lint 策略

Python 文件三层检测：

1. **tree-sitter basic_lint**：通用语法检测，遍历 AST 找 ERROR 节点，适用于所有支持 tree-sitter 的语言
2. **compile()**：Python 特有，用 Python 解释器 compile，获取精确错误行和异常信息
3. **flake8**（只检测致命错误）：`--select=E9,F821,F823,F831,F406,F407,F701,F702,F704,F706`，只看未定义变量、语法错误等，不检查风格

用户也可通过 `--lint-cmd` 配置自定义 linter（如 `eslint`, `mypy`），替换或追加到语言特定 linter。

### 6.3 LintResult + TreeContext

错误输出格式化：

```python
res = "# Fix any errors below, if possible.\n\n"
res += lintres.text          # flake8/compile 错误文本
res += tree_context(fname, code, lintres.lines)  # 错误行的代码骨架（带行号 + 上下文）
```

`TreeContext` 在这里用 `mark_lois=True`（高亮感兴趣的行）和 `loi_pad=3`（上下 3 行上下文），让 LLM 精确看到是哪里出错了。

---

## 7. SWE-bench 表现与策略

### 7.1 历史成绩

- **2024-05**: SWE Bench Lite **26.3%**（当时 SOTA，前一名是 Amazon Q 的 20.3%）
- **2024-06**: SWE Bench（完整版）也取得 SOTA
- **2024-12**: 推出 Polyglot Leaderboard（C++/Go/Java/JS/Python/Rust）

### 7.2 基准测试策略

```
for each problem in SWE-bench:
    launch aider in problem repo
    submit problem statement as user message
    aider runs (auto-accept all suggestions)
    
    check "plausible correctness":
        - 编辑成功（无语法错误）
        - 不破坏 pre-existing tests
    
    if not plausible (up to 6 retries):
        alternate between GPT-4o and Claude Opus
    
    if all fail:
        pick solution with fewest edit/lint/test problems
```

关键点：**只用现有测试**，不看 held-out acceptance tests。这证明 aider 的 lint+test 反射机制对代码质量有实质性提升。

### 7.3 核心优势来源

官方分析（非 agentic）：
- **静态代码分析**（repo map）：无需 RAG，无需向量检索
- **可靠的代码编辑**（SEARCH/REPLACE + lint 反射）
- **保守的 agentic 行为**：没有自主执行任意代码、没有 web 搜索，减少了代价高昂的错误

---

## 8. 完整架构图

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Entry (main.py)                    │
│  --model, --architect, --edit-format, --map-tokens       │
└─────────────────┬───────────────────────────────────────┘
                  │ creates
                  ▼
┌─────────────────────────────────────────────────────────┐
│                    Coder.create()                         │
│  (Factory pattern: edit_format → concrete Coder class)   │
└──┬──────────────┬──────────────┬──────────────┬─────────┘
   │              │              │              │
   ▼              ▼              ▼              ▼
EditBlock    Architect      WholeFile       Udiff
Coder        Coder          Coder           Coder
(edit_format  (edit_format   (edit_format    (edit_format
 ="diff")      ="architect")  ="whole")       ="udiff")
                  │
                  │ reply_completed() spawns
                  ▼
            EditorEditBlock
            Coder
            (edit_format="editor-diff")

┌────────── BaseCoder (共享基础设施) ──────────────────────┐
│                                                           │
│  format_chat_chunks()                                     │
│    ChatChunks: system | examples | readonly | repo |      │
│                done | chat_files | cur | reminder         │
│                                                           │
│  send_message() → litellm.completion()                   │
│  apply_updates() → get_edits() → apply_edits()           │
│  auto_commit() → repo.commit() → get_commit_message()    │
│  lint_edited() → reflected_message (反射循环)            │
│  run_one() [反射循环: max 3 次]                           │
└───────────────────────────────────────────────────────────┘

┌────────── RepoMap ────────────────────────────────────────┐
│                                                            │
│  get_tags(fname)                                           │
│    tree-sitter parse → .scm queries → Tag(def/ref)        │
│    diskcache (SQLite) by mtime                             │
│                                                            │
│  get_ranked_tags()                                         │
│    defines/references → nx.MultiDiGraph                   │
│    weight = mul * sqrt(num_refs)                           │
│    nx.pagerank(personalization=chat_files)                 │
│                                                            │
│  get_ranked_tags_map_uncached()                            │
│    binary search → to_tree() → token_count()              │
│    fits within max_map_tokens ± 15%                        │
│                                                            │
│  render_tree()                                             │
│    TreeContext → function signatures (no bodies)           │
└────────────────────────────────────────────────────────────┘

┌────────── Model 抽象层 ──────────────────────────────────┐
│                                                            │
│  ModelSettings (dataclass)                                 │
│    edit_format / use_repo_map / lazy / overeager /        │
│    weak_model_name / editor_model_name / cache_control    │
│                                                            │
│  Model.configure_model_settings()                          │
│    YAML → ModelSettings → 动态行为控制                    │
│                                                            │
│  LazyLiteLLM → litellm.completion(model=name, ...)        │
│    OpenAI / Anthropic / Gemini / DeepSeek / Bedrock       │
└────────────────────────────────────────────────────────────┘

┌────────── GitRepo ───────────────────────────────────────┐
│  commit() → get_commit_message(weak_model) → git commit  │
│  cmd_undo() → 选择性 checkout HEAD~1                     │
│  aider_commit_hashes: set[str] → undo 安全检查           │
└────────────────────────────────────────────────────────────┘

┌────────── Linter ────────────────────────────────────────┐
│  basic_lint() → tree-sitter ERROR nodes                   │
│  lint_python_compile() → compile()                        │
│  flake8_lint() → fatal errors only                        │
│  → LintResult(text, lines) → tree_context() → reflected  │
└────────────────────────────────────────────────────────────┘
```

---

## 9. 对 Clade Worker 可借鉴的具体模式

### 9.1 Reflection Loop（反射循环）

Aider 的 `run_one()` 核心模式：

```python
# aider/coders/base_coder.py:run_one()
while message:
    self.reflected_message = None
    list(self.send_message(message))
    
    if not self.reflected_message:
        break
    if self.num_reflections >= self.max_reflections:
        break
    
    self.num_reflections += 1
    message = self.reflected_message  # 用错误信息作为下一轮输入
```

**错误触发反射的位置**：
- SEARCH/REPLACE 解析失败 → `reflected_message = parse_error`
- lint 错误 → `reflected_message = lint_errors + tree_context`
- test 失败 → `reflected_message = test_output`

**Clade 借鉴方案**：在 worker 执行 task 后，如果有 lint/type-check 错误，直接把错误输出注入下一轮 message，最多 3 次重试。比"失败就停止"更高效，比"无限重试"更安全。

```python
# Clade worker 伪代码
async def run_with_reflection(worker, task, max_reflections=3):
    message = task.description
    for i in range(max_reflections + 1):
        result = await worker.run(message)
        errors = await lint_and_test(result.edited_files)
        if not errors:
            break
        message = f"Fix these errors:\n{errors}"
    return result
```

### 9.2 ChatChunks 消息分层结构

Aider 的消息不是简单地 append，而是按层次组织：

```python
# aider/coders/chat_chunks.py
ChatChunks:
    system           # 不变，可 cache
    examples         # 不变，可 cache  
    readonly_files   # 参考文件，可 cache
    repo             # repo map（动态，按对话动态变化）
    done             # 历史对话（已压缩的部分）
    chat_files       # 当前编辑文件内容
    cur              # 本轮对话
    reminder         # 格式提醒（每次都发）
```

**Clade 借鉴方案**：Orchestrator 给 worker 的 context 也应分层：
- L1 (stable): 项目说明、全局规则 → 候选 cache
- L2 (semi-stable): 相关文件内容 → 每次更新
- L3 (dynamic): 当前 task 描述 + 历史对话 → 每次更新

### 9.3 Personalized PageRank for Context Selection

Aider 用 PageRank + personalization 而不是向量相似度来选择"相关文件"：

```python
# 关键：当前消息中提到的符号 → 偏向这些文件
personalization[rel_fname] = 100 / total_files  # 提到 → 权重提升
```

**Clade 借鉴方案**：Clade 的 `/map` skill 目前是全量扫描。如果任务描述中提到了具体函数名/类名，可以用 personalized ranking 选择最相关的文件子集，而不是把所有文件都放进 context。

### 9.4 Weak Model 分工

Aider 用 weak_model 处理：
- commit message 生成（不需要理解代码，只需要 diff）
- 聊天历史压缩/摘要

**Clade 借鉴**：
- TLDR 生成 → haiku（已有）
- task 分类/路由 → haiku
- commit message → haiku（目前未实现）

### 9.5 Edit Format 的 Fallback 策略

Aider 的 `do_replace()` 对 SEARCH 块失败有多级回退，最终还能 fuzzy match。这种"宽容解析"对 LLM 输出非常关键，因为 LLM 经常在格式细节上犯错。

**Clade 借鉴**：Worker 解析 LLM 输出的任何结构化格式时，都应该有类似的多级回退：
1. 精确匹配
2. 空白/缩进容错
3. 模糊匹配（SequenceMatcher）
4. 返回错误给 LLM 重试

### 9.6 map_tokens 自适应

```python
# 无文件时扩大 repo map
if not chat_files:
    max_map_tokens = min(base * 8, context_window - 4096)
```

**Clade 借鉴**：Worker 在"空白状态"开始任务时（没有已知相关文件），应该给 LLM 更大的项目概览，帮助它自主定位相关文件。

---

## 10. 关键洞察总结

1. **Repo map 不是 RAG**：PageRank 图排名比向量相似度更能捕捉"架构重要性"（被调用多的函数/被很多文件依赖的模块）。向量相似度只看文本相关，不看代码依赖关系。

2. **SEARCH/REPLACE 是工程决策，不是技术限制**：它比 unified diff 对 LLM 更友好，比 whole file 更省 token，错误提示更明确（`find_similar_lines` 给出"你是不是想改这里"的提示）。

3. **Architect mode 的真正价值**：不是让一个 LLM 思考更多，而是让两个 LLM 使用不同的 system prompt 分工——一个说"哪里改、怎么改"，另一个专注"精确输出格式正确的代码"。避免了强模型同时承担规划和精确输出两件事。

4. **Lint 反射是 SWE-bench 成绩的关键**：26.3% 的 SOTA 没有用 RAG、没有 web search、没有 agentic tool use，主要靠 lint 反射自修正。这说明"错误反馈回路"比"更强的模型"更重要。

5. **Binary search 适配 token 预算**：Aider 不是"尽量多放文件"，而是精确控制 map 在 budget ± 15% 内。过多的 repo context 会混淆 LLM（官方警告：map_tokens > 2×推荐值 "can confuse LLMs"）。
