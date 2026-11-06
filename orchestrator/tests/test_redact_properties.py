"""Property-based must-not tests for configs/scripts/redact.py.

test_redact.py says what should happen to inputs somebody thought of. This file
says what must NOT happen, for inputs nobody picked (Osmani, *Agentic
Verification*, 2026-10-14: "Example tests say what should happen; properties say
what must not"):

1. A credential embedded in arbitrary text, delimited by separators the patterns
   can anchor on, leaves no run of 8 or more of its characters in the output —
   which includes, and is stronger than, "no 8-character tail survives".
2. Redaction is idempotent on the text it returns: a second pass changes nothing
   and reports nothing.

What the first runs found in redact.py, all fixed in the same change and pinned
below: overlapping matches resolved by dropping the later-listed one, so a JWT
holding an `-AKIA…` or `-sk-ant-…` run kept its header and payload in the clear;
env_secret matching its own `<redacted:…>` marker, so a second pass (and
scrub-corrections.py) reported the marker as a credential; and a trailing `\\b`
after a class containing `-`, so `AIza` + 34 + `-` or `sk-` + 19 + `-` was not
masked at all.

Why the generator inserts separators. Every token pattern in redact.py is
\\b-anchored at its start and several are fixed-length (`AKIA[0-9A-Z]{16}`).
A credential glued into random word characters is, by design, not a credential
to those patterns, so an undelimited generator's first counterexample would
describe the patterns' scope rather than a defect. The separators include CJK and Cyrillic
characters on purpose: that is the context correction-detector.sh actually feeds
the redactor, and the one an earlier version silently failed on.

What the consumer receives. correction-detector.sh pipes the prompt through
`python3 redact.py` and persists stdout; secret-scanner.sh reads the exit code of
`redact.py --check`. Both properties therefore read redact.py's main() — the CLI
entry point, run in-process so a few hundred examples stay fast — never scan()'s
spans.

Each counterexample Hypothesis shrank to is pinned below with @example, so it is
re-run first on every run whether or not the random search finds it again. The
search itself is random per run (no example database is written into the tree):
a failure that appears once and not on a rerun is a real counterexample the
search found by luck — pin it, do not rerun it away.

The last section keeps the mutations in the file: a copy of redact.py with one
pattern removed, or one of the fixes these properties forced undone, must make
the property find a counterexample, and the same search over the shipped module
must find none. A property that cannot go red when a pattern disappears is not
checking that pattern.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import HealthCheck, Phase, example, given, settings
from hypothesis import strategies as st

REDACT_PATH = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "redact.py"
MIN_RUN = 8


# ─── Loading ──────────────────────────────────────────────────────────────────

def _load(name: str, source: str | None = None) -> ModuleType:
    """Load redact.py, or a mutated copy of its source, as an independent module.

    Registered in sys.modules before exec because @dataclass resolves the
    module by cls.__module__ (the same constraint test_redact.py documents).
    """
    spec = importlib.util.spec_from_loader(name, loader=None)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(REDACT_PATH)
    sys.modules[name] = mod
    code = source if source is not None else REDACT_PATH.read_text(encoding="utf-8")
    exec(compile(code, str(REDACT_PATH), "exec"), mod.__dict__)
    return mod


REDACT = _load("clade_redact_properties")


def _run_cli(mod: ModuleType, text: str, *argv: str) -> tuple[int, str]:
    """redact.py's main() on `text` as stdin: (exit code, stdout)."""
    out, err = io.StringIO(), io.StringIO()
    saved = sys.argv, sys.stdin
    sys.argv, sys.stdin = ["redact.py", *argv], io.StringIO(text)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mod.main()
    finally:
        sys.argv, sys.stdin = saved
    return rc, out.getvalue()


def _masked(mod: ModuleType, text: str) -> str:
    """What correction-detector.sh persists: `printf '%s' "$text" | python3 redact.py`."""
    rc, out = _run_cli(mod, text)
    assert rc == 0
    return out


