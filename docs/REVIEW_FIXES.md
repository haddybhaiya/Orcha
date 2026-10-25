# Review corrections

October 25, 2026. Repository fixes for the 16 findings in the read-only review.
The original dataset and model adapter weights were not changed. No cloud
deployment was performed for this patch; restart the local app after updating.
The Laya service lifecycle changes take effect after rebuilding and redeploying
`services/laya`. The currently deployed image remains the earlier verified image.

| Finding | Correction |
| --- | --- |
| Demo CSVs ignored | Ignore only `/dataset/`; the eight fictional demo CSVs can now be committed. |
| Negative event amounts | Reject non-finite and negative event amounts, normalized amounts and reduction limits at the shared repository boundary. Validate financing and FX values too. |
| Duplicate records | Reject duplicate request, event, message, image and payment-option IDs; reject duplicate CSV profile IDs before indexing. |
| Installment underpayment | Sum payments and require agreement with both the supplied total and purchase price plus stated fee. |
| Negated salary | Unconfirmed/conditional evidence does not introduce confirmed salary; first-salary recognition requires positive confirmation language. |
| Foreign salary | Convert evidence-derived salary with an exact dated FX rate; missing FX blocks the calculation. |
| Cross-employer amendments | A linked message applies only to a recurrence stream containing its linked event. |
| Overdue scheduled debits | Reserve outstanding scheduled debits immediately until their status changes. |
| Settled debits today | Treat both settled debits and credits through the reference date as already included in the starting balance. |
| Stale image facts | Bind cached amounts to SHA-256 of the reviewed image; replaced or missing images fail validation. Existing cache facts are unchanged, with source hashes added. |
| Large planning search | Cap spending combinations at 2,000 and candidates at 5,000; check an eight-second cooperative deadline between candidate replays. Exhaustion returns clarification, never a partial recommendation. |
| Wheel portability | Ship synthetic CSVs and examples in `orcha.demo`; default web startup, reset and template generation use packaged resources. A regression check keeps checkout examples synchronized. |
| Private-data test dependency | Public CLI tests use the demo; optional original-dataset checks skip when that dataset is absent. Add an offline CI workflow. |
| Infrastructure cold start | Retry readiness after transient connection timeouts and HTTP 502/503/504 within the existing startup deadline. Authentication and failed-model responses fail promptly. |
| Failed model load | Return unhealthy status and exit with code 1 after failed initialization, allowing the deployment supervisor to restart the process. |
| Settings reload | Read `.env` per request without polluting process environment; explicit process settings take precedence. Provider identity includes hashed credentials, timeout and cache directory. |

## Decisions and limits

Money direction is represented by `debit`/`credit`; values must be non-negative.
An overdue scheduled debit is still unpaid, while a settled event on the reference
date is already in the imported balance. Importers must supply a balance consistent
with that convention.

Exact spending-plan search remains exhaustive within its budget. Larger searches
request narrower input. The deadline is cooperative: an individual replay finishes
before the next deadline check. It is not a hard process-level CPU timeout.

Image hashes prevent reuse against changed source bytes. They do not establish the
truth of a receipt's contents or independently authenticate the issuer. New image
extractions must record the source hash alongside the reviewed facts.

The original private dataset remains optional and ignored. The root demo CSVs and
the packaged copy are fictional, small and intended for redistribution. Commit
both copies with these changes; the consistency test detects divergence.

## Verification

Observed results: **217 tests passed** with the original dataset installed;
**203 passed, 14 skipped** in a clean source copy without it. Ruff passes, and
mypy passes across the source and changed test modules.

Regression tests reproduce the reported financial failures and cover corrected
results or rejection. Routing tests cover infrastructure wake errors, deadlines,
authentication, failed checkpoints and failed-process lifecycle behavior. Settings
tests cover reload, process precedence and provider replacement without exposing keys.

The test fixture isolates local `.env` and model-related process variables, so offline
checks cannot discover a developer's real credentials. No live model calls are
required. The wheel was built and its dashboard, examples, CSV template and engine
result verified from an extracted wheel outside the checkout. A clean source copy
without the private dataset or `.env` also runs the public suite.

Run from the repository root:

```powershell
python -m pytest --basetemp .local/pytest-review
python -m ruff check .
python -m mypy src
```

On Windows, create `.local` first if it does not exist. The optional private checks
run automatically when the original dataset is installed at `dataset/` or
`../dataset/`; they are reported as skipped otherwise.
