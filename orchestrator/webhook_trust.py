"""Who is allowed to put text into a permission-bypassed worker.

`routes/webhooks.py` turns a GitHub issue label or an `/claude …` comment into
a queued task, and `auto_start` (default on) spawns that task as a worker with
`--dangerously-skip-permissions`. Until 2026-08-29 the only check was an
optional HMAC signature, and `webhook_secret` defaults to `""`, at which point
the verifier logged a warning and returned True.

So: any GitHub user could comment `/claude <anything>` on a watched repo and
have that text reach an agent that edits the operator's machine. On a host with
Tailscale the server binds 0.0.0.0 (`orchestrator/start.sh:98`), so the endpoint
is not even loopback-only.

Two rules, both from the payload — no API call, so this cannot fail open on a
network error:

  1. the sender must not be a bot
  2. the actor must hold repo write access, or be explicitly vouched for

**This fails CLOSED and `configs/scripts/vouch_check.py` fails OPEN, on
purpose.** That script decides whether to close someone's issue: locking out
every contributor because a trust file vanished is the worse error there. Here
the question is whether to hand someone an agent, and a missing trust file is
not consent. The two share `TRUSTED_ASSOCIATIONS` — the GitHub associations
that already imply write access — and `tests/test_webhook_trust.py` asserts
they have not drifted apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# GitHub author_association values that imply repo write access. Kept identical
# to configs/scripts/vouch_check.py:TRUSTED_ASSOCIATIONS; the test pins that.
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}

#: Repo-root file listing usernames vouched for by the operator, one per line.
TRUSTED_CONTRIBUTORS_FILE = "TRUSTED_CONTRIBUTORS.txt"


def _vouched_logins(project_dir: Path | str | None) -> set[str]:
    """Explicitly vouched usernames. A missing file means nobody — not everybody."""
    if not project_dir:
        return set()
    try:
        text = (Path(project_dir) / TRUSTED_CONTRIBUTORS_FILE).read_text(encoding="utf-8")
    except OSError:
        return set()
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def actor_of(event: str, payload: dict) -> tuple[str, str, bool]:
    """(login, author_association, is_bot) for the person who caused this event.

    Read from the object that carries the instruction — the comment for
    `issue_comment`, the issue itself otherwise — because `sender` is whoever
    delivered the event, which is not always whoever wrote the text. A label
    added by a collaborator to someone else's issue is the collaborator's act.
    """
    if event == "issue_comment":
        source = payload.get("comment") or {}
    else:
        source = payload.get("issue") or {}
    user = source.get("user") or payload.get("sender") or {}
    login = str(user.get("login") or "")
    association = str(source.get("author_association") or "")
    is_bot = str(user.get("type") or "") == "Bot" or login.endswith("[bot]")
    return login, association, is_bot


def is_trusted_actor(
    event: str, payload: dict, project_dir: Path | str | None = None
) -> tuple[bool, str]:
    """Whether this event may queue work. Fails closed; never raises."""
    try:
        login, association, is_bot = actor_of(event, payload)
    except Exception:  # a malformed payload is not an authorisation
        return False, "unreadable actor"

    if is_bot:
        return False, f"sender is a bot ({login or 'unknown'})"
    if not login:
        return False, "no actor on the payload"
    if association in TRUSTED_ASSOCIATIONS:
        return True, f"{login}: {association}"
    if login in _vouched_logins(project_dir):
        return True, f"{login}: vouched in {TRUSTED_CONTRIBUTORS_FILE}"
    return False, f"{login}: {association or 'no association'}, not vouched"


def describe(decision: tuple[bool, str]) -> dict[str, Any]:
    """Log/response shape — the reason, never the payload."""
    trusted, reason = decision
    return {"trusted": trusted, "reason": reason}