def _check_rc(mod: ModuleType, text: str) -> int:
    """What secret-scanner.sh reads: the exit code of `redact.py --check` (1 = found)."""
    return _run_cli(mod, text, "--check")[0]


# ─── Documents ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Embedded:
    """One credential as pasted: `before + secret + after`.

    `before`/`after` carry the non-secret context a pattern needs
    (`AWS_SECRET_ACCESS_KEY=`, `token: "`, a PEM armour line); `secret` is the
    part of which no run of MIN_RUN characters may survive.
    """

    before: str
    secret: str
    after: str = ""

    @property
    def fragment(self) -> str:
        return self.before + self.secret + self.after


@dataclass(frozen=True)
class Doc:
    """Filler and separators (str) interleaved with embedded credentials."""

    parts: tuple[str | Embedded, ...]

    def text(self, without: int | None = None) -> str:
        """The document; with `without=i`, part i keeps its context but loses its secret."""
        out = []
        for i, part in enumerate(self.parts):
            if isinstance(part, Embedded):
                out.append(part.before + part.after if i == without else part.fragment)
            else:
                out.append(part)
        return "".join(out)

    def embedded(self) -> list[tuple[int, Embedded]]:
        return [(i, p) for i, p in enumerate(self.parts) if isinstance(p, Embedded)]


ALNUM = string.ascii_letters + string.digits
URLSAFE = ALNUM + "_-"
B64 = ALNUM + "+/"
UPPER_DIGITS = string.ascii_uppercase + string.digits
AWS_SECRET_ALPHABET = ALNUM + "/+="
# env_secret's value class is [^'"\s]: printable ASCII less quotes and whitespace.
ENV_VALUE_ALPHABET = "".join(
    c for c in string.printable if c not in "'\"" and not c.isspace()
)
# Non-word characters outside every credential alphabet, so a pattern's \b (or
# the end of its character class) can anchor on them. CJK and Cyrillic are
# non-word under the re.ASCII flag every pattern carries, and are the context the
# main caller produces.
SEPARATORS = list(" \t\n,;()[]{}<>|!?&*#@%^~`'\"") + ["，", "是", "к"]
# Delimiters an inner token may sit between INSIDE a container's own alphabet.
ENV_INNER_DELIMS = list(",;|!?&*#@%^~()[]{}<>/.:")


def _chars(alphabet: str, lo: int, hi: int) -> st.SearchStrategy[str]:
    return st.text(alphabet=alphabet, min_size=lo, max_size=hi)


def _body(alphabet: str, lo: int, hi: int) -> st.SearchStrategy[str]:
    """Like _chars, but the LAST character is a non-word one about half the time.

    A trailing `-` is where a `\\b` after a class that contains `-` stops
    anchoring. Uniform characters reach it about once in 64 tokens, and plain
    300-example runs never found it; this generator found it on the first run.
    """
    edge = "".join(c for c in alphabet if not (c.isalnum() or c == "_"))
    last = st.sampled_from(alphabet) if not edge else st.one_of(st.sampled_from(edge), st.sampled_from(alphabet))
    return st.builds(str.__add__, _chars(alphabet, lo - 1, hi - 1), last)


def _pick(*options: str) -> st.SearchStrategy[str]:
    return st.sampled_from(options)


