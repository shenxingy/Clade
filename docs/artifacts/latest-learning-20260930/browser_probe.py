#!/usr/bin/env python3
"""Exercise two recent browser features with local, disposable HTTP fixtures.

Requires Playwright and Chrome; no vendor API, credentials or public server.
Example: uv run --offline --with playwright python browser_probe.py --output /tmp/probe.json
This is a small learning experiment, not a security conformance suite.
"""
import argparse
import asyncio
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from playwright.async_api import async_playwright


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        with self.server.hits_lock:
            self.server.hits[path] += 1
        headers = {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                   "Access-Control-Allow-Origin": "*"}
        status, body = 200, "<!doctype html><title>Local learning fixture</title>ok"
        if path == "/enforce":
            headers["Connection-Allowlist"] = "(response-origin)"
        elif path == "/report-only":
            headers["Connection-Allowlist-Report-Only"] = "(response-origin)"
        elif path.startswith("/redirect/"):
            status = 302
            headers["Location"] = "/redirect-target/" + path.rsplit("/", 1)[-1]
        elif path in ("/frames", "/frames-no-opt-in"):
            child = "/child" if path == "/frames" else "/child-no-opt-in"
            body = ('<!doctype html><title>Frame fixture</title>'
                    '<style>iframe{width:400px;border:0}#responsive{frame-sizing:content-height}</style>'
                    f'<iframe id="control" src="{child}" title="Default sizing"></iframe>'
                    f'<iframe id="responsive" src="{child}" title="Responsive sizing"></iframe>')
        elif path in ("/child", "/child-no-opt-in"):
            meta = '<meta name="responsive-embedded-sizing" content="allow-origins=*">' if path == "/child" else ""
            body = (f'<!doctype html><head>{meta}<title>Child</title>'
                    '<style>body{margin:0}#content{height:600px;background:#ddd}</style></head>'
                    '<body><div id="content">600 pixel content</div></body>')
        encoded = body.encode()
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.hits, httpd.hits_lock = Counter(), threading.Lock()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


async def run(chrome):
    first, second = server(), server()
    origin = f"http://127.0.0.1:{first.server_port}"
    other = f"http://127.0.0.1:{second.server_port}"
    started = time.monotonic()
    rows = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=chrome, args=["--disable-gpu"])
            version = browser.version
            # Independent pages, two bounded contexts; each lane's observations are sequential.
            gate = asyncio.Semaphore(2)

            async def network(mode):
                async with gate:
                    context = await browser.new_context()
                    page = await context.new_page()
                    errors = []
                    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                    await page.goto(origin + "/" + mode)
                    results = {}
                    for label, url in [("same_origin", origin + "/same-" + mode),
                                       ("other_origin", other + "/other-" + mode),
                                       ("same_origin_redirect", origin + "/redirect/" + mode)]:
                        results[label] = await page.evaluate("""async url => {
                          try { const r = await fetch(url); await r.text(); return {ok:r.ok}; }
                          catch (e) { return {ok:false, error:e.name}; }
                        }""", url)
                    await context.close()
                    return {"mode": mode, "fetch": results, "console_errors": errors}

            rows = await asyncio.gather(*(network(mode) for mode in ("control", "enforce", "report-only")))
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(origin + "/frames")
            await page.wait_for_function("document.querySelectorAll('iframe').length === 2")
            support = await page.evaluate("CSS.supports('frame-sizing', 'content-height')")
            child_element = await page.query_selector("#responsive")
            child = await child_element.content_frame()
            assert child is not None
            resize = await child.evaluate("typeof window.requestResize === 'function'")
            if support:
                await page.wait_for_function("document.querySelector('#responsive').clientHeight >= 600", timeout=5000)
            initial = await page.locator("iframe").evaluate_all("els => els.map(e => ({id:e.id,height:e.clientHeight}))")
            await child.evaluate("document.querySelector('#content').style.height = '900px'")
            if resize:
                await child.evaluate("window.requestResize()")
                await page.wait_for_function("document.querySelector('#responsive').clientHeight >= 900", timeout=5000)
            dynamic_height = await page.locator("#responsive").evaluate("e => e.clientHeight")
            await page.goto(origin + "/frames-no-opt-in")
            no_opt_in = await page.locator("#responsive").evaluate("e => e.clientHeight")
            await context.close()
            await browser.close()
        by_mode = {row["mode"]: row["fetch"] for row in rows}
        checks = {
            "control_requests_succeed": all(x["ok"] for x in by_mode["control"].values()),
            "enforced_same_origin_allowed": by_mode["enforce"]["same_origin"]["ok"],
            "enforced_other_origin_blocked_before_server": not by_mode["enforce"]["other_origin"]["ok"] and second.hits["/other-enforce"] == 0,
            "enforced_redirect_blocked_before_target": not by_mode["enforce"]["same_origin_redirect"]["ok"] and first.hits["/redirect-target/enforce"] == 0,
            "report_only_requests_succeed": all(x["ok"] for x in by_mode["report-only"].values()),
            "responsive_height_600_default_150": support and {x["id"]: x["height"] for x in initial} == {"control": 150, "responsive": 600},
            "explicit_resize_updates_to_900": resize and dynamic_height == 900,
            "child_opt_in_required": no_opt_in == 150,
        }
        return {"kind": "local-browser-learning-probe", "browser": version,
                "seconds": round(time.monotonic() - started, 3), "browser_context_limit": 2,
                "gpu_used": False, "remote_requests_intended": False,
                "checks": checks, "network": rows, "server_hits": {"first": dict(first.hits), "second": dict(second.hits)},
                "frames": {"css_supported": support, "request_resize_supported": resize,
                           "initial": initial, "after_request_resize": dynamic_height, "without_child_opt_in": no_opt_in},
                "limits": ["one Linux Chrome build, loopback HTTP only", "no WebRTC, workers or hostile-code security audit",
                           "report-only delivery to a reporting endpoint not tested", "no Firefox, Safari or hosted wrapper"]}
    finally:
        first.shutdown()
        second.shutdown()
        first.server_close()
        second.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chrome", default="/usr/bin/google-chrome")
    args = parser.parse_args()
    result = asyncio.run(run(args.chrome))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"browser": result["browser"], "seconds": result["seconds"], "checks": result["checks"]}, indent=2))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
