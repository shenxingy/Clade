"""leaks.py RUN_DIR AB — list the A/B agents whose tool calls could reach outside their cell.

RUN_DIR is <config dir>/projects/<slug>/<session>/subagents/workflows/<run id>.
Each agent's label, tier:<task>:<arm>:<rep>, names its one cell, AB/<task>/<arm>-<rep>;
AB/args.json (written by prep.sh) supplies AB's root and the PY path the brief exports.

A call is a hit when it:
- names an absolute path that is not inside the agent's own cell, not the exact PY
  path, and not under a system directory (a sibling cell or another checkout is a hit);
- names the filesystem root itself as a bare `/` word (`find / -name x`, `grep -r x /`,
  `cd / && ls`, `ls /*`): a search from there reaches every cell and checkout. A
  division sign written between spaces (`$((a / 2))`) is flagged too; hand review
  clears it;
- uses `~`, `$HOME` or a `..` path component (in a Bash command, or a tool's path);
- is a Bash command that does not begin with `cd <own cell>`. Every Bash call starts in
  the lead's working directory, so without that `cd` it runs somewhere else;
- is a Read, Write, Edit, Grep or Glob whose path is missing, relative, or outside the
  cell (Grep and Glob without a path search the lead's working directory);
- uses any other tool than those and StructuredOutput, TodoWrite and ToolSearch: web,
  MCP and agent-spawning tools are always hits.
A transcript line that does not parse is a hit too, because the call it held went
unchecked. File contents an agent writes (Write content, Edit strings) are not scanned:
writing a path is not reading one.

This is a list for hand review, not proof: it reads what a call asked for, not what a
command did, so a path built inside a variable can pass unseen. Prints one line per agent
with hits (label, count, up to five `reason: text`), then a summary. Exit 1 if any agent
had a hit, 0 if none. Protocol: ../2026-10-23-workflow-effort-and-reader-ab.md
"""
import json
import pathlib
import posixpath
import re
import sys

# ─── What counts as a reach outside the cell ───
SYSTEM = ("/usr/", "/bin/", "/sbin/", "/etc/", "/dev/", "/proc/", "/lib", "/opt/homebrew/")
PATH_TOOLS = {"Read": ("file_path",), "Write": ("file_path",), "Edit": ("file_path",),
              "MultiEdit": ("file_path",), "NotebookEdit": ("notebook_path",),
              "Grep": ("path",), "Glob": ("path",)}
QUIET_TOOLS = {"StructuredOutput", "TodoWrite", "ToolSearch"}
LABEL = re.compile(r"^tier:([\w.-]+):([ABC]):(\d+)$")
ABS = re.compile(r"(?<![\w.~$}-])/[A-Za-z][\w.+-]*(?:/[\w.+@-]*)*")
HOMEISH = re.compile(r"(?<![\w$])~(?=[/\s'\"):;&|]|$)|\$HOME\b|\$\{HOME\}")
UPDIR = re.compile(r"(?:^|[\s/'\"=:(])\.\.(?=[/\s'\"):;&|]|$)")
# A word that starts at the root without naming a directory under it: `/`, `//`, `/*`,
# `/.`. ABS needs a letter after the slash, so it never sees these.
ROOT = re.compile(r"(?<![^\s'\"=(])/+(?=$|[\s'\";&|)<>*?.\[{])[^\s'\";&|)<>]*")


def inside(path, cell):
    norm = posixpath.normpath(path)
    return cell is not None and (norm == cell or norm.startswith(cell + "/"))


def check_text(text, cell, py):
    """Hits in free text that a shell will execute."""
    hits = [f"outside: {p}" for p in ABS.findall(text)
            if not inside(p, cell) and p != py and p != "/dev/null" and not p.startswith(SYSTEM)]
    hits += [f"outside: {m.group(0)}" for m in ROOT.finditer(text)]
    hits += [f"home: {m.group(0)}" for m in HOMEISH.finditer(text)]
    hits += ["updir: .." for _ in UPDIR.finditer(text)]
    return hits


def starts_in_cell(command, cell):
    """True when the command's first action is `cd` into the cell or a directory under it."""
    if cell is None:
        return False
    lead = re.compile(r"\s*cd\s+([\"']?)" + re.escape(cell) + r"(?:/[^\s\"';&|]*)?\1(?=$|[\s;&|])")
    target = lead.match(command)
    return bool(target) and ".." not in target.group(0)


def check_call(name, args, cell, py):
    if name == "Bash":
        command = str(args.get("command", ""))
        hits = check_text(command, cell, py)
        if not starts_in_cell(command, cell):
            hits.append("no-cd: " + command.strip().splitlines()[0][:80] if command.strip() else "no-cd: (empty)")
        return hits
    if name in PATH_TOOLS:
        hits = []
        pattern = str(args.get("pattern", "")) if name == "Glob" else ""
        for key in PATH_TOOLS[name]:
            value = args.get(key)
            if not value and pattern.startswith("/"):
                continue  # an absolute Glob pattern does not depend on the working directory
            if not value:
                hits.append(f"{name} without {key}")
            elif not str(value).startswith("/"):
                hits.append(f"{name} relative {key}: {value}")
            elif not inside(str(value), cell):
                hits.append(f"{name} outside: {value}")
            hits += [h for h in check_text(str(value or ""), cell, py) if not h.startswith("outside")]
        if pattern.startswith("/") and not inside(pattern.split("*", 1)[0] or "/", cell):
            hits.append(f"Glob pattern outside: {pattern}")
        if ".." in pattern.split("/"):
            hits.append(f"Glob pattern updir: {pattern}")
        return hits
    if name in QUIET_TOOLS:
        return []
    return [f"tool: {name}"]


# ─── One transcript ───
def scan(transcript, cell, py):
    hits, unreadable = [], 0
    for line in transcript.open(encoding="utf-8", errors="replace"):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            unreadable += 1
            continue
        content = (record.get("message") or {}).get("content") if isinstance(record, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                hits += check_call(str(block.get("name", "")), args, cell, py)
    if unreadable:
        hits.append(f"unreadable: {unreadable} transcript line(s) not checked")
    return hits


def main(argv):
    if len(argv) != 2:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    run, ab = pathlib.Path(argv[0]), pathlib.Path(argv[1])
    spec = json.loads((ab / "args.json").read_text())
    root, py = str(spec["root"]).rstrip("/"), str(spec["py"])
    agents = flagged = 0
    for transcript in sorted(run.glob("agent-*.jsonl")):
        agents += 1
        meta = transcript.with_suffix(".meta.json")
        try:
            label = json.loads(meta.read_text()).get("description", transcript.stem)
        except (OSError, ValueError):
            label = transcript.stem
        match = LABEL.match(str(label))
        cell = f"{root}/{match.group(1)}/{match.group(2)}-{match.group(3)}" if match else None
        hits = scan(transcript, cell, py)
        if cell is None:
            hits.insert(0, "label is not tier:<task>:<arm>:<rep>, so no cell is allowed")
        if hits:
            flagged += 1
            unique = list(dict.fromkeys(hits))
            print(f"{label}\t{len(hits)} hit(s)\t" + " | ".join(unique[:5]))
    print(f"scanned {agents} agent(s), {flagged} with hits")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