# Bare tokens: each shape the corresponding pattern documents, body characters
# drawn from the full documented alphabet (so a body may end in `-`, as a
# base64url key does about one time in 64).
BARE_TOKENS: dict[str, st.SearchStrategy[str]] = {
    "anthropic_key": st.builds(lambda k, b: f"sk-ant-{k}-{b}", _pick("api03", "admin01"), _body(URLSAFE, 40, 90)),
    "openai_key": st.builds(lambda p, b: f"sk-{p}{b}", _pick("", "proj-"), _body(URLSAFE, 20, 80)),
    "github_token": st.builds(lambda c, b: f"gh{c}_{b}", _pick(*"pousr"), _chars(ALNUM, 36, 60)),
    "aws_access_key": st.builds(lambda b: f"AKIA{b}", _chars(UPPER_DIGITS, 16, 16)),
    "google_api_key": st.builds(lambda b: f"AIza{b}", _body(URLSAFE, 35, 35)),
    "slack_token": st.builds(lambda c, b: f"xox{c}-{b}", _pick(*"baprs"), _body(ALNUM + "-", 10, 60)),
    "stripe_key": st.builds(lambda p, m, b: f"{p}_{m}_{b}", _pick("sk", "rk", "pk"), _pick("live", "test"),
                            _chars(ALNUM, 20, 60)),
    "generic_secret_key": st.builds(lambda p, b: f"{p}_{b}", _pick("sk", "rk", "ak"), _chars(ALNUM, 32, 64)),
}
ANY_BARE = st.one_of(*BARE_TOKENS.values())


@st.composite
def _maybe_nested(draw, plain: st.SearchStrategy[str], short: st.SearchStrategy[str], delims: list[str]) -> str:
    """A container body, half the time with another credential inside it.

    A JWT segment, an env value or a PEM body may contain a run some OTHER
    pattern matches. That inner match must not cost the outer credential its
    own redaction.
    """
    if not draw(st.booleans()):
        return draw(plain)
    d = draw(st.sampled_from(delims))
    return draw(short) + d + draw(ANY_BARE) + d + draw(short)


_JWT_SEGMENT = _maybe_nested(_body(URLSAFE, 10, 60), _chars(URLSAFE, 0, 12), ["-"])


@st.composite
def _jwt(draw) -> Embedded:
    return Embedded("", f"eyJ{draw(_JWT_SEGMENT)}.eyJ{draw(_JWT_SEGMENT)}.{draw(_JWT_SEGMENT)}")


@st.composite
def _aws_secret(draw) -> Embedded:
    q = draw(_pick("", "'", '"'))
    assign = draw(_pick("=", ": ", " = ", ":"))
    return Embedded(f"AWS_SECRET_ACCESS_KEY{assign}{q}", draw(_chars(AWS_SECRET_ALPHABET, 40, 40)), q)


@st.composite
def _env_secret(draw) -> Embedded:
    keyword = draw(_pick("api_key", "API_KEY", "api-key", "apikey", "secret", "SECRET",
                         "password", "Password", "passwd", "token", "TOKEN", "auth"))
    assign = draw(_pick("=", ": ", " = ", ":"))
    q = draw(_pick("'", '"'))
    value = draw(_maybe_nested(_chars(ENV_VALUE_ALPHABET, 12, 60), _chars(ENV_VALUE_ALPHABET, 0, 12),
                               ENV_INNER_DELIMS))
    return Embedded(f"{keyword}{assign}{q}", value, q)


@st.composite
def _private_key(draw) -> Embedded:
    kind = draw(_pick("", "RSA ", "OPENSSH ", "DSA ", "EC ", "PGP "))
    lines = st.lists(_chars(B64, 1, 64), min_size=1, max_size=4).map("\n".join)
    body = draw(_maybe_nested(lines, _chars(B64, 0, 12), ["\n"]))
    return Embedded(f"-----BEGIN {kind}PRIVATE KEY-----\n", body, f"\n-----END {kind}PRIVATE KEY-----")


EMBEDDED: dict[str, st.SearchStrategy[Embedded]] = {
    **{kind: s.map(lambda tok: Embedded("", tok)) for kind, s in BARE_TOKENS.items()},
    "aws_secret_key": _aws_secret(),
    "jwt": _jwt(),
    "env_secret": _env_secret(),
    "private_key": _private_key(),
}
FILLER = st.text(max_size=16)


@st.composite
def documents(draw) -> Doc:
    parts: list[str | Embedded] = [draw(FILLER)]
    for _ in range(draw(st.integers(1, 3))):
        parts += [draw(st.sampled_from(SEPARATORS)), draw(st.one_of(*EMBEDDED.values())),
                  draw(st.sampled_from(SEPARATORS)), draw(FILLER)]
    return Doc(tuple(parts))


