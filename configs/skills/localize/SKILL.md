---
name: localize
description: Full-site/app internationalization — audit translatable surfaces, extract hardcoded strings into a message namespace, wire i18n (next-intl etc.), translate to N locales with brand/ICU/RTL fidelity, run an independent ISO-17100 revision pass (a second adversarial native reviewer per locale, back-translation + MQM scoring, catching the false-friend / register-flip / terminology-drift defects that build+leak checks miss), then verify completeness + UI across every viewport and RTL. Held to MQM/ISO-17100 quality and a "beat professional human translation" bar via automated key-parity, leak, build, and Playwright viewport/RTL audits. NOT for translating blog article content (use blog-localize) — this is for the codebase/marketing-site UI.
when_to_use: "translate the website, internationalize the app, add languages, i18n audit, localize the UI, review/QA existing translations for meaning, why is my page English under /es, RTL broken, language switcher, nav overflows in German, 网站翻译, 全站本地化, 多语言, 翻译审核, 语义审核, 校对翻译 — use /localize"
user_invocable: true
---

See prompt.md for the full playbook.
