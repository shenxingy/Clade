"""Ask every --self-test whether it can still go red.

This repository has now shipped SIX instruments that could not fire, and the
failure mode is always the same: a clean run and a broken run print the same
sentence, so the gate reads as evidence while measuring nothing.

  red-phase-audit.py     reported 0% because the harness could not fire
  workflow-scorecard.py  matched the `>/` of `2>/dev/null`, so every session
                         reported zero polls and it read as discipline
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

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# script -> [(what the mutation removes, exact source before, exact source after)]
MUTATIONS: dict[str, list[tuple[str, str, str]]] = {
    "configs/scripts/artifact-lint.py": [
        ("the headline-is-a-claim check",
         "if h1 and argued and not is_claim(h1[0]):",
         "if False:"),
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
