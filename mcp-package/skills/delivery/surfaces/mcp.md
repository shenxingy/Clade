# MCP/headless surface adapter

- The MCP client and its persistent UI are unknown unless explicitly probed.
  Return structured delivery JSON plus concise text; do not assume a footer,
  interactive approval dialog, or local worktree manager.
- Resolve the repository root passed by the client; never assume the MCP server
  process working directory is the task checkout.
- Invoke the packaged controller resource from this skill. Do not spawn an
  agent CLI merely to run Git policy.
- If the client cannot expose an authorization decision, keep external writes
  pending and return the branch/patch plus required next action.
- No-forge repositories are supported through local commits and patch/bundle
  preservation; do not invoke `gh`.
