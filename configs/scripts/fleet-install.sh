#!/usr/bin/env bash
# Bring every machine in your fleet to the current commit and reinstall the kit.
#
# Nothing in this repository deployed Clade anywhere but the box you were sitting
# on. The sync-* scripts look like they might, but they move dotfiles, not the
# checkout, and they knew about two of the hosts. So machines drifted silently:
# an audit on 2026-09-16 found two Linux boxes 269 commits behind, a Mac 519
# commits behind (a checkout from three months earlier), and one host that had
# been advertising itself as reachable on the tailnet while refusing every
# connection. Each of those machines was running a session against a kit its
# owner believed was current.
#
# The host list is NOT in this file. It lives in ~/.claude/fleet.conf, outside
# the repository, because hostnames and home directory paths are yours and this
# repository is public. One "host<space>path" per line; # comments and blanks
# ignored. See fleet.conf.example. Without it this script explains itself and
# exits 0 — a missing fleet is not an error, it is the normal case for anyone
# running Clade on one machine.
#
#   bash configs/scripts/fleet-install.sh            # report state, change nothing
#   bash configs/scripts/fleet-install.sh --apply    # pull --ff-only + ./install.sh
#   bash configs/scripts/fleet-install.sh --self-test
#
# SAFETY, because this runs `rm -rf` per skill directory on every machine it
# touches: a host with a dirty worktree is REPORTED AND SKIPPED, never stashed
# and never forced. A stash on a file that upstream rewrites is how you lose
# work you did not know you had. Bring it up with its owner instead.
#
# bash 3.2 and a BSD userland: no associative arrays, no `timeout` (macOS has
# none, and wrapping a remote command in it there fails silently — that is how
# one audit read a stale cached origin/main as a successful pull).

set -uo pipefail

FLEET_CONF="${CLADE_FLEET_CONF:-$HOME/.claude/fleet.conf}"
# -n is not optional: ssh reads stdin, and the host loop below reads fleet.conf
# FROM stdin. Without it the first ssh swallows every remaining line and the
# script deploys to host 1 and silently reports nothing about hosts 2..n —
# which looks exactly like a one-machine fleet. Caught by the two-host case in
# self_test(), added the same hour the bug appeared.
SSH_OPTS="-n -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10"
SSH_KEY="${CLADE_FLEET_KEY:-$HOME/.ssh/id_ed25519}"
# Injectable so the self-test can substitute a stub that DRAINS STDIN the way a
# real ssh does. A stub that merely fails is not a control here: an unresolvable
# host fails before ssh ever touches stdin, so it cannot reproduce the bug this
# exists to pin, and a self-test built on one passes with `-n` removed.
SSH_BIN="${CLADE_FLEET_SSH:-ssh}"
APPLY=0
SELF_TEST=0

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --self-test) SELF_TEST=1 ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

_ssh() {
  local host="$1"; shift
  # shellcheck disable=SC2086
  "$SSH_BIN" $SSH_OPTS -i "$SSH_KEY" "$host" "$@" 2>&1
}

