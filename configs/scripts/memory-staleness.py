#!/usr/bin/env python3
"""Report auto-memories whose declared repository anchors have changed.

Usage: memory-staleness.py MEMORY_DIR PROJECT_DIR [--review] [--days N]
       [--budget SECONDS]

Path and glob anchors are compared with their latest git commit. A missing path
is stale regardless of timestamps. A ``commit: SHA`` anchor baselines a memory's
path anchors: a path is stale when ``git log SHA..HEAD -- PATH`` is non-empty.
A commit anchor without paths is a review finding. The review mode also lists
unanchored memories older than 60 days by default.
Only Python's standard library is used, and no file is modified.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

MAX_READ_BYTES = 65536
DEFAULT_BUDGET_SECONDS = 2.0


@dataclass(frozen=True)
class Anchor:
    kind: str
    value: str

    @property
    def display(self) -> str:
        return self.value if self.kind == "path" else "commit:" + self.value


@dataclass(frozen=True)
class Memory:
    path: Path
    modified: float
    anchors: Tuple[Anchor, ...]


class BudgetExceeded(Exception):
    pass


class Deadline:
    def __init__(self, seconds: float) -> None:
        self.finish = time.monotonic() + max(0.0, seconds)

    def remaining(self) -> float:
        return self.finish - time.monotonic()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) < 2 or value[0] != value[-1] or value[0] not in ("'", '"'):
        return value.split(" #", 1)[0].rstrip()
    if value[0] == '"':
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, str) else ""
        except (ValueError, TypeError):
            return ""
    return value[1:-1].replace("''", "'")


def _path_anchor(value: str) -> Optional[Anchor]:
    value = _unquote(value)
    if not value or value.startswith(("/", ":")) or ".." in PurePosixPath(value).parts:
        return None
    if "\x00" in value or "\n" in value or "\r" in value:
        return None
    # git reports "nested/a.py", never "./nested/a.py"; an unnormalised anchor never matched.
    value = "/".join(part for part in value.split("/") if part not in ("", "."))
    return Anchor("path", value) if value else None


def _anchor(value: str) -> Optional[Anchor]:
    value = value.strip()
    match = re.match(r"^(commit|path)\s*:\s*(.*?)\s*$", value)
    if match:
        if match.group(1) == "path":
            return _path_anchor(match.group(2))
        sha = _unquote(match.group(2))
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
            return Anchor("commit", sha)
        return None
    if ":" in value and not value.startswith(('"', "'")):
        return None
    return _path_anchor(value)


def _inline_anchors(raw: str) -> Tuple[Anchor, ...]:
    body = raw[1:-1].strip()
    if not body:
        return ()
    items: List[str] = []
    current: List[str] = []
    quote = ""
    escaped = False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote == '"':
            current.append(char)
            escaped = True
            continue
        if char in ("'", '"'):
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
            current.append(char)
            continue
        if char == "," and not quote:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    if quote:
        return ()
    items.append("".join(current))
    return tuple(anchor for anchor in (_anchor(item) for item in items) if anchor is not None)


def _frontmatter(text: str) -> Tuple[Optional[str], Tuple[Anchor, ...]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, ()
    closing: Optional[int] = None
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            closing = index
            break
    if closing is None:
        return None, ()

    modified: Optional[str] = None
    anchors: Tuple[Anchor, ...] = ()
    index = 1
    while index < closing:
        line = lines[index]
        modified_match = re.match(r"^\s+modified\s*:\s*(.*?)\s*$", line)
        top_modified = re.match(r"^modified\s*:\s*(.*?)\s*$", line)
        if top_modified or (modified_match and not line.lstrip().startswith("-")):
            modified = _unquote((top_modified or modified_match).group(1))  # type: ignore[union-attr]
        anchor_match = re.match(r"^anchors\s*:\s*(.*?)\s*$", line)
        if not anchor_match:
            index += 1
            continue
        raw = anchor_match.group(1)
        if raw.startswith("[") and raw.endswith("]"):
            anchors = _inline_anchors(raw)
        elif not raw:
            found: List[Anchor] = []
            index += 1
            while index < closing:
                item = re.match(r"^[ \t]*-[ \t]*(.*?)\s*$", lines[index])
                if item:
                    anchor = _anchor(item.group(1))
                    if anchor is not None:
                        found.append(anchor)
                elif re.match(r"^[A-Za-z_][A-Za-z0-9_-]*\s*:", lines[index]):
                    break
                index += 1
            anchors = tuple(found)
            continue
        index += 1
    return modified, anchors


def _timestamp(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _load_memory(path: Path) -> Optional[Memory]:
    if path.name == "MEMORY.md" or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(MAX_READ_BYTES)
        modified_raw, anchors = _frontmatter(text)
        modified = _timestamp(modified_raw)
        modified = modified if modified is not None else path.stat().st_mtime
    except (OSError, ValueError):
        return None
    return Memory(path, modified, anchors)


def _memories(memory_dir: Path) -> List[Memory]:
    try:
        paths = sorted(memory_dir.glob("*.md"))
    except OSError:
        return []
    return [memory for memory in (_load_memory(path) for path in paths) if memory is not None]


def _git_bytes(project: Path, arguments: Sequence[str], deadline: Deadline,
               input_data: Optional[bytes] = None) -> Optional[bytes]:
    remaining = deadline.remaining()
    if remaining <= 0:
        raise BudgetExceeded()
    try:
        proc = subprocess.run(
            ["git", "-C", str(project), *arguments],
            stdin=subprocess.DEVNULL if input_data is None else None,
            input=input_data,
            capture_output=True,
            timeout=remaining,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise BudgetExceeded()
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git(project: Path, arguments: Sequence[str], deadline: Deadline,
         input_text: Optional[str] = None) -> Optional[str]:
    input_data = input_text.encode("utf-8") if input_text is not None else None
    output = _git_bytes(project, arguments, deadline, input_data)
    return output.decode("utf-8", errors="replace") if output is not None else None


def _git_root(project: Path, deadline: Deadline) -> Optional[Path]:
    output = _git(project, ["rev-parse", "--show-toplevel"], deadline)
    if not output:
        return None
    root = Path(output.splitlines()[0].strip())
    return root if root.is_dir() else None


def _history(output: bytes) -> Dict[str, int]:
    history: Dict[str, int] = {}
    timestamp: Optional[int] = None
    first_path = False
    records = output.split(b"\0")
    for index, record in enumerate(records):
        if not record:
            continue
        next_record = records[index + 1] if index + 1 < len(records) else b""
        if record.isdigit() and next_record.startswith(b"\n"):
            timestamp = int(record)
            first_path = True
            continue
        if timestamp is None:
            continue
        if first_path:
            if not record.startswith(b"\n"):
                timestamp = None
                continue
            record = record[1:]
        first_path = False
        path = os.fsdecode(record)
        history[path] = max(timestamp, history.get(path, timestamp))
    return history


def _has_glob(anchor: str) -> bool:
    return any(char in anchor for char in "*?[")


def _glob_match(pattern: str, path: str) -> bool:
    pattern_parts = tuple(pattern.split("/"))
    path_parts = tuple(path.split("/"))

    @lru_cache(maxsize=None)
    def match(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        part = pattern_parts[pattern_index]
        if part == "**":
            return (match(pattern_index + 1, path_index) or
                    (path_index < len(path_parts) and match(pattern_index, path_index + 1)))
        return (path_index < len(path_parts) and
                fnmatch.fnmatchcase(path_parts[path_index], part) and
                match(pattern_index + 1, path_index + 1))

    return match(0, 0)


def _glob_covers(pattern: str, path: str) -> bool:
    parts = path.split("/")
    return any(_glob_match(pattern, "/".join(parts[:end])) for end in range(1, len(parts) + 1))


def _matches(anchor: str, path: str) -> bool:
    if path == anchor or path.startswith(anchor.rstrip("/") + "/"):
        return True
    return _has_glob(anchor) and _glob_covers(anchor, path)


def _pathspecs(anchors: Iterable[str]) -> List[str]:
    # A plain pathspec's "**/x" misses a root-level x; ":(glob)" matches it. The union is a
    # superset of _matches, which filters the history afterwards.
    specs = set()
    for anchor in anchors:
        specs.add(anchor)
        if _has_glob(anchor):
            specs.add(":(glob)" + anchor)
    return sorted(specs)


def _latest(history: Dict[str, int], anchor: Anchor) -> Optional[int]:
    commits = [timestamp for path, timestamp in history.items() if _matches(anchor.value, path)]
    return max(commits) if commits else None


def _literal_prefix(pattern: str) -> Tuple[str, ...]:
    prefix: List[str] = []
    for part in pattern.split("/"):
        if any(char in part for char in "*?["):
            break
        prefix.append(part)
    return tuple(prefix)


def _can_descend(pattern: Tuple[str, ...], index: int, name: str) -> bool:
    if "**" in pattern[:index + 1]:
        return True
    if index >= len(pattern):
        return False
    return fnmatch.fnmatchcase(name, pattern[index])


def _anchor_exists(root: Path, anchor: Anchor, deadline: Deadline) -> bool:
    try:
        if (root / anchor.value).exists():
            return True
    except OSError:
        pass
    if not _has_glob(anchor.value):
        return False
    pattern = tuple(anchor.value.split("/"))
    prefix = _literal_prefix(anchor.value)
    base = root.joinpath(*prefix)
    # os.path.isdir, not Path.is_dir: below an unreadable directory Path.is_dir
    # raises PermissionError (Python 3.12), and one such anchor emptied the report.
    if not os.path.isdir(base):
        return False
    pending = [(base, len(prefix))]
    while pending:
        current, pattern_index = pending.pop()
        if deadline.remaining() <= 0:
            raise BudgetExceeded()
        try:
            with os.scandir(current) as scanner:
                entries = list(scanner)
        except OSError:
            continue
        directories = []
        for entry in entries:
            relative = os.path.relpath(entry.path, str(root)).replace(os.sep, "/")
            if ".git" in relative.split("/"):
                continue
            if _glob_match(anchor.value, relative) and os.path.exists(entry.path):
                return True
            if entry.is_dir(follow_symlinks=False) and _can_descend(pattern, pattern_index, entry.name):
                directories.append((Path(entry.path), pattern_index + 1))
        pending.extend(reversed(directories))
    return False


def _commit_lookup(root: Path, refs: Iterable[str], deadline: Deadline) -> Dict[str, Tuple[str, int]]:
    terms = ["HEAD", *sorted(set(refs))]
    if len(terms) == 1:
        return {}
    output = _git_bytes(root, ["cat-file", "--batch"], deadline,
                        ("\n".join(terms) + "\n").encode("utf-8"))
    if output is None:
        return {}
    commits: Dict[str, Tuple[str, int]] = {}
    position = 0
    for term in terms:
        header_end = output.find(b"\n", position)
        if header_end < 0:
            break
        header = output[position:header_end].split()
        position = header_end + 1
        if len(header) == 2:  # "<ref> missing" or "<ref> ambiguous": no body follows
            continue
        if len(header) != 3:
            break
        try:
            size = int(header[2])
        except ValueError:
            break
        content = output[position:position + size]
        position += size
        if output[position:position + 1] == b"\n":
            position += 1
        if header[1] != b"commit":
            continue
        try:
            committer = next(line for line in content.split(b"\n") if line.startswith(b"committer "))
            timestamp = int(committer.rsplit(b" ", 2)[1])
        except (StopIteration, ValueError, IndexError):
            continue
        commits[term] = (header[0].decode("ascii"), timestamp)
    return commits


def _date(timestamp: Optional[float]) -> str:
    if timestamp is None:
        return "unknown"
    return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()


def _baseline(memory: Memory) -> Optional[Anchor]:
    return next((anchor for anchor in memory.anchors if anchor.kind == "commit"), None)


def _stale_line(memory: Memory, root: Path, history: Dict[str, int],
                baseline_histories: Dict[str, Dict[str, int]], commits: Dict[str, Tuple[str, int]],
                deadline: Deadline) -> Optional[str]:
    path_anchors = [anchor for anchor in memory.anchors if anchor.kind == "path"]
    if not path_anchors:
        return None
    baseline = _baseline(memory)
    memory_history = history
    if baseline is not None:
        anchored = commits.get(baseline.value)
        if anchored is None:
            return f"⚠STALE {memory.path.name}: anchor commit {baseline.value} not in this repository"
        memory_history = baseline_histories.get(anchored[0], {})
    for anchor in path_anchors:
        if deadline.remaining() <= 0:
            raise BudgetExceeded()
        latest = _latest(memory_history, anchor)
        if not _anchor_exists(root, anchor, deadline):
            return (f"⚠STALE {memory.path.name}: {anchor.display} changed {_date(latest)} "
                    f"(memory {_date(memory.modified)})")
        if baseline is not None:
            if latest is not None:
                return (f"⚠STALE {memory.path.name}: {anchor.display} changed {_date(latest)} "
                        f"(memory {_date(memory.modified)})")
        elif latest is not None and latest > memory.modified:
            return (f"⚠STALE {memory.path.name}: {anchor.display} changed {_date(latest)} "
                    f"(memory {_date(memory.modified)})")
    return None


def _staleness(memories: Sequence[Memory], project: Path, deadline: Deadline) -> List[str]:
    if not any(anchor.kind == "path" for memory in memories for anchor in memory.anchors):
        return []
    root = _git_root(project, deadline)
    if root is None:
        return []
    default_path_anchors = sorted({anchor.value for memory in memories if _baseline(memory) is None
                                   for anchor in memory.anchors if anchor.kind == "path"})
    history: Dict[str, int] = {}
    if default_path_anchors:
        output = _git_bytes(root, ["log", "--name-only", "-z", "--format=%ct", "--no-renames", "--",
                                   *_pathspecs(default_path_anchors)], deadline)
        if output is None:
            return []
        history = _history(output)
    commit_refs = {anchor.value for memory in memories for anchor in memory.anchors
                   if anchor.kind == "commit" and any(candidate.kind == "path"
                                                    for candidate in memory.anchors)}
    commits = _commit_lookup(root, commit_refs, deadline)
    baseline_paths: Dict[str, set] = {}
    for memory in memories:
        baseline = _baseline(memory)
        if baseline is None or baseline.value not in commits:
            continue
        oid = commits[baseline.value][0]
        baseline_paths.setdefault(oid, set()).update(
            anchor.value for anchor in memory.anchors if anchor.kind == "path")
    baseline_histories: Dict[str, Dict[str, int]] = {}
    for oid, paths in sorted(baseline_paths.items()):
        output = _git_bytes(root, ["log", f"{oid}..HEAD", "--name-only", "-z", "--format=%ct",
                                   "--no-renames", "--", *_pathspecs(paths)], deadline)
        if output is None:
            return []
        baseline_histories[oid] = _history(output)
    lines: List[str] = []
    for memory in memories:
        line = _stale_line(memory, root, history, baseline_histories, commits, deadline)
        if line is not None:
            lines.append(line)
    return lines


def _review(memories: Sequence[Memory], days: int, deadline: Deadline) -> List[str]:
    cutoff = time.time() - days * 86400
    lines: List[str] = []
    for memory in memories:
        if deadline.remaining() <= 0:
            raise BudgetExceeded()
        if _baseline(memory) is not None and not any(anchor.kind == "path" for anchor in memory.anchors):
            lines.append(f"⚠REVIEW {memory.path.name}: commit anchor without paths")
            continue
        if memory.anchors:
            continue
        if memory.modified >= cutoff:
            continue
        age = int((time.time() - memory.modified) // 86400)
        lines.append(f"⚠REVIEW {memory.path.name}: unanchored memory {_date(memory.modified)} "
                     f"({age} days old)")
    return lines


def _incomplete(memory_dir: Path, project_dir: Path, budget: float, review: bool) -> str:
    retry = ("python3 ~/.claude/scripts/memory-staleness.py " +
             shlex.quote(str(memory_dir)) + " " + shlex.quote(str(project_dir)))
    if review:
        retry += " --review"
    return f"⚠STALE-CHECK incomplete: {budget:g}s budget exceeded; run {retry} --budget 30"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("memory_dir", type=Path)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_SECONDS)
    args = parser.parse_args(argv)
    if args.days < 0 or args.budget < 0:
        parser.error("--days and --budget must be non-negative")

    deadline = Deadline(args.budget)
    try:
        memories = _memories(args.memory_dir)
        lines = (_review(memories, args.days, deadline) if args.review
                 else _staleness(memories, args.project_dir, deadline))
    except BudgetExceeded:
        lines = [_incomplete(args.memory_dir, args.project_dir, args.budget, args.review)]
    except (OSError, ValueError, re.error):
        return 0
    if lines:
        sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
