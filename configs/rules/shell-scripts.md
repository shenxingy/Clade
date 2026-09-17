---
paths: configs/hooks/**/*.sh, configs/scripts/**/*.sh, tests/*.sh, install.sh
---
**Shell, measured on this repository — not style preferences.**

- Target **bash 3.2 + BSD userland**. macOS is a shipped platform. Use capability
  detection with a fallback (`command -v X`, `stat -c … || stat -f …`), never
  `uname` branching. macOS has no `timeout`; wrapping a remote command in it there
  fails silently — one audit read a stale cached `origin/main` as a successful pull.
- **`ssh` reads stdin.** In a `while read … done < file` loop, the first `ssh`
  eats the rest of the file and hosts 2..n vanish with no error. Pass `-n`.
- **`$?` after a pipe is the LAST command's.** `cmd | head; echo $?` reports
  `head`. Capture the exit code directly, or use `${PIPESTATUS[0]}`. This mistake
  was made four times in one session, twice producing a wrong report to the owner.
- Per-user scratch goes through `configs/hooks/lib/runtime-dir.sh`, never a fixed
  `/tmp` path — a fixed path is squattable and on a shared host it silently
  disables the feature for every account but the one that created it.
- A script that genuinely needs bash 4 carries the `BASH_VERSINFO` re-exec guard
  from `run-tasks-parallel.sh`.
