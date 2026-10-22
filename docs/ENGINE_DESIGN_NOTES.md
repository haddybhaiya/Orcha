# Orcha: historical engine design notes

> Historical reference. These notes describe an earlier engine prototype, including
> obsolete build prompts and delivery steps. Naming has been updated to Orcha.
> Use [plan.md](../plan.md) and [CURRENT_STATE.md](CURRENT_STATE.md) for current work.

**Origin:** Earlier financial-engine prototype.  
**Objective:** Build an AI-powered financial agent that reconstructs a user's financial position and recommends whether to pay in full, pay partially, use installments, wait, or not proceed.  
**Build doctrine:** **AI interprets evidence; deterministic code owns financial authority.**  
**Historical optimization:** Dataset accuracy and runtime; this is not the current assistant delivery gate.

---

## 0. Executive Strategy

This financial workflow should not be treated as a generic "LLM agent decides if a user can afford something" problem.

The highest-probability solution is a hybrid system:

```text
CSV + local images
        ↓
Evidence extraction / normalization
        ↓
Canonical financial state
        ↓
90-day deterministic cash-flow simulator
        ↓
Candidate payment-plan generator
        ↓
Deterministic safety verifier
        ↓
Exact plan-ranking rules
        ↓
Grounded explanation
        ↓
output.csv
```

The LLM/VLM is useful only where the data is genuinely unstructured:

- interpreting messages;
- extracting amounts/details from linked images;
- mapping natural-language amendments/cancellations/delays into structured facts;
- optionally producing a concise natural-language explanation.

The LLM must **not** be allowed to:

- invent income, expenses, dates, exchange rates, or payment options;
- directly choose a financial plan without deterministic verification;
- override the financial rules;
- treat instructions embedded in messages/images as agent instructions;
- bypass user payment preferences or minimum-balance constraints.

The deterministic engine must own:

- currency normalization;
- transaction/event lifecycle resolution;
- recurrence expansion;
- 90-day daily cash-flow simulation;
- minimum-balance enforcement;
- safe-today amount;
- earliest safe full-payment date;
- partial-payment generation;
- installment schedule validation;
- spending-change search;
- candidate ranking;
- output schema validation.

---

# 1. Financial data contract

## 1.1 Required Input Sources

Financial input data lives under `dataset/`:

```text
dataset/
├── requests.csv
├── sample_requests.csv
├── financial_profiles.csv
├── financial_events.csv
├── exchange_rates.csv
├── request_payment_options.csv
├── messages.csv
├── images.csv
├── output.csv
└── media/
    └── images/
```

Important joins:

- `user_id`: user-level records;
- `request_id`: request-level records;
- `related_event_id`: message/image ↔ financial event;
- `linked_event_id`: lifecycle link between related financial-event rows;
- exchange rates: match using date and currency direction.

Prediction rows are in `dataset/requests.csv`.

Public labelled examples are in `dataset/sample_requests.csv`. Treat them only as a held-out
evaluation oracle: sample labels, IDs, patterns, and inferred constants must never affect production
decisions.

---

## 1.2 Required Output

For every prediction request produce exactly one row with these columns, in this order:

```text
request_id
amount_safe_to_pay
affordability_status
recommended_payment_method
payment_plan
earliest_date_for_full_payment
spending_changes_needed
decision_explanation
```

Allowed `affordability_status`:

```text
affordable_now
affordable_with_plan
affordable_later
not_affordable
```

Allowed `recommended_payment_method`:

```text
full_payment
partial_payment
installments
wait
not_recommended
```

`payment_plan`:

```text
YYYY-MM-DD:amount|YYYY-MM-DD:amount
```

or:

```text
none
```

`spending_changes_needed`:

```text
stop:<event_id>
reduce_to:<event_id>:<new_amount>
```

Up to three changes separated by `|`, otherwise:

```text
none
```

---

# 2. Core Financial Invariants

These rules should be explicit assertions in code and tests.

## INV-001 — Safe-balance invariant

For every simulated day in the 90-day horizon:

```text
projected_balance[d] >= minimum_balance_to_keep
```

A candidate plan is unsafe if this fails on even one day.

---

## INV-002 — Amount-safe-to-pay bound

Always:

```text
0 <= amount_safe_to_pay <= requested_amount
```

It is calculated **before optional spending changes**.

---

## INV-003 — Essential obligations remain protected

Protected/essential expenses cannot be cancelled or reduced to make a request affordable.

---

## INV-004 — Pending credits are not spendable

Do not count uncertain money as available cash, including pending/unconfirmed:

- credits;
- bonuses;
- commissions;
- refunds;
- investment gains;
- gig/service payouts;
- any other unconfirmed incoming cash.

Pending/confirmed debits should be reserved when relevant.

---

