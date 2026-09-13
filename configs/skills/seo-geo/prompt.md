---
name: seo-geo
description: >
  Optimize content for AI Overviews (formerly SGE), ChatGPT web search,
  Perplexity, and other AI-powered search experiences. Generative Engine
  Optimization (GEO) analysis including brand mention signals, AI crawler
  accessibility, llms.txt compliance, passage-level citability scoring, and
  platform-specific optimization. Use when user says "AI Overviews", "SGE",
  "GEO", "AI search", "LLM optimization", "Perplexity", "AI citations",
  "ChatGPT search", or "AI visibility".
user-invokable: true
argument-hint: "[url]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "2.0.0"
  category: seo
---

# AI Search / GEO Optimization (May 2026)

## Primary Source: Google's AI Optimization Guide

Google's official position, published under Search Central docs:

> "Optimizing for generative AI search is **still SEO** from Google's
> perspective. AEO and GEO are rebranded labels for the same work."

Read `references/google-ai-optimization-guide.md` for the full synthesis,
myth-busting list (`llms.txt`, chunking, AI-rephrasing, mention-farming —
all rejected by Google as ineffective), and the Who/How/Why test for
content quality.

Audits should frame GEO findings as **SEO fundamentals applied to AI-search
surfaces**, not as a separate optimization discipline. When community
recommendations contradict Google's primary source, defer to Google and note
the contradiction in the report.

## Key Statistics

| Metric | Value | Source |
|--------|-------|--------|
| AI Overviews reach | 1.5 billion users/month across 200+ countries | Google |
| AI Overviews query coverage | 50%+ of all queries | Industry data |
| AI-referred sessions growth | 527% (Jan-May 2025) | SparkToro |
| ChatGPT weekly active users | 900 million | OpenAI |
| Perplexity monthly queries | 500+ million | Perplexity |

## Critical Insight: Brand Mentions > Backlinks

**Brand mentions correlate 3x more strongly with AI visibility than backlinks.**
(Ahrefs December 2025 study of 75,000 brands)

| Signal | Correlation with AI Citations |
|--------|------------------------------|
| YouTube mentions | ~0.737 (strongest) |
| Reddit mentions | High |
| Wikipedia presence | High |
| LinkedIn presence | Moderate |
| Domain Rating (backlinks) | ~0.266 (weak) |

**Only 11% of domains** are cited by both ChatGPT and Google AI Overviews for the same query, so platform-specific optimization is essential.

---

## Step 0 — Acquire the evidence (free, keyless, no account)

**This skill never needed a paid API and must not acquire one.** Everything
scored below comes off the page and its origin. Until 2026-09-12 the prompt
described what to score and never said how to obtain it, so a run had to invent
its own acquisition or score from memory of the URL.

Run these first. `<url>` is the argument; `<origin>` is its scheme + host.

```bash
# 1. The page as a normal browser sees it
python3 ~/.claude/scripts/seo/fetch_page.py <url> -o /tmp/geo-page.html

# 2. The page as a crawler that does NOT execute JavaScript sees it
python3 ~/.claude/scripts/seo/fetch_page.py <url> --googlebot -o /tmp/geo-bot.html
wc -c /tmp/geo-page.html /tmp/geo-bot.html

# 3. Crawler access
curl -sS -w '\nHTTP %{http_code}\n' <origin>/robots.txt

# 4. llms.txt — record presence, assign no citation weight (see below)
curl -sS -w '\nHTTP %{http_code}\n' <origin>/llms.txt

# 5. Structured data actually present in the served HTML
python3 - <<'EOF'
import re, json, pathlib
html = pathlib.Path('/tmp/geo-page.html').read_text(errors='replace')
for m in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S|re.I):
    try:
        d = json.loads(m)
    except ValueError:
        print('  INVALID JSON-LD block'); continue
    for node in (d if isinstance(d, list) else [d]):
        print('  @type:', node.get('@type'))
EOF
```

**Reading step 3 — a wildcard is not an absence.** Counting named AI tokens is
not the check. `User-Agent: * / Allow: /` names none of them and permits all of
them; a run that greps for `GPTBot` and reports "0 AI crawlers configured" has
inverted the answer. Resolve it in this order, which is how a crawler resolves
it: the most specific matching `User-agent` group wins, and only if no group
names the crawler does `*` apply. Report per crawler as **allowed**, **blocked**
or **ungoverned** — never as "not found". (Verified against a live site on
2026-09-12: four lines, zero named tokens, every AI crawler allowed.)

**Reading step 2.** A large size gap is the finding: the smaller document is
what an AI crawler without a JS engine receives. Quote both byte counts in the
report. If the bot fetch is a fraction of the browser fetch, no amount of
passage optimisation matters — the passages are not in what gets read.

**If a fetch fails,** say which one and score the rest. A report that silently
omits a dimension because its input was unavailable is the failure this
repository keeps finding in its own instruments: report `not measured`, never a
zero, and never a score computed from a page you did not retrieve.

