Generate a concise morning briefing for the current project. Follow these steps:

1. Run `git log --since="18 hours ago" --oneline` to get recent commits.
2. Run `git log --since="18 hours ago" --format="%s" | wc -l` to count commits.
3. Probe the orchestrator. **Every control-plane route requires a bearer token**
   (`docs/configuration.md`, "Control-plane authentication"), so an
   unauthenticated request comes back as `401 {"detail": "Missing or invalid API
   token."}` — which is *valid JSON* and must never be read as queue data. Send
   the token and branch on the HTTP status, not on whether the body parses:

   ```bash
   PORT="${ORCHESTRATOR_PORT:-8765}"
   TOKEN=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.claude/orchestrator-settings.json'))).get('api_token',''))" 2>/dev/null)
   curl -s --max-time 5 -w '\n%{http_code}' \
     -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:$PORT/api/sessions/overview"
   ```

   (`python3` rather than the `jq` one-liner in `docs/configuration.md` only
   because python3 is already a hard dependency of this repo's gates. A missing
   or unreadable settings file yields an empty token and no stderr noise.)

   The **last line** of the output is the HTTP status; everything above it is the
   body. Read the two together — never the body alone:

   - curl exits non-zero, or the status is `000` (7 = refused, 28 = timed out)
     → nothing is listening: report `Orchestrator offline`.
   - `200` **and** the body parses as a JSON array → extract
     pending/running/done/failed and total_cost for each session.
   - `401` → the server is up but the token is missing or wrong: report
     `Orchestrator running, no valid api_token in ~/.claude/orchestrator-settings.json`.
   - anything else (`404`, `5xx`, or a `200` whose body is not a JSON array)
     → something other than the orchestrator answered on that port: report
     `Port $PORT busy, not the orchestrator`.

   In every non-`200` case, say which one it was and move on. Do not guess,
   interpolate, or carry over counts from a previous run.
4. If PROGRESS.md exists, read its last 2000 characters to find the most recent lesson entry.
5. Read TODO.md to find the next 3 open `- [ ]` items.

Then output a concise markdown briefing with exactly these sections:

## Overnight Activity
- Number of commits in the last 18 hours
- Most recent 5 commit messages (one per line)

## Queue Status
- Pending / Running / Done / Failed counts, from the `200` branch of step 3 only
- Total cost if available (format: $X.XX)
- If step 3 did not reach the `200` branch, print its one-line reason verbatim
  instead of counts

## Recent Lessons
- The last lesson from PROGRESS.md (one paragraph max). If PROGRESS.md missing: "(no PROGRESS.md found)"

## Suggested Next Actions
1. First open TODO item
2. Second open TODO item
3. Third open TODO item
4. One improvement suggestion based on recent commits or lessons (be specific, not generic)

Keep the entire briefing under 40 lines. Be specific and actionable. Do not pad with filler text.
