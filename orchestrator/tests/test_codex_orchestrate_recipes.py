"""The codex-orchestrate skill's shell recipes, run the way their consumer runs them.

The orchestrating agent copies these ```bash blocks out of the shipped
configs/skills/codex-orchestrate/prompt.md and fills in the placeholders. No
other check runs them, so this one does: it takes each block from prompt.md,
substitutes the placeholders and runs it against a fake `codex` on PATH. The
fake copies what codex-cli 0.167.0 was seen to do on 2026-11-06:

- its log header names the session (`session id: <uuid>`);
- it works in the directory after `-C`, else in its cwd, also for `resume`;
- it rejects `-C` after `resume` and exits 2, as clap does: `-C` is an option
  of `exec`, and `codex exec resume --help` lists none;
- it starts a child in a process group of its OWN inside the worker's session
  (an MCP server, in the observed run). `kill -- -PGID` misses that child.

What each test pins, as the consumer sees it:

- dispatch records the wrapper's pid, which leads its own session and group;
- cancel reaches every process in the session, including that child, which the
  fake also makes ignore SIGTERM, and writes the flag the tracked poll waits for;
- cancel reads the wrapper's whole command line even with a terminal-width
  $COLUMNS, signals nothing that is not this worker's wrapper, leaves a
  finished worker's flag alone, and keeps an rc the worker wrote while being
  cancelled;
- resume runs in the worktree whatever the caller's cwd, re-passes the bypass
  flag, reads the follow-up prompt from stdin and writes new round files;
- a resumed round records its own wrapper, so the cancel block pointed at that
  round's flag stops it and leaves round 1's flag alone.

Linux only: the recipes use util-linux setsid(1), which macOS does not ship.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

# ─── Locating the recipes ───

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "configs" / "skills" / "codex-orchestrate" / "prompt.md"
FAKE_SESSION = "0190a5c0-0000-7000-8000-00000000c0de"

DISPATCH = "codex exec -C <worktree> --dangerously-bypass-approvals-and-sandbox"
CANCEL = "P=$(cat <pgid-file>)"
SESSION_ID = "^session id:"
RESUME = "resume <session-id>"

pytestmark = pytest.mark.skipif(
    shutil.which("setsid") is None
    or shutil.which("pkill") is None
    or not Path("/proc/self/stat").exists(),
    reason="needs util-linux setsid(1), pkill and /proc (Linux)",
)


def _block(needle: str) -> str:
    blocks = re.findall(r"```bash\n(.*?)```", PROMPT.read_text(encoding="utf-8"), re.S)
    hits = [b for b in blocks if needle in b]
    assert len(hits) == 1, (
        f"expected exactly one ```bash block containing {needle!r} in "
        f"{PROMPT.relative_to(ROOT)}, found {len(hits)}"
    )
    return hits[0]


# ─── Process inspection (Linux /proc) ───


def _stat(pid: int) -> list[str] | None:
    """Fields after the command name: state, ppid, pgrp, session, …"""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return raw.rsplit(")", 1)[1].split()


def _alive(pid: int) -> bool:
    fields = _stat(pid)
    return fields is not None and fields[0] != "Z"


def _session_members(sid: int) -> list[int]:
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        fields = _stat(int(entry.name))
        if fields and fields[0] != "Z" and int(fields[3]) == sid:
            members.append(int(entry.name))
    return members


def _wait(predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


# ─── The fake codex ───

FAKE_CODEX = r"""#!/usr/bin/env bash
# Records what it was given, prints the 0.167.0 log header, and copies the
# observed process tree: a child in its own process group, same session. The
# child also ignores SIGTERM, so cancel has to escalate to SIGKILL.
d=$FAKE_CODEX_DIR
workdir=$PWD; out=""; prev=""; resumed=""
for a in "$@"; do
  case $prev in
    -C|--cd) workdir=$a ;;
    -o) out=$a ;;
    *)
      case $a in
        resume) resumed=1 ;;
        -C|--cd|--cd=*)
          # -C is an option of `exec`, not of `exec resume`. 0.167.0's clap
          # parser rejects it after `resume` before doing anything else.
          if [ -n "$resumed" ]; then
            printf "error: unexpected argument '%s' found\n" "${a%%=*}" >&2
            exit 2
          fi ;;
      esac ;;
  esac
  prev=$a
