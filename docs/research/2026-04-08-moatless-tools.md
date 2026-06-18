---
title: Moatless Tools — Lightweight Code Navigation for LLM Agents
date: 2026-04-08
review_date: 2026-04-08
reconciled: 2026-06-18
status: integrated
integrated_items:
  - item: AST-based code signature extraction (classes, functions, methods)
    clade_location: orchestrator/worker_tldr.py (_parse_python_ast, _parse_js_ts_regex)
  - item: Pre-hydration of linked resources before agent start
    clade_location: orchestrator/worker.py (_pre_hydrate, lines 529-622)
  - item: Task readiness scoring via small model
    clade_location: orchestrator/worker_tldr.py (_score_task)
  - "Two-phase search-then-identify (secondary haiku distills large TLDR) — DONE: orchestrator/worker_tldr.py:428 (_localize_tldr_for_task), wired orchestrator/worker_taskfile.py:230"
  - "Span-level FileContext + per-span token budgeting + eviction — DONE: orchestrator/worker_tldr.py:375 (_span_evict_tldr) + config.py:131 (context_span_budget), wired orchestrator/worker_taskfile.py:258-260"
  - "max_tokens_per_worker budget — DONE: config.py:107 (worker_token_budget), enforced orchestrator/worker.py:547-553 (gate) and 607-616 (kill on exceed, reason token_budget_exceeded)"
  - "StringReplace edit-discipline — DONE: worker_utils.py:50 `EDIT_DISCIPLINE_BLOCK` (old_string uniqueness + line-number-prefix stripping + minimal edits), wired worker_taskfile.py:400"
  - "Resolve-rate eval (audit re-review) — DONE (a1272c2): `evals/run_resolve_eval.py` SWE-bench-Lite pipeline + dry-run self-test. The earlier 'run_oracle_eval already covers it' SKIP was wrong — that measures judge accuracy, not end-to-end resolution. Real parity still needs a live run."
  - "Localizer window (audit re-review) — DONE (d389ed0): the localizer's `tldr[:3000]` truncation (real exposure, not the FAISS absence) widened to 8000."
reference_items:
  - "Typed search actions (FindClass/FindFunction/FindCodeSnippet) — SKIP: already-equivalent — clade_search_class/method/code are real MCP tools (mcp_server.py:338,357,381); only SemanticSearch (embedding) absent"
  - "Embedding semantic index (FAISS + tree-sitter + Voyage) — SKIP: different-not-deficient — paid API + doubled deps + stale-on-commit, negligible gain at <500-file scale; 3/4 search actions already exist as tools"
  - "SWE-bench evaluation harness — SKIP: different-not-deficient — Clade-shaped eval already exists (orchestrator/evals/run_oracle_eval.py)"
needs_work_items: []
---

# Moatless Tools — Span-Based Code Navigation and Tool-First Agent Design

## Core Approach

Moatless Tools (github.com/aorwall/moatless-tools) by Albert Örwall is a lightweight
Python framework for running LLM agents on software engineering tasks. Central thesis:
**agent quality is bottlenecked by context quality, not reasoning quality**. Instead of
giving an agent a raw shell, Moatless provides structured retrieval tools that fetch
specific code spans and inject them into a bounded "file context" window.

SWE-bench Lite results:

| Mode              | Model                   | Solve rate | Cost/issue |
|-------------------|-------------------------|------------|------------|
| Linear agent      | Claude 3.5 Sonnet v2    | 39 %       | $0.14      |
| Linear agent      | Deepseek V3             | 30.7 %     | $0.01      |
| MCTS (tree-search)| Claude 3.5 Sonnet v2    | 70.8 %     | $0.63      |

The 39% linear agent is the fair comparison for Clade's single-worker model.
The 70.8% requires the full `moatless-tree-search` MCTS stack.

**vs. SWE-agent**: SWE-agent gives the agent a full bash shell + scroll editor. Moatless
replaces both with typed retrieval tools + token-budgeted file context. Fewer hallucinated
line numbers, less context noise.

**vs. AutoCodeRover**: Similar AST philosophy but Moatless achieves 39% at $0.14/issue
vs. AutoCodeRover's ~$0.43–$0.70/issue. Cost advantage from avoiding full subprocess
restarts for retries.

## Key Abstractions

### Code Index (`moatless/index/code_index.py`)
Two-layer structure:
- **CodeBlockIndex** — inverted index over span IDs, class names, function names, glob patterns. O(1) lookup by identifier.
- **FAISS vector store** — Voyage AI embeddings. Semantic similarity search. Indexed offline via `EpicSplitter` (tree-sitter-based, 750-token chunks at function/class boundaries).

### FileContext (`moatless/file_context.py`)
Live view of code the agent has "opened":
- `ContextFile` per open file with list of `ContextSpan` (span_id, line range, token count, pinned flag)
- `patch` field carries current git-format diff so agent always sees edited content
- `context_size()` counts tokens across all open spans; actions check before adding more
- Agent can call `CleanupContext` to evict files it no longer needs

