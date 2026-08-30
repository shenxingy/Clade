"""Who may put text into a permission-bypassed worker.

The webhook turns a label or an `/claude …` comment into a queued task, and
`auto_start` spawns that task with `--dangerously-skip-permissions`. Until
2026-08-29 the only check was an optional HMAC signature whose secret defaults
to `""`, at which point the verifier logged a warning and returned True — so
any GitHub user could direct an agent on the operator's machine.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from webhook_trust import (  # noqa: E402
    TRUSTED_ASSOCIATIONS,
    actor_of,
    is_trusted_actor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _comment(login: str, association: str, user_type: str = "User") -> dict:
    return {
        "comment": {
            "body": "/claude do something",
            "user": {"login": login, "type": user_type},
            "author_association": association,
        }
    }


def _issue(login: str, association: str, user_type: str = "User") -> dict:
    return {
        "issue": {
            "title": "t",
            "user": {"login": login, "type": user_type},
            "author_association": association,
        }
    }


class TestActorTrust:
    @pytest.mark.parametrize("association", sorted(TRUSTED_ASSOCIATIONS))
    def test_write_access_associations_are_trusted(self, association, tmp_path):
        ok, reason = is_trusted_actor("issue_comment", _comment("alex", association), tmp_path)
        assert ok, reason

    @pytest.mark.parametrize(
        "association", ["CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE", "MANNEQUIN", ""]
    )
    def test_everyone_else_is_refused(self, association, tmp_path):
        """The whole hole: a stranger commenting `/claude …` on a watched repo."""
        ok, reason = is_trusted_actor("issue_comment", _comment("drive-by", association), tmp_path)
        assert not ok
        assert "drive-by" in reason

    def test_a_vouched_login_is_trusted(self, tmp_path):
        (tmp_path / "TRUSTED_CONTRIBUTORS.txt").write_text("# friends\nfriendly-dev\n")
        ok, reason = is_trusted_actor("issue_comment", _comment("friendly-dev", "NONE"), tmp_path)
        assert ok and "vouched" in reason

    def test_a_missing_trust_file_means_nobody_not_everybody(self, tmp_path):
        """This fails CLOSED where configs/scripts/vouch_check.py fails OPEN.

        That script decides whether to close someone's issue; locking out every
        contributor because a file vanished is the worse error there. Here the
        question is whether to hand someone an agent, and a missing file is not
        consent.
        """
        assert not (tmp_path / "TRUSTED_CONTRIBUTORS.txt").exists()
        ok, _ = is_trusted_actor("issue_comment", _comment("stranger", "NONE"), tmp_path)
        assert not ok

    @pytest.mark.parametrize(
        "login,user_type",
        [("dependabot[bot]", "User"), ("some-app", "Bot"), ("renovate[bot]", "Bot")],
    )
    def test_bots_are_refused_however_they_present(self, login, user_type, tmp_path):
        ok, reason = is_trusted_actor(
            "issue_comment", _comment(login, "COLLABORATOR", user_type), tmp_path
        )
        assert not ok and "bot" in reason.lower()

    def test_a_malformed_payload_is_not_an_authorisation(self, tmp_path):
        for payload in ({}, {"comment": None}, {"comment": {"user": None}}):
            ok, _ = is_trusted_actor("issue_comment", payload, tmp_path)
            assert not ok

    def test_the_issue_author_is_read_for_issue_events(self, tmp_path):
        ok, reason = is_trusted_actor("issues", _issue("alex", "OWNER"), tmp_path)
        assert ok and "alex" in reason

    def test_the_comment_author_is_read_not_the_delivering_sender(self, tmp_path):
        """`sender` is whoever delivered the event, not whoever wrote the text."""
        payload = _comment("stranger", "NONE")
        payload["sender"] = {"login": "alex", "type": "User"}
        ok, _ = is_trusted_actor("issue_comment", payload, tmp_path)
        assert not ok, "the collaborator who delivered it is not the author"


class TestNoDriftFromTheCiGate:
    def test_trusted_associations_match_vouch_check(self):
        """One fact, two surfaces. The rules differ; this set must not.

        Parsed rather than imported: vouch_check.py is a standalone CI script
        by design and lives outside the orchestrator's import path.
        """
        src = (REPO_ROOT / "configs" / "scripts" / "vouch_check.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "TRUSTED_ASSOCIATIONS" for t in node.targets
            ):
                found = ast.literal_eval(node.value)
        assert found is not None, "vouch_check.py no longer defines TRUSTED_ASSOCIATIONS"
        assert set(found) == TRUSTED_ASSOCIATIONS
