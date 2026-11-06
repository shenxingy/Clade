"""Tests for configs/scripts/redact.py — secret detection lib + CLI."""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Load redact.py as a module without polluting sys.path globally.
# Register in sys.modules BEFORE exec_module so @dataclass on Python 3.14
# can resolve the module via cls.__module__.
_REDACT_PATH = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "redact.py"
_spec = importlib.util.spec_from_file_location("clade_redact", _REDACT_PATH)
assert _spec and _spec.loader
redact_mod = importlib.util.module_from_spec(_spec)
sys.modules["clade_redact"] = redact_mod
_spec.loader.exec_module(redact_mod)


# ─── Library tests ───────────────────────────────────────────────────────────

# Fake credentials, split so this file never carries a contiguous scannable
# literal — configs/scripts/checks.sh scans every staged diff and would block
# the commit that adds these tests. Same convention as tests/test-checks.sh.
FAKE_UNDERSCORE_KEY = "sk_" + "d69f1a2b3c4d5e6f7081920a1b2c3d4e5f60718293a4b5c6"
FAKE_STRIPE_LIVE = "sk_" + "live_51ABCdefGHIjklMNOpqrSTU12345"
FAKE_STRIPE_TEST = "sk_" + "test_51ABCdefGHIjklMNOpqrSTU12345"

def test_anthropic_key_detected() -> None:
    text = "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghij1234567890ABCDEFGHIJ1234567890XX"
    masked, hits = redact_mod.redact(text)
    assert hits, "should detect anthropic key"
    assert hits[0].kind == "anthropic_key"
    assert "sk-ant-" not in masked
    assert "<redacted:anthropic_key>" in masked


def test_github_token_detected() -> None:
    text = "token = ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    masked, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "github_token"
    assert "ghp_" not in masked


def test_aws_access_key_detected() -> None:
    masked, hits = redact_mod.redact("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert hits and hits[0].kind == "aws_access_key"


def test_jwt_detected() -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    _, hits = redact_mod.redact(jwt)
    assert hits and hits[0].kind == "jwt"


def test_generic_env_secret() -> None:
    text = 'API_KEY="abc123def456ghi789"'
    _, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "env_secret"


def test_pem_private_key() -> None:
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234\n"
        "-----END RSA PRIVATE KEY-----"
    )
    masked, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "private_key"
    assert "MIIEpAIBAAKCAQEA1234" not in masked


def test_underscore_prefixed_key_detected() -> None:
    # The hyphen-form `sk-` pattern does not cover `sk_`, and env_secret needs
    # quotes — so this shape used to escape every pattern in the file.
    text = "the key is sk_" + "d69f1a2b3c4d5e6f7081920a1b2c3d4e5f60718293a4b5c6"
    masked, hits = redact_mod.redact(text)
    assert hits, "should detect underscore-prefixed vendor key"
    assert hits[0].kind == "generic_secret_key"
    assert "sk_d69" not in masked
    assert "<redacted:generic_secret_key>" in masked


def test_unquoted_underscore_key_in_env_assignment_detected() -> None:
    # `\bAPI_KEY` finds no word boundary inside SCAMAI_API_KEY, so env_secret
    # misses this even when quoted. The value pattern is what has to catch it.
    text = "SCAMAI_API_KEY=" + FAKE_UNDERSCORE_KEY
    masked, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "generic_secret_key"
    assert "sk_d69" not in masked


def test_stripe_live_key_keeps_specific_label() -> None:
    # Pins the ordering claim: a future reorder that let the generic pattern
    # shadow stripe_key would flip this label.
    _, hits = redact_mod.redact(FAKE_STRIPE_LIVE)
    assert hits and hits[0].kind == "stripe_key"


def test_stripe_test_key_detected() -> None:
    # Previously matched nothing: stripe_key demanded `_live_`, and the generic
    # pattern cannot span `test_` (4 alnum before the second underscore).
    masked, hits = redact_mod.redact(FAKE_STRIPE_TEST)
    assert hits and hits[0].kind == "stripe_key"
    assert "sk_test_51" not in masked


