---
name: obs-review-loop
description: Real-user observability review — pull recent Sentry errors, PostHog behavior data, and application logs, exclude internal traffic, triage what real users actually hit, fix obvious bugs, and assess whether the "how do we know this succeeded" monitoring is complete. NOT marketing analytics or a one-off error dump.
when_to_use: "看看sentry, posthog数据, 用户真实数据, sentry报错, 用户行为分析, 数据库log, real user data, observability review, error triage, 报错修复, 用户反映和统计对比"
user_invocable: true
---

# Observability Review Loop

Turn real-user signals (Sentry, PostHog, app/DB logs) into fixes and into a
completeness verdict on the success-mechanism. The executable instructions
live in `prompt.md`; this body is the Codex-facing summary.

Key contracts:

- Read-only against observability APIs. Credentials are resolved from the
  target project's own env/config — never hard-coded, never printed.
- Internal traffic (VPN/tailnet IPs, staff accounts, health-check bots,
  the owner's own devices) is excluded, and the exclusion rule is stated
  in the report.
- Every triaged issue links evidence (issue URL/count, affected flow,
  likely code location) and lands in one of: 真bug / 体验摩擦 / 数据噪声.
- Obvious bugs with clear repro are fixed in a branch, gated, and
  committed. Muting/ignoring an error without a code fix or a documented
  rationale is forbidden.
- For each fix, "how will we know it worked?" must have an answer; missing
  metric/alert/dashboard coverage is reported as a 机制缺口, not silently
  accepted.
- Final report is in Chinese and categorized: 已修 (commits + evidence) /
  发现未修 (why) / 机制缺口 / 数据健康度.