TEXTS = st.one_of(documents().map(Doc.text), st.text())


# ─── Properties ───────────────────────────────────────────────────────────────

def _occurrences(needle: str, hay: str) -> int:
    return sum(1 for k in range(len(hay) - len(needle) + 1) if hay.startswith(needle, k))


_MARKER = re.compile(r"<redacted:[a-z_]+>")


def _unmarked(mod: ModuleType, text: str) -> str:
    """The masked text with every `<redacted:…>` marker reduced to one NUL.

    A marker is redact.py's own output, not surviving input: a secret whose
    value ends in `redacted` would otherwise "leak" through the marker's name
    (Hypothesis found exactly that oracle bug on the first long run).
    """
    return _MARKER.sub("\0", _masked(mod, text))


def surviving_runs(mod: ModuleType, doc: Doc) -> list[str]:
    """Every MIN_RUN-character run of an embedded secret that the output still carries.

    Differential, so filler that happens to share a run with a secret (Hypothesis
    likes `00000000`) is not a leak: a run counts only if the output holds MORE
    copies of it than the same document with that secret removed.
    """
    masked = _unmarked(mod, doc.text())
    leaks = []
    for i, emb in doc.embedded():
        baseline = _unmarked(mod, doc.text(without=i))
        for k in range(len(emb.secret) - MIN_RUN + 1):
            run = emb.secret[k:k + MIN_RUN]
            if run in masked and _occurrences(run, masked) > _occurrences(run, baseline):
                leaks.append(run)
    return leaks


def assert_no_surviving_run(mod: ModuleType, doc: Doc) -> None:
    leaks = surviving_runs(mod, doc)
    assert not leaks, f"credential runs survived redaction: {leaks[:3]!r}"


def assert_idempotent(mod: ModuleType, text: str) -> None:
    once = _masked(mod, text)
    twice = _masked(mod, once)
    assert twice == once, f"a second pass changed the output:\n  once:  {once!r}\n  twice: {twice!r}"
    # scrub-corrections.py re-scans history that correction-detector.sh already
    # masked; a marker that matches again is reported to the owner as a leak.
    assert _check_rc(mod, once) == 0, f"a second pass still reports a secret in {once!r}"


PROPERTY_SETTINGS = settings(
    max_examples=300,
    deadline=None,          # a loaded shared host is not a performance regression
    database=None,          # no .hypothesis/ directory in the tree
    print_blob=True,        # a failure prints the @reproduce_failure line to pin
    suppress_health_check=[HealthCheck.too_slow],
)


# ─── Pinned counterexamples ───────────────────────────────────────────────────
# What Hypothesis shrank each failure to, kept so it is re-run first on every run.
# Literals are assembled from pieces: configs/scripts/checks.sh scans every
# staged line with redact.py and would refuse a commit carrying a whole one.

def _one(emb: Embedded) -> Doc:
    return Doc(("", " ", emb, " ", ""))


_ANT = "sk-" + "ant-api03-" + "0" * 40
_JWT_HEAD = "ey" + "J" + "0" * 10 + ".ey" + "J" + "0" * 10 + "."

