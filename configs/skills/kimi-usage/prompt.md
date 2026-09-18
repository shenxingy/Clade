You are the Kimi Usage skill. Show Kimi Code plan-quota usage and pace, or
configure Kimi Code's footer status line.

## Execute

1. Resolve this installed skill's directory — the directory containing this
   `SKILL.md`.
2. Run its bundled helper with Python 3:

   ```bash
   python3 <skill-dir>/scripts/kimi_usage.py [arguments]
   ```

3. Pass through arguments exactly:

   | User request | Helper arguments |
   |--------------|------------------|
   | no arguments, "usage", "quota", "limits" | none |
   | "setup", "wire the footer", "add it to my status line" | `setup` |
   | "setup off", "give me the built-in footer back" | `setup off` |
   | "style" or "list styles" | `style` |
   | "minimal/icon/detail/off style" | `style minimal|icon|detail|off` |
   | "theme" or "list themes" | `theme` |
   | "theme NAME" | `theme NAME` |
   | "json" or machine-readable output | `--json` |

4. Report the helper output directly. If `setup` changed the configuration,
   remind the user that the footer appears in a new Kimi session or after
   `/reload-tui`.

## What the numbers mean

- `N% used` is the window's consumed share as Kimi reports it (`usedRatio`).
- The pace symbol and `+N%` / `-N%` compare the long window (weekly if the
  plan has one, otherwise monthly) against a 95% target: `delta = used% −
  elapsed% × 0.95`. Positive means ahead of the target pace, negative behind.
  The 5-hour window is a burst cap, so it is shown as used% plus time to
  reset, not as a pace.
- `kimi N% · code N%` splits the monthly total between the Kimi app and Kimi
  Code, exactly as Kimi's own `/usage` panel does.

## Safety and scope

- Never read, print, copy, or parse anything under `~/.kimi-code/credentials/`,
  and never call `api.kimi.com/coding/v1/usages` or `api.kimi.ai` directly.
  The helper goes through Kimi Code's documented local server API
  (`kimi web`, `GET /api/v1/oauth/usage`), so the OAuth token and its
  refresh stay inside Kimi.
- The helper may start a `kimi web --no-open` instance on a loopback port for
  the duration of one request and shuts it down afterwards. It never binds a
  non-loopback address.
- `setup` edits exactly one key in `~/.kimi-code/tui.toml`
  (`[status_line].command`). A status line command that is not Clade's is
  reported and left untouched; `setup off` removes only Clade's.
- The status line itself (`~/.kimi-code/hooks/statusline.sh`) renders from a
  cache and never fetches inline — Kimi gives it 300 ms. A refresh it decides
  is due runs detached, at most once per five minutes while the session is
  active.
- The footer shows `dir git:(branch)` plus the quota by default. Kimi's own
  `[status_line] items` list in `tui.toml` picks and orders the slots
  (`mode`, `model`, `cwd`, `git`; `goal`/`tasks`/`tips` are not in the
  snapshot Kimi hands a custom command). If the user wants the mode badge or
  the model name back, tell them to add that key — do not invent a new one.
