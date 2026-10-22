# Orcha

A financial assistant for everyday purchase decisions. Orcha forecasts cash flow,
protects a minimum balance, and explains when and how a purchase can be paid for.

**Current status:** the deterministic financial engine and a synthetic offline demo
work locally. Gemma interpretation, local Laya routing, and an upload interface are
planned in [plan.md](plan.md); they are not implemented yet.

## How it works

1. Load a financial profile, transaction history, purchase question, and supporting evidence.
2. Resolve financial events and recurring income and expenses.
3. Simulate 90 days while preserving the user's minimum balance.
4. Generate, verify, and rank eligible payment plans.
5. Return a recommendation with the safe amount, payment dates, and explanation.

Python owns all financial calculations and plan verification. The planned Gemma
integration will interpret evidence and explain verified results; Laya will select
from a bounded set of workflow actions.

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

The original dataset and receipt images are absent. The baseline run passed 89
checks; 17 original-data checks failed and one skipped. The synthetic demo passes
smoke, data audit, generation, and independent output validation. The baseline
report includes Windows temporary-directory workarounds and reproducible commands.

## Documentation

- [Current status](docs/CURRENT_STATE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data contract](docs/DATA_CONTRACT.md)
- [Decision rules](docs/DECISION_RULES.md)
- [Validation approach](docs/EVALUATION.md)
- [Roadmap](docs/PHASES.md)
- [Baseline evidence](docs/BASELINE.md)
- [Historical engine design notes](docs/ENGINE_DESIGN_NOTES.md)
