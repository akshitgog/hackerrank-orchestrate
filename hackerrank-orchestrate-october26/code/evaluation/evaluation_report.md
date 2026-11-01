# Threshold Evaluation Report

Generated: 2026-10-25T02:37:43.678357+00:00

## Purpose

This report records measurements from the real production pipeline. Each threshold produces a saved prediction CSV first; the evaluator then scores that exact file. The evaluator does not rerun the scanner for a saved-prediction run.

## Reproducibility policy

- Intent/model mode: deterministic fallback (--no-llm)
- Runtime cache: `cache\multimodal_cache.json`
- Cache lifecycle: one optional clear before the sweep, then reuse across thresholds.
- Sample truth: `dataset/sample_output.csv` (preserved; never overwritten).
- Per-threshold predictions: `evaluation/threshold_runs/`.
- Selected sample predictions: `sample_predictions.csv`.

## Threshold selection

Thresholds are selected from measured results, not by copying a fixed value. The ranking is status accuracy first, step F1 second, full-case exact matches third, and evidence grounding fourth. If the configured threshold is tied for the top score, it is retained as the operational baseline and the tie is documented.

Configured threshold: **0.65**
Selected threshold: **0.65**
Selection reason: The configured baseline 0.65 is tied for the best measured score, so it remains the selected operating threshold. This is a measured tie, not an assumed advantage.

## All threshold results

| Threshold | Status accuracy | Step F1 | Exact cases | Precision | Recall | Field accuracy | Sequence accuracy | Evidence grounding |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |
| 0.60 | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |
| 0.65 **selected** | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |
| 0.70 | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |
| 0.80 | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |
| 0.85 | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |
| 0.90 | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |
| 0.95 | 1.0000 | 0.9741 | 24/32 | 0.9741 | 0.9741 | 1.0000 | 1.0000 | 1.0000 |

## Selected sample run

- Status accuracy: `1.0000`
- Step F1: `0.9741`
- Full-case exact matches including evidence IDs: `24/32`
- Guardrail pass rate: `1.0000`

## Whole-dataset packaging

- Root output: `output.csv`
- Rows: `518`
- COMPLETE: `210`
- INCOMPLETE: `298`
- NOT_APPLICABLE: `10`
- JSON and row-order validation: passed.
