# Production deployment verification

October 25, 2026. The user authorized deployment, live checks, and a commit/push
with CI verification. Demo recording and submission writing remain deferred.

## Deployed service

- Existing InstaCloud project `orcha`, branch `laya-service`, compute service `laya`.
- URL: https://prod-laya-service-laya-043265-00gf0dcghfb.compute.instacloud-edge.com
- Image: `728301184821.dkr.ecr.us-east-1.amazonaws.com/insta-compute-builds-us-east-1@sha256:c55f895b2e98da7331767222d70d4e656250b16fd98f2ede681cf40b7372cd1a`.
- Workflow policy: `orcha-workflow-v1`; adapter SHA-256:
  `5a19737961a8d1be868010a86dea9a1c574e140a1304a241b5b2d63b195120ab`.
- The local application and financial engine remain local. No public multi-user
  web deployment was performed. Existing service URL and credentials are unchanged.

The image was built and deployed to `laya-refinement` first. Its four routing
stages and three fresh Gemma scenarios passed. That exact image digest was then
promoted to production, avoiding a second build. The isolated service was stopped
after promotion and confirmed suspended with desired state stopped.

## Production live checks

All four routing stages returned accepted Laya proposals. Readiness verified the
policy and adapter hash. Fresh, uncached Google Gemma requests then verified:

| Synthetic scenario | Result | Safe today | Payment plan | Elapsed |
| --- | --- | --- | --- | --- |
| Laptop and new repair bill | Complete | INR 18,000 | INR 25,000 on October 25 | 11.24 seconds |
| Bill missing its amount | Needs clarification | No recommendation | No plan | 7.63 seconds |
| Repair-bill amendment | Complete | INR 15,000 | INR 25,000 on October 25 | 12.30 seconds |

All eight routing points across those scenarios used accepted Laya proposals.
Complete scenarios included a 90-day timeline and passed the financial engine's
independent result verification. The full production check took 39.77 seconds,
including its initial four routing-stage calls. Timings are observations, not an SLA.

Only fictional demo inputs were sent to Gemma. Laya received workflow flags and
counts. Credentials and raw provider payloads were not printed or committed.

A controlled production restart verified the cold-start path separately. The probe
observed `/ready` return HTTP 503 with `status=loading`, then the real client waited
and obtained an accepted Laya route. The check completed in 21.66 seconds and the
restart command succeeded. This establishes recovery after an actual model reload,
not only the mocked timeout tests.

## Source and offline checks

The full original-data suite passes 217 tests. Ruff and mypy pass locally.
The source before this release patch is commit
`a144d7b2388e779f0aeedcec4149096004e0da65` on the user's `dply` branch.

That commit's GitHub Actions tests and Ruff passed, but mypy failed because the
`dev` dependency group omitted `uvicorn`. The server happened to be installed
locally, hiding the missing dependency. This release adds the same existing
`uvicorn>=0.30,<1` constraint to `dev`, so a clean CI install has the dependency
required to type-check the web entry point.

The adapter and checkpoint are unchanged. These checks establish the bounded
workflow's behavior, not general model accuracy or calibrated confidence.
