# Offline synthetic demo

All records here were created for this demo. No supplied financial records,
messages, receipts, or image assets were copied. IDs use a `demo_` prefix to avoid
the imported evidence cache IDs. Dates are fixed for reproducibility.

This is a deterministic engine baseline. It does not call Gemma or Laya, interpret
an uploaded document, or send data to an external service.

## Scenario

Two fictional profiles represent the same finances before and after a new bill:

- Reference date: October 21, 2026; home currency: INR.
- Available balance: 40,000; minimum balance to keep: 10,000.
- Monthly salary: 40,000 on the 25th, supported by two settled historical entries.
- Monthly rent: 18,000 on the 1st; groceries: 8,000 on the 5th;
  transport: 2,000 on the 10th. Each has three historical entries.
- Purchase: a 25,000 laptop, wanted by October 30, with no partial payments.
- Updated scenario only: a one-off 12,000 repair bill due October 23.

Settled history is already included in the opening balance. Recurrence is inferred
by the existing engine; historical amounts are not credited or debited again.
The new bill is explicitly encoded in `financial_events.csv` and corroborated by
`demo_repair_notice` in `messages.csv`. The message alone does not create the bill.
Turning fresh text into a validated new event is task 2.

| Request | Safe amount today | Recommendation | Full-payment date |
| --- | ---: | --- | --- |
| `demo_before_bill` | INR 25,000 | Pay in full today | October 21, 2026 |
| `demo_after_bill` | INR 18,000 | Wait, then pay in full | October 25, 2026 |

The safe amount is capped at the requested purchase amount. It is not the account's
uncapped spending capacity. Both recommendations preserve the 10,000 minimum
through the 90-day forecast. The updated case's 18,000 safe amount is information,
not a recommendation to make a partial payment.

## Run from the repository root

Use Python 3.11 or newer with the dependencies in `pyproject.toml`. On this
machine the launcher `py` did not discover Python; the following executable worked.
No dependency installation was needed during baseline verification.

```powershell
$demoPython = 'C:\Users\hp\AppData\Local\Programs\Python\Python313\python.exe'
& $demoPython main.py --dataset demo/dataset --smoke
& $demoPython main.py --dataset demo/dataset --audit-data
& $demoPython main.py --dataset demo/dataset --decision demo_before_bill
& $demoPython main.py --dataset demo/dataset --decision demo_after_bill
```

For an output file checked by both the production simulator and independent replay:

```powershell
New-Item -ItemType Directory -Force -Path .local | Out-Null
& $demoPython main.py --dataset demo/dataset --output .local/demo-output.csv --generate
& $demoPython main.py --dataset demo/dataset --output .local/demo-output.csv --validate-output
```

`expected_results.json` records the observed decision fields for manual comparison;
it is not loaded by the engine. `dataset/output.csv` is a header-only compatibility
file required by the existing loader, not a set of target predictions. Write
generated output under `.local/`, keeping all demo input files unchanged.

## Contents and limits

The dataset contains two requests, two profiles, 23 events, two payment options,
one message, one identity FX rate, and no images. All eight CSV files required by
the imported loader are present. There is no sample oracle or original dataset
dependency. Empty image metadata is deliberate; receipt extraction remains future
work. No evidence cache is required for these scenarios.

The old `--audit-evidence` command compares dataset IDs with the original global
caches. It is an original-dataset diagnostic and is not a suitable demo check.
Use `--audit-data`, `--smoke`, and the output validation commands above.

## Fresh text with hosted Gemma

The static CSV checks above remain offline. To interpret a genuinely new update,
use the separate assistant examples:

```powershell
python main.py --dataset demo/dataset --assist demo/assistant_request.json
python main.py --dataset demo/dataset --assist demo/assistant_missing_amount.json
python main.py --dataset demo/dataset --assist demo/assistant_amendment.json --brief-json
```

These explicit commands read `GEMMA_API_KEY` from the environment or `.env` and
send the selected fictional texts to Google. The first case adds the bill to the
`demo_before` profile in memory; the second asks for a missing amount; the third
amends an existing bill once. See [assistant documentation](../docs/ASSISTANT.md).
