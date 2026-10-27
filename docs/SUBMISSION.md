*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 3: Slow and Steady](https://dev.to/challenges/hacktoberfest-week3-2026-10-19).*

## What I Built

**Orcha is a financial decision assistant for the everyday question: "Can I buy this without making next week harder?"**

A bank balance tells you what is there today. It takes more work to remember the repair bill, account for rent, check the next payday, and work out whether a purchase can wait.

Orcha brings those steps into one workflow. Give it a purchase question and a text update about a bill. It interprets the update, checks the evidence, projects cash flow over 90 days, and returns a short payment brief with dates, a protected minimum balance, and the source facts behind the decision.

The intended user is someone who wants help thinking through a purchase without rebuilding a spreadsheet every time a bill changes.

## Demo

**[Open the live Orcha demo](https://prod-web-demo-web-6a2d0d-00h16he17ck.compute.instacloud-edge.com)** — no sign-up required.

1. Choose **A laptop & a new bill**.
2. Read the purchase question and unpaid repair invoice.
3. Select **Find a steady way forward**.
4. Inspect the recommendation, cash-flow chart, source evidence, and workflow trace.

The fictional scenario uses a fixed reference date of October 21, 2026:

| Scenario | Amount safe to pay today | Recommended full payment |
| --- | --- | --- |
| Before the new bill | INR 25,000 | October 21 |
| After an unpaid INR 12,000 repair bill | INR 18,000 | October 25 |

The purchase has not changed. A new obligation changes when it fits.

Try **A bill with missing details** to see the clarification path, or **An updated repair bill** to see an amendment affect the plan. You can also enter a fresh fictional question and text bill.

Use fictional information on the public demo. Selected question and document text goes to Google's hosted Gemma service. Financial calculations run on the Orcha server. The demo has no durable account history and does not connect to a bank or execute payments. The first request can take longer while a service wakes up.

## Code

[Source code — Orcha, deployment branch](https://github.com/haddybhaiya/Orcha/tree/dply)

The repository contains the Python application, web interface, synthetic demo data, tests, Laya service, and scorer-fitting experiment. The large base model is downloaded when building the Laya service.

To run the web app locally with Python 3.11 or newer:

```sh
python -m pip install -e ".[web]"
python web.py
```

Copy `.env.example` to `.env` and configure `GEMMA_API_KEY` for fresh text interpretation. Hosted Laya is optional for local use; the controller has a deterministic fallback. The packaged financial demo also runs offline without model API keys.

## How I Built It

Orcha has three distinct responsibilities.

**Gemma reads the question and text evidence.** I use `gemma-4-26b-a4b-it` through Google AI Studio. It extracts typed amounts, currencies, dates, and source quotes. That interpretation is central: it turns a new invoice or changed bill into a proposed financial update.

The extraction must pass Python validation before it can affect a forecast. For example, this check comes from the controller:

```python
def _money_grounded(fact: MoneyQuote, source: TextSource) -> bool:
    return (
        fact.source_id == source.source_id
        and fact.quote in source.text
        and (fact.currency, fact.amount) in _currency_amounts(fact.quote)
    )
```

A value needs a matching source, a real quote, and the stated amount and currency. Additional checks handle dates, unsupported updates, conflicting details, and missing information. When an update cannot be accepted, the user receives a clarification request.

**Laya proposes the next workflow action.** The open-weight Laya model runs in a separate authenticated service on InstaCloud. It receives progress flags and counts. Its four actions are interpretation, clarification, forecasting, and explanation. Python enforces which action is eligible and falls back when a proposal is invalid or unavailable.

The original checkpoint struggled with these states. Prompt changes and larger checkpoints did not resolve that consistently, so I normalized the input and adapted only the final 768 scoring weights. The resulting adapter is 3,152 bytes.

That experiment has a narrow meaning: the normalized workflow contains four finite input patterns, and the controller already determines the permitted next step. Laya's high scores on these states are not calibrated financial-accuracy probabilities.

**Python calculates and verifies the decision.** The engine resolves financial events, simulates the timeline, evaluates payment options, and checks the selected plan against the resolved ledger. The final brief is rendered from verified results. The model never calculates the safe payment amount or authorizes a payment.

I built this week's assistant around my existing Python cash-flow engine. The new work includes Gemma interpretation and evidence validation, the guarded Laya workflow and scorer adaptation, the web experience, and the public deployment.

### What I checked

The latest local offline suite passed **229 tests**, with Ruff and mypy passing as well. The pushed deployment commit also passed CI.

Three live synthetic workflows completed: a new bill, a bill missing its amount, and a bill amendment. They took about **7.5–11.1 seconds** in those observed runs. The missing amount produced clarification; the completed cases returned the expected payment plans. Those timings are observations, not guarantees.

The public app submits a background job and polls for its result, so a slow model call does not hold one gateway request open. It accepts one active forecast at a time and has a shared hourly quota. Public CSV imports are disabled; local use supports imports.

This remains a bounded prototype. Tests establish specific behavior and internal consistency; they do not establish general financial correctness. Broader reference cases still expose disagreements in safe-amount calculations, and the text workflow supports only the documented bill types.

## Why Does Open Innovation Matter?

Open weights gave me a practical way to inspect and change the routing model when prompts alone did not work. I could compare checkpoints, freeze the encoder, fit a tiny scorer, and keep the experiment reproducible in the repository.

Gemma supplies the language understanding at the center of the assistant. I chose hosted inference for this demo so my laptop does not need to load its weights. Orcha currently depends on that network service for fresh interpretation; it does not run entirely offline.

The useful freedom is being able to change the model, provider, and routing behavior while retaining explicit application contracts. A model change still has to pass the same evidence checks and financial rules.

Credits: [Google Gemma](https://ai.google.dev/gemma), [Laya](https://github.com/NandhaKishorM/laya), and the [Laya multilingual checkpoint](https://huggingface.co/convaiinnovations/laya-multilingual). The repository retains model and bundled asset notices.

Related community reading reflects these same boundaries: [*Keep the LLM Out of the Math* by @feasibilityproaiai](https://dev.to/feasibilityproaiai/keep-the-llm-out-of-the-math-deterministic-boundaries-for-financial-modelling-agents-5cl7) discusses deterministic calculation layers, while [*Schema-Valid Isn't Correct* by @michael_maurice](https://dev.to/michael_maurice/schema-valid-correct-4-checks-before-you-trust-llm-extraction-4n6f) explains why extracted values still need grounding and domain checks.

## The Lazy Payoff

The demonstrated payoff is fewer manual steps: paste the bill, ask the question, and inspect one brief instead of editing a timeline and recalculating a purchase plan yourself.

I have not measured real-world time savings. What the synthetic demo shows is that an extra bill can change the recommendation, and missing evidence can stop the workflow before it invents an answer.

## Prize Categories

**Best Use of Gemma.** Gemma is the interpretation layer for fresh purchase questions and bill updates. Its extracted facts must pass validation before entering the financial engine.

*AI disclosure: I used an AI coding assistant during development and to help draft this write-up.*

