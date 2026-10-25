"""Run reproducible sample threshold experiments and package the best result.

The workflow is intentionally two-stage:

1. Run the real production pipeline once per threshold and save each prediction CSV.
2. Score those saved CSVs against ``dataset/sample_output.csv`` without rerunning the
   pipeline, so every reported metric belongs to one exact prediction artifact.

The multimodal cache is warmed once and reused for every threshold. ``--clear-cache``
only removes the runtime extraction cache before the first run; it never deletes the
evidence manifest or the supplied sample truth.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from code.config.loader import load_config
from code.evaluation.main import EvaluationEngine


def _threshold_label(threshold: float) -> str:
    return f"{threshold:.2f}".replace(".", "_")


def _run_command(command: list[str], log_path: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        tail = completed.stdout[-3000:]
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}\n{tail}"
        )


def _exact_case_matches(prediction_path: Path, truth_path: Path) -> int:
    predictions = pd.read_csv(prediction_path)
    truth = pd.read_csv(truth_path)
    truth_map = {
        str(row["case_id"]): (
            str(row["deletion_status"]),
            json.loads(str(row["steps_json"])),
        )
        for _, row in truth.iterrows()
    }
    matches = 0
    for _, row in predictions.iterrows():
        case_id = str(row["case_id"])
        predicted_steps = json.loads(str(row["steps_json"]))
        gold_status, gold_steps = truth_map[case_id]
        if str(row["deletion_status"]) == gold_status and predicted_steps == gold_steps:
            matches += 1
    return matches


def _validate_whole_output(output_path: Path, request_path: Path) -> dict[str, Any]:
    output = pd.read_csv(output_path)
    requests = pd.read_csv(request_path)
    required = ["case_id", "deletion_status", "steps_json"]
    if output.columns.tolist() != required:
        raise ValueError(f"Unexpected output columns: {output.columns.tolist()}")
    if len(output) != len(requests):
        raise ValueError(f"Expected {len(requests)} rows, found {len(output)}")
    for value in output["steps_json"]:
        parsed = json.loads(str(value))
        if not isinstance(parsed, list):
            raise ValueError("Every steps_json value must decode to a list")
    if output["case_id"].tolist() != requests["case_id"].tolist():
        raise ValueError("output.csv case order does not match deletion_requests.csv")
    return {
        "path": str(output_path),
        "rows": len(output),
        "complete": int((output["deletion_status"] == "COMPLETE").sum()),
        "incomplete": int((output["deletion_status"] == "INCOMPLETE").sum()),
        "not_applicable": int((output["deletion_status"] == "NOT_APPLICABLE").sum()),
    }


def _write_report(
    report_path: Path,
    *,
    thresholds: list[float],
    results: list[dict[str, Any]],
    configured_threshold: float,
    selected_threshold: float,
    selected_prediction: Path,
    cache_path: Path,
    deterministic: bool,
    whole_validation: dict[str, Any] | None,
) -> None:
    selected_rows = [r for r in results if r["threshold"] == selected_threshold]
    selected = selected_rows[0]
    top_score = max(
        (
            r["status_accuracy"],
            r["step_f1"],
            r["exact_case_matches"],
            r["evidence_grounding_accuracy"],
        )
        for r in results
    )
    top_thresholds = [
        r["threshold"]
        for r in results
        if (
            r["status_accuracy"],
            r["step_f1"],
            r["exact_case_matches"],
            r["evidence_grounding_accuracy"],
        )
        == top_score
    ]

    if configured_threshold in top_thresholds:
        selection_reason = (
            f"The configured baseline {configured_threshold:.2f} is tied for the best measured "
            "score, so it remains the selected operating threshold. This is a measured tie, "
            "not an assumed advantage."
        )
    else:
        selection_reason = (
            f"The configured baseline {configured_threshold:.2f} was not among the best measured "
            f"thresholds; {selected_threshold:.2f} was selected by status accuracy, then step F1, "
            "then full-case exact matches, then evidence grounding."
        )

    lines = [
        "# Threshold Evaluation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Purpose",
        "",
        "This report records measurements from the real production pipeline. Each threshold "
        "produces a saved prediction CSV first; the evaluator then scores that exact file. "
        "The evaluator does not rerun the scanner for a saved-prediction run.",
        "",
        "## Reproducibility policy",
        "",
        f"- Intent/model mode: {'deterministic fallback (--no-llm)' if deterministic else 'configured model'}",
        f"- Runtime cache: `{cache_path}`",
        "- Cache lifecycle: one optional clear before the sweep, then reuse across thresholds.",
        "- Sample truth: `dataset/sample_output.csv` (preserved; never overwritten).",
        "- Per-threshold predictions: `evaluation/threshold_runs/`.",
        f"- Selected sample predictions: `{selected_prediction}`.",
        "",
        "## Threshold selection",
        "",
        "Thresholds are selected from measured results, not by copying a fixed value. The "
        "ranking is status accuracy first, step F1 second, full-case exact matches third, "
        "and evidence grounding fourth. If the configured threshold is tied for the top score, "
        "it is retained as the operational baseline and the tie is documented.",
        "",
        f"Configured threshold: **{configured_threshold:.2f}**",
        f"Selected threshold: **{selected_threshold:.2f}**",
        f"Selection reason: {selection_reason}",
        "",
        "## All threshold results",
        "",
        "| Threshold | Status accuracy | Step F1 | Exact cases | Precision | Recall | Field accuracy | Sequence accuracy | Evidence grounding |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        marker = " **selected**" if result["threshold"] == selected_threshold else ""
        lines.append(
            f"| {result['threshold']:.2f}{marker} | {result['status_accuracy']:.4f} | "
            f"{result['step_f1']:.4f} | {result['exact_case_matches']}/32 | "
            f"{result['step_precision']:.4f} | {result['step_recall']:.4f} | "
            f"{result['field_accuracy']:.4f} | {result['sequence_accuracy']:.4f} | "
            f"{result['evidence_grounding_accuracy']:.4f} |"
        )

    lines.extend(
        [
            "",
            "## Selected sample run",
            "",
            f"- Status accuracy: `{selected['status_accuracy']:.4f}`",
            f"- Step F1: `{selected['step_f1']:.4f}`",
            f"- Full-case exact matches including evidence IDs: `{selected['exact_case_matches']}/32`",
            f"- Guardrail pass rate: `{selected['guardrail_pass_rate']:.4f}`",
            "",
            "## Whole-dataset packaging",
            "",
        ]
    )
    if whole_validation is None:
        lines.append("Whole-dataset execution was not requested in this run.")
    else:
        lines.extend(
            [
                f"- Root output: `{whole_validation['path']}`",
                f"- Rows: `{whole_validation['rows']}`",
                f"- COMPLETE: `{whole_validation['complete']}`",
                f"- INCOMPLETE: `{whole_validation['incomplete']}`",
                f"- NOT_APPLICABLE: `{whole_validation['not_applicable']}`",
                "- JSON and row-order validation: passed.",
            ]
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and document reproducible threshold experiments")
    parser.add_argument("--config", default="code/config/config.yaml")
    parser.add_argument("--thresholds", nargs="+", type=float, default=None)
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--rerun", action="store_true", help="Regenerate existing threshold artifacts")
    parser.add_argument("--with-llm", action="store_true", help="Use configured model calls; deterministic fallback is the default")
    parser.add_argument("--run-whole", action="store_true", help="Run the 518-request pipeline at the selected threshold")
    parser.add_argument("--rerun-whole", action="store_true", help="Regenerate output.csv even if it already exists")
    parser.add_argument("--report", default="evaluation/evaluation_report.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    configured_threshold = float(config.get("thresholds", {}).get("intent_decision", 0.65))
    thresholds = args.thresholds or [
        float(value)
        for value in config.get("thresholds", {}).get(
            "grid_search_candidates", [0.50, 0.60, 0.65, 0.70, 0.80, 0.85, 0.90, 0.95]
        )
    ]
    thresholds = sorted(set(thresholds))
    if any(not 0.0 <= value <= 1.0 for value in thresholds):
        raise ValueError(f"Every threshold must be between 0 and 1: {thresholds}")

    cache_path = REPO_ROOT / "cache" / "multimodal_cache.json"
    if args.clear_cache and cache_path.exists():
        cache_path.unlink()
        print(f"Cleared runtime cache: {cache_path}")

    run_root = REPO_ROOT / "evaluation" / "threshold_runs"
    run_root.mkdir(parents=True, exist_ok=True)
    truth_path = REPO_ROOT / "dataset" / "sample_output.csv"
    results: list[dict[str, Any]] = []
    engine = EvaluationEngine(config_path=args.config, use_llm=args.with_llm)

    for threshold in thresholds:
        label = _threshold_label(threshold)
        run_dir = run_root / f"threshold_{label}"
        run_dir.mkdir(parents=True, exist_ok=True)
        prediction_path = run_dir / "sample_predictions.csv"
        pipeline_log = run_dir / "pipeline.log"
        score_path = run_dir / "score.json"
        if prediction_path.exists() and score_path.exists() and not args.rerun:
            score = json.loads(score_path.read_text(encoding="utf-8"))
            results.append(score)
            print(
                f"Reusing threshold {threshold:.2f}: status={score['status_accuracy']:.4f} "
                f"step_f1={score['step_f1']:.4f} exact={score['exact_case_matches']}/32"
            )
            continue
        command = [
            sys.executable,
            "code/main.py",
            "--sample",
            "--threshold",
            f"{threshold:.4f}",
            "--output",
            str(prediction_path),
        ]
        if not args.with_llm:
            command.append("--no-llm")
        print(f"Running pipeline at threshold {threshold:.2f}...")
        _run_command(command, pipeline_log)

        score = engine.evaluate_prediction_file(prediction_path, threshold)
        score["threshold"] = threshold
        score["prediction_path"] = str(prediction_path)
        score["exact_case_matches"] = _exact_case_matches(prediction_path, truth_path)
        score_path.write_text(json.dumps(score, indent=2), encoding="utf-8")
        results.append(score)
        print(
            f"  status={score['status_accuracy']:.4f} step_f1={score['step_f1']:.4f} "
            f"exact={score['exact_case_matches']}/32"
        )

    top_key = lambda result: (
        result["status_accuracy"],
        result["step_f1"],
        result["exact_case_matches"],
        result["evidence_grounding_accuracy"],
    )
    best_score = max(top_key(result) for result in results)
    top_results = [result for result in results if top_key(result) == best_score]
    selected = next(
        (result for result in top_results if result["threshold"] == configured_threshold),
        top_results[0],
    )
    selected_threshold = float(selected["threshold"])
    selected_prediction = REPO_ROOT / "sample_predictions.csv"
    shutil.copyfile(selected["prediction_path"], selected_prediction)
    print(f"Selected threshold: {selected_threshold:.2f}")
    print(f"Saved selected sample predictions: {selected_prediction}")

    whole_validation: dict[str, Any] | None = None
    if args.run_whole:
        output_path = REPO_ROOT / "output.csv"
        if output_path.exists() and not args.rerun_whole:
            print("Reusing existing output.csv for whole-dataset validation")
        else:
            whole_log = REPO_ROOT / "evaluation" / "whole_pipeline.log"
            command = [
                sys.executable,
                "code/main.py",
                "--whole",
                "--threshold",
                f"{selected_threshold:.4f}",
                "--output",
                "output.csv",
            ]
            if not args.with_llm:
                command.append("--no-llm")
            print(f"Running whole dataset at threshold {selected_threshold:.2f}...")
            _run_command(command, whole_log)
        whole_validation = _validate_whole_output(
            output_path, REPO_ROOT / "dataset" / "deletion_requests.csv"
        )
        print(f"Validated root output.csv: {whole_validation['rows']} rows")

    _write_report(
        REPO_ROOT / args.report,
        thresholds=thresholds,
        results=results,
        configured_threshold=configured_threshold,
        selected_threshold=selected_threshold,
        selected_prediction=selected_prediction,
        cache_path=cache_path,
        deterministic=not args.with_llm,
        whole_validation=whole_validation,
    )
    history_path = REPO_ROOT / "evaluation" / "threshold_grid_history.jsonl"
    with history_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result) + "\n")
    print(f"Wrote threshold report: {REPO_ROOT / args.report}")


if __name__ == "__main__":
    main()
