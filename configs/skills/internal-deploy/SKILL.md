---
name: internal-deploy
description: Deploy to the company intranet and prove the served state — publish a single HTML report to the Artifact Hub (slug directory + manifest under the hub root), or rebuild and reload an app behind its process manager and reverse proxy, then smoke-verify the internal URL and report exactly what changed. NOT public/cloud deployment or CI pipeline configuration.
when_to_use: "内网部署, 部署artifact, 发布到内网, artifact hub发布, internal deploy, intranet deploy, 发布报告到hub, 部署后验证, deploy and verify, smoke verify"
user_invocable: true
---

# Internal Deploy

Ship to the company intranet and verify the served result, in two modes.
The executable instructions live in `prompt.md`; this body is the
Codex-facing summary.

Key contracts:

- The concrete machine map (hub root path, process-manager app name,
  proxy config, internal URLs, publish timers, credential locations) is
  never hard-coded here — it resolves from the target repo's CLAUDE.md /
  infra docs, or from the operator's private global-instructions tail.
  If no map resolves, stop and say which file should carry it.
- Mode A (artifact publish): head normalization first (doctype, charset,
  viewport), slug directory + manifest with owner/source/tags/version,
  version bump or dated slug on republish, then verify over the internal
  HTTPS URL — never the file on disk — before reporting the URL.
- Mode B (app deploy): clean-tree preflight, build, zero-downtime reload,
  smoke the health endpoint plus key pages through the proxy URL, check
  process error logs, and state the rollback path before declaring done.
- Report: URL + what changed (commits) + smoke evidence + parked items.
  Deploying is outward state: confirm ambiguous version intent first.