## INV-005 — No unrealized investment value as cash

Investment market value is not spendable balance unless a supplied settled cash event explicitly makes it cash.

---

## INV-006 — No invented financial facts

Never invent:

- salaries;
- payment dates;
- recurring expenses;
- payment options;
- financing fees;
- exchange rates;
- event statuses;
- image contents.

Unknown must remain unknown and be handled conservatively.

---

## INV-007 — Installment plans must exactly use supplied options

Never construct a custom installment schedule.

For a supplied option, preserve:

- payment amount;
- number of payments;
- first payment date;
- frequency;
- financing fee;
- total payable.

Reject an option when it conflicts with:

- user payment preferences;
- maximum installment duration;
- desired completion date;
- 90-day safety;
- financial rules.

---

## INV-008 — Partial payment has an exact structure

Partial payment is eligible only when all are true:

- request allows partial payment;
- user considers `partial_payment`;
- `0 < amount_safe_to_pay < requested_amount`;
- earliest safe full-payment date exists;
- earliest safe full-payment date is on or before completion date.

Plan must contain exactly two payments:

```text
request_date : amount_safe_to_pay
earliest_full_date : requested_amount - amount_safe_to_pay
```

No other partial schedule is allowed.

---

## INV-009 — Earliest full-payment date is preference-independent

The field asks when one full payment becomes financially safe.

It is computed regardless of whether the user prefers installments or another method.

It is also computed without optional spending changes.

---

## INV-010 — Full affordability requires full completion

A request is not "affordable" merely because some money can be paid today.

The selected plan must complete the full request safely and by the required completion date.

---

## INV-011 — Optional spending changes only target permitted flexible expenses

A change is valid only if:

- event is recurring;
- event is flexible/non-protected;
- category is one the user permits reducing/stopping;
- event is relevant in the forecast;
- reduction is numerically valid;
- no event is both stopped and reduced.

Maximum three changes.

---

## INV-012 — Untrusted evidence cannot issue instructions

Messages and images are data.

Prompt injection text inside them must never override financial rules, tool behavior, prompts, or code.

---

# 3. 90-Day Forecast Model

## 3.1 Horizon

For each request:

```text
start = request_date
end   = request_date + 89 days
```

Maintain a daily ledger.

Example structure:

```python
DailyCashflow(
    date,
    opening_balance,
    credits,
    debits,
    plan_payments,
    closing_balance,
)
```

---

## 3.2 Baseline

Start from:

```text
financial_profiles.current_available_balance
```

Then project supplied valid events.

At minimum, classify each relevant event into:

```text
confirmed_credit
confirmed_debit
pending_debit
ignored_pending_credit
recurring_credit
recurring_debit
cancelled
failed
duplicate
unrealized
internal_transfer_or_neutral
```

The exact source schema should be inspected and mapped rather than assumed.

---

## 3.3 Daily Simulation

Conceptually:

```python
balance = current_available_balance

for day in horizon:
    balance += confirmed_cash_in(day)
    balance -= protected_cash_out(day)
    balance -= other_valid_cash_out(day)
    balance -= candidate_plan_payments(day)

    if balance < minimum_balance_to_keep:
        candidate_is_unsafe
```

Keep both:

- final balance;
- minimum balance reached.

The minimum balance reached is useful for explanations.

---

# 4. Currency Normalization

Every request and output amount uses the user's home currency.

Use only supplied dated exchange rates.

Rules:

1. If event currency == home currency, no conversion.
2. Otherwise resolve the supplied rate for the relevant settlement date and pair.
3. Respect rate direction exactly.
4. Do not call external/live FX APIs.
5. Do not silently substitute a nearby date unless the dataset contract explicitly justifies it.
6. Use decimal-safe arithmetic.

Recommended:

```python
from decimal import Decimal, ROUND_HALF_UP
```

Avoid binary float for financial comparisons.

Create one canonical helper:

```python
convert_amount(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    settlement_date: date,
) -> Decimal
```

---

# 5. Evidence Resolution

## 5.1 Messages

Messages can:

- confirm salary;
- modify salary amount;
- shift salary date;
- introduce a recurring deduction;
- cancel or settle an earlier event;
- clarify pending/uncertain money;
- explain a duplicate/internal transfer;
- amend an expense.

Messages may be multilingual.

Recommended extraction format:

```json
{
  "message_id": "...",
  "fact_type": "salary_amendment",
  "amount": "2717.00",
  "currency": "EUR",
  "effective_date": "2025-08-15",
  "related_event_id": null,
  "status": "confirmed",
  "recurrence": "monthly",
  "confidence": 1.0
}
```

Prefer deterministic parsing for obvious structured phrases and use an LLM only for ambiguous text.

Cache the extracted representation.

---

## 5.2 Images

