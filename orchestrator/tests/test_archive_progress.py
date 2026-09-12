"""archive-progress.py holds PROGRESS.md to the cap its own skill sets.

Two bugs were found the first time it did a real archive, and both are the kind
that only appear on a live file:

1. It produced a file ONE LINE over the cap, because `plan()` measured the
   header before the pointer line the run then adds to it. A gate failing on a
   file the tool just produced is worse than no gate.
2. Entries carried their links two directories down unchanged, so
   `[TODO.md](TODO.md)` became a dead link the moment it was archived —
   `check-references.py` caught it, which is the only reason it was noticed.

Everything here runs against a synthetic PROGRESS.md under tmp_path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "configs" / "scripts" / "archive-progress.py"

HEADER = """# Progress Log

> **Role: a dated journal — what happened, when.** Open work lives in
> [TODO.md](TODO.md).

"""


def _entry(date: str, filler: int, link: bool = False) -> str:
    body = "\n".join(f"- point {i} for {date}" for i in range(filler))
    tail = "\n\nSee [TODO.md](TODO.md) and [PROGRESS.md](PROGRESS.md)." if link else ""
    return f"---\n### {date} — Entry for {date}\n\n{body}{tail}\n\n"


def _make_repo(tmp_path: Path, entries: str) -> Path:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "PROGRESS.md").write_text(HEADER + entries, encoding="utf-8")
    (tmp_path / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """The script resolves paths from its own location, so give it a copy."""
    script = repo / "archive-progress.py"
    if not script.exists():
        src = SCRIPT.read_text(encoding="utf-8")
        # REPO is parents[2] of the script; place it so parents[2] == repo.
        nest = repo / "configs" / "scripts"
        nest.mkdir(parents=True, exist_ok=True)
        (nest / "archive-progress.py").write_text(src, encoding="utf-8")
        script = nest / "archive-progress.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )


@pytest.fixture()
def big_repo(tmp_path: Path) -> Path:
    entries = "".join(_entry(f"2026-0{m}-15", 20, link=True) for m in range(1, 6))
    return _make_repo(tmp_path, entries)


def test_over_cap_is_reported_and_nothing_is_written(big_repo: Path) -> None:
    before = (big_repo / "PROGRESS.md").read_bytes()
    result = _run(big_repo, "--check")
    assert result.returncode == 1
    assert "over the" in result.stdout
    assert (big_repo / "PROGRESS.md").read_bytes() == before


@pytest.mark.parametrize("filler", [1, 2, 3, 4, 5, 6, 8, 11])
def test_apply_lands_at_or_under_the_cap(tmp_path: Path, filler: int) -> None:
    """The off-by-one: the header gains a pointer line after plan() measured it.

    Swept across entry sizes on purpose. A single fixture size passes whether or
    not the reserve exists, because the boundary has to land within three lines
    of the cap for the bug to show — the first version of this test was tuned to
    a size that missed it and stayed green against the broken script, which is
    the failure mode this whole repository keeps finding in its own gates.
    """
    # Enough entries that the cap is genuinely exceeded at EVERY filler size.
    # The first version generated twelve, which at small sizes never reached 100
    # lines, so the archiver had nothing to do and the test passed by not
    # exercising it — the same empty-run-looks-clean shape it is meant to catch.
    entries = "".join(_entry(f"2026-{m % 12 + 1:02d}-{m % 28 + 1:02d}", filler) for m in range(40))
    repo = _make_repo(tmp_path, entries)
    source_lines = len((repo / "PROGRESS.md").read_text(encoding="utf-8").splitlines())
    assert source_lines > 100, f"filler={filler}: fixture never exceeded the cap"

    assert _run(repo, "--apply").returncode == 0

    lines = len((repo / "PROGRESS.md").read_text(encoding="utf-8").splitlines())
    assert lines <= 100, (
        f"filler={filler}: archiver produced {lines} lines against its own 100-line cap"
    )
    # And its own gate must agree with what it just wrote.
    assert _run(repo, "--check").returncode == 0, f"filler={filler}: gate rejects its own output"


def test_archived_links_are_rerooted(big_repo: Path) -> None:
    """An entry moving two directories down takes its links with it."""
    _run(big_repo, "--apply")
    archives = list((big_repo / "docs" / "progress-archive").glob("*.md"))
    assert archives, "nothing was archived"
    text = "\n".join(p.read_text(encoding="utf-8") for p in archives)
    assert "](../../TODO.md)" in text
    assert "](TODO.md)" not in text.replace("](../../TODO.md)", "")


def test_no_entry_is_lost(big_repo: Path) -> None:
    source = (big_repo / "PROGRESS.md").read_text(encoding="utf-8")
    before = source.count("\n### ")
    _run(big_repo, "--apply")
    after = (big_repo / "PROGRESS.md").read_text(encoding="utf-8").count("\n### ")
    archived = sum(
        p.read_text(encoding="utf-8").count("\n### ")
        for p in (big_repo / "docs" / "progress-archive").glob("*.md")
    )
    assert after + archived == before, f"{before} entries in, {after + archived} out"


def test_active_entries_never_move(tmp_path: Path) -> None:
    """[ACTIVE] outranks age — that is the one exemption the skill grants."""
    entries = _entry("2026-01-15", 40).replace("Entry for", "[ACTIVE] Entry for")
    entries += "".join(_entry(f"2026-0{m}-15", 20) for m in range(2, 5))
    repo = _make_repo(tmp_path, entries)
    _run(repo, "--apply")
    kept = (repo / "PROGRESS.md").read_text(encoding="utf-8")
    assert "[ACTIVE]" in kept, "an [ACTIVE] entry was archived"


def test_under_cap_is_left_alone(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _entry("2026-05-01", 3))
    before = (repo / "PROGRESS.md").read_bytes()
    result = _run(repo, "--apply")
    assert result.returncode == 0
    assert "under the" in result.stdout
    assert (repo / "PROGRESS.md").read_bytes() == before
    assert not (repo / "docs" / "progress-archive").exists()


def test_rerunning_is_idempotent(big_repo: Path) -> None:
    _run(big_repo, "--apply")
    first = (big_repo / "PROGRESS.md").read_bytes()
    _run(big_repo, "--apply")
    assert (big_repo / "PROGRESS.md").read_bytes() == first


def test_pointer_is_replaced_not_appended(big_repo: Path) -> None:
    """Two runs used to leave two pointer lines claiming different totals.

    The real file ended up saying "60 archived" and "3 archived" on consecutive
    lines while the archive held 63. A stale count in the file that owns the
    count is worse than no count.
    """
    _run(big_repo, "--apply")
    # Add more entries and archive again, so a second pointer would appear.
    text = (big_repo / "PROGRESS.md").read_text(encoding="utf-8")
    extra = "".join(_entry(f"2026-1{n}-01", 20, link=True) for n in range(3))
    head, _, rest = text.partition("---\n")
    (big_repo / "PROGRESS.md").write_text(head + extra + "---\n" + rest, encoding="utf-8")
    _run(big_repo, "--apply")

    final = (big_repo / "PROGRESS.md").read_text(encoding="utf-8")
    pointers = [ln for ln in final.splitlines() if "docs/progress-archive/" in ln]
    assert len(pointers) == 1, f"expected one pointer line, got {len(pointers)}: {pointers}"

    archived = sum(
        p.read_text(encoding="utf-8").count("\n### ")
        for p in (big_repo / "docs" / "progress-archive").glob("*.md")
    )
    assert f"{archived} archived" in pointers[0], (
        f"pointer says {pointers[0]!r} but the archive holds {archived}"
    )
