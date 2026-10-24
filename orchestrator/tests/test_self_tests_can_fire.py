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


# ─── Hook suites ──────────────────────────────────────────────────────
#
# The same question for a guard that lives in a shell hook and is tested by a
# shell suite rather than a --self-test. The hook is mutated in a COPY and the
# suite pointed at it through its override variable, so the tree is never
# written. A mutation can take several (old, new) edits: a gate that two
# checks implement together is removed by removing both.
#
# pre-tool-guardian's subagent-wait rule, run as GUARDIAN_WAITS_ONLY=1. Its
# fork-free pre-checks are not listed alone, on purpose: the `"agent_id"`
# string test, the wait-word test, the `"timeout"`-key test and the `> 270000`
# test. Each is a fast path that a later check repeats (the non-empty agent_id
# test, the awk itself, the effective-timeout test, the awk capping every wait
# at the call's timeout), so removing one alone changes latency and no verdict
# — which is what a mutation of any of them shows. Where it matters they are
# removed together with their counterpart. Two more are deliberately absent:
# the `{` that opens a brace group (its close is listed, and a group never
# opened is never closed, so the same case decides both) and the depth cap of
# 6 nested scripts (a guard against runaway recursion, not a verdict).
#
# Its force-push walk, run as GUARDIAN_PUSH_ONLY=1 under a second key (the
# "hook" field names the file), and the same walk in the Codex mirror, mutated
# through GUARDIAN_PY_HOOK. GUARDIAN_SIDE asserts only the guardian a table
# mutates (the full suite asserts both), which halves its time. The two tables
# name the same guards in the same order, so a guard added to one walk and not
# the other shows as a missing name. Not mutated, on purpose: the depth cap of
# 6 queued walks (a guard against runaway recursion, not a verdict); the
# "nested" block code of a queued walk (the verdict is BLOCK either way); the
# empty-delimiter test before a heredoc's prefix rule (it only keeps <<''
# from matching every line); and the text a substitution leaves in the word
# around it, which changes no verdict since a ref holding a substitution is
# read as the session branch.
#
# Every anchor must occur exactly once: the edit replaces the first match, and
# the hook carries two awk programs whose option-parsing lines are alike, so a
# duplicated anchor would mutate whichever comes first and test nothing.
HOOK_SUITES: dict[str, dict] = {
    "configs/hooks/pre-tool-guardian.sh": {
        "suite": "tests/test-pre-tool-guardian.sh",
        "hook_var": "GUARDIAN_HOOK",
        "env": {"GUARDIAN_WAITS_ONLY": "1"},
        "fail_fast_env": {"GUARDIAN_FAIL_FAST": "1"},
        "mutations": [
            ("the agent_id gate — the main thread would be warned",
             [("[[ \"$INPUT\" == *'\"agent_id\"'* ]] || return 0", ":"),
              ('[[ -n "$agent" && "$bg" != "true" ]]', '[[ "$bg" != "true" ]]')]),
            ("the non-empty agent_id test",
             [('[[ -n "$agent" && "$bg" != "true" ]]', '[[ "$bg" != "true" ]]')]),
            ("the run_in_background gate",
             [('[[ -n "$agent" && "$bg" != "true" ]]', '[[ -n "$agent" ]]')]),
            ("the default for a call that sets no timeout, or 0",
             [('gd_ms "$timeout" "$default";', 'gd_ms "$timeout" 600000;')]),
            ("the 600 s ceiling on a call's timeout",
             [("(( eff > max )) && eff=$max", ":")]),
            ("the call's timeout as the bound of an unbounded wait",
             [('GD_WAIT_BOUND_MS="$eff"', "GD_WAIT_BOUND_MS=600000"),
              ("(( eff > GD_WAIT_LIMIT_S * 1000 )) || return 0", ":")]),
            ("the 270 s limit",
             [("if (r > limit)", "if (r > 0)")]),
            ("GNU duration suffixes",
             [('if (u == "m") v *= 60', "if (0) v *= 60")]),
            ("an until/while loop around sleep",
             [('if (LK[d, f] == "uw") { if (LS[d, f]) { r = INF;',
               'if (LK[d, f] == "uw") { if (LS[d, f]) { r = 0;')]),
            ("a for loop as count x sleep",
             [("r = LC[d, f] * LSUM[d, f];", "r = LSUM[d, f];")]),
            ("the $(seq …) count of a for loop",
             [('if (TV[d, k] == "seq") LC[d, FORPEND[d]]', 'if (0) LC[d, FORPEND[d]]')]),
            ("a timeout prefix bounding what it wraps",
             [("if (secs > 0 && secs < sb) sb = secs", "if (0) sb = secs")]),
            ("a job sent to the background with &",
             [('bg = (sep == "&")', "bg = 0")]),
            ("a ( … ) & group sent to the background",
             [('if (!bg || GT[d, g] == "S") return', "return")]),
            ("wait collecting a backgrounded wait",
             [("if (BGMAX[d] > 0) add_wait(", "if (0) add_wait(")]),
            ("reading a bash -c script",
             [("if (j < n) { r = scan(TV[d, j + 1], eb, d + 1);", "if (j < n) { r = 0;")]),
            ("reading an ssh remote command",
             [('for (j += 2; j <= n; j++) script = script " " TV[d, j]\n    r = scan(script, eb, d + 1);',
               'for (j += 2; j <= n; j++) script = script " " TV[d, j]\n    r = 0;')]),
            # The shell's own bound goes too: left in, an unset bound reads as
            # 0 and masks the mutation — this entry's first version did that.
            ("a heredoc is read only when a shell reads it",
             [("if (STDIN_SH[d]) { r = scan(body, min2(bound, SHB[d]), d + 1)",
               "if (1) { r = scan(body, bound, d + 1)")]),
            ("a heredoc fed to a shell is read",
             [("if (STDIN_SH[d]) { r = scan(body", "if (0) { r = scan(body")]),
            ("quoted text is one word, not commands",
             [("if (c == \"\\047\" || c == \"\\\"\") { tstart(d); q = c; i++; continue }",
               "if (0) { tstart(d); q = c; i++; continue }")]),
            ("tail -f",
             [('add_wait(d, sb, "tail -f", bg); return', "return")]),
            ("python -c time.sleep",
             [('add_wait(d, min2(secs, sb), "python time.sleep", bg)', "secs = 0")]),
            ("a rewrite carrying the wait warning",
             [('--arg why "$2${GD_WAIT_WARN:+ $GD_WAIT_WARN}"', '--arg why "$2"')]),
            ("the warning reaching the model at all",
             [('[[ -n "$GD_WAIT_WARN" ]] && gd_warn "$GD_WAIT_WARN"', ":")]),
            ("a warning that never decides permission",
             [('{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}',
               '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"allow",additionalContext:$c}}')]),
            # ── the remedy the warning gives (review, 2026-10-23) ──
            ("the recommended loop staying under 270 s",
             [("bound the loop (for i in \\$(seq 1 26);", "bound the loop (for i in \\$(seq 1 40);")]),
            ("nohup, not run_in_background, as the detach",
             [("To outlast this agent, detach the job (nohup <job> > <log> 2>&1 &), record the log "
               "path and end; run_in_background is no detach here, since a synchronous subagent's "
               "background jobs end with its final response.",
               "Or start the job with run_in_background, record where its result will land, and "
               "end once that path is in your report.")]),
            # ── the subagent TTL the environment sets ──
            ("the TTL check at all",
             [("  gd_subagent_ttl_1h && return 0", "  :")]),
            ("CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h",
             [("in 1h) return 0 ;; 5m) return 1 ;; esac", "in 1h) ;; 5m) return 1 ;; esac")]),
            ("the TTL variable outranking ENABLE_PROMPT_CACHING_1H",
             [("in 1h) return 0 ;; 5m) return 1 ;; esac", "in 1h) return 0 ;; 5m) ;; esac")]),
            ("reading the subagent TTL variable, not the main thread's",
             [('case "${CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL:-}" in',
               'case "${CLAUDE_CODE_PROMPT_CACHE_TTL:-}" in')]),
            ("ENABLE_PROMPT_CACHING_1H",
             [('gd_env_true "${ENABLE_PROMPT_CACHING_1H:-}" && return 0', "false && return 0")]),
            ("FORCE_PROMPT_CACHING_5M outranking the rest",
             [('gd_env_true "${FORCE_PROMPT_CACHING_5M:-}" && return 1', "false && return 1")]),
            ("ENABLE_PROMPT_CACHING_1H_BEDROCK on Bedrock",
             [('gd_env_true "${CLAUDE_CODE_USE_BEDROCK:-}" && gd_env_true "${ENABLE_PROMPT_CACHING_1H_BEDROCK:-}" && return 0',
               "false && return 0")]),
            ("ENABLE_PROMPT_CACHING_1H_BEDROCK only on Bedrock",
             [('gd_env_true "${CLAUDE_CODE_USE_BEDROCK:-}" && gd_env_true "${ENABLE_PROMPT_CACHING_1H_BEDROCK:-}"',
               'gd_env_true "${ENABLE_PROMPT_CACHING_1H_BEDROCK:-}"')]),
            ("true, yes and on in any case",
             [("1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn]) return 0", "1) return 0")]),
            ("0 and other words reading as off",
             [('  case "$1" in 1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;; esac\n  return 1',
               '  [ -n "$1" ]')]),
            # ── durations ──
            ("the h suffix", [('else if (u == "h") v *= 3600', 'else if (u == "h") v *= 1')]),
            ("the d suffix", [('else if (u == "d") v *= 86400', 'else if (u == "d") v *= 1')]),
            ("sleep infinity", [('if (s == "infinity" || s == "inf") return INF', "if (0) return INF")]),
            # ── for-loop counts ──
            ("a {A..B} count",
             [("if (v ~ /^\\{-?[0-9]+\\.\\.-?[0-9]+\\}$/) {", "if (0) {")]),
            ("a word-list count",
             [("} else if (v ~ /[*?[$`]/) return\n    else c++", "} else if (v ~ /[*?[$`]/) return\n    else c += 0")]),
            ("a glob or $var word making the count unknown",
             [("} else if (v ~ /[*?[$`]/) return", "} else if (0) return")]),
            ("a sleep of unknown length making a for loop unknown",
             [("if (LC[d, f] >= 0 && !LX[d, f])", "if (LC[d, f] >= 0)")]),
            # ── command prefixes ──
            ("an assignment before the command",
             [("while (k <= n && TV[d, k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) k++", "while (0) k++")]),
            ("sudo/nice/env/nohup/… prefixes", [("if (w in PFX) {", "if (0) {")]),
            ("the nice prefix", [('PFX["nice"] = " -n --adjustment "; ', "")]),
            ("the nohup prefix", [('PFX["nohup"] = " "; ', "")]),
            ("the command prefix", [('; PFX["command"] = " "', "")]),
            ("the sudo prefix", [('PFX["sudo"] = " -u -g -h -p -C -D -r -t -U "; ', "")]),
            ("the env prefix", [('; PFX["env"] = " -u -C -S --unset --chdir "', "")]),
            ("the stdbuf prefix", [('PFX["stdbuf"] = " -i -o -e "; ', "")]),
            ("the ionice prefix", [('PFX["ionice"] = " -c -n -p -P -u "; ', "")]),
            ("the exec prefix", [('; PFX["exec"] = " -a "', "")]),
            ("the option values those prefixes take",
             [('if (index(PFX[w], " " v " ") > 0) { k++; continue }', "if (0) { k++; continue }")]),
            ("an assignment an env prefix carries",
             [("if (v ~ /^-/ || v ~ /^[A-Za-z_][A-Za-z0-9_]*=/) continue", "if (v ~ /^-/) continue")]),
            ("the signal and kill-after values of timeout",
             [('if (v == "-s" || v == "-k" || v == "--signal" || v == "--kill-after") { k++; continue }',
               "if (0) { k++; continue }")]),
            # ── sleep arguments ──
            ("sleep stopping at a redirect",
             [("if (v ~ /^[0-9]*[<>]/ || v ~ /^&>/) break", "if (v ~ /^&>/) break")]),
            ("sleep stopping at &>",
             [("if (v ~ /^[0-9]*[<>]/ || v ~ /^&>/) break", "if (v ~ /^[0-9]*[<>]/) break")]),
            # ── waiters ──
            ("watch", [('if (w == "watch" || w == "pidwait")', 'if (w == "pidwait")')]),
            ("pidwait", [('if (w == "watch" || w == "pidwait")', 'if (w == "watch")')]),
            ("tail --follow", [('if (v ~ /^--follow/ || (v ~ /^-[A-Za-z0-9]+$/ && v ~ /[fF]/))',
                                'if ((v ~ /^-[A-Za-z0-9]+$/ && v ~ /[fF]/))')]),
            ("docker wait",
             [('if (TV[d, k + 1] == "wait") add_wait(d, sb, "docker wait", bg)', 'if (0) add_wait(d, sb, "docker wait", bg)')]),
            ("gh run watch", [('{ add_wait(d, sb, "gh run watch", bg); return }', "{ return }")]),
            ("gh pr checks --watch",
             [('if (TV[d, j] == "--watch") { add_wait(d, sb, "gh pr checks --watch", bg); return }',
               'if (0) { add_wait(d, sb, "gh pr checks --watch", bg); return }')]),
            ("inotifywait waiting without end by default",
             [("    secs = INF\n    for (j = k + 1; j <= n; j++) {\n      v = TV[d, j]\n      if (v == \"-t\"",
               "    secs = 0\n    for (j = k + 1; j <= n; j++) {\n      v = TV[d, j]\n      if (v == \"-t\"")]),
            ("inotifywait -t",
             [('if (v == "-t" || v == "--timeout") { r = dur(TV[d, j + 1]); if (r > 0) secs = r; j++ }',
               "if (0) { j++ }")]),
            ("inotifywait --timeout=",
             [("else if (v ~ /^--timeout=/) { r = dur(substr(v, 11)); if (r > 0) secs = r }",
               "else if (0) { secs = 0 }")]),
            ("kubectl wait's 30 s default",
             [("    secs = 30\n", "    secs = INF\n")]),
            ("kubectl wait --timeout as a separate word",
             [('if (v == "--timeout") { v = "--timeout=" TV[d, j + 1]; j++ }', "if (0) { j++ }")]),
            ("kubectl wait's negative --timeout",
             [("secs = (v ~ /^-/) ? INF : dur(v)", "secs = dur(v)")]),
            ("kubectl wait's unreadable --timeout left uncounted",
             [("secs = (v ~ /^-/) ? INF : dur(v)", "secs = (v ~ /^-/ || dur(v) < 0) ? INF : dur(v)")]),
            ("a python while loop around time.sleep",
             [("if (script ~ /(^|[^A-Za-z0-9_])while[ \\t(]/) {", "if (0) {")]),
            # ── nested scripts ──
            ("eval", [('if (w == "eval" && k < n) {', 'if (0 && k < n) {')]),
            ("bash -lc and other combined flags",
             [('if (v == "-c" || (v ~ /^-[A-Za-z]+$/ && index(v, "c") > 0)) {\n        if (j < n)',
               'if (v == "-c") {\n        if (j < n)')]),
            ("the values of bash -o / --rcfile",
             [('if (v == "-o" || v == "+o" || v == "-O" || v == "+O" || v == "--rcfile" || v == "--init-file") { j++; continue }\n      if (v == "-s") break',
               'if (v == "-s") break')]),
            ("the option values of ssh",
             [("      v = TV[d, j]\n      if (v ~ /^-[BbcDEeFIiJLlmOopQRSWw]$/) { j++; continue }",
               "      v = TV[d, j]\n      if (0) { j++; continue }")]),
            ("ssh reading its script from a heredoc",
             [("if (j == n) { STDIN_SH[d] = 1; SHB[d] = sb; SHBG[d] = bg; return }", "if (j == n) return")]),
            # ── the scanner ──
            ("a comment skipped whole",
             [('if (c == "#" && !INTOK[d]) { while (i <= n && substr(text, i, 1) != "\\n") i++; continue }',
               'if (0) { while (i <= n && substr(text, i, 1) != "\\n") i++; continue }')]),
            ("a # inside a word not starting a comment",
             [('if (c == "#" && !INTOK[d]) { while (i <= n && substr(text, i, 1) != "\\n") i++; continue }',
               'if (c == "#") { while (i <= n && substr(text, i, 1) != "\\n") i++; continue }')]),
            ("a { …; } & group sent to the background",
             [('if (w == "}") { close_group(d, bg); return }', 'if (w == "}") { close_group(d, 0); return }')]),
            ("the tab strip of a <<- heredoc",
             [('if (HDS[d, h]) sub(/^\\t+/, "", line)', 'if (0) sub(/^\\t+/, "", line)')]),
            ("a here-string not sending its second < into the heredoc branch",
             [('if (c == "<" && substr(text, i, 2) == "<<") {',
               'if (c == "<" && substr(text, i, 2) == "<<" && substr(text, i, 3) != "<<<") {')]),
            (">& read as a redirect, not a background job",
             [('(substr(text, i - 1, 1) == ">" || substr(text, i - 1, 1) == "<")',
               '(substr(text, i - 1, 1) == "<")')]),
            ("&> read as a redirect, not a background job",
             [('|| substr(text, i + 1, 1) == ">") {', ") {")]),
            (") && not read as a background group",
             [('substr(text, j + 1, 1) != "&" && ', "")]),
            (") &> not read as a background group",
             [(' && substr(text, j + 1, 1) != ">")', ")")]),
        ],
    },
    "configs/hooks/pre-tool-guardian.sh (force-push walk)": {
        "hook": "configs/hooks/pre-tool-guardian.sh",
        "suite": "tests/test-pre-tool-guardian.sh",
        "hook_var": "GUARDIAN_HOOK",
        "env": {"GUARDIAN_PUSH_ONLY": "1", "GUARDIAN_SIDE": "sh"},
        "fail_fast_env": {"GUARDIAN_FAIL_FAST": "1"},
        "mutations": [
            ('a here-string is never a heredoc (the 2026-10-23 bug)',
             [('  if (substr(cmd, i, 3) == "<<<") {',
              '  if (substr(cmd, i, 3) == "<<<") { start_tok(); tok_val = tok_val "<"; i++; return 1 }\n  if (0) {')]),
            ("a here-string's word is a script for a shell reading stdin",
             [('  if (tok_val ~ /^[0-9]*<<</) { sub(/^[0-9]*<<</, "", tok_val); note_script(tok_val) }',
              '  if (0) { sub(/^[0-9]*<<</, "", tok_val); note_script(tok_val) }')]),
            ('a push-like word is a script for a shell reading stdin',
             [('  else if (tok_val ~ /[ \\t\\n]/ && may_push(tok_val)) note_script(tok_val)',
              '  else if (0) note_script(tok_val)')]),
            ("a redirection is not a shell's script file",
             [('    if ((r = redir(v)) > 0) { j += r - 1; continue }\n    if (v == "-c"',
              '    if (0) { j += r - 1; continue }\n    if (v == "-c"')]),
            ('a redirection whose target is the next word',
             [('  return (v ~ /^[0-9]*[<>]+&?$/ || v ~ /^&>>?$/) ? 2 : 1',
              '  return 1')]),
            ("redirections after ssh's host are not its remote command",
             [('  while (m <= nt && (r = redir(tv[m])) > 0) m += r',
              '  while (0) m += r')]),
            ("a git push's redirections are not refs",
             [('    if ((rd = redir(v)) > 0) { skipnext = (rd == 2); continue }',
              '    if (0) { skipnext = (rd == 2); continue }')]),
            ('a substitution inside double quotes is walked',
             [('      if (open_exp(c)) continue\n      if (c == "\\"") q = ""',
              '      if (0) continue\n      if (c == "\\"") q = ""')]),
            ('an unquoted $( is walked, not a cut in its statement',
             [('    if (open_exp(c)) continue\n    if (c == "(" && substr',
              '    if (c == "$" && substr(cmd, i + 1, 1) == "(") { end_seg(); i += 2; continue }\n    if (open_exp(c)) continue\n    if (c == "(" && substr')]),
            ('the statement around a substitution resumes',
             [('  nt = snt[sn]\n',
              '  nt = 0\n')]),
            ('the quote a substitution was opened in resumes',
             [('  q = sq[sn]; cd_seen = scd[sn];',
              '  q = ""; cd_seen = scd[sn];')]),
            ('a ( inside $( is counted',
             [('    if (c == "(") { if (sn > 0) sp[sn]++; end_seg()',
              '    if (c == "(") { end_seg()')]),
            ('and its ) uncounted',
             [('      if (sn > 0 && sp[sn] > 0) sp[sn]--\n',
              '')]),
            ('a backtick ends at the next backtick, whatever the quotes inside it',
             [('    if (sn > 0 && sbt[sn] > 0 && i >= sbt[sn]) {',
              '    if (0) {')]),
            ('an unterminated substitution is closed at the end',
             [('  while (sn > 0) close_sub(0)\n  end_seg()',
              '  while (0) close_sub(0)\n  end_seg()')]),
            ('an escaped backtick inside backticks is walked again',
             [('    if (index(substr(cmd, i + 1, e - i - 1), "\\\\")) enqueue(',
              '    if (0) enqueue(')]),
            ("$'…' quoting",
             [('    if (substr(cmd, i, 2) == "$\\047") { start_tok(); q = "$"; i += 2; continue }',
              '    if (0) { start_tok(); q = "$"; i += 2; continue }')]),
            ("a backslash escaping a quote inside $'…'",
             [('      if (c == "\\\\" && i < n) { i++; tok_val = tok_val ansi(); continue }',
              '      if (0) { i++; tok_val = tok_val ansi(); continue }')]),
            ("$'…' escapes decoded",
             [('    i += 1 + k; return (v > 0 && v < 128) ? sprintf("%c", v) : "?"',
              '    i += 1 + k; return "?"')]),
            ('$"…" quoting',
             [('    if (substr(cmd, i, 2) == "$\\"") { start_tok(); q = "\\""; i += 2; continue }',
              '    if (0) { start_tok(); q = "\\""; i += 2; continue }')]),
            ('$$ is one word',
             [('    if (substr(cmd, i, 2) == "$$") { start_tok(); tok_val = tok_val "$$"; i += 2; continue }',
              '    if (0) { start_tok(); tok_val = tok_val "$$"; i += 2; continue }')]),
            ('$$ is one word inside double quotes',
             [('      if (substr(cmd, i, 2) == "$$") { tok_val = tok_val "$$"; i += 2; continue }',
              '      if (0) { tok_val = tok_val "$$"; i += 2; continue }')]),
            ('the zsh and bash readings of $$\' and "$$(',
             [('  if (top ~ /\\$\\$[\\047(]/) {',
              '  if (0) {')]),
            ('$(( is arithmetic',
             [('  if (nc == "(") { if (substr(cmd, i + 2, 1) == "(" && arith_end(i + 3)) open_sub("A", 3); else open_sub("$", 2); return 1 }',
              '  if (nc == "(") { open_sub("$", 2); return 1 }')]),
            ('only when it closes with ))',
             [('    else if (ch == ")") { if (d == 0) return substr(cmd, p + 1, 1) == ")"; d-- }',
              '    else if (ch == ")") { if (d == 0) return 1; d-- }')]),
            ("(( at a command's place is arithmetic",
             [('    if (c == "(" && substr(cmd, i + 1, 1) == "(" && cmd_pos() && arith_end(i + 2)) {',
              '    if (0) {')]),
            ('and only there',
             [('    if (c == "(" && substr(cmd, i + 1, 1) == "(" && cmd_pos() && arith_end(i + 2)) {',
              '    if (c == "(" && substr(cmd, i + 1, 1) == "(" && arith_end(i + 2)) {')]),
            ('$[ ] is arithmetic',
             [('  if (nc == "[") { open_sub("[", 2); return 1 }',
              '  if (0) { open_sub("[", 2); return 1 }')]),
            ('<< in arithmetic is a shift',
             [('  if (arith()) return 0\n  if (in_tok',
              '  if (in_tok')]),
            ('a word in arithmetic is not a command',
             [('function end_seg() { flush_tok(); if (nt > 0 && !arith()) analyze();',
              'function end_seg() { flush_tok(); if (nt > 0) analyze();')]),
            ('a heredoc delimiter is a whole word',
             [('    if (index(" \\t\\n;&|<>()", ch)) break',
              '    if (ch !~ /[A-Za-z0-9_\\047"\\\\]/) break')]),
            ('a backslash quotes the delimiter',
             [('    if (ch == "\\\\") { hdq = 1; hdw = hdw substr(cmd, j + 1, 1); j += 2; continue }',
              '    if (0) { hdq = 1; hdw = hdw substr(cmd, j + 1, 1); j += 2; continue }')]),
            ('a heredoc whose delimiter never comes is read as commands',
             [('  if (!closed) { if (facts(body)) block("nested"); enqueue(body, "", cd_seen, wd + 1); return }',
              '  if (!closed) return')]),
            ("an unquoted delimiter's body is expanded",
             [('  if (!quoted) enqueue(body, "H", cd_seen, wd + 1)',
              '  if (0) enqueue(body, "H", cd_seen, wd + 1)')]),
            ('and its escaped $( is data',
             [('      if (c == "\\\\" && i < n && index("$`\\\\\\n", substr(cmd, i + 1, 1))) { i += 2; continue }',
              '      if (0) { i += 2; continue }')]),
            ('a heredoc body is a script for a shell reading stdin',
             [('  note_script(body)\n}',
              '}')]),
            ('in $( ), a line starting with the delimiter and holding ) ends the heredoc',
             [('          if (sn > 0 && sk[sn] == "$" && hd_delim[h] != "" && index(line, ")") &&',
              '          if (0 && sn > 0 && sk[sn] == "$" && hd_delim[h] != "" && index(line, ")") &&')]),
            ('a cd inside a substitution changes nothing outside it',
             [('  q = sq[sn]; cd_seen = scd[sn]; pd = spd[sn];',
              '  q = sq[sn]; pd = spd[sn];')]),
            ('nor one inside ( )',
             [('      if (pd > ((sn > 0) ? spd[sn] : 0)) { cd_seen = pcd[pd]; pd-- }',
              '      if (pd > ((sn > 0) ? spd[sn] : 0)) pd--')]),
            ('nor one beside | or ||',
             [('      nocd = 1; end_seg(); nocd = 1\n',
              '      end_seg()\n')]),
            ('nor one sent to the background',
             [('      nocd = 1; end_seg(); i++; continue',
              '      end_seg(); i++; continue')]),
            ('a ref the shell computes is the session branch',
             [('    if (index(raw, "$(") || index(raw, "`")) subref = 1',
              '    if (0) subref = 1')]),
            ('even after a cd or over ssh',
             [('  if ((((nrefs == 0 || headref) && !allrefs && !cd_seen && !hasC) || subref) &&',
              '  if (((nrefs == 0 || headref || subref) && !allrefs && !cd_seen && !hasC) &&')]),
            ('a remote shell reading stdin has an unknown branch',
             [('  if (m > nt) { set_stdin(1); return 1 }',
              '  if (m > nt) { set_stdin(cd_seen); return 1 }')]),
            ('a local one has this one',
             [('  set_stdin(cd_seen); return 1\n}',
              '  set_stdin(1); return 1\n}')]),
            ('a local stdin shell after a remote one',
             [('  if (stdin_any && stdin_cd <= cdf) return',
              '  if (stdin_any) return')]),
            ('a string another shell runs is walked again',
             [('  for (j = start; j <= stop; j++) s = s ((j > start) ? " " : "") tv[j]\n  enqueue(s, "", cdf, wd + 1)',
              '  for (j = start; j <= stop; j++) s = s ((j > start) ? " " : "") tv[j]')]),
            ('and all its arguments are matched as text',
             [('  if (facts(s)) block("nested")',
              '  if (0) block("nested")')]),
            ('a nested walk never rewrites',
             [('function add_edit(s, e, t) { if (!ed) return;',
              'function add_edit(s, e, t) {')]),
            ('a shell reading stdin gets the whole command matched as text',
             [('  if (stdin_any && facts(top)) block("nested")',
              '  if (0) block("nested")')]),
            ('that text with its quotes removed too',
             [('    if (pass == 2) gsub(/[\\047"\\\\]/, "", t)',
              '    if (0) t = t')]),
            ('and a delete in it',
             [('|--mirror|--delete|-[A-Za-z]*[fd][A-Za-z]*)',
              '|-[A-Za-z]*f[A-Za-z]*)')]),
            ("a case pattern's ) closes nothing",
             [('  if (tok_val == "in" && nt == 3 && tv[1] == "case") {',
              '  if (0) {')]),
            ("nor a pattern's opening (",
             [('    if (c == "(" && ip[sn] && !in_tok && nt == 0) { i++; continue }\n',
              '')]),
            ('nor the ) of a pattern after ;;',
             [('        if (cc[sn] > 0) ip[sn] = 1',
              '        if (0) ip[sn] = 1')]),
            ('esac ends the patterns',
             [('  if (tok_val == "esac" && nt == 1 && cc[sn] > 0) {',
              '  if (0) {')]),
            ('an assignment or option is never the command',
             [('  for (; k <= nt; k++) {\n    w = tv[k]\n    if (w ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || w ~ /^-/) continue',
              '  for (k = 1; k <= nt; k++) {\n    w = tv[k]\n    if (0) continue')]),
            ('a git not followed by push is not the command',
             [('    if (w == "git") { if (analyze_git(k)) return }',
              '    if (w == "git") { analyze_git(k); return }')]),
            ('nor a shell given a script file',
             [('    else if (is_shell(w)) { if (analyze_shell(k)) return }',
              '    else if (is_shell(w)) { analyze_shell(k); return }')]),
            ('su -c',
             [('    else if (w == "su" || w == "runuser") { analyze_su(k); return }\n',
              '')]),
            ('sudo -s',
             [('    else if (w == "sudo" || w == "doas") { if (analyze_sudo(k)) return }\n',
              '')]),
            ('a computed subcommand is read as push',
             [('    if (!index(raw, "$") && !index(raw, "`")) return 0',
              '    return 0')]),
            ('and never rewritten',
             [('  if (nf == 0 && np == 0 || ex) return 1',
              '  if (nf == 0 && np == 0) return 1')]),
            ('--mirror',
             [('  if (mirror) { block("mirror"); return 1 }',
              '  if (0) { block("mirror"); return 1 }')]),
            ('an alias given with -c',
             [('    for (j = 1; j <= ncf; j++) if (ck[j] == "alias." tolower(tv[k])',
              '    for (j = 1; j <= 0; j++) if (ck[j] == "alias." tolower(tv[k])')]),
            ('one that names another alias',
             [('      if (ck[r] ~ /^alias\\./ && (cv[r] ~ /push/ || cv[r] == "?")) {',
              '      if (ck[r] == ck[j] && (cv[r] ~ /push/ || cv[r] == "?")) {')]),
            ('GIT_CONFIG_KEY_n/VALUE_n are config on the command line',
             [('    if (v ~ /^GIT_CONFIG_(KEY|VALUE)_[0-9]+=/) {',
              '    if (0) {')]),
            ('and GIT_CONFIG_PARAMETERS',
             [('    else if (v ~ /^GIT_CONFIG_PARAMETERS=/) {',
              '    else if (0) {')]),
            ('a push refspec given with -c',
             [('    if ((ck[j] ~ /^remote\\..+\\.push$/ && (nf || np || lease || cv[j] ~ /^\\+/ || cv[j] == "?")) ||',
              '    if ((0) ||')]),
            ('heads/main is main',
             [('  sub(/^refs\\/heads\\//, "", r); sub(/^heads\\//, "", r)',
              '  sub(/^refs\\/heads\\//, "", r)')]),
            ('a glob that covers main',
             [('    if (d == "main" || d == "master" || glob_main(d) || r == ":") {',
              '    if (d == "main" || d == "master" || r == ":") {')]),
            ('only one that does',
             [('  if (!(p = index(d, "*"))) return 0\n',
              '  if (!(p = index(d, "*"))) return 0\n  return 1\n')]),
            ('the matching refspec :',
             [('    if (d == "main" || d == "master" || glob_main(d) || r == ":") {',
              '    if (d == "main" || d == "master" || glob_main(d)) {')]),
            ('is no delete',
             [('      if (substr(r, 1, 1) == ":" && r != ":") del = 1',
              '      if (substr(r, 1, 1) == ":") del = 1')]),
            ('--all with a lease',
             [('  if (mainref || (allrefs && (nf > 0 || np > 0 || lease))) {',
              '  if (mainref || (allrefs && (nf > 0 || np > 0))) {')]),
            ('a redirection ends the word before it (main>/dev/null)',
             [('  if (in_tok && !fd_tok() && tok_val !~ /^[0-9]*[<>]+&?$/ && tok_val !~ /^&>>?$/) flush_tok()',
              '  if (0) flush_tok()')]),
            ('but not its descriptor (2>)',
             [('  return (r ~ /^[0-9]+$/ || r ~ /^\\{[A-Za-z_][A-Za-z0-9_]*\\}$/)',
              '  return 0')]),
            ('&> ends the word before it',
             [('      if (substr(cmd, i + 1, 1) == ">") { flush_tok(); start_tok();',
              '      if (substr(cmd, i + 1, 1) == ">") { start_tok();')]),
            ('the walk runs once quotes are removed',
             [('_gd_plain=${_gd_plain//\\"/}; _gd_plain=${_gd_plain//\\\'/}; _gd_plain=${_gd_plain//\\\\/}',
              ':')]),
            ('and line continuations',
             [("_gd_plain=${COMMAND//\\\\$'\\n'/};",
              '_gd_plain=$COMMAND;')]),
            ("or on a $'…' string",
             [('if [[ "$_gd_plain" == *push* || "$COMMAND" == *"\\$\'"* ]]; then',
              'if [[ "$_gd_plain" == *push* ]]; then')]),
        ],
    },
    "plugins/clade/hooks/pre_tool_guardian.py": {
        "suite": "tests/test-pre-tool-guardian.sh",
        "hook_var": "GUARDIAN_PY_HOOK",
        "env": {"GUARDIAN_PUSH_ONLY": "1", "GUARDIAN_SIDE": "py"},
        "fail_fast_env": {"GUARDIAN_FAIL_FAST": "1"},
        "mutations": [
            ('a here-string is never a heredoc (the 2026-10-23 bug)',
             [('        if cmd.startswith("<<<", i):\n            self.start_tok()\n            self.tok[1] += "<<<"\n            self.i += 3',
              '        if cmd.startswith("<<<", i):\n            self.start_tok()\n            self.tok[1] += "<"\n            self.i += 1\n            return True')]),
            ("a here-string's word is a script for a shell reading stdin",
             [('        if m:\n            self.note_script(val[m.end():])',
              '        if False:\n            self.note_script(val[m.end():])')]),
            ('a push-like word is a script for a shell reading stdin',
             [('        elif re.search(r"[ \\t\\n]", val) and _may_push(val):',
              '        elif False:')]),
            ("a redirection is not a shell's script file",
             [('            if words:\n                j += words\n                continue\n            if v == "-c"',
              '            if False:\n                j += words\n                continue\n            if v == "-c"')]),
            ('a redirection whose target is the next word',
             [('    return 2 if re.match(r"^[0-9]*[<>]+&?$", word) or re.match(r"^&>>?$", word) else 1',
              '    return 1')]),
            ("redirections after ssh's host are not its remote command",
             [('        while m < len(vals) and _redirect_words(vals[m]):',
              '        while False:')]),
            ("a git push's redirections are not refs",
             [('            if words:\n                skip = words == 2',
              '            if False:\n                skip = words == 2')]),
            ('a substitution inside double quotes is walked',
             [('                if self.open_exp(c):\n                    continue\n                if c == \'"\':',
              '                if False:\n                    continue\n                if c == \'"\':')]),
            ('an unquoted $( is walked, not a cut in its statement',
             [('            if self.open_exp(c):\n                continue\n            if c == "(" and cmd[i + 1:i + 2] == "("',
              '            if c == "$" and cmd[i + 1:i + 2] == "(":\n                self.end_seg()\n                self.i += 2\n                continue\n            if self.open_exp(c):\n                continue\n            if c == "(" and cmd[i + 1:i + 2] == "("')]),
            ('the statement around a substitution resumes',
             [('        self.toks, self.q, self.cd_seen = sub["toks"], sub["quote"], sub["cd"]',
              '        self.toks, self.q, self.cd_seen = [], sub["quote"], sub["cd"]')]),
            ('the quote a substitution was opened in resumes',
             [('        self.toks, self.q, self.cd_seen = sub["toks"], sub["quote"], sub["cd"]',
              '        self.toks, self.q, self.cd_seen = sub["toks"], "", sub["cd"]')]),
            ('a ( inside $( is counted',
             [('            if c == "(":\n                if self.subs:\n                    self.subs[-1]["parens"] += 1',
              '            if c == "(":\n                if False:\n                    self.subs[-1]["parens"] += 1')]),
            ('and its ) uncounted',
             [('                if top and top["parens"] > 0:\n                    top["parens"] -= 1',
              '                if top and top["parens"] > 0:\n                    pass')]),
            ('a backtick ends at the next backtick, whatever the quotes inside it',
             [('            if self.subs and self.subs[-1]["bt"] is not None and i >= self.subs[-1]["bt"]:',
              '            if False:')]),
            ('an unterminated substitution is closed at the end',
             [('        while self.subs:\n            self.close_sub(0)\n        self.end_seg()',
              '        while False:\n            self.close_sub(0)\n        self.end_seg()')]),
            ('an escaped backtick inside backticks is walked again',
             [('            if "\\\\" in inner:',
              '            if False:')]),
            ("$'…' quoting",
             [('            if cmd.startswith("$\'", i):\n                self.start_tok()',
              '            if False:\n                self.start_tok()')]),
            ("a backslash escaping a quote inside $'…'",
             [('            if self.q == "$\'":\n                if c == "\\\\" and i + 1 < n:',
              '            if self.q == "$\'":\n                if False:')]),
            ("$'…' escapes decoded",
             [('        return (chr(v) if 0 < v < 128 else "?"), i + 1 + len(m.group(0))',
              '        return "?", i + 1 + len(m.group(0))')]),
            ('$"…" quoting',
             [("            if cmd.startswith('$\"', i):",
              '            if False:')]),
            ('$$ is one word',
             [('            if cmd.startswith("$$", i):\n                self.start_tok()',
              '            if False:\n                self.start_tok()')]),
            ('$$ is one word inside double quotes',
             [('                if cmd.startswith("$$", i):\n                    self.tok[1] += "$$"',
              '                if False:\n                    self.tok[1] += "$$"')]),
            ('the zsh and bash readings of $$\' and "$$(',
             [('        if re.search(r"\\$\\$[\'(]", command):',
              '        if False:')]),
            ('$(( is arithmetic',
             [('            if cmd[i + 2:i + 3] == "(" and _arith_end(cmd, i + 3):',
              '            if False:')]),
            ('only when it closes with ))',
             [('                return cmd[p + 1:p + 2] == ")"',
              '                return True')]),
            ("(( at a command's place is arithmetic",
             [('            if c == "(" and cmd[i + 1:i + 2] == "(" and self.cmd_pos() and _arith_end(cmd, i + 2):',
              '            if False:')]),
            ('and only there',
             [('            if c == "(" and cmd[i + 1:i + 2] == "(" and self.cmd_pos() and _arith_end(cmd, i + 2):',
              '            if c == "(" and cmd[i + 1:i + 2] == "(" and _arith_end(cmd, i + 2):')]),
            ('$[ ] is arithmetic',
             [('        if nc == "[":\n            self.open_sub("[", 2)',
              '        if False:\n            self.open_sub("[", 2)')]),
            ('<< in arithmetic is a shift',
             [('    def redirect(self) -> bool:\n        if self.arith():\n            return False\n',
              '    def redirect(self) -> bool:\n')]),
            ('a word in arithmetic is not a command',
             [('        if self.toks and not self.arith():',
              '        if self.toks:')]),
            ('a heredoc delimiter is a whole word',
             [('        if ch in " \\t\\n;&|<>()":',
              '        if not re.match(r"[A-Za-z0-9_\'\\"\\\\\\\\]", ch):')]),
            ('a backslash quotes the delimiter',
             [('        if ch == "\\\\":\n            quoted = True',
              '        if False:\n            quoted = True')]),
            ('a heredoc whose delimiter never comes is read as commands',
             [('        if not closed:\n            if _facts(body):\n                self.block("nested")\n            self.enqueue(body, "", self.cd_seen, self.depth + 1)\n            return',
              '        if not closed:\n            return')]),
            ("an unquoted delimiter's body is expanded",
             [('        if not quoted:\n            self.enqueue(body, "H", self.cd_seen, self.depth + 1)',
              '        if False:\n            self.enqueue(body, "H", self.cd_seen, self.depth + 1)')]),
            ('and its escaped $( is data',
             [('                if c == "\\\\" and i + 1 < n and cmd[i + 1] in "$`\\\\\\n":',
              '                if False:')]),
            ('a heredoc body is a script for a shell reading stdin',
             [('            return\n        self.note_script(body)\n',
              '            return\n')]),
            ('in $( ), a line starting with the delimiter and holding ) ends the heredoc',
             [('                        if (self.subs and self.subs[-1]["kind"] == "$" and delim and ")" in line',
              '                        if (False and self.subs and self.subs[-1]["kind"] == "$" and delim and ")" in line')]),
            ('a cd inside a substitution changes nothing outside it',
             [('        self.toks, self.q, self.cd_seen = sub["toks"], sub["quote"], sub["cd"]',
              '        self.toks, self.q = sub["toks"], sub["quote"]')]),
            ('nor one inside ( )',
             [('                    self.cd_seen = self.parens.pop()',
              '                    self.parens.pop()')]),
            ('nor one beside | or ||',
             [('            if c == "|":\n                self.nocd = True\n                self.end_seg()\n                self.nocd = True',
              '            if c == "|":\n                self.end_seg()')]),
            ('nor one sent to the background',
             [('                self.nocd = True\n                self.end_seg()\n                self.i += 1\n                continue\n            if c in "<>"',
              '                self.end_seg()\n                self.i += 1\n                continue\n            if c in "<>"')]),
            ('a ref the shell computes is the session branch',
             [('            if "$(" in raw or "`" in raw:\n                subref = True',
              '            if False:\n                subref = True')]),
            ('even after a cd or over ssh',
             [('        if ((((nrefs == 0 or headref) and not allrefs and not self.cd_seen and not has_c) or subref)',
              '        if (((nrefs == 0 or headref or subref) and not allrefs and not self.cd_seen and not has_c)')]),
            ('a remote shell reading stdin has an unknown branch',
             [('            self.set_stdin(True)',
              '            self.set_stdin(self.cd_seen)')]),
            ('a local one has this one',
             [('            return False\n        self.set_stdin(self.cd_seen)\n        return True',
              '            return False\n        self.set_stdin(True)\n        return True')]),
            ('a local stdin shell after a remote one',
             [('        if self.stdin_any and self.stdin_cd <= cd:',
              '        if self.stdin_any:')]),
            ('a string another shell runs is walked again',
             [('        self.enqueue(" ".join(vals[start:stop + 1]), "", cd, self.depth + 1)',
              '        pass')]),
            ('and all its arguments are matched as text',
             [('        if _facts("".join(" " + v for v in vals[start:])):',
              '        if False:')]),
            ('a nested walk never rewrites',
             [('        if self.edits_on:\n            self.edits.append',
              '        if True:\n            self.edits.append')]),
            ('a shell reading stdin gets the whole command matched as text',
             [('        if self.stdin_any and _facts(command):',
              '        if False:')]),
            ('that text with its quotes removed too',
             [('    for t in (text, re.sub(r"[\\\\\'\\"]", "", text)):',
              '    for t in (text,):')]),
            ('and a delete in it',
             [('|--mirror|--delete"\n                                   r"|-[A-Za-z]*[fd][A-Za-z]*)',
              '"\n                                   r"|-[A-Za-z]*f[A-Za-z]*)')]),
            ("a case pattern's ) closes nothing",
             [('        if val == "in" and len(self.toks) == 3 and self.toks[0][2] == "case":',
              '        if False:')]),
            ("nor a pattern's opening (",
             [('            if c == "(" and self.cases[-1][1] and self.tok is None and not self.toks:',
              '            if False:')]),
            ('nor the ) of a pattern after ;;',
             [('                    if self.cases[-1][0] > 0:\n                        self.cases[-1][1] = True',
              '                    if False:\n                        self.cases[-1][1] = True')]),
            ('esac ends the patterns',
             [('        if val == "esac" and len(self.toks) == 1 and case[0] > 0:',
              '        if False:')]),
            ('an assignment or option is never the command',
             [('        while k < len(vals):\n            v = vals[k]\n            if _ASSIGN.match(v) or v.startswith("-"):',
              '        k = 0\n        while k < len(vals):\n            v = vals[k]\n            if False:')]),
            ('a git not followed by push is not the command',
             [('            if w == "git":\n                if self.analyze_git(vals, k):\n                    return',
              '            if w == "git":\n                self.analyze_git(vals, k)\n                return')]),
            ('nor a shell given a script file',
             [('            elif w in _SHELLS:\n                if self.analyze_shell(vals, k):\n                    return',
              '            elif w in _SHELLS:\n                self.analyze_shell(vals, k)\n                return')]),
            ('su -c',
             [('            elif w in ("su", "runuser"):',
              '            elif w in ("-",):')]),
            ('sudo -s',
             [('            elif w in ("sudo", "doas"):',
              '            elif w in ("-",):')]),
            ('a computed subcommand is read as push',
             [('            if "$" not in raw and "`" not in raw:\n                return False',
              '            if True:\n                return False')]),
            ('and never rewritten',
             [('        if not forces and not pluses or computed:',
              '        if not forces and not pluses:')]),
            ('--mirror',
             [('        if mirror:\n            self.block("mirror")',
              '        if False:\n            self.block("mirror")')]),
            ('an alias given with -c',
             [('            if any(key == name for key, _ in cfg) and any(',
              '            if False and any(')]),
            ('one that names another alias',
             [('                    key.startswith("alias.") and ("push" in val or val == "?") for key, val in cfg):',
              '                    key == name and ("push" in val or val == "?") for key, val in cfg):')]),
            ('GIT_CONFIG_KEY_n/VALUE_n are config on the command line',
             [('            if m:\n                env[m.group(1)] = v[m.end():]',
              '            if False:\n                env[m.group(1)] = v[m.end():]')]),
            ('and GIT_CONFIG_PARAMETERS',
             [('            elif v.startswith("GIT_CONFIG_PARAMETERS="):',
              '            elif False:')]),
            ('a push refspec given with -c',
             [('                (re.match(r"^remote\\..+\\.push$", key) and (forces or pluses or lease or val.startswith("+") or val == "?"))',
              '                False')]),
            ('heads/main is main',
             [('    return re.sub(r"^heads/", "", ref)',
              '    return ref')]),
            ('a glob that covers main',
             [('            if dst in ("main", "master") or _glob_main(dst) or ref == ":":',
              '            if dst in ("main", "master") or ref == ":":')]),
            ('only one that does',
             [('    pre, _, suf = dst.partition("*")',
              '    return True')]),
            ('the matching refspec :',
             [('            if dst in ("main", "master") or _glob_main(dst) or ref == ":":',
              '            if dst in ("main", "master") or _glob_main(dst):')]),
            ('is no delete',
             [('                if ref.startswith(":") and ref != ":":',
              '                if ref.startswith(":"):')]),
            ('--all with a lease',
             [('        if mainref or (allrefs and (forces or pluses or lease)):',
              '        if mainref or (allrefs and (forces or pluses)):')]),
            ('a redirection ends the word before it (main>/dev/null)',
             [('                and not re.match(r"^[0-9]*[<>]+&?$", self.tok[1]) and not re.match(r"^&>>?$", self.tok[1])):\n            self.flush_tok()',
              '                and not re.match(r"^[0-9]*[<>]+&?$", self.tok[1]) and not re.match(r"^&>>?$", self.tok[1])):\n            pass')]),
            ('but not its descriptor (2>)',
             [('        return bool(re.fullmatch(r"[0-9]+|\\{[A-Za-z_][A-Za-z0-9_]*\\}", self.cmd[self.tok[0]:self.i]))',
              '        return False')]),
            ('&> ends the word before it',
             [('                if cmd[i + 1:i + 2] == ">":\n                    self.flush_tok()\n                    self.start_tok()',
              '                if cmd[i + 1:i + 2] == ">":\n                    self.start_tok()')]),
            ('the walk runs once quotes are removed',
             [('    return "push" in re.sub(r"[\\\\\'\\"]", "", command.replace("\\\\\\n", "")) or "$\'" in command',
              '    return "push" in command.replace("\\\\\\n", "") or "$\'" in command')]),
            ('and line continuations',
             [('    return "push" in re.sub(r"[\\\\\'\\"]", "", command.replace("\\\\\\n", "")) or "$\'" in command',
              '    return "push" in re.sub(r"[\\\\\'\\"]", "", command) or "$\'" in command')]),
            ("or on a $'…' string",
             [('    return "push" in re.sub(r"[\\\\\'\\"]", "", command.replace("\\\\\\n", "")) or "$\'" in command',
              '    return "push" in re.sub(r"[\\\\\'\\"]", "", command.replace("\\\\\\n", ""))')]),
        ],
    },
}