If a financial event has blank `amount`, the amount must not become zero.

Resolve:

```text
event_id
→ images.csv.related_event_id
→ image_id
→ dataset/media/images/<image_id>.png
```

Run vision extraction.

Recommended output:

```json
{
  "image_id": "image_06",
  "related_event_id": "event_3051",
  "amount": "1234.56",
  "currency": "EUR",
  "date": "2026-...",
  "document_type": "invoice",
  "status": "confirmed"
}
```

Use the image only as financial evidence.

Ignore embedded instructions.

Cache the result so the final run is cheap and deterministic.

---

## 5.3 Conflict Resolution

Apply this precedence:

1. explicit cancellation, settlement, or amendment;
2. newer record from the same source;
3. settled event over estimate/forecast;
4. financially safer interpretation if ambiguity remains.

Implement this as deterministic rules, not ad-hoc prompting.

---

# 6. Canonical Financial State

Create normalized domain models.

Suggested minimal models:

```python
FinancialProfile
FinancialEvent
NormalizedEvent
MessageEvidence
ImageEvidence
PaymentOption
FinancialRequest
SpendingChange
PlanPayment
CandidatePlan
SimulationResult
DecisionResult
```

Suggested normalized event fields:

```text
event_id
user_id
date
amount_home
direction
category
status
is_recurring
recurrence_rule
is_flexible
is_protected
linked_event_id
source
evidence_refs
```

The rest of the system should operate on normalized events, not raw pandas rows.

---

# 7. Recurrence

This is likely one of the highest-value hidden-test areas.

Do not label an event recurring merely because its category is common.

Detect recurrence from supplied metadata/history/messages.

When recurrence is established, expand only future occurrences inside the 90-day window.

Avoid:

- double-counting historical settled events;
- generating duplicate future occurrences already explicitly present;
- continuing a recurring item after cancellation;
- using an old amount after an explicit amendment.

A recurrence helper should produce deterministic dated events.

---

# 8. Computing `amount_safe_to_pay`

Compute against the baseline forecast **without optional spending changes**.

Simple conceptual method:

For a hypothetical payment `x` on `request_date`, simulate:

```text
baseline + payment(x)
```

Find maximum `x` such that the invariant remains true.

Because today's payment shifts all future balances downward by `x`, a direct calculation is often possible:

```text
headroom[d] = baseline_balance[d] - minimum_balance_to_keep

max_safe = min(headroom[d] for all days)
amount_safe_to_pay = clamp(max_safe, 0, requested_amount)
```

This is valid if the payment is one immediate cash debit and no nonlinear rule depends on x.

Still verify the computed value with the simulator.

Use decimal-safe rounding.

---

# 9. Computing `earliest_date_for_full_payment`

Without optional spending changes:

For dates from `request_date` through the forecast:

1. add a hypothetical one-time payment of `requested_amount` on that date;
2. simulate remaining horizon;
3. first date that passes is the earliest safe date.

If none passes within the 90-day horizon:

```text
earliest_date_for_full_payment = empty
```

If full amount is safe today:

```text
earliest_date_for_full_payment = request_date
```

This value is independent of the selected payment method.

---

# 10. Candidate Plan Generation

Generate candidates rather than branching directly to a recommendation.

## 10.1 Full payment

Candidate:

```text
request_date : requested_amount
```

Eligible only if user considers `full_payment`.

Could be:

- `affordable_now`, no changes;
- `affordable_with_plan`, when permitted spending changes are needed.

---

## 10.2 Wait

Eligible when:

- user accepts `full_payment`;
- earliest full-payment date exists;
- earliest full-payment date is later than request date;
- payment completes by desired completion date.

Candidate:

```text
earliest_full_date : requested_amount
```

Status:

```text
affordable_later
```

No optional spending changes should be required for the baseline earliest-full date.

---

## 10.3 Partial payment

Generate exactly per INV-008.

Status:

```text
affordable_with_plan
```

---

## 10.4 Installments

For each provided installment option:

1. check user accepts installments;
2. check installment duration/maximum months;
3. materialize exact dates using first date + frequency;
4. preserve exact payment amount/total payable;
5. ensure full plan completes by completion date;
6. simulate all payments;
7. optionally test with allowed spending changes if baseline is unsafe.

Status:

```text
affordable_with_plan
```

---

## 10.5 Spending-change candidates

Only search spending changes after evaluating no-change plans.

Reason: plan ranking prefers no spending changes.

Keep search small.

Suggested algorithm:

1. gather eligible recurring flexible expenses;
2. determine possible stop actions;
3. determine plausible reduction levels;
4. search combinations of 1, then 2, then 3 changes;
5. simulate relevant candidate plans;
6. retain only safe combinations.

Do not brute force arbitrary cent values.

