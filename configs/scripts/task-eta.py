#!/usr/bin/env python3
"""task-eta.py — how long the current Claude Code task has run, and what it is waiting on.

The status line calls this with its own JSON on stdin and prints one segment;
``--forms`` prints it two ways, longest first, and the status line keeps the
longer one when it fits its pane. These are the self-test's, from its synthetic history:

    25m                       the task has run 25 min (a turn is running)
    10m workflow              no turn running: it waits on a Workflow (named before other jobs)
    12m monitor ≤8m left      a Monitor's declared timeout bounds what is left
    (nothing)                 idle: nothing running, so the pane waits on you

No state word, no job age and no remaining-time band (owner, 2026-11-20:
"run, idle, wait这几个字有点过于占空间 ... 只保留有必要保留的信息"). A time
means busy, an empty segment means idle, and a job kind means it is waiting on
that job.

What "task" means
-----------------
The episode from the latest HUMAN prompt (typed or queued; an SDK or peer
prompt also starts one) to now. Turns that a background job's completion
notification starts belong to the same task, because a task's wall time is
mostly spent waiting on background work between turns. When no turn is running
but a background Workflow, Agent, Bash or Monitor job is still in flight, the
line reads ``<elapsed> <kind>``. In flight means launched
during the last three tasks (all the tail reader reads), not seen to finish,
and under a day old; a job launched before the latest prompt still shows. A job
ends at its completion notice, at a TaskStop (or KillShell) naming it, which no
notice follows, or at a Monitor's timeout; a launch whose call failed or was
refused never ran, so it is neither in flight nor fitted.

What the range is, and why the line never prints it
---------------------------------------------------
A survival lookup on elapsed time, fitted from the last 30 days of this
machine's own main-thread transcripts: at elapsed t, the p25-p75 of the time
that was left for past tasks that ran at least t. Only ``--json`` carries it,
and only ``--json`` reads the model: a status-line call never opens it. The
line printed it from 2026-11-20 only when p75 was at most 4 times p25, and
dropped it on 2026-11-23: the owner settled on not chasing time remaining, and
a band too wide to act on tells nobody whether to wait. On the author's
history it almost never was narrow: tasks were 28x wide at 1 min and 8x at 15 min, and
single background jobs 5-9x, on a held-out week (2026-11-12..20, 221 tasks and
1,106 jobs; docs/research/2026-11-19-cc-eta-and-bottlenecks.md). Neither the
job's identity (its normalised command, subagent type or Workflow name), its
kind, the prompt's length nor the task's phase narrowed it, because after a
wait the agent launches another round about half the time (54% then 67%) and
nothing observable predicted which
better than about 60/40. Past 4 h elapsed, and wherever fewer than
``MIN_N`` past items survived, the lookup is ``beyond``. A Monitor's declared
timeout is the one hard bound, and the one thing about what is left that the
line prints: ``≤<time> left``.

The model and its refit
-----------------------
``<config dir>/task-eta-model.json`` (config dir = ``$CLAUDE_CONFIG_DIR`` or
``~/.claude``). ``--fit`` scans every root ``transcripts.default_roots()``
names (``~/.claude/projects``, each ``~/.claude-profiles/*/projects``, and the
config dir's own), main-thread transcripts modified in the last 30 days, and
writes the survival grid atomically. When the model is missing or older than a
day, a ``--json`` call starts ONE detached low-priority refit behind an
``O_EXCL`` lock file (``task-eta-model.lock``; a lock older than an hour is
stale, and one caller breaks it under a second lock), and carries no band
until a model exists; a config dir it cannot write means no refit. Each
refit appends one line to ``task-eta-fit.log``. A status-line call (no
``--json``) does none of this: it neither reads the model nor starts a refit,
so the line is the same with the model present, missing or corrupt.

Failing soft
------------
In status-line mode (and ``--json``) every error, and a one-second deadline,
ends in printing nothing and exit 0, so the other segments always render.

Usage
-----
  task-eta.py --stdin                 status-line JSON on stdin (reads transcript_path)
  task-eta.py --stdin --forms         the segment two ways, longest first, one per line
  task-eta.py --transcript PATH       the same for a transcript path
  task-eta.py ... --json              the estimate as JSON, band included (the only mode that reads the model)
  task-eta.py --fit                   refit the model now (foreground)
  task-eta.py --check-tail [N]        tail read vs full parse on the N largest local transcripts
  task-eta.py --self-test             synthetic transcripts only; exit 1 when a guard fails

Stdlib only, python3 >= 3.8.
"""
# ─── Imports ───
import json
import math
import os
import re
import sys
import time
from datetime import datetime as _dt

HERE = os.path.dirname(os.path.abspath(__file__))

# ─── Constants ───
MODEL_VERSION = 1
# Elapsed grid in seconds; the evaluation checkpoints (1/5/15/30/60 min) are grid points.
GRID_S = [0, 15, 30, 60, 120, 180, 300, 450, 600, 900, 1200, 1800, 2700, 3600,
          5400, 7200, 10800, 14400, 21600, 28800, 43200, 86400]
MIN_N = 20                    # a grid cell needs this many surviving past items, else "beyond history"
HORIZON_S = 4 * 3600          # from here on the line says "beyond history" (see the docstring)
FIT_WINDOW_DAYS = 30          # Claude Code deletes transcripts after 30 days
CENSOR_S = 2 * 3600           # a transcript written this recently may still be running its last episode
MODEL_MAX_AGE_S = 24 * 3600   # refit once a day
LOCK_STALE_S = 3600           # a refit lock older than this is broken (a killed or hung refit)
BREAK_STALE_S = 60            # a break lock (held for a few syscalls) older than this was left by a kill
FIT_LOG_KEEP = 20             # lines kept in task-eta-fit.log
DEADLINE_S = 1.0              # status-line mode gives up and prints nothing after this
BG_STALE_S = 24 * 3600        # a launch older than this with no completion seen is not in flight
TAIL_EPISODES = 3             # episode starts the tail reader goes back for earlier launches
TAIL_CAP = 32 << 20           # bytes read back from the end at most
EARLIER_CAP = 8 << 20         # bytes read before the latest episode start, looking for earlier launches
CHUNK = 1 << 20
LIGHT_MIN = 4000              # tool-result lines longer than this are cut, not decoded

BG_PRIORITY = ('workflow', 'agent', 'bash', 'monitor')   # which in-flight job the line names
EP_STARTERS = ('human', 'queued', 'sdk', 'peer')          # triggers that start a task
FIT_STARTERS = ('human', 'queued')                        # tasks the model is fitted on


def config_dir():
    override = os.environ.get('CLAUDE_CONFIG_DIR', '')
    return os.path.expanduser(override) if override else os.path.join(os.path.expanduser('~'), '.claude')


def model_path(cfg):
    return os.path.join(cfg, 'task-eta-model.json')


def lock_path(cfg):
    return os.path.join(cfg, 'task-eta-model.lock')


def fit_log_path(cfg):
    return os.path.join(cfg, 'task-eta-fit.log')


def now_s():
    """Wall clock; CLADE_TASK_ETA_NOW (epoch seconds) pins it for tests."""
    v = os.environ.get('CLADE_TASK_ETA_NOW', '')
    try:
        return float(v) if v else time.time()
    except ValueError:
        return time.time()


