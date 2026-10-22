# Orcha

A financial assistant for everyday purchase decisions. Orcha forecasts cash flow,
protects a minimum balance, and explains when and how a purchase can be paid for.

**Current status:** the financial engine works locally, and hosted Gemma can
interpret fresh purchase questions and text bill updates through `--assist`.
Local Laya routing and an upload interface are next in [plan.md](plan.md).

## How it works

1. Load a financial profile, transaction history, purchase question, and supporting evidence.
2. Resolve financial events and recurring income and expenses.
3. Simulate 90 days while preserving the user's minimum balance.
4. Generate, verify, and rank eligible payment plans.
5. Return a recommendation with the safe amount, payment dates, and explanation.

Python owns all financial calculations, plan verification, and the final brief.
Gemma extracts typed facts and source quotes; Python validates them before ledger
use. Planned Laya routing will select from a bounded set of workflow actions.

## Run the offline demo

Use Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\orcha.exe --dataset demo/dataset --smoke
.\.venv\Scripts\orcha.exe --dataset demo/dataset --decision demo_before_bill
.\.venv\Scripts\orcha.exe --dataset demo/dataset --decision demo_after_bill
```

If `python` is unavailable, replace it with your installed interpreter's full path.
The [baseline report](docs/BASELINE.md) records the working path on this machine.
For an environment with dependencies already installed, `python main.py` runs the
same CLI without installing the package.

The demo compares a 25,000 INR laptop purchase before and after a new 12,000 INR
repair bill. It recommends paying today before the bill and waiting until October
25 after it. All demo data is fictional; no API key or network call is required.
See [demo instructions](demo/README.md) for the inputs and validated results.

## Ask with fresh text evidence

Add your Google AI Studio key as `GEMMA_API_KEY` in the ignored `.env` file, then run:

```powershell
python main.py --dataset demo/dataset --assist demo/assistant_request.json
python main.py --dataset demo/dataset --assist demo/assistant_missing_amount.json
python main.py --dataset demo/dataset --assist demo/assistant_amendment.json --brief-json
```

Only the selected question and text updates, reference date, and currency go to
Google. Profiles, transaction history, calculations, and verification stay local.
The first text workflow supports unpaid one-off bills and scheduled-bill
amendments. Missing/conflicting/unsupported facts produce clarification instead
of a recommendation. See [assistant setup and limits](docs/ASSISTANT.md).

## Commands

The installed command is `orcha`; the Python import namespace is `orcha`.
You can also run `python main.py` or, with the package installed, `python -m orcha.cli`.
The examples below assume the environment is active; otherwise use
`.\.venv\Scripts\orcha.exe` in place of `orcha`.

```powershell
orcha --help
orcha --version
orcha --dataset demo/dataset --audit-data
orcha --dataset demo/dataset --forecast demo_after_bill
orcha --dataset demo/dataset --decision demo_after_bill
New-Item -ItemType Directory -Force -Path .local | Out-Null
orcha --dataset demo/dataset --output .local/demo-output.csv --generate
orcha --dataset demo/dataset --output .local/demo-output.csv --validate-output
```

`DATASET_DIR`, `OUTPUT_CSV`, and `LOG_LEVEL` provide optional environment overrides.
Keep secrets out of source control; `.env.example` describes the current settings.

## Repository

- `src/orcha/`: loaders, evidence handling, ledger, simulation, planning, and CLI.
- `tests/`: existing offline checks and original-dataset integration checks.
- `demo/`: self-contained synthetic data and expected decisions.
- `docs/`: architecture, financial rules, current status, baseline, and design history.
- `evaluation/`: historical diagnostics from the earlier engine dataset.
- `plan.md`: current implementation brief and build order.

## Verification

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src tests main.py
```

The restored original dataset and its 16 receipt images are present locally.
The original 107 tests pass after correcting the sample-request integration test.
Focused assistant checks also run offline without API keys or paid calls; current
results are recorded in [CURRENT_STATE.md](docs/CURRENT_STATE.md). The synthetic
demo passes smoke, data audit, generation, and independent output validation.
The baseline report includes Windows temporary-directory workarounds.

## Documentation

- [Current status](docs/CURRENT_STATE.md)
- [Gemma assistant](docs/ASSISTANT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data contract](docs/DATA_CONTRACT.md)
- [Decision rules](docs/DECISION_RULES.md)
- [Validation approach](docs/EVALUATION.md)
- [Roadmap](docs/PHASES.md)
- [Baseline evidence](docs/BASELINE.md)
- [Historical engine design notes](docs/ENGINE_DESIGN_NOTES.md)
