---
name: seo-dataforseo
description: Live SEO data via DataForSEO MCP server. SERP analysis (Google, Bing, Yahoo, YouTube, Google Images), keyword research (volume, difficulty, intent, trends), backlink profiles, on-page analysis (Lighthouse, content parsing), competitor analysis, content analysis, business listings, AI visibility (ChatGPT scraper, LLM mention tracking), and domain analytics. Requires DataForSEO extension installed. Use when user says "dataforseo", "live SERP", "keyword volume", "backlink data", "competitor data", "AI visibility check", "LLM mentions", "image SERP", "google images", "image rankings", or "real search data".
argument-hint: '[command] [query]'
user_invocable: false
---

> ## Version gate — read before invoking anything below
>
> **Every tool name in this skill is a DataForSEO MCP _v2_ name, and there are
> 84 of them.** v3.0.0 (2026-08-11) replaced roughly 79 per-endpoint tools with
> four generic ones — `api_request` plus three documentation tools — and marked
> v2 deprecated. On a v3 install every name here resolves to nothing, and this
> skill is `user_invocable: false`, so the caller sees a sub-skill that
> silently found no tools rather than an error naming the cause.
>
> Before using this skill, do one of:
>
> 1. **Check what is actually loaded.** If the tool list has `api_request` and
>    not `serp_organic_live_advanced`, you are on v3 and the names below do not
>    apply. Translate each to `api_request` with its REST path.
> 2. **Pin v2** — `dataforseo-mcp-server@2.9.13` — accepting a deprecated
>    server.
>
> **And note what this skill is.** DataForSEO is a paid API, billed per call.
> Under "paid APIs are opt-in, never a dependency", nothing may require it: the
> keyless path for the same questions is `/seo` and `/seo geo`, which are
> written to produce a complete result with no account and no spend. Reach for
> this skill only when the user already pays for DataForSEO and wants the
> depth. Never as the reason a dimension goes unreported.

