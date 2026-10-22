# Orcha: current status

Updated October 22, 2026. The active brief is [plan.md](../plan.md).

## Working

- Local CSV financial imports, typed Decimal money, and dated FX normalization.
- Canonical ledger resolution, recurrence, 90-day simulation, payment planning,
  deterministic explanations, and independent result verification.
- Synthetic offline demo data and expected financial decisions.
- Google AI Studio Gemma interpretation through the explicit `--assist` command.
- Fresh purchase questions, new unpaid text bills, and scheduled-bill amendments.
- Source-grounded amounts/dates, clarification on incomplete/conflicting evidence,
  bounded provider retries, optional content-based local caching, and JSON briefs.

The provider receives only the selected question and text updates, source IDs,
reference date, and currency. Financial profiles/history stay local. Python
validates all extracted facts and independently verifies recommendations. The
brief uses engine output, not model-generated financial conclusions.

See [ASSISTANT.md](ASSISTANT.md) for commands, data flow, supported inputs, and limits.
The product, distribution, CLI, and import namespace are **Orcha** / `orcha`.

## Verified live examples

All live requests used fictional demo text with `gemma-4-26b-a4b-it`.

| Scenario | Result |
| --- | --- |
| Fresh 12,000 INR repair bill | Safe today 18,000; pay the 25,000 laptop price on October 25. |
| Missing repair amount | Clarification; no forecast or financial recommendation. |
| Existing repair bill amended to 15,000 | Safe today 15,000; pay the laptop price on October 25. |

Early provider probes saw a transient internal error and a timeout. The working
configuration uses minimal thinking and a bounded output budget. Successful-run
latency and actual token usage are recorded in [ASSISTANT.md](ASSISTANT.md).

## Offline verification

The root dataset and all 16 receipt images are restored. All original 107 tests
pass with the corrected sample-request lookup. New assistant tests cover complete
workflows, source validation, conflicts, missing facts, ownership, unavailable FX,
provider errors, retry bounds, caches, secrets, and CLI JSON output without API keys.

Final result: **144 tests passed in 20.71 seconds**, including 37 new assistant
checks. Lint and type checks passed; all eight changed/new Python files pass the
format check. The wheel builds and includes the new workflow modules.
Current test logs are under `.local/task2/`. The repository-wide format check flags an existing extra blank
line in `tests/test_cli.py`; that file is unchanged by task 2.

Original dataset/cache files match their earlier verified hashes. Historical
baseline results remain in [BASELINE.md](BASELINE.md); their missing-data status
is historical and no longer describes this checkout.

## Next work

1. Add local Laya action selection with deterministic eligibility and fallback.
2. Add a minimal upload/question/result interface with source and action visibility.
3. Finish remaining focused checks, setup, demo recording, and submission draft.

Image/PDF extraction, income-change interpretation, and an upload interface are
not part of this first text workflow. Existing image facts remain cache-backed.
