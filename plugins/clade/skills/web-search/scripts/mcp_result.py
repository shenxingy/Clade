#!/usr/bin/env python3
"""Check TinyFish MCP envelopes, run states, and source coverage from saved JSON."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys

from web_search import RetrievalError, public_url, safe_text, select_passages, atomic_json, state_root


def unwrap(value):
    if not isinstance(value, dict):
        raise RetrievalError("mcp_expected_object")
    if value.get("jsonrpc"):
        if "error" in value:
            raise RetrievalError("mcp_rpc_error")
        value = value.get("result")
    if not isinstance(value, dict):
        raise RetrievalError("mcp_missing_result")
    if value.get("isError"):
        raise RetrievalError("mcp_tool_error")
    if isinstance(value.get("structuredContent"), dict):
        return value["structuredContent"]
    if "content" in value:
        # Ignore progress prose; require a complete data object, not a truncated fragment.
        candidates = []
        for item in value.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            try:
                decoded = json.loads(item.get("text", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(decoded, dict):
                candidates.append(decoded)
        if len(candidates) != 1:
            raise RetrievalError("mcp_ambiguous_or_truncated_content")
        return candidates[0]
    return value


def inspect(operation, envelope, requested=(), required=(), query="", budget=12000):
    value = unwrap(envelope)
    received = dt.datetime.now(dt.timezone.utc).isoformat()
    if operation == "run":
        status = str(value.get("status", "UNKNOWN")).upper()
        run_id = value.get("run_id") or value.get("id")
        base = {"operation": operation, "provider_status": status, "run_id": run_id,
                "received_at": received, "evidence_verified": False}
        if status in ("PENDING", "RUNNING"):
            return {**base, "status": "running", "next_action": "poll_existing_run" if run_id else "recover_owned_run_id",
                    "poll_after_seconds": 30, "do_not_resubmit": True}
        if status in ("FAILED", "CANCELLED"):
            return {**base, "status": status.lower(), "next_action": "report_run_outcome"}
        if status != "COMPLETED":
            return {**base, "status": "unverified", "next_action": "inspect_unknown_status"}
        result = value.get("result", value.get("resultJson"))
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = None
        if not isinstance(result, dict) or not result:
            return {**base, "status": "unverified", "next_action": "recover_missing_result"}
        if str(result.get("status", "")).lower() in ("failure", "failed", "error") or result.get("success") is False or result.get("error"):
            return {**base, "status": "failed", "next_action": "report_goal_failure"}
        if str(result.get("status", "")).lower() == "blocked":
            return {**base, "status": "blocked", "next_action": "report_goal_blocker"}
        missing = [name for name in required if name not in result or result[name] in (None, "", [], {})]
        partial = missing or result.get("missing_fields") or str(result.get("status", "")).lower() == "partial"
        return {**base, "status": "partial" if partial else "needs_review", "missing_fields": missing,
                "next_action": "verify_source_evidence_and_acceptance_criteria"}

    rows = value.get("results")
    errors = value.get("errors") or []
    if not isinstance(rows, list) or not isinstance(errors, list):
        raise RetrievalError("mcp_invalid_retrieval_schema")
    sources, seen, issues = [], set(), []
    expected = set(public_url(url) for url in requested)
    remaining = budget
    for row in rows:
        if not isinstance(row, dict):
            issues.append("malformed_result")
            continue
        try:
            url = public_url(row.get("url", ""))
            final_url = public_url(row.get("final_url") or url)
        except RetrievalError:
            issues.append("invalid_source_url")
            continue
        if url in seen:
            continue
        if expected and url not in expected:
            issues.append("unexpected_source_url")
            continue
        seen.add(url)
        raw = row.get("snippet") if operation == "search" else row.get("text")
        if not isinstance(raw, str) or not raw.strip():
            issues.append("missing_source_text")
            raw = ""
        cap = min(900 if operation == "search" else 1800, remaining)
        excerpt, matched = select_passages(raw, query, cap)
        excerpt = safe_text(excerpt)
        if raw and not excerpt:
            issues.append("output_budget_exhausted")
        remaining -= len(excerpt)
        sources.append({"url": url, "final_url": final_url, "title": safe_text(row.get("title"))[:300],
                        "published_date": safe_text(row.get("published_date") or row.get("date"))[:80] or None,
                        "excerpt": excerpt, "keyword_match": matched,
                        "truncated": len(excerpt) < len(raw), "evidence_verified": False})
    missing = sorted(expected - seen)
    failures = [{"url": safe_text(e.get("url"))[:2000], "code": safe_text(e.get("code", "fetch_failed"))[:100]}
                for e in errors if isinstance(e, dict)]
    status = "empty" if not sources else ("partial" if missing or errors or issues else "needs_review")
    return {"operation": operation, "status": status, "sources": sources, "errors": failures,
            "missing_urls": missing, "issues": issues, "received_at": received,
            "next_action": "select_relevant_primary_urls" if operation == "search" else "verify_evidence_and_retry_only_gaps"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("search", "fetch", "run"))
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--requested-url", action="append", default=[])
    p.add_argument("--required-field", action="append", default=[])
    p.add_argument("--query", default="")
    p.add_argument("--max-chars", type=int, default=12000)
    args = p.parse_args(argv)
    try:
        if not 100 <= args.max_chars <= 100000 or args.input.stat().st_size > 8 * 1024 * 1024:
            raise RetrievalError("mcp_input_or_output_too_large")
        raw = json.loads(args.input.read_text())
        result = inspect(args.operation, raw, args.requested_url, args.required_field, args.query, args.max_chars)
        import hashlib
        cache = state_root() / "mcp-results" / (hashlib.sha256(args.input.read_bytes()).hexdigest() + ".json")
        atomic_json(cache, json.loads(safe_text(json.dumps(raw))))
        result["cache_file"] = str(cache)
        print(safe_text(json.dumps(result, ensure_ascii=False)))
        return 2 if result["status"] in ("failed", "blocked", "cancelled", "empty", "partial", "unverified") else 0
    except (RetrievalError, ValueError, OSError, TypeError) as error:
        print(json.dumps({"status": "unverified", "code": error.code if isinstance(error, RetrievalError) else "invalid_saved_result"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