def test_no_false_positive_on_underscore_suffixed_identifier() -> None:
    # Regression guard for the \b. This is the exact shape that appears 14x in
    # the real correction corpus (task_count, task_live, task_progress, ...).
    _, hits = redact_mod.redact("task_abcdefghijklmnopqrstuvwxyz0123456789ABCD")
    assert hits == []


def test_no_false_positive_on_short_strings() -> None:
    # Short literals that look like prefixes shouldn't trip the detector.
    _, hits = redact_mod.redact("sk-ant-foo and ghp_short and sk-test")
    assert hits == []


def test_idempotent() -> None:
    text = "X-API-Key: ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    masked, _ = redact_mod.redact(text)
    masked_again, hits_again = redact_mod.redact(masked)
    assert masked == masked_again
    assert hits_again == []


def test_preview_truncates() -> None:
    text = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    _, hits = redact_mod.redact(text)
    assert hits[0].preview.startswith("ghp_ab")
    assert hits[0].preview.endswith("6789")
    assert "..." in hits[0].preview


def test_empty_input() -> None:
    masked, hits = redact_mod.redact("")
    assert masked == ""
    assert hits == []


def test_preserves_non_secret_text() -> None:
    text = "before sk-ant-api03-abcdefghij1234567890ABCDEFGHIJ1234567890XX after"
    masked, _ = redact_mod.redact(text)
    assert masked.startswith("before <redacted:")
    assert masked.endswith(" after")


# ─── CLI tests ──────────────────────────────────────────────────────────────

def test_cli_check_returns_1_on_hit() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--check"],
        input="ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 1
    assert "github_token" in proc.stderr


def test_cli_check_flags_underscore_key() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--check"],
        input=FAKE_UNDERSCORE_KEY,
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 1
    assert "generic_secret_key" in proc.stderr


def test_cli_check_returns_0_on_clean() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--check"],
        input="hello world\nno secrets here",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_cli_default_prints_redacted() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH)],
        input="key=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert "ghp_" not in proc.stdout
    assert "<redacted:github_token>" in proc.stdout


def test_cli_json_output_shape() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--json"],
        input="key=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert "redacted" in payload
    assert "hits" in payload
    assert payload["hits"][0]["kind"] == "github_token"

# ─── Non-ASCII context ────────────────────────────────────────────────────────
# Python's \w, and therefore \b, is Unicode-aware by default: 是 and к are word
# characters, so there is no boundary between them and the `s` of `sk-`. Every
# \b-anchored pattern in redact.py silently failed on a key pasted into Chinese
# or Cyrillic prose — which is the path that matters, because the main caller is
# correction-detector.sh and its own trigger list is 不要|别用|错了|改回|不对.


def test_key_in_chinese_prose_is_detected() -> None:
    """The case the redactor exists for, and the one that did not work."""

    text = "不对，改回原来的写法，key是" + "sk-ant-" + "api03-" + "A" * 45
    masked, hits = redact_mod.redact(text)
    assert hits, "a key adjacent to CJK text must still be detected"
    assert "sk-ant-" not in masked


def test_github_token_after_chinese_is_detected() -> None:
    text = "别用这个，token是" + "ghp_" + "a" * 36
    masked, hits = redact_mod.redact(text)
    assert hits
    assert "ghp_" not in masked


def test_aws_key_between_chinese_is_detected() -> None:
    text = "错了，密钥" + "AKIA" + "IOSFODNN7EXAMPLE" + "别提交"
    masked, hits = redact_mod.redact(text)
    assert hits
    assert "AKIA" not in masked


def test_key_after_cyrillic_is_detected() -> None:
    masked, hits = redact_mod.redact("ключ" + "sk_" + "b" * 40)
    assert hits
    assert "sk_" not in masked


def test_task_id_in_chinese_prose_is_still_not_a_secret() -> None:
    """The ASCII fix must not cost the false-positive guard."""

    _, hits = redact_mod.redact("这是一个" + "task_" + "c" * 32 + "的任务")
    assert not hits


