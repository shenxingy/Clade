---
name: reverse-engineer-anything
description: "Reverse engineer shipped software without its source — native binaries, Electron/JavaScript apps and ASAR archives, Android APKs, .NET assemblies, firmware images, websites, recorded crashes — through the REA CLI/MCP server. Evidence-cited feature tracing, version comparison, decompilation, and reconstruction guidance"
when_to_use: "reverse engineer, decompile, disassemble, binary analysis, how does this app feature work, inspect Electron app, ASAR, APK analysis, IPA, firmware, pseudocode, Ghidra, Hopper, IDA, EVM bytecode, HAR capture, 逆向, 逆向工程, 反编译, 反汇编, 二进制分析, 分析软件原理, 逆向分析 — NOT for ordinary source-repository architecture analysis (read the code directly, or /map), NOT for security auditing your own project (use /cso)"
user_invocable: true
license: "MIT (absorbed from morluto/rea)"
metadata:
  upstream: "morluto/rea"
  absorbed_at: "e8491e023a255f790ae9850225084d7495e9ade0"
---

# Reverse Engineer Anything (REA)

> Absorbed from [morluto/rea](https://github.com/morluto/rea) (MIT) @ `e8491e0`
> via `/equip` — audit: `.claude/equipment/audits/rea-2026-10-11.md`.
> This skill is the investigation workflow layer; the REA engine itself is an
> external npm package (`rea-agents`), deliberately not vendored.

Use when a claim depends on a **shipped binary, package, or observed runtime**
rather than available source: explain how a closed-source app's feature works,
decompile a function to pseudocode, trace an Electron IPC bridge, inventory an
APK or firmware image, compare two versions of a shipped artifact. Every
conclusion comes back with cited Evidence IDs and explicit limitations.

For ordinary analysis of a complete source repository, use normal repository
tools — do not run REA.

## Requires

- Node.js ≥22.19; use an installed `rea` CLI or `npx -y rea-agents@latest`
- Agent integration: `npx rea-agents setup` (registers the MCP server with
  backups; restart the agent afterward)
- Static JavaScript/Electron and .NET inspection need no analysis engine;
  deep native analysis uses a bring-your-own Hopper, Ghidra, or IDA install

## Example asks

```
Understand how search works in the Notes app, show me the evidence, and build
a similar feature for my project.
```

```
rea analyze-javascript-application /absolute/path/to/app --json
```

## Layout of this skill

- `prompt.md` — the full investigation workflow (target routing, evidence
  paging, staged investigations), byte-identical to upstream `SKILL.md` so
  `/equip sync rea` stays a clean 3-way merge
- `references/` — per-target guides: native/artifacts, JavaScript/Electron,
  Android, runtime observation, evidence workflows, connection/recovery
