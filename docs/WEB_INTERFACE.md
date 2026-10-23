# Orcha local workspace

Run from the repository root with Python 3.11 or later:

```powershell
python -m pip install -e ".[web,dev]"
python web.py
```

Open http://127.0.0.1:8000. On this Windows machine, the interpreter is
`C:\Users\hp\AppData\Local\Programs\Python\Python313\python.exe`.
Use `--port 8001` if needed, or `--dataset path/to/csv-folder` for existing inputs.
The installed `orcha-web` command is equivalent. Keep the source checkout and
its `demo` folder available; the template and reset actions use those files.

## User flow

1. Start with the clearly labelled synthetic demo, or open **Import finances**.
2. Download and extract the sample CSV bundle. Replace its records while retaining
   headers, then select all eight CSV files together. This is Orcha's CSV format,
   not an automatic bank-statement importer. Header-only files are supported.
3. Select a financial profile and the date its balance was reconciled.
4. Ask about a purchase with its price, currency, and deadline. Paste an unpaid
   bill or upload a UTF-8 `.txt` file. To amend a scheduled bill, select it from
   the update's dropdown.
5. Run the planner. Read the verified amount, payment date and plan. Expand source
   evidence and the workflow trace to inspect Gemma usage and Laya/fallback choices.
6. Edit incomplete facts and rerun if clarification is requested.

The overview and activity table describe imported finances. A completed result
updates the chart with the new bills, **before the proposed purchase**. The
purchase plan is shown separately. The 30/90-day chart is not a post-payment
projection. Draft edits clear the old recommendation to avoid stale results.
Text updates are hypothetical for each request and do not permanently amend CSVs.

## Data and deployment boundaries

- The server binds to `127.0.0.1` for one local user. Tabs share one workspace.
  This is not a public, authenticated, multi-user service.
- Imports are parsed through a temporary directory, which is deleted after
  loading. The active dataset and interpretation cache remain in process memory;
  reset/restart clears them. Source CSVs are not modified.
- Questions, text updates, source identifiers, reference date and currency go
  to Google's configured Gemma endpoint. Laya receives workflow flags only.
  Profiles, transaction history, calculations and independent verification stay
  in Python locally. Keys are read server-side from the ignored `.env`.
- The 32-entry interpretation cache keys include content, model, prompt version
  and output-token settings. Cache hits report zero new Gemma calls; financial
  calculation and verification still run again.
- CSV bundles have an 8 MB request cap; the browser limits individual files to
  5 MB. At most eight text updates, each up to 8,000 characters, are supported.
  Uploaded receipt images/PDFs, bank sync, income-change interpretation and durable
  account history are outside this version.
- Same-origin checks, a per-process request token, trusted local hosts, bounded
  payloads and serialized operations protect the local HTTP boundary. API errors
  avoid echoing raw financial inputs. These controls do not replace production
  authentication or per-user storage.

## Design decisions

Original HTML/CSS and small vanilla JavaScript modules keep the interface runnable
without a Node build or component framework. FastAPI connects it directly to the
existing Python controller. This reduces setup, at the cost of manually maintained
UI state and no reusable framework component system yet.

Self-hosted Manrope and Newsreader provide readable controls and editorial headings.
Both use SIL Open Font License 1.1; licenses and provenance ship under
`src/orcha/web/static/fonts` and `static/ASSETS.md`. The chart uses original SVG,
with an accessible text summary, native form controls and reduced-motion support.

## Verification

Task 4 adds 15 API tests, bringing the offline suite to 184 tests. Tests cover
real engine results through a stubbed interpreter, cache invalidation, import
rollback, reset, template contents, origin/host/token checks and sanitized errors.
Run `python -m pytest --basetemp .local/pytest-web` if Windows denies access to its
default pytest temporary directory. Ruff and mypy checks also pass.

Chrome checks verified the desktop and 390px mobile layouts and live Gemma flows:
new repair bill -> INR 18,000 safe today; missing amount -> clarification;
amended repair bill -> INR 15,000 safe today. Both complete examples recommend
paying INR 25,000 on October 25, 2026. Hosted Laya was unavailable in this check;
the trace correctly showed local fallback. This is not evidence of reliable
Laya predictions.

Automated browser file selection was blocked by the extension's file-URL
permission. The import picker and guide were checked visually; upload parsing,
validation and rollback were verified through API tests. A successful automated
file-chooser round trip is not claimed.
