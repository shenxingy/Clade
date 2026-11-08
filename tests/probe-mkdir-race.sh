#!/usr/bin/env bash
# Throwaway: how many rounds of 4 concurrent creators have more than one winner?
set -u
ROUNDS=${ROUNDS:-300}
noclobber_create() { ( set -C; : > "$1" ) 2>/dev/null; }
py_mkdir() { python3 -c 'import os, sys; os.mkdir(sys.argv[1])' "$1" 2>/dev/null; }
race() {
  local label=$1 both=0 i k d T
  shift
  T=$(mktemp -d)
  for i in $(seq "$ROUNDS"); do
    d="$T/d$i"
    : > "$T/w$i"
    for k in 1 2 3 4; do ( "$@" "$d" 2>/dev/null && echo w >> "$T/w$i" ) & done
    wait
    [ "$(wc -l < "$T/w$i")" -gt 1 ] && both=$((both + 1))
  done
  rm -rf "$T"
  printf 'RACE %-28s %s of %s rounds had more than one winner\n' "$label" "$both" "$ROUNDS"
}
M=$(readlink -f "$(command -v mkdir)")
printf 'mkdir resolves to %s\n' "$M"
mkdir --version 2>&1 | head -1
dpkg -S "$M" 2>/dev/null || true
dpkg -l 'rust-coreutils' 'coreutils*' 2>/dev/null | awk '/^ii/{print $2, $3}'
ls -l /usr/bin/gnumkdir /usr/lib/cargo/bin/coreutils/mkdir 2>/dev/null || true
T=$(mktemp -d); mkdir "$T/x"; mkdir "$T/x" 2>/dev/null; printf 'sequential mkdir on an existing dir exits %s\n' "$?"; rm -rf "$T"
race 'mkdir (default)' mkdir
[ -x /usr/bin/gnumkdir ] && race 'gnumkdir' /usr/bin/gnumkdir
race 'bash noclobber (O_EXCL)' noclobber_create
race 'python os.mkdir' py_mkdir
