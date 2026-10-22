# HF26 task 1 baseline

Verified October 21, 2026 in `C:\Users\hp\Desktop\PAPERS\mlh\Orcha`.
The active brief is `plan.md`; earlier engine reports remain historical.
Package references use the current Orcha namespace. This report records task 1
before the naming cleanup; the unchanged-source hash result below applies to that
baseline task, not to the later authorized rename.

## Package and execution flow

The package root is this directory, containing `pyproject.toml`, `main.py`, and
`src/orcha/`. There is no additional extracted `code/` directory to enter.
`AGENTS.md` points to `plan.md`. Source layout and existing tests were preserved.

| Component | Role |
| --- | --- |
| `main.py` / `cli.py` | Add `src/` to the import path and expose dataset, ledger, forecast, decision, and output commands. |
| `config.py` | Select dataset/output paths from CLI or environment. Default dataset paths are `dataset/` and `../dataset/`. |
| `loaders.py` / `models.py` / `repository.py` | Read CSV records into typed dates and Decimal amounts, normalize FX, and index requests and source records. |
| `evidence/provider.py` | Define `EvidenceProvider` and a local implementation backed by saved image facts and a limited message parser. |
| `ledger/` | Resolve lifecycle states and evidence amendments; infer recurring cash flows. |
| `simulation/` | Forecast 90 days and calculate the safe amount and earliest full-payment date. |
| `planning/` | Generate payment candidates, replay safety, rank valid candidates, and produce explanations. |
| `evaluation.py` / `simulation/independent.py` | Check output contracts, independently replay payment plans, and verify capacity boundaries and earliest dates. |
| `tests/` | Existing offline unit/scenario checks plus integrations tied to the missing original dataset. |

## Environment actually used

The `py` launcher is present but reports no installed Python. The working command
is `& 'C:\Users\hp\AppData\Local\Programs\Python\Python313\python.exe'`.

| Dependency | Installed version |
| --- | --- |
| Python | 3.13.7, Windows x64 |
| pandas | 2.3.3 |
| pydantic | 2.12.5 |
| python-dotenv | 1.2.2 |
| pytest | 9.0.2 |
| ruff | 0.16.3 |
| mypy | 2.3.1 |

No packages were installed or upgraded. These are observed versions, not a new
dependency lock. The project declares Python >=3.11.

## Existing checks

| Check | Actual result |
| --- | --- |
| Existing full pytest suite with isolated temp/cache paths | 89 passed, 17 failed, 1 skipped in 2.62 seconds. |
| `ruff check .` | Passed. |
| `ruff format --check .` | Passed; 71 files already formatted. |
| `mypy src tests main.py` with a local cache | Passed; no issues in 55 source files. |

All 17 remaining failures require the absent original dataset or its image files.
The skipped planning integration explicitly reports that the dataset is absent.
Passing checks cover money/FX, typed models, synthetic loaders/repository,
evidence parsing, lifecycle/recurrence, simulation, planning, invariants,
independent replay, output serialization, and imports/configuration. These results
do not establish correctness on the original dataset.

An initial default pytest invocation also hit six Windows temporary-directory
permission errors. Rerunning with a workspace-local `--basetemp` removed those
errors. Imported bytecode can retain paths from the previous checkout; the final
run used a separate bytecode prefix and disabled unrelated auto-loaded plugins.
No existing tests or source files were changed to alter their outcomes.

Reproduce from the root (choose a fresh basetemp directory for each run):

```powershell
$baselinePython = 'C:\Users\hp\AppData\Local\Programs\Python\Python313\python.exe'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $baselinePython -B -X pycache_prefix=.local/isolated-pycache -m pytest --tb=short -ra -p no:cacheprovider --basetemp=.local/pytest-review
& $baselinePython -m ruff check .
& $baselinePython -m ruff format --check .
& $baselinePython -B -X pycache_prefix=.local/isolated-pycache -m mypy --cache-dir .local/mypy src tests main.py
```

Raw verification output is retained locally under `.local/baseline/` and ignored
by Git. `.gitignore` also excludes virtual environments, bytecode, tool caches,
and `.env` secrets, while allowing `.env.example`.

## Resources present and missing

- Neither `dataset/` nor `../dataset/` exists in this checkout. The original
  requests, profiles, events, FX tables, payment options, message/image metadata,
  sample labels, and receipt PNG files are unavailable at those expected paths.
- `cache/image_evidence.json` and `cache/message_evidence.json` are present;
  existing checks confirm 16 saved image facts and 215 message records. Their
  presence does not restore the original input records or image assets.
- Image extraction is saved-fact lookup, not OCR or a live vision model. Blank
  event amounts require matching image metadata, a matching saved fact, and the
  source image when using a filesystem-backed dataset; missing evidence fails.
- Fresh messages use narrow deterministic patterns. A new arbitrary bill message
  does not create a ledger event. Existing keyword sanitization is not a complete
  trust boundary for a future LLM controller.
- The provider protocol exists, but `BaselineEngine`, `DecisionEngine`, and the
  ledger resolver currently receive concrete image/message extractors. Adding a
  Gemma provider alone will not wire it into the financial workflow.
- Default caches are resolved relative to the working directory, and provider
  lookups use record IDs rather than content/model/prompt versions. This needs
  deliberate handling for fresh evidence in task 2.
- `.env.example` documents offline engine settings. It does not establish Gemma
  integration. There is no implemented Gemma API adapter, Laya routing, or upload
  interface in this baseline. No model download or paid API call was performed.

## New self-contained demo

See `demo/README.md`. Eight schema-compatible CSVs contain entirely fictional
inputs with distinct `demo_` IDs. Two profiles represent the same finances before
and after a one-off repair bill, avoiding cross-contamination between scenarios.
There are no copied financial input files or images to redistribute in this bundle.
Original caches and inputs were not modified or included in it.

Observed results for a 25,000 INR laptop:

| Scenario | Safe amount today | Recommendation | Full-payment date |
| --- | ---: | --- | --- |
| Before repair bill | 25,000 | Full payment today | 2026-10-21 |
| After 12,000 repair bill due October 23 | 18,000 | Wait, then full payment | 2026-10-25 |

Dataset validation, smoke, data audit, both decision commands, generation, and
fresh serialized-output validation all passed. Generation checks independent
replay, safe-amount boundaries, earliest dates, and payment-plan contracts for
both rows. The repair amount is explicitly supplied as an event; this is not a
claim of new message or document interpretation.

A second smoke/generate/validate run from an empty temporary working directory
also passed without access to the imported evidence caches. Both generated rows
matched `demo/expected_results.json`. Input CSV hashes stayed unchanged, and all
56 recorded imported Python source/test and JSON cache hashes matched the
pre-change snapshot. Git ignore checks confirmed local outputs, bytecode, secrets,
and virtual environments are excluded. Nothing was staged or committed.

## Handoff to task 2

Keep the deterministic engine and its useful checks. Add one controller path
that interprets a fresh question/update with Gemma, validates typed facts and
source links, requests clarification for material gaps/conflicts, and supplies
the validated inputs to the existing engine. Explain only verified outputs.
Recheck provider availability and parameters before implementing paid calls.
Complete that workflow before introducing Laya routing or optional integrations.
