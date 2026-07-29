"""Contract tests for immutable EvidenceBundle v1 snapshots."""

from __future__ import annotations

import copy

import pytest

from evidence_bundle import (
    REDACTION_SCHEMA_VERSION,
    SCHEMA_VERSION,
    EvidenceLifecycle,
    EvidenceValidationError,
    advance_evidence_bundle,
    create_evidence_bundle,
    validate_evidence_chain,
)


EMPTY_REDACTION = {
    "schema_version": REDACTION_SCHEMA_VERSION,
    "count": 0,
    "kinds": {},
    "fields": [],
}


def _initial():
    return create_evidence_bundle(
        task_id="task-1",
        attempt_index=1,
        attempt_id="attempt-1",
        bundle_id="bundle-1",
        recorded_at=100.0,
        evidence={"git": {"base_sha": "abc"}},
        redaction_metadata=EMPTY_REDACTION,
    )


def test_create_bundle_is_versioned_immutable_and_digest_verified():
    bundle = _initial()

    assert bundle.schema_version == SCHEMA_VERSION
    assert bundle.lifecycle_state is EvidenceLifecycle.CREATED
    assert bundle.digest.startswith("sha256:")
    assert bundle.to_dict()["evidence"] == {"git": {"base_sha": "abc"}}
    with pytest.raises(TypeError):
        bundle.evidence["git"] = {}  # type: ignore[index]

    loaded = type(bundle).from_dict(bundle.to_dict())
    assert loaded == bundle


def test_advance_deep_merges_evidence_and_links_digest():
    initial = _initial()
    running = advance_evidence_bundle(
        initial,
        lifecycle_state=EvidenceLifecycle.RUNNING,
        recorded_at=101.0,
        evidence_patch={"git": {"head_sha": "def"}, "timing": {"started_at": 101.0}},
        redaction_metadata=EMPTY_REDACTION,
    )

    assert running.revision == 2
    assert running.previous_digest == initial.digest
    assert running.to_dict()["evidence"]["git"] == {
        "base_sha": "abc",
        "head_sha": "def",
    }
    validate_evidence_chain([initial, running])


def test_same_phase_can_append_evidence_without_mutating_prior_revision():
    initial = _initial()
    running = advance_evidence_bundle(
        initial,
        lifecycle_state="running",
        recorded_at=101.0,
        evidence_patch={"events": {"worker_started": True}},
        redaction_metadata=EMPTY_REDACTION,
    )
    enriched = advance_evidence_bundle(
        running,
        lifecycle_state="running",
        recorded_at=102.0,
        evidence_patch={"events": {"provider_resumed": True}},
        redaction_metadata=EMPTY_REDACTION,
    )

    assert "provider_resumed" not in running.to_dict()["evidence"]["events"]
    assert enriched.to_dict()["evidence"]["events"]["provider_resumed"] is True
    validate_evidence_chain([initial, running, enriched])


def test_invalid_lifecycle_transition_is_rejected():
    with pytest.raises(
        EvidenceValidationError,
        match="created -> delivered",
    ):
        advance_evidence_bundle(
            _initial(),
            lifecycle_state="delivered",
            recorded_at=101.0,
            evidence_patch={},
            redaction_metadata=EMPTY_REDACTION,
        )


def test_digest_tampering_and_chain_reordering_are_rejected():
    initial = _initial()
    running = advance_evidence_bundle(
        initial,
        lifecycle_state="running",
        recorded_at=101.0,
        evidence_patch={"result": "safe"},
        redaction_metadata=EMPTY_REDACTION,
    )
    tampered = copy.deepcopy(running.to_dict())
    tampered["evidence"]["result"] = "changed"

    with pytest.raises(EvidenceValidationError, match="digest mismatch"):
        type(running).from_dict(tampered)
    unsigned = running.to_dict()
    unsigned["digest"] = ""
    with pytest.raises(EvidenceValidationError, match="requires a sha256 digest"):
        type(running).from_dict(unsigned)
    with pytest.raises(EvidenceValidationError, match="start at revision 1"):
        validate_evidence_chain([running])


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"schema_version": "clade.redaction/v0", "count": 0, "kinds": {}, "fields": []},
        {
            "schema_version": REDACTION_SCHEMA_VERSION,
            "count": 2,
            "kinds": {"secret": 1},
            "fields": ["$.secret"],
        },
    ],
)
def test_redaction_metadata_contract_is_strict(metadata):
    with pytest.raises(EvidenceValidationError):
        create_evidence_bundle(
            task_id="task-1",
            attempt_index=1,
            recorded_at=100.0,
            evidence={},
            redaction_metadata=metadata,
        )
