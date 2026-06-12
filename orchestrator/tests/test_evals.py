"""Offline tests for the prompt eval harness (orchestrator/evals/).

ONLY offline checks live in pytest: fixture schema, prompt construction,
infra-error simulations (stubbed subprocess), and the supervisor parser
round-trip. Live API replays are manual/scheduled — see evals/README.md.

Loads the eval modules via importlib by file path (evals/ is not a package
and run_oracle_eval itself loads the real worker_review.py the same way,
bypassing the conftest MagicMock).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent / "evals"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_eval_{name}", EVALS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


oe = _load("run_oracle_eval")
se = _load("supervisor_eval")


# ─── Oracle fixture schema ────────────────────────────────────────────────────


def test_oracle_fixtures_validate():
    cases, errors = oe.load_cases()
    assert not errors, "fixture schema errors:\n" + "\n".join(errors)
    assert len(cases) >= 18, f"expected ~20 curated cases, found {len(cases)}"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"


def test_oracle_fixture_category_coverage():
    """Every contract-critical category must keep at least one fixture."""
    cases, _ = oe.load_cases()
    by_cat: dict[str, int] = {}
    for c in cases:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    for required in oe.VALID_CATEGORIES:
        assert by_cat.get(required), f"no fixtures left in category {required!r}"
    # All three infra failure modes stay covered
    sims = {c["simulate"] for c in cases if c.get("simulate")}
    assert sims == oe.VALID_SIMULATIONS
    # Both review paths stay exercised
    assert any(len(c["diff"]) > oe.wr._ORACLE_CHUNK_SIZE for c in cases), "no chunked-path case"
    assert any(
        len(c["diff"]) <= oe.wr._ORACLE_CHUNK_SIZE and not c.get("simulate") for c in cases
    ), "no short-path case"


def test_validate_case_rejects_bad_shapes():
    """Failure paths of the schema validator itself."""
    assert oe.validate_case({"id": "x"}, "x")  # missing fields
    base = {
        "id": "x", "category": "clear-approve", "source": "constructed",
        "task": "t", "diff": "d", "expected_verdict": "approved", "rationale": "r",
    }
    assert not oe.validate_case(dict(base), "x")
    assert oe.validate_case({**base, "expected_verdict": "maybe"}, "x")
    assert oe.validate_case({**base, "category": "nonsense"}, "x")
    assert oe.validate_case({**base, "simulate": "timeout"}, "x")  # sim must expect unreviewed
    assert oe.validate_case({**base, "expected_verdict": "unreviewed"}, "x")  # needs simulate
    assert oe.validate_case({**base, "acceptance_criteria": ["ok", ""]}, "x")
    assert oe.validate_case({**base, "test_evidence": {"tests_passed": "yes"}}, "x")


# ─── Prompt construction ──────────────────────────────────────────────────────


def test_prompt_construction_all_cases():
    cases, _ = oe.load_cases()
    problems: list[str] = []
    for case in cases:
        problems.extend(oe.check_prompts(case))
    assert not problems, "prompt construction problems:\n" + "\n".join(problems)


def test_fix_intent_criterion_threading():
    cases, _ = oe.load_cases()
    by_id = {c["id"]: c for c in cases}
    fix_case = by_id["reject-fix-without-test"]
    assert oe.wr._detect_fix_intent(fix_case["task"])
    joined = "\n".join(oe.build_prompts(fix_case).values())
    assert "Additional completeness criterion" in joined
    # evidence present → infra is reported as known, not unknown
    assert "Test infrastructure present in this project: yes" in joined

    unknown_case = by_id["approve-real-skill-fix-unknown-infra"]
    assert not unknown_case.get("test_evidence")
    joined = "\n".join(oe.build_prompts(unknown_case).values())
    assert "Test infrastructure present in this project: unknown" in joined

    plain = by_id["approve-feature-with-tests"]
    assert not oe.wr._detect_fix_intent(plain["task"])
    assert "Additional completeness criterion" not in "\n".join(oe.build_prompts(plain).values())


def test_evidence_threading_into_both_passes():
    cases, _ = oe.load_cases()
    case = next(c for c in cases if c["id"] == "reject-failing-tests-evidence")
    prompts = oe.build_prompts(case)
    assert set(prompts) == {"spec", "quality"}
    for prompt in prompts.values():
        assert "Test results (run before this review):" in prompt
        assert "Project tests FAILED." in prompt


def test_acceptance_criteria_threading():
    cases, _ = oe.load_cases()
    case = next(c for c in cases if c["id"] == "reject-criterion-violated")
    joined = "\n".join(oe.build_prompts(case).values())
    assert "Acceptance criteria (give a verdict for EACH):" in joined
    for criterion in case["acceptance_criteria"]:
        assert criterion in joined


def test_chunked_path_prompt_routing():
    cases, _ = oe.load_cases()
    case = next(c for c in cases if c["id"] == "approve-chunked-large-refactor")
    prompts = oe.build_prompts(case)
    assert len(prompts) == 3, "live path reviews at most the first 3 chunks"
    assert all(k.startswith("chunk-") for k in prompts)
    for label, prompt in prompts.items():
        assert prompt.startswith(f"[Reviewing chunk: {label.removeprefix('chunk-')}]")
        # severity gate contract text must be present on the chunked path
        assert "decision MUST be 'APPROVED' unless at least one finding has severity 'error'" in prompt


# ─── Infra simulations (real _oracle_review, stubbed subprocess) ──────────────


async def test_infra_simulations_yield_unreviewed(tmp_path):
    cases, _ = oe.load_cases()
    sim_cases = [c for c in cases if c.get("simulate")]
    assert len(sim_cases) == 3
    for case in sim_cases:
        case_dir = tmp_path / case["id"]
        case_dir.mkdir()
        verdict, reason = await oe.run_simulated_case(case, case_dir)
        assert verdict == "unreviewed", f"{case['id']}: got {verdict} ({reason})"


async def test_simulation_restores_asyncio_module(tmp_path):
    """The sim swaps wr.asyncio and MUST restore it (live cases run after sims)."""
    import asyncio as real_asyncio

    cases, _ = oe.load_cases()
    case = next(c for c in cases if c.get("simulate"))
    before = oe.wr.asyncio
    await oe.run_simulated_case(case, tmp_path)
    assert oe.wr.asyncio is before is real_asyncio


# ─── summarize / threshold gate ───────────────────────────────────────────────


def test_summarize_threshold_gate():
    results = [
        {"got": "approved", "expected": "approved"},
        {"got": "rejected", "expected": "rejected"},
        {"got": "approved", "expected": "rejected"},
        {"got": "unreviewed", "expected": "unreviewed"},
    ]
    rate, ok = oe.summarize(results, threshold=0.75)
    assert rate == 0.75 and ok
    rate, ok = oe.summarize(results, threshold=0.80)
    assert not ok
    assert oe.summarize([], threshold=0.0) == (0.0, False)


def test_offline_mode_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(EVALS_DIR / "run_oracle_eval.py"), "--offline"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ─── Supervisor parser round-trip ─────────────────────────────────────────────


def test_supervisor_parser_extraction_tracks_live_script():
    snippet = se.extract_parser_snippet()
    assert "json.loads" in snippet and "re.findall" in snippet
    # Fidelity guard: bash double-quote processing must not rewrite the snippet.
    # If someone adds $vars/backticks/escapes to the embedded parser, raw
    # extraction stops being equivalent to what the shell executes — fail loud.
    for forbidden in ("$", "`", '\\"', "\\\\"):
        assert forbidden not in snippet, (
            f"embedded parser now contains {forbidden!r} — bash would rewrite it; "
            "update supervisor_eval.extract_parser_snippet to shell-decode first"
        )


def test_supervisor_fixtures_validate():
    cases, errors = se.load_cases()
    assert not errors, "\n".join(errors)
    assert len(cases) >= 6


def test_supervisor_cases_roundtrip():
    cases, _ = se.load_cases()
    snippet = se.extract_parser_snippet()
    failures: list[str] = []
    for case in cases:
        failures.extend(se.run_case(case, snippet))
    assert not failures, "\n".join(failures)


def test_supervisor_structural_check_units():
    assert se.structural_check({"description": "x"}) == ["not_a_list"]
    assert se.structural_check([]) == []
    good = [{"description": "do x", "model": "haiku", "files": ["a.py"]}]
    assert se.structural_check(good) == []
    bad = [
        {"description": " ", "model": "gpt-4o", "files": []},
        "not-a-task",
        {"description": "y", "model": "opus", "files": ["b.py", "b.py"]},
    ]
    assert se.structural_check(bad) == [
        "bad_model", "file_overlap", "missing_description", "missing_files", "task_not_object",
    ]


def test_supervisor_eval_main_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(EVALS_DIR / "supervisor_eval.py")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