# 1. A JWT whose third segment holds an anthropic-shaped run. anthropic_key is
#    listed before jwt, and scan() let the first-listed match win and DROPPED the
#    overlapping jwt one, so header and payload went out in the clear. Fixed by
#    merging overlapping matches (scan()).
PIN_JWT_AROUND_KEY = _one(Embedded("", _JWT_HEAD + "-" + _ANT + "-"))
# 2. Same defect, seen by the idempotence property: the first pass masked only the
#    AKIA run, so the second pass found the JWT it had left behind.
PIN_JWT_AROUND_AKIA_TEXT = " " + _JWT_HEAD + "0" * 10 + "-AK" + "IA" + "0" * 16 + "- "
# 3. env_secret matched its own marker: an `api_key=` value that is exactly
#    <redacted:env_secret> is 21 non-quote characters in quotes. Fixed by a
#    lookahead in that pattern.
PIN_ENV_MARKER_TEXT = " api_" + "key='" + "0" * 12 + "' "
# 4. A Google key whose last character is `-`: `AIza…{35}\b` cannot place a
#    boundary between `-` and a space, and a fixed count cannot backtrack, so the
#    whole key was missed. Found by an 8,000-example run before _body() existed.
PIN_GOOGLE_TRAILING_DASH = _one(Embedded("", "AI" + "za" + "0" * 34 + "-"))
# 5. The same `\b`-after-`-` defect in an open count: at the minimum length,
#    backtracking off the dash left 19 characters for a {20,} and nothing matched.
#    Found by the first run with _body(). Fixed by dropping the trailing \b from
#    every pattern whose class contains `-`.
PIN_OPENAI_SHORTEST_TRAILING_DASH = _one(Embedded("", "sk-" + "0" * 19 + "-"))
# 6. Not a redact.py defect — this file's oracle: a secret ending in `redacted`
#    "survived" through the marker's own name until _unmarked() existed.
PIN_SECRET_SPELLING_MARKER = _one(Embedded("api_" + "key='", "," + _ANT + ",redacted", "'"))


@PROPERTY_SETTINGS
@given(documents())
@example(PIN_JWT_AROUND_KEY)
@example(PIN_GOOGLE_TRAILING_DASH)
@example(PIN_OPENAI_SHORTEST_TRAILING_DASH)
@example(PIN_SECRET_SPELLING_MARKER)
def test_no_run_of_an_embedded_credential_survives(doc: Doc) -> None:
    assert_no_surviving_run(REDACT, doc)


@PROPERTY_SETTINGS
@given(TEXTS)
@example(PIN_JWT_AROUND_AKIA_TEXT)
@example(PIN_ENV_MARKER_TEXT)
def test_redaction_is_idempotent_on_its_output(text: str) -> None:
    assert_idempotent(REDACT, text)


# ─── Mutations: each property must be able to go red ─────────────────────────
# A search that stops at the first counterexample, generate phase only (the pins
# above are not allowed to do the finding) and derandomized, so a mutation run is
# the same run every time — a mutation test must not itself be flaky. Measured on
# 2026-11-05: the slowest of the 16 mutations below went red at example 231 (the
# openai trailing \b), most within 40; SEARCH_BUDGET leaves room for generator
# changes to reshuffle the sequence.
SEARCH_BUDGET = 600


def _finds_counterexample(prop, mod: ModuleType, strategy: st.SearchStrategy) -> bool:
    @settings(max_examples=SEARCH_BUDGET, phases=[Phase.generate], derandomize=True, database=None,
              deadline=None, suppress_health_check=list(HealthCheck))
    @given(strategy)
    def search(value) -> None:
        prop(mod, value)

    try:
        search()
    except AssertionError:
        return True
    return False


@pytest.mark.parametrize("prop, strategy", [(assert_no_surviving_run, documents()), (assert_idempotent, TEXTS)],
                         ids=["leak", "idempotence"])
def test_the_search_reports_nothing_on_the_shipped_module(prop, strategy) -> None:
    """The negative control: the same search, unmutated, must come back empty.

    Without it every mutation test below could pass because the search fires on
    anything — a property that cannot say "no" proves nothing when it says "yes".
    """
    assert not _finds_counterexample(prop, REDACT, strategy)


# Removing this pattern leaves nothing for the leak property to see, and that is
# checked rather than assumed (test_excluded_pattern_is_covered_by_another).
NOT_LOAD_BEARING = {"anthropic_key": "openai_key"}
PATTERN_KINDS = [kind for kind, _, _ in REDACT._PATTERNS]


def test_every_pattern_has_a_generator_and_a_mutation() -> None:
    """A pattern added to redact.py without a generator here is a pattern no property covers."""
    assert sorted(EMBEDDED) == sorted(PATTERN_KINDS)
    assert set(NOT_LOAD_BEARING) <= set(PATTERN_KINDS)


