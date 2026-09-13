from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from data.config import load_config, resolve_repo_path
from data.loader import load_dataset
from observability.usage import write_usage_reports
from pipeline.orchestrator import run_pipeline
from validation.guardrails import OUTPUT_COLUMNS, decision_row


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Buy or Wait? decision pipeline")
    parser.add_argument("--config", default="code/config.yaml")
    parser.add_argument("--requests")
    parser.add_argument("--output")
    parser.add_argument("--debug", action="store_true", help="Write per-request JSON traces")
    parser.add_argument(
        "--final-run", action="store_true",
        help="Write required final-run usage reports (automatically enabled for dataset/requests.csv -> output.csv)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    config_path = resolve_repo_path(repo_root, args.config)
    config = load_config(config_path, repo_root)
    dataset_dir = resolve_repo_path(repo_root, config["paths"]["dataset_dir"])
    requests_path = resolve_repo_path(repo_root, args.requests or config["paths"]["requests_file"])
    output_path = resolve_repo_path(repo_root, args.output or config["paths"]["output_file"])
    image_dir = resolve_repo_path(repo_root, config["paths"]["image_dir"])
    artifacts_dir = resolve_repo_path(repo_root, config["paths"]["artifacts_dir"])
    debug_enabled = args.debug or bool(config.get("logging", {}).get("write_debug_traces", False))
    debug_dir = artifacts_dir / "debug" / output_path.stem if debug_enabled else None

    dataset = load_dataset(dataset_dir, requests_path)
    decisions, summary = run_pipeline(
        dataset, config, image_dir=image_dir, artifacts_dir=artifacts_dir,
        debug_dir=debug_dir,
    )
    rows = [decision_row(decision) for decision in decisions]
    if [row["request_id"] for row in rows] != [request.request_id for request in dataset.requests]:
        raise RuntimeError("output request IDs do not exactly match input order")
    if len({row["request_id"] for row in rows}) != len(rows):
        raise RuntimeError("output contains duplicate request IDs")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    final_run = args.final_run or (
        requests_path.resolve() == (dataset_dir / "requests.csv").resolve()
        and output_path.resolve() == (repo_root / "output.csv").resolve()
    )
    usage_totals = None
    if final_run:
        usage_totals = write_usage_reports(
            list(summary.model_records),
            repo_root / "code" / "evaluation" / "usage_report.md",
            run_type="final evaluation dataset",
            requests_processed=summary.processed,
        )
        write_usage_reports(
            list(summary.model_records),
            artifacts_dir / "usage_report.md",
            run_type="final evaluation dataset",
            requests_processed=summary.processed,
        )

    # Save output copy and evaluation reports into artifacts folder
    save_output_and_evaluate(output_path, artifacts_dir, dataset_dir, requests_path, rows)

    run_summary = {
        "requests_processed": summary.processed,
        "successful": summary.successful,
        "fallback": summary.fallback,
        "failed_request_ids": list(summary.failed_request_ids),
        "output": str(output_path),
        "debug_directory": str(debug_dir) if debug_dir else None,
        "usage": usage_totals,
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / f"{output_path.stem}_run_summary.json").write_text(
        json.dumps(run_summary, indent=2, default=str), encoding="utf-8"
    )
    print(f"Wrote {len(rows)} rows to {output_path}")
    print(f"Saved evaluation artifacts to {artifacts_dir}")
    print(f"Successful requests: {summary.successful}/{summary.processed}")
    print(f"Fallback requests: {summary.fallback}/{summary.processed}")
    if debug_dir:
        print(f"Debug traces: {debug_dir}")
    if usage_totals is not None:
        print(f"Model calls: {usage_totals['calls']}; total tokens: {usage_totals['total']}")
    return 0


def save_output_and_evaluate(
    output_path: Path,
    artifacts_dir: Path,
    dataset_dir: Path,
    requests_path: Path,
    rows: list[dict[str, str]],
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_output = artifacts_dir / "output.csv"
    if output_path.resolve() != artifact_output.resolve():
        with artifact_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    sample_file = dataset_dir / "sample_requests.csv"
    rates_file = dataset_dir / "exchange_rates.csv"
    profiles_file = dataset_dir / "financial_profiles.csv"

    if requests_path.resolve() == sample_file.resolve():
        from evaluation.main import evaluate, write_details, write_report
        from decimal import Decimal
        details, eval_summary = evaluate(
            sample_file,
            output_path,
            profiles_file,
            rates_file if rates_file.exists() else None,
            tolerance=Decimal("0.01"),
        )
        write_details(artifacts_dir / "evaluation_details.csv", details)
        write_report(artifacts_dir / "evaluation_report.md", eval_summary, Decimal("0.01"))


if __name__ == "__main__":
    sys.exit(main())