done
stdin=$(cat)    # a recipe that leaves stdin open hangs here, as codex does
{
  printf 'pwd=%s\n' "$PWD"
  printf 'workdir=%s\n' "$workdir"
  printf 'stdin=%s\n' "$stdin"
  printf 'arg=%s\n' "$@"
} > "$d/call.$$"
printf 'OpenAI Codex v0.167.0\n--------\nworkdir: %s\nsession id: %s\n--------\n' \
  "$workdir" "$FAKE_SESSION" >&2
set -m; bash -c 'trap "" TERM; sleep 300' & child=$!; set +m   # ignores TERM, too
echo "$child" > "$d/child.$$"
echo "$$" > "$d/codex.$$"
if [ "$FAKE_CODEX_MODE" = hang ]; then
  sleep 300
else
  [ -n "$out" ] && echo "worker done" > "$out"
  kill -KILL -- "-$child"
fi
"""


class Worker:
    """One worker's files, the placeholder map, and a runner for recipe blocks."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.fake = tmp / "fake"
        self.worktree = tmp / "wt-gap"
        self.elsewhere = tmp / "live-checkout"
        self.state = tmp / "state"
        for d in (self.bin, self.fake, self.worktree, self.elsewhere, self.state):
            d.mkdir()
        codex = self.bin / "codex"
        codex.write_text(FAKE_CODEX)
        codex.chmod(0o755)
        (self.state / "prompt.txt").write_text("implement the gap\n")
        (self.state / "followup.txt").write_text("fix the test you missed\n")
        self.pgid_file = self.state / "w.pgid"
        self.log = self.state / "w.log"
        self.last = self.state / "w.last"
        self.done = self.state / "w.done"
        self.mapping = {
            "<worktree>": str(self.worktree),
            "<pgid-file>": str(self.pgid_file),
            "<prompt-file>": str(self.state / "prompt.txt"),
            "<followup-file>": str(self.state / "followup.txt"),
            "<log>": str(self.log),
            "<last-msg-file>": str(self.last),
            "<done-flag>": str(self.done),
        }
        self.strangers: list[subprocess.Popen] = []

    def fill(self, block: str, overrides: dict[str, str] | None = None) -> str:
        for key, value in {**self.mapping, **(overrides or {})}.items():
            block = block.replace(key, value)
        left = re.findall(r"<[a-z][a-z0-9-]*>", block)
        assert not left, f"placeholders this test does not know: {left}"
        return block

    def run(
        self,
        block: str,
        mode: str = "finish",
        overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(
            PATH=f"{self.bin}{os.pathsep}{env.get('PATH', '')}",
            FAKE_CODEX_DIR=str(self.fake),
            FAKE_CODEX_MODE=mode,
            FAKE_SESSION=FAKE_SESSION,
            # A terminal's width. procps ps cuts piped output to $COLUMNS
            # unless given -ww, and the wrapper's command line names
            # <worktree> only after its pgid-file path, past column 80.
            COLUMNS="80",
        )
        return subprocess.run(
            ["bash", "-c", self.fill(block, overrides)],
            cwd=self.elsewhere,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def dispatch(self, mode: str) -> int:
        self.run(_block(DISPATCH), mode)
        assert _wait(lambda: _read_int(self.pgid_file) is not None), (
            "the dispatch recipe wrote no <pgid-file>, so nothing can cancel the worker"
        )
        return _read_int(self.pgid_file)  # type: ignore[return-value]

    def calls(self) -> list[dict]:
        out = []
        for path in sorted(self.fake.glob("call.*")):
            rec: dict = {"args": []}
            for line in path.read_text().splitlines():
                key, _, value = line.partition("=")
                if key == "arg":
                    rec["args"].append(value)
                else:
                    rec[key] = value
            out.append(rec)
        return out

    def pids(self, prefix: str) -> list[int]:
        return [p for f in self.fake.glob(f"{prefix}.*") if (p := _read_int(f))]

    def stranger(self, *argv: str) -> subprocess.Popen:
        """A process in a session of its own that no recipe started."""
        proc = subprocess.Popen(
            list(argv),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.strangers.append(proc)
        return proc

    def cleanup(self) -> None:
        """SIGKILL what this test started, and nothing else.

        Selected by an environment entry only this test's processes carry,
        never by a recorded pid: a recipe broken the right way records some
        other process's pid (a mutation that wrote $PPID recorded pid 1), and
        a cleanup that trusted it would signal that process's whole session.
        """
        marker = f"FAKE_CODEX_DIR={self.fake}".encode()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                environ = (entry / "environ").read_bytes()
            except OSError:
                continue
            if marker in environ.split(b"\0"):
                try:
                    os.kill(int(entry.name), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        for proc in self.strangers:  # each leads its own group: take its children too
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)


@pytest.fixture
def worker(tmp_path):
    w = Worker(tmp_path)
    try:
        yield w
    finally:
        w.cleanup()


# ─── Dispatch ───


def test_dispatch_records_the_wrapper_that_leads_the_worker_session(worker):
    p = worker.dispatch(mode="hang")
    assert os.getsid(p) == p and os.getpgid(p) == p, (
        "the recorded pid must lead its own session and group, or cancel has no handle"
    )
    assert _wait(lambda: bool(worker.pids("codex")))
    (codex,) = worker.pids("codex")
    assert os.getsid(codex) == p


# ─── Cancel ───


def test_cancel_reaches_a_child_outside_the_process_group(worker):
    p = worker.dispatch(mode="hang")
    assert _wait(lambda: bool(worker.pids("child")))
    (child,) = worker.pids("child")
    # The fixture must reproduce the case a group kill misses, or this test
    # cannot tell `pkill -s` from `kill -- -PGID`.
    assert os.getpgid(child) != p and os.getsid(child) == p

    worker.run(_block(CANCEL))

    assert _wait(lambda: not _session_members(p)), (
        f"still running in the worker's session after cancel: {_session_members(p)}"
    )
    assert not _alive(child)
    assert worker.done.read_text().strip() == "rc=cancelled", (
        "cancel must write the flag the tracked poll waits on"
    )


def test_cancel_signals_nothing_that_is_not_this_worker(worker):
    stranger = worker.stranger("sleep", "300")
    worker.pgid_file.write_text(f"{stranger.pid}\n")

    result = worker.run(_block(CANCEL))

    time.sleep(0.3)
    assert _alive(stranger.pid), (
        "cancel killed a process that was not this worker's wrapper"
    )
    assert "nothing killed" in result.stdout
    assert not worker.done.exists(), (
        "cancel invented a flag for a worker it did not stop"
    )


def test_cancel_leaves_a_finished_worker_alone(worker):
    worker.dispatch(mode="finish")
    assert _wait(lambda: worker.done.exists())
    assert worker.done.read_text().strip() == "rc=0"
    # The finished wrapper's pid now belongs to something else in this
    # worktree, e.g. the orchestrator's own verification run.
    reused = worker.stranger(
        "bash", "-c", f"sleep 300; exit 0  # verify run in {worker.worktree}"
    )
    worker.pgid_file.write_text(f"{reused.pid}\n")

    result = worker.run(_block(CANCEL))

    time.sleep(0.3)
    assert _alive(reused.pid), "cancel signalled a pid after the worker had finished"
    assert worker.done.read_text().strip() == "rc=0"
    assert "rc=0" in result.stdout


# A wrapper whose codex exits between the cancel block's identity check and its
# kill writes its real rc. The stand-in does that on SIGTERM, which makes the
# window deterministic. It records itself the way the dispatch wrapper does,
# only once its trap is set, and names <worktree> on its command line. `setsid
# -f` hands it to a reaper, because pgrep -s also lists a zombie in the session.
RC_DURING_CANCEL = """setsid -f bash -c '
  trap "echo rc=0 > <done-flag>; exit 0" TERM   # its codex exited 0 just now
  sleep 300 &
  echo $$ > <pgid-file>                          # a wrapper in <worktree>
  wait
' >/dev/null 2>&1
"""


def test_cancel_keeps_an_rc_the_worker_wrote_while_being_cancelled(worker):
    worker.run(RC_DURING_CANCEL)
    assert _wait(lambda: _read_int(worker.pgid_file) is not None)
    p = _read_int(worker.pgid_file)
    assert not worker.done.exists()

    worker.run(_block(CANCEL))

    assert _wait(lambda: not _session_members(p))
    assert worker.done.read_text().strip() == "rc=0", (
        "cancel overwrote the rc the worker wrote with rc=cancelled"
    )


# ─── Follow up: resume ───


def _finish_round_one(worker: Worker) -> str:
    """Dispatch round 1 to completion and read its session id the documented way."""
    worker.dispatch(mode="finish")
    assert _wait(lambda: worker.done.exists())
    sid = worker.run(_block(SESSION_ID)).stdout.strip()
    assert sid == FAKE_SESSION, (
        f"the documented id extraction read {sid!r} from the log"
    )
    worker.mapping["<session-id>"] = sid
    return sid


def _round_two_log(worker: Worker) -> str:
    try:
        return Path(f"{worker.log}.2").read_text()
    except OSError:
        return "(no round-2 log)"


def test_resume_runs_in_the_worktree_with_flags_and_prompt_repassed(worker):
    sid = _finish_round_one(worker)
    worker.run(_block(RESUME), mode="finish")

    done2 = Path(f"{worker.done}.2")
    assert _wait(done2.exists), "the resume round wrote no done-flag of its own"
    assert done2.read_text().strip() == "rc=0", (
        "codex rejected the resume round (0.167.0 exits 2 on a -C placed after "
        f"`resume`); its log: {_round_two_log(worker)!r}"
    )
    assert worker.done.read_text().strip() == "rc=0", (
        "round 2 must not touch round 1's flag"
    )
    assert Path(f"{worker.last}.2").read_text().strip() == "worker done"

    (call,) = [c for c in worker.calls() if "resume" in c["args"]]
    assert call["pwd"] == str(worker.elsewhere)  # the recipe ran from somewhere else …
    assert call["workdir"] == str(
        worker.worktree
    ), (  # … and the worker still works in its worktree
        "resume uses the caller's cwd unless -C names the worktree"
    )
    args = call["args"]
    i = args.index("resume")
    assert args[i + 1] == sid
    assert "--dangerously-bypass-approvals-and-sandbox" in args[i:], (
        "flags do not carry over into a resumed session; the recipe must pass it again"
    )
    assert args[-1] == "-"
    assert call["stdin"] == "fix the test you missed"


def test_a_resumed_round_records_its_own_wrapper_and_cancels_alone(worker):
    _finish_round_one(worker)
    p1 = _read_int(worker.pgid_file)
    worker.run(_block(RESUME), mode="hang")

    assert _wait(lambda: _read_int(worker.pgid_file) not in (None, p1)), (
        "the resume round left round 1's pid in <pgid-file>, so cancel cannot reach it"
    )
    p2 = _read_int(worker.pgid_file)
    assert _alive(p2) and os.getsid(p2) == p2 and os.getpgid(p2) == p2, (
        "the recorded pid must be the resume round's wrapper, leading its own session"
    )

    def resumed() -> list[int]:
        return [c for c in worker.pids("codex") if (f := _stat(c)) and int(f[3]) == p2]

    assert _wait(lambda: bool(resumed())), "the resumed codex is not in that session"
    (codex2,) = resumed()

    worker.run(_block(CANCEL), overrides={"<done-flag>": f"{worker.done}.2"})

    assert _wait(lambda: not _session_members(p2)), (
        f"still running in round 2's session after cancel: {_session_members(p2)}"
    )
    assert not _alive(codex2)
    assert Path(f"{worker.done}.2").read_text().strip() == "rc=cancelled"
    assert worker.done.read_text().strip() == "rc=0", (
        "cancelling round 2 must not touch round 1's flag"
    )
