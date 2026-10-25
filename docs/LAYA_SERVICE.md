# Laya on InstaCloud

October 25 production update: review recovery fixes are deployed on the existing
endpoint. See [deployment verification](DEPLOYMENT_VERIFICATION.md) for the current
image and fresh live checks; the earlier measurements below are historical.

October 23 refinement: the existing endpoint now runs the task-specific
`orcha-workflow-v1` scorer. All four live production routing stages pass. The
candidate also passed three live Gemma scenarios. See [experiments, limits and
deployment status](LAYA_REFINEMENT.md). Results below describe the original deployment.

Verified October 22, 2026. Orcha calls Laya remotely; the laptop does not install
PyTorch, load the checkpoint, or need a GPU. Python retains financial authority.

## Existing deployment

| Setting | Value |
| --- | --- |
| Project / cloud branch / compute service | `orcha` / `laya-service` / `laya` |
| Service origin | `https://prod-laya-service-laya-043265-00gf0dcghfb.compute.instacloud-edge.com` |
| Runtime | CPU, 4 shared vCPUs, 4096 MB RAM, one machine, scale to zero |
| Checkpoint | `convaiinnovations/laya-multilingual`, about 322M parameters |
| Pinned revision | `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67` |
| Observed packages | Laya 0.4.13, PyTorch 2.9.1+cpu, Transformers 4.57.6 |

This is self-managed model inference on InstaCloud compute. The free account's
existing compute allowance was used without a plan upgrade. Usage consumes cloud
credit; no fixed monthly cost or unlimited free hosting is promised. The default
cloud `main` branch has no deployed service; commands below target the isolated
branch explicitly.

## Run Orcha locally

The current ignored `.env` is configured. For a new checkout, copy `.env.example`
to `.env` and supply the Google key plus these service settings:

```dotenv
LAYA_API_URL=https://prod-laya-service-laya-043265-00gf0dcghfb.compute.instacloud-edge.com
LAYA_API_TOKEN=<private service token>
LAYA_TIMEOUT_SECONDS=8
LAYA_MIN_CONFIDENCE=0.8
```

```powershell
python main.py --dataset demo/dataset --assist demo/assistant_request.json
python main.py --dataset demo/dataset --assist demo/assistant_request.json --brief-json
```

On this machine, replace `python` with
`& 'C:\Users\hp\AppData\Local\Programs\Python\Python313\python.exe'`.
The JSON result contains `routing`, including the proposed and selected actions,
confidence, model revision, latency, and fallback reason. No routing settings
means the original deterministic flow. Offline engine commands never call Laya.

## Routing contract and limits

`POST /v1/route` requires `Authorization: Bearer <token>`. Its only input fields
are `schema_version` and `state`; state contains `interpreted`, `evidence_valid`,
`result_verified`, `issues_count`, and `document_count`. There is no question,
document text, user ID, balance, purchase amount, or transaction history. The
endpoint rejects unknown fields, impossible flag combinations, and oversized
bodies. Authentication is checked before model inference. Credentials never go
in URLs or browser code.

The allowed proposals are `interpret_request`, `ask_clarification`, `run_forecast`,
and `explain_result`. Python determines eligibility from the current stage and
accepts only an eligible proposal above the configured threshold. It always
validates evidence before forecasting and independently verifies the result
before explaining it. This makes Laya advisory: the controller already knows
the permitted next action. Confidence is a filter, not a correctness guarantee.

Wrong-stage, low-confidence, invalid, or unavailable responses use the local
action. After a network or schema failure, the remaining workflow avoids further
service calls. The default eight-second network timeout can expire during a cold
start; that request continues locally. The server runs one inference at a time;
concurrent requests receive an unavailable response and fall back.

## Actual measurements

Initial `/ready` returned HTTP 200 after a recorded **10.82-second model load**.
This measures model loading after process start, not total deployment or wake
latency. Anonymous inference returned HTTP 401; authenticated inference returned
HTTP 200 with the pinned model metadata.

Four synthetic stage probes measured **92-97 ms model inference** and
**0.89-1.57 seconds round trip** from this laptop. All four proposed
`explain_result`, at confidence **0.46-0.52**. Three proposals were ineligible;
the final explanation proposal was below threshold. None was accepted. These
are small diagnostic probes, not an accuracy benchmark. The checkpoint currently
does not justify autonomous routing, and lowering the threshold is not a fix.
Probe artifacts are ignored under `.local/laya-cloud/`.

After the final deployment, the complete fictional Gemma/Laya workflow finished
in **12.79 seconds**. It returned safe-today **INR 18,000** and full payment of
**INR 25,000 on October 25, 2026**, with all three routing decisions falling back.
Final readiness reported a 10.83-second model load. The full result is saved in
the ignored `.local/laya-cloud/full-workflow.json`.

Offline tests cover accepted proposals, wrong stages, low confidence, malformed
responses, downtime, authentication, restricted state, cancelled-bill negation,
and preservation of mandatory validation and verification. Existing assistant
tests continue to cover conflicting financial evidence.

## Deploy and operate

The dedicated build context is `services/laya/`; its allowlist excludes `.env`,
datasets, and local files. Dependencies and the checkpoint are pinned. Model
files are downloaded during the remote build and loaded offline at runtime.
The container runs as a non-root user. No local Docker daemon is required for
the InstaCloud source build.

After authenticating and linking the existing project with `insta`:

```powershell
insta secrets set LAYA_API_TOKEN --branch laya-service --service compute/laya
insta deploy services/laya --group laya --branch laya-service --port 8080
insta compute logs laya --branch laya-service --limit 50
insta compute metrics laya --branch laya-service --json
```

The secret command accepts a private value through its prompt/stdin. Use the
same value in local `.env`; never add it to command arguments or source control.
`GET /health` is process liveness. `GET /ready` checks that the model actually
loaded and reports the checkpoint/package versions. Verify `/ready` and an
authenticated inference after deployment. A successful image build alone does
not establish readiness.

## Decisions and tradeoffs

- CPU and the smaller multilingual checkpoint fit the existing 4 GB cloud limit;
  inference stays off the laptop, at the cost of network latency and cloud usage.
- Scale to zero limits idle usage, at the cost of first-request wake/load delays.
- A separate authenticated service keeps heavyweight dependencies out of Orcha
  and sends only workflow state to InstaCloud.
- Strict eligibility and fallback keep the verified workflow working despite
  poor model predictions, at the cost of limited useful routing autonomy.
- The upload interface remains task 4. Model quality improvements require their
  own evidence before granting Laya more control.

Upstream implementation and limitations: [Laya](https://github.com/NandhaKishorM/laya).
Checkpoint and license: [Laya multilingual](https://huggingface.co/convaiinnovations/laya-multilingual).