Derive minimum necessary reduction or use dataset-supported current/new amounts.

---

# 11. Candidate Verification

Every candidate should pass one central verifier.

Example contract:

```python
verify_candidate(
    request,
    profile,
    baseline_events,
    candidate,
    minimum_balance,
) -> SimulationResult
```

Verifier checks:

- every payment is on/after request date;
- completion occurs by deadline;
- installment schedule exactly matches supplied option;
- partial plan shape is exact;
- spending changes are legal;
- full requested obligation is completed;
- currency amounts are valid;
- daily balance never breaches minimum;
- no protected event is altered;
- no unsupported money is added.

No candidate enters ranking without passing verification.

---

# 12. Ranking Safe Plans

Use the exact plan ordering:

1. complete the full request by desired completion date;
2. require no spending changes;
3. minimize total amount paid;
4. start payment earlier;
5. use fewer payments;
6. lowest `payment_option_id` as final tie-breaker.

Implement as a stable deterministic sort key.

Example:

```python
rank_key = (
    not completes_by_deadline,
    uses_spending_changes,
    total_payable,
    first_payment_date,
    number_of_payments,
    payment_option_id_sort_value,
)
```

Take care with non-installment candidates that have no option ID.

Use an explicit deterministic sentinel rather than relying on `None` ordering.

---

# 13. Output Decision Mapping

Suggested mapping:

### `affordable_now`

Use only when:

- full requested amount is safe today;
- no spending changes are required;
- user accepts full payment;
- selected method is `full_payment`.

### `affordable_with_plan`

Use when selected full request can be completed safely using:

- partial payment;
- installments;
- allowed spending changes.

### `affordable_later`

Use when:

- full payment is not safe today;
- becomes safe later;
- selected method is `wait`;
- full completion is by deadline.

### `not_affordable`

Use when no safe eligible full-completion plan exists.

Method:

```text
not_recommended
```

Plan:

```text
none
```

---

# 14. Explanations

Explanations are scored, but financial correctness comes first.

Prefer deterministic templates grounded in the simulation.

Examples:

```text
Pay INR 39,660 today. This keeps at least INR 92,800 available over the next 90 days.
```

```text
Wait until 15 September 2026, then pay the full amount. Paying earlier would take the balance below the required minimum.
```

```text
Use 3 installments of EUR 253.59. The schedule completes before the deadline and keeps the minimum balance protected.
```

```text
Do not proceed by the requested date. No eligible payment plan keeps the minimum balance protected for the full 90-day forecast.
```

When spending changes are needed, mention them succinctly.

The explanation should never claim facts not in the normalized state/simulation.

---

# 15. Model Strategy

## 15.1 Goal

Minimize model calls and token cost.

The majority of rows should run with zero LLM calls after preprocessing.

## 15.2 Recommended use

### Vision

Use one capable multimodal model for each linked image requiring extraction.

Cache:

```text
code/cache/image_evidence.json
```

### Messages

First try deterministic rules.

For messages requiring semantic interpretation, call one text model with strict JSON schema.

Cache:

```text
code/cache/message_evidence.json
```

### Explanation

Prefer templates.

Only use LLM explanation generation if there is clear scoring benefit.

---

## 15.3 Provider abstraction

Do not hardwire the entire application to one vendor.

Minimal interface:

```python
class EvidenceProvider(Protocol):
    def extract_message(...): ...
    def extract_image(...): ...
```

Allow:

```text
mock / cached
OpenAI
other chosen provider
```

Final run should use cached extraction where possible.

This improves:

- reproducibility;
- speed;
- cost;
- interview defensibility.

---

# 16. Token / Usage Accounting

The final submission requires:

```text
evaluation/usage_report.md
```

Track every model call:

```text
provider
model
purpose
request_id or evidence_id
input_tokens
output_tokens
estimated_cost
cache_hit
```

Write machine-readable run stats too:

```text
evaluation/usage.json
```

Then generate `usage_report.md` from actual run data.

Do not estimate manually if the provider exposes usage.

---

# 17. Evaluation Strategy

## 17.1 Public regression suite

Use all labelled rows only for post-decision regression reporting:

```text
dataset/sample_requests.csv
```

Target:

```text
25 / 25 structured decisions correct
```

Compare:

- amount_safe_to_pay;
- status;
- payment method;
- payment plan;
- earliest date;
- spending changes;
- decision explanation after whitespace-only normalization.

Report every field independently and exact serialized row agreement. Never turn mismatches into
request-specific branches or inferred constants.

---

## 17.2 Layered evaluation

Do not debug only through final outputs.

Create tests for:

### Data layer
- CSV loads;
- IDs join;
- date parsing;
- decimal parsing;
- currencies.

