"""leaks.py RUN_DIR AB [ALLOW_PREFIX...] — list tool calls that reached outside the cells.

RUN_DIR is <config dir>/projects/<slug>/<session>/subagents/workflows/<run id>.
Prints one line per agent with a hit: its label, then up to five offending
inputs. Paths under AB, the given prefixes and the system directories pass; so
does nothing else, and web and MCP tools are always reported. Review hits by
hand. Protocol: ../2026-10-23-workflow-effort-and-reader-ab.md
"""
import json
import pathlib
import re
import sys

run, ab, *allow = sys.argv[1:]
ok = (ab, *allow, "/usr/", "/bin/", "/etc/", "/dev/", "/proc/", "/lib")
path_re = re.compile(r"(?<![\w.~$-])/[A-Za-z][\w.+-]*(?:/[\w.+@-]+)+")
for f in sorted(pathlib.Path(run).glob("agent-*.jsonl")):
    meta = f.with_suffix(".meta.json")
    label = json.loads(meta.read_text()).get("description", f.stem) if meta.is_file() else f.stem
    hits = []
    for line in f.open(encoding="utf-8", errors="replace"):
        content = (json.loads(line).get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if b.get("type") != "tool_use":
                continue
            if b.get("name") in ("WebFetch", "WebSearch") or "mcp__" in b.get("name", ""):
                hits.append(b.get("name"))
                continue
            text = json.dumps(b.get("input"))
            hits += [p for p in path_re.findall(text) if not p.startswith(ok)]
    if hits:
        print(label, sorted(set(hits))[:5])
