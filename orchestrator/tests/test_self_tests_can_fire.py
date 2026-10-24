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
    source = (REPO / hook).read_text(encoding="utf-8")
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
            path = Path(tmp) / f"m{i}-{Path(hook).name}"
            path.write_text(mutated, encoding="utf-8")
            return name, _run_suite(spec, path, fail_fast=True)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(one, enumerate(spec["mutations"])))

    stayed_green = [name for name, res in results if res.returncode == 0]
    assert not stayed_green, (
        f"{spec['suite']} still PASSES with these removed from {hook}: {stayed_green}.\n"
        f"Those properties are claimed and not checked.")


@pytest.mark.parametrize("hook", sorted(HOOK_SUITES))
def test_the_unmutated_hook_suite_passes(hook):
    spec = HOOK_SUITES[hook]
    result = _run_suite(spec, REPO / hook)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]