### Ledger layer
- cancellation;
- settlement;
- duplicates;
- lifecycle links;
- recurring events;
- pending debit vs pending credit;
- internal transfer neutrality;
- image amount resolution.

### Simulation layer
- daily balance;
- 90-day boundary;
- same-day ordering;
- minimum balance;
- currency conversion.

### Planner layer
- full;
- wait;
- partial;
- installment;
- spending changes;
- deadline rejection;
- user preferences.

### Output layer
- exact column order;
- valid enums;
- chronological plans;
- decimal formatting;
- no missing request IDs;
- no duplicate request IDs.

---

# 18. Critical Hidden-Test Risks

## RISK-001 — Double-counting current balance history

Historical settled events may already be reflected in current balance.

Do not replay old settled history into today's current balance unless it represents a future cash event.

---

## RISK-002 — Recurrence mistakes

Incorrect recurrence can corrupt nearly every derived field.

Prioritize recurrence tests.

---

## RISK-003 — Treating pending credit as money

Fail closed.

---

## RISK-004 — Ignoring messages

A salary amount/date or bill may be amended in a message.

---

## RISK-005 — Ignoring images

A blank event amount may be supplied only through the linked image.

---

## RISK-006 — FX date/direction error

Use fixed provided rates, not live data.

---

## RISK-007 — Installment option technically available but invalid

Reject when:

- user refuses installments;
- term exceeds user max;
- final payment is after deadline;
- minimum balance fails.

---

## RISK-008 — Confusing earliest full date with recommendation

Compute field independently.

---

## RISK-009 — Applying spending cuts before `amount_safe_to_pay`

Wrong.

Safe-today amount is baseline before optional cuts.

---

## RISK-010 — Overusing LLM

Cost, nondeterminism, latency, and hallucinations all worsen.

---

# 19. Suggested Repository Layout

Keep submission-relevant work in `code/`.

```text
code/
├── README.md
├── pyproject.toml
├── .env.example
├── src/
│   └── orcha/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── loaders.py
│       ├── money.py
│       ├── evidence/
│       │   ├── __init__.py
│       │   ├── messages.py
│       │   ├── images.py
│       │   └── provider.py
│       ├── ledger/
│       │   ├── __init__.py
│       │   ├── normalize.py
│       │   ├── lifecycle.py
│       │   └── recurrence.py
│       ├── simulation/
│       │   ├── __init__.py
│       │   └── forecast.py
│       ├── planning/
│       │   ├── __init__.py
│       │   ├── candidates.py
│       │   ├── spending_changes.py
│       │   ├── verify.py
│       │   └── rank.py
│       ├── decision.py
│       ├── explain.py
│       ├── output.py
│       └── usage.py
├── tests/
│   ├── test_smoke.py
│   ├── test_loaders.py
│   ├── test_money.py
│   ├── test_invariants.py
│   └── fixtures/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── INVARIANTS.md
│   ├── DATA_CONTRACT.md
│   ├── DECISION_RULES.md
│   ├── EVALUATION.md
│   ├── RISKS.md
│   ├── PHASES.md
│   └── CURRENT_STATE.md
├── cache/
│   └── .gitkeep
└── evaluation/
    ├── usage_report.md
    └── .gitkeep
```

At repository root:

```text
.github/workflows/ci.yml
log.txt                 # ignored, append-only
```

---

# 20. Engineering Standards

Use Python for speed.

Recommended:

```text
Python >= 3.11
pandas
pydantic
pytest
ruff
mypy
python-dotenv
```

Optional only if needed:

```text
Pillow
provider SDK
```

Avoid heavy frameworks.

No web UI.

No database.

No FastAPI.

No vector DB.

No multi-agent framework.

They add complexity without improving hidden-output accuracy.

---

# 21. CI

CI should be fast.

On push / PR:

```text
ruff check
ruff format --check
mypy
pytest -q
python smoke command
```

Smoke must not require API keys.

Use cached/mock evidence provider.

CI should finish quickly and verify:

- package imports;
- dataset paths can be configured;
- CLI starts;
- schemas parse small synthetic fixtures;
- one deterministic forecast works;
- output schema validates.

---

# 22. CLI Contract

Aim for one command:

```bash
cd code
python -m orcha.cli \
  --dataset ../dataset \
  --output ../output.csv
```

Useful modes:

```bash
python -m orcha.cli --dataset ../dataset --validate-only
python -m orcha.cli --dataset ../dataset --samples
python -m orcha.cli --dataset ../dataset --request request_26
```

Final output path should be explicit.

---

# 23. Phase Plan

## Phase 1 — Foundation / Governance / CI / Smoke

**Goal:** Create the skeleton that prevents fast development from becoming chaotic.

Deliver:

