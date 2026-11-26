"""doc-align.py's mutations, loaded into test_self_tests_can_fire.py's MUTATIONS.

Each one removes one guard of the dated-row report (apply/sync name a row they
rewrote when it carries a YYYY-MM-DD, and never change the date), or of the
no-mode refusal, and the script's --self-test must turn red. The self-test
drives main() on fixture repositories built in a temporary directory; nothing
reads the real docs.

The no-mode refusal is main()'s own check, not argparse's: `mode` takes
nargs="?" so --self-test can stand alone, which leaves argparse enforcing
nothing. Without the check a bare run exits 0 having checked nothing.

Not mutated, and why: the drift search and the rewrite itself (older than the
self-test, and exercised by every case, so a broken rewrite fails all of them
at once rather than one guard).
"""

from __future__ import annotations

S = "configs/scripts/doc-align.py"

MUTATIONS: dict[str, list[tuple[str, str, str]]] = {S: [
    ("the dated-row report is never printed",
     "        if dated:\n",
     "        if False:\n"),
    ("the report prints when no dated row was rewritten",
     "        if dated:\n",
     "        if True:\n"),
    ("the report fails the run, though it is report-only",
     '                print(f"  {file}:{line}  {row}")\n        return 0\n',
     '                print(f"  {file}:{line}  {row}")\n            return 1\n        return 0\n'),
    ("no date is ever recognised",
     'DATE_RE = re.compile(r"(?<!\\d)\\d{4}-\\d{2}-\\d{2}(?!\\d)")',
     'DATE_RE = re.compile(r"$^")'),
    ("a date inside a longer digit run counts",
     'DATE_RE = re.compile(r"(?<!\\d)\\d{4}-\\d{2}-\\d{2}(?!\\d)")',
     'DATE_RE = re.compile(r"\\d{4}-\\d{2}-\\d{2}")'),
    ("word boundaries instead of digit boundaries — a timestamp is missed",
     'DATE_RE = re.compile(r"(?<!\\d)\\d{4}-\\d{2}-\\d{2}(?!\\d)")',
     'DATE_RE = re.compile(r"\\b\\d{4}-\\d{2}-\\d{2}\\b")'),
    ("a date-valued fact counts as its own row's date",
     'around = content[row_start:m.start(1)] + " " + content[m.end(1):row_end]',
     "around = content[row_start:row_end]"),
    ("the row named is where the match starts, not where the value is",
     '"row_line": content.count("\\n", 0, m.start(1)) + 1,',
     '"row_line": content.count("\\n", 0, m.start()) + 1,'),
    ("a row with two fixes is named twice",
     'if not d["dated"] or d["row_line"] in seen:',
     'if not d["dated"]:'),
    ("every rewritten row is named, dated or not",
     'if not d["dated"] or d["row_line"] in seen:',
     'if d["row_line"] in seen:'),
    ("a run with no mode is not refused",
     '    if args.mode is None:\n        ap.error("a mode is required")\n',
     ""),
    ("a run with no mode exits 0 instead of 2",
     '        ap.error("a mode is required")\n',
     "        return 0\n"),
]}

NO_OP_CONTROLS: dict[str, list[tuple[str, str, str]]] = {S: [
    ("a comment reworded",
     "# Report-only: the fix stands and the exit stays 0.",
     "# Report only: the fix stands, and the exit stays 0."),
]}
