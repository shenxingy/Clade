#!/usr/bin/env python3
"""keep-sessions.py — keep the sessions a correction points at, past Claude Code's 30-day cleanup.

Why this exists
---------------
"Sessions where an engineer corrected or reverted the agent are ready-made
evals" (Migdal, *Your agent session transcripts are precious*, Quesma,
2026-10-01). Claude Code deletes a transcript 30 days after its last write
(``cleanupPeriodDays``), and the record of what the agent did before it was
corrected goes with it. ``~/.claude/corrections/history.jsonl`` says which
sessions were corrected: since the session link (TODO.md, "Correction records
carry no session link", Step 1) both correction detectors write ``session_id``
and ``transcript_path`` into each record; older records carry neither. This
copies those sessions somewhere the cleanup does not reach. Keeping only
corrected sessions is this repository's narrowing, chosen for cost; the essay
keeps every session.

What it keeps
-------------
Every history record is read with ``transcripts.iter_records``. Malformed lines
(a sync conflict marker, a half-written line) are counted. A record is:

- **excluded** when ``revert_scope`` is ``"probe"``: the agent's own mutation
  test, not a rejection;
- **linked** when its ``transcript_path`` is a main-thread transcript under a
  root of ``transcripts.default_roots()``, or its ``session_id`` names one
  there (the newest copy when two roots hold the id). A path outside every root
  is never read, whatever the record says;
- **unlinkable** otherwise, counted by reason: no link at all (records written
  before the detectors recorded one), or no transcript under any root (deleted
  by the cleanup, or written on another machine; a session kept on an earlier
  run is counted apart, because its copy is here).

A linked session is **private**, and skipped, when a ``private-sessions/<id>``
marker exists under any config directory (``~/.claude``, every
``~/.claude-profiles/<p>``, ``$CLAUDE_CONFIG_DIR``), when the record's project
holds ``.claude/conversation-mode``, or when it is listed in a config
directory's ``private-projects``. The marker is checked when copying, not when
the record was written, so a session marked private later is not copied again.
A copy kept before it was marked is reported, never deleted.

For each kept session, the main transcript and every regular file under its
``<session>/`` directory (subagent and Workflow transcripts, tool results) go
to ``<dest>/<session_id>/``: ``transcript.jsonl.gz``, ``session/<path>.gz`` and
a ``manifest.json``. Default dest ``~/.local/share/clade/sessions``, outside
``~/.claude``, because that directory (and the dotfiles sync store) syncs to a
remote; a ``--dest`` inside either is refused. Directories are 0700 and files
0600.

Redaction goes through ``redact.py`` beside this file. A JSONL record is
re-serialized after every string in it, key or value, is masked, so a mask can
never break the JSON. A ``.json`` file is treated the same way. Any other file
that decodes as UTF-8 is masked as text. A file that does not decode (an image,
a PDF page) cannot be redacted and is not kept. A symlink is never followed.
The manifest records how many masks of each kind were applied, never the value
or a preview of it.

Compression is gzip from the standard library: the zstd the TODO item named is
not in it, and lzma, on one 8.1 MB transcript on the author's host
(2026-11-06), compressed 7.1x against gzip's 3.8x at a twelfth of its speed
(2 against 25 MB/s). ``zcat`` reads the result anywhere. Redaction, not
compression, sets the pace: 3.8 MB/s end to end on one 5.2 MB transcript on the
same host, under load.

Re-running is idempotent. A file is rewritten only when its source changed
(size or mtime) or the redaction patterns did, so a second run writes nothing.
A source that is gone leaves its copy in place: nothing here deletes a kept
session.

Usage
-----
    python3 configs/scripts/keep-sessions.py              # what it would keep; writes nothing
    python3 configs/scripts/keep-sessions.py --apply      # keep them
    python3 configs/scripts/keep-sessions.py --self-test  # can each guard still go red?

``radar-cron.sh`` runs ``--apply`` once a week, after its sweep; a failure is
logged and never fails the sweep. The last line printed is a one-line summary,
which is what the cron log keeps.

Stdlib only, on purpose: cron runs it with whatever ``python3`` is on PATH.
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import datetime
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import redact  # beside this file
import transcripts  # beside this file

SCHEMA = "clade.kept-session/v1"
TRANSCRIPT_NAME = "transcript.jsonl.gz"
SESSION_PREFIX = "session/"

# The correction hooks keep exactly this character set in a session id.
_SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,128}")

NO_LINK = "no session link (written before the detectors recorded one, or the hook input lacked it)"
NOT_FOUND = "no transcript under any root (deleted by the 30-day cleanup, or written on another machine)"
KEPT_EARLIER = "transcript gone, kept by an earlier run"
BINARY = "binary: does not decode as UTF-8, so it cannot be redacted; not kept"


# ─── Where things are ───────────────────────────────────────────────────────


def default_history() -> Path:
    """Where both correction hooks append: ``$HOME/.claude``, whatever the profile."""

    return Path.home() / ".claude" / "corrections" / "history.jsonl"


def default_dest() -> Path:
    return Path.home() / ".local" / "share" / "clade" / "sessions"


def config_dirs() -> list[Path]:
    """Every Claude config directory: the parent of each transcript root."""

    return [root.parent for root in transcripts.default_roots()]


def _sync_dir(config: Path) -> Path | None:
    """``SYNC_DIR`` from a config directory's ``.sync-config``, the dotfiles sync store."""

    try:
        text = (config / ".sync-config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("SYNC_DIR="):
            value = line[len("SYNC_DIR="):].strip().strip("'\"")
            return Path(value).expanduser() if value else None
    return None


def synced_places() -> list[tuple[str, Path]]:
    """Directories that sync to a remote, so a kept session must not land inside one."""

    places = [("the Claude config directory", config) for config in config_dirs()]
    places.append(("the profiles directory", Path.home() / ".claude-profiles"))
    for config in config_dirs():
        store = _sync_dir(config)
        if store is not None:
            places.append(("the dotfiles sync store", store))
    return places


def refuse_dest(dest: Path) -> str | None:
    """Why ``dest`` must not be used, or None."""

    target = Path(os.path.realpath(dest))
    for name, place in synced_places():
        real = Path(os.path.realpath(place))
        if target == real or real in target.parents:
            return f"--dest {dest} is inside {name} ({place}), which syncs to a remote; keep sessions outside it"
    if target.exists() and target.stat().st_uid != os.geteuid():
        return f"--dest {dest} belongs to another user"
    return None


# ─── Which sessions ─────────────────────────────────────────────────────────


@dataclass
class Session:
    session_id: str
    transcript: Path
    records: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Selection:
    records: int = 0
    malformed: int = 0
    probe: int = 0
    unlinkable: dict[str, int] = field(default_factory=dict)
    private: dict[str, str] = field(default_factory=dict)  # session id -> why
    private_records: int = 0
    linked_records: int = 0
    sessions: dict[str, Session] = field(default_factory=dict)


class TranscriptIndex:
    """The main-thread transcripts under every root, by session id and by real path."""

    def __init__(self, roots: list[Path]) -> None:
        self.by_id: dict[str, Path] = {}
        self.by_real: dict[str, Path] = {}
        # Oldest first, so where two roots hold one id the newest copy wins.
        for path in transcripts.find_transcripts(roots, None):
            self.by_id[path.stem] = path
            self.by_real[os.path.realpath(path)] = path


def _session_id(value: object) -> str | None:
    return value if isinstance(value, str) and _SESSION_ID.fullmatch(value) else None


def locate(record: dict[str, Any], index: TranscriptIndex) -> tuple[str | None, Path | None]:
    """(session id, transcript) for a record; the transcript is None when it cannot be found."""

    sid = _session_id(record.get("session_id"))
    path = record.get("transcript_path")
    if isinstance(path, str) and path:
        known = index.by_real.get(os.path.realpath(path))
        if known is not None and sid in (None, known.stem) and _session_id(known.stem):
            return known.stem, known
        sid = sid or _session_id(Path(path).stem)
    if sid is None:
        return None, None
    return sid, index.by_id.get(sid)


class Privacy:
    """The three private signals the correction hooks honour, read once."""

    def __init__(self) -> None:
        self.marker_dirs = [config / "private-sessions" for config in config_dirs()]
        self.projects: list[str] = []
        for config in config_dirs():
            try:
                lines = (config / "private-projects").read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            self.projects.extend(p.strip().rstrip("/") for p in lines if p.strip().rstrip("/"))

    def why(self, sid: str, project: object) -> str | None:
        if any((markers / sid).exists() for markers in self.marker_dirs):
            return "private-sessions marker"
        if isinstance(project, str) and project.startswith("/"):
            if (Path(project) / ".claude" / "conversation-mode").exists():
                return "conversation-mode project"
            if any(project == p or project.startswith(p + "/") for p in self.projects):
                return "listed in private-projects"
        return None


def select(history: Path, index: TranscriptIndex, privacy: Privacy, dest: Path) -> Selection:
    sel = Selection()
    tally: dict[str, int] = {}
    for record in transcripts.iter_records(history, tally):
        sel.records += 1
        if record.get("revert_scope") == "probe":
            sel.probe += 1
            continue
        sid, transcript = locate(record, index)
        if sid is None or transcript is None:
            if sid is None:
                reason = NO_LINK
            elif (dest / sid / "manifest.json").is_file():
                reason = KEPT_EARLIER
            else:
                reason = NOT_FOUND
            sel.unlinkable[reason] = sel.unlinkable.get(reason, 0) + 1
            continue
        why = sel.private.get(sid) or privacy.why(sid, record.get("project"))
        if why:
            sel.private[sid] = why
            sel.private_records += 1
            earlier = sel.sessions.pop(sid, None)
            if earlier is not None:  # a session made private by a later record
                sel.private_records += len(earlier.records)
            continue
        session = sel.sessions.setdefault(sid, Session(sid, transcript))
        session.records.append({key: record.get(key) for key in ("timestamp", "type", "revert_scope")})
    sel.malformed = tally.get("malformed", 0) + tally.get("truncated", 0)
    sel.linked_records = sum(len(s.records) for s in sel.sessions.values())
    return sel


# ─── Redaction ──────────────────────────────────────────────────────────────


def redactor_fingerprint() -> str:
    """Changes whenever redact.py's patterns do, so a new pattern reaches sessions still on disk."""

    digest = hashlib.sha256()
    for kind, pattern, group in redact._PATTERNS:
        digest.update(f"{kind}\0{pattern.pattern}\0{pattern.flags}\0{group}\n".encode())
    return digest.hexdigest()[:16]


def _mask(text: str, counts: dict[str, int]) -> str:
    masked, hits = redact.redact(text)
    for hit in hits:
        counts[hit.kind] = counts.get(hit.kind, 0) + 1
    return masked


def scrub(value: Any, counts: dict[str, int]) -> Any:
    """``value`` with every string in it, key or value, masked."""

    if isinstance(value, str):
        return _mask(value, counts)
    if isinstance(value, list):
        return [scrub(item, counts) for item in value]
    if isinstance(value, dict):
        return {_mask(key, counts): scrub(item, counts) for key, item in value.items()}
    return value


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Unredactable(Exception):
    """A file that does not decode as UTF-8 cannot be redacted, so it is not kept."""


def _head_is_text(path: Path) -> bool:
    """Whether the first 8 KiB decode as UTF-8, so a dry run can say which files will not be kept."""

    with open(path, "rb") as handle:
        head = handle.read(8192)
    try:
        # An incremental decoder, so a character cut at the 8 KiB edge is not a failure.
        codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
    except UnicodeDecodeError:
        return False
    return True


def redacted_chunks(path: Path, entry: dict[str, Any]) -> Iterator[str]:
    """The redacted content of one source file, in pieces; fills ``entry`` with what was done."""

    counts: dict[str, int] = {}
    entry["redactions"] = counts
    if path.suffix == ".jsonl":
        tally: dict[str, int] = {}
        for record in transcripts.iter_records(path, tally):
            yield _dump(scrub(record, counts)) + "\n"
        entry["records"] = tally.get("records", 0)
        entry["malformed"] = tally.get("malformed", 0)
        entry["truncated"] = tally.get("truncated", 0)
        return
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise Unredactable(path) from None
    if path.suffix == ".json":
        try:
            yield _dump(scrub(json.loads(text), counts))
            return
        except ValueError:
            pass
    yield _mask(text, counts)


# ─── Writing ────────────────────────────────────────────────────────────────


def _mkdir_private(path: Path) -> None:
    """Create ``path`` 0700, and every missing parent too. ``mkdir(parents=True)`` would leave those 0755."""

    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        with contextlib.suppress(FileExistsError):
            directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
    os.chmod(path, 0o700)


def _write_private(target: Path, data: Iterable[bytes]) -> None:
    """Write ``target`` 0600, atomically: a reader never sees half a file."""

    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            for chunk in data:
                handle.write(chunk)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _gzip(chunks: Iterable[str]) -> Iterator[bytes]:
    """gzip of the UTF-8 text, with a fixed header mtime, so equal input gives equal bytes.

    A lone surrogate (JSON can carry one as ``\\udXXX``) is written back as that
    escape, which a JSON reader turns into the same string.
    """

    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
        for chunk in chunks:
            gz.write(chunk.encode("utf-8", "backslashreplace"))
            if buffer.tell() >= 1 << 20:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()
    yield buffer.getvalue()


@dataclass
class Source:
    name: str  # where it goes, relative to the session's dest dir
    path: Path
    rel: str  # where it came from, relative to the transcript's directory
    size: int = 0
    mtime_ns: int = 0
    skip: str | None = None


def sources(session: Session) -> list[Source]:
    """The main transcript and every regular file under its ``<session>/`` directory."""

    transcript = session.transcript
    found = [Source(TRANSCRIPT_NAME, transcript, transcript.name)]
    session_dir = transcript.with_suffix("")
    if session_dir.is_dir() and not session_dir.is_symlink():
        for top, dirs, files in os.walk(session_dir, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                path = Path(top) / name
                rel = path.relative_to(session_dir).as_posix()
                found.append(Source(f"{SESSION_PREFIX}{rel}.gz", path, f"{session_dir.name}/{rel}"))
            # A symlinked directory is listed in dirs and never entered (followlinks=False);
            # name it, so the manifest says what was not kept.
            for name in dirs:
                path = Path(top) / name
                if path.is_symlink():
                    rel = path.relative_to(session_dir).as_posix()
                    found.append(Source(f"{SESSION_PREFIX}{rel}.gz", path, f"{session_dir.name}/{rel}"))
    for source in found:
        try:
            st = os.lstat(source.path)
        except OSError as exc:
            source.skip = f"unreadable: {exc.strerror or exc}"
            continue
        source.size, source.mtime_ns = st.st_size, st.st_mtime_ns
        if os.path.islink(source.path):
            source.skip = "symlink: not followed"
        elif not os.path.isfile(source.path):
            source.skip = "not a regular file"
        elif source.path.suffix != ".jsonl":
            try:
                if not _head_is_text(source.path):
                    source.skip = BINARY
            except OSError as exc:
                source.skip = f"unreadable: {exc.strerror or exc}"
    return found


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_source(source: Source, old: dict[str, Any]) -> bool:
    return old.get("size") == source.size and old.get("mtime_ns") == source.mtime_ns


def _unchanged(source: Source, old: object, fingerprint: str, dest_dir: Path) -> bool:
    return (
        isinstance(old, dict)
        and _same_source(source, old)
        and old.get("redactor") == fingerprint
        and (dest_dir / source.name).is_file()
    )


@dataclass
class Outcome:
    status: str  # new | updated | unchanged
    written: int = 0
    pending: int = 0
    pending_bytes: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    gone: int = 0


def keep(session: Session, dest: Path, fingerprint: str, apply: bool) -> Outcome:
    """Copy one session into ``dest/<id>``; with ``apply`` False, only say what would change."""

    dest_dir = dest / session.session_id
    manifest_path = dest_dir / "manifest.json"
    old = _load_manifest(manifest_path)
    old_files: dict[str, Any] = old["files"] if isinstance(old.get("files"), dict) else {}
    old_corrections = old["corrections"] if isinstance(old.get("corrections"), list) else []
    old_skipped: dict[str, Any] = old["skipped"] if isinstance(old.get("skipped"), dict) else {}
    # Copies, not the loaded entries: source_gone is set below, and the manifest is
    # rewritten only when it differs from what was loaded.
    files: dict[str, Any] = {name: dict(e) if isinstance(e, dict) else e for name, e in old_files.items()}
    skipped: dict[str, dict[str, Any]] = {}
    outcome = Outcome("new" if not old else "unchanged")
    found = sources(session)
    if apply:
        _mkdir_private(dest_dir)
    for source in found:
        prior = old_skipped.get(source.name)
        if not source.skip and isinstance(prior, dict) and prior.get("why") == BINARY and _same_source(source, prior):
            source.skip = BINARY  # it failed to decode last time, and has not changed since
        if source.skip:
            skipped[source.name] = {"why": source.skip, "size": source.size, "mtime_ns": source.mtime_ns}
            outcome.skipped += 1
            continue
        if _unchanged(source, old_files.get(source.name), fingerprint, dest_dir):
            continue
        if outcome.status == "unchanged":
            outcome.status = "updated"
        outcome.pending += 1
        outcome.pending_bytes += source.size
        if not apply:
            continue
        entry: dict[str, Any] = {
            "source": source.rel,
            "size": source.size,
            "mtime_ns": source.mtime_ns,
            "redactor": fingerprint,
        }
        target = dest_dir / source.name
        try:
            _mkdir_private(target.parent)
            _write_private(target, _gzip(redacted_chunks(source.path, entry)))
        except Unredactable:
            skipped[source.name] = {"why": BINARY, "size": source.size, "mtime_ns": source.mtime_ns}
            outcome.skipped += 1
            continue
        except OSError as exc:
            outcome.errors.append(f"{source.rel}: {exc.strerror or exc}")
            continue
        entry["written"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        files[source.name] = entry
        outcome.written += 1
    present = {source.name for source in found}
    for name, entry in files.items():
        if isinstance(entry, dict):
            entry["source_gone"] = name not in present
            outcome.gone += entry["source_gone"]
    manifest = {
        "schema": SCHEMA,
        "session_id": session.session_id,
        "project_dir": session.transcript.parent.name,
        "corrections": sorted(
            {_dump(r): r for r in [*old_corrections, *session.records] if isinstance(r, dict)}.values(),
            key=lambda r: str(r.get("timestamp")),
        ),
        "files": dict(sorted(files.items())),
        "skipped": dict(sorted(skipped.items())),
    }
    if apply and manifest != {key: old.get(key) for key in manifest}:
        _write_private(manifest_path, [(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n").encode("utf-8")])
    return outcome


# ─── Report ─────────────────────────────────────────────────────────────────


def _n(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _mb(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


@contextlib.contextmanager
def _lock(dest: Path) -> Iterator[bool]:
    """An exclusive lock on ``dest/.lock``; yields False when another run holds it."""

    try:
        import fcntl
    except ImportError:  # not POSIX: no lock, and the writes are still atomic per file
        yield True
        return
    fd = os.open(dest / ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def run(history: Path, dest: Path, apply: bool) -> int:
    index = TranscriptIndex(transcripts.default_roots())
    sel = select(history, index, Privacy(), dest)
    mode = "kept" if apply else "would keep"
    print(f"keep-sessions: {'writing to' if apply else 'dry run, nothing written (--apply writes) —'} {dest}")
    print(f"history {history}: {_n(sel.records, 'record')}, {_n(sel.malformed, 'unreadable line')}")
    print(f"  excluded    {_n(sel.probe, 'probe record')} (the agent's own mutation tests)")
    unlinkable = sum(sel.unlinkable.values())
    print(f"  unlinkable  {_n(unlinkable, 'record')}")
    for reason, count in sorted(sel.unlinkable.items(), key=lambda item: -item[1]):
        print(f"              {count:,} {reason}")
    print(f"  private     {_n(len(sel.private), 'session')} ({_n(sel.private_records, 'record')}), skipped")
    print(f"  linked      {_n(sel.linked_records, 'record')} in {_n(len(sel.sessions), 'session')}")

    fingerprint = redactor_fingerprint()
    totals = {"new": 0, "updated": 0, "unchanged": 0}
    written = pending = pending_bytes = gone = 0
    failed: list[str] = []
    rows: list[str] = []
    for sid, session in sorted(sel.sessions.items()):
        try:
            outcome = keep(session, dest, fingerprint, apply)
        except OSError as exc:
            failed.append(f"{sid}: {exc.strerror or exc}")
            continue
        totals[outcome.status] += 1
        written += outcome.written
        pending += outcome.pending
        pending_bytes += outcome.pending_bytes
        gone += outcome.gone
        failed.extend(f"{sid}: {error}" for error in outcome.errors)
        rows.append(
            f"  {sid}  {outcome.status:<9} {_n(len(session.records), 'correction'):>14}"
            f"  {_mb(outcome.pending_bytes):>9} to write  {outcome.skipped} not kept  {session.transcript.parent.name}"
        )
    for sid, why in sorted(sel.private.items()):
        if (dest / sid / "manifest.json").is_file():
            rows.append(f"  {sid}  private ({why}); a copy kept before is still at {dest / sid}, remove it by hand")
    for row in rows:
        print(row)
    for failure in failed:
        print(f"  FAILED {failure}", file=sys.stderr)
    if gone:
        print(f"  {_n(gone, 'kept file')} outlived its source, as intended")
    print(
        f"keep-sessions: {mode} {_n(len(sel.sessions), 'session')} "
        f"({totals['new']} new, {totals['updated']} updated, {totals['unchanged']} unchanged), "
        + (f"{_n(written, 'file')} written from {_mb(pending_bytes)}; " if apply
           else f"{_n(pending, 'file')} ({_mb(pending_bytes)}) to write; ")
        + f"{_n(unlinkable, 'record')} unlinkable; {_n(len(sel.private), 'private session')} skipped"
        + (f"; {len(failed)} FAILED" if failed else "")
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Keep the transcripts of corrected sessions past Claude Code's 30-day cleanup, redacted.",
        epilog="Without --apply nothing is written.",
    )
    parser.add_argument("--apply", action="store_true", help="Write the copies (default: only report).")
    parser.add_argument("--dest", type=Path, help="Where to keep them (default ~/.local/share/clade/sessions).")
    parser.add_argument("--history", type=Path, help="Correction history (default ~/.claude/corrections/history.jsonl).")
    parser.add_argument("--self-test", action="store_true", help="Ask every guard whether it can still go red.")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()

    dest = Path(os.path.abspath((args.dest or default_dest()).expanduser()))
    refusal = refuse_dest(dest)
    if refusal:
        print(f"keep-sessions: {refusal}", file=sys.stderr)
        return 2
    history = (args.history or default_history()).expanduser()
    if not history.is_file():
        print(f"keep-sessions: no correction history at {history}: nothing to keep")
        return 2 if args.history else 0
    try:
        if not args.apply:
            return run(history, dest, apply=False)
        _mkdir_private(dest)
        with _lock(dest) as held:
            if not held:
                print(f"keep-sessions: another run holds {dest / '.lock'}; nothing done")
                return 0
            return run(history, dest, apply=True)
    except OSError as exc:
        print(f"keep-sessions: FAILED: {exc}", file=sys.stderr)
        return 1




# ─── Self-test ──────────────────────────────────────────────────────────────
# Drives main() in-process on a synthetic HOME: two linked sessions, and a
# negative control for each exclusion. Every guard above has a mutation in
# orchestrator/tests/test_self_tests_can_fire.py that must turn this red.

# Built at runtime, so no scanner mistakes this file for a leak.
_FAKE_KEY = "sk-ant-" + "api03-" + "Q" * 48
_FAKE_TOKEN = "gh" + "p_" + "R" * 36


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _jsonl(*records: dict[str, Any]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


def _turn(sid: str, text: str) -> dict[str, Any]:
    return {"type": "user", "sessionId": sid, "message": {"role": "user", "content": text}}


def _fixture(home: Path) -> dict[str, Path]:
    """A HOME with two profiles, a correction history and the transcripts it names.

    sess-a  linked by transcript_path; two records; subagent, meta, tool results,
            an image, a file that stops decoding past 8 KiB, a symlink out
    sess-b  linked by session_id alone, under the second profile; its project
            /…/secretary must not match the private project /…/secret
    sess-c  a probe                      sess-d  no transcript anywhere
    sess-e  private-sessions marker under the second profile
    sess-f  transcript_path outside every root
    sess-g  conversation-mode project    sess-h  public record, then a private-projects one
    and two records with no link, one id that is not an id, two unreadable lines.
    """

    main_root = home / ".claude" / "projects"
    profile_root = home / ".claude-profiles" / "p1" / "projects"
    diary, secret_project, work = home / "diary", home / "secret", home / "work"
    for project in (diary, secret_project, work):
        project.mkdir(parents=True)
    _write(diary / ".claude" / "conversation-mode", "")
    _write(home / ".claude" / "private-projects", f"{secret_project}/\n")
    _write(home / ".claude-profiles" / "p1" / "private-sessions" / "sess-e", "")
    _write(home / ".claude" / ".sync-config", f"SYNC_BACKEND=git\nSYNC_DIR={home / 'dotfiles'}\n")
    (home / "dotfiles").mkdir()

    paths: dict[str, Path] = {}
    for sid, root in (("sess-a", main_root), ("sess-c", main_root), ("sess-e", main_root),
                      ("sess-g", main_root), ("sess-h", main_root), ("sess-b", profile_root)):
        paths[sid] = _write(root / "-work" / f"{sid}.jsonl", _jsonl(
            _turn(sid, f"first turn of {sid}"),
            # U+2028 inside a string: a splitlines() reader breaks this record in two.
            {"type": "assistant", "sessionId": sid, "message": {"content": [
                {"type": "text", "text": "line separator MARKER-424242"}]}},
            {"type": "user", "sessionId": sid, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": f"export KEY={_FAKE_KEY}"}]}},
        ))
    session_a = main_root / "-work" / "sess-a"
    _write(session_a / "subagents" / "agent-x.jsonl", _jsonl(
        {"type": "user", "agentId": "x", "message": {"content": f"token {_FAKE_TOKEN}"}}))
    _write(session_a / "subagents" / "agent-x.meta.json",
           json.dumps({"agentType": "x", "note": _FAKE_TOKEN, _FAKE_TOKEN: "a secret as a key"}))
    _write(session_a / "tool-results" / "out.txt", f"persisted output with {_FAKE_TOKEN} inside\n")
    (session_a / "tool-results" / "shot.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + bytes(range(256)))
    (session_a / "tool-results" / "late.log").write_bytes(b"a" * 9000 + b"\xff\xfe tail")
    _write(home / "outside.txt", f"never copied {_FAKE_TOKEN}\n")
    (session_a / "tool-results" / "escape.txt").symlink_to(home / "outside.txt")
    paths["outside"] = _write(home / "elsewhere" / "sess-f.jsonl", _jsonl(_turn("sess-f", "outside every root")))

    def link(sid: str, project: Path = work, **extra: Any) -> str:
        return json.dumps({"timestamp": "2026-11-05T12:00:00Z", "prompt": "[redacted prompt]", "project": str(project),
                           "type": "explicit", "session_id": sid,
                           "transcript_path": str(paths[sid]) if sid in paths else None, **extra}) + "\n"

    unlinked = {"timestamp": "2026-10-01T00:00:00Z", "prompt": "x", "project": str(work), "type": "explicit"}
    history = home / ".claude" / "corrections" / "history.jsonl"
    _write(history, "".join([
        link("sess-a"),
        link("sess-a", type="implicit-revert", revert_scope="paths"),
        link("sess-b", project=home / "secretary", transcript_path=None, type="implicit-revert", revert_scope="paths"),
        link("sess-c", type="implicit-revert", revert_scope="probe"),
        link("sess-d"),
        json.dumps(unlinked) + "\n",
        json.dumps({**unlinked, "timestamp": "2026-10-02T00:00:00Z"}) + "\n",
        json.dumps({**unlinked, "session_id": "../escape"}) + "\n",
        link("sess-e"),
        link("sess-f", transcript_path=str(paths["outside"])),
        link("sess-g", project=diary),
        link("sess-h"),
        link("sess-h", project=secret_project),
        "<<<<<<< Updated upstream\n",
        "not json at all\n",
    ]))
    paths["history"] = history
    return paths


def _read_gz(path: Path) -> str:
    if not path.is_file():
        return ""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return handle.read()


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for top, _, files in os.walk(root):
        for name in files:
            st = os.stat(Path(top) / name)
            out[str(Path(top, name).relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return out


def self_test() -> int:
    failures: list[str] = []

    def expect(label: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{label}{': ' + detail if detail else ''}")

    def call(*args: str) -> tuple[int, str]:
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                code = main(list(args))
        except Exception as exc:  # a crash is a failed control, not a crashed self-test
            return -1, f"{buffer.getvalue()}\nCRASHED: {type(exc).__name__}: {exc}"
        return code, buffer.getvalue()

    saved = {key: os.environ.get(key) for key in ("HOME", "CLAUDE_CONFIG_DIR")}
    saved_patterns = list(redact._PATTERNS)
    # The mode checks below mean something only under a umask that would leave
    # a directory 0755 and a file 0644 if the code did not set them itself.
    saved_umask = os.umask(0o022)
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(os.path.realpath(tmp)) / "home"
        os.environ["HOME"] = str(home)
        os.environ["CLAUDE_CONFIG_DIR"] = ""
        try:
            paths = _fixture(home)
            dest = home / ".local" / "share" / "clade" / "sessions"
            kept_a, kept_b = dest / "sess-a", dest / "sess-b"
            tool_results = kept_a / SESSION_PREFIX / "tool-results"

            # 1. A dry run reports and writes nothing.
            code, out = call()
            expect("dry run exits 0", code == 0, out[-600:])
            expect("a dry run writes nothing", not (home / ".local").exists())
            for needle in ("would keep 2 sessions (2 new", "1 probe record", "2 unreadable lines",
                           f"3 {NO_LINK}", f"2 {NOT_FOUND}", "3 sessions (4 records), skipped",
                           "3 records in 2 sessions", "2 not kept"):
                expect(f"dry-run report says {needle!r}", needle in out, out[-1500:])

            # 2. --apply keeps the linked sessions and nothing else.
            code, out = call("--apply")
            expect("apply exits 0", code == 0, out[-600:])
            expect("sess-a, linked by transcript_path, is kept", (kept_a / TRANSCRIPT_NAME).is_file())
            expect("sess-b, linked by session_id under another profile, is kept", (kept_b / TRANSCRIPT_NAME).is_file())
            for sid, why in (("sess-c", "a probe"), ("sess-d", "no transcript"), ("sess-e", "a private-sessions marker"),
                             ("sess-f", "a path outside every root"), ("sess-g", "a conversation-mode project"),
                             ("sess-h", "a later private-projects record")):
                expect(f"{sid} ({why}) is not kept", not (dest / sid).exists())
            text = _read_gz(kept_a / TRANSCRIPT_NAME)
            lines = text.split("\n")[:-1]
            expect("every source record is kept", len(lines) == 3, f"{len(lines)} lines")
            parsed = 0
            for line in lines:
                with contextlib.suppress(ValueError):
                    json.loads(line)
                    parsed += 1
            expect("every kept line is JSON", parsed == len(lines), f"{parsed} of {len(lines)}")
            expect("the transcript's key is masked", _FAKE_KEY not in text and "<redacted:anthropic_key>" in text)
            expect("U+2028 survives inside its record", "line separator" in text)
            for label, kept in (("a subagent transcript", kept_a / SESSION_PREFIX / "subagents" / "agent-x.jsonl.gz"),
                                ("its meta.json, key and value", kept_a / SESSION_PREFIX / "subagents" / "agent-x.meta.json.gz"),
                                ("a tool result", tool_results / "out.txt.gz")):
                body = _read_gz(kept)
                expect(f"{label} is kept", bool(body))
                expect(f"{label} is masked", bool(body) and _FAKE_TOKEN not in body and "<redacted:github_token>" in body)
            meta = _read_gz(kept_a / SESSION_PREFIX / "subagents" / "agent-x.meta.json.gz")
            try:
                json.loads(meta)
            except ValueError:
                failures.append("a masked meta.json is still JSON")
            manifest = _load_manifest(kept_a / "manifest.json")
            skipped = manifest.get("skipped", {})
            for name, why in (("shot.jpg", "binary"), ("late.log", "binary"), ("escape.txt", "symlink")):
                expect(f"{name} is not kept", not (tool_results / f"{name}.gz").exists())
                expect(f"the manifest says why {name} is not kept",
                       why in str(skipped.get(f"{SESSION_PREFIX}tool-results/{name}.gz")), json.dumps(skipped))
            expect("the manifest lists both corrections of sess-a", len(manifest.get("corrections", [])) == 2)
            expect("the manifest never holds a secret",
                   _FAKE_KEY not in json.dumps(manifest) and _FAKE_TOKEN not in json.dumps(manifest))
            masks = manifest.get("files", {}).get(TRANSCRIPT_NAME, {}).get("redactions", {})
            expect("the manifest counts the masks", masks.get("anthropic_key") == 1, json.dumps(masks))
            for top, dirs, files in os.walk(dest):
                for name in dirs:
                    mode = os.stat(Path(top) / name).st_mode & 0o777
                    expect(f"directory {name} is 0700", mode == 0o700, oct(mode))
                for name in files:
                    mode = os.stat(Path(top) / name).st_mode & 0o777
                    expect(f"file {name} is 0600", mode == 0o600, oct(mode))
            expect("the dest root is 0700", dest.is_dir() and os.stat(dest).st_mode & 0o777 == 0o700)

            # 3. A second run writes nothing.
            before = _snapshot(dest)
            code, out = call("--apply")
            expect("a second run exits 0", code == 0, out[-600:])
            expect("a second run says 0 files written", "0 files written" in out and "2 unchanged" in out, out[-400:])
            after = _snapshot(dest)
            expect("a second run rewrites no file", before == after,
                   ", ".join(k for k in after if before.get(k) != after[k]) or "a file appeared or vanished")

            # 4. Another run holding the lock: this one does nothing.
            import fcntl

            holder = os.open(dest / ".lock", os.O_WRONLY)
            try:
                fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with open(paths["sess-a"], "a", encoding="utf-8") as handle:
                    handle.write(_jsonl(_turn("sess-a", "a later turn")))
                code, out = call("--apply")
                expect("a run that finds the lock held exits 0", code == 0, out[-300:])
                expect("and says so", "another run holds" in out, out[-300:])
                expect("and writes nothing", "a later turn" not in _read_gz(kept_a / TRANSCRIPT_NAME))
            finally:
                os.close(holder)

            # 5. A transcript that grew is copied again; the other session is untouched.
            code, out = call("--apply")
            text = _read_gz(kept_a / TRANSCRIPT_NAME)
            expect("a grown transcript is copied again", len(text.split("\n")) - 1 == 4 and "a later turn" in text)
            expect("an unchanged session is not rewritten",
                   _snapshot(kept_b) == {k[len("sess-b/"):]: v for k, v in before.items() if k.startswith("sess-b/")})

            # 6. A tool result deleted since keeps its copy, and the manifest says so,
            #    in a run where nothing else changed.
            (paths["sess-a"].with_suffix("") / "tool-results" / "out.txt").unlink()
            code, out = call("--apply")
            gone = _load_manifest(kept_a / "manifest.json").get("files", {}).get(f"{SESSION_PREFIX}tool-results/out.txt.gz", {})
            expect("a deleted tool result keeps its copy", (tool_results / "out.txt.gz").is_file())
            expect("and the manifest marks its source gone", gone.get("source_gone") is True, json.dumps(gone))
            expect("and the report says a kept file outlived its source", "1 kept file outlived its source" in out, out[-500:])

            # 7. A new redaction pattern reaches a session whose source is still there.
            redact._PATTERNS.append(("selftest_marker", re.compile(r"MARKER-[0-9]{6}"), 0))
            code, out = call("--apply")
            redact._PATTERNS[:] = saved_patterns
            text = _read_gz(kept_b / TRANSCRIPT_NAME)
            expect("a new pattern re-redacts a kept session",
                   "MARKER-424242" not in text and "<redacted:selftest_marker>" in text)

            # 8. A transcript the cleanup deleted leaves its copy in place.
            paths["sess-b"].unlink()
            code, out = call("--apply")
            expect("a run after the source is gone exits 0", code == 0, out[-600:])
            expect("the copy outlives its source", (kept_b / TRANSCRIPT_NAME).is_file())
            expect("the report counts it as kept earlier", f"1 {KEPT_EARLIER}" in out, out[-800:])

            # 9. A session marked private after it was kept is not copied again, and is reported.
            _write(home / ".claude" / "private-sessions" / "sess-a", "")
            with open(paths["sess-a"], "a", encoding="utf-8") as handle:
                handle.write(_jsonl(_turn("sess-a", "after the marker")))
            code, out = call("--apply")
            expect("a session marked private later is not copied again",
                   "after the marker" not in _read_gz(kept_a / TRANSCRIPT_NAME))
            expect("its earlier copy is reported", "remove it by hand" in out, out[-600:])

            # 10. A --dest that syncs to a remote is refused before anything is written.
            for label, refused in (("inside ~/.claude", home / ".claude" / "kept"),
                                   ("inside the profiles directory", home / ".claude-profiles" / "kept"),
                                   ("inside the dotfiles sync store", home / "dotfiles" / "kept")):
                code, out = call("--apply", "--dest", str(refused))
                expect(f"a --dest {label} is refused", code == 2 and "syncs to a remote" in out, out[-300:])
                expect(f"and nothing is written {label}", not refused.exists())
            code, out = call("--dest", str(home / "elsewhere-kept"))
            expect("a --dest outside them is accepted", code == 0, out[-300:])
        finally:
            redact._PATTERNS[:] = saved_patterns
            os.umask(saved_umask)
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    if failures:
        print(f"keep-sessions self-test: FAILED ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("keep-sessions self-test: passed (dry run, selection, privacy, redaction, modes, idempotence, lock, refusal)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