report_host() {
  local host="$1" path="$2" out state head dirty
  # The fetch is not optional. Without it `HEAD..@{u}` is measured against
  # whatever that machine last fetched, and a host 270 commits behind reports
  # "0 behind" — which is the worst possible output, because it is the one a
  # reader acts on. Observed on all four hosts the first time this ran.
  out=$(_ssh "$host" "cd '$path' 2>/dev/null || { echo NOPATH; exit 0; }
        git fetch --quiet origin 2>/dev/null || echo 'fetchfail=1'
        printf 'head=%s\n' \"\$(git rev-parse --short HEAD 2>/dev/null)\"
        printf 'dirty=%s\n' \"\$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')\"
        printf 'behind=%s\n' \"\$(git rev-list --count HEAD..@{u} 2>/dev/null || echo '?')\"")
  # "Could not resolve hostname" is OpenSSH's own fixed-format prefix; the
  # getaddrinfo error text after the colon is resolver/OS-dependent (glibc
  # says "Name or service not known" for a permanent DNS failure and
  # "Temporary failure in name resolution" for EAI_AGAIN — seen live on a
  # GitHub-hosted runner where the developer machine that wrote this pattern
  # only ever produced the first). Match the prefix, not the suffix.
  if [ -z "$out" ] || printf '%s' "$out" | grep -qiE 'timed out|refused|not known|No route|Permission denied|Could not resolve hostname'; then
    printf '  %-12s UNREACHABLE  (%s)\n' "$host" "$(printf '%s' "$out" | head -1 | cut -c1-60)"
    return 3
  fi
  if printf '%s' "$out" | grep -q NOPATH; then
    printf '  %-12s NO CHECKOUT at %s\n' "$host" "$path"
    return 4
  fi
  head=$(printf '%s' "$out" | sed -n 's/^head=//p')
  dirty=$(printf '%s' "$out" | sed -n 's/^dirty=//p')
  state=$(printf '%s' "$out" | sed -n 's/^behind=//p')
  if [ "${dirty:-0}" != "0" ]; then
    printf '  %-12s DIRTY (%s file(s)) at %s — skipped, needs its owner\n' "$host" "$dirty" "$head"
    return 5
  fi
  if printf '%s' "$out" | grep -q 'fetchfail=1'; then
    printf '  %-12s %s, %s behind — WARNING: fetch failed, that count is against a stale ref\n' \
      "$host" "$head" "${state:-?}"
  else
    printf '  %-12s %s, %s commit(s) behind upstream\n' "$host" "$head" "${state:-?}"
  fi
  return 0
}

