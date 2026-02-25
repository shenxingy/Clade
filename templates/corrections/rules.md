# Correction Rules

Learned preferences and patterns from past corrections.
Claude auto-maintains this file — newest rules at the bottom, max 50 lines.

Format: `- [YYYY-MM-DD] <domain> (<root-cause>): <do this> instead of <not this>`

Root-cause categories: settings-disconnect | edge-case | async-race | security | deploy-gap

---

- [2026-02-25] shell (edge-case): Use `stat -c%s 2>/dev/null || stat -f%z 2>/dev/null` for cross-platform file size — not Linux-only `stat -c`
- [2026-02-25] shell (edge-case): Guard `git diff HEAD~N` with `2>/dev/null` fallback for repos with fewer than N commits
- [2026-02-25] async (async-race): `asyncio.wait_for()` cancels the coroutine but NOT the subprocess — always add `proc.kill(); await proc.communicate()` in the TimeoutError handler
- [2026-02-25] settings (settings-disconnect): After defining a new config/flag, grep the codebase to verify it's actually READ somewhere — definition without consumption = dead code
- [2026-02-25] deploy (deploy-gap): After modifying source scripts, verify deployed copies match — `diff source deployed` before trusting the runtime
