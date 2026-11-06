"""keep-sessions.py's mutations, loaded into test_self_tests_can_fire.py's MUTATIONS.

Each one removes one guard the session keeper claims, and its --self-test must
turn red. That self-test drives main() in-process on a synthetic HOME (two
profiles, a correction history, transcripts, a dotfiles sync store), with one
negative control per exclusion, under umask 022 so the mode checks can fail.
"""

from __future__ import annotations

MUTATIONS: dict[str, list[tuple[str, str, str]]] = {"configs/scripts/keep-sessions.py": [
    # Which records.
    ("a probe is excluded — the agent's own mutation test is kept as a correction",
     '        if record.get("revert_scope") == "probe":',
     "        if False:"),
    ("a session id is validated — '../escape' reads as an id",
     '_SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,128}")',
     '_SESSION_ID = re.compile(r".{1,128}")'),
    ("transcript_path must be a transcript under a root — a file anywhere is copied",
     "        known = index.by_real.get(os.path.realpath(path))",
     "        known = index.by_real.get(os.path.realpath(path)) or (Path(path) if os.path.isfile(path) else None)"),
    ("a record with only session_id is located through every root",
     "    return sid, index.by_id.get(sid)",
     "    return sid, None"),
    ("two records of one session are one session with both corrections",
     "        session = sel.sessions.setdefault(sid, Session(sid, transcript))",
     "        session = sel.sessions[sid] = Session(sid, transcript)"),
    ("unreadable history lines are counted",
     '    sel.malformed = tally.get("malformed", 0) + tally.get("truncated", 0)',
     "    sel.malformed = 0"),
    ("a copy kept earlier is reported as such once its transcript is gone",
     '            elif (dest / sid / "manifest.json").is_file():',
     "            elif False:"),
    # Privacy.
    ("a private-sessions marker skips the session",
     "        if any((markers / sid).exists() for markers in self.marker_dirs):",
     "        if False:"),
    ("private-sessions under EVERY config dir — only ~/.claude's is read",
     '        self.marker_dirs = [config / "private-sessions" for config in config_dirs()]',
     '        self.marker_dirs = [config_dirs()[0] / "private-sessions"]'),
    ("a conversation-mode project skips the session",
     '            if (Path(project) / ".claude" / "conversation-mode").exists():',
     "            if False:"),
    ("a private-projects entry skips the session",
     '            if any(project == p or project.startswith(p + "/") for p in self.projects):',
     "            if False:"),
    ("a private-projects entry is a directory — /x/secret makes /x/secretary private",
     '            if any(project == p or project.startswith(p + "/") for p in self.projects):',
     "            if any(project.startswith(p) for p in self.projects):"),
    ("a private-projects entry's trailing slash is ignored",
     '            self.projects.extend(p.strip().rstrip("/") for p in lines if p.strip().rstrip("/"))',
     "            self.projects.extend(p.strip() for p in lines if p.strip())"),
    ("a session made private by a LATER record drops its earlier public records",
     "            earlier = sel.sessions.pop(sid, None)",
     "            earlier = None"),
    ("a session kept before it was marked private is reported",
     '        if (dest / sid / "manifest.json").is_file():\n            rows.append(',
     "        if False:\n            rows.append("),
    # Redaction.
    ("a transcript record is masked",
     '            yield _dump(scrub(record, counts)) + "\\n"',
     '            yield _dump(record) + "\\n"'),
    ("a .json file is masked",
     "            yield _dump(scrub(json.loads(text), counts))",
     "            yield _dump(json.loads(text))"),
    ("a JSON key is masked, not only its value",
     "        return {_mask(key, counts): scrub(item, counts) for key, item in value.items()}",
     "        return {key: scrub(item, counts) for key, item in value.items()}"),
    ("any other text file is masked",
     "    yield _mask(text, counts)",
     "    yield text"),
    ("a file that does not decode is not kept — decoded with replacement and written",
     '        text = path.read_bytes().decode("utf-8")',
     '        text = path.read_bytes().decode("utf-8", "replace")'),
    ("a dry run names the files that will not decode",
     "                if not _head_is_text(source.path):",
     "                if False:"),
    ("a symlink is not followed",
     '        if os.path.islink(source.path):\n            source.skip = "symlink: not followed"',
     '        if False:\n            source.skip = "symlink: not followed"'),
    ("a new redaction pattern re-redacts a session still on disk",
     '        and old.get("redactor") == fingerprint\n',
     ""),
    # Writing.
    ("a dry run writes nothing",
     "        if not args.apply:\n            return run(history, dest, apply=False)",
     "        if False:\n            return run(history, dest, apply=False)"),
    ("every directory is 0700, parents included",
     "    for directory in reversed(missing):\n"
     "        with contextlib.suppress(FileExistsError):\n"
     "            directory.mkdir(mode=0o700)\n"
     "        os.chmod(directory, 0o700)\n"
     "    os.chmod(path, 0o700)",
     "    path.mkdir(parents=True, exist_ok=True)"),
    ("every kept file is 0600",
     "    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)\n"
     "    try:\n"
     '        with os.fdopen(fd, "wb") as handle:\n'
     "            for chunk in data:\n"
     "                handle.write(chunk)\n"
     "        os.chmod(tmp, 0o600)",
     "    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)\n"
     "    try:\n"
     '        with os.fdopen(fd, "wb") as handle:\n'
     "            for chunk in data:\n"
     "                handle.write(chunk)\n"
     "        os.chmod(tmp, 0o644)"),
    ("the lock file is 0600",
     '    fd = os.open(dest / ".lock", os.O_WRONLY | os.O_CREAT, 0o600)',
     '    fd = os.open(dest / ".lock", os.O_WRONLY | os.O_CREAT, 0o644)'),
    ("a held lock stops a second run",
     "        except OSError:\n            yield False\n            return",
     "        except OSError:\n            yield True\n            return"),
    ("an unchanged file is not rewritten",
     "    return (\n        isinstance(old, dict)\n        and _same_source(source, old)",
     "    return False and (\n        isinstance(old, dict)\n        and _same_source(source, old)"),
    ("a grown source is copied again",
     "        and _same_source(source, old)\n",
     ""),
    ("an undecodable file that has not changed is not retried every run",
     "        if not source.skip and isinstance(prior, dict) and prior.get(\"why\") == BINARY and _same_source(source, prior):",
     "        if False:"),
    ("source_gone persists: the loaded entries are copied, so a mark set in place is not compared equal and lost",
     "    files: dict[str, Any] = {name: dict(e) if isinstance(e, dict) else e for name, e in old_files.items()}",
     "    files: dict[str, Any] = dict(old_files)"),
    # Where.
    ("a --dest inside a synced place is refused",
     "        if target == real or real in target.parents:",
     "        if False:"),
    ("the Claude config directories are synced places",
     '    places = [("the Claude config directory", config) for config in config_dirs()]',
     "    places: list[tuple[str, Path]] = []"),
    ("the profiles directory is a synced place",
     '    places.append(("the profiles directory", Path.home() / ".claude-profiles"))',
     "    pass"),
    ("the dotfiles sync store is a synced place",
     '            places.append(("the dotfiles sync store", store))',
     "            pass"),
]}
