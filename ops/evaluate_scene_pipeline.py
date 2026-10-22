"""Evaluate the OpenCV 5 scene pipeline against baselines on synthetic scenes.

Methods compared on identical rendered pairs:

* ``pipeline``: quality gates + shape-filtered lit-red detection + fusion;
* ``ablation_no_quality_gate``: the same detector without quality gates;
* ``baseline_naive_red``: red-pixel count only (no morphology/shape/quality);
* ``baseline_legacy_brightness``: the prior grey-threshold pixel count.

Thresholds were chosen on the ``dev`` split; the ``test`` split uses
different seeds and wider parameter ranges. All inputs are SYNTHETIC; the
numbers bound pipeline behaviour on this generator only, not field accuracy.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vision import scene_analysis as sa  # noqa: E402
from vision.synthetic_scenes import (  # noqa: E402
    GENERATOR_VERSION,
    SCENARIOS,
    VIEWS,
    generate_split,
)


DECISIONS = ("REVIEW", "REQUEST_VIEW", "STOP")
METHODS = (
    "pipeline",
    "ablation_no_quality_gate",
    "baseline_naive_red",
    "baseline_legacy_brightness",
)


def _decide(method: str, views: dict) -> tuple[str, str, float]:
    started = time.perf_counter()
    if method == "pipeline":
        fused = sa.fuse({name: sa.analyze_view(px) for name, px in views.items()})
    elif method == "ablation_no_quality_gate":
        fused = sa.fuse(
            {
                name: sa.analyze_view(px, use_quality_gate=False)
                for name, px in views.items()
            }
        )
    elif method == "baseline_naive_red":
        alarm = any(sa.baseline_naive_red(px) for px in views.values())
        fused = {
            "decision": "STOP" if alarm else "REVIEW",
            "reason": "ALARM" if alarm else "HUMAN_REVIEW",
        }
    elif method == "baseline_legacy_brightness":
        alarm = any(sa.baseline_legacy_brightness(px) for px in views.values())
        fused = {
            "decision": "STOP" if alarm else "REVIEW",
            "reason": "ALARM" if alarm else "HUMAN_REVIEW",
        }
    else:
        raise ValueError(method)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return fused["decision"], fused["reason"], elapsed_ms


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(split: str, per_scenario: int) -> dict[str, object]:
    scenes = generate_split(split, per_scenario)
    results: dict[str, object] = {}
    for method in METHODS:
        confusion = {e: Counter() for e in DECISIONS}
        per_scenario_correct = defaultdict(int)
        per_scenario_total = defaultdict(int)
        latencies = []
        exact = acceptable = unsafe = false_stop = 0
        alarm_total = non_alarm_total = 0
        degraded_request = degraded_total = 0
        failures = []
        for scene in scenes:
            scenario = scene.scenario
            decision, reason, elapsed = _decide(method, scene.views)
            latencies.append(elapsed)
            confusion[scenario.expected][decision] += 1
            per_scenario_total[scenario.name] += 1
            if decision == scenario.expected:
                exact += 1
                per_scenario_correct[scenario.name] += 1
            if decision in scenario.acceptable:
                acceptable += 1
            if scenario.alarm_present:
                alarm_total += 1
                if decision == "REVIEW":
                    unsafe += 1
            else:
                non_alarm_total += 1
                if decision == "STOP":
                    false_stop += 1
            if scenario.expected == "REQUEST_VIEW":
                degraded_total += 1
                degraded_request += decision == "REQUEST_VIEW"
            if decision not in scenario.acceptable:
                failures.append(
                    {
                        "scenario": scenario.name,
                        "index": scene.index,
                        "seed": scene.seed,
                        "expected": scenario.expected,
                        "decision": decision,
                        "reason": reason,
                    }
                )
        total = len(scenes)
        failure_summary = Counter(
            (f["scenario"], f["decision"], f["reason"]) for f in failures
        )
        results[method] = {
            "pairs": total,
            "exact_accuracy": _rate(exact, total),
            "acceptable_rate": _rate(acceptable, total),
            "unsafe_miss_count": unsafe,
            "unsafe_miss_rate": _rate(unsafe, alarm_total),
            "false_stop_count": false_stop,
            "false_stop_rate": _rate(false_stop, non_alarm_total),
            "request_view_recall_on_degraded": _rate(degraded_request, degraded_total),
            "confusion_expected_to_decision": {
                expected: {d: confusion[expected][d] for d in DECISIONS}
                for expected in DECISIONS
            },
            "per_scenario_exact": {
                name: f"{per_scenario_correct[name]}/{per_scenario_total[name]}"
                for name in per_scenario_total
            },
            "failure_modes": [
                {
                    "scenario": scenario,
                    "decision": decision,
                    "reason": reason,
                    "count": count,
                }
                for (scenario, decision, reason), count in sorted(
                    failure_summary.items()
                )
            ],
            "first_failure_seeds": failures[:10],
            "latency_ms_per_pair": {
                "median": round(statistics.median(latencies), 3),
                "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3),
            },
        }
    return {
        "split": split,
        "per_scenario": per_scenario,
        "scenario_count": len(SCENARIOS),
        "pairs": len(scenes),
        "frames": len(scenes) * len(VIEWS),
        "methods": results,
    }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-per-scenario", type=int, default=10)
    parser.add_argument("--test-per-scenario", type=int, default=30)
    parser.add_argument("--output", help="Optional JSON evidence path")
    args = parser.parse_args()

    report = {
        "schema_version": 1,
        "cut": "VISUALGUARD_OPENCV5_SCENE_PIPELINE_EVAL001",
        "evidence_mode": "SYNTHETIC_SCENE_EVALUATION",
        "provenance": "DERIVED",
        "source_commit": _git_sha(),
        "generator_version": GENERATOR_VERSION,
        "runtime": {
            **sa.runtime_evidence(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "config": sa.CONFIG,
        "threshold_selection": "dev split only; test split held out",
        "scenarios": [
            {
                "name": s.name,
                "expected": s.expected,
                "acceptable": sorted(s.acceptable),
                "alarm_present": s.alarm_present,
                "note": s.note,
            }
            for s in SCENARIOS
        ],
        "dev": evaluate("dev", args.dev_per_scenario),
        "test": evaluate("test", args.test_per_scenario),
        "live_state": {
            "camera": "NOT_RUN",
            "aws": "NOT_RUN",
            "physical_action": "NONE",
        },
        "limitations": [
            "All frames are procedurally rendered; metrics do not establish field accuracy.",
            "The same author wrote the generator and the detector; held-out seeds and wider ranges reduce but do not remove that coupling.",
            "Latency is measured in-process on the evaluation host, without network or AWS overhead.",
        ],
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    summary = {
        split: {
            method: {
                key: report[split]["methods"][method][key]
                for key in (
                    "exact_accuracy",
                    "acceptable_rate",
                    "unsafe_miss_count",
                    "false_stop_count",
                    "request_view_recall_on_degraded",
                )
            }
            for method in METHODS
        }
        for split in ("dev", "test")
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
