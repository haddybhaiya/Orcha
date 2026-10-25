# Public Orcha demo

Deployed October 25, 2026:
https://prod-web-demo-web-6a2d0d-00h16he17ck.compute.instacloud-edge.com

Open the link, choose **A laptop & a new bill**, and select **Find a steady way
forward**. No sign-up, login, or saved customer history is required. The interface
also accepts fresh fictional purchase questions and text bills.

## Challenge scope

The [Week 3 official rules](https://dev.to/page/hacktoberfest-week3-2026-10-19-contest-rules)
require a new project with open-source AI at its core, relevance to the Slow and
Steady theme, an explanation of open innovation, a DEV submission using the
template/tag, a demo link or video, and a code link/embed. They do not require a
customer account system or persistent user memory. Auth0 and memory-related
integrations are optional partner categories on the
[challenge page](https://dev.to/challenges/hacktoberfest-week3-2026-10-19).

The user requested the public demo deployment; demo recording and submission
writing remain deferred. This deployment does not publish a challenge submission
or assert eligibility for work completed before the challenge window.

## Hosting and privacy

- InstaCloud project `orcha`, isolated branch `web-demo`, compute service `web`.
- Final deployed image: `728301184821.dkr.ecr.us-east-1.amazonaws.com/insta-compute-builds-us-east-1@sha256:a56dcc9f6cfe37c20088b05e2ce6328c7cf672952e42f7d2691e773e4e1816b1`.
- The existing Laya service remains on `laya-service`; it was not duplicated.
- Python/FastAPI runs in one container/process on port 8080, bound to `0.0.0.0`.
- The image contains source, static assets, and the fictional packaged demo. The
  allowlisted Docker context excludes `.env`, `.local`, the original dataset,
  credentials, evidence caches, Git metadata, and the Laya model service.
- Gemma and Laya credentials are scoped to `web-demo/web` as runtime secrets.
  Browser code calls Orcha's endpoints and never receives these credentials.
- Public CSV imports and workspace reset are rejected server-side. Visitors cannot
  replace the common fictional dataset. The local app still supports CSV imports.
- Selected questions and text updates are sent to Google for Gemma interpretation.
  Financial calculations run on the hosted Python server; Laya receives flags and
  counts. The page labels this explicitly. Use fictional data on the public demo.
- There is no database or durable user history. The existing bounded interpreter
  cache holds up to 32 text extractions in process memory until eviction/restart.
  Forecast results are separately retained for ten minutes, at most 16 results.

## Request flow and limits

Public `POST /api/assist` validates the request and returns HTTP 202 with a random,
unguessable job identifier. The browser polls `/api/jobs/{identifier}` until the
result is ready. This keeps a slow Gemma call or Laya cold start from exceeding the
hosting gateway's request deadline. The identifier is needed to retrieve a result;
there is no job-list endpoint. Lost/expired jobs can be rerun.

The public demo supports one active forecast and 60 submissions per rolling hour
across all visitors. Limits and jobs are in memory and reset on a process restart;
this is a single-process demo, not distributed multi-user infrastructure. A busy
demo returns HTTP 409, and quota exhaustion returns HTTP 429 with `Retry-After`.
Background results expire and may be evicted when their capacity is reached.

The exact HTTPS origin and host are configured with `ORCHA_PUBLIC_ORIGIN`. Origin
validation uses this explicit value instead of trusting incoming proxy headers.
Existing CSRF-token, payload-limit, no-store, CSP, and sanitized-error protections
remain active. Scale to zero stays enabled; the first page or forecast can be slow.

## Verification

The offline suite passes **229 tests**; Ruff, mypy, and JavaScript syntax checks
pass. Tests cover public host/origin/token enforcement, immutable demo data,
background result retrieval, sanitized failures, expiration, bounded result count,
hourly quota and recovery, and rejection of arbitrary datasets in public mode.

Live HTTPS checks verified the following results, with accepted Laya routing at
every stage:

| Scenario | Result | Safe today | Observed elapsed |
| --- | --- | --- | --- |
| New repair bill | Complete; pay INR 25,000 on October 25 | INR 18,000 | 9.80 seconds |
| Missing amount | Needs clarification | No recommendation | 7.53 seconds |
| Bill amendment | Complete; pay INR 25,000 on October 25 | INR 15,000 | 11.09 seconds |

Submission returned HTTP 202 in 0.60–1.57 seconds, followed by successful polling.
Both complete results contained the verified 90-day timeline. Blocked import/reset
requests left the synthetic workspace unchanged. Chrome also completed the new-bill
flow through the actual UI and displayed the expected result. These are observed
synthetic examples, not latency guarantees or general model-accuracy claims.

## Redeploy

From the repository root, after the service's runtime secrets are configured:

```powershell
insta --agent build . --port 8080
insta --agent deploy . --branch web-demo --group web --port 8080
```

The root Dockerfile serves the public demo. `services/laya/Dockerfile` remains the
independent Laya image. Local use stays `python web.py`. Model credentials must
remain server-side; do not put them in browser files or Docker build arguments.