## GEO Analysis Criteria (Updated)

### 1. Citability Score (25%)

**Optimal passage length: 134-167 words** for AI citation.

**Strong signals:**
- Clear, quotable sentences with specific facts/statistics
- Self-contained answer blocks (can be extracted without context)
- Direct answer in first 40-60 words of section
- Claims attributed with specific sources
- Definitions following "X is..." or "X refers to..." patterns
- Unique data points not found elsewhere

**Weak signals:**
- Vague, general statements
- Opinion without evidence
- Buried conclusions
- No specific data points

### 2. Structural Readability (20%)

**92% of AI Overview citations come from top-10 ranking pages**, but 47% come from pages ranking below position 5, demonstrating different selection logic.

**Strong signals:**
- Clean H1->H2->H3 heading hierarchy
- Question-based headings (matches query patterns)
- Short paragraphs (2-4 sentences)
- Tables for comparative data
- Ordered/unordered lists for step-by-step or multi-item content
- FAQ sections with clear Q&A format

**Weak signals:**
- Wall of text with no structure
- Inconsistent heading hierarchy
- No lists or tables
- Information buried in paragraphs

### 3. Multi-Modal Content (15%)

Content with multi-modal elements sees **156% higher selection rates**.

**Check for:**
- Text + relevant images
- Video content (embedded or linked)
- Infographics and charts
- Interactive elements (calculators, tools)
- Structured data supporting media

### 4. Authority & Brand Signals (20%)

**Strong signals:**
- Author byline with credentials
- Publication date and last-updated date
- Citations to primary sources (studies, official docs, data)
- Organization credentials and affiliations
- Expert quotes with attribution
- Entity presence in Wikipedia, Wikidata
- Mentions on Reddit, YouTube, LinkedIn

**Weak signals:**
- Anonymous authorship
- No dates
- No sources cited
- No brand presence across platforms

### 5. Technical Accessibility (20%)

**AI crawlers do NOT execute JavaScript.** Server-side rendering is critical.

**Check for:**
- Server-side rendering (SSR) vs client-only content
- AI crawler access in robots.txt
- llms.txt file presence and configuration
- RSL 1.0 licensing terms

---

## AI Crawler Detection

**The crawler table lives in one place:**
`configs/skills/blog/references/ai-crawler-guide.md`. Read it rather than the
short list this section used to carry — that copy had drifted, listing
`anthropic-ai` (deprecated) and missing `Google-Extended`, `Claude-SearchBot`,
`Claude-User`, `Perplexity-User`, `Applebot-Extended`, `Meta-ExternalAgent`,
`Amazonbot`, `DuckAssistBot` and `MistralAI-User`. Two tables for one fact is
how the wrong one gets read.

What that guide adds beyond a list:

- **Each provider runs three bots** — training, search-indexing, retrieval.
  Blocking the search-indexing bot is what removes you from that platform's
  answers; blocking only the training bot does not.
- **`Google-Extended` is the Gemini lever** and it is separate from
  `Googlebot`. Disallowing it removes you from Gemini grounding while leaving
  classic Search untouched — the single most consequential line in most
  robots.txt files, and the one most often set by accident.
- **Cloudflare blocks AI crawlers by default.** A correct robots.txt in front
  of a default Cloudflare config still yields zero AI visibility. Check the
  edge before auditing the file.
- **Grok and DeepSeek cannot be governed at all** — no published token, fetches
  indistinguishable from a browser. Report them as *ungoverned*, never as
  *allowed*: a clean robots.txt has said nothing about either.

---

## llms.txt Standard

Read `references/llmstxt-evidence.md` for the primary-source evidence (Mueller, Illyes, SE Ranking 300k-domain study, OtterlyAI server-log audit) on why `/llms.txt` is not currently a citation lever for major AI search systems. claude-seo reports presence but assigns no citation-ranking weight.

The emerging **llms.txt** standard provides AI crawlers with structured content guidance.

**Location:** `/llms.txt` (root of domain)

**Format:**
```
# Title of site
> Brief description

## Main sections
- [Page title](url): Description
- [Another page](url): Description

## Optional: Key facts
- Fact 1
- Fact 2
```

**Check for:**
- Presence of `/llms.txt`
- Structured content guidance
- Key page highlights
- Contact/authority information

---

## RSL 1.0 (Really Simple Licensing)

New standard (December 2025) for machine-readable AI licensing terms.

**Backed by:** Reddit, Yahoo, Medium, Quora, Cloudflare, Akamai, Creative Commons

**Check for:** RSL implementation and appropriate licensing terms.

---

## Platform-Specific Optimization