def test_every_pattern_is_ascii_anchored() -> None:
    """A pattern added later without re.ASCII reopens the whole hole."""

    import re

    missing = [kind for kind, rx, _ in redact_mod._PATTERNS if not rx.flags & re.ASCII]
    assert not missing, f"patterns missing re.ASCII: {missing}"


# ─── Oldest interpreter ──────────────────────────────────────────────────────
# The hooks run redact.py under whatever `python3` the machine has:
# correction-detector.sh and checks.sh call `python3 redact.py`, and
# secret-scanner.sh runs it through its `#!/usr/bin/env python3` line. install.sh
# accepts any python3 that starts. The oldest one this repository names is 3.8:
# context-policy.py keeps its `tuple[...]` aliases under TYPE_CHECKING for "the
# Python 3.8 install.sh accepts".
#
# A redact.py that cannot import there is worse than a no-op. A traceback exits
# 1, which is what `--check` returns for a hit, so checks.sh refuses every
# commit that adds a line and secret-scanner.sh tells the model every prompt
# holds a credential. A module-level `_Piece = tuple[...]` did exactly that on
# 3.8.
#
# CI runs 3.12, so importing the module there proves nothing about 3.8. The AST
# check runs on every interpreter; the subprocess check runs where python3.8
# exists and covers what the AST cannot see, such as a newer stdlib API.
HOOK_PYTHON_FLOOR = (3, 8)
_PEP585_BUILTINS = frozenset({"tuple", "list", "dict", "set", "frozenset", "type"})
# Modules whose classes became subscriptable at runtime in 3.9 (PEP 585).
# typing's own aliases (Tuple, Iterable, ...) always were.
_PEP585_MODULES = frozenset({"collections", "collections.abc", "contextlib", "re"})
_TYPE_NAMES = _PEP585_BUILTINS | {"int", "str", "bytes", "bytearray", "float", "complex", "bool", "object"}


def newer_than_floor(source: str) -> list[str]:
    """Constructs in `source` that a HOOK_PYTHON_FLOOR interpreter rejects or crashes on.

    Grammar is ast.parse's feature_version. On top of that, two things parse
    on 3.8 and raise when they run: a subscripted builtin or collections.abc
    class (PEP 585, 3.9) and a `|` between types (PEP 604, 3.10). Annotations
    are skipped only under `from __future__ import annotations`, which keeps
    them unevaluated, and an `if TYPE_CHECKING:` body never runs. Function
    bodies are checked: they run when the hook calls them.
    """
    try:
        tree = ast.parse(source, feature_version=HOOK_PYTHON_FLOOR)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: {exc.msg}"]
    lazy = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)
    imported = {a.asname or a.name for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module in _PEP585_MODULES for a in n.names}

    def generic(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in _PEP585_BUILTINS or node.id in imported
        return isinstance(node, ast.Attribute) and ast.unparse(node.value) in _PEP585_MODULES

    def is_type(node: ast.AST) -> bool:
        return ((isinstance(node, ast.Constant) and node.value is None)
                or (isinstance(node, ast.Name) and (node.id in _TYPE_NAMES or node.id in imported))
                or (isinstance(node, ast.Subscript) and generic(node.value)))

    found: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Subscript) and generic(node.value):
            found.append(f"line {node.lineno}: {ast.unparse(node)} subscripts a builtin at runtime (3.9+)")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr) and (is_type(node.left) or is_type(node.right)):
            found.append(f"line {node.lineno}: {ast.unparse(node)} is a runtime union of types (3.10+)")
        type_checking = isinstance(node, ast.If) and ast.unparse(node.test).endswith("TYPE_CHECKING")
        for field, value in ast.iter_fields(node):
            if (lazy and field in ("annotation", "returns")) or (type_checking and field == "body"):
                continue
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, ast.AST):
                    visit(child)

    visit(tree)
    return found


_REDACT_SOURCE = _REDACT_PATH.read_text(encoding="utf-8")
_PIECE_ALIAS = "_Piece = Tuple[int, int, int, int, bool]"


def test_redact_runs_on_the_oldest_python_the_hooks_name() -> None:
    assert newer_than_floor(_REDACT_SOURCE) == []