### Four Search Actions
All run the same pipeline: search → if result set too large, fire `_identify_code` (secondary LLM call) → merge surviving spans into FileContext.

- **SemanticSearch** — natural language against FAISS vector store
- **FindClass** — exact lookup by class name; strips fully-qualified prefixes; retries on failure
- **FindFunction** — lookup by function/method name, optionally scoped to class
- **FindCodeSnippet** — grep-style exact text match, capped at 10 hits ± context

### Edit Actions
- **StringReplace** — requires `old_str` unique in file; strips copy-pasted line numbers; fails loudly if zero or multiple matches
- **CreateFile / AppendString / ViewCode** — file creation, append, and span-explicit viewing

### Agent Loop
`ActionAgent.run(node)` is single-step: generate actions, execute in sequence, stop on terminal. `MessageHistoryGenerator` assembles prompt from most-recent-to-oldest history, always preserving initial user message, discarding what doesn't fit under `max_tokens`.

## What Clade Already Has

| Capability | Moatless | Clade |
|---|---|---|
| AST extraction | tree-sitter, all langs, span-level | `ast.parse` Python + JS regex, `worker_tldr.py` |
| Signature format | addressable SpanIDs in FileContext | flat text TLDR, 3000-char cap, injected once |
| Semantic search | FAISS + Voyage AI, offline index | none |
| Exact symbol lookup | CodeBlockIndex O(1) | none (agent uses Bash grep) |
| Pre-task context | FileContext per task, agent adds spans | `_pre_hydrate` fetches linked GitHub issues/PRs |
| Token budget | per-span token counts + history cap | none; Claude Code handles internally |
| Edit primitive | StringReplace with validation | Claude Code native Edit tool |
| Task readiness | ValueFunction (MCTS) | `_score_task` via haiku 0-100 score |
| Multi-branch | MCTS SearchTree | parallel workers in git worktrees |

`_pre_hydrate` (worker.py) and Moatless's pre-population of FileContext are the same
conceptual idea: deterministically fetch known resources before the agent starts.
`_generate_code_tldr` (worker_tldr.py) and CodeBlockIndex solve the same "give the
agent a map" problem at different granularities.

## Gaps — What Clade Could Adopt

### Gap 1: Two-phase search-then-identify (small effort)
Most immediately adoptable. When TLDR is large/ambiguous, add a haiku call before injecting: "given this code map, which are the top-5 most relevant files for this task description?" Maps to Moatless's `_identify_code` secondary call. No indexing infrastructure needed.

Concrete: in `_build_task_file`, after generating TLDR, if `len(tldr) > 4000` and task description is specific enough, run a haiku call: `f"Given this codebase map:\n{tldr}\n\nTask: {self.description}\n\nList the 5 most relevant files, one per line."` Use that filtered list instead of the full TLDR.

### Gap 2: StringReplace discipline in worker system prompt (small effort)
Add to worker task file boilerplate: "When using Edit tool: ensure `old_str` is unique in the file (include 3+ lines of surrounding context). Never copy-paste line numbers into old_str — strip them first." Prompt-level, no code change.

### Gap 3: Span-level FileContext with token budgeting (medium effort)
The central Moatless advantage. Without it, the agent gets static context that doesn't adapt as it discovers new code. A minimal Clade implementation:
- Build a `file_context: dict[str, str]` at `_build_task_file` time (file path → relevant excerpt)
- Track total char count; cap at 32KB
- Expose a structured section in the task file: `# Active File Context\n{file: excerpt}`
- Instruction: "Add to active context with ViewCode: `path:line-range`; remove with RemoveContext"
This is achievable without an embedding index.

### Gap 4: Typed search actions in worker system prompt (medium effort)
Replace "use Bash grep" with named search tools in the system prompt:
```
FindClass <ClassName>       — find a class definition
FindFunction <fn> in <cls>  — find a method
FindSnippet <exact_string>  — grep for exact text
```
These are prompt conventions backed by Bash, not real tools. They improve search discipline and make worker prompts easier to analyze.

### Gap 5: Token-limited message history (medium effort)
Add `max_tokens_per_worker` to `config.py:_SETTINGS_DEFAULTS` (default: 0 = unlimited). In `_build_task_file`, if set, warn in the task file: "You have a token budget of {N}. Use search tools efficiently; evict context you no longer need." Track approximate usage via distillation threshold.

### Gap 6: Embedding-based semantic code index (large effort)
Full CodeIndex stack: tree-sitter parse → EpicSplitter chunks → FAISS + Voyage AI. High value for large codebases (>50k LOC). Requires offline ingestion per project + ProjectSession integration. Overkill for Clade's current project sizes.

## References

- GitHub: https://github.com/aorwall/moatless-tools
- moatless-tree-search (MCTS): https://github.com/aorwall/moatless-tree-search
- SWE-Search paper: https://arxiv.org/html/2410.20285v1
- PyPI: https://pypi.org/project/moatless/
