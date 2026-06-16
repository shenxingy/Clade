"""Mutation-testing patrol lane (lovesegfault mutants.toml pattern, Python/mutmut).

Coverage says a line RAN during tests; mutation testing says a test would CATCH a
bug — it makes tiny code changes ("mutants") and checks the suite fails. A mutant
that SURVIVES = a test executed the code but never asserted the behavior (a hollow
test). This is the gap coverage can't see, and the real risk for agent-written
tests.

Run-over-run **ratchet**: the first run seeds a survivor baseline and creates NO
tasks (it would otherwise flood with the whole existing debt). Subsequent runs
create tasks only for NEWLY-surviving mutants — a regression in test quality —
mirroring the facts.json / coverage ratchets. Scoped to high-signal modules
(mutmut runs the whole suite once per mutant — expensive — so this is a patrol
lane, never a commit gate).

mutmut is an OPTIONAL dependency: absent → the lane logs an install hint and
no-ops, exactly like the browser-verify Playwright wiring.
"""

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Mutation targets are inherently project-specific (you mutate a few high-signal
# modules, not the whole tree) — there is no sane universal default, so this is
# empty and the lane no-ops until `mutation_targets` is configured in settings.
# Example for Clade's own repo: ["orchestrator/worker_review.py",
# "orchestrator/error_classifier.py"].
_MUTATION_TARGETS: list[str] = []

_MAX_TASKS_PER_RUN = 10  # never flood the queue from one scan

# `mutmut results` groups survivors under file headers, e.g.:
#   ---- worker_review.py (3) ----
#   12-14, 27
_MUT_FILE_RE = re.compile(r'^-+\s*(?P<file>\S+\.py)\s*\(\d+\)\s*-+\s*$')
_MUT_IDS_RE = re.compile(r'^[\d,\s\-]+$')
# Section headers in `mutmut results`; survivors live under "Survived".
_SURVIVED_HDR = re.compile(r'^survived\b', re.IGNORECASE)
_OTHER_HDR = re.compile(r'^(killed|timeout|suspicious|skipped|no tests|untested)\b', re.IGNORECASE)


def _parse_mutmut_survivors(text: str) -> set[str]:
    """Extract surviving-mutant keys ('file.py:id') from `mutmut results` text.

    Only the 'Survived' section is read; ranges like '12-14' expand to one key
    per id. Pure + deterministic — the durable, testable core (the mutmut subprocess
    format may drift across versions; this is the one place a fix would land)."""
    survivors: set[str] = set()
    cur_file: str | None = None
    in_survived = False
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if _SURVIVED_HDR.match(s):
            in_survived = True
            cur_file = None
            continue
        if _OTHER_HDR.match(s):
            in_survived = False
            cur_file = None
            continue
        m = _MUT_FILE_RE.match(s)
        if m:
            cur_file = m.group("file")
            continue
        if in_survived and cur_file and _MUT_IDS_RE.match(s):
            for tok in re.split(r'[,\s]+', s):
                tok = tok.strip()
                if not tok:
                    continue
                if "-" in tok:
                    a, _, b = tok.partition("-")
                    if a.isdigit() and b.isdigit():
                        for i in range(int(a), int(b) + 1):
                            survivors.add(f"{cur_file}:{i}")
                elif tok.isdigit():
                    survivors.add(f"{cur_file}:{tok}")
    return survivors


def _ratchet_new_survivors(current: set[str], baseline_path: Path) -> set[str]:
    """Ratchet: return survivors that are NEW vs the stored baseline, then rewrite
    the baseline to `current` (so killed mutants drop out and persistent ones don't
    re-fire). The FIRST run (no baseline file) seeds the floor and returns empty —
    existing debt is recorded, not dumped into the queue."""
    existed = baseline_path.exists()
    prev: set[str] = set()
    if existed:
        try:
            prev = set(json.loads(baseline_path.read_text()).get("survivors", []))
        except Exception as e:
            logger.warning("mutation_scan: corrupt baseline %s, treating as empty: %s",
                           baseline_path, e)
            prev = set()
    try:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps({"survivors": sorted(current)}))
    except Exception as e:
        logger.warning("mutation_scan: could not write baseline: %s", e)
    return (current - prev) if existed else set()


async def check_mutation_survivors(
    task_queue: Any, project_dir: str, targets: list[str] | None = None,
    claude_dir: str | None = None,
) -> list[str]:
    """Run mutmut on scoped targets, ratchet survivors, create a test task per NEW
    survivor. Returns created task ids. No-op (returns []) when mutmut is absent or
    nothing newly survives — never raises into the patrol loop."""
    created: list[str] = []
    targets = targets or _MUTATION_TARGETS
    project = Path(project_dir)

    if shutil.which("mutmut") is None:
        logger.info("mutation_scan: mutmut not installed (pip install mutmut) — skipping")
        return created

    if not targets:
        logger.info("mutation_scan: no mutation_targets configured — skipping")
        return created

    paths = ",".join(t for t in targets if (project / t).exists())
    if not paths:
        logger.info("mutation_scan: configured targets not found under %s — skipping", project)
        return created

    try:
        run = await asyncio.create_subprocess_exec(
            "mutmut", "run", "--paths-to-mutate", paths,
            cwd=project_dir,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(run.communicate(), timeout=1800)  # 30-min cap
        except asyncio.TimeoutError:
            run.kill()
            await run.communicate()
            logger.warning("mutation_scan: mutmut run timed out (30m) — skipping")
            return created
    except Exception as e:
        logger.warning("mutation_scan: mutmut run failed: %s", e)
        return created

    try:
        res = await asyncio.create_subprocess_exec(
            "mutmut", "results",
            cwd=project_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(res.communicate(), timeout=60)
        except asyncio.TimeoutError:
            res.kill()
            await res.communicate()  # reap + close the stdout pipe
            logger.warning("mutation_scan: mutmut results timed out — skipping")
            return created
    except Exception as e:
        logger.warning("mutation_scan: mutmut results failed: %s", e)
        return created

    current = _parse_mutmut_survivors(out.decode("utf-8", errors="replace"))
    cdir = Path(claude_dir) if claude_dir else project / ".claude"
    new_survivors = _ratchet_new_survivors(current, cdir / "mutation-baseline.json")
    if not new_survivors:
        logger.info("mutation_scan: %d survivor(s), 0 new vs baseline", len(current))
        return created

    try:
        existing = {t.get("source_ref") for t in await task_queue.list() if t.get("source_ref")}
    except Exception:
        existing = set()

    for key in sorted(new_survivors)[:_MAX_TASKS_PER_RUN]:
        source_ref = "mutation_" + key.replace("/", "_").replace(":", "_")
        if source_ref in existing:
            continue
        mutant_id = key.rsplit(":", 1)[-1]
        description = (
            f"Mutation survived: {key} — a test executes this code but does not "
            f"assert the mutated behavior (hollow-test gap). Strengthen the assertion "
            f"so the mutant is killed; inspect the exact change with "
            f"`mutmut show {mutant_id}`."
        )
        try:
            task = await task_queue.add(
                description=description, source_ref=source_ref, task_type="test"
            )
            created.append(task["id"])
            logger.info("mutation_scan: created task %s for survivor %s", task["id"], key)
        except Exception as e:
            logger.warning("mutation_scan: failed to create task for %s: %s", key, e)

    return created
