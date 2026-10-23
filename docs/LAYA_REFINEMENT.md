# Laya workflow refinement

October 23, 2026. The refined image was verified on the isolated `laya-refinement`
branch, then deployed to the existing `laya-service` endpoint with user approval.
The app's `.env` URL and credentials have not changed. Production readiness verifies
the policy version and adapter hash, and all four live routing stages are accepted.

The deployed image is pinned to
`sha256:987e77b5957f91b2466be1360410e3aa86d6f9d4e8052d2f6067906034d3d680`.
Restart the local app after picking up this code so it understands the new policy
metadata and uses the bounded cold-start handling.

The production Gemma purchase-and-bill smoke test completed in 12.86 seconds,
retaining INR 18,000 safe today and the October 25 payment date. All three routing
points used accepted Laya proposals. The separate experiment service was stopped
after verification; the existing `laya-service` endpoint remains active.

## Experiments

Three pinned checkpoints were screened against the same synthetic workflow states:

| Checkpoint | Original JSON, correct / 8 | Best of the first four prompt variants |
| --- | --- | --- |
| Multilingual, 322M | 2 / 8 | 4 / 8 |
| English, 421M | 2 / 8 | 4 / 8 |
| Typed-decisions, 421M | 3 / 8 | 4 / 8 |

The larger checkpoints did not justify their memory for this task. English
descriptions, neutral labels, option rotation and status-classification prompts
were insufficient. Token diagnostics confirmed no truncation of the original
question/state. Language selection and context length alone do not explain the
failure.

Scorer adaptations using the original inputs improved some cases but remained
unstable across counts. Document count does not affect the next action, and only
the presence of blocking issues matters. The final model input therefore drops
document count and maps positive issue counts to one. It preserves the progress
flags without computing or inserting an action label.

Only **768 weights** in Laya's final linear option scorer were fine-tuned. The
encoder, transformer decision head, preceding scoring layers and final bias are
frozen. Cross-entropy, class weighting, seed 23 and bounded LBFGS optimization
produce a **3,152-byte** safetensors adapter, SHA-256:

`5a19737961a8d1be868010a86dea9a1c574e140a1304a241b5b2d63b195120ab`

The service verifies that hash before loading; it never uses pickle. A failed
adapter load leaves readiness false. Proposals and readiness identify
`orcha-workflow-v1`; readiness also exposes the adapter hash.

## Results and limits

- Fit: 18 / 18; validation count variations: 10 / 10; further variations: 24 / 24.
  Those raw count combinations were withheld from fitting, but normalization
  reduces them to the same four trained inputs. This is not unseen semantic
  generalization.
- An exhaustive offline check covers all **927** controller-emitted combinations:
  nine document counts, three clear progress stages and 100 blocked issue counts.
  They reduce to four model inputs, each associated with one expected action.
- Authenticated live inference through Orcha's unchanged 0.8 gate accepts all
  four Laya selections: interpret, clarify, forecast and explain.
- All three live Gemma workflows pass with the candidate: the new repair bill
  leaves INR 18,000 safe today; the missing amount produces clarification; the
  amended bill leaves INR 15,000 safe today. Both purchase plans pay on October 25.
  All eight routing points use accepted Laya proposals.
- Scores round to 1.0 for these specialized inputs. They are not calibrated
  real-world correctness probabilities or evidence of general financial reasoning.
  The threshold was not lowered and scores were not overwritten.
- Unsupported progress states are rejected. Python still enforces eligibility,
  validates evidence, computes financial results and independently verifies plans.
  The fallback remains available.

The controller currently permits one next action at each stage. This work makes
the model agree with those dependencies; it does not grant new financial authority.

See [machine-readable results](../experiments/laya/results.json). Detailed raw
artifacts remain ignored under `.local/laya-refinement/`.

## Cold-start handling

After an explicit inference `503 {"error":"model_unavailable"}`, the client polls
`/ready` while it reports `loading`, then retries inference once ready. The total
budget defaults to 45 seconds (`LAYA_STARTUP_TIMEOUT_SECONDS`, maximum 60).
Individual network calls remain bounded by `LAYA_TIMEOUT_SECONDS`. Authentication
failures, failed loads and unexpected responses do not enter a readiness loop;
budget expiry uses the usual fallback.

A real candidate restart exercised this path: 12 readiness checks, 28.53 seconds
to an accepted model result. Production reported an 11.08-second checkpoint load
on its deployment; this excludes infrastructure wake time and network latency.

## Reproduction

Scripts under [experiments/laya](../experiments/laya/) are cloud-only workers:
`screen_prompts.py` compares four prompt formats; `screen_status.py` checks status
questions; `fit_scorer.py` reproduces the normalized final-scorer adaptation and
emits the artifact as base64 alongside its metrics. Heavy imports occur only when
the scripts execute. They are not required by the application or offline tests.

From the repo root, with the isolated cloud service started:

```powershell
$source = [IO.File]::ReadAllText((Join-Path (Get-Location) 'experiments/laya/fit_scorer.py'))
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($source))
$payload = "import base64;exec(base64.b64decode('$encoded'))"
insta --agent compute exec laya --branch laya-refinement --timeout 180 --json -- python -c $payload
```

The worker loads the base checkpoint without applying the adapter; fitting does
not modify the served model. Comparisons used English and typed-decisions from
`convaiinnovations/laya` revision `7b928d828b7b0e022f929d9bd2e44165aa270148`.
Multilingual uses `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67`. Screening alternatives
requires preparing their directories in the isolated container and passing the
path with `--model`. One experiment model was loaded at a time, within the 4 GB cap.

Different hardware/software can change bytes or scores. A replacement adapter
needs a new checksum, policy version and repeat verification. The offline suite
passes **194 tests**; lint and type checks pass. No financial data was used for fitting.

References: [official confidence documentation](https://github.com/NandhaKishorM/laya#confidence-and-abstention)
and the [multilingual model card](https://huggingface.co/convaiinnovations/laya-multilingual#limits).
