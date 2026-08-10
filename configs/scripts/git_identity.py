#!/usr/bin/env python3
"""Pin and verify the human VCS identity used by Clade automation.

Provider logins (Claude, Codex, gateways) are deliberately outside this
boundary.  Automated commits must use the identity explicitly pinned here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "clade.git-identity/v1"
IDENT_RE = re.compile(r"^(.*?) <([^<>]+)> \d+ [+-]\d{4}$")


class IdentityError(RuntimeError):
    pass


def identity_path() -> Path:
    override = os.environ.get("CLADE_GIT_IDENTITY_FILE")
    return Path(override).expanduser() if override else Path.home() / ".clade/git-identity.json"


def validate_field(label: str, value: str) -> str:
    value = value.strip()
    if not value or any(char in value for char in "\r\n\t\0"):
        raise IdentityError(f"{label} must be non-empty and contain no control characters")
    return value


def validate_identity(name: str, email: str) -> dict[str, str]:
    name = validate_field("name", name)
    email = validate_field("email", email)
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise IdentityError("email must look like a Git email address")
    return {"name": name, "email": email}


def git_output(repo: str, *args: str) -> str:
    command = ["git", "-C", repo, *args]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise IdentityError(f"{' '.join(command)}: {detail}")
    return result.stdout.rstrip("\n")


def configured_identity(repo: str) -> dict[str, str]:
    return validate_identity(
        git_output(repo, "config", "--get", "user.name"),
        git_output(repo, "config", "--get", "user.email"),
    )


def effective_identity(repo: str, variable: str) -> dict[str, str]:
    raw = git_output(repo, "var", variable)
    match = IDENT_RE.fullmatch(raw)
    if not match:
        raise IdentityError(f"could not parse {variable}: {raw!r}")
    return validate_identity(match.group(1), match.group(2))


def load_identity() -> dict[str, str]:
    path = identity_path()
    if not path.is_file():
        raise IdentityError(
            f"no pinned Git identity at {path}; pin the human owner explicitly with:\n"
            "  python3 git_identity.py pin --name \"Your Name\" --email \"your-git-email\""
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError(f"cannot read pinned Git identity at {path}: {exc}") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise IdentityError(f"unsupported Git identity schema in {path}")
    return validate_identity(str(payload.get("name", "")), str(payload.get("email", "")))


def write_identity(identity: dict[str, str], force: bool) -> None:
    path = identity_path()
    if path.exists():
        current = load_identity()
        if current == identity:
            print(f"Git identity already pinned: {identity['name']} <{identity['email']}>")
            return
        if not force:
            raise IdentityError(
                f"refusing to replace pinned Git identity at {path}; inspect it first, "
                "then repeat with --force if the human owner really changed"
            )

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "name": identity["name"],
        "email": identity["email"],
        "pinned_at": datetime.now(timezone.utc).isoformat(),
        "source": "explicit-human-vcs-identity",
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Pinned Git identity: {identity['name']} <{identity['email']}> ({path})")


def assert_matches(label: str, actual: dict[str, str], expected: dict[str, str]) -> None:
    if actual != expected:
        raise IdentityError(
            f"Git identity mismatch ({label})\n"
            f"  pinned: {expected['name']} <{expected['email']}>\n"
            f"  actual: {actual['name']} <{actual['email']}>\n"
            "Refusing to commit. Provider login emails must never be used as VCS identity."
        )


def check_identity(repo: str) -> dict[str, str]:
    expected = load_identity()
    assert_matches("git config", configured_identity(repo), expected)
    assert_matches("effective author", effective_identity(repo, "GIT_AUTHOR_IDENT"), expected)
    assert_matches("effective committer", effective_identity(repo, "GIT_COMMITTER_IDENT"), expected)
    return expected


def verify_head(repo: str) -> dict[str, str]:
    expected = load_identity()
    fields = git_output(repo, "log", "-1", "--format=%an%x00%ae%x00%cn%x00%ce").split("\0")
    if len(fields) != 4:
        raise IdentityError("could not parse HEAD author and committer identity")
    author = validate_identity(fields[0], fields[1])
    committer = validate_identity(fields[2], fields[3])
    assert_matches("HEAD author", author, expected)
    assert_matches("HEAD committer", committer, expected)
    return expected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pin = subparsers.add_parser("pin", help="pin the human Git identity")
    pin.add_argument("--name")
    pin.add_argument("--email")
    pin.add_argument("--from-git", action="store_true", help="pin the current configured Git identity")
    pin.add_argument("--repo", default=".")
    pin.add_argument("--force", action="store_true")

    show = subparsers.add_parser("show", help="show the pinned identity")
    show.add_argument("--format", choices=("json", "tsv"), default="json")

    check = subparsers.add_parser("check", help="verify configured and effective Git identity")
    check.add_argument("--repo", default=".")
    check.add_argument("--format", choices=("human", "tsv"), default="human")

    verify = subparsers.add_parser("verify-head", help="verify the actual HEAD attribution")
    verify.add_argument("--repo", default=".")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "pin":
            if args.from_git:
                if args.name or args.email:
                    raise IdentityError("use either --from-git or --name/--email, not both")
                identity = configured_identity(args.repo)
            else:
                if not args.name or not args.email:
                    raise IdentityError("pin requires both --name and --email (or --from-git)")
                identity = validate_identity(args.name, args.email)
            write_identity(identity, args.force)
        elif args.command == "show":
            identity = load_identity()
            if args.format == "tsv":
                print(f"{identity['name']}\t{identity['email']}")
            else:
                print(json.dumps(identity, sort_keys=True))
        elif args.command == "check":
            identity = check_identity(args.repo)
            if args.format == "tsv":
                print(f"{identity['name']}\t{identity['email']}")
            else:
                print(f"Git identity OK: {identity['name']} <{identity['email']}>")
        elif args.command == "verify-head":
            identity = verify_head(args.repo)
            print(f"HEAD identity OK: {identity['name']} <{identity['email']}>")
        return 0
    except IdentityError as exc:
        print(f"git-identity: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
