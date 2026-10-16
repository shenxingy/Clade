#!/usr/bin/env python3
"""Calibrate two historical terminal verifiers; no model or network calls.

Run from a Clade checkout with history:
  python3 docs/artifacts/learning-radar-20260930/preflight.py --output /tmp/clade-preflight

Each lane uses the FIXED snapshot and identical fixed tests. In the red lane
only the task-owned implementation file is restored from the parent. This
measures verifier sensitivity, not agent success or an entire parent revision.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

CASES = [
    {"id": "stats-recovery", "fix": "f66656b08949d18953de6cfe243549182ca110df",
     "implementation": "configs/hooks/correction-detector.sh",
     "test": "tests/test-correction-pairing.sh",
     "expected_red": ["a stats.json full of conflict markers is rebuilt into valid JSON",
                      "the correction that found it is still counted",
                      "the unreadable file is kept beside it, not discarded"]},
    {"id": "prompt-noise", "fix": "78013146bc0e154668d5f3fb0289fde0cae5d7fd",
     "implementation": "configs/hooks/prompt-tracker.sh", "test": "tests/test-hooks.sh",
     "expected_red": ["machine-generated text is never fingerprinted"]},
]
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def run_lane(repo, output, case, lane):
    start = time.monotonic()
    parent = git(repo, "rev-parse", case["fix"] + "^").decode().strip()
    snapshot = git(repo, "archive", "--format=tar", case["fix"], "configs", "tests")
    with tempfile.TemporaryDirectory(prefix="clade-verifier-") as scratch:
        root = Path(scratch)
        with tarfile.open(fileobj=io.BytesIO(snapshot)) as archive:
            archive.extractall(root, filter="data")
        if lane == "red":
            (root / case["implementation"]).write_bytes(git(repo, "show", parent + ":" + case["implementation"]))
        env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        command = ["bash", case["test"]]
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=120)
        log = ANSI.sub("", result.stdout + result.stderr)
        log_name = case["id"] + "-" + lane + ".log"
        (output / log_name).write_text(log)
        failures = re.findall(r"^\s*✗ (.+)$", log, re.M)
        successes = re.findall(r"^\s*✓ (.+)$", log, re.M)
        test_hash = hashlib.sha256((root / case["test"]).read_bytes()).hexdigest()
    return {"case": case["id"], "lane": lane, "fixed_commit": case["fix"],
            "parent_commit": parent, "implementation": case["implementation"],
            "command": command, "test_sha256": test_hash, "exit_code": result.returncode,
            "passed_assertions": len(successes), "failed_assertions": failures,
            "skip_detected": bool(re.search(r"\bskip(?:ped|ping)?\b", log, re.I)),
            "log": log_name, "log_sha256": hashlib.sha256(log.encode()).hexdigest(),
            "seconds": round(time.monotonic() - start, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name in ("git", "bash", "jq", "python3"):
        if not shutil.which(name):
            parser.error(f"missing required dependency: {name}; not a passing lane")
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    workers = min(4, len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_lane, repo, args.output, case, lane)
                   for case in CASES for lane in ("red", "green")]
        lanes = [future.result() for future in futures]
    checks = []
    for case in CASES:
        red, green = [r for r in lanes if r["case"] == case["id"]]
        ready = (red["exit_code"] != 0 and sorted(red["failed_assertions"]) == sorted(case["expected_red"])
                 and green["exit_code"] == 0 and not green["failed_assertions"]
                 and green["passed_assertions"] > 0
                 and red["passed_assertions"] + len(red["failed_assertions"]) == green["passed_assertions"]
                 and red["test_sha256"] == green["test_sha256"]
                 and not red["skip_detected"] and not green["skip_detected"])
        checks.append({"case": case["id"], "verifier_ready": ready})
    report = {"kind": "historical-verifier-calibration", "agent_trials": 0,
              "snapshot_rule": "fixed snapshot and tests; red restores only owned implementation from parent",
              "workers": workers, "native_threads": 1, "gpu_used": False,
              "seconds": round(time.monotonic() - started, 3), "checks": checks, "lanes": lanes}
    (args.output / "preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if all(c["verifier_ready"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
