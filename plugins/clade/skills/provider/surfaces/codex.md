# Codex connection adapter

- Use user-scoped Codex `model_provider`/model configuration and its native
  credential mechanism. Project config is trust-gated and must not donate
  credentials.
- Prefer the Responses protocol when supported; treat Chat Completions or a
  compatible gateway as an explicit protocol choice.
- Preserve unknown custom provider/model IDs. Validate capabilities through
  declared metadata or probes, never prefixes.
- Start a new session if the installed Codex version does not reload provider
  configuration dynamically.