def test_the_floor_check_finds_the_alias_that_broke_it() -> None:
    """The mutation: put back the module-level `tuple[...]` the check exists for."""
    assert _REDACT_SOURCE.count(_PIECE_ALIAS) == 1, "the alias moved; update the anchor, do not delete the case"
    mutated = _REDACT_SOURCE.replace(_PIECE_ALIAS, _PIECE_ALIAS.replace("Tuple[", "tuple["))
    assert newer_than_floor(mutated)


# The checker's own controls: what it must report, and what it must leave alone.
FLOOR_CASES = {
    "a subscripted builtin at module level": ("X = tuple[int, str]\n", True),
    "a subscripted builtin in a function body": ("def f():\n    return list[int]\n", True),
    "a subscripted collections.abc import": ("from collections.abc import Callable\nX = Callable[[], int]\n", True),
    "a subscripted module attribute": ("import re\nX = re.Pattern[str]\n", True),
    "a union of types": ("X = int | None\n", True),
    "an annotation with no __future__ import": ("def f(x: tuple[int]) -> None:\n    pass\n", True),
    "grammar newer than the floor": ("match x:\n    case 1:\n        pass\n", True),
    "annotations under the __future__ import": (
        "from __future__ import annotations\nX: dict[str, int] = {}\n"
        "def f(x: tuple[int]) -> list[int | None]:\n    y: set[str] = set()\n    return []\n", False),
    "a TYPE_CHECKING body": ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    X = tuple[int]\n", False),
    "typing's own alias": ("from typing import Tuple\nX = Tuple[int, int]\n", False),
    "a | between flags and ints": ("import re\nF = re.I | re.M\nx = 1 | 2\n", False),
    "an ordinary subscript": ("import sys\nx = sys.argv[1:]\n", False),
}


@pytest.mark.parametrize("name", list(FLOOR_CASES))
def test_the_floor_check_reports_exactly_what_breaks_the_floor(name: str) -> None:
    source, breaks = FLOOR_CASES[name]
    assert bool(newer_than_floor(source)) is breaks, newer_than_floor(source)


_FLOOR_PYTHON = shutil.which("python{}.{}".format(*HOOK_PYTHON_FLOOR))
# Inputs that reach the merge and a second read, not only the import.
_FLOOR_INPUTS = [
    "key " + "sk-" + "a" * 24 + " end",
    'sec' + 'ret: "' + "-----BEGIN " + "PRIVATE KEY-----\\nMIIE" + "0" * 16 + "\\n-----END " + "PRIVATE KEY-----" + '\\n"',
    "AWS_SECRET_ACCESS_" + "KEY=" + "0" * 40 + "AK" + "IA" + "0" * 16,
]


def _run_under(python: str, script: Path, text: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([python, str(script), *argv], input=text, capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(_FLOOR_PYTHON is None, reason="no python3.8 on PATH; the AST check above still ran")
def test_redact_under_the_floor_interpreter_matches_this_one(tmp_path: Path) -> None:
    assert _FLOOR_PYTHON is not None
    for text in _FLOOR_INPUTS:
        here, there = _run_under(sys.executable, _REDACT_PATH, text), _run_under(_FLOOR_PYTHON, _REDACT_PATH, text)
        assert (there.returncode, there.stdout, there.stderr) == (0, here.stdout, ""), text
        assert "<redacted:" in there.stdout
    assert _run_under(_FLOOR_PYTHON, _REDACT_PATH, "hello world", "--check").returncode == 0
    # Control: the same run over the alias this file was fixed for must fail there.
    assert _REDACT_SOURCE.count(_PIECE_ALIAS) == 1, "the alias moved; update the anchor, do not delete the control"
    broken = tmp_path / "redact.py"
    broken.write_text(_REDACT_SOURCE.replace(_PIECE_ALIAS, _PIECE_ALIAS.replace("Tuple[", "tuple[")), encoding="utf-8")
    assert _run_under(_FLOOR_PYTHON, broken, "hello world", "--check").returncode != 0
