# Goal: Fix Remaining Orchestrator Bugs (Medium/Low Severity)

The critical and high-severity bugs have already been fixed. This goal covers the remaining medium and low severity issues from the audit.

## Backend Fixes Needed

### Medium
1. **Race condition in force_stop** (orchestrator/worker.py ~line 1403): `w.status = "failed"` is set before task_queue update — swap order so task_queue is updated first, then worker status synced
2. **Encoding guards on all plan_path.write_text** (orchestrator/session.py): Audit ALL `write_text()` calls in session.py — ensure every one has `errors="replace"` parameter
3. **Subprocess returncode after timeout** (orchestrator/server.py ~line 927): After TimeoutError in merge_all_done, skip returncode check — process was killed, returncode is meaningless
4. **Imprecise JSON extraction regex** (orchestrator/session.py ~line 245): `re.search(r'\[.*\]', response, re.DOTALL)` can match too greedily with nested brackets. Use a more precise approach: find the FIRST `[` and match to its balanced `]`, or try `json.loads` on the full response first.

### Low
5. **Loop iteration overflow guard** (orchestrator/session.py ~line 556): Add `if iteration >= max_iterations: break` guard before incrementing

## Frontend Fixes Needed

### Medium
6. **Stale activeSessionId in closures** (orchestrator/web/index.html): In `refreshProjectBadge()` (~line 1594), capture `activeSessionId` at call time into a local variable, then check it hasn't changed before applying the result
7. **DOM element movement in intervene panel** (orchestrator/web/index.html ~line 1839-1852): When `openIntervene()` is called, check if a different session's intervene is already open and close it first. In `closeIntervene()`, verify `st.el` still exists before moving it.
8. **Global _logRefreshInterval conflict** (orchestrator/web/index.html ~line 1229): When opening worker log modal, clear any existing interval first. When closing modal, always clear the interval.

### Low
9. **Empty catch blocks**: Replace `catch(e) {}` with `catch(e) { console.warn(e); }` in: fit addon calls (~lines 514, 659), renderAnalytics (~line 2322), renderOverview (~line 2514)
10. **Missing error handling in cancelSchedule** — ALREADY FIXED (skip this)
11. **Array bounds check** (orchestrator/web/index.html ~line 638): `const firstId = [...st.panes.keys()][0]` — add `if (!firstId) return;` guard

## Success Criteria

- `python3 -c "import ast; ast.parse(open('orchestrator/server.py').read())"` passes
- `python3 -c "import ast; ast.parse(open('orchestrator/session.py').read())"` passes
- `python3 -c "import ast; ast.parse(open('orchestrator/worker.py').read())"` passes
- `node -e "new Function(require('fs').readFileSync('orchestrator/web/index.html','utf8').match(/<script>([\s\S]*)<\/script>/)[1])"` passes
- No `catch(e) {}` (empty catch blocks) remain in index.html
- All `write_text()` calls in session.py include `errors="replace"`
- grep for `\[.*\].*re.DOTALL` in session.py returns 0 results (greedy regex replaced)
