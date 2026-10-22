# Orcha architecture

**AI interprets evidence; Python owns financial authority.**

## Current engine

```text
Financial CSV inputs
    -> typed records and FX normalization
    -> evidence-aware canonical ledger
    -> recurring cash-flow reconstruction
    -> 90-day simulation and safe-payment capacity
    -> candidate payment plans
    -> safety verification and deterministic ranking
    -> recommendation, explanation, and validated output
```

| Module | Responsibility |
| --- | --- |
| `orcha.cli` / `orcha.config` | Commands, input/output paths, and runtime settings. |
| `orcha.models` / `orcha.loaders` | Typed financial records, dates, and CSV parsing. |
| `orcha.repository` / `orcha.money` | Entity indexes, Decimal amounts, and dated FX conversion. |
| `orcha.evidence` | Saved image facts and deterministic message parsing. |
| `orcha.ledger` | Lifecycle resolution, amendments, recurrence, and source links. |
| `orcha.simulation` | Forecast, safe amount, earliest payment date, and independent replay. |
| `orcha.planning` | Generate, verify, rank, and explain eligible payment plans. |
| `orcha.output` / `orcha.evaluation` | CSV contract, generation, and independent output validation. |

The engines currently receive concrete image/message extractors. The evidence
provider protocol is available but does not yet connect a managed model to the
financial workflow. Image handling uses saved facts; it does not perform live OCR.

## Planned assistant workflow

```text
Question and uploaded financial evidence
    -> Python controller with bounded local Laya action selection
    -> Gemma interpretation when needed
    -> validated typed facts with source references
    -> existing deterministic engine and verification
    -> concise financial brief and evidence view
```

This workflow is planned, not implemented. The controller will validate model
arguments, enforce dependencies, handle clarification, and reject instructions
embedded in documents. Neither model will calculate affordability or approve a
payment independently. See [plan.md](../plan.md) for the full build order.
