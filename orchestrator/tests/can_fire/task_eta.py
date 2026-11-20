"""task-eta.py's mutations, loaded into test_self_tests_can_fire.py's MUTATIONS.

Each one removes one guard the status-line task timer claims, and its
--self-test must turn red. The self-test builds every transcript it reads
(a seeded heavy-tailed history for the fit, then one transcript per case);
nothing derived from a real transcript is involved. The first four are the
guards the feature exists for: the survival lookup, the human-prompt task
boundary, background work in flight, and "beyond history" past the 4 h
horizon. NO_OP_CONTROLS holds the mutation that must stay green.

Not mutated, and why: the one-second deadline (timing, not behaviour), the
atomic tmp+rename write (a reader cannot observe the difference in-process),
and the light tool-result parser (a speed path; json.loads gives the same
records when it is skipped).
"""

from __future__ import annotations

S = "configs/scripts/task-eta.py"

MUTATIONS: dict[str, list[tuple[str, str, str]]] = {S: [
    # The four the feature is for.
    ("the survival lookup — every task gets the global median",
     "    got = survival_quantiles(block, elapsed_s)\n",
     "    got = ([block['p0_median_s']] * 3, block['n_items'])\n"),
    ("the task boundary — every turn, notification turns included, starts a task",
     "            if kind in EP_STARTERS or not self.episodes:",
     "            if True:"),
    ("background work in flight — an idle task never shows its Workflow",
     "    inflight = live_background(tl, T)",
     "    inflight = []"),
    ("the 4 h horizon — a number prints where held-out items were never within 2x",
     "    if elapsed_s >= HORIZON_S:\n        return BEYOND\n",
     ""),
    # The rest of the estimate.
    ("past the history's support — the last cell with data is reused",
     "    if not cell:\n        return None\n    q = [float(v) for v in cell[:3]]",
     "    if not cell:\n        cell = next(c for c in reversed(block['global'][:gi]) if c)\n"
     "    q = [float(v) for v in cell[:3]]"),
    ("a Monitor is open-ended — the line prints no '(open-ended)'",
     "    tail += ' (open-ended)' if bg['kind'] == 'monitor' else _range_txt(bg['range'], False)",
     "    tail += _range_txt(bg['range'], False)"),
    ("a Monitor is open-ended — the estimate carries a range for it",
     "'range': None if kind == 'monitor' else lookup(model, 'bg', age)",
     "'range': lookup(model, 'bg', age)"),
    ("a Monitor's timeout ends it",
     "                    self.bg_by_tuid[tuid][3] = c[0] + tm",
     "                    pass"),
    ("a Workflow is named before older background Bash",
     "    launch, kind = min(inflight, key=lambda x: (rank.get(x[1], len(rank)), x[0]))",
     "    launch, kind = min(inflight, key=lambda x: x[0])"),
    ("in flight means launched during the last three tasks — every task's jobs are searched",
     "    for ep in tl.episodes[-TAIL_EPISODES:]:",
     "    for ep in tl.episodes:"),
    ("a launch a day old with no completion is not in flight",
     "and T - launch < BG_STALE_S * 1000:",
     ":"),
    ("an interrupt ends the turn",
     "            self.cur['last'] = max(self.cur['last'], ts)\n            if self.cur['t1'] is None:\n"
     "                self.cur['t1'] = ts\n",
     "            self.cur['last'] = max(self.cur['last'], ts)\n"),
    # The tail reader agrees with a full parse.
    ("the tail goes back three prompts — a Workflow from the previous prompt disappears",
     "TAIL_EPISODES = 3 ",
     "TAIL_EPISODES = 1 "),
    ("a sparse key — turn ends are no longer read",
     "b'\"subtype\":\"turn_duration\"', ",
     ""),
    ("a sparse key — a queued completion notice is no longer read",
     "b'<task-notification>', ",
     ""),
    ("a sparse key — an interrupt is no longer read",
     ", b'[Request interrupted by user')",
     ")"),
    ("the auto-backgrounded call lookup — its launch moves to its result",
     "        if b'\"backgroundTaskId\"' in line or b'\"isAsync\":true' in line:",
     "        if False:"),
    ("malformed lines are skipped",
     "        except ValueError:\n            return None\n    return r if isinstance(r, dict) else None",
     "        except ValueError:\n            raise\n    return r if isinstance(r, dict) else None"),
    # The fit.
    ("the 30-day window",
     "transcripts.find_transcripts(roots, FIT_WINDOW_DAYS)\n    seen = set()",
     "transcripts.find_transcripts(roots, None)\n    seen = set()"),
    ("the last task of a transcript written in the last 2 h is censored",
     "    eps = tl.episodes[:-1] if censor else tl.episodes",
     "    eps = tl.episodes"),
    ("a forked session's repeated tasks count once",
     "            if ('task', slug, t0) not in seen:",
     "            if True:"),
    # The refit trigger.
    ("O_EXCL — a second refit takes the lock",
     "os.O_CREAT | os.O_EXCL | os.O_WRONLY",
     "os.O_CREAT | os.O_WRONLY"),
    ("a stale lock is broken",
     "            if age < LOCK_STALE_S:",
     "            if True:"),
    ("a lock younger than the stale timeout holds",
     "            if age < LOCK_STALE_S:",
     "            if age < 0:"),
    ("a lock is released only by its owner",
     "            if f.read().strip() != token:",
     "            if False:"),
    ("a day-old model is refitted",
     "    if model is None or age is None or age > MODEL_MAX_AGE_S:",
     "    if model is None:"),
    ("a failed spawn releases the lock",
     "            except Exception:  # noqa: BLE001 — no refit this time; do not leave the lock behind\n"
     "                release_lock(lock_path(cfg), token)",
     "            except Exception:  # noqa: BLE001 — no refit this time; do not leave the lock behind\n"
     "                pass"),
    # The status-line entry point.
    ("fail soft — an exception inside the estimate escapes",
     "    except BaseException:  # noqa: BLE001 — fail soft",
     "    except _Deadline:  # noqa: BLE001 — fail soft"),
]}

# Mutations that change nothing the self-test may notice: it must stay GREEN on them.
NO_OP_CONTROLS: dict[str, list[tuple[str, str, str]]] = {S: [
    ("a comment reworded",
     "# Elapsed grid in seconds; the evaluation checkpoints",
     "# Elapsed grid, in seconds; the evaluation checkpoints"),
]}
