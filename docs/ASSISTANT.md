# Gemma text workflow

Task 2 adds a Google AI Studio adapter and a Python controller around the existing
financial engine. It interprets fresh text rather than looking up saved demo facts.
Task 3 adds optional hosted Laya proposals and guarded local fallback; see
[Laya service](LAYA_SERVICE.md). An upload UI remains a later task.

## Run

From the repository root, set `GEMMA_API_KEY` in `.env` or your process environment.
The file is ignored; `.env.example` lists the non-secret settings. Existing offline
commands never load this file or initialize a model provider.

```powershell
$orchaPython = 'C:\Users\hp\AppData\Local\Programs\Python\Python313\python.exe'
& $orchaPython main.py --dataset demo/dataset --assist demo/assistant_request.json
& $orchaPython main.py --dataset demo/dataset --assist demo/assistant_missing_amount.json
& $orchaPython main.py --dataset demo/dataset --assist demo/assistant_amendment.json --brief-json
```

The first example starts from `demo_before`, whose imported events contain no
repair bill. Gemma extracts the new 12,000 INR obligation from its text, and Python
adds it to an isolated in-memory ledger. The CSV inputs are not edited. The
amendment example changes the existing scheduled bill to 15,000 INR once, rather
than adding a second obligation.

## Input and import

`--dataset` selects the existing financial CSV import. Its profile, events, FX,
and supporting records stay local. The existing loader requires its eight CSV
files; unused requests/options/images can be header-only files. Profile balances
must be reconciled to the supplied reference date.

`--assist` accepts a JSON file with:

- `user_id`: an imported profile ID.
- `as_of`: the financial reference date, not a model-generated date.
- `question`: a unique `source_id` and purchase text containing an explicit price,
  three-letter currency code, and completion date.
- `documents`: up to eight short text updates with unique IDs; use
  `related_event_id` to explicitly identify an existing scheduled debit to amend.

See the files under `demo/assistant_*.json` for complete examples. Each source is
limited to 8,000 characters and the input file to 64 KB. Explicit ISO dates are
recommended; written English dates with a year are also verified locally.

## Validation and financial authority

The provider returns a closed, versioned extraction contract. Every amount/date
has a source ID and a verbatim quote. The controller checks quote membership,
amount/currency matches, date matches, positive exact money, ownership, forecast
window, duplicate bills, and complete accounting for all supplied updates.
Conflicting totals, missing fields, unsupported changes, and suspicious instructions
route to clarification. Confidence is not a permission signal.

Only one-off unpaid debit bills and amendments to existing scheduled debits are
currently applied. Historical settled transactions cannot be rewritten. Income
changes, cancellation/settlement updates, installment terms, relative/ambiguous
dates, complex invoices with multiple totals, and image/PDF uploads require a
reconciled import or clarification in this first workflow. Nothing silently drops
an unresolved supplied update and proceeds with a recommendation.

The controller creates a fresh typed purchase request and isolated repository.
It preserves imported payment preferences and the minimum balance, asks the
existing decision engine to calculate a result, and calls the existing independent
final-row validator. This checks capacity boundaries, earliest dates, payment
contracts, and daily cash replay. The final brief uses verified engine output;
Gemma never writes financial numbers or conclusions in that brief.

Quoted text is still supporting evidence, not proof of authenticity or a guarantee
that the source itself is correct. This first workflow expects short, explicit
updates and asks for clarification rather than resolving complex documents.

## Output and failure handling

Normal output shows the brief, source facts, controller actions, and model usage.
`--brief-json` emits an `AssistantResult` with status, questions, decision, evidence,
actions, usage, and a `routing` trace. That trace distinguishes accepted Laya
proposals from deterministic fallbacks. Validation and financial verification
remain mandatory Python actions.

Exit codes: `0` complete, `2` clarification/input/configuration needed, `3` provider
unavailable. Rate limits and transient server errors have at most one retry.
Authentication failures are not retried. Truncated, refused, or malformed model
responses never yield a financial recommendation. API errors do not echo provider
bodies, input contents, credentials, or model reasoning.

## Provider settings and privacy

The adapter uses Google's documented `generateContent` endpoint, a bounded output
budget, and minimal thinking. Default model: `gemma-4-26b-a4b-it`. Model ID, key,
timeout, and output limit are configurable; the initial provider is Google.
No extra SDK dependency was needed.

Only the selected question/document texts, IDs, reference date, and home currency
are sent to Google's managed service. Account balance and transaction history
are not included in the model prompt. This is hosted Gemma, not local inference.
Google currently lists Gemma 4 as free-tier access and says free-tier content may
be used to improve products; verify your account's current terms and limits before
using personal data. [Gemma API guide](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api),
[Google pricing and data-use table](https://ai.google.dev/gemini-api/docs/pricing).

Local extraction caching is off by default. Set `GEMMA_CACHE_DIR` to opt in, for
example `.local/gemma-cache`. Keys include source content, reference state, model,
prompt/schema version, and generation settings. Cached facts are revalidated
against the source and financial rules on every run. Cache files contain source
quotes; keep them private. Original evidence caches are not overwritten.

## Verification on October 22, 2026

Live calls used only the synthetic examples:

| Scenario | Observed result | API calls in successful run | Tokens | Time |
| --- | --- | ---: | ---: | ---: |
| New 12,000 INR bill | Safe today 18,000; full laptop payment October 25 | 1 | 1,718 | 7.99 s |
| Missing bill amount | Clarification; no forecast or recommendation | 1 | 1,561 | 5.21 s |
| Existing bill amended to 15,000 | Safe today 15,000; full payment October 25 | 1 | 1,738 | 8.66 s |

Early probes encountered a Google internal error and a timeout; a later missing-
amount attempt also returned a transient error. These unsuccessful probes are
not included in the successful-run token counts above. The final configuration
uses the verified minimal-thinking setting. Live results and test logs are stored
only under `.local/task2/`; model reasoning and credentials are not stored there.

Offline tests use fake transports/providers and cover the full engine workflow,
amendments, missing/unsupported/conflicting evidence, ownership, exact money,
prompt-instruction attempts, unavailable FX, response validity, retry limits,
secret-safe errors, content-based caching, and CLI JSON output. CI needs no key.

Final checks: 144 tests passed in 20.71 seconds; lint and mypy passed; all changed
Python files passed formatting; the wheel built with the new modules. The full
repository format check also found a pre-existing extra blank line in unchanged
`tests/test_cli.py`. All 27 original dataset/cache file hashes remained unchanged,
and the credential was absent from reviewable files and the built wheel.