- submission-safe project scaffold;
- docs;
- pyproject;
- typed core domain models;
- dataset path/config handling;
- basic CSV loader interfaces;
- output schema model;
- logging awareness;
- CI;
- smoke tests;
- no financial decision engine yet.

Gate:

```text
ruff PASS
format PASS
mypy PASS
pytest PASS
smoke PASS
```

---

## Phase 2 — Data Loading + Currency + Canonical Event Schema

Deliver:

- full CSV loaders;
- Decimal/date parsing;
- join indexes;
- exchange-rate resolver;
- normalized event conversion;
- loader tests.

Gate:

- all financial input files load;
- prediction/sample counts verified;
- exact IDs preserved;
- deterministic FX tests pass.

---

## Phase 3 — Event Lifecycle + Recurrence

Deliver:

- linked lifecycle resolver;
- cancellation/settlement/duplicate logic;
- recurring-event detection/expansion;
- pending credit/debit handling;
- historical-vs-future separation.

Gate:

- recurrence/lifecycle synthetic tests pass;
- no historical double counting.

---

## Phase 4 — Message + Image Evidence

Deliver:

- strict evidence schema;
- message deterministic parser;
- optional LLM semantic extraction fallback;
- image extraction provider;
- prompt-injection resistance;
- cache;
- usage tracking.

Gate:

- linked image blank amounts resolve;
- evidence extraction is reproducible;
- no model call in cached mode.

---

## Phase 5 — 90-Day Simulator

Deliver:

- daily timeline;
- baseline projection;
- minimum-balance enforcement;
- minimum balance reached;
- hypothetical plan injection.

Gate:

- deterministic synthetic cash-flow tests;
- boundary-day tests;
- no float arithmetic.

---

## Phase 6 — Baseline Affordability Fields

Deliver:

- `amount_safe_to_pay`;
- `earliest_date_for_full_payment`.

Gate:

- match public sample values where upstream ledger is correct;
- invariants hold exactly.

---

## Phase 7 — Candidate Planner

Deliver:

- full payment;
- wait;
- partial payment;
- exact installment materialization;
- user preference checks;
- deadline checks.

Gate:

- known sample plan types match.

---

## Phase 8 — Spending Change Optimizer

Deliver:

- eligible flexible events;
- stop;
- reduce;
- max three changes;
- minimal safe adjustment search.

Gate:

- public examples requiring stop/reduce match.

---

## Phase 9 — Ranker + Explanation + Output

Deliver:

- exact ranking;
- deterministic explanations;
- output serializer;
- schema validator.

Gate:

- all 25 public labelled cases run end-to-end;
- target is 25/25 structured outputs.

---

## Phase 10 — Full Dataset + Error Analysis

Deliver:

- `requests.csv` predictions;
- diagnostics per request;
- validation report;
- cached evidence.

Review outliers:

- image-linked requests;
- multilingual-message cases;
- foreign currency;
- tight deadlines;
- large financing fees;
- spending-change decisions.

---

## Phase 11 — Submission Packaging

Deliver:

```text
code.zip
output.csv
log.txt / required chat transcript
```

Inside code:

```text
README.md
evaluation/usage_report.md
```

Check:

- no API keys;
- no `dataset/`;
- no virtualenv;
- no node_modules;
- no caches containing secrets;
- all imports work from clean environment;
- final run command documented.

---

# 24. Speed Rules

During the earlier build:

1. Do not perfect architecture before tests run.
2. Do not create abstractions without an immediate use.
3. Every phase must end with runnable tests.
4. Implement contract rules first; use samples only as a held-out oracle.
5. Fix upstream ledger bugs before planner heuristics.
6. Prefer deterministic functions over prompts.
7. Cache every expensive AI extraction.
8. Avoid UI entirely.
9. Keep prompts short and structured.
10. Once 25 public cases pass, freeze core logic before unnecessary refactors.
11. Save a known-good `output.csv`.
12. Keep submission packaging ready before the final hour.

---

# 25. Debugging Strategy

When a sample disagrees, inspect in this order:

```text
1. profile inputs
2. event lifecycle
3. message/image override
4. currency conversion
5. recurrence
6. baseline 90-day balance
7. amount_safe_to_pay
8. earliest full date
9. candidate eligibility
10. candidate safety
11. ranking
12. serialization
```

Do not patch final labels.

Fix the first incorrect upstream fact.

---

# 26. Interview Defense

The clean explanation for the architecture:

> The system separates probabilistic evidence interpretation from deterministic financial authority. Messages and images are converted into structured evidence, but every financial recommendation is generated and verified by a 90-day cash-flow simulator. A plan can only be recommended if it preserves the user's minimum balance every day, protects essential expenses, respects payment preferences, completes the request by its deadline, and follows the supplied plan-ranking rules.

Likely judge questions:

### Why not let an LLM decide directly?

