---
name: trim-tests
description: "Test-suite diet — consolidate near-identical tests into table-driven cases, delete trivial/mock-only/brittle tests, and report every piece of coverage intentionally given up. Counterweight to AI test bloat that erodes loop clock speed."
when_to_use: "trim tests, test suite too slow, tests take too long, consolidate tests, test bloat, prune tests, 测试太慢, 精简测试 — NOT for writing new tests, NOT for fixing failing tests (use /investigate)"
argument-hint: '[optional: test directory, file, or "all" for suite-wide]'
user_invocable: true
---
