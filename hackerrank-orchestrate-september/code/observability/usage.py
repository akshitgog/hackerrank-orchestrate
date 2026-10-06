from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cost(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def write_usage_reports(
    records: list[dict[str, Any]],
    usage_report_path: Path,
    token_usage_path: Path | None = None,
    *,
    run_type: str,
    requests_processed: int,
) -> dict[str, Any]:
    provider_calls = [record for record in records if record.get("provider_call", True)]
    aggregate: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "input": 0, "output": 0, "total": 0, "cost": Decimal("0"), "cost_known": True}
    )
    by_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "input": 0, "output": 0, "total": 0}
    )
    unavailable = 0
    for record in provider_calls:
        model = str(record.get("model") or "unavailable")
        call_type = str(record.get("call_type") or "unavailable")
        values = tuple(_number(record.get(field)) for field in ("input_tokens", "output_tokens", "total_tokens"))
        item = aggregate[model]
        item["calls"] += 1
        by_type[call_type]["calls"] += 1
        if any(value is None for value in values):
            unavailable += 1
        else:
            input_tokens, output_tokens, total_tokens = values
            if total_tokens != input_tokens + output_tokens:
                raise ValueError(f"usage total mismatch for {record.get('request_id')} {call_type}")
            item["input"] += input_tokens
            item["output"] += output_tokens
            item["total"] += total_tokens
            by_type[call_type]["input"] += input_tokens
            by_type[call_type]["output"] += output_tokens
            by_type[call_type]["total"] += total_tokens
        cost = _cost(record.get("cost"))
        if cost is None:
            item["cost_known"] = False
        else:
            item["cost"] += cost

    generated = datetime.now(timezone.utc).isoformat()
    models = ", ".join(sorted(aggregate)) or "none"
    token_lines = [
        "# Token Usage Report", "", "## Run Information", "",
        f"- Run type: {run_type}",
        f"- Requests processed: {requests_processed}",
        f"- Models used: {models}",
        f"- Generated at: {generated}", "", "## Aggregate Usage", "",
        "| Model | Calls | Input Tokens | Output Tokens | Total Tokens | Cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model, item in sorted(aggregate.items()):
        cost_text = str(item["cost"]) if item["cost_known"] else "not reported"
        token_lines.append(
            f"| {model} | {item['calls']} | {item['input']} | {item['output']} | {item['total']} | {cost_text} |"
        )
    if not aggregate:
        token_lines.append("| none | 0 | 0 | 0 | 0 | not reported |")
    token_lines.extend(["", "## Usage by Call Type", "", "| Call Type | Calls | Input Tokens | Output Tokens | Total Tokens |", "|---|---:|---:|---:|---:|"])
    for call_type, item in sorted(by_type.items()):
        token_lines.append(f"| {call_type} | {item['calls']} | {item['input']} | {item['output']} | {item['total']} |")
    if not by_type:
        token_lines.append("| none | 0 | 0 | 0 | 0 |")
    token_lines.extend(["", "## Per-Request Usage", "", "| Request ID | Call Type | Model | Input Tokens | Output Tokens | Total Tokens | Latency | Cost | Status |", "|---|---|---|---:|---:|---:|---:|---:|---|"])
    for record in records:
        def shown(field: str) -> str:
            value = record.get(field)
            return "unavailable" if value is None else str(value)
        token_lines.append(
            f"| {record.get('request_id', 'unknown')} | {record.get('call_type', 'unknown')} | "
            f"{record.get('model', 'unknown')} | {shown('input_tokens')} | {shown('output_tokens')} | "
            f"{shown('total_tokens')} | {shown('latency_seconds')} | "
            f"{shown('cost') if record.get('cost') is not None else 'not reported'} | {record.get('status', 'unknown')} |"
        )
    if not records:
        token_lines.append("| none | none | none | 0 | 0 | 0 | 0 | not reported | no model calls |")
    totals = {
        "calls": sum(item["calls"] for item in aggregate.values()),
        "input": sum(item["input"] for item in aggregate.values()),
        "output": sum(item["output"] for item in aggregate.values()),
        "total": sum(item["total"] for item in aggregate.values()),
        "unavailable": unavailable,
    }
    known_costs = [item["cost"] for item in aggregate.values() if item["cost_known"]]
    all_cost_known = bool(aggregate) and all(item["cost_known"] for item in aggregate.values())
    cost_text = str(sum(known_costs, Decimal("0"))) if all_cost_known else "not reported"
    token_lines.extend([
        "", "## Totals", "",
        f"- Total model calls: {totals['calls']}",
        f"- Total input tokens: {totals['input']}",
        f"- Total output tokens: {totals['output']}",
        f"- Total tokens: {totals['total']}",
        f"- Total reported cost: {cost_text}",
        f"- Calls with unavailable token usage: {unavailable}", "",
    ])
    if token_usage_path is not None:
        token_usage_path.parent.mkdir(parents=True, exist_ok=True)
        token_usage_path.write_text("\n".join(token_lines), encoding="utf-8")

    average_tokens = (Decimal(totals["total"]) / requests_processed) if requests_processed else Decimal("0")
    usage_lines = [
        "# Final Full-Dataset Model Usage", "",
        f"- Run type: {run_type}",
        f"- Requests processed: {requests_processed}",
        f"- Models/providers: {models}",
        f"- Model calls: {totals['calls']}",
        f"- Input tokens: {totals['input']}",
        f"- Output tokens: {totals['output']}",
        f"- Total tokens: {totals['total']}",
        f"- Average tokens per request: {average_tokens}",
        f"- Total cost: {cost_text}",
        f"- Average cost per request: {(Decimal(cost_text) / requests_processed) if cost_text != 'not reported' and requests_processed else 'not reported'}",
        f"- Calls with unavailable usage: {unavailable}", "",
        "Counts include only model calls made by the submitted runtime; cache hits are not counted as provider calls.", "",
    ]
    usage_report_path.parent.mkdir(parents=True, exist_ok=True)
    usage_report_path.write_text("\n".join(usage_lines), encoding="utf-8")
    totals["cost"] = cost_text
    return totals
