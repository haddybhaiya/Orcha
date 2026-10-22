# Orcha validation

Orcha uses deterministic financial checks to verify its recommendations. The
current delivery gate is a working assistant workflow with documented evidence,
not a large scoring benchmark.

## Financial checks

- Money uses Decimal values; FX rates match the applicable date and direction.
- Safe amounts preserve the minimum balance throughout the 90-day forecast.
- Optional spending changes do not increase the reported baseline safe amount.
- Earliest full-payment dates are checked with independent replay.
- Payment plans respect available options, preferences, amounts, and dates.
- Spending changes reference eligible recurring events and respect allowed minima.
- Explanations use verified results and do not introduce unsupported numbers.
- Generated CSVs satisfy the financial output contract and validate on reload.

## Offline baseline

The [synthetic demo](../demo/README.md) works without the original dataset, evidence
caches, API keys, or paid calls. Its expected decision fields are recorded in
`demo/expected_results.json`. See [BASELINE.md](BASELINE.md) for measured check
results, missing original resources, and reproducible commands.

The existing tests remain in place. Original-data integrations require the absent
input CSVs and images. Reports under `evaluation/` are historical diagnostics;
their sample scores and 250-row run are not results from this checkout.

## Assistant workflow checks to add

When the Gemma controller is implemented, use focused mocked-provider and boundary
checks for typed extraction, missing/conflicting facts, untrusted input, provider
errors, and the complete workflow. CI must not require credentials or paid calls.
Track correctness of demonstrated cases, model calls, latency, and cost where useful.

## Delivery evidence

Provide setup instructions, a short demo using synthetic data, and a local
submission draft under the active brief. Historical archive formats and transcript
requirements from the earlier prototype are not current delivery requirements.
