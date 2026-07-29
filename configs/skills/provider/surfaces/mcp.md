# MCP connection adapter

- The MCP client/runtime owns endpoint and authentication configuration.
- Select only a secret-free connection identity exposed to Clade.
- If the client does not expose model/capability discovery, keep those fields
  unknown and require explicit confirmation for capability-sensitive work.
- If it does expose discovery, preserve its TTL/observation provenance and
  require an explicit pinned model before any stale fallback.
