# TinyFish MCP: task brief, execution, acceptance

Use this contract whenever routing selects TinyFish, or the user explicitly
asks TinyFish to search, fetch, extract or inspect websites. Phrases such as
“批量查这些网站”, “帮我比较并附原文”, “让 TinyFish 干活” and “抓网页初筛”
should activate this workflow without requiring the user to know a tool name.
The ordinary small-lookup/native routing still applies unless TinyFish is chosen.

## Discover the real tools

The operational server is `https://agent.tinyfish.ai/mcp`.
`https://docs.tinyfish.ai/mcp` searches TinyFish's documentation only.
Use the names and schemas actually exposed by the runtime; MCP namespace prefixes
vary. A configured server is not a connected server. Check tool discovery and a
successful call before claiming it works. If discovery/authentication fails,
report that boundary and use the configured API fallback when permitted.

Default retrieval uses `search` and `fetch_content`. The focused install exposes
these two tools in Codex. Agent, Browser and Monitor operations are separately
metered and are not automatic fallbacks for search/fetch failures. Do not enable
or invoke them unless the user's task explicitly authorizes that mode and cost.

## Before the call: a small task brief

Derive these from the user's request, keeping private conversation context out
of the provider request:

- **Question and decision:** what will the user decide using the answer?
- **Scope:** entities, URLs/domains, geography, language and relevant date range.
- **Evidence required:** exact fields or claims to establish and primary sources
  to prefer; include exclusions the user supplied.
- **Budget and stopping point:** planned queries/pages/items; stop when required
  claims are supported, or record the remaining gaps when the budget is reached.

For an unspecified comparison, start with 3 targeted queries and up to 5 relevant
pages; expand only for named evidence gaps. These are local planning defaults,
not API guarantees. Do not infer permission to contact people, submit forms,
purchase, log in or change accounts from a request to collect information.

### Search: query finds candidates, purpose explains relevance

Example for “比较 TinyFish Search/Fetch 的免费额度和限制，用官网证据”:

```json
{
  "query": "TinyFish Search Fetch pricing rate limits",
  "purpose": "Verify current Search and Fetch rates and quotas for a retrieval workflow. Prefer official pricing and API documentation; separate them from Agent and Browser charges.",
  "include_domains": "tinyfish.ai,docs.tinyfish.ai"
}
```

Keep the query concrete. Put the reason for searching and selection criteria in
`purpose`, not a wall of instructions in the query. Apply domain/date/language
filters only when they fit the task. Paper searches use publication years rather
than recency/date filters. Do not send `goal`, `output_schema`, or Highlights
parameters to Search. Inspect live schemas before using optional parameters.

Search titles/snippets select candidates; they do not verify a claim. Deduplicate
URLs, prefer primary evidence, and choose pages because they address a required
field. One empty query gets one useful reformulation; repeated empty searches
become an explicit evidence gap, not a claim that the information does not exist.

### Fetch: ask for the needed source material

```json
{
  "urls": ["https://www.tinyfish.ai/pricing"],
  "purpose": "Read the Search and Fetch rates, per-minute/hour/day quotas, and applicable conditions. Preserve the distinctions between the two products.",
  "format": "markdown",
  "links": false,
  "image_links": false,
  "page_metadata": false,
  "ttl": 0,
  "per_url_timeout_ms": 30000
}
```

The live MCP schema requires all five fields `urls`, `format`, `links`,
`image_links`, `page_metadata`, even though some have defaults. Pass them.
Batch at most 10 URLs and use fewer when large pages would overwhelm context.
Known CSS selectors can narrow extraction. Never guess selectors and treat an
empty extraction as proof of absence. `purpose` is an intent signal, not a
guarantee that the service returns a requested JSON report or limited text.

MCP Fetch currently exposes no Highlights parameter. Do not copy a REST-only
field into MCP. For relevance excerpts use local keyword selection on the
returned source; keep full source privately when the runtime permits saving it.
Do not claim this is semantic ranking. `ttl=0` prefers a fresh request but may
still use cache allowed by the origin or provider; preserve returned freshness
metadata rather than claiming a live origin check.

## While running

Search and Fetch are ordinary tool calls: wait for their result. A progress
notification is not final evidence. If a tool call times out, report the timeout;
retry a read-only request once or use the API fallback. Do not call `get_run`
unless an Agent call actually returned an owned run ID.

