# Codex connection adapter

- Invoke the installed plugin workflow explicitly as `$clade:provider`; bare
  `$provider` is not the Clade plugin identity.
- Use user-scoped Codex `model_provider`/model configuration and its native
  credential mechanism. Project config is trust-gated and must not donate
  credentials.
- Prefer the Responses protocol when supported; treat Chat Completions or a
  compatible gateway as an explicit protocol choice.
- Preserve unknown custom provider/model IDs. Validate capabilities through
  declared metadata or probes, never prefixes.
- A discovery-managed connection references the trusted user profile as
  `store: codex-config` plus its `model_providers` profile name. Model-list
  probes may use that profile's endpoint and credential environment variable,
  but neither value may enter repository settings, status, or cache output.
- Start a new session if the installed Codex version does not reload provider
  configuration dynamically.