def _run_suite(spec: dict, hook: Path, fail_fast: bool = False) -> subprocess.CompletedProcess:
    """Run the suite against `hook`. fail_fast stops it at the first red case:
    a mutation needs one, and the full list on every one of them would make
    this the slowest test in the job."""
    env = {**os.environ, **spec["env"], spec["hook_var"]: str(hook)}
    if fail_fast:
        env.update(spec.get("fail_fast_env", {}))
    return subprocess.run(["bash", str(REPO / spec["suite"])], capture_output=True, text=True,
                          timeout=300, env=env, cwd=REPO)


@pytest.mark.parametrize("hook", sorted(HOOK_SUITES))
def test_removing_a_hook_guard_turns_its_suite_red(hook):
    """One test per hook, the mutations run concurrently: the suite takes a few
    seconds and there are dozens of them, which as separate cases would add
    minutes to the pytest job."""
    spec = HOOK_SUITES[hook]
    path = spec.get("hook", hook)
    source = (REPO / path).read_text(encoding="utf-8")
    unanchored = [name for name, edits in spec["mutations"]
                  for old, _ in edits if old not in source]
    assert not unanchored, (
        f"mutation anchors no longer appear in {hook}: {unanchored}. The code "
        f"moved; update the anchor, do not delete the case — an unanchored "
        f"mutation silently stops testing.")
    ambiguous = [name for name, edits in spec["mutations"]
                 for old, _ in edits if source.count(old) > 1]
    assert not ambiguous, (
        f"mutation anchors occur more than once in {hook}: {ambiguous}. The "
        f"edit hits the first match, which may not be the guard named; widen "
        f"the anchor until it is unique.")

    with tempfile.TemporaryDirectory() as tmp:
        def one(i_mut):
            i, (name, edits) = i_mut
            mutated = source
            for old, new in edits:
                mutated = mutated.replace(old, new, 1)
            assert mutated != source, name
            copy = Path(tmp) / f"m{i}-{Path(path).name}"
            copy.write_text(mutated, encoding="utf-8")
            return name, _run_suite(spec, copy, fail_fast=True)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(one, enumerate(spec["mutations"])))

    stayed_green = [name for name, res in results if res.returncode == 0]
    assert not stayed_green, (
        f"{spec['suite']} still PASSES with these removed from {hook}: {stayed_green}.\n"
        f"Those properties are claimed and not checked.")


def test_both_force_push_tables_name_the_same_guards():
    """The awk and the Codex mirror are one walk written twice; a guard
    mutated in one table and missing from the other is a guard one of them
    lacks, or one nobody showed can fire there."""
    awk = [name for name, _ in HOOK_SUITES["configs/hooks/pre-tool-guardian.sh (force-push walk)"]["mutations"]]
    mirror = [name for name, _ in HOOK_SUITES["plugins/clade/hooks/pre_tool_guardian.py"]["mutations"]]
    assert awk == mirror


@pytest.mark.parametrize("hook", sorted(HOOK_SUITES))
def test_the_unmutated_hook_suite_passes(hook):
    spec = HOOK_SUITES[hook]
    result = _run_suite(spec, REPO / spec.get("hook", hook))
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]
