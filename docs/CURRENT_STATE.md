# Orcha: current status

Updated October 23, 2026. The active brief is [plan.md](../plan.md).

## Working

- Deployed Laya workflow v1: normalized input and a 768-weight scorer adaptation.
  All four production routing stages pass. Three candidate Gemma scenarios pass;
  see [LAYA_REFINEMENT.md](LAYA_REFINEMENT.md) for scope and verification.
- Local web workspace with CSV imports, text updates, cash-flow chart, verified
  recommendations, source evidence, and model/fallback traces. See [WEB_INTERFACE.md](WEB_INTERFACE.md).
- Local CSV financial imports, typed Decimal money, and dated FX normalization.
- Canonical ledger resolution, recurrence, 90-day simulation, payment planning,
  deterministic explanations, and independent result verification.
- Synthetic offline demo data and expected financial decisions.
- Google AI Studio Gemma interpretation through the explicit `--assist` command.
- Fresh purchase questions, new unpaid text bills, and scheduled-bill amendments.
- Source-grounded amounts/dates, clarification on incomplete/conflicting evidence,
  bounded provider retries, optional content-based local caching, and JSON briefs.
- Authenticated CPU Laya inference on InstaCloud, compact workflow state, bounded
  proposals, eligibility checks, confidence threshold, and a local fallback.

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

Task 2 result: **144 tests passed in 20.71 seconds**, including 37 assistant
checks. Task 3 result: **169 tests passed in 19.64 seconds**, adding 25 routing
and service-boundary checks. These checks use stubs and require no cloud access.
Lint, type checks, and formatting of all changed/new Python files passed.
The repository-wide format check flags an existing extra blank line in
`tests/test_cli.py`; that file is unchanged by this work.

Original dataset/cache files match their earlier verified hashes. Historical
baseline results remain in [BASELINE.md](BASELINE.md); their missing-data status
is historical and no longer describes this checkout.

## Next work

1. Decide whether optional Task 5 integrations add value to the demonstration.
2. Complete Task 6: demo recording and submission draft, with final delivery checks.

Task 3's service is deployed to the isolated `laya-service` cloud branch. Its
322M multilingual checkpoint loaded on CPU in 10.82 seconds. Four live stage
probes all proposed `explain_result` at 0.46-0.52 confidence: the controller rejects
them as ineligible or below the default 0.8 threshold. This demonstrates the
fallback, not reliable model routing. See [LAYA_SERVICE.md](LAYA_SERVICE.md).
The live combined Gemma/Laya demo completed in 12.79 seconds and retained the
verified 18,000 INR safe-today result and October 25 full-payment date. All three
routing points used the documented fallback.

Task 4's 15 API checks bring the suite to 184 passing tests. Desktop and mobile
browser checks and live examples are documented in WEB_INTERFACE.md, including
the browser extension's automated-file-selection limitation.

Fresh image/PDF extraction and income-change interpretation remain unsupported.
The interface accepts CSV bundles and text updates. Existing image facts remain
cache-backed.
