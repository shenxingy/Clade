"""Ask every --self-test whether it can still go red.

This repository has now shipped SIX instruments that could not fire, and the
failure mode is always the same: a clean run and a broken run print the same
sentence, so the gate reads as evidence while measuring nothing.

  red-phase-audit.py     reported 0% because the harness could not fire
  workflow-scorecard.py  matched the `>/` of `2>/dev/null`, so every session
                         reported zero polls and it read as discipline; its
                         main mode had no self-test at all until 2026-10-23
  check-skill-contracts  accepted the bare word, and flag names are common
                         English, so /brief passed with its --all handling gone
  generate_hero.py       `for lic in (...): assert lic not in SAFE_LICENSES` is
                         vacuously true when the tuple is EMPTY — deleting the
                         entire licence allowlist still printed PASSED
  cognitive_load.py      fenced its fixture under a heading the fixture already
                         contained, so it asserted on an empty section
  check-sibling-facts    exercised only the extractor; three mutations of the
                         survivor search all left it green

Each entry below removes ONE guard and requires the script's own --self-test to
notice. A mutation that stays green is not a style complaint: it names a
property the instrument claims and does not check.

Adding a self-test to a script means adding its mutations here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# workflow-scorecard.py's three verdict blocks, verbatim, so one mutation can
# reorder them. Spelled out rather than sliced from the file: an anchor that
# moves must fail loudly here, not silently match something else.
_SCORECARD_STRAGGLER = (
    '    if stats["outlived_frac"] >= _OUTLIVED_FLAG:\n'
    "        found.append(\n"
    '            f"straggler, pipeline() or finer units — one agent outlived its "\n'
    "            f\"siblings for {stats['outlived_frac'] * 100:.0f}% of the makespan\"\n"
    "        )\n"
)
_SCORECARD_SERIAL = (
    '    if stats["serial_frac"] >= _SERIAL_FLAG:\n'
    '        stage = stats.get("longest_serial") or {}\n'
    "        found.append(\n"
    "            f\"serial stage {stage.get('name', '?')} alone \"\n"
    "            f\"{stage.get('alone_s', 0.0) / 60:.0f} min, shorten or overlap it\"\n"
    "        )\n"
)
_SCORECARD_LOW_UTIL = (
    '    if stats["util_vs_peak"] < _UTIL_FLOOR:\n'
    "        found.append(\n"
    "            f\"low util, not enough queued work to keep the {stats['peak']} \"\n"
    '            f"slots it reached busy"\n'
    "        )\n"
)

# script -> [(what the mutation removes, exact source before, exact source after)]
MUTATIONS: dict[str, list[tuple[str, str, str]]] = {
    "configs/scripts/artifact-lint.py": [
        ("the headline-is-a-claim check",
         "if h1 and argued and not is_claim(h1[0]):",
         "if False:"),
        ("a register's obligation to state what it does not cover",
         'if (argued or kind == "reference") and not _LIMITS.search(roles):',
         "if argued and not _LIMITS.search(roles):"),
        ("the pinned, position-aware index a long page owes its reader",
         "if words > _LONG_PAGE and p.anchors >= 5:",
         "if False:"),
        ("the half of that check that asks where the reader is",
         'follows = bool(re.search(r"IntersectionObserver|aria-current|scroll-?spy|:target", html, re.I))',
         "follows = True"),
        ("the external-reference check",
         "if p.ext:",
         "if False:"),
        ("the first-screen date check",
         'if kind != "landing" and not _ASOF.search(text[:1800]):',
         "if False:"),
        ("the head-standard check",
         "if missing_head:",
         "if False:"),
        ("the categorical-palette ceiling",
         "if len(palette) > 8:",
         "if len(palette) > 80:"),
        ("an SVG <title> kept out of the page title",
         "if self._svg_depth == 0:\n                self._in_title = True",
         "if True:\n                self._in_title = True"),
        ("the work-log header check",
         'if missing:\n            add("worklog-header"',
         'if False:\n            add("worklog-header"'),
        ("the Chinese claim-heading branch",
         "return len(_CJK.findall(h)) >= 6 and bool(_CLAIM_ZH.search(h))",
         "return True"),
        ("the single-theme declaration",
         'single_theme = "artifact:single-theme" in html',
         "single_theme = False"),
        ("section roles read from in-page index links",
         'roles = all_heads + " | " + " ".join(p.role_hints) + " | " + " ".join(_norm(t) for t in p.nav_text)',
         'roles = all_heads + " | " + " ".join(p.role_hints)'),
        ("section roles read from ids and classes",
         "if hint:\n                self.role_hints.append(",
         "if False:\n                self.role_hints.append("),
        ("the missing-caption check",
         "if p.figures_without_caption:",
         "if False:"),
        ("the wall-of-tables check",
         "if n_tables >= 6 and n_figs == 0:",
         "if False:"),
        ("the deck check",
         "if deck_len < 35 and total < 60 and not _DECK_HINT.search(",
         "if False and not _DECK_HINT.search("),
        ("the why-section check",
         'if kind in ("finding", "status", "rca", "decision") and not _WHY.search(roles):',
         "if False:"),
        ("the method-section check",
         "if argued and not _METHOD.search(roles):",
         "if False:"),
        ("the token-stack font exemption",
         'if "," not in v and "var(" not in v and "inherit" not in v]',
         'if "," not in v]'),
        ("the per-figure palette opt-out",
         '"ignore_palette": "palette" in a.get("data-artifact-lint", "")}',
         '"ignore_palette": False}'),
        ("survey owner aliasing",
         "who = aliases.get(who, who)",
         "who = who"),
        ("survey owner-prefix stripping",
         'who = _PREFIX.sub("", who)',
         "who = who"),
    ],
    "configs/scripts/check-sibling-facts.py": [
        ("the per-fact exemption becomes global",
         "if rel in wanted[fact]:",
         "if rel in {f for fs in wanted.values() for f in fs}:"),
        ("the word boundary around a fact",
         'probes = {fact: re.compile(r"(?<![\\w-])" + re.escape(fact) + r"(?![\\w-])", re.I)',
         "probes = {fact: re.compile(re.escape(fact))"),
        ("case-insensitive survivor search",
         're.escape(fact) + r"(?![\\w-])", re.I)',
         're.escape(fact) + r"(?![\\w-])")'),
        ("the git failure check",
         "if proc.returncode:",
         "if False:"),
        ("the diff's own additions are chased again",
         'if fact in added.get(f, ""):',
         "if False:"),
        ("a deleted file inherits the previous file's name",
         'current = tail[2:] if tail.startswith("b/") else ""',
         'current = tail[2:] if tail.startswith("b/") else current'),
    ],
    "configs/scripts/blog/cognitive_load.py": [
        ("noise stripping before the section split",
         "rows = measure(split_sections(strip_noise(text)), jargon)",
         "rows = measure(split_sections(text), jargon)"),
        ("CJK from the word pattern",
         '_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\'’-]*|[\\u4e00-\\u9fff\\u3040-\\u30ff]")',
         '_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\'’-]*")'),
        ("word boundaries from the jargon match",
         'present = {term for term in jargon\n                   if re.search(r"(?<![\\w-])" + re.escape(term) + r"(?![\\w-])", lowered)}',
         "present = {term for term in jargon if term in lowered}"),
        ("the fenced-code stripper",
         'text = re.sub(r"```.*?```", " ", text, flags=re.S)',
         "text = text"),
        ("the short-section floor",
         "if count < MIN_SCORABLE_WORDS:",
         "if False:"),
    ],
    "configs/scripts/load_untrusted_root.py": [
        ("symlink refusal",
         'flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)',
         "flags = os.O_RDONLY | os.O_NONBLOCK"),
        ("nonce freshness",
         "nonce = nonce or secrets.token_hex(16)",
         'nonce = nonce or "a" * 32'),
        ("the size cap",
         "if st.st_size > max_bytes:",
         "if False:"),
        ("the regular-file check",
         "if not _stat.S_ISREG(st.st_mode):",
         "if False:"),
        ("the strong injection patterns",
         "    strong = [src for src, rx in _STRONG_RX if rx.search(text)]",
         "    strong = []"),
        ("the whitespace bound on the system: pattern",
         r'r"^[ \t]{0,8}(?:system|assistant)\s*:",',
         r'r"^\s*(?:system|assistant)\s*:",'),
    ],
    "configs/scripts/blog/lint_prose.py": [
        ("the capsule-opener set the spec names",
         'TRANSITION_WORDS = sorted(CAPSULE_OPENERS | {t.lower() for t in TRANSITION_WORDS',
         'TRANSITION_WORDS = sorted(set() | {t.lower() for t in TRANSITION_WORDS'),
        ("re.MULTILINE from the key-insight tell",
         "    re.I | re.M,   # without re.M, `^` meant start-of-DOCUMENT, so the tell was",
         "    re.I,          # without re.M, `^` meant start-of-DOCUMENT, so the tell was"),
        ("paragraph-scoped Here counting",
         'heres = sum(1 for para in re.split(r"\\n\\s*\\n", prose)',
         'heres = sum(1 for para in re.split(r"\\n", prose)'),
        ("the listicle precondition",
         "if first_list and listicle:",
         "if first_list:"),
        ("three signals leave the advisory bucket",
         'ADVISORY = {\n    "paragraph_shape_flatness",\n    "paragraph_sentence_flatness",\n    "opening_word_repetition",\n    "symmetric_list_bloat",\n}',
         'ADVISORY = {\n    "symmetric_list_bloat",\n}'),
    ],
    "configs/scripts/blog/blog_render.py": [
        ("entity resolution before counting words",
         "    text = _html.unescape(text)",
         "    text = text"),
        ("fence awareness in the h1 strip",
         'elif not fenced and not dropped and re.match(r"#\\s+\\S", stripped):',
         'elif not dropped and re.match(r"#\\s+\\S", stripped):'),
        ("single-escaping of link URLs",
         "lambda m: f'<a href=\"{m.group(2)}\">{m.group(1)}</a>', out)",
         "lambda m: f'<a href=\"{_html.escape(m.group(2), quote=True)}\">{m.group(1)}</a>', out)"),
        ("fence detection in the fallback converter",
         'if line.startswith("```") or line.startswith("~~~"):',
         'if line.startswith("\\u0000"):'),
        ("the nested-list warning",
         '"nested list": re.compile(r"^(?:\\t| {2,})(?:[-*+]|\\d+[.)])\\s+", re.M),',
         '"nested list": re.compile(r"^(?:\\t| {99,})(?:[-*+]|\\d+[.)])\\s+", re.M),'),
    ],
    "configs/scripts/blog/blog_preflight.py": [
        ("CJK from the word pattern Gate 5 audits",
         '_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\'’-]*|[\\u4e00-\\u9fff\\u3040-\\u30ff]")',
         '_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\'’-]*")'),
        ("the mandatory-agent check",
         "        return _blocked(\"1 capability discovery\",",
         "        return _passed(\"1 capability discovery\","),
        ("the hero requirement",
         'missing.append("hero image (" + "/".join(HERO_NAMES) + ")")',
         "pass"),
        ("the BLOCKING: true branch",
         'if verdict.lower() == "true":',
         "if False:"),
        ("the canonical requirement",
         "problems.append(\"<link rel=canonical> is not set\")",
         "pass"),
        ("the og:image requirement",
         'problems.append("og:image is not set — the social-preview asset is load-bearing")',
         "pass"),
        ("the halt-on-first-block rule",
         'if results[-1]["status"] == "block":',
         "if False:"),
        ("JSON-LD required-field validation",
         'problems.append(f"BlogPosting is missing required field {field!r}")',
         "pass"),
    ],
    "configs/scripts/blog/generate_hero.py": [
        ("the GIF refusal",
         'if ctype == "image/gif":',
         "if False:"),
        ("the licence allowlist",
         'SAFE_LICENSES = ("cc0", "pdm", "by", "by-sa")',
         "SAFE_LICENSES = ()"),
        ("non-commercial licences enter the allowlist",
         'SAFE_LICENSES = ("cc0", "pdm", "by", "by-sa")',
         'SAFE_LICENSES = ("cc0", "pdm", "by", "by-sa", "by-nc")'),
        ("aspect-ratio weighting",
         "fit = max(0.0, 1.0 - abs(ratio - TARGET_RATIO) / TARGET_RATIO)",
         "fit = 1.0"),
        ("relevance weighting",
         "relevance = hits / max(len(query_terms), 1)",
         "relevance = 1.0"),
        ("source authority",
         'authority = next((v for k, v in SOURCE_AUTHORITY.items() if k in provider), 0.6)',
         "authority = 1.0"),
        ("query relaxation",
         "    for i in range(len(terms)):",
         "    for i in range(1):"),
        ("stopword filtering in the query",
         "if w not in STOPWORDS and len(w) > 2]",
         "if len(w) > 2]"),
    ],
    # The four below were the entire `known_gap` until 2026-09-15: every script
    # CI runs under the banner "can the harness go red?", exempted from the file
    # that asks exactly that. Two of them needed work before a mutation could
    # reach them, and both gaps were in the guard that mattered most.
    "configs/scripts/red-phase-audit.py": [
        ("the requirement that the added test PASSED at its base commit",
         "fired = total > 0 and passed > 0",
         "fired = total > 0"),
        ("the fire decision entirely",
         "fired = total > 0 and passed > 0",
         "fired = False"),
        # These two guards are the reason the script is trustworthy: its first
        # version passed an unrecognised argument to pytest, so every commit
        # reported 0 passed and the 0% fire rate read as good news. Inline in
        # run_at_base they were unreachable from --self-test and BOTH could be
        # deleted with it staying green. classify_pytest_output() exists so the
        # self-test can drive them directly.
        ("the pytest usage-error guard",
         'if "unrecognized arguments" in out or "usage:" in out.lower()[:400]:',
         "if False:"),
        ("the no-result-line guard",
         'if not re.search(r"\\d+ (passed|failed|error|skipped)", out):',
         "if False:"),
        ("the healthy-run passed-count parse",
         'm_pass = re.search(r"(\\d+) passed", out)',
         "m_pass = None"),
    ],
    "configs/scripts/workflow-scorecard.py": [
        ("the repeat requirement — the FIRST status read becomes a poll",
         "if seen[key] > 1:",
         "if seen[key] > 0:"),
        ("the poll counter",
         "polls += 1",
         "polls += 0"),
        # The main mode had NO self-test until 2026-10-23: `== 99` on the
        # lone-agent check and `if False:` on the straggler verdict both still
        # printed PASSED. Everything below goes through scan_workflow().
        ("per-message usage keying — each record counted as an API call (the 1.9x double count)",
         'key = message.get("id") or f"record-{number}"',
         'key = f"record-{number}"'),
        ("output as the max over one message's records — streamed partials summed",
         'call.output = max(call.output, usage.get("output_tokens") or 0)',
         'call.output += usage.get("output_tokens") or 0'),
        ("the running-set check that credits lone time to an agent",
         "if len(running) == 1:",
         "if len(running) == 99:"),
        ("the serial/outlived test — every lone agent called a straggler",
         'kind = "outlived" if overlapped else "serial"',
         'kind = "outlived"'),
        ("the verdict order — straggler listed after low util",
         _SCORECARD_STRAGGLER + _SCORECARD_SERIAL + _SCORECARD_LOW_UTIL,
         _SCORECARD_SERIAL + _SCORECARD_LOW_UTIL + _SCORECARD_STRAGGLER),
        ("every verdict that holds — only the first one kept",
         "        return found\n",
         "        return found[:1]\n"),
        # The thresholds are held from both sides by the wf_edge_hit run (exactly
        # 0.15 and 0.25) and wf_edge_miss (0.145 and 0.245). Bracketing them
        # loosely let 0.10, 0.16, 0.01 and 0.45 all stay green.
        ("the 0.15 straggler threshold, raised — an outlived share of exactly 15% goes unflagged",
         "_OUTLIVED_FLAG = 0.15",
         "_OUTLIVED_FLAG = 0.16"),
        ("the 0.15 straggler threshold, lowered — a 14.5% outlived share gets flagged",
         "_OUTLIVED_FLAG = 0.15",
         "_OUTLIVED_FLAG = 0.14"),
        ("the straggler threshold is inclusive (outlived >= 0.15)",
         'if stats["outlived_frac"] >= _OUTLIVED_FLAG:',
         'if stats["outlived_frac"] > _OUTLIVED_FLAG:'),
        ("the 0.25 serial threshold, raised — a serial share of exactly 25% goes unflagged",
         "_SERIAL_FLAG = 0.25",
         "_SERIAL_FLAG = 0.26"),
        ("the 0.25 serial threshold, lowered — a 24.5% serial share gets flagged",
         "_SERIAL_FLAG = 0.25",
         "_SERIAL_FLAG = 0.24"),
        ("the serial threshold is inclusive (serial >= 0.25)",
         'if stats["serial_frac"] >= _SERIAL_FLAG:',
         'if stats["serial_frac"] > _SERIAL_FLAG:'),
        ("the 0.55 util floor, lowered — a run at 53% of its peak reads as busy",
         "_UTIL_FLOOR = 0.55",
         "_UTIL_FLOOR = 0.5"),
        # The advice is the point of the verdict. Comparing only the text before
        # the first comma let both of these stay green.
        ("the straggler advice — pipeline() or finer units",
         'f"straggler, pipeline() or finer units — one agent outlived its "',
         'f"straggler, add more agents — one agent outlived its "'),
        ("the serial-stage advice — the misdiagnosis item (2) removed, put back",
         "f\"{stage.get('alone_s', 0.0) / 60:.0f} min, shorten or overlap it\"",
         "f\"{stage.get('alone_s', 0.0) / 60:.0f} min, use pipeline()\""),
        ("null cost for an unknown model — it is priced at zero instead",
         "return None  # unpriced, never a guess",
         "return 0.0  # unpriced, never a guess"),
        ("a sequential run gets that verdict alone",
         'if stats["peak"] <= 1:',
         "if False:"),
        ("ends before starts at one instant — back-to-back agents counted as concurrent",
         "events.sort(key=lambda event: (event[0], event[1]))",
         "events.sort(key=lambda event: (event[0], -event[1]))"),
        ("the cache-TTL gap in the long-gap miss share",
         "gap > _CACHE_TTL_S",
         "gap > 10 * _CACHE_TTL_S"),
        ("a failed agent's outcome",
         'entry["outcome"] = "failed"',
         'entry["outcome"] = "ok"'),
        ("a null result — the silent usage-limit null reads as ok",
         'entry["outcome"] = "ok" if result is not None else "null result"',
         'entry["outcome"] = "ok"'),
        ("meta.json's label wins over the journal's",
         'run.label = meta.get("description") or entry.get("label")',
         'run.label = entry.get("label") or meta.get("description")'),
        ("the <synthetic> exclusion — a usage-limit notice counted as an API call",
         'if message.get("model") == _SYNTHETIC:',
         "if False:"),
        ("fast mode priced as null — it would be billed at standard rates",
         'if not model or speed not in (None, "standard"):',
         "if not model:"),
        ("the dated-snapshot strip — a dated Haiku 4.5 snapshot id goes unpriced",
         'return _RATES.get(_SNAPSHOT_DATE.sub("", model.replace("[1m]", "")))',
         'return _RATES.get(model.replace("[1m]", ""))'),
        ("1-hour cache writes at their own rate — priced as 5-minute writes",
         'self.write_1h = (split.get("ephemeral_1h_input_tokens") or 0) if isinstance(split, dict) else 0',
         "self.write_1h = 0"),
        ("the 20k context floor of a long-gap cache miss",
         "and context > _MISS_MIN_CONTEXT",
         "and context > 0"),
        ("the half-rewritten condition of a long-gap cache miss",
         "and call.cache_create > _MISS_SHARE * context",
         "and True"),
        # The table and the summary are rendered by the self-test too.
        ("the straggler line names the agent credited with the outlived time",
         "f\"{pad} straggler: {top['name']}{phase} ran alone",
         "f\"{pad} straggler: {row['slowest_tag']}{phase} ran alone"),
        ("Largest tail names the agent credited with the outlived time",
         'culprit = (worst["top_outlived"] or {}).get("name", "one agent")',
         'culprit = worst["slowest_tag"]'),
        ("Largest tail ranks only flagged runs — an unflagged one used to suppress the line",
         'flagged = [r for r in parallel_rows if r["outlived_frac"] >= _OUTLIVED_FLAG]',
         "flagged = parallel_rows"),
        ("Largest tail ranks by minutes lost, not by fraction",
         'worst = max(flagged, key=lambda r: r["makespan_s"] * r["outlived_frac"])',
         'worst = max(flagged, key=lambda r: r["outlived_frac"])'),
        ("the Longest serial stage line",
         'staged = [r for r in parallel_rows if r["longest_serial"]]',
         "staged = []"),
        ("Longest serial stage picks the longest",
         "longest = max(staged,",
         "longest = min(staged,"),
        # The ledger and outcome checks live in scorecard_ledger.py and drive
        # main(). These remove the call from main() itself, which a check that
        # called record_ledger() directly would never see.
        ("main() records the ledger — --ledger falls through to the table",
         "    if args.ledger is not None:\n",
         "    if False:\n"),
        ("main() emits the outcome windows — --outcome falls through to the table",
         "    if args.outcome:\n        return emit_outcomes(scanned)",
         "    if False:\n        return emit_outcomes(scanned)"),
        ("main() reads the ledger back — --ledger-summary falls through to a scan",
         "    if args.ledger_summary is not None:\n",
         "    if False:\n"),
        ("the summary's flags are the verdicts' thresholds, passed from one place",
         "args.json, _OUTLIVED_FLAG, _UTIL_FLOOR)",
         "args.json, 0.25, _UTIL_FLOOR)"),
        ("--recorded-before without --ledger-summary is refused, not ignored",
         "    if args.recorded_before is not None and args.ledger_summary is None:\n        parser.error(",
         "    if False:\n        parser.error("),
        ("the scan reads the config dir it writes the ledger into",
         "    if all(configured.resolve() != root.resolve() for root in roots):\n        roots.append(configured)",
         "    if False:\n        roots.append(configured)"),
    ],
    # Split out of workflow-scorecard.py on 2026-10-23 with its self-test. That
    # self-test had no mutations here before the move.
    "configs/scripts/codex_children.py": [
        ("grandchildren — a child that delegates again is still work the parent caused",
         "        queue.extend((grandchild, level + 1) for grandchild in edges.get(thread_id, ()))\n",
         ""),
        ("the headless-only filter — interactive threads counted as `codex exec`",
         'if _source_kind(record.get("source")) != "exec":',
         "if False:"),
    ],
    # workflow-scorecard.py --ledger / --outcome. Its --self-test runs
    # workflow-scorecard.py's, whose ledger and outcome checks drive main().
    "configs/scripts/scorecard_ledger.py": [
        ("the ledger's check — an end already recorded is appended again",
         "            if run_id in batch or _key(row) in present:",
         "            if run_id in batch:"),
        ("one row per run id in one pass — a copy under a second root appended twice",
         "            batch.add(run_id)\n",
         ""),
        ("a row is a run's END — a resumed run's later end skipped as already present",
         '    return row.get("run_id"), row.get("ended_at")',
         '    return row.get("run_id"), None'),
        ("the LAST launch decides — a resumed run read as ended by its first launch",
         "        task = launches[-1][0]\n        if task not in self.notified:",
         "        task = launches[0][0]\n        if task not in self.notified:"),
        ("append, never rewrite — the file reopened for writing",
         'with path.open("a+", encoding="utf-8") as handle:',
         'with path.open("w+", encoding="utf-8") as handle:'),
        ("a fresh line after a fragment — the first new row glued onto a cut-off line",
         'fresh = "" if not existing or existing.endswith("\\n") else "\\n"',
         'fresh = ""'),
        ("a run that may still be running is not recorded",
         ".isoformat(), task\n    return None\n",
         ".isoformat(), task\n    return \"unknown\", \"\", None\n"),
        ("the 24 h quiet threshold, lowered — 23 h of quiet counts as ended",
         "_SETTLE_QUIET_S = 24 * 3600",
         "_SETTLE_QUIET_S = 22 * 3600"),
        ("the 24 h quiet threshold, raised — 25 h of quiet still counts as running",
         "_SETTLE_QUIET_S = 24 * 3600",
         "_SETTLE_QUIET_S = 26 * 3600"),
        ("a terminal task-notification ends a run",
         "lead.notified.setdefault(task_id.group(1), (status.group(1), at))",
         "pass"),
        ("blocked is not an end",
         "if task_id and status and status.group(1) in _TERMINAL:",
         "if task_id and status:"),
        ("failed is an end",
         '_TERMINAL = frozenset({"completed", "failed", "killed"})',
         '_TERMINAL = frozenset({"completed", "killed"})'),
        ("a queued_command is read — queued notifications and queued owner messages",
         "            return \"queued\", attachment.get(\"prompt\")\n        return None\n",
         "            return None\n        return None\n"),
        ("the one role check — an assistant record read as the owner",
         '    if record.get("type") == "user" and isinstance(message, dict):',
         "    if isinstance(message, dict):"),
        ("CLAUDE_CONFIG_DIR is honoured — the ledger lands in ~/.claude",
         'override = os.environ.get("CLAUDE_CONFIG_DIR", "")',
         'override = ""'),
        ("an empty CLAUDE_CONFIG_DIR means ~/.claude, not the working directory",
         "return Path(override).expanduser() if override else Path.home() / \".claude\"",
         "return Path(override).expanduser() if override is not None else Path.home() / \".claude\""),
        ("per-agent detail stays out of a ledger row",
         'kept = {key: value for key, value in row.items() if key != "agent_rows"}',
         "kept = dict(row)"),
        ("the outcome window's upper bound is inclusive — a message at exactly 6 h dropped",
         "if at <= done or at > close:",
         "if at <= done or at >= close:"),
        ("the outcome window opens when the run ends — a message typed mid-run kept",
         "if at <= done or at > close:",
         "if at > close:"),
        ("the 6-hour window, widened — a message at 6 h 1 min kept",
         "OUTCOME_WINDOW_S = 6 * 3600",
         "OUTCOME_WINDOW_S = 7 * 3600"),
        ("a tool result is the harness, not the owner",
         'if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):\n'
         "        return None",
         "if False:\n        return None"),
        ("a meta record is the harness, not the owner",
         'if record.get("isMeta") or record.get("isCompactSummary"):',
         'if record.get("isCompactSummary"):'),
        ("injected markup (a leading <) is not the owner",
         'if not typed or typed.startswith("<") or typed.startswith(_HARNESS_PREFIXES):',
         "if not typed or typed.startswith(_HARNESS_PREFIXES):"),
        ("the harness prefixes are not the owner",
         'if not typed or typed.startswith("<") or typed.startswith(_HARNESS_PREFIXES):',
         'if not typed or typed.startswith("<"):'),
        ("a queued command counts only when a human typed it",
         'if not isinstance(origin, dict) or origin.get("kind") != "human":',
         "if not isinstance(origin, dict):"),
        ("pasted blocks become [pasted]",
         'typed = _PASTED.sub("[pasted]", text).strip()',
         "typed = text.strip()"),
        ("each message once — a queued message written again as a user record",
         "        if typed in seen:\n            continue\n",
         ""),
        ("redaction — a key in an owner message printed whole",
         '"text": _mask(typed)[:_MESSAGE_CHARS],',
         '"text": typed[:_MESSAGE_CHARS],'),
        ("redact, then cut — cutting first leaves a key too short to match, head intact",
         '"text": _mask(typed)[:_MESSAGE_CHARS],',
         '"text": _mask(typed[:_MESSAGE_CHARS]),'),
        ("the 300-character cut",
         "_MESSAGE_CHARS = 300",
         "_MESSAGE_CHARS = 3000"),
        ("a run in flight gets no outcome window",
         "        if run_end(directory, lead) is None:\n            in_flight += 1",
         "        if False:\n            in_flight += 1"),
        ("a window still open is skipped, not emitted half-full",
         "if now < done + datetime.timedelta(seconds=OUTCOME_WINDOW_S):",
         "if False:"),
        ("a gone lead transcript is counted as unknowable",
         "        if lead is None:\n            gone += 1\n            continue\n",
         ""),
        ("a resumed run's earlier end gets a window — the owner's reaction to it dropped",
         "        found.append((opens, min(opens + datetime.timedelta(seconds=OUTCOME_WINDOW_S), relaunched)))",
         "        pass"),
        ("the relaunch closes the earlier end's window — a mid-run message kept",
         "min(opens + datetime.timedelta(seconds=OUTCOME_WINDOW_S), relaunched)",
         "opens + datetime.timedelta(seconds=OUTCOME_WINDOW_S)"),
        ("an earlier end opens at its own last agent stop, not at the notification",
         "    before = [stop for stop in stops if stop <= ended]",
         "    before = []"),
        ("the summary reads the LAST row per run id — a resumed run's first row kept",
         "        latest[run_id] = row",
         "        latest.setdefault(run_id, row)"),
        ("a missing ledger is said, not summarised as 0 runs",
         'text = path.read_text(encoding="utf-8")\n    except OSError:\n        return None\n',
         'text = path.read_text(encoding="utf-8")\n    except OSError:\n        return [], 0\n'),
        ("the summary's recorded-before cut",
         "        if recorded_before is not None and recorded >= recorded_before:\n            continue",
         "        if False:\n            continue"),
        ("the summary skips a row this script did not write",
         " or not isinstance(row.get(\"makespan_s\"), (int, float)):",
         ":"),
        ("the summary's parallel-only population",
         '    parallel = [row for row in rows if row.get("peak", 0) > 1]',
         "    parallel = list(rows)"),
        ("the summary's shares weighted by makespan",
         '        return sum(row[field] * row["makespan_s"] for row in parallel) / makespan if makespan else 0.0',
         "        return sum(row[field] for row in parallel) / len(parallel) if parallel else 0.0"),
        ("the summary counts a run ON the outlived flag",
         '"outlived_flagged": sum(row["outlived_frac"] >= outlived_flag for row in parallel),',
         '"outlived_flagged": sum(row["outlived_frac"] > outlived_flag for row in parallel),'),
        ("the summary counts a run ON the merged-tail flag",
         '"tail_flagged": sum(row["tail_alone"] >= outlived_flag for row in parallel),',
         '"tail_flagged": sum(row["tail_alone"] > outlived_flag for row in parallel),'),
        ("the summary does not count a run ON the util floor",
         '"low_util": sum(row["util_vs_peak"] < util_floor for row in parallel),',
         '"low_util": sum(row["util_vs_peak"] <= util_floor for row in parallel),'),
    ],
    "configs/scripts/check-skill-contracts.py": [
        # The historical bug itself. It stayed green here until the bad-skill
        # fixture was given the bare word to match on — a control that cannot
        # fail on the defect the gate was written for is not a control.
        ("the literal --flag requirement (the original bare-word bug)",
         'if f"--{flag}" not in body:',
         "if flag not in body:"),
        ("the flag check entirely",
         'if f"--{flag}" not in body:',
         "if False:"),
        ("the front-matter path existence check",
         "if not (directory / rel).exists():",
         "if False:"),
    ],
    "configs/scripts/check-runnable-paths.py": [
        ("the existence check — every referenced path resolves",
         "if candidate.exists():",
         "if True:"),
    ],
    "configs/scripts/erosion-trend.py": [
        ("the boolean-operand arm — a collapsed `and` chain scores as one branch",
         "score += len(child.values) - 1",
         "score += 0"),
        ("BoolOp counting entirely",
         "if isinstance(child, ast.BoolOp):",
         "if False:"),
        ("every other branching construct",
         "elif isinstance(child, _BRANCHING):",
         "elif False:"),
        ("the unparseable-source skip — a syntax error would score as clean",
         "        return None\n\n    functions = [n for n in ast.walk(tree)",
         "        return {}\n\n    functions = [n for n in ast.walk(tree)"),
    ],
    "configs/scripts/check-asserted-numbers.py": [
        ("the self-scope requirement — third-party numbers get reported as ours",
         'if kind in {"count-of-n", "multiple", "loc"} and not SELF_SCOPE_RE.search(window):',
         "if False:"),
        ("the fire-rate pattern",
         '("rate", re.compile(r"fires on (?:~|roughly |about )?(\\d+(?:\\.\\d+)?)\\s?%")),',
         ""),
        ("the Workflow run-population pattern",
         '("workflow-runs", re.compile(r"\\b(\\d[\\d,]*) parallel (?:Workflow )?runs\\b")),',
         ""),
        ("the Workflow agents-and-hours pattern",
         '("agent-hours", re.compile(r"\\b(\\d{1,3}(?:,\\d{3})+|\\d+) agents, (\\d+(?:\\.\\d+)?) ?h\\b")),',
         ""),
        ("the Workflow makespan-share pattern",
         '("makespan-share", re.compile(r"\\b(\\d+(?:\\.\\d+)?)\\s?% of (?:all )?makespan\\b")),',
         ""),
    ],
    "configs/scripts/check-skill-listing.py": [
        ("the bundled-skill reserve — the budget reads 8,000 chars larger than it is",
         "    listing = total + reserved\n",
         "    listing = total\n"),
        ("the 1536-char description cap",
         "    if len(desc) > DESC_CAP:\n",
         "    if False:\n"),
        ("descending usage order — a never-used skill would outrank a used one",
         "    candidates.sort(key=lambda n: -scores[n])",
         "    candidates.sort(key=lambda n: scores[n])"),
        ("the name-only override",
         '    forced = {s["name"] for s in skills if overrides.get(s["name"]) == "name-only"}',
         "    forced = set()"),
        ("the 0.1 score floor — a skill unused for a year would decay to nothing",
         "max(0.5 ** (days / 7), 0.1)",
         "0.5 ** (days / 7)"),
    ],
}


# ─── check-workflow-script.py ─────────────────────────────────────────
# Its own block rather than a row in the dict above, so a concurrent edit to
# that table rebases cleanly. Each mutation removes one guard the Workflow
# preflight claims; its --self-test drives every control through hook_main /
# check_paths, the entry points the hook and the CLI use.
MUTATIONS["configs/scripts/check-workflow-script.py"] = [
    ("the logged-cut exemption — an owned truncation would be reported",
     "    if cut_is_logged(s):\n        return []",
     "    if False:\n        return []"),
    ("the cut-words test — any log() would excuse a silent cut",
     "            if CUT_WORDS.search(text):",
     "            if True:"),
    ("metadata keys — a label slice would read as a prompt",
     "            if key in META_KEYS:",
     "            if False:"),
    ("the log() context — a slice inside log() would read as a prompt",
     "            if callee in LOG_CALLEES:\n                return False",
     "            if False:\n                return False"),
    ("the cut-shape test — a chunk walk would read as a cut",
     'if inner[0].text == "0" and len(inner) >= 3 and inner[1].text == ",":',
     "if True:"),
    ("template interpolation — a helper-built prompt would be missed",
     '        if fr.kind in ("${", "`"):\n            composite = True',
     '        if fr.kind in ("${", "`"):\n            pass'),
    ("the workflow's own return value — a final result would read as a prompt",
     "        if fid < 0 and _statement_starts_with_return(s, anchor):",
     "        if False:"),
    ("receiver tracing through a variable",
     "        return _assigned_from_stringify(s, t.text), k",
     "        return False, k"),
    ("result tracing through an assignment",
     'if before is not None and before.text == "=" and first_k >= 2 and depth < 2:',
     "if False:"),
    ("string literals are text, not code",
     """            if ch in "'\\"":""",
     """            if ch in "\\"":"""),
    ("the dunder-sentinel value pattern",
     '    ("dunder sentinel", re.compile(r"^__[A-Z][A-Z0-9_]*__$")),\n',
     ""),
    ("the '(see …)' pointer pattern",
     '    ("\'(see …)\' pointer", re.compile(r"^\\(see\\b[^)]*\\)?$", re.I)),\n',
     ""),
    ("dunder values are upper case only (__init__ is data)",
     're.compile(r"^__[A-Z][A-Z0-9_]*__$")),',
     're.compile(r"^__[A-Za-z][A-Za-z0-9_]*__$")),'),
    ("sentinel keys are the measured shapes, not any __ prefix",
     'PLACEHOLDER_KEY = re.compile(r"^(?:__(?:[Ss]ee',
     'PLACEHOLDER_KEY = re.compile(r"^(?:__[A-Za-z]\\w*|__(?:[Ss]ee'),
    ("the sentinel-key check",
     "            if isinstance(leaf, str) and PLACEHOLDER_KEY.match(leaf):",
     "            if False:"),
    ("the stringified-args warning",
     "        if isinstance(parsed, (dict, list)):",
     "        if False:"),
    ("deny wins over warn",
     "def _render(deny: List[Finding], warn: List[Finding]) -> str:\n    if deny:",
     "def _render(deny: List[Finding], warn: List[Finding]) -> str:\n    if False:"),
    ("stage isolation — a crash in script resolution would drop the deny",
     "    except Exception:\n        return\n    deny.extend(d)",
     "    except ZeroDivisionError:\n        return\n    deny.extend(d)"),
    ("args first — a deadline in the script stage would drop the deny",
     "    _run_stage(lambda: check_args(tool_input), deny, warn)\n    try:\n"
     "        _arm_deadline(_deadline_s(env))\n"
     "        _run_stage(lambda: _script_stage(tool_input, payload, env), deny, warn)\n",
     "    try:\n"
     "        _arm_deadline(_deadline_s(env))\n"
     "        _run_stage(lambda: _script_stage(tool_input, payload, env), deny, warn)\n"
     "        _run_stage(lambda: check_args(tool_input), deny, warn)\n"),
    ("the stale-cache rejection — a weeks-old reading would warn",
     "    if age > QUOTA_MAX_AGE_S or age < -60:",
     "    if age < -60:"),
    ("the 7-day threshold",
     "SEVEN_DAY_WARN = 90.0",
     "SEVEN_DAY_WARN = 101.0"),
    ("the 5-hour threshold",
     "FIVE_HOUR_WARN = 85.0",
     "FIVE_HOUR_WARN = 101.0"),
    ("the previous-window rejection",
     "        if left is not None and left <= 0:\n            continue",
     "        if False:\n            continue"),
    ("the config-dir fallback for a saved workflow name",
     'for base in (Path(cwd) / ".claude" / "workflows", config_dir(env) / "workflows"):',
     'for base in (Path(cwd) / ".claude" / "workflows",):'),
    # ── fix round 2 (2026-10-23 review): each guard below stayed green
    #    before its control existed. Truncation: which calls account for a cut.
    ("cut accounting limited to log()/console.* — a cut word in a prompt would excuse the script",
     'if fr.kind == "(" and fr.callee in CUT_LOG_CALLEES and fr.close_tok > fr.open_tok:',
     'if fr.kind == "(" and fr.close_tok > fr.open_tok:'),
    ("phase() is not cut accounting — phase('Drop …') would excuse the script",
     'CUT_LOG_CALLEES = LOG_CALLEES - {"phase"}',
     "CUT_LOG_CALLEES = LOG_CALLEES"),
    # Truncation reach: methods, receivers, sinks.
    ("the .slice(-N) tail cut",
     'if method == "slice" and inner[0].text == "-" and len(inner) == 2 and inner[1].kind in ("num", "ident"):',
     "if False:"),
    (".substring and .substr",
     'if t.kind != "ident" or t.text not in ("slice", "substring", "substr"):',
     'if t.kind != "ident" or t.text not in ("slice",):'),
    ("the .toString() receiver",
     'if callee in ("JSON.stringify", "String") or callee.endswith(".toString") or callee == "toString":',
     'if callee in ("JSON.stringify", "String"):'),
    ("a variable assigned from String(",
     'if rhs.startswith("JSON.stringify(") or rhs.startswith("String("):',
     'if rhs.startswith("JSON.stringify("):'),
    ("push/unshift/concat as a sink",
     'if callee.split(".")[-1] in APPEND_CALLEES:\n                composite = True',
     'if callee.split(".")[-1] in APPEND_CALLEES:\n                pass'),
    ("an array literal as a sink",
     '                return False, "index"\n            composite = True',
     '                return False, "index"\n            pass'),
    ("'+' concatenation as a sink",
     'composite = bool((before and before.text in ("+", "+=")) or (after and after.text == "+"))',
     "composite = False"),
    # Truncation exclusions and lexing.
    ("the index-access exclusion",
     '            if fr.is_index:\n                return False, "index"',
     '            if False:\n                return False, "index"'),
    ("the condition exclusion",
     'elif callee in STATEMENT_KEYWORDS:\n                return False, "condition"',
     'elif False:\n                return False, "condition"'),
    ("the agent() options exclusion",
     'return False, "agent() options"',
     'return True, "agent() options"'),
    ("line comments are skipped",
     'if src.startswith("//", i):',
     "if False:"),
    ("block comments are skipped",
     'if src.startswith("/*", i):',
     "if False:"),
    ("regex literals are lexed as one token",
     'if ch == "/" and self._regex_allowed():',
     "if False:"),
    ("a line break ends a return statement (ASI)",
     "            if s.line_of(t.end) != s.line_of(later.start) and \\\n"
     "                    t.text not in _CONT_END and later.text not in _CONT_START:\n"
     "                return False",
     "            if False:\n                return False"),
    ("an object key is not a read — only after { or ,",
     'return nxt.text == ":" and prev is not None and prev.text in ("{", ",")',
     "return False"),
    ("a ternary's ':' is a read — the key test needs the { or , before it",
     'return nxt.text == ":" and prev is not None and prev.text in ("{", ",")',
     'return nxt.text == ":"'),
    ("an assignment target is not a read",
     '    if nxt.text == "=":\n        return True\n',
     ""),
    # Placeholder args.
    ("the dunder sentinel matches a whole leaf only",
     're.compile(r"^__[A-Z][A-Z0-9_]*__$")',
     're.compile(r"^__[A-Z][A-Z0-9_]*__")'),
    ("every placeholder leaf is reported, not only the first",
     '                                    kind + " " + json.dumps(_short(leaf, 40)), "deny"))\n',
     '                                    kind + " " + json.dumps(_short(leaf, 40)), "deny"))\n'
     '                break\n'),
    ("a JSON-encoded string is decoded before matching",
     "        elif isinstance(parsed, str):\n            value = parsed",
     "        elif False:\n            value = parsed"),
    ("the deny excerpt is bounded — 500-char keys would push the instruction out",
     '                deny.append(Finding("placeholder-args", 0, _short(path, 120),\n'
     '                                    kind + " "',
     '                deny.append(Finding("placeholder-args", 0, path,\n'
     '                                    kind + " "'),
    ("the deny reason is fitted to DENY_BUDGET",
     'reason = _fit("\\n".join(lines), DENY_BUDGET)',
     'reason = "\\n".join(lines)'),
    # Hook contract.
    ("the tool_name filter",
     'payload.get("tool_name") != "Workflow"',
     "False"),
    ("the '..' guard on a saved workflow name",
     'if isinstance(name, str) and name and ".." not in name and not name.startswith("/"):',
     "if isinstance(name, str) and name:"),
    ("cwd resolved inside the script stage — a removed directory would cost the deny",
     "    deny: List[Finding] = []\n    warn: List[Finding] = []\n    # Args FIRST",
     "    _hook_cwd(payload, env)\n    deny: List[Finding] = []\n    warn: List[Finding] = []\n    # Args FIRST"),
    ("the deadline is armed",
     "        _arm_deadline(_deadline_s(env))\n",
     "        pass\n"),
    ("the deadline handler raises",
     "        _ARMED[0] = False\n        raise _Deadline()",
     "        _ARMED[0] = False"),
    ("CLADE_PREFLIGHT_DEADLINE is read",
     'v = float(env.get("CLADE_PREFLIGHT_DEADLINE", "") or HOOK_DEADLINE_S)',
     "v = HOOK_DEADLINE_S"),
    # Quota: the numbers, at their boundaries.
    ("the 10-minute freshness bound, loosened",
     "QUOTA_MAX_AGE_S = 600 ",
     "QUOTA_MAX_AGE_S = 3500 "),
    ("the 10-minute freshness bound, tightened",
     "QUOTA_MAX_AGE_S = 600 ",
     "QUOTA_MAX_AGE_S = 500 "),
    ("the 7-day threshold, raised",
     "SEVEN_DAY_WARN = 90.0",
     "SEVEN_DAY_WARN = 93.0"),
    ("the 7-day threshold, lowered",
     "SEVEN_DAY_WARN = 90.0",
     "SEVEN_DAY_WARN = 89.5"),
    ("the 5-hour threshold, raised",
     "FIVE_HOUR_WARN = 85.0",
     "FIVE_HOUR_WARN = 88.0"),
    ("the 5-hour threshold, lowered",
     "FIVE_HOUR_WARN = 85.0",
     "FIVE_HOUR_WARN = 84.5"),
    ("a cache with no _at says nothing",
     '    at = data.get("_at")\n',
     '    at = data.get("_at", time.time())\n'),
    ("a cache stamped in the future says nothing",
     "    if age > QUOTA_MAX_AGE_S or age < -60:",
     "    if age > QUOTA_MAX_AGE_S:"),
    ("a non-numeric utilization says nothing",
     "        if not isinstance(util, (int, float)):\n            continue",
     "        if not isinstance(util, (int, float)):\n            util = 100"),
]

