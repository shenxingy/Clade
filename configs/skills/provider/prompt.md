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

## Select or change

1. Parse the requested runtime, connection, model, effort, and task profile.
2. Read trusted repository policy and the current surface adapter.
3. Validate that the connection belongs to the selected runtime.
4. Resolve required/preferred/optional/forbidden capabilities.
5. Preview requested vs. resolved values and explicit degradations.
6. Change only the requested user-scoped selection. Repository files may name
   a connection/profile but must not supply credentials or silently mutate
   user-level provider configuration.
7. Re-read the effective configuration and report whether a restart/new
   session is required.

Unknown required capabilities fail before spending tokens or changing Git.
Unknown preferred capabilities may continue only with a visible degradation.

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
      "capabilities": {}
    }
  }
}
```

This object is metadata only. Keep endpoint URLs, API keys, tokens, shell
exports, and machine-specific credential paths in the native user store.

## Completion

- `DONE`: selection is resolved and verified.
- `DONE_WITH_CONCERNS`: selection works with named degradation/restart need.
- `BLOCKED`: required capability or trusted connection is unavailable.
- `NEEDS_CONTEXT`: the user must choose among materially different accounts,
  costs, or authority boundaries.
