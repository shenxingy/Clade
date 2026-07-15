---
name: codex-orchestrate
description: Orchestrate a fleet of parallel `codex exec` workers with you (Claude Code) as the supervisor — spawn one per isolated git worktree, dispatch headless, verify each INDEPENDENTLY, PR/merge. The manual "codex-ultracode" pattern for fanning out real implementation, research, or review work onto Codex. Bakes in the hard gotchas (stdin blocking, background tracking, don't-trust-self-reports, writer isolation). Triggers on — orchestrate codex, codex workers, codex fleet, spawn codex, delegate to codex in parallel, manual ultracode, 开 codex 小弟, 派 codex worker — NOT for a single cross-vendor opinion (use the `second-opinion-codex` agent), NOT for web-UI worker decomposition (use `/orchestrate`).
---

# Codex Orchestrate — you supervise a fleet of `codex exec` workers

Use when the user wants Codex to actually DO work at scale (implement N gaps, research N sources, review N dimensions) and you drive it — the manual equivalent of Codex's native `ultra`/multi_agent, but with no slot cap and with YOUR verification gate on every result.

Read `prompt.md` for the full loop, the exact dispatch command, and the verification checklist. The four rules that make it work (each learned from a real failure):

1. **`< /dev/null`** on every `codex exec` — it blocks on stdin EOF otherwise, even with the prompt as an arg, and hangs until timeout.
2. **One isolated git worktree per worker** off the latest main — parallel writers to shared build/test state race; core-engine changes merge **sequentially** so each builds on the last.
3. **Verify independently — never trust the worker's self-report.** Re-run the tests yourself (a worker reported "996 passed"; the real number was 995 + 1 real failure). For core-engine changes run the FULL suite, not just the new test.
4. **Dispatch via a tracked background call** (`run_in_background`), not `&` inside another command, or you lose the completion signal.