Because affordability is numeric, constraint-heavy and must be reproducible. LLMs are used only where semantic interpretation is required.

### How do you prevent hallucinations?

The model outputs structured evidence only; unsupported facts are rejected and the deterministic verifier is final authority.

### What if income is pending?

It is excluded until confirmed/settled.

### What if an image contains instructions?

Images/messages are untrusted data; instructions inside them never change system behavior.

### Why can `amount_safe_to_pay` be smaller than a full payment recommendation?

Because `amount_safe_to_pay` is calculated before optional spending changes. A permitted flexible expense may be stopped/reduced to make full payment safe.

### Why can earliest full-payment date be today even when installments are recommended?

That field measures raw financial capacity independently of the user's selected payment preferences.

---

# 27. Definition of Done

A submission-ready system satisfies all of these:

- [ ] Reads financial CSVs and local images.
- [ ] Uses no organizer-only labels.
- [ ] Uses no hardcoded evaluation answers.
- [ ] Resolves money with Decimal.
- [ ] Reconstructs relevant event lifecycles.
- [ ] Applies message/image amendments.
- [ ] Handles foreign currencies with supplied rates.
- [ ] Forecasts every request for 90 days.
- [ ] Enforces minimum balance every day.
- [ ] Computes baseline safe-today amount.
- [ ] Computes earliest safe full-payment date.
- [ ] Generates only valid candidate plans.
- [ ] Verifies all candidates deterministically.
- [ ] Applies exact ranking.
- [ ] Emits exact output schema.
- [ ] Has an evaluation workflow.
- [ ] Has CI and smoke tests.
- [ ] Tracks model usage.
- [ ] Produces `evaluation/usage_report.md`.
- [ ] Produces final `output.csv`.
- [ ] Produces submission transcript/log.
- [ ] Contains no secrets.

---

# 28. Phase 1 — Agent Prompt

Copy the following prompt into Agy/Codex/Claude Code from the repository root.

