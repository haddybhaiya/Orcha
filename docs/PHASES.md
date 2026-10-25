# Orcha roadmap

The full implementation brief and constraints are in [plan.md](../plan.md).

| Task | Deliverable | Status |
| --- | --- | --- |
| 1. Baseline | Inspect the engine, run offline checks, record gaps, add synthetic demo data. | Complete; original dataset restored and its checks pass. |
| 2. Gemma workflow | Interpret fresh inputs, validate facts and source references, call the engine, explain verified results. | Complete for fresh text bills and scheduled-bill amendments; see ASSISTANT.md. |
| 3. Hosted Laya routing | InstaCloud inference, enforced dependencies, proposal trace, and a reliable fallback. | Workflow v1 and recovery fixes deployed October 25; fresh production checks pass. See DEPLOYMENT_VERIFICATION.md and LAYA_REFINEMENT.md. |
| 4. Demonstration interface | Upload/question/result flow with recommendations, evidence, and action visibility. | Local interface and public synthetic demo complete; see WEB_INTERFACE.md and PUBLIC_DEMO.md. |
| 5. Optional integrations | Sentry tracing first; voice or hosting only if useful and time allows. | Planned. |
| 6. Delivery | Focused checks, setup documentation, a short working demo, and a submission draft. | Planned. |

The existing financial engine is reused. Historical implementation stages in
[ENGINE_DESIGN_NOTES.md](ENGINE_DESIGN_NOTES.md) describe earlier work and are not
current task instructions or claims about when that code was written.