| Platform | Key Citation Sources | Optimization Focus |
|----------|---------------------|-------------------|
| **Google AI Overviews** | Top-10 ranking pages (92%) | Traditional SEO + passage optimization |
| **Google AI Mode / Gemini** | Google index + Gemini grounding | Same SEO base, but gated on `Google-Extended` — a site can rank in Search and be absent here |
| **ChatGPT** | Wikipedia (47.9%), Reddit (11.3%) | Entity presence, authoritative sources |
| **Perplexity** | Reddit (46.7%), Wikipedia | Community validation, discussions |
| **Bing Copilot** | Bing index, authoritative sites | Bing SEO, IndexNow |
| **Claude** | Live web fetch at answer time | Server-rendered HTML and a clean `Claude-SearchBot` allow; no separate index to rank in |
| **Grok (xAI)** | **Live X posts**, then the open web | The lever is X presence — mentions, replies, and your own account. Page-level SEO barely reaches it, and no robots.txt directive does |
| **Meta AI** | Facebook/Instagram surfaces + Bing | Owned-profile content on Meta's platforms; `Meta-ExternalAgent` covers only the bulk crawl |
| **DeepSeek** | Whatever renders publicly | Server-side rendering only. No token, no index, no access control |

**Scoring must not average these.** A brand can be strong in ChatGPT and absent
from Grok, because one reads Wikipedia and the other reads X. Report per
platform and say which surfaces were not measurable rather than folding them
into one number.

---

## Output

Generate `GEO-ANALYSIS.md` with:

1. **GEO Readiness Score: XX/100**
2. **Platform breakdown** — Google AIO, Google AI Mode/Gemini, ChatGPT, Perplexity, Bing Copilot, Claude, Grok, Meta AI, DeepSeek. Score each separately; mark *ungoverned* (Grok, DeepSeek) and *not measured* rather than scoring them 0
3. **AI Crawler Access Status** (which crawlers allowed/blocked)
4. **llms.txt Status** (present, missing, recommendations)
5. **Brand Mention Analysis** (presence on Wikipedia, Reddit, YouTube, LinkedIn)
6. **Passage-Level Citability** (optimal 134-167 word blocks identified)
7. **Server-Side Rendering Check** (JavaScript dependency analysis)
8. **Top 5 Highest-Impact Changes**
9. **Schema Recommendations** (for AI discoverability)
10. **Content Reformatting Suggestions** (specific passages to rewrite)

---

## Quick Wins

1. Add "What is [topic]?" definition in first 60 words
2. Create 134-167 word self-contained answer blocks
3. Add question-based H2/H3 headings
4. Include specific statistics with sources
5. Add publication/update dates
6. Implement Person schema for authors
7. Allow key AI crawlers in robots.txt

## Medium Effort

1. Create `/llms.txt` file
2. Add author bio with credentials + Wikipedia/LinkedIn links
3. Ensure server-side rendering for key content
4. Build entity presence on Reddit, YouTube
5. Add comparison tables with data
6. Implement FAQ sections (structured, not schema for commercial sites)

## High Impact

1. Create original research/surveys (unique citability)
2. Build Wikipedia presence for brand/key people
3. Establish YouTube channel with content mentions
4. Implement comprehensive entity linking (sameAs across platforms)
5. Develop unique tools or calculators

## Paid AI-visibility APIs — deliberately NOT a dependency

**Do not require, and do not default to, an API that costs money.** This skill
must produce a complete report with no account, no key and no spend. Everything
in Step 0 and every criterion below satisfies that.

What that costs you, stated plainly rather than papered over: **you cannot
measure actual citations.** Whether ChatGPT or Perplexity cited this domain last
week is only observable through a paid endpoint or a vendor dashboard. This
skill therefore scores *citability* — whether the page is shaped to be cited —
and must never present that as evidence that it *was* cited. Two different
claims; only the first is in scope here.

Two more honest limits:

- The tool names an earlier version of this file recommended
  (`ai_opt_llm_ment_top_domains`, `ai_optimization_llm_response`) were removed
  from the DataForSEO MCP server in v3.0.0 on 2026-08-11. Anything written
  against them resolves to nothing today.
- The citation-source percentages in the platform table are undated
  third-party studies. Treat them as directional. They are the shape of the
  answer, not this month's number.

## Error Handling

| Scenario | Action |
|----------|--------|
| URL unreachable (DNS failure, connection refused) | Report the error clearly. Do not guess site content. Suggest the user verify the URL and try again. |
| AI crawlers blocked by robots.txt | Report exactly which crawlers are blocked and which are allowed. Provide specific robots.txt directives to add for enabling AI search visibility. |
| No llms.txt found | Note the absence and provide a ready-to-use llms.txt template based on the site's content structure. |
| No structured data detected | Report the gap and provide specific schema recommendations (Article, Organization, Person) for improving AI discoverability. |

## FLOW Framework Integration

For prompt-guided AI content optimization, use `/seo flow optimize <url>` — FLOW's 21 optimize-stage prompts complement GEO's citability and structure analysis with evidence-led AI prompts.
