<command-metadata>
name: provider
contract: clade.execution/v1
completion-status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
</command-metadata>

Treat these as independent dimensions:

1. surface;
2. agent runtime (`claude`, `codex`, or another installed adapter);
3. secret-free connection identity;
4. inference provider;
5. wire protocol;
6. opaque provider-scoped model ID;
7. capability profile and task policy.

Never infer provider/capabilities from a model prefix. Never silently fall
back to Claude, a default account, or another billing identity.

## No argument / inspect

Show the resolved execution identity and provenance. List available connection
identities only from trusted user/runtime configuration. Do not read or print
credentials, raw authorization headers, or secret-bearing files.

When the orchestrator provider registry is available, report its catalog
state (`fresh`, `stale`, `unavailable`, or `declared`), observation time,
adapter/profile provenance, health, and capability provenance. A live catalog
is a time-bounded observation, not a permanent model allowlist.

## Select or change

1. Parse the requested runtime, connection, model, effort, and task profile.
2. Read trusted repository policy and the current surface adapter.
3. Validate that the connection belongs to the selected runtime.
4. Resolve required/preferred/optional/forbidden capabilities.
5. Refresh an expired discovery-managed catalog before selection.
6. Preview requested vs. resolved values, catalog provenance, and explicit
   degradations.
7. Change only the requested user-scoped selection. Repository files may name
   a connection/profile but must not supply credentials or silently mutate
   user-level provider configuration.
8. Re-read the effective configuration and report whether a restart/new
   session is required.

Unknown required capabilities fail before spending tokens or changing Git.
Unknown preferred capabilities may continue only with a visible degradation.
If discovery fails or expires, continue only when the resolved opaque model ID
is explicitly pinned on that connection. Mark the execution as a stale catalog
degradation; never substitute another model, account, or provider.

## Clade orchestrator configuration

Use canonical fields:

```json
{
  "agent_runtime": "claude",
  "runtime_connections": {"claude": "minimax-work"},
  "connections": {
    "minimax-work": {
      "agent_runtime": "claude",
      "inference_provider": "minimax",
      "wire_protocol": "anthropic-compatible",
      "endpoint_identity": "minimax-user-config",
      "models": {"strong": "MiniMax-M2.5"},
      "pinned_models": ["MiniMax-M2.5"],
      "discovery": {
        "adapter": "minimax",
        "store": "claude-providers",
        "profile": "minimax-work",
        "ttl_seconds": 300
      },
      "capabilities": {}
    }
  }
}
```

This object is metadata only. Keep endpoint URLs, API keys, tokens, shell
exports, and machine-specific credential paths in the native user store.
`discovery.store` and `discovery.profile` are secret-free references to that
store. Supported adapters are Anthropic, OpenAI, MiniMax, Moonshot,
OpenAI-compatible custom gateways, and explicitly declared native-static
profiles.

## Completion

- `DONE`: selection is resolved and verified.
- `DONE_WITH_CONCERNS`: selection works with named degradation/restart need.
- `BLOCKED`: required capability or trusted connection is unavailable.
- `NEEDS_CONTEXT`: the user must choose among materially different accounts,
  costs, or authority boundaries.
