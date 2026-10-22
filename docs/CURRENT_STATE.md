# Orcha: current status

The current implementation brief is [plan.md](../plan.md). This page describes
this checkout; historical design notes and original-data evaluation reports are
not evidence of completed assistant features.

## Working locally

- Typed CSV inputs, exact Decimal money, and dated FX normalization.
- Ledger lifecycle resolution and evidence-based recurring cash flow.
- A 90-day forecast with minimum-balance protection.
- Payment-plan generation, verification, ranking, and explanations.
- Independent replay and serialized-output validation.
- A self-contained synthetic demo before and after a new bill.

The product, distribution, CLI, and import namespace now use **Orcha** / `orcha`.
The package is `src/orcha/`; run `python main.py`, `python -m orcha.cli` after
installation, or the installed `orcha` command.

## Verified baseline

See [BASELINE.md](BASELINE.md) for the environment and actual check results.
The existing suite passed 89 checks, with 17 failures and one skip tied to missing
original data or images. Lint, formatting, and static type checks passed.
The demo passes smoke, data audit, generation, and independent output validation.

The naming cleanup was checked separately: the same 89 tests pass, the same 17
original-data tests fail, and one skips. Lint, formatting, and type checks pass.
A local `orcha-0.1.0` wheel builds without downloading dependencies; its console
entry point is `orcha = orcha.cli:main`, and the packaged CLI reports
`orcha 0.1.0`. Demo output, including explanations, matches the pre-rename output
exactly. All 11 recorded data/cache/expected-result file hashes are unchanged.
Local check logs are under `.local/rename/` and excluded from source control.

| Synthetic scenario | Safe amount today | Recommendation |
| --- | ---: | --- |
| Before repair bill | INR 25,000 | Full payment on October 21, 2026 |
| After INR 12,000 bill | INR 18,000 | Wait; full payment on October 25, 2026 |

## Next work

1. Complete one Gemma workflow: fresh question/update, validated facts and source
   references, deterministic engine result, and grounded explanation.
2. Add local Laya action selection with a deterministic fallback.
3. Add a minimal upload/question/result interface and action visibility.
4. Finish focused checks, setup, demo recording, and a local submission draft.

No live model adapter, model routing, or upload interface is implemented yet.
The original dataset and receipt assets are not present in this checkout.
