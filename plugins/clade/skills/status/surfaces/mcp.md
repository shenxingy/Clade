# MCP status adapter

- The MCP client owns conversation activity and native quota UI. Report those
  fields only when the client supplies them.
- Clade MCP may expose repository, orchestrator, and skill data; absence of a
  tool means unsupported/unavailable, not zero.
- Keep connection identities secret-free.