def _cases():
    for script, muts in MUTATIONS.items():
        for name, old, new in muts:
            yield pytest.param(script, name, old, new, id=f"{Path(script).stem}:{name[:40]}")


@pytest.mark.parametrize("script,name,old,new", list(_cases()))
def test_removing_a_guard_turns_the_self_test_red(script, name, old, new):
    target = REPO / script
    source = target.read_text(encoding="utf-8")
    assert old in source, (
        f"the mutation anchor for {name!r} no longer appears in {script}. "
        f"The code moved; update the anchor, do not delete the case — an "
        f"unanchored mutation silently stops testing.")

    with tempfile.TemporaryDirectory() as tmp:
        backup = Path(tmp) / "backup"
        shutil.copy(target, backup)
        try:
            target.write_text(source.replace(old, new, 1), encoding="utf-8")
            result = subprocess.run([sys.executable, str(target), "--self-test"],
                                    capture_output=True, text=True, timeout=180)
        finally:
            shutil.copy(backup, target)

    assert result.returncode != 0, (
        f"{script} --self-test PASSES with {name} removed.\n"
        f"That property is claimed and not checked.\n{result.stdout[-600:]}")


@pytest.mark.parametrize("script", sorted(MUTATIONS))
def test_the_unmutated_self_test_passes(script):
    result = subprocess.run([sys.executable, str(REPO / script), "--self-test"],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_script_with_a_self_test_is_covered():
    """A script that gained --self-test and no mutations is untested by this file."""
    have = set(MUTATIONS)
    missing = []
    for path in sorted((REPO / "configs" / "scripts").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(REPO))
        if rel in have:
            continue
        if "--self-test" in path.read_text(encoding="utf-8", errors="replace"):
            missing.append(rel)
    # EMPTY, and it stays empty. This set held four scripts: the three CI runs
    # under the banner "can the harness go red?" (red-phase-audit,
    # workflow-scorecard, check-skill-contracts) plus check-runnable-paths,
    # which CI runs as a plain gate and never with --self-test. So the exemption
    # list was a strict superset of the self-tests CI exercises — the meta-gate
    # exempting the gates it exists to police, which is the same recursion as
    # every instrument named in this file's docstring. (An earlier phrasing said
    # "exactly the four scripts CI runs"; that is off by one and was refuted on
    # 2026-09-16 — the set identity does not hold, the recursion does.) An empty escape hatch is the point: a
    # one-entry list is a parking space with a precedent. A script that gains
    # --self-test now gains mutations in the same commit, or this test fails.
    known_gap: set[str] = set()
    unexpected = sorted(set(missing) - known_gap)
    assert not unexpected, (
        f"these scripts have a --self-test that nothing proves can fire: {unexpected}. "
        f"Add their mutations to MUTATIONS.")
