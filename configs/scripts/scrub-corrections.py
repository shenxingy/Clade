#!/usr/bin/env python3
r"""
scrub-corrections.py — remove credentials already written into the correction logs.

The hooks now redact before writing, but that fix is prospective: it cannot
touch what is already on disk. This is the retrospective half.

Why it is a script and not a one-off command
--------------------------------------------
The filed item named two files. The secret was in three, because two of them
were `.bak-*` copies made by earlier maintenance passes — a scrub that walks
only the files someone remembered leaves the credential sitting in a snapshot
of the same directory at the same mode. Sweeping the whole directory is the
part that has to be repeatable, so it is code.

It also has to scan the DECODED record, which is the second thing a one-off
command gets wrong. A JSONL file stores a newline as the two characters `\` and
`n`, so a credential that began a line inside a captured prompt is preceded on
disk by the letter `n` — a word character, so `\b` does not match and the
pattern misses it. Measured on the real file: the same 44-character key
appeared twice on one line and a raw scan saw one of them. Scanning the decoded
strings and then replacing every literal occurrence in the raw line is what
makes the count come out right. The live hook path is unaffected: it redacts
before encoding, where the newline is still a newline.

Default is a read-only report. `--apply` rewrites, and only then.

    python3 configs/scripts/scrub-corrections.py               # report
    python3 configs/scripts/scrub-corrections.py --apply       # rewrite
    python3 configs/scripts/scrub-corrections.py --dir PATH    # elsewhere
    python3 configs/scripts/scrub-corrections.py FILE [FILE…]  # named files only

Named files exist because the same credential turned up outside the directory
this was written for, and not everything it turned up in should be rewritten by
this tool. A content-addressed snapshot under file-history/ is named after a
hash of its own bytes; editing it desynchronises the name from the content. A
session transcript is the harness's own resumable state. Both are reported and
left alone deliberately — for a leaked key the remedy is rotation, after which
every copy is inert, and that is the owner's action, not this script's.

Stdlib only, like everything else CI runs from configs/scripts/.

A redacted credential must still be treated as leaked: it was readable for as
long as it sat there. This prints the masked shape and provenance of every hit
so the owner can find the key in the issuing dashboard and rotate it. Rotation
is the actual remedy; this only stops the bleeding.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from redact import redact, scan  # noqa: E402

DEFAULT_DIR = Path.home() / ".claude" / "corrections"

# Files whose bytes are structured records rather than prose. Everything in the
# directory is swept regardless; this only decides how a hit is reported.
_RECORD_SUFFIXES = {".jsonl", ".json"}


def _mask(secret: str) -> str:
    """Enough to identify the key in a dashboard, not enough to use it."""
    if len(secret) <= 12:
        return f"<{len(secret)} chars>"
    return f"{secret[:8]}…{secret[-4:]} ({len(secret)} chars)"


def _secrets_in(line: str) -> tuple[list, list[str]]:
    """Every credential on this line, however it happens to be escaped.

    Returns (hits_for_reporting, distinct_secret_strings). The raw scan finds
    what is plainly there; the decoded scan finds what JSON escaping hid. A
    secret is reported once but replaced at every literal occurrence.
    """
    import json

    hits = list(scan(line))
    secrets: list[str] = [line[h.start:h.end] for h in hits]

    try:
        record = json.loads(line)
    except Exception:
        return hits, list(dict.fromkeys(secrets))

    stack = [record]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            for hit in scan(node):
                value = node[hit.start:hit.end]
                if value not in secrets:
                    secrets.append(value)
                    hits.append(hit)
        elif isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)

    return hits, list(dict.fromkeys(secrets))


def _provenance(line: str) -> str:
    """Best-effort record context, without parsing arbitrary JSON deeply."""
    import json

    try:
        rec = json.loads(line)
    except Exception:
        return ""
    bits = [str(rec[k]) for k in ("timestamp", "date", "project") if k in rec]
    return "  ".join(bits)


def sweep(targets: list[Path], apply: bool, label: str) -> int:
    total_hits = 0
    files_touched = 0

    for path in targets:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"  {path.name}: unreadable ({exc})")
            continue

        lines = text.splitlines(keepends=True)
        kinds: Counter[str] = Counter()
        out: list[str] = []
        changed = False

        for lineno, line in enumerate(lines, 1):
            hits, secrets = _secrets_in(line)
            if not secrets:
                out.append(line)
                continue
            masked_line = line
            for hit, secret in zip(hits, secrets):
                occurrences = masked_line.count(secret)
                kinds[hit.kind] += occurrences
                total_hits += occurrences
                where = "" if occurrences == 1 else f"  ×{occurrences} on this line"
                print(
                    f"  {path.name}:{lineno}  {hit.kind}  "
                    f"{_mask(secret)}{where}"
                )
                prov = _provenance(line) if path.suffix in _RECORD_SUFFIXES else ""
                if prov:
                    print(f"      from: {prov}")
                masked_line = masked_line.replace(secret, f"<redacted:{hit.kind}>")
            out.append(masked_line)
            changed = True

        if not changed:
            continue
        files_touched += 1
        mode = oct(path.stat().st_mode)[-3:]
        if apply:
            # Same-directory temp + atomic replace: a partial write here would
            # corrupt the very history the correction system reasons from.
            tmp = path.with_name(f".{path.name}.scrub.{os.getpid()}")
            tmp.write_text("".join(out), encoding="utf-8")
            os.chmod(tmp, path.stat().st_mode & 0o777)
            os.replace(tmp, path)
            print(f"  → rewrote {path.name} ({sum(kinds.values())} masked, mode {mode})")
        else:
            print(f"  → would rewrite {path.name} ({sum(kinds.values())} to mask, mode {mode})")

    print()
    if not total_hits:
        print(f"clean: no credentials found {label}")
        return 0

    verb = "masked" if apply else "found"
    print(f"{total_hits} credential(s) {verb} across {files_touched} file(s).")
    if not apply:
        print("Nothing was written. Re-run with --apply to rewrite.")
    else:
        print(
            "ROTATE THESE KEYS. Masking removes them from disk; it does not\n"
            "un-expose them. Anything listed above was readable for as long as\n"
            "it sat in a group-readable file."
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("files", nargs="*", type=Path, help="specific files to scrub")
    ap.add_argument("--dir", type=Path, default=None)
    ap.add_argument("--apply", action="store_true", help="rewrite files in place")
    args = ap.parse_args()

    if args.files and args.dir:
        print("pass named files or --dir, not both")
        return 2

    if args.files:
        missing = [f for f in args.files if not f.is_file()]
        if missing:
            for f in missing:
                print(f"no such file: {f}")
            return 1
        targets, label = sorted(args.files), f"in {len(args.files)} named file(s)"
        what = ", ".join(f.name for f in targets)
    else:
        directory = args.dir or DEFAULT_DIR
        if not directory.is_dir():
            print(f"no such directory: {directory}")
            return 1
        targets = [p for p in sorted(directory.rglob("*")) if p.is_file()]
        label = what = f"under {directory}"

    print(f"scrubbing {what}{'' if args.apply else '  (dry run)'}\n")
    return sweep(targets, args.apply, label)


if __name__ == "__main__":
    raise SystemExit(main())
