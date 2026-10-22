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
| `orcha.evidence` | Hosted Gemma structured text extraction, saved image facts, and local message parsing. |
| `orcha.assistant` | Source validation, clarification, isolated engine requests, independent verification, and briefs. |
| `orcha.ledger` | Lifecycle resolution, amendments, recurrence, and source links. |
| `orcha.simulation` | Forecast, safe amount, earliest payment date, and independent replay. |
| `orcha.planning` | Generate, verify, rank, and explain eligible payment plans. |
| `orcha.output` / `orcha.evaluation` | CSV contract, generation, and independent output validation. |

The original engine still receives concrete image/message extractors. A separate
`StructuredEvidenceProvider` protocol handles fresh questions and text updates;
the Google adapter implements it. The controller validates its output and creates
an isolated repository rather than letting the model invoke financial tools.
Image handling remains saved-fact lookup, not live OCR.

## Current text assistant workflow

```text
Imported local profile/history + fresh question and text updates
    -> Gemma interprets selected source text only
    -> Python validates typed facts, quotes, ownership, and completeness
    -> isolated request and ledger amendments
    -> existing deterministic engine
    -> independent output verification
    -> financial brief, source facts, and action trace
```

The explicit `--assist` command loads model configuration; existing offline CLI
commands do not. Provider errors and unresolved facts produce no recommendation.
The model does not calculate affordability or write financial conclusions.
See [ASSISTANT.md](ASSISTANT.md) for current input limits and validation behavior.

## Hosted Laya routing

The local controller sends five workflow flags/counts to an authenticated Laya
service on InstaCloud. No question, document text, identity, amount, or financial
history goes to that service. Google still receives the selected text for Gemma.

Laya proposes `interpret_request`, `ask_clarification`, `run_forecast`, or
`explain_result`. Python accepts a proposal only when it matches the eligible
stage and meets the confidence threshold. Validation and independent financial
verification are mandatory Python operations. Every proposal/fallback is traced.
The controller already determines eligibility, so this is advisory routing with
limited model autonomy. Live checkpoint predictions are currently unreliable;
the deterministic path preserves the working Gemma flow.

See [LAYA_SERVICE.md](LAYA_SERVICE.md) for deployment and measured limits. The
upload/question/result interface remains the next task.
