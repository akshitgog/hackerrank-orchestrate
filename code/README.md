# Buy or Wait? submission

Python 3.11+ implementation for the HackerRank Orchestrate challenge. LiteLLM is
used only to turn relevant messages and images into validated evidence facts.
All balances, FX conversion, recurrence, 90-day simulation, payment candidates,
spending recovery, ranking, labels, and final guardrails are deterministic and use
`Decimal`.

## Setup

```text
python -m pip install -r code/requirements.txt
copy code/.env.example code/.env
```

Configure Amazon Bedrock credentials in `code/.env` or through the standard AWS
credential chain. Model identifiers can be set with `EVIDENCE_TEXT_MODEL` and
`EVIDENCE_VISION_MODEL`; otherwise `code/config.yaml` supplies the defaults. Never
commit `code/.env`.

## Final run

Run from the repository root:

```text
python code/main.py --config code/config.yaml --requests dataset/requests.csv --output output.csv --debug --final-run
```

This writes the exact eight-column submission CSV, one row per request. Debug mode
writes per-request JSON traces beneath `artifacts/debug/output/` and does not alter
predictions. Final-run model accounting is written to
`code/evaluation/usage_report.md` and `code/evaluation/token_usage.md`.

Model or request failures are isolated. If required evidence cannot be resolved,
the request receives the conservative contract-compliant fallback row and the
failure is visible in its trace.

## Public sample evaluation

```text
python code/main.py --config code/config.yaml --requests dataset/sample_requests.csv --output artifacts/sample_predictions.csv --debug
python code/evaluation/main.py --expected dataset/sample_requests.csv --predictions artifacts/sample_predictions.csv --profiles dataset/financial_profiles.csv --rates dataset/exchange_rates.csv --details artifacts/sample_evaluation.csv --report artifacts/sample_evaluation.md
```

The evaluator reports native and USD-normalized amount errors, classification
metrics and confusion matrices, semantic plan/action matches, date errors, and
structural failures. It never changes production predictions.

## Tests

```text
python -m pytest
python -m unittest discover -s code/tests -v
```

Generated artifacts, caches, local credentials, and Python bytecode are excluded
from version control.
