#!/usr/bin/env python3
"""Oracle prompt eval harness — replays recorded fixtures through the LIVE
``_oracle_review`` path in ``worker_review.py``.

Why: Clade's stated quality metric is "90%+ oracle-approved success", yet an
oracle prompt edit cannot be shown to move that number before deployment.
This harness makes prompt changes regression-testable: ~20 curated fixture
cases (task + diff + expected verdict) replay through the exact code path the
worker pool uses, and the run fails when the pass-rate drops below threshold.

Modes
-----
  live (default)   each case calls ``claude -p`` (haiku) via the real
                   ``_oracle_review``. Manual / scheduled only — never CI.
  --offline        no API calls: fixture schema validation, prompt
                   construction checks (criteria/evidence/fix-intent
                   threading, no unrendered placeholders), and infra-error
                   simulations replayed through the real ``_oracle_review``
                   with a stubbed subprocess layer.

Fixture schema — see README.md in this directory.

Exit codes: 0 = pass, 1 = pass-rate below threshold (live) or offline check
failed, 2 = fixture schema invalid / unusable.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_DIR = EVALS_DIR.parent
ORACLE_CASES_DIR = EVALS_DIR / "oracle_cases"

VALID_VERDICTS = {"approved", "rejected", "unreviewed"}
VALID_SIMULATIONS = {"timeout", "garbage_output", "empty_output"}
VALID_CATEGORIES = {
    "clear-approve",
    "style-nit-no-reject",
    "reject-spec-violation",
    "reject-missing-test-on-fix",
    "reject-quality",
    "infra-error",
}
REQUIRED_FIELDS = {"id", "category", "source", "task", "diff", "expected_verdict", "rationale"}

# Default live pass-rate gate. Ratchet upward as prompts improve — never down
# without a README note explaining which fixture became a known-miss and why.
DEFAULT_THRESHOLD = 0.75


def _load_worker_review():
    """Load the REAL worker_review.py by file path.

    Bypasses any sys.modules mock (tests/conftest.py replaces worker_review
    with a MagicMock) — the whole point of this harness is to exercise the
    live module, not a test double. worker_review is a documented leaf
    (stdlib-only imports), so this load is side-effect free.
    """
    spec = importlib.util.spec_from_file_location(
        "_eval_worker_review", ORCHESTRATOR_DIR / "worker_review.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


wr = _load_worker_review()


# ─── Fixture loading & schema validation ─────────────────────────────────────


def validate_case(case: dict, source_name: str = "?") -> list[str]:
    """Return a list of schema errors for one fixture case (empty = valid)."""
    errors: list[str] = []
    if not isinstance(case, dict):
        return [f"{source_name}: case is not a JSON object"]
    cid = case.get("id", source_name)
    missing = REQUIRED_FIELDS - set(case)
    if missing:
        errors.append(f"{cid}: missing required fields: {sorted(missing)}")
    if case.get("expected_verdict") not in VALID_VERDICTS:
        errors.append(f"{cid}: expected_verdict must be one of {sorted(VALID_VERDICTS)}")
    if case.get("category") not in VALID_CATEGORIES:
        errors.append(f"{cid}: category must be one of {sorted(VALID_CATEGORIES)}")
    for field in ("id", "task", "diff", "rationale", "source"):
        if field in case and (not isinstance(case[field], str) or not case[field].strip()):
            errors.append(f"{cid}: {field} must be a non-empty string")
    sim = case.get("simulate")
    if sim is not None and sim not in VALID_SIMULATIONS:
        errors.append(f"{cid}: simulate must be one of {sorted(VALID_SIMULATIONS)}")
    # Infra simulation and verdict must agree both ways: a simulated case can
    # only ever produce 'unreviewed', and 'unreviewed' is only reachable by
    # simulation (a live haiku call never returns an infra error on demand).
    if sim and case.get("expected_verdict") != "unreviewed":
        errors.append(f"{cid}: simulate cases must expect 'unreviewed'")
    if case.get("expected_verdict") == "unreviewed" and not sim:
        errors.append(f"{cid}: expected 'unreviewed' requires a simulate field")
    crit = case.get("acceptance_criteria")
    if crit is not None and (
        not isinstance(crit, list) or not all(isinstance(c, str) and c.strip() for c in crit)
    ):
        errors.append(f"{cid}: acceptance_criteria must be a list of non-empty strings")
    te = case.get("test_evidence")
    if te is not None:
        if not isinstance(te, dict) or not isinstance(te.get("tests_passed"), bool):
            errors.append(f"{cid}: test_evidence must be an object with bool tests_passed")
        else:
            for k in ("test_output", "reg_warning"):
                if not isinstance(te.get(k, ""), str):
                    errors.append(f"{cid}: test_evidence.{k} must be a string")
    return errors


def load_cases(cases_dir: Path = ORACLE_CASES_DIR) -> tuple[list[dict], list[str]]:
    """Load all fixture cases. Returns (cases, errors)."""
    cases: list[dict] = []
    errors: list[str] = []
    paths = sorted(cases_dir.glob("*.json"))
    if not paths:
        return [], [f"no fixture cases found in {cases_dir}"]
    seen_ids: set[str] = set()
    for path in paths:
        try:
            case = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"{path.name}: unreadable JSON ({e})")
            continue
        errors.extend(validate_case(case, path.name))
        cid = case.get("id") if isinstance(case, dict) else None
        if cid:
            if cid != path.stem:
                errors.append(f"{path.name}: id {cid!r} != filename stem {path.stem!r}")
            if cid in seen_ids:
                errors.append(f"{path.name}: duplicate id {cid!r}")
            seen_ids.add(cid)
        if isinstance(case, dict):
            cases.append(case)
    return cases, errors


# ─── Prompt construction (offline-checkable) ──────────────────────────────────


def build_evidence(case: dict) -> str:
    """Build the test-evidence block exactly like worker.py does pre-gate."""
    te = case.get("test_evidence")
    if not te:
        return ""
    return wr._build_test_evidence(
        bool(te.get("tests_passed", True)),
        str(te.get("test_output", "")),
        str(te.get("reg_warning", "")),
    )


def build_prompts(case: dict) -> dict[str, str]:
    """Construct every prompt the live ``_oracle_review`` would send for a case.

    Mirrors the live routing: diffs over ``_ORACLE_CHUNK_SIZE`` go through the
    chunked single-prompt path (first 3 chunks), short diffs through the
    two-pass spec+quality path.
    """
    evidence = build_evidence(case)
    task_block = wr._build_oracle_task_block(
        case["task"], case.get("acceptance_criteria"), evidence
    )
    diff = case["diff"]
    prompts: dict[str, str] = {}
    if len(diff) > wr._ORACLE_CHUNK_SIZE:
        chunks = [
            diff[i : i + wr._ORACLE_CHUNK_SIZE]
            for i in range(0, len(diff), wr._ORACLE_CHUNK_SIZE)
        ][:3]
        for i, chunk in enumerate(chunks):
            label = f"{i + 1}/{len(chunks)}"
            prompt = wr._ORACLE_PROMPT_TEMPLATE.format(
                task=task_block[: wr._ORACLE_TASK_DESC_CAP + 2500], diff=chunk
            )
            prompts[f"chunk-{label}"] = f"[Reviewing chunk: {label}]\n\n" + prompt
    else:
        excerpt = diff[: wr._ORACLE_CHUNK_SIZE]
        prompts["spec"] = wr._ORACLE_SPEC_PROMPT.format(task=task_block, diff=excerpt)
        evidence_block = (
            f"Test results (run before this review):\n{evidence[:800]}\n\n"
            if evidence
            else ""
        )
        prompts["quality"] = wr._ORACLE_QUALITY_PROMPT.format(
            diff=excerpt, evidence=evidence_block
        )
    return prompts


def check_prompts(case: dict) -> list[str]:
    """Offline assertions on prompt construction for one case. Empty = OK."""
    problems: list[str] = []
    cid = case.get("id", "?")
    try:
        prompts = build_prompts(case)
    except (KeyError, IndexError, ValueError) as e:
        return [f"{cid}: prompt construction raised {type(e).__name__}: {e}"]
    joined = "\n\n".join(prompts.values())
    task_head = case["task"].splitlines()[0][:80]
    if task_head not in joined:
        problems.append(f"{cid}: task description head missing from prompts")
    for criterion in (case.get("acceptance_criteria") or [])[:10]:
        if criterion[:80] not in joined:
            problems.append(f"{cid}: acceptance criterion not threaded: {criterion[:60]!r}")
    fix_intent = wr._detect_fix_intent(case["task"])
    has_fix_criterion = "Additional completeness criterion" in joined
    if fix_intent and not has_fix_criterion:
        problems.append(f"{cid}: fix-intent task but covering-test criterion missing")
    if not fix_intent and has_fix_criterion:
        problems.append(f"{cid}: non-fix task got the covering-test criterion")
    evidence = build_evidence(case)
    if evidence and "Test results (run before this review):" not in joined:
        problems.append(f"{cid}: test evidence not threaded into prompts")
    for placeholder in ("{task}", "{diff}", "{evidence}", "{infra}"):
        if placeholder in joined:
            problems.append(f"{cid}: unrendered placeholder {placeholder} in prompt")
    return problems


# ─── Infra-error simulation (no API calls) ────────────────────────────────────


class _FakeProc:
    """Stand-in for an asyncio subprocess (same shape as test_oracle_integrity)."""

    def __init__(self, stdout: bytes = b""):
        self._stdout = stdout
        self.returncode = 0

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        pass


class _AsyncioProxy:
    """asyncio stand-in: overridden names hit stubs, everything else passes through."""

    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(asyncio, name)


async def run_simulated_case(case: dict, claude_dir: Path) -> tuple[str, str]:
    """Replay an infra-simulation fixture through the REAL ``_oracle_review``
    with a stubbed subprocess layer. Returns (verdict, reason). No API calls —
    these run identically in live and offline modes."""
    sim = case["simulate"]
    overrides: dict = {}
    if sim == "timeout":

        async def _fake_shell(*args, **kwargs):
            return _FakeProc(b"")

        async def _raising_wait_for(coro, timeout=None):
            coro.close()  # avoid "never awaited" warnings
            raise asyncio.TimeoutError

        overrides = {
            "create_subprocess_shell": _fake_shell,
            "wait_for": _raising_wait_for,
        }
    else:
        stdout = b"" if sim == "empty_output" else b"Error: 429 rate limited, retry later"

        async def _fake_shell(*args, **kwargs):
            return _FakeProc(stdout)

        overrides = {"create_subprocess_shell": _fake_shell}

    original = wr.asyncio
    wr.asyncio = _AsyncioProxy(**overrides)
    try:
        evidence = build_evidence(case)
        approved, reason, infra_error = await wr._oracle_review(
            case["task"],
            case["diff"],
            claude_dir,
            acceptance_criteria=case.get("acceptance_criteria") or None,
            test_evidence=evidence,
        )
    finally:
        wr.asyncio = original
    if infra_error:
        return "unreviewed", reason
    return ("approved" if approved else "rejected"), reason


# ─── Live replay ──────────────────────────────────────────────────────────────


class _CountingAsyncio:
    """Pass-through asyncio proxy that counts claude subprocess invocations."""

    def __init__(self, counter: dict):
        self._counter = counter

    def __getattr__(self, name):
        if name == "create_subprocess_shell":
            counter = self._counter

            async def _counted(*args, **kwargs):
                counter["calls"] += 1
                return await asyncio.create_subprocess_shell(*args, **kwargs)

            return _counted
        return getattr(asyncio, name)


async def run_live_case(case: dict, claude_dir: Path) -> tuple[str, str]:
    """Replay one fixture through the real ``_oracle_review`` (real claude CLI)."""
    evidence = build_evidence(case)
    approved, reason, infra_error = await wr._oracle_review(
        case["task"],
        case["diff"],
        claude_dir,
        acceptance_criteria=case.get("acceptance_criteria") or None,
        test_evidence=evidence,
    )
    if infra_error:
        return "unreviewed", reason
    return ("approved" if approved else "rejected"), reason


def summarize(results: list[dict], threshold: float) -> tuple[float, bool]:
    """Compute (pass_rate, ok) from per-case results."""
    if not results:
        return 0.0, False
    hits = sum(1 for r in results if r["got"] == r["expected"])
    rate = hits / len(results)
    return rate, rate >= threshold


async def _run_live(cases: list[dict], concurrency: int, model: str | None) -> list[dict]:
    """Run all cases: simulations first (they swap module state, so run them
    sequentially before any live concurrency), then live cases under a
    semaphore."""
    if model:
        wr.HAIKU_MODEL = model
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="oracle-eval-") as tmp:
        tmp_path = Path(tmp)
        sim_cases = [c for c in cases if c.get("simulate")]
        live_cases = [c for c in cases if not c.get("simulate")]
        for case in sim_cases:
            case_dir = tmp_path / case["id"]
            case_dir.mkdir()
            verdict, reason = await run_simulated_case(case, case_dir)
            results.append(
                {"id": case["id"], "expected": case["expected_verdict"],
                 "got": verdict, "reason": reason, "live": False}
            )

        counter = {"calls": 0}
        original = wr.asyncio
        wr.asyncio = _CountingAsyncio(counter)
        sem = asyncio.Semaphore(max(1, concurrency))

        async def _one(case: dict) -> dict:
            async with sem:
                case_dir = tmp_path / case["id"]
                case_dir.mkdir()
                verdict, reason = await run_live_case(case, case_dir)
                return {"id": case["id"], "expected": case["expected_verdict"],
                        "got": verdict, "reason": reason, "live": True}

        try:
            results.extend(await asyncio.gather(*[_one(c) for c in live_cases]))
        finally:
            wr.asyncio = original
        results.sort(key=lambda r: r["id"])
        for r in results:
            r.setdefault("calls", None)
        results.append({"_meta": True, "claude_calls": counter["calls"]})
    return results


# ─── CLI ──────────────────────────────────────────────────────────────────────


def run_offline(cases: list[dict]) -> int:
    """Offline validation: prompt construction + infra simulations. Returns exit code."""
    problems: list[str] = []
    for case in cases:
        problems.extend(check_prompts(case))

    async def _sims() -> None:
        with tempfile.TemporaryDirectory(prefix="oracle-eval-sim-") as tmp:
            for case in cases:
                if not case.get("simulate"):
                    continue
                case_dir = Path(tmp) / case["id"]
                case_dir.mkdir()
                verdict, reason = await run_simulated_case(case, case_dir)
                if verdict != case["expected_verdict"]:
                    problems.append(
                        f"{case['id']}: simulation produced {verdict!r}, "
                        f"expected {case['expected_verdict']!r} ({reason})"
                    )

    asyncio.run(_sims())
    n_sim = sum(1 for c in cases if c.get("simulate"))
    print(f"offline: {len(cases)} cases — prompt construction checked, "
          f"{n_sim} infra simulations replayed")
    if problems:
        print(f"\nOFFLINE FAILURES ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("offline: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true",
                        help="validate fixtures + prompt construction, no API calls")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"live pass-rate gate (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--cases", default="",
                        help="only run cases whose id contains this substring")
    parser.add_argument("--model", default="",
                        help="override grader model (default: worker_review.HAIKU_MODEL)")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="parallel live cases (default 4)")
    parser.add_argument("--cases-dir", default=str(ORACLE_CASES_DIR))
    args = parser.parse_args(argv)

    cases, errors = load_cases(Path(args.cases_dir))
    if errors:
        print(f"FIXTURE SCHEMA ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
        return 2
    if args.cases:
        cases = [c for c in cases if args.cases in c["id"]]
        if not cases:
            print(f"no cases match filter {args.cases!r}")
            return 2
    print(f"loaded {len(cases)} fixture cases from {args.cases_dir}")

    if args.offline:
        return run_offline(cases)

    # Live mode — real claude -p calls. Manual/scheduled only (see README).
    started = time.monotonic()
    raw = asyncio.run(_run_live(cases, args.concurrency, args.model or None))
    elapsed = time.monotonic() - started
    meta = next((r for r in raw if r.get("_meta")), {})
    results = [r for r in raw if not r.get("_meta")]

    print(f"\n{'case':<42} {'expected':<11} {'got':<11} result")
    print("-" * 84)
    for r in results:
        mark = "ok  " if r["got"] == r["expected"] else "MISS"
        print(f"{r['id']:<42} {r['expected']:<11} {r['got']:<11} {mark}  {r['reason'][:60]}")
    rate, ok = summarize(results, args.threshold)
    hits = sum(1 for r in results if r["got"] == r["expected"])
    print("-" * 84)
    print(f"pass-rate: {hits}/{len(results)} = {rate:.0%} "
          f"(threshold {args.threshold:.0%}) — "
          f"{meta.get('claude_calls', '?')} claude calls, {elapsed:.0f}s wall")
    if not ok:
        print("BELOW THRESHOLD — oracle prompt contract has regressed "
              "(or a fixture needs recalibration; see README).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