@PROPERTY_SETTINGS
@given(BARE_TOKENS["anthropic_key"])
def test_excluded_pattern_is_covered_by_another(token: str) -> None:
    """Why anthropic_key has no removal mutation: openai_key masks the same span."""
    for kind, cover in NOT_LOAD_BEARING.items():
        pats = {k: rx for k, rx, _ in REDACT._PATTERNS}
        own, other = pats[kind].search(token), pats[cover].search(token)
        assert own is not None and other is not None and other.span() == own.span()


@pytest.mark.parametrize("kind", [k for k in PATTERN_KINDS if k not in NOT_LOAD_BEARING])
def test_removing_a_pattern_turns_the_leak_property_red(kind: str) -> None:
    mod = _load(f"clade_redact_without_{kind}")
    kept = [p for p in mod._PATTERNS if p[0] != kind]
    assert len(kept) == len(mod._PATTERNS) - 1, f"no pattern named {kind!r}: the mutation would change nothing"
    mod._PATTERNS[:] = kept
    assert _finds_counterexample(assert_no_surviving_run, mod, documents()), (
        f"redact.py without {kind!r} still passes the leak property: its generator does not reach that pattern")


# The scan() this PR replaced, verbatim: first-listed match wins, overlaps dropped.
_FIRST_WINS_SCAN = """def scan(text: str) -> list[Hit]:
    if not text:
        return []
    hits: list[Hit] = []
    occupied: list[tuple[int, int]] = []
    for kind, pat, gi in _PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span(gi) if gi else m.span()
            if any(not (e <= os_ or s >= oe) for os_, oe in occupied):
                continue  # overlap with earlier hit — skip
            occupied.append((s, e))
            value = m.group(gi) if gi else m.group(0)
            preview = _preview(value)
            hits.append(Hit(kind=kind, start=s, end=e, preview=preview))
    hits.sort(key=lambda h: h.start)
    return hits
"""


def _swap_scan(source: str) -> str:
    start = source.index("def scan(text: str) -> list[Hit]:")
    end = source.index("\n\ndef redact(", start)
    return source[:start] + _FIRST_WINS_SCAN + source[end:]


SOURCE_MUTATIONS = {
    # name: (anchor, replacement or callable, property, strategy)
    "scan back to first-listed-wins": ("def scan(text: str) -> list[Hit]:", _swap_scan,
                                       assert_no_surviving_run, documents()),
    "env_secret may match its own marker": (r"""(?!<redacted:[a-z_]+>['\"])""", "",
                                            assert_idempotent, TEXTS),
    "google key back to {35}\\b": (r'AIza[0-9A-Za-z_-]{35,}"', r'AIza[0-9A-Za-z_-]{35}\b"',
                                   assert_no_surviving_run, documents()),
    "openai key gets its trailing \\b back": (r'(?:proj-)?[A-Za-z0-9_-]{20,}"', r'(?:proj-)?[A-Za-z0-9_-]{20,}\b"',
                                              assert_no_surviving_run, documents()),
    "re.ASCII dropped": ("_A = re.ASCII", "_A = 0", assert_no_surviving_run, documents()),
}


@pytest.mark.parametrize("name", list(SOURCE_MUTATIONS))
def test_undoing_a_fix_turns_its_property_red(name: str) -> None:
    anchor, replacement, prop, strategy = SOURCE_MUTATIONS[name]
    source = REDACT_PATH.read_text(encoding="utf-8")
    assert source.count(anchor) == 1, (
        f"the anchor for {name!r} no longer appears exactly once in redact.py. The code moved; "
        f"update the anchor, do not delete the case — an unanchored mutation silently stops testing.")
    mutated = replacement(source) if callable(replacement) else source.replace(anchor, replacement)
    assert mutated != source
    mod = _load("clade_redact_mutated_" + "".join(c if c.isalnum() else "_" for c in name), mutated)
    assert _finds_counterexample(prop, mod, strategy), f"{name!r} did not turn its property red"