apply_host() {
  local host="$1" path="$2"
  printf '  %-12s pulling + installing…\n' "$host"
  _ssh "$host" "set -e
    cd '$path'
    git fetch --quiet origin
    git merge --ff-only origin/\$(git rev-parse --abbrev-ref HEAD) >/dev/null
    ./install.sh >/tmp/clade-install.log 2>&1 || { tail -5 /tmp/clade-install.log; exit 1; }
    src=\$(cat ~/.claude/.kit-source-dir 2>/dev/null)
    . ~/.claude/hooks/lib/kit-checksum.sh 2>/dev/null || true
    if command -v kit_checksum >/dev/null 2>&1 && [ -n \"\$src\" ]; then
      a=\$(kit_checksum \"\$src/configs\"); b=\$(cat ~/.claude/.kit-checksum)
      [ \"\$a\" = \"\$b\" ] && echo VERIFIED || echo 'CHECKSUM MISMATCH after install'
    else
      echo 'INSTALLED (no checksum verification: kit-checksum.sh predates this commit)'
    fi
    echo \"now at \$(git rev-parse --short HEAD)\"" | sed 's/^/    /'
}

self_test() {
  local tmp rc=0 out
  tmp=$(mktemp -d) || return 1
  # A missing fleet file must be a clean no-op, not a crash and not a silent zero.
  out=$(CLADE_FLEET_CONF="$tmp/absent.conf" bash "$0" 2>&1); rc=$?
  if [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -q 'no fleet configured'; then
    echo "SELF-TEST FAILED: a missing fleet.conf must exit 0 and say so (rc=$rc)"; rm -rf "$tmp"; return 1
  fi
  # Comments and blanks must not become hosts.
  printf '# comment\n\n   \nhost-that-does-not-exist /tmp/nope\n' > "$tmp/f.conf"
  out=$(CLADE_FLEET_CONF="$tmp/f.conf" bash "$0" 2>&1)
  if [ "$(printf '%s' "$out" | grep -c 'UNREACHABLE\|NO CHECKOUT')" != "1" ]; then
    echo "SELF-TEST FAILED: expected exactly one host from a file with 1 host + comments"
    printf '%s\n' "$out"; rm -rf "$tmp"; return 1
  fi
  # And an unreachable host must be reported as unreachable, never as up to date.
  if ! printf '%s' "$out" | grep -q 'UNREACHABLE'; then
    echo "SELF-TEST FAILED: an unreachable host was not reported as unreachable"
    rm -rf "$tmp"; return 1
  fi
  # A DNS resolver failure is classified by OpenSSH's own fixed-format prefix
  # ("Could not resolve hostname"), not by the getaddrinfo error text after
  # the colon — that text is resolver/OS-dependent (glibc: "Name or service
  # not known" for a permanent failure, "Temporary failure in name
  # resolution" for EAI_AGAIN). This exact gap let a hosted GitHub Actions
  # runner — whose resolver produced the second string, never seen on the
  # developer machine that wrote the original pattern — silently misreport an
  # unreachable host as "?  commit(s) behind" instead of UNREACHABLE.
  cat > "$tmp/ssh-stub-dns" <<'STUB'
#!/usr/bin/env bash
echo "ssh: Could not resolve hostname stub-host: Temporary failure in name resolution" >&2
exit 255
STUB
  chmod +x "$tmp/ssh-stub-dns"
  printf 'stub-host /tmp/nope\n' > "$tmp/dns.conf"
  out=$(CLADE_FLEET_CONF="$tmp/dns.conf" CLADE_FLEET_SSH="$tmp/ssh-stub-dns" bash "$0" 2>&1)
  if ! printf '%s' "$out" | grep -q 'UNREACHABLE'; then
    echo "SELF-TEST FAILED: 'Temporary failure in name resolution' was not classified UNREACHABLE"
    printf '%s\n' "$out"; rm -rf "$tmp"; return 1
  fi
  # EVERY host must be visited. ssh reads stdin and the host loop reads the
  # fleet file from stdin, so without `ssh -n` host 1 eats the rest of the file
  # and hosts 2..n vanish with no error at all.
  printf 'nope-one /tmp/a\nnope-two /tmp/b\nnope-three /tmp/c\n' > "$tmp/three.conf"
  cat > "$tmp/ssh-stub" <<'STUB'
#!/usr/bin/env bash
# Behaves like ssh in the one way that matters here: it consumes stdin unless
# the caller passed -n. Then it reports the host as having no checkout.
for a in "$@"; do [ "$a" = "-n" ] && { echo NOPATH; exit 0; }; done
cat >/dev/null
echo NOPATH
STUB
  chmod +x "$tmp/ssh-stub"
  out=$(CLADE_FLEET_CONF="$tmp/three.conf" CLADE_FLEET_SSH="$tmp/ssh-stub" bash "$0" 2>&1)
  if [ "$(printf '%s' "$out" | grep -c 'UNREACHABLE\|NO CHECKOUT')" != "3" ]; then
    echo "SELF-TEST FAILED: 3 hosts in, $(printf '%s' "$out" | grep -c 'UNREACHABLE\|NO CHECKOUT') reported — a host was silently dropped"
    printf '%s\n' "$out"; rm -rf "$tmp"; return 1
  fi
  rm -rf "$tmp"
  echo "SELF-TEST PASSED: missing fleet is a clean no-op, comments are not hosts, an unreachable host says so"
  return 0
}

[ "$SELF_TEST" = "1" ] && { self_test; exit $?; }

if [ ! -f "$FLEET_CONF" ]; then
  echo "no fleet configured — $FLEET_CONF does not exist."
  echo "Create it with one 'host path' per line to deploy to more than this machine:"
  echo "  echo 'my-other-box /home/me/projects/Clade' >> $FLEET_CONF"
  echo "See configs/scripts/fleet.conf.example."
  exit 0
fi

echo "fleet: $FLEET_CONF"
[ "$APPLY" = "1" ] || echo "(reporting only — pass --apply to pull and install)"
echo

skipped=0
while read -r host path _rest; do
  case "$host" in ''|\#*) continue ;; esac
  [ -z "${path:-}" ] && { printf '  %-12s MALFORMED LINE (no path)\n' "$host"; continue; }
  if report_host "$host" "$path"; then
    [ "$APPLY" = "1" ] && apply_host "$host" "$path"
  else
    skipped=$((skipped + 1))
  fi
done < "$FLEET_CONF"

echo
if [ "$skipped" -gt 0 ]; then
  echo "$skipped host(s) were skipped. Skipped is not 'up to date' — each one is"
  echo "still running whatever kit it had, and the reason is printed above."
fi
exit 0