# ─── Transcript records -> turns, episodes, background jobs ───
def ts_ms(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        return _dt.fromisoformat(s.replace('Z', '+00:00')).timestamp() * 1000.0
    except ValueError:
        return None


_TUID = re.compile(r'<tool-use-id>([^<]+)</tool-use-id>')
_TASKID = re.compile(r'<task-id>([^<]{1,80})</task-id>')
_STATUS = re.compile(r'<status>([^<]{0,20})</status>')
_INTERRUPT = '[Request interrupted by user'


def trigger_kind(r):
    """human / queued / task-notification / wakeup / sdk / peer / auto-continuation / other."""
    o = r.get('turnOrigin')
    ok = r['origin'].get('kind') if isinstance(r.get('origin'), dict) else None
    if o == 'human':
        return 'queued' if r.get('promptSource') == 'queued' else 'human'
    if o == 'task_notification' or ok == 'task-notification':
        return 'task-notification'
    if o == 'scheduled':
        return 'wakeup'
    if o in ('sdk', 'peer'):
        return o
    if o == 'auto_continuation':
        return 'auto-continuation'
    return 'other'


def _text_of(cont):
    if isinstance(cont, str):
        return cont
    if isinstance(cont, list):
        return ''.join(b.get('text', '') for b in cont if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def _bg_kind(name):
    return {'Workflow': 'workflow', 'Monitor': 'monitor', 'Agent': 'agent', 'Task': 'agent'}.get(name, 'bash')


class Timeline:
    """Consumes transcript records in file order.

    turns:    {t0, t1 (None while running), trig, last, ep}
    episodes: {t0, starter, turns: [turn index], bgs: [bg]}
    bg:       [launch_ms, done_ms or None, kind, expire_ms or None]
    """

    def __init__(self):
        self.turns = []
        self.episodes = []
        self.calls = {}           # tool_use id -> [start_ms, kind]
        self.bg_by_tuid = {}
        self.task_to_tuid = {}
        self.cur = None
        self.seen_triggers = set()

    def _close_turn_fallback(self):
        if self.cur is not None and self.cur['t1'] is None:
            self.cur['t1'] = self.cur['last']

    def _mark_done(self, text, ts):
        m = _TUID.search(text)
        tuid = m.group(1) if m else None
        if not tuid:
            m = _TASKID.search(text)
            tuid = self.task_to_tuid.get(m.group(1)) if m else None
        if tuid and _STATUS.search(text) and tuid in self.bg_by_tuid:
            bg = self.bg_by_tuid[tuid]
            if bg[1] is None:
                bg[1] = ts

    def _launch(self, tuid, ts, kind):
        bg = [ts, None, kind, None]
        self.bg_by_tuid[tuid] = bg
        if self.episodes:
            self.episodes[-1]['bgs'].append(bg)

    def _stop(self, task_id, ts):
        """TaskStop / KillShell: the job ends at the call. No completion notice follows a stop, so
        without this a stopped job stays in flight until it ages out."""
        bg = self.bg_by_tuid.get(self.task_to_tuid.get(task_id)) if isinstance(task_id, str) else None
        if bg is not None and bg[1] is None:
            bg[1] = ts

    def _unlaunch(self, tuid):
        """A launch whose call failed or was refused (a hook denial, a bad argument): it never ran."""
        bg = self.bg_by_tuid.pop(tuid, None)
        for ep in reversed(self.episodes if bg is not None else []):
            if any(b is bg for b in ep['bgs']):
                ep['bgs'] = [b for b in ep['bgs'] if b is not bg]
                return

    def feed(self, r):
        if not isinstance(r, dict):
            return
        t = r.get('type')
        if t not in ('user', 'assistant', 'system', 'attachment') or r.get('isSidechain'):
            return
        ts = ts_ms(r.get('timestamp'))
        if ts is None:
            return
        if t == 'user':
            self._feed_user(r, ts)
        elif t == 'assistant':
            self._feed_assistant(r, ts)
        elif t == 'system':
            if self.cur is None:
                return
            st = r.get('subtype')
            if st == 'turn_duration' and self.cur['t1'] is None:
                self.cur['t1'] = max(ts, self.cur['t0'])
            elif st in ('stop_hook_summary', 'compact_boundary') and self.cur['t1'] is None:
                self.cur['last'] = max(self.cur['last'], ts)
        else:
            a = r.get('attachment') if isinstance(r.get('attachment'), dict) else {}
            if a.get('type') == 'queued_command':
                p = a.get('prompt')
                ptxt = p if isinstance(p, str) else _text_of(p)
                if '<task-notification>' in (ptxt or '')[:300]:
                    self._mark_done(ptxt, ts)

    def _feed_user(self, r, ts):
        msg = r.get('message') if isinstance(r.get('message'), dict) else {}
        cont = msg.get('content')
        trs = [b for b in cont if isinstance(b, dict) and b.get('type') == 'tool_result'] \
            if isinstance(cont, list) else []
        if trs:
            self._feed_tool_results(r, ts, trs)
            return
        is_trig = (r.get('turnOrigin') or (isinstance(r.get('origin'), dict)
                                           and r['origin'].get('kind') == 'task-notification')) \
            and not r.get('isCompactSummary')
        if is_trig:
            u = r.get('uuid')
            if u is not None and u in self.seen_triggers:
                return
            self.seen_triggers.add(u)
            self._close_turn_fallback()
            kind = trigger_kind(r)
            text = _text_of(cont)
            if kind == 'task-notification' and '<task-notification>' in text[:300]:
                self._mark_done(text, ts)
            if kind in EP_STARTERS or not self.episodes:
                self.episodes.append({'t0': ts, 'starter': kind if kind in EP_STARTERS else 'none',
                                      'turns': [], 'bgs': []})
            self.cur = {'t0': ts, 't1': None, 'trig': kind, 'last': ts, 'ep': len(self.episodes) - 1}
            self.turns.append(self.cur)
            self.episodes[-1]['turns'].append(len(self.turns) - 1)
            return
        if self.cur is not None and _text_of(cont).lstrip().startswith(_INTERRUPT):
            # An interrupt ends the turn, and no turn_duration record follows one.
            self.cur['last'] = max(self.cur['last'], ts)
            if self.cur['t1'] is None:
                self.cur['t1'] = ts

    def _feed_tool_results(self, r, ts, blocks):
        tur = r.get('toolUseResult')
        trs = [b.get('tool_use_id') for b in blocks]
        if isinstance(tur, dict) and len(trs) == 1:
            tuid = trs[0]
            c = self.calls.get(tuid)
            for k in ('backgroundTaskId', 'taskId', 'agentId'):
                v = tur.get(k)
                if isinstance(v, str) and v:
                    self.task_to_tuid[v] = tuid
            auto_bg = isinstance(tur.get('backgroundTaskId'), str) or tur.get('isAsync') is True
            if auto_bg and tuid not in self.bg_by_tuid:
                if c is not None:
                    self._launch(tuid, c[0], 'agent' if c[1] == 'agent' else 'bash')
                elif self.episodes:
                    # the launching call was not decoded (a sparse read): it went to the background here
                    self._launch(tuid, ts, 'agent' if tur.get('isAsync') is True else 'bash')
            if c is not None and c[1] == 'monitor' and tuid in self.bg_by_tuid:
                tm = tur.get('timeoutMs')
                if isinstance(tm, (int, float)) and not tur.get('persistent'):
                    self.bg_by_tuid[tuid][3] = c[0] + tm
        for b in blocks:
            if b.get('is_error') is True:          # the launching call failed: the job never ran
                self._unlaunch(b.get('tool_use_id'))
        if self.cur is not None:
            self.cur['last'] = max(self.cur['last'], ts)

    def _feed_assistant(self, r, ts):
        if self.cur is None:
            return
        msg = r.get('message') if isinstance(r.get('message'), dict) else {}
        if msg.get('model') == '<synthetic>':
            return
        self.cur['last'] = max(self.cur['last'], ts)
        for b in msg.get('content') or []:
            if not isinstance(b, dict) or b.get('type') != 'tool_use':
                continue
            name = b.get('name') or '?'
            inp = b.get('input') if isinstance(b.get('input'), dict) else {}
            kind = _bg_kind(name)
            tid = b.get('id')
            self.calls[tid] = [ts, kind]
            if inp.get('run_in_background') is True or name in ('Workflow', 'Monitor'):
                self._launch(tid, ts, kind)
            elif name in ('TaskStop', 'KillShell'):
                self._stop(inp.get('task_id') or inp.get('shell_id'), ts)

    def finish(self):
        self._close_turn_fallback()


# ─── Tail reader ───
# Lines worth decoding outside a full parse: triggers, turn ends, interrupts, background launches,
# completions, stops and failed calls. Everything the live estimate reads comes from these. Inside a
# JSON string a quote is escaped, so a key pattern matches a real key, never text that quotes one.
SPARSE_KEYS = (b'"turnOrigin"', b'"subtype":"turn_duration"', b'<task-notification>', b'"backgroundTaskId"',
               b'"isAsync":true', b'"name":"Workflow"', b'"name":"Monitor"', b'"run_in_background":true',
               b'"timeoutMs"', b'"taskId"', b'"agentId"', b'"name":"TaskStop"', b'"name":"KillShell"',
               b'"is_error":true', b'[Request interrupted by user')
_SKIP_PREFIX = tuple(('{"type":"%s"' % t).encode() for t in (
    'last-prompt', 'mode', 'permission-mode', 'atis-latch', 'ai-title', 'pr-link',
    'file-history-snapshot', 'file-history-delta', 'queue-operation', 'cost-state'))
_TO_KEY = b'"turnOrigin":"'

# A large tool_result line is mostly stdout. Claude Code writes its top-level keys in a fixed order
# (..., message, uuid, timestamp, toolUseResult, ...), so the few fields the Timeline reads can be cut
# out without decoding the payload. Anything unexpected falls back to json.loads.
_LR_TS = re.compile(rb'"uuid":"[^"]+","timestamp":"([^"]+)","toolUseResult":')
_LR_ID = re.compile(rb'"tool_use_id":"([^"]+)"')
_LR_FIELDS = {k: re.compile(rb'"' + k.encode() + rb'":"([^"]{1,80})"') for k in ('backgroundTaskId', 'taskId', 'agentId')}
_LR_NUM = re.compile(rb'"timeoutMs":(\d+)')


def _light_tool_result(line):
    if not line.startswith(b'{"parentUuid"') or b'"type":"user"' not in line[:400]:
        return None
    m = _LR_TS.search(line)
    i = _LR_ID.search(line)
    if not m or not i or i.start() > m.start():
        return None
    part = line[m.end():]
    tur = None
    if part.startswith(b'{'):
        tur = {}
        for k, rx in _LR_FIELDS.items():
            mm = rx.search(part)
            if mm:
                tur[k] = mm.group(1).decode('utf-8', 'replace')
        if b'"isAsync":true' in part:
            tur['isAsync'] = True
        if b'"persistent":true' in part:
            tur['persistent'] = True
        mm = _LR_NUM.search(part)
        if mm:
            tur['timeoutMs'] = int(mm.group(1))
    block = {'type': 'tool_result', 'tool_use_id': i.group(1).decode('utf-8', 'replace')}
    if b'"is_error":true' in line[:m.start()]:
        block['is_error'] = True
    return {'type': 'user', 'isSidechain': b'"isSidechain":true' in line[:200],
            'timestamp': m.group(1).decode('utf-8', 'replace'), 'toolUseResult': tur,
            'message': {'content': [block]}}


def decode_line(line):
    """One transcript line -> record, or None (blank, skipped type, or not JSON)."""
    if not line or line.startswith(_SKIP_PREFIX):
        return None
    r = _light_tool_result(line) if len(line) > LIGHT_MIN else None
    if r is None:
        try:
            r = json.loads(line)
        except ValueError:
            return None
    return r if isinstance(r, dict) else None


def _is_ep_start_line(line):
    return (b'"isCompactSummary":true' not in line and b'"isSidechain":true' not in line
            and b'"type":"user"' in line)


def read_tail_records(path, n_starts=TAIL_EPISODES, cap_bytes=TAIL_CAP, chunk=CHUNK):
    """Read backwards one chunk at a time until n_starts task-starting prompts (human, queued, sdk or
    peer) or the cap, then decode only the SPARSE_KEYS lines of what was read.
    Returns (records in file order, found: at least the latest task start was seen)."""
    size = os.path.getsize(path)
    pos = size
    pieces = []          # complete-line byte runs, newest first
    carry = b''          # leading partial line of the data read so far
    n_found = 0
    latest_abs = None    # file offset of the latest task start
    with open(path, 'rb') as f:
        while pos > 0 and size - pos < cap_bytes and (latest_abs is None or latest_abs - pos < EARLIER_CAP):
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            seg = f.read(step) + carry
            if pos > 0:
                nl = seg.find(b'\n')
                if nl < 0:          # one line longer than the chunk: keep reading
                    carry = seg
                    continue
                first = nl + 1
            else:
                first = 0
            starts = []
            k = seg.find(_TO_KEY, first)
            while k >= 0:
                v = seg[k + len(_TO_KEY):k + len(_TO_KEY) + 6]
                if v.startswith((b'human"', b'sdk"', b'peer"')):
                    ls = seg.rfind(b'\n', 0, k) + 1
                    le = seg.find(b'\n', k)
                    if _is_ep_start_line(seg[ls:le if le >= 0 else len(seg)]):
                        starts.append(ls)
                k = seg.find(_TO_KEY, k + 1)
            if starts and latest_abs is None:
                latest_abs = pos + starts[-1]
            need = n_starts - n_found
            if len(starts) >= need:
                pieces.append(seg[starts[-need]:])
                break
            n_found += len(starts)
            pieces.append(seg[first:])
            carry = seg[:first]
    return sparse_records(b''.join(reversed(pieces))), latest_abs is not None


def sparse_records(buf):
    """Decode only the lines carrying a SPARSE_KEYS key, in file order."""
    found = {}
    for key in SPARSE_KEYS:                    # bytes.find per key; decode only the matching lines
        k = buf.find(key)
        while k >= 0:
            ls = buf.rfind(b'\n', 0, k) + 1
            le = buf.find(b'\n', k)
            le = le if le >= 0 else len(buf)
            found.setdefault(ls, buf[ls:le])
            k = buf.find(key, le)
    # An auto-backgrounded call (its result carries backgroundTaskId or isAsync) was launched at its
    # tool_use line, which matches no key: find that line by its id, so the launch time is a full parse's.
    for ls, line in list(found.items()):
        if b'"backgroundTaskId"' in line or b'"isAsync":true' in line:
            m = _LR_ID.search(line)
            k = buf.rfind(b'"id":"' + m.group(1) + b'"', 0, ls) if m else -1
            if k >= 0:
                cs = buf.rfind(b'\n', 0, k) + 1
                ce = buf.find(b'\n', k)
                found.setdefault(cs, buf[cs:ce if ce >= 0 else len(buf)])
    recs = []
    for ls in sorted(found):
        r = decode_line(found[ls])
        if r is not None:
            recs.append(r)
    return recs


def iter_all_records(path):
    """Every decodable record of a transcript, one at a time (the full parse the tail reader
    must agree with). A generator, so a fit holds one record of a large transcript, not all."""
    with open(path, 'rb') as f:
        for line in f:
            r = decode_line(line.rstrip(b'\n'))
            if r is not None:
                yield r


def read_all_records(path):
    return list(iter_all_records(path))


# ─── Model: lookup ───
BEYOND = 'beyond'


def grid_index(e_s):
    i = 0
    for j, g in enumerate(GRID_S):
        if g <= e_s:
            i = j
    return i


def survival_quantiles(block, elapsed_s):
    """[p25, p50, p75] of the time left among past items that ran at least elapsed_s, and that n;
    log-interpolated between grid points. None where too few past items survived."""
    gi = grid_index(elapsed_s)
    cell = block['global'][gi]
    if not cell:
        return None
    q = [float(v) for v in cell[:3]]
    nxt = block['global'][gi + 1] if gi + 1 < len(GRID_S) else None
    if nxt and elapsed_s > GRID_S[gi]:
        g0, g1 = GRID_S[gi], GRID_S[gi + 1]
        w = (math.log1p(elapsed_s) - math.log1p(g0)) / (math.log1p(g1) - math.log1p(g0))
        w = min(1.0, max(0.0, w))
        q = [math.exp((1 - w) * math.log(max(a, 1.0)) + w * math.log(max(b, 1.0))) for a, b in zip(q, nxt[:3])]
    return q, int(cell[3])


def lookup(model, kind, elapsed_s):
    """{'p25','p50','p75','n'}, BEYOND past the history's support, or None without a model."""
    block = (model or {}).get(kind)
    if not block or not block.get('global') or not block['global'][0]:
        return None                      # no model, or too little history to say anything
    if elapsed_s >= HORIZON_S:
        return BEYOND
    got = survival_quantiles(block, elapsed_s)
    if got is None:
        return BEYOND
    q, n = got
    return {'p25': q[0], 'p50': q[1], 'p75': q[2], 'n': n}


def load_model(path):
    """The model, or None when it is missing, unreadable or of another version or grid."""
    try:
        with open(path) as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get('version') != MODEL_VERSION or m.get('grid_s') != GRID_S:
        return None
    return m


# ─── Model: fit ───
def _quantiles(xs):
    xs = sorted(xs)
    n = len(xs)
    q = lambda p: xs[min(n - 1, int(p * (n - 1) + 0.5))]  # noqa: E731
    return [round(q(0.25), 1), round(q(0.5), 1), round(q(0.75), 1), n]


def survival_grid(durations):
    """Per grid point: quantiles of the time left among items that ran longer, or None below MIN_N."""
    out = []
    for g in GRID_S:
        rem = [d - g for d in durations if d > g]
        out.append(_quantiles(rem) if len(rem) >= MIN_N else None)
    return out


def file_items(path, censor):
    """Durations (seconds) a transcript contributes: human-started tasks and background jobs.
    censor drops the last task, which may still be running."""
    tl = Timeline()
    for r in iter_all_records(path):
        tl.feed(r)
    tl.finish()
    eps = tl.episodes[:-1] if censor else tl.episodes
    tasks, bgs = [], []
    for ep in eps:
        ends = [tl.turns[i]['t1'] for i in ep['turns'] if tl.turns[i]['t1'] is not None]
        if ep['starter'] in FIT_STARTERS and ends and max(ends) > ep['t0']:
            tasks.append((ep['t0'], (max(ends) - ep['t0']) / 1000.0))
        for launch, done, kind, expire in ep['bgs']:
            end = done if done is not None else expire      # done includes a stop; a Monitor may expire
            if end is not None and end > launch:
                bgs.append((launch, kind, (end - launch) / 1000.0))
    return tasks, bgs


def fit_model(roots=None, now=None):
    """Fit the survival grids from main-thread transcripts modified in the last FIT_WINDOW_DAYS."""
    sys.path.insert(0, HERE)
    import transcripts  # noqa: E402  (beside this file; the status-line path never imports it)
    from pathlib import Path
    now = time.time() if now is None else now
    roots = transcripts.default_roots() if roots is None else [Path(r) for r in roots]
    files = transcripts.find_transcripts(roots, FIT_WINDOW_DAYS)
    seen = set()
    tasks, bgs = [], []
    n_files = n_errors = 0
    for p in files:
        try:
            censor = now - os.path.getmtime(p) < CENSOR_S
            t, b = file_items(str(p), censor)
        except OSError:
            n_errors += 1
            continue
        n_files += 1
        slug = p.parent.name
        for t0, d in t:
            if ('task', slug, t0) not in seen:          # a forked session repeats its triggers
                seen.add(('task', slug, t0))
                tasks.append(d)
        for launch, kind, d in b:
            if ('bg', slug, launch, kind) not in seen:
                seen.add(('bg', slug, launch, kind))
                bgs.append(d)
    return {
        'version': MODEL_VERSION, 'grid_s': GRID_S, 'min_n': MIN_N, 'horizon_s': HORIZON_S,
        'fitted_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
        'window_days': FIT_WINDOW_DAYS, 'n_files': n_files, 'n_unreadable': n_errors,
        'episode': {'p0_median_s': sorted(tasks)[len(tasks) // 2] if tasks else None,
                    'n_items': len(tasks), 'global': survival_grid(tasks)},
        'bg': {'n_items': len(bgs), 'global': survival_grid(bgs)},
    }


def write_model(model, path):
    """Write atomically: a reader sees the old model or the new one, never half of one."""
    tmp = '%s.tmp.%d' % (path, os.getpid())
    try:
        with open(tmp, 'w') as f:
            json.dump(model, f, separators=(',', ':'))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _append_fit_log(cfg, line):
    p = fit_log_path(cfg)
    try:
        with open(p) as f:
            old = f.read().splitlines()
    except OSError:
        old = []
    keep = (old + [line])[-FIT_LOG_KEEP:]
    tmp = '%s.tmp.%d' % (p, os.getpid())
    try:
        with open(tmp, 'w') as f:
            f.write('\n'.join(keep) + '\n')
        os.replace(tmp, p)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def run_fit(cfg, token=None):
    """Fit and write the model; with token, release that refit lock after a success."""
    started = time.time()
    delay = os.environ.get('CLADE_TASK_ETA_FIT_DELAY', '')     # tests: hold the lock this long
    if delay:
        time.sleep(float(delay))
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    try:
        model = fit_model()
        write_model(model, model_path(cfg))
    except Exception as e:  # noqa: BLE001 — logged; the lock stays until stale, which is the backoff
        _append_fit_log(cfg, '%s fit failed: %s: %s' % (stamp, type(e).__name__, str(e)[:200]))
        return 1
    _append_fit_log(cfg, '%s fit ok files=%d tasks=%d bg=%d seconds=%.1f' % (
        stamp, model['n_files'], model['episode']['n_items'], model['bg']['n_items'], time.time() - started))
    if token:
        release_lock(lock_path(cfg), token)
    return 0


# ─── Refit trigger: O_EXCL lock, one detached low-priority child ───
def _create_excl(path, token):
    """The token if this call created path (O_EXCL), None if it exists."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    with os.fdopen(fd, 'w') as f:
        f.write(token + '\n')
    return token


def _age(path, now):
    try:
        return now - os.path.getmtime(path)
    except OSError:
        return None                      # gone


def _held(age):
    """A lock of this age (None: gone) still belongs to a live refit."""
    return age is not None and age < LOCK_STALE_S


_RACE = lambda stage: None   # noqa: E731 — the self-test runs a competing locker at each stage


def try_lock(path, now=None):
    """Create the lock with O_EXCL; break it if it is older than LOCK_STALE_S.
    Returns the token written into it, or None when another refit holds it.
    (O_EXCL, not mkdir: a lost mkdir race can exit 0 on some coreutils.)
    Breaking happens under a second O_EXCL lock, with the age checked again inside it: of several
    callers that all saw the same stale lock, one breaks it and the rest find the fresh one it made."""
    now = time.time() if now is None else now
    token = '%d-%d-%s' % (os.getpid(), int(now * 1000), os.urandom(3).hex())
    if _create_excl(path, token):
        return token
    age = _age(path, now)
    if age is None:
        return _create_excl(path, token)     # released in between
    if _held(age):
        return None                          # the fast path; the check inside the break lock decides
    _RACE('judged')
    brk = path + '.break'
    if not _create_excl(brk, token):
        b_age = _age(brk, now)
        if b_age is not None and b_age >= BREAK_STALE_S:
            _unlink(brk)                     # a breaker killed mid-break; the next call breaks the lock
        return None
    try:
        if _held(_age(path, now)):
            return None                      # another caller broke it first: its lock is fresh
        _RACE('breaking')
        _unlink(path)
        return _create_excl(path, token)
    finally:
        release_lock(brk, token)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def release_lock(path, token):
    """Remove the lock only while it still holds our token (a stale-breaker may own it now)."""
    try:
        with open(path) as f:
            if f.read().strip() != token:
                return False
        os.unlink(path)
        return True
    except OSError:
        return False


def spawn_refit(cfg, token):
    """Start `--fit --background` detached, so the --json caller never waits for it."""
    import subprocess
    kw = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
          'close_fds': True}
    if os.name == 'nt':
        kw['creationflags'] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw['start_new_session'] = True
    env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '--fit', '--background',
                      '--lock-token', token], env=env, **kw)


_SPAWN = spawn_refit


def model_for_json(cfg, now):
    """The model (None when missing), after starting one refit if it is missing or a day old.
    Only --json calls this: the line prints no band, so it never reads the model or refits it."""
    path = model_path(cfg)
    model = load_model(path)
    try:
        age = now - os.path.getmtime(path) if model is not None else None
    except OSError:
        age = None
    if model is None or age is None or age > MODEL_MAX_AGE_S:
        try:
            token = try_lock(lock_path(cfg), now)
        except OSError:                  # a missing or read-only config dir: no refit, use what there is
            token = None
        if token is not None:
            try:
                _SPAWN(cfg, token)
            except Exception:  # noqa: BLE001 — no refit this time; do not leave the lock behind
                release_lock(lock_path(cfg), token)
    return model


# ─── Live estimate ───
def live_background(tl, T):
    """Background jobs launched during the last TAIL_EPISODES tasks, not seen to finish, and not
    stale at T. The last tasks, not every task: that is all the tail reader sees, and a full parse
    must answer the same, or what the status line shows would depend on chunk boundaries."""
    out = []
    for ep in tl.episodes[-TAIL_EPISODES:]:
        for launch, done, kind, expire in ep['bgs']:
            if launch <= T and (done is None or done > T) and (expire is None or expire > T) \
                    and T - launch < BG_STALE_S * 1000:
                out.append((launch, kind, expire))
    return out


def estimate_records(recs, found, model, now_ms):
    tl = Timeline()
    for r in recs:
        tl.feed(r)
    if not tl.episodes:
        return {'state': 'none'}
    ep = tl.episodes[-1]
    T = now_ms
    active = any(tl.turns[i]['t1'] is None or tl.turns[i]['t1'] > T for i in ep['turns'])
    out = {'state': 'active' if active else 'idle', 'found_start': found,
           'elapsed_s': max(0.0, (T - ep['t0']) / 1000.0)}
    if active and found:
        out['task'] = lookup(model, 'episode', out['elapsed_s'])
    inflight = live_background(tl, T)
    if inflight:
        rank = {k: i for i, k in enumerate(BG_PRIORITY)}
        launch, kind, expire = min(inflight, key=lambda x: (rank.get(x[1], len(rank)), x[0]))
        age = (T - launch) / 1000.0
        out['bg'] = {'kind': kind, 'age_s': age, 'more': len(inflight) - 1,
                     'range': None if kind == 'monitor' else lookup(model, 'bg', age),
                     'left_max_s': None if expire is None else (expire - T) / 1000.0}
    return out


def estimate(path, model, now_ms):
    recs, found = read_tail_records(path)
    return estimate_records(recs, found, model, now_ms)


# ─── Line ───
def fmt_dur(s):
    s = max(0, s)
    if s < 60:
        return '%ds' % s
    if round(s / 60) < 60:
        return '%dm' % round(s / 60)
    if round(s / 3600) < 24:
        h = s / 3600
        return ('%.1fh' % h) if h < 9.95 else '%dh' % round(h)
    return '%.1fd' % (s / 86400)


def fmt_forms(est):
    """The segment two ways, longest first; the status line keeps the longer one when it fits its pane.
    Busy prints the task's elapsed time. With no turn running it adds the job it waits on, and a
    Monitor's timeout, the one exact bound. Idle prints nothing: an empty segment is the pane's cue."""
    state = est.get('state')
    bg = est.get('bg')
    if state not in ('active', 'idle') or (state == 'idle' and not bg):
        return []
    head = fmt_dur(est['elapsed_s']) + ('' if est.get('found_start') else '+')
    if state == 'active':                 # a running turn is the news; a job beside it is not
        return [head]
    job = '%s %s' % (head, bg['kind'])
    if bg.get('left_max_s') is not None:  # a Monitor's timeout: an upper bound, never an estimate
        job += ' ≤%s left' % fmt_dur(bg['left_max_s'])
    return [job, head]


def fmt_line(est):
    forms = fmt_forms(est)
    return forms[0] if forms else ''


# ─── CLI: status line ───
class _Deadline(Exception):
    pass


def _arm_deadline():
    try:
        import signal

        def _fire(*_):
            raise _Deadline()
        signal.signal(signal.SIGALRM, _fire)
        signal.setitimer(signal.ITIMER_REAL, DEADLINE_S)
    except (ImportError, AttributeError, ValueError, OSError):
        pass                              # no SIGALRM (Windows) or not the main thread


def _disarm_deadline():
    try:
        import signal
        signal.setitimer(signal.ITIMER_REAL, 0)
    except (ImportError, AttributeError, ValueError, OSError):
        pass


def cmd_statusline(argv, stdin=None, stdout=None):
    stdout = stdout or sys.stdout
    try:
        _arm_deadline()
        if '--stdin' in argv:
            data = json.loads((stdin or sys.stdin).read() or '{}')
            path = data.get('transcript_path') if isinstance(data, dict) else None
        else:
            i = argv.index('--transcript') if '--transcript' in argv else -1
            path = argv[i + 1] if 0 <= i < len(argv) - 1 else None
        if not isinstance(path, str) or not path or not os.path.isfile(path):
            return 0
        # The band is --json's alone. The line prints none, so it never reads the model or starts a
        # refit, and a corrupt model cannot blank it. File ages use the real clock.
        model = model_for_json(config_dir(), time.time()) if '--json' in argv else None
        est = estimate(path, model, now_s() * 1000.0)
        if '--json' in argv:
            out = json.dumps(est)
        else:
            out = '\n'.join(fmt_forms(est)) if '--forms' in argv else fmt_line(est)
        if out:
            stdout.write(out + '\n')
    except BaseException:  # noqa: BLE001 — fail soft: the other segments must still render
        pass
    finally:
        _disarm_deadline()
    return 0


# ─── CLI: --check-tail (local diagnostic over the owner's own transcripts) ───
def compare_tail_full(path, nows_ms, chunk=CHUNK):
    """True when the tail read and a full parse give the same estimate at every now."""
    tail, found = read_tail_records(path, chunk=chunk)
    full = read_all_records(path)
    for now_ms in nows_ms:
        a = estimate_records(tail, found, None, now_ms)
        b = estimate_records(full, True, None, now_ms)
        if a != b:
            return False
    return True


def cmd_check_tail(argv):
    i = argv.index('--check-tail')
    n = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else 40
    sys.path.insert(0, HERE)
    import transcripts
    files = sorted(transcripts.find_transcripts(transcripts.default_roots(), FIT_WINDOW_DAYS),
                   key=lambda p: -p.stat().st_size)[:n]
    same = 0
    for p in files:
        last = os.path.getmtime(p) * 1000.0
        same += compare_tail_full(str(p), [last, last + 600000.0, last + 3 * 3600000.0])
    print('tail read == full parse: %d of %d largest main-thread transcripts (mtime <= %d d)' % (
        same, len(files), FIT_WINDOW_DAYS))
    return 0 if same == len(files) else 1


# ─── Self-test (synthetic transcripts only) ───
_T0 = 1794505738107.0     # a fixed instant for the synthetic transcripts: 2026-11-12T17:48:58.107Z
MIN = 60000.0


def _iso(ms):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(ms / 1000)) + '.%03dZ' % (int(ms) % 1000)


class _Synth:
    """One synthetic transcript, records in Claude Code's top-level key order."""

    def __init__(self):
        self.lines = []
        self.n = 0

    def _rec(self, kind, ms, **kw):
        self.n += 1
        r = {'parentUuid': 'p%d' % self.n, 'isSidechain': False, 'type': kind}
        msg = kw.pop('message', None)
        if msg is not None:
            r['message'] = msg
        r['uuid'] = 'u%d' % self.n
        r['timestamp'] = _iso(ms)
        r.update(kw)
        self.lines.append(json.dumps(r, separators=(',', ':')))
        return self

    def prompt(self, ms, source='typed'):
        return self._rec('user', ms, message={'role': 'user', 'content': 'a synthetic prompt'},
                         turnOrigin='human', promptSource=source, origin={'kind': 'human'})

    def notification(self, ms, tuid, queued=False):
        text = ('<task-notification>\n<task-id>t-%s</task-id>\n<tool-use-id>%s</tool-use-id>\n'
                '<status>completed</status>\n</task-notification>' % (tuid, tuid))
        if queued:
            return self._rec('attachment', ms, attachment={'type': 'queued_command', 'prompt': text})
        return self._rec('user', ms, message={'role': 'user', 'content': text}, turnOrigin='task_notification',
                         promptSource='system', origin={'kind': 'task-notification'})

    def tool(self, ms, tid, name, **inp):
        return self._rec('assistant', ms, message={'model': 'synthetic', 'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}]})

    def result(self, ms, tid, pad=0, error=None, **tur):
        block = {'type': 'tool_result', 'content': (error or '') + 'x' * pad or 'ok'}
        if error:
            block['is_error'] = True
        block['tool_use_id'] = tid
        return self._rec('user', ms, message={'role': 'user', 'content': [block]},
                         toolUseResult='Error: ' + error if error else tur)

    def turn_end(self, ms):
        return self._rec('system', ms, subtype='turn_duration', durationMs=0)

    def interrupt(self, ms):
        return self._rec('user', ms, message={'role': 'user', 'content': [
            {'type': 'text', 'text': '[Request interrupted by user]'}]})

    def raw(self, line):
        self.lines.append(line)
        return self

    def write(self, path, age_s=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(''.join(line + '\n' for line in self.lines))
        if age_s is not None:
            t = time.time() - age_s
            os.utime(path, (t, t))
        return path


def _draw(rng):
    """A heavy-tailed task duration in seconds: mostly minutes, with a long tail of hours."""
    if rng.random() < 0.12:
        return rng.lognormvariate(math.log(3 * 3600), 0.8)
    return max(15.0, rng.lognormvariate(math.log(300), 1.4))


def _synthetic_history(root, rng, n_sessions):
    """n_sessions transcripts of three tasks each; every other task waits on a Workflow.
    Returns (tasks, bg jobs) the fit should count."""
    n_bg = 0
    for s in range(n_sessions):
        syn = _Synth()
        t = _T0 - 25 * 86400000.0 + s * 3 * 86400000.0 / n_sessions
        for e in range(3):
            d = _draw(rng) * 1000.0
            syn.prompt(t).tool(t + 2000, 'b%d_%d' % (s, e), 'Bash', command='ls').result(t + 3000, 'b%d_%d' % (s, e))
            if e % 2 == 0:
                wid = 'w%d_%d' % (s, e)
                syn.tool(t + 4000, wid, 'Workflow', script='s').result(t + 5000, wid, taskId='t-' + wid)
                syn.turn_end(t + 6000).notification(t + d - 3000, wid).turn_end(t + d)
                n_bg += 1
            else:
                syn.turn_end(t + d)
            t += d + 600000.0
        syn.write(os.path.join(root, '-synthetic-p%d' % (s % 4), 's%d.jsonl' % s), age_s=3 * 86400)
    return 3 * n_sessions, n_bg


def _within2(pred, act):
    return abs(math.log2(max(pred, 1.0) / max(act, 1.0))) <= 1.0


def self_test():
    import io
    import random
    import shutil
    import tempfile
    global _SPAWN, _RACE
    fails = []

    def check(ok, what):
        print('%s  %s' % ('ok  ' if ok else 'FAIL', what))
        if not ok:
            fails.append(what)

    tmp = tempfile.mkdtemp(prefix='task-eta-selftest-')
    saved = {k: os.environ.get(k) for k in ('HOME', 'CLAUDE_CONFIG_DIR', 'CLADE_TASK_ETA_NOW')}
    saved_spawn, saved_race = _SPAWN, _RACE
    try:
        os.environ['HOME'] = tmp
        cfg = os.path.join(tmp, 'cfg')
        os.makedirs(cfg)
        os.environ['CLAUDE_CONFIG_DIR'] = cfg
        os.environ.pop('CLADE_TASK_ETA_NOW', None)
        _selftest_body(tmp, cfg, check, io, random)
    finally:
        _SPAWN, _RACE = saved_spawn, saved_race
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print('SELF-TEST FAILED: ' + '; '.join(fails))
        return 1
    print('SELF-TEST PASSED')
    return 0


def _selftest_body(tmp, cfg, check, io, random):
    global _SPAWN, _RACE
    # 1. Fit: the history, plus files the fit must leave out or count once.
    root = os.path.join(tmp, 'projects')
    n_tasks, n_bg = _synthetic_history(root, random.Random(1), 250)
    hist = os.path.join(root, '-synthetic-p0', 's0.jsonl')
    with open(hist) as f:
        text = f.read()
    with open(os.path.join(root, '-synthetic-p0', 's0-fork.jsonl'), 'w') as f:
        f.write(text)                                  # a forked session repeats s0's tasks
    os.utime(os.path.join(root, '-synthetic-p0', 's0-fork.jsonl'), (time.time() - 86400,) * 2)
    old = _Synth()
    for i in range(30):
        old.prompt(_T0 + i * 7200000.0).turn_end(_T0 + i * 7200000.0 + 3600000.0)
    old.write(os.path.join(root, '-synthetic-old', 'old.jsonl'), age_s=(FIT_WINDOW_DAYS + 1) * 86400)
    live = _Synth().prompt(_T0).turn_end(_T0 + 60000).prompt(_T0 + 120000).turn_end(_T0 + 180000)
    live.write(os.path.join(root, '-synthetic-live', 'live.jsonl'))          # touched now: last task censored
    model = fit_model(roots=[root])
    check(model['episode']['n_items'] == n_tasks + 1,
          'fit counts %d tasks: 30-day window, censored last task, forked session once (got %d)' % (
              n_tasks + 1, model['episode']['n_items']))
    check(model['bg']['n_items'] == n_bg, 'fit counts %d background jobs (got %d)' % (n_bg, model['bg']['n_items']))
    sroot = os.path.join(tmp, 'projects-stops')
    (_Synth().prompt(_T0).tool(_T0 + 5000, 'w1', 'Workflow', script='s').result(_T0 + 6000, 'w1', taskId='t-w1')
     .tool(_T0 + 7000, 'w2', 'Workflow', script='s').result(_T0 + 8000, 'w2', error='refused')
     .turn_end(_T0 + 9000).prompt(_T0 + 10 * MIN).tool(_T0 + 11 * MIN, 's1', 'TaskStop', task_id='t-w1')
     .turn_end(_T0 + 12 * MIN)).write(os.path.join(sroot, '-synthetic-stops', 'x.jsonl'), age_s=3 * 86400)
    check(fit_model(roots=[sroot])['bg']['n_items'] == 1,
          'fit: a job stopped with TaskStop is fitted up to its stop; a refused launch is not fitted')
    mp = model_path(cfg)
    write_model(model, mp)
    check(load_model(mp) == json.loads(json.dumps(model)) and os.listdir(cfg) == ['task-eta-model.json'],
          'model written whole, no temporary file left')

    # 2. Held-out: the survival lookup must beat the global median (same generator, another seed).
    rng = random.Random(2)
    held = [_draw(rng) for _ in range(3000)]
    p0 = model['episode']['p0_median_s']
    hit1, hit0, cov = [], [], []
    for c in (1, 5, 15, 30, 60):
        t = c * 60.0
        rows = [d - t for d in held if d > t]
        rng_t = lookup(model, 'episode', t)
        hit1.append(sum(_within2(rng_t['p50'], a) for a in rows) / len(rows))
        hit0.append(sum(_within2(p0, a) for a in rows) / len(rows))
        cov.append(sum(rng_t['p25'] <= a <= rng_t['p75'] for a in rows) / len(rows))
    s1, s0, sc = sum(hit1) / 5, sum(hit0) / 5, sum(cov) / 5
    print('      held-out within 2x: survival lookup %.1f%%, global median %.1f%%; p25-p75 holds %.1f%%' % (
        100 * s1, 100 * s0, 100 * sc))
    check(s1 - s0 >= 0.10, 'the lookup beats the global median by 10 points or more')
    check(0.35 <= sc <= 0.65, 'the p25-p75 band holds the truth about half the time')
    a, b = lookup(model, 'episode', 60), lookup(model, 'episode', 3600)
    check(b['p50'] > a['p50'], 'the median left grows with elapsed time (1 min %.0fs, 60 min %.0fs)' % (
        a['p50'], b['p50']))
    check(survival_quantiles(model['episode'], 5 * 3600) is not None,
          'fixture: past tasks survive 5 h, so only the horizon guard can say beyond history there')

    def line_at(syn, now_ms, mdl=model, name='t.jsonl'):
        p = syn.write(os.path.join(tmp, 'live', name))
        est = estimate(p, mdl, now_ms)
        return fmt_line(est), est

    # 3. idle | bg workflow, from a turn that launched a Workflow and ended.
    wf = (_Synth().prompt(_T0).tool(_T0 + 2000, 'b1', 'Bash', command='make').result(_T0 + 3000, 'b1')
          .tool(_T0 + 5000, 'w1', 'Workflow', script='s').result(_T0 + 6000, 'w1', taskId='t-w1')
          .turn_end(_T0 + 9000))
    line, est = line_at(wf, _T0 + 20 * MIN)
    check(line == '20m workflow', 'Workflow in flight after its turn: %r' % line)
    check(isinstance(est['bg']['range'], dict), 'fixture: the lookup ran: %r' % (est['bg']['range'],))
    narrow = json.loads(json.dumps(model))         # a history whose background jobs all took ~10-20 min
    narrow['bg']['global'] = [None if c is None else [600.0, 900.0, 1200.0] + c[3:] for c in narrow['bg']['global']]
    line, est = line_at(wf, _T0 + 20 * MIN, mdl=narrow)
    check(line == '20m workflow' and est['bg']['range']['p75'] <= 2 * est['bg']['range']['p25'],
          'no band prints, however narrow: %r' % line)
    # 4. A prompt typed while the Workflow runs still shows it; the task restarts at that prompt.
    wf2 = _Synth()
    wf2.lines = list(wf.lines)
    wf2.n = wf.n
    wf2.prompt(_T0 + 10 * MIN).turn_end(_T0 + 10.5 * MIN)
    line, _ = line_at(wf2, _T0 + 30 * MIN)
    check(line == '20m workflow', 'Workflow from the previous prompt still shown: %r' % line)
    # 5. A notification-started turn belongs to the task the human prompt started.
    notif = (_Synth().prompt(_T0).tool(_T0 + 5000, 'w1', 'Workflow', script='s').result(_T0 + 6000, 'w1')
             .turn_end(_T0 + 9000).notification(_T0 + 20 * MIN, 'w1')
             .tool(_T0 + 20 * MIN + 5000, 'b2', 'Bash', command='pytest'))
    line, est = line_at(notif, _T0 + 25 * MIN)
    check(line == '25m' and isinstance(est['task'], dict),
          'task elapsed counts from the human prompt, not the notification turn: %r' % line)
    # 6. Beyond history: at 5 h elapsed, and where no past task survived.
    fg = _Synth().prompt(_T0).tool(_T0 + 2000, 'b1', 'Bash', command='sleep 99999')
    line, est = line_at(fg, _T0 + 300 * MIN)
    check(line == '5.0h' and est['task'] == BEYOND, 'past the horizon: %r' % line)
    line, est = line_at(fg, _T0 + 3 * 1440 * MIN)
    check(line == '3.0d' and est['task'] == BEYOND, 'past the history: %r' % line)
    thin = json.loads(json.dumps(model))           # a history in which no task outlived 30 min
    thin['episode']['global'] = [c if g < 1800 else None for g, c in zip(GRID_S, thin['episode']['global'])]
    line, est = line_at(fg, _T0 + 45 * MIN, mdl=thin)
    check(line == '45m' and est['task'] == BEYOND, 'past a thin history, inside the horizon: %r' % line)
    # 7. A Monitor is open-ended: its age, no range; a declared timeout bounds what is left.
    mon = (_Synth().prompt(_T0).tool(_T0 + 5000, 'm1', 'Monitor', command='tail -f x')
           .result(_T0 + 6000, 'm1', taskId='t-m1').turn_end(_T0 + 9000))
    line, est = line_at(mon, _T0 + 12 * MIN)
    check(line == '12m monitor', 'Monitor in flight: %r' % line)
    check(est['bg']['range'] is None, 'a Monitor carries no range in the estimate either')
    mon20 = (_Synth().prompt(_T0).tool(_T0 + 5000, 'm1', 'Monitor', command='tail -f x')
             .result(_T0 + 6000, 'm1', taskId='t-m1', timeoutMs=20 * MIN).turn_end(_T0 + 9000))
    line, est = line_at(mon20, _T0 + 12 * MIN)
    check(line == '12m monitor ≤8m left', 'a Monitor\'s timeout bounds what is left: %r' % line)
    # 8. Several in flight: a Workflow is named before an older background Bash.
    two = (_Synth().prompt(_T0).tool(_T0 + 1000, 'b1', 'Bash', command='serve', run_in_background=True)
           .result(_T0 + 1500, 'b1', backgroundTaskId='bt1')
           .tool(_T0 + 60000, 'w1', 'Workflow', script='s').result(_T0 + 61000, 'w1').turn_end(_T0 + 62000))
    line, _ = line_at(two, _T0 + 10 * MIN)
    check(line == '10m workflow', 'Workflow named before the older background Bash: %r' % line)
    # 8b. While a turn runs, the line is its elapsed time; the job beside it is not named.
    busy = (_Synth().prompt(_T0).tool(_T0 + 1000, 'b1', 'Bash', command='serve', run_in_background=True)
            .result(_T0 + 1500, 'b1', backgroundTaskId='bt1').tool(_T0 + 60000, 'r1', 'Read', file_path='x'))
    line, est = line_at(busy, _T0 + 5 * MIN)
    check(line == '5m' and est['bg']['kind'] == 'bash', 'a running turn hides the job beside it: %r' % line)
    # 9. An interrupt ends the turn; a launch a day old with no completion is not in flight.
    intr = _Synth().prompt(_T0).tool(_T0 + 2000, 'b1', 'Bash', command='x').interrupt(_T0 + 60000)
    line, est = line_at(intr, _T0 + 5 * MIN)
    check(line == '' and est['state'] == 'idle', 'an interrupted turn reads as ended, and idle prints nothing: %r' % line)
    stale = (_Synth().prompt(_T0).tool(_T0 + 5000, 'b1', 'Bash', command='serve', run_in_background=True)
             .turn_end(_T0 + 9000).prompt(_T0 + 25 * 60 * MIN).turn_end(_T0 + 25 * 60 * MIN + 10000))
    line, _ = line_at(stale, _T0 + 25 * 60 * MIN + 5 * MIN)
    check(line == '', 'a day-old launch with no completion is not in flight: %r' % line)
    # 9b. A stop ends the job it names (no completion notice follows a stop), and only that job.
    stop = (_Synth().prompt(_T0).tool(_T0 + 5000, 'w1', 'Workflow', script='s').result(_T0 + 6000, 'w1', taskId='t-w1')
            .tool(_T0 + 60000, 's1', 'TaskStop', task_id='t-w1').result(_T0 + 61000, 's1', task_id='t-w1')
            .turn_end(_T0 + 62000))
    line, _ = line_at(stop, _T0 + 2 * MIN)
    check(line == '', 'a Workflow stopped with TaskStop is not in flight: %r' % line)
    kill = (_Synth().prompt(_T0).tool(_T0 + 5000, 'b1', 'Bash', command='serve', run_in_background=True)
            .result(_T0 + 6000, 'b1', backgroundTaskId='bt1').tool(_T0 + 60000, 'k1', 'KillShell', shell_id='bt1')
            .result(_T0 + 61000, 'k1').turn_end(_T0 + 62000))
    line, _ = line_at(kill, _T0 + 2 * MIN)
    check(line == '', 'a background Bash stopped with KillShell is not in flight: %r' % line)
    other = (_Synth().prompt(_T0).tool(_T0 + 5000, 'w1', 'Workflow', script='s').result(_T0 + 6000, 'w1', taskId='t-w1')
             .tool(_T0 + 60000, 's1', 'TaskStop', task_id='t-other').turn_end(_T0 + 62000))
    line, _ = line_at(other, _T0 + 2 * MIN)
    check(line == '2m workflow', 'a stop naming another job ends nothing: %r' % line)
    # 9c. A launch whose call failed or was refused never ran (a short result, and one the light parser cuts).
    for pad in (0, 2 * LIGHT_MIN):
        den = (_Synth().prompt(_T0).tool(_T0 + 5000, 'w1', 'Workflow', script='s')
               .result(_T0 + 6000, 'w1', pad=pad, error='denied by a hook').turn_end(_T0 + 9000))
        line, _ = line_at(den, _T0 + 5 * MIN)
        check(line == '', 'a refused Workflow launch is not in flight (%d-byte pad): %r' % (pad, line))
    # 10. No model yet: elapsed only.
    line, est = line_at(wf, _T0 + 20 * MIN, mdl=None)
    check(line == '20m workflow' and est['bg']['range'] is None, 'no model, elapsed only: %r' % line)
    # 10b. The two forms, longest first.
    forms = fmt_forms(line_at(mon20, _T0 + 12 * MIN)[1])
    check(forms == ['12m monitor ≤8m left', '12m'], 'two forms, the job then the time: %r' % forms)
    check(fmt_forms(line_at(fg, _T0 + 5 * MIN)[1]) == ['5m'], 'a running turn has one form')
    check(fmt_forms(line_at(intr, _T0 + 5 * MIN)[1]) == [], 'idle has none')
    durs = [fmt_dur(x) for x in (59, 3569, 3590, 35800, 35900, 86000)]
    check(durs == ['59s', '59m', '1.0h', '9.9h', '10h', '1.0d'], 'durations round into the next unit: %r' % durs)

    # 11. The tail read gives what a full parse gives (sparse lines, chunk edges, light tool results).
    big = _Synth()
    t = _T0
    for e in range(6):          # every job of the first tasks finishes but one server; the last ones still run
        big.prompt(t, source='queued' if e == 3 else 'typed')
        if e == 0:              # never finishes, launched four tasks before the last: not in flight
            big.tool(t + 500, 'srv', 'Bash', command='serve', run_in_background=True).result(
                t + 600, 'srv', backgroundTaskId='bsrv')
        big.tool(t + 1000, 'w%d' % e, 'Workflow', script='s').result(t + 2000, 'w%d' % e, pad=6000, taskId='t%d' % e)
        big.tool(t + 3000, 'a%d' % e, 'Agent', prompt='p').result(t + 9000, 'a%d' % e, pad=5000, isAsync=True,
                                                                     agentId='ag%d' % e)
        big.tool(t + 10000, 'c%d' % e, 'Bash', command='long').result(t + 70000, 'c%d' % e,
                                                                       backgroundTaskId='bc%d' % e)
        big.tool(t + 71000, 'm%d' % e, 'Monitor', command='m').result(t + 72000, 'm%d' % e, timeoutMs=1200000)
        if e == 4:              # one job stopped, one launch refused (a result the light parser cuts)
            big.tool(t + 73000, 'k4', 'TaskStop', task_id='bc4').result(t + 73500, 'k4', task_id='bc4')
            big.tool(t + 74000, 'f4', 'Workflow', script='s').result(t + 74500, 'f4', pad=6000, error='refused')
        big.raw('{"type":"user", not json').raw('{"type":"file-history-snapshot","x":1}')
        big.turn_end(t + 80000)
        big.notification(t + 5 * MIN, 'w%d' % e, queued=(e % 2 == 1))
        if e % 2 == 0:
            big.turn_end(t + 5.2 * MIN)
        if e < 5:
            big.notification(t + 6 * MIN, 'a%d' % e).turn_end(t + 6.5 * MIN)
        if e < 4:
            big.notification(t + 20 * MIN, 'c%d' % e).turn_end(t + 20.5 * MIN)
        t += 30 * MIN
    bp = big.write(os.path.join(tmp, 'live', 'big.jsonl'))
    nows = [t - 30 * MIN + d * MIN for d in (0.5, 2, 5.5, 7, 21, 40)]
    check(compare_tail_full(bp, nows) and compare_tail_full(bp, nows, chunk=4096),
          'tail read == full parse on a six-task transcript (1 MB and 4 KB chunks)')
    est = estimate(bp, None, nows[2])
    check(est.get('bg', {}).get('more') == 2,
          'fixture: three jobs in flight at once, a fourth stopped and a fifth refused (got %r)' % est.get('bg'))

    # 12. The refit lock.
    now = time.time()
    lp = os.path.join(tmp, 'x.lock')
    tok = try_lock(lp, now)
    check(tok is not None and try_lock(lp, now) is None, 'a held lock refuses a second refit')
    check(not release_lock(lp, 'not-ours') and os.path.exists(lp), 'a lock is released only by its owner')
    os.utime(lp, (now - LOCK_STALE_S + 60,) * 2)
    check(try_lock(lp, now) is None, 'a lock younger than the stale timeout still holds')
    os.utime(lp, (now - LOCK_STALE_S - 60,) * 2)
    check(try_lock(lp, now) is not None and not os.path.exists(lp + '.break'),
          'a stale lock is broken, and no break lock is left behind')

    def race(stage_for_a):
        """b sees the lock stale; a competing caller a runs whole at stage_for_a of b's break."""
        global _RACE
        for q in (lp, lp + '.break'):
            if os.path.exists(q):
                os.unlink(q)
        open(lp, 'w').close()
        os.utime(lp, (now - LOCK_STALE_S - 60,) * 2)
        got = {}

        def hook(stage):
            global _RACE
            if stage == stage_for_a:
                _RACE = lambda _s: None     # noqa: E731
                got['a'] = try_lock(lp, now)
        _RACE = hook
        try:
            got['b'] = try_lock(lp, now)
        finally:
            _RACE = lambda _s: None         # noqa: E731
        with open(lp) as f:
            held = f.read().strip()
        return sorted(k for k, v in got.items() if v and v == held), sorted(k for k, v in got.items() if v)
    check(race('judged') == (['a'], ['a']), 'two callers saw one stale lock; the one that broke it first holds it')
    check(race('breaking') == (['b'], ['b']), 'a caller that finds the lock being broken backs off')
    open(lp + '.break', 'w').close()
    os.utime(lp + '.break', (now - BREAK_STALE_S - 5,) * 2)
    os.utime(lp, (now - LOCK_STALE_S - 60,) * 2)
    first = try_lock(lp, now)
    check(first is None and try_lock(lp, now) is not None,
          'a break lock left by a killed breaker is cleared, and the next call breaks the stale lock')

    # 13. The refit trigger: one spawn while missing, none while fresh, one more once a day old.
    calls = []
    _SPAWN = lambda c, k: calls.append(k)   # noqa: E731
    c2 = os.path.join(tmp, 'cfg2')
    os.makedirs(c2)
    first = model_for_json(c2, now)
    model_for_json(c2, now)
    check(first is None and len(calls) == 1, 'missing model: one refit across two calls (%d)' % len(calls))
    write_model(model, model_path(c2))
    release_lock(lock_path(c2), calls[0])
    check(model_for_json(c2, now) is not None and len(calls) == 1, 'fresh model: no refit')
    os.utime(model_path(c2), (now - MODEL_MAX_AGE_S - 60,) * 2)
    check(model_for_json(c2, now) is not None and len(calls) == 2, 'day-old model: used, and refitted')

    def boom(c, k):
        raise OSError('spawn failed')
    _SPAWN = boom
    for p in (lock_path(c2), model_path(c2)):
        if os.path.exists(p):
            os.unlink(p)
    model_for_json(c2, now)
    check(not os.path.exists(lock_path(c2)), 'a failed spawn leaves no lock behind')

    # 14. The status-line entry point fails soft.
    _SPAWN = lambda c, k: None              # noqa: E731
    os.environ['CLADE_TASK_ETA_NOW'] = '%.3f' % ((_T0 + 20 * MIN) / 1000.0)
    wfp = wf.write(os.path.join(tmp, 'live', 'wf.jsonl'))

    def run(argv, stdin=''):
        out = io.StringIO()
        rc = cmd_statusline(argv, stdin=io.StringIO(stdin), stdout=out)
        return rc, out.getvalue().strip()
    rc, out = run(['--stdin'], json.dumps({'transcript_path': wfp}))
    check(rc == 0 and out == '20m workflow', 'status-line JSON on stdin: %r' % out)
    rc, out = run(['--stdin', '--forms'], json.dumps({'transcript_path': wfp}))
    check(rc == 0 and out.split('\n') == ['20m workflow', '20m'], '--forms prints two lines, longest first: %r' % out)
    rc, out = run(['--stdin', '--json'], json.dumps({'transcript_path': wfp}))
    check(rc == 0 and isinstance(json.loads(out)['bg']['range'], dict), 'with a model, the estimate has a band')
    os.environ['CLAUDE_CONFIG_DIR'] = os.path.join(tmp, 'no-such-dir')
    rc, out = run(['--transcript', wfp])
    rc2, js = run(['--transcript', wfp, '--json'])
    os.environ['CLAUDE_CONFIG_DIR'] = cfg
    check(rc == 0 and out == '20m workflow' and js and json.loads(js)['bg']['range'] is None,
          'a missing config dir: the line prints, --json carries no band: %r %r' % (out, js))
    rc, out = run(['--transcript', wfp, '--json'])
    check(rc == 0 and json.loads(out).get('bg', {}).get('kind') == 'workflow', '--json prints the estimate')
    bad = _Synth()
    bad.lines = wf.lines[:2] + ['{"type":"user","message":', '\x00\xff garbage'] + wf.lines[2:]
    rc, out = run(['--transcript', bad.write(os.path.join(tmp, 'live', 'bad.jsonl'))])
    check(rc == 0 and out == '20m workflow', 'malformed lines are skipped: %r' % out)
    empty = os.path.join(tmp, 'live', 'empty.jsonl')
    open(empty, 'w').close()
    for argv, stdin, what in ((['--stdin'], 'not json', 'stdin not JSON'),
                              (['--stdin'], json.dumps({'transcript_path': '/nonexistent/x.jsonl'}), 'no transcript'),
                              (['--stdin'], json.dumps(['a list']), 'JSON not an object'),
                              (['--transcript', empty], '', 'empty transcript'),
                              (['--transcript', tmp], '', 'a directory')):
        rc, out = run(argv, stdin)
        check(rc == 0 and out == '', 'fails soft, prints nothing: %s' % what)
    with open(model_path(cfg), 'w') as f:
        json.dump({'version': MODEL_VERSION, 'grid_s': GRID_S, 'episode': {'global': ['corrupt']}}, f)
    np_ = notif.write(os.path.join(tmp, 'live', 'n.jsonl'))
    rc, out = run(['--transcript', np_])
    rc2, js = run(['--transcript', np_, '--json'])
    check(rc == 0 and out == '20m', 'a corrupt model: the line never reads it: %r' % out)
    check(rc2 == 0 and js == '', 'a corrupt model raises inside the --json estimate, which prints nothing')

    # 15. Only --json reads the model and refits it: a line call on a missing model starts nothing.
    calls = []
    _SPAWN = lambda c, k: calls.append(k)   # noqa: E731
    c3 = os.path.join(tmp, 'cfg3')
    os.makedirs(c3)
    os.environ['CLAUDE_CONFIG_DIR'] = c3
    rc, out = run(['--stdin', '--forms'], json.dumps({'transcript_path': wfp}))
    check(rc == 0 and out.split('\n') == ['20m workflow', '20m'] and calls == [] and os.listdir(c3) == [],
          'a status-line call on a missing model starts no refit and takes no lock: %r %r' % (out, os.listdir(c3)))
    rc, js = run(['--stdin', '--json'], json.dumps({'transcript_path': wfp}))
    check(rc == 0 and len(calls) == 1 and os.listdir(c3) == ['task-eta-model.lock'],
          '--json on a missing model starts one refit behind its lock (%d)' % len(calls))
    os.environ['CLAUDE_CONFIG_DIR'] = cfg


# ─── CLI ───
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--self-test' in argv:
        return self_test()
    if '--fit' in argv:
        cfg = config_dir()
        if '--background' in argv:
            try:
                os.nice(19)
            except (AttributeError, OSError):
                pass
            i = argv.index('--lock-token') if '--lock-token' in argv else -1
            return run_fit(cfg, argv[i + 1] if 0 <= i < len(argv) - 1 else None)
        os.makedirs(cfg, exist_ok=True)
        rc = run_fit(cfg)
        m = load_model(model_path(cfg))
        if m:
            print('wrote %s: %d tasks, %d background jobs, %d transcripts' % (
                model_path(cfg), m['episode']['n_items'], m['bg']['n_items'], m['n_files']))
        return rc
    if '--check-tail' in argv:
        return cmd_check_tail(argv)
    return cmd_statusline(argv)


if __name__ == '__main__':
    sys.exit(main())