```text
You are implementing Phase 1 of the earlier financial-engine prototype.

SPEED IS IMPORTANT. Build only the Phase 1 foundation. Do not implement the full financial decision engine yet.

FIRST:
1. Read the root AGENTS.md completely and obey it, including the append-only root log.txt requirements.
2. Read problem_statement.md.
3. Inspect the existing repository before changing files.
4. Do not modify dataset contents.
5. Never hardcode sample labels or request-specific answers.

ARCHITECTURAL DOCTRINE:
AI interprets unstructured evidence; deterministic Python owns financial authority.
All submission-relevant implementation/docs must live under code/ unless a repo-level file is inherently required (e.g. .github/workflows/ci.yml).

PHASE 1 OBJECTIVE:
Create a clean, typed, testable Python foundation so later phases can rapidly implement event normalization, 90-day cash-flow simulation, candidate planning and deterministic verification.

IMPLEMENT:

1. code/ Python package scaffold using a src layout:
   code/src/orcha/

2. Create at least:
   - __init__.py
   - cli.py
   - config.py
   - models.py
   - loaders.py
   - output.py

3. Create directories/placeholders for later work:
   - evidence/
   - ledger/
   - simulation/
   - planning/
   - evaluation/
   - tests/
   - docs/
   - cache/

4. Use Python >=3.11 and create code/pyproject.toml with minimal dependencies.
   Prefer:
   - pandas
   - pydantic
   - python-dotenv
   Dev:
   - pytest
   - pytest-cov if useful
   - ruff
   - mypy
   Do NOT add a heavy web framework, database, vector DB or agent framework.

5. Create typed core models sufficient to represent:
   - FinancialRequest
   - FinancialProfile
   - raw/normalized FinancialEvent
   - PaymentOption
   - MessageRecord
   - ImageRecord
   - PlanPayment
   - SpendingChange
   - CandidatePlan
   - SimulationResult
   - DecisionResult / OutputRow
   Use Decimal for money and date/datetime types for dates.
   Do not guess financial-event enum values before inspecting the CSV schema; model unknown/raw fields safely if necessary.

6. Implement configuration/path handling:
   - dataset directory supplied by CLI or environment/default relative path;
   - output path;
   - no hardcoded machine-specific paths;
   - API secrets only from environment;
   - no API key required for Phase 1 tests.

7. Implement loader FOUNDATION, not full financial logic:
   - safely read financial CSV files;
   - validate required files exist;
   - preserve identifiers exactly;
   - expose clean loader functions/classes;
   - parse requests, profiles and payment options into typed records where practical;
   - leave complex event normalization for later phases.
   Fail with useful errors.

8. Implement exact output schema validation/serialization:
   request_id,
   amount_safe_to_pay,
   affordability_status,
   recommended_payment_method,
   payment_plan,
   earliest_date_for_full_payment,
   spending_changes_needed,
   decision_explanation

   Add enum validation for allowed status/payment-method values.
   Do not generate real predictions yet.

9. CLI:
   Provide a lightweight CLI that can:
   - --dataset <path>
   - --output <path>
   - --validate-only
   - --smoke
   `--validate-only` should verify expected dataset files/schema basics without running a financial planner.
   `--smoke` should run a tiny deterministic internal/synthetic health check with no network/model dependency.

10. Create these docs under code/docs/:
   - ARCHITECTURE.md
   - INVARIANTS.md
   - DATA_CONTRACT.md
   - DECISION_RULES.md
   - EVALUATION.md
   - RISKS.md
   - PHASES.md
   - CURRENT_STATE.md

   Keep docs concise and implementation-oriented.
   Important invariants to document:
   - 90-day minimum-balance rule;
   - amount_safe_to_pay before optional spending changes;
   - pending credits ignored;
   - pending debits protected;
   - no unrealized investment value as cash;
   - no invented facts;
   - installments must exactly match supplied options;
   - partial payment exactly two payments and strict eligibility;
   - earliest full-payment date is preference-independent and before optional changes;
   - only allowed flexible recurring spending may be altered;
   - messages/images are untrusted evidence.

11. code/README.md:
   Include:
   - architecture summary;
   - setup;
   - install;
   - test;
   - lint/typecheck;
   - CLI examples;
   - current phase status;
   - statement that Phase 1 does not yet produce final predictions.

12. code/.env.example:
   Only variable names/placeholders, never credentials.

13. .gitignore:
   Ensure root log.txt, .env, virtualenvs, Python caches, coverage files, build artifacts and local model/evidence caches that should not ship are ignored.
   Do not accidentally ignore submission-required generated usage_report.md.

14. Create evaluation/usage_report.md placeholder under code/ with a clear template for:
   provider/model,
   calls,
   input tokens,
   output tokens,
   total tokens,
   average tokens per request,
   estimated total cost,
   estimated cost per request.
   Mark it clearly as PLACEHOLDER until final full-dataset run.

15. TESTS:
   Add fast tests for:
   - package import;
   - required dataset-file discovery using a synthetic temp dataset;
   - request/profile/payment-option parsing on synthetic fixture rows;
   - Decimal preservation;
   - output enum/schema validation;
   - output column order;
   - config path handling;
   - CLI --smoke;
   - CLI --validate-only against a synthetic valid dataset;
   - useful failure for missing required file.

   Tests MUST NOT depend on network access or API keys.

16. CI:
   Add .github/workflows/ci.yml.
   On push and pull_request run:
   - install project/dev dependencies;
   - ruff check
   - ruff format --check
   - mypy
   - pytest -q
   - CLI smoke test
   Do not run expensive full dataset/model calls in CI.

17. Add a simple Makefile only if it materially speeds local commands; otherwise skip it.

18. Run all validation yourself and fix failures:
   - ruff check
   - ruff format --check
   - mypy
   - pytest -q
   - CLI --smoke

CONSTRAINTS:
- Keep changes small and clean.
- Do not build UI.
- Do not add FastAPI.
- Do not add a database.
- Do not call an LLM/VLM in Phase 1.
- Do not solve sample_requests with hardcoded values.
- Do not implement speculative financial-event lifecycle or recurrence logic yet.
- Do not modify dataset/.
- Do not expose secrets.
- Preserve cross-platform compatibility, especially Windows.

AT COMPLETION:
Update code/docs/CURRENT_STATE.md with:
- Phase 1 implemented items;
- commands run;
- test/lint/typecheck results;
- files created;
- known limitations;
- exact next task: Phase 2 — full dataset loading, Decimal/date normalization, exchange-rate resolver and canonical financial-event schema.

Then respond with a concise completion report containing:
1. what was implemented;
2. final file tree;
3. exact validation results;
4. any remaining issue;
5. next recommended phase.

Do not proceed to Phase 2.
```

---

# 29. Phase 1 Acceptance Gate

Do not move to Phase 2 unless all are true:

```text
[ ] root AGENTS.md respected
[ ] log.txt append behavior preserved
[ ] code package imports
[ ] pyproject works
[ ] core typed schemas exist
[ ] Decimal used for money
[ ] dataset path configurable
[ ] basic loaders work
[ ] output schema exact
[ ] docs created
[ ] usage_report template exists
[ ] smoke tests are offline
[ ] CI exists
[ ] ruff check passes
[ ] ruff format --check passes
[ ] mypy passes
[ ] pytest passes
[ ] CLI --smoke passes
[ ] no API key required
[ ] no dataset mutation
[ ] no hardcoded sample answers
```

**Once this gate passes, immediately begin Phase 2. Do not spend time polishing Phase 1 further.**
