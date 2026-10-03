#!/usr/bin/env python3
"""Native/TinyFish routing and bounded retrieval; no third-party dependencies."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SEARCH_ENDPOINT = "https://api.search.tinyfish.ai"
FETCH_ENDPOINT = "https://api.fetch.tinyfish.ai"
MAX_RESPONSE = 8 * 1024 * 1024
KEY_PATTERN = re.compile(r"sk-tinyfish-[A-Za-z0-9_-]{20,120}")


class RetrievalError(Exception):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code)


def private_dir(path):
    path = Path(path).expanduser()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or (hasattr(os, "getuid") and path.stat().st_uid != os.getuid()):
        raise RetrievalError("unsafe_private_directory")
    path.chmod(0o700)
    return path


def atomic_json(path, value):
    private_dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        os.chmod(temp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def key_file():
    return Path(os.environ.get("TINYFISH_API_KEY_FILE", "~/.config/clade/secrets/tinyfish.key")).expanduser()


def read_key():
    key = os.environ.get("TINYFISH_API_KEY", "").strip()
    if not key:
        path = key_file()
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise RetrievalError("unsafe_key_file")
                if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                    raise RetrievalError("key_file_must_be_owner_only")
                key = stream.read(512).strip()
        except FileNotFoundError:
            raise RetrievalError("missing_tinyfish_key") from None
        except OSError:
            raise RetrievalError("unreadable_key_file") from None
    if not KEY_PATTERN.fullmatch(key):
        raise RetrievalError("invalid_key_format")
    return key


def state_root():
    return private_dir(Path(os.environ.get("CLADE_SEARCH_STATE_DIR", "~/.clade/search")).expanduser())


def safe_text(value):
    return KEY_PATTERN.sub("[REDACTED]", str(value or ""))


def public_url(value):
    try:
        url = urllib.parse.urlsplit(value)
        host = (url.hostname or "").lower()
        if (url.scheme not in ("http", "https") or not host or url.username or url.password
                or url.port not in (None, 80, 443) or any(c.isspace() for c in value)):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # An IP-looking address must parse as a public IP, not fall back to a hostname.
            if re.fullmatch(r"[\d.:]+", host) or ":" in host or "." not in host:
                raise ValueError
        else:
            if not address.is_global:
                raise ValueError
        if host.rstrip(".").endswith((".local", ".internal", ".localhost")):
            raise ValueError
        return urllib.parse.urlunsplit((url.scheme, url.netloc, url.path or "/", url.query, ""))
    except (ValueError, TypeError):
        raise RetrievalError("invalid_public_url") from None


def route(operation, native, queries, pages, recurring, provider, credential):
    if provider == "native":
        selected = "native" if native == "available" else "blocked"
        reason = "explicit_native" if selected == "native" else "native_unavailable"
    elif provider == "tinyfish":
        selected = "tinyfish" if credential else "blocked"
        reason = "explicit_tinyfish" if credential else "missing_tinyfish_key"
    elif native == "available" and not recurring and queries < 5 and pages < 20:
        selected, reason = "native", "small_interactive_lookup"
    elif credential:
        selected, reason = "tinyfish", "bulk_recurring_or_native_unavailable"
    elif native == "available":
        selected, reason = "native", "tinyfish_unconfigured"
    else:
        selected, reason = "blocked", "no_available_retrieval_backend"
    return {"provider": selected, "operation": operation, "reason": reason,
            "executed": False, "next_action": "call_native_" + operation if selected == "native"
            else ("run_tinyfish_" + operation if selected == "tinyfish" else "report_unavailable")}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward an API credential to a redirect destination.


class Client:
    def __init__(self, key, root=None, timeout=35):
        self.key = key
        self.root = private_dir(root or state_root())
        self.cache = private_dir(self.root / "cache")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())
        # Capability/cache state is isolated per credential without persisting the key.
        self.account = hashlib.sha256(key.encode()).hexdigest()[:16]
        self.cap_file = self.root / ("capabilities-" + self.account + ".json")

    def request(self, endpoint, payload, method):
        if endpoint not in (SEARCH_ENDPOINT, FETCH_ENDPOINT):
            raise RetrievalError("unsupported_endpoint")
        data = None
        url = endpoint
        if method == "GET":
            url += "?" + urllib.parse.urlencode(payload)
        else:
            data = json.dumps(payload).encode()
        request = urllib.request.Request(url, data=data, method=method, headers={
            "X-API-Key": self.key, "Content-Type": "application/json", "Accept": "application/json"})
        for attempt in range(2):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    body = response.read(MAX_RESPONSE + 1)
                if len(body) > MAX_RESPONSE:
                    raise RetrievalError("response_too_large")
                obj = json.loads(body)
                if not isinstance(obj, dict) or not isinstance(obj.get("results"), list):
                    raise RetrievalError("unexpected_response_schema")
                # A malformed entry must not masquerade as an empty successful result.
                if any(not isinstance(row, dict) for row in obj["results"]):
                    raise RetrievalError("unexpected_result_schema")
                return obj
            except urllib.error.HTTPError as error:
                if attempt == 0 and (error.code == 429 or 500 <= error.code < 600):
                    wait = error.headers.get("Retry-After", "1")
                    if wait.isdigit() and int(wait) <= 2:
                        time.sleep(max(1, int(wait)))
                        continue
                raise RetrievalError("tinyfish_http_error", error.code) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                raise RetrievalError("tinyfish_network_error") from None
            except (ValueError, UnicodeError):
                raise RetrievalError("invalid_json_response") from None
        raise RetrievalError("retry_exhausted")

    def capabilities(self):
        try:
            value = json.loads(self.cap_file.read_text())
            if time.time() - value["checked_at"] < 86400:
                return value
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return {"highlights": "unknown"}

    def set_highlights(self, supported):
        atomic_json(self.cap_file, {"highlights": supported, "checked_at": time.time()})

    def cached_request(self, endpoint, payload, method, fresh=False):
        digest = hashlib.sha256(json.dumps([self.account, endpoint, payload], sort_keys=True).encode()).hexdigest()
        path = self.cache / (digest + ".json")
        if not fresh:
            try:
                stored = json.loads(path.read_text())
                if time.time() - stored["cached_at"] < 3600 and isinstance(stored["data"].get("results"), list):
                    return stored["data"], str(path), True
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
        value = self.request(endpoint, payload, method)
        value = json.loads(safe_text(json.dumps(value, ensure_ascii=False)))
        atomic_json(path, {"cached_at": time.time(), "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(), "data": value})
        return value, str(path), False

    def search(self, query, filters=None, fresh=False):
        payload = {"query": query, **(filters or {})}
        obj, cache, hit = self.cached_request(SEARCH_ENDPOINT, payload, "GET", fresh)
        rows, seen = [], set()
        for row in obj["results"]:
            try:
                url = public_url(row.get("url", ""))
            except RetrievalError:
                continue
            if url in seen:
                continue
            seen.add(url)
            rows.append({"url": url, "title": safe_text(row.get("title"))[:300],
                         "snippet": safe_text(row.get("snippet"))[:900],
                         "date": safe_text(row.get("date"))[:40]})
        return {"provider": "tinyfish", "operation": "search", "status": "ok" if rows else "empty",
                "results": rows[:10], "omitted_results": len(obj["results"]) - min(10, len(rows)),
                "cache_file": cache, "cache_hit": hit,
                "next_action": "select_urls_then_fetch" if rows else "revise_query_or_use_native"}

    def fetch(self, urls, query="", max_chars=1800, total_chars=12000, fresh=False,
              highlights="auto", include=None, exclude=None):
        urls = list(dict.fromkeys(public_url(url) for url in urls))
        if not urls or len(urls) > 50:
            raise RetrievalError("fetch_requires_1_to_50_urls")
        results, errors, caches = [], [], []
        remaining = total_chars
        for offset in range(0, len(urls), 10):
            payload = {"urls": urls[offset:offset + 10], "format": "markdown", "ttl": 0 if fresh else 3600,
                       "per_url_timeout_ms": 30000}
            if query:
                payload["purpose"] = query[:2000]
            if include:
                payload["include_selectors"] = include
            if exclude:
                payload["exclude_selectors"] = exclude
            use_highlights = bool(query) and highlights != "off" and self.capabilities()["highlights"] is not False
            if use_highlights:
                payload["highlights"] = {"query": query, "max_snippets": 3,
                                         "max_characters": max_chars, "include_full_page_text": False}
            try:
                obj, cache, hit = self.cached_request(FETCH_ENDPOINT, payload, "POST", fresh)
            except RetrievalError as error:
                if not use_highlights or error.status != 403:
                    raise
                # A successful plain request distinguishes Beta denial from a bad credential.
                payload.pop("highlights")
                obj, cache, hit = self.cached_request(FETCH_ENDPOINT, payload, "POST", fresh)
                self.set_highlights(False)
                use_highlights = False
            if use_highlights and any(row.get("highlights") is not None for row in obj["results"]):
                self.set_highlights(True)
            if use_highlights and any(not highlight_text(row.get("highlights")) and not row.get("text")
                                      for row in obj["results"]):
                # Beta response shapes can change. Get ordinary source text when no excerpt is usable.
                payload.pop("highlights")
                obj, cache, hit = self.cached_request(FETCH_ENDPOINT, payload, "POST", fresh)
                use_highlights = False
            caches.append({"path": cache, "hit": hit})
            for error in obj.get("errors", []):
                if isinstance(error, dict):
                    errors.append({"url": safe_text(error.get("url"))[:2000],
                                   "code": safe_text(error.get("code", "fetch_failed"))[:100]})
            returned = set()
            for row in obj["results"]:
                url = public_url(row.get("url", ""))
                if url not in payload["urls"] or url in returned:
                    raise RetrievalError("unexpected_fetch_url")
                returned.add(url)
                final_url = public_url(row.get("final_url") or url)
                text = row.get("text") or ""
                if not isinstance(text, str):
                    raise RetrievalError("unexpected_fetch_text")
                passages = highlight_text(row.get("highlights")) if use_highlights else ""
                mode = "tinyfish_highlights" if passages else "local_keyword_passages"
                cap = min(max_chars, remaining)
                if not passages:
                    passages, matched = select_passages(text, query, cap)
                    if not matched:
                        mode = "preview_no_keyword_match" if query else "page_preview"
                excerpt = safe_text(passages)[:cap]
                remaining -= len(excerpt)
                results.append({"url": url, "final_url": final_url, "title": safe_text(row.get("title"))[:300],
                                "excerpt": excerpt, "selection": mode,
                                "truncated": len(passages) > cap or (not mode.startswith("tinyfish") and len(text) > len(excerpt)),
                                "cache_file": cache, "cache_hit": hit,
                                "evidence_status": "retrieved_not_verified"})
            accounted = returned | {e["url"] for e in errors}
            for missing in set(payload["urls"]) - accounted:
                errors.append({"url": missing, "code": "missing_from_response"})
        return {"provider": "tinyfish", "operation": "fetch", "status": "partial" if errors else "ok",
                "results": results, "errors": errors, "cache_files": caches,
                "highlights_capability": self.capabilities()["highlights"],
                "omitted_page_excerpts": sum(not row["excerpt"] for row in results),
                "next_action": "verify_excerpts_and_read_cached_source_if_needed"}


def highlight_text(value):
    """Accept documented passage arrays; unknown shapes must use the plain-text path."""
    if isinstance(value, dict):
        value = value.get("snippets", value.get("passages", []))
    if not isinstance(value, list):
        return ""
    return "\n\n".join(item if isinstance(item, str) else str(item.get("text", ""))
                       for item in value if isinstance(item, (str, dict)))


def terms(query):
    found = re.findall(r"[a-z0-9_]{2,}", query.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", query):
        found.extend(run[i:i + 2] for i in range(len(run) - 1))
    return set(found)


def select_passages(text, query, budget):
    # Bounded overlapping windows also work for minified/one-paragraph pages.
    windows = [text[i:i + 1200] for i in range(0, len(text), 1000)]
    needles = terms(query)
    scored = [(sum(min(chunk.lower().count(word), 3) for word in needles), i, chunk)
              for i, chunk in enumerate(windows)]
    matched = any(score > 0 for score, _, _ in scored)
    if not matched:
        return text[:budget], False
    snippets, remaining, used = [], budget, []
    for score, index, chunk in sorted(scored, key=lambda row: (-row[0], row[1])):
        if not score or remaining <= 0 or len(snippets) == 3:
            break
        if any(abs(index - previous) <= 1 for previous in used):
            continue  # Avoid repeating overlapping source windows.
        width = min(len(chunk), remaining)
        hits = [chunk.lower().find(word) for word in needles if word in chunk.lower()]
        # Center the bounded slice on evidence, rather than cutting it off at a window's tail.
        start = max(0, min(min(hits) - width // 3, len(chunk) - width))
        snippets.append(chunk[start:start + width])
        remaining -= width + 2
        used.append(index)
    return "\n\n".join(snippets), True


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("route")
    plan.add_argument("--operation", choices=("search", "fetch"), required=True)
    plan.add_argument("--native", choices=("available", "unavailable", "failed"), required=True)
    plan.add_argument("--queries", type=positive, default=1)
    plan.add_argument("--pages", type=positive, default=1)
    plan.add_argument("--recurring", action="store_true")
    plan.add_argument("--provider", choices=("auto", "native", "tinyfish"), default="auto")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--purpose")
    for flag in ("include-domain", "exclude-domain"):
        search.add_argument("--" + flag, action="append")
    for flag in ("after-date", "before-date", "language", "location"):
        search.add_argument("--" + flag)
    search.add_argument("--recency-minutes", type=positive)
    search.add_argument("--domain-type", choices=("web", "news", "research_paper"))
    search.add_argument("--pub-year-min", type=int)
    search.add_argument("--pub-year-max", type=int)
    search.add_argument("--fresh", action="store_true")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("urls", nargs="+")
    fetch.add_argument("--query", default="")
    fetch.add_argument("--max-chars", type=positive, default=1800)
    fetch.add_argument("--total-chars", type=positive, default=12000)
    fetch.add_argument("--highlights", choices=("auto", "off"), default="auto")
    fetch.add_argument("--include-selector", action="append")
    fetch.add_argument("--exclude-selector", action="append")
    fetch.add_argument("--fresh", action="store_true")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--live", action="store_true")
    sub.add_parser("configure-key")
    return parser.parse_args(argv)


def search_filters(args):
    if not args.query.strip() or len(args.query) > 2000 or len(args.purpose or "") > 2000:
        raise RetrievalError("invalid_query_or_purpose")
    if args.recency_minutes and (args.after_date or args.before_date):
        raise RetrievalError("conflicting_date_filters")
    for value in (args.after_date, args.before_date):
        if value:
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                raise RetrievalError("invalid_date_filter") from None
    if args.after_date and args.before_date and args.after_date > args.before_date:
        raise RetrievalError("reversed_date_range")
    if args.domain_type == "research_paper" and (args.after_date or args.before_date or args.recency_minutes):
        raise RetrievalError("papers_require_year_filters")
    if args.domain_type != "research_paper" and (args.pub_year_min is not None or args.pub_year_max is not None):
        raise RetrievalError("year_filters_require_papers")
    fields = ("purpose", "after_date", "before_date", "language", "location", "recency_minutes",
              "domain_type", "pub_year_min", "pub_year_max")
    output = {key: getattr(args, key) for key in fields if getattr(args, key) is not None}
    for source, target in (("include_domain", "include_domains"), ("exclude_domain", "exclude_domains")):
        domains = getattr(args, source)
        if domains:
            if any(not re.fullmatch(r"[A-Za-z0-9.-]+", domain) for domain in domains):
                raise RetrievalError("invalid_domain_filter")
            output[target] = ",".join(domains)
    return output


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.command == "configure-key":
            import getpass
            key = getpass.getpass("TinyFish API key: ") if sys.stdin.isatty() else sys.stdin.read(512).strip()
            if not KEY_PATTERN.fullmatch(key):
                raise RetrievalError("invalid_key_format")
            dest = key_file()
            private_dir(dest.parent)
            fd, temp = tempfile.mkstemp(prefix=".key-", dir=dest.parent)
            with os.fdopen(fd, "w") as stream:
                stream.write(key + "\n")
            os.chmod(temp, 0o600)
            os.replace(temp, dest)
            result = {"status": "configured", "credential_visible": False}
        elif args.command == "route":
            try:
                read_key()
                credential = True
            except RetrievalError:
                credential = False
            result = route(args.operation, args.native, args.queries, args.pages, args.recurring, args.provider, credential)
        else:
            client = Client(read_key())
            if args.command == "search":
                result = client.search(args.query, search_filters(args), args.fresh)
            elif args.command == "fetch":
                if not 100 <= args.max_chars <= 20000 or args.total_chars > 100000 or len(args.query) > 2000:
                    raise RetrievalError("invalid_output_budget_or_query")
                result = client.fetch(args.urls, args.query, args.max_chars, args.total_chars, args.fresh,
                                      args.highlights, args.include_selector, args.exclude_selector)
            else:
                result = {"credential": "configured", "highlights": client.capabilities()["highlights"], "live_verified": False}
                if args.live:
                    search = client.search("TinyFish Search API documentation", fresh=True)
                    fetch = client.fetch(["https://www.tinyfish.ai/pricing"], "TinyFish Search Fetch free limits", fresh=True)
                    result.update(live_verified=bool(search["results"] and any(r["excerpt"] for r in fetch["results"])
                                                     and not fetch["errors"]),
                                  search_status=search["status"], fetch_status=fetch["status"],
                                  highlights=fetch["highlights_capability"],
                                  fetch_selection=[r["selection"] for r in fetch["results"]])
        print(json.dumps(result, ensure_ascii=False))
        failed = (result.get("provider") == "blocked" or result.get("status") in ("partial", "empty")
                  or (args.command == "doctor" and args.live and not result.get("live_verified")))
        return 2 if failed else 0
    except RetrievalError as error:
        print(json.dumps({"status": "error", "code": error.code, "http_status": error.status,
                          "next_action": "use_native_if_available_otherwise_report_failure"}))
        return 2
    except (OSError, ValueError, TypeError):
        print(json.dumps({"status": "error", "code": "local_io_or_data_error",
                          "next_action": "use_native_if_available_otherwise_report_failure"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