Inspect MCP `isError` and JSON-RPC errors before reading data. For Fetch, inspect
both `results` and per-URL `errors`; retain successes and retry only missing or
failed URLs, at most once when the failure is transient. A `selector_not_matched`
error calls for checking selectors, not repeating the same selector unchanged.
Authentication failures need a credential fix/fallback; 429 honors Retry-After
and the task deadline. Do not rotate keys or switch into paid Agent mode.

For long work, tell the user which stage is running, sources completed and the
remaining gap. Use actual observations; never invent percentages. Do not dump
raw progress notifications into the final answer.

## Optional Agent mode: only when already authorized

Use this when the authorized task truly needs clicks/navigation, not ordinary
page reading. Prefer `run_web_automation_async` for long operations. Its live
schema requires `url`, `goal`, and a newly generated UUID `session_id` for every
new run. Read the schema before passing `output_schema`; unsupported JSON Schema
features can be rejected. Do not reuse a sample UUID or resend a start call
because polling is slow.

Adapt this **goal template** to one site and a bounded task:

```text
Read [starting URL] to answer [specific question] for [entities/date/locale].
Find [required fields]. Prefer [named authoritative page/section].
If needed, follow same-site links to [allowed page types], at most [N] pages.
Stop when each field is supported, or when that limit is reached.
Read only: do not submit forms, create accounts, buy, message or alter data.
If blocked by login, CAPTCHA, missing data or an inaccessible page, stop that
branch and report the reason. Do not guess missing values or use prior knowledge.
Return JSON: {"status":"complete|partial|blocked","records":[{"source_url":
"https://...","fields":{"requested_field":null},"evidence":[{"field":
"requested_field","quote":"short verbatim source excerpt"}]}],
"missing_fields":[],"limitations":[]}.
Use null for unknown fields; preserve original units, currency and dates.
```

Store the returned run ID and original goal. Poll `get_run` with `{"id":"..."}`
every 30–60 seconds; `batch_status` supports at most 8 run IDs. Keep user updates
within a minute. `PENDING`/`RUNNING` mean continue observing the same run;
`FAILED`/`CANCELLED` are terminal. A disconnected stream does not prove the run
stopped: recover by ID instead of starting a duplicate. At the task deadline,
cancel only a run owned by this task if cancellation is supported, and confirm
its final state. Never cancel someone else's run. Do not silently leave paid
work running after reporting it stopped.

`COMPLETED` only describes execution. Inspect the nested result for failure,
empty data, missing fields and evidence. A goal-level failure is still a failure.

## After the call: return usable evidence

Unwrap the MCP `structuredContent`, or the JSON object inside `content[].text`.
If content is truncated/ambiguous, narrow the call or retrieve the missing
source; do not manufacture the lost tail. Keep source URLs and `final_url` when
redirected. A receipt timestamp is not the source's publication/update time.

For a saved response, the deterministic checker is:

```bash
python3 <skill-dir>/scripts/mcp_result.py fetch --input /private/path/result.json --requested-url https://example.com/pricing --query "pricing quotas"
python3 <skill-dir>/scripts/mcp_result.py run --input /private/path/run.json --required-field records
```

It bounds excerpts, identifies missing URLs/fields, distinguishes waiting,
transport failure and goal failure, and saves a private raw cache. `needs_review`
means extraction succeeded but evidence still needs the current agent's review;
even exit 0 is not an endorsement of the source. Do not write a second copy of
huge output through the model just to run it; use the runtime's saved result
artifact, or apply these checks directly when no artifact is available.

Before answering, map each requested claim/field to a source passage. Mark
missing, stale, conflicting, or only-snippet evidence explicitly. Open omitted
context when truncation affects meaning. Further calls should close a named
gap; stop when criteria are met or the budget is exhausted. The final answer
contains the user's requested result with citations, the material gaps, and any
fetch/coverage limitation—not a raw MCP transcript or unverified Agent summary.

Contracts verified against the live MCP schema and official documentation:
[MCP](https://docs.tinyfish.ai/mcp-integration/index),
[goals](https://docs.tinyfish.ai/prompting-guide),
[run lifecycle](https://docs.tinyfish.ai/key-concepts/runs).
