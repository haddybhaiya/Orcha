"""Screen status classification rather than imperative next-action prompts."""


def main() -> None:
    import argparse
    import json
    import time

    import laya
    import torch

    p = argparse.ArgumentParser()
    p.add_argument("--model", default="/opt/laya-model")
    args = p.parse_args()
    torch.set_num_threads(2)
    agent = laya.load(args.model, device="cpu")
    actions = ["interpret_request", "ask_clarification", "run_forecast", "explain_result"]
    descriptions = {
        "A": (
            "A new request has arrived and its meaning is still unknown. No "
            "blocking issues are reported."
        ),
        "B": (
            "There are unresolved problems, missing details or conflicting "
            "facts requiring user input."
        ),
        "C": (
            "The request is understood and evidence is validated. A verified "
            "financial result is still pending."
        ),
        "D": (
            "The financial result is complete and independently verified. All "
            "facts are valid and there are no unresolved issues."
        ),
    }
    short = {
        "A": "New unprocessed request.",
        "B": "Blocked by missing or conflicting information.",
        "C": "Ready for financial calculation.",
        "D": "Verified result ready for presentation.",
    }
    rows = []
    for expected in actions:
        s = dict(
            interpreted=expected in ["run_forecast", "explain_result"],
            evidence_valid=expected in ["run_forecast", "explain_result"],
            result_verified=expected == "explain_result",
            issues_count=1 if expected == "ask_clarification" else 0,
            document_count=2,
        )
        full = "\n".join(
            [
                "Request understanding: " + ("complete" if s["interpreted"] else "pending") + ".",
                "Evidence validation: " + ("complete" if s["evidence_valid"] else "pending") + ".",
                "Financial result verification: "
                + ("complete" if s["result_verified"] else "pending")
                + ".",
                "Unresolved problems: " + str(s["issues_count"]) + ".",
                "Supporting documents: 2.",
            ]
        )
        focused = " ".join(
            (
                ["The request has unresolved problems requiring user input."]
                if s["issues_count"]
                else ["There are no unresolved problems."]
            )
            + (
                ["The request has been understood."]
                if s["interpreted"]
                else ["A new request has arrived; its contents are still unprocessed."]
            )
            + (
                ["Supporting facts are checked and valid."]
                if s["evidence_valid"]
                else ["Supporting facts are awaiting checking."]
            )
            + (
                ["A financial result is complete and independently verified."]
                if s["result_verified"]
                else ["The financial result is pending."]
            )
        )
        for variant in [
            "status_full",
            "status_short",
            "focused_full",
            "focused_short",
            "focused_order",
        ]:
            options = short if "short" in variant else descriptions
            q = dict(
                type="choice",
                instructions=(
                    "Which workflow status best matches the case? An unresolved "
                    "problem takes priority over other progress."
                ),
                criteria=options,
            )
            questions = (
                {str(i): dict(q, option_order=[(i + j) % 4 for j in range(4)]) for i in range(4)}
                if variant == "focused_order"
                else {"status": q}
            )
            start = time.monotonic()
            result = agent.predict(
                full if variant.startswith("status") else focused, questions, max_len=512
            )
            probs = {k: 0.0 for k in descriptions}
            for answer in result["answers"].values():
                for k, v in answer["probabilities"].items():
                    probs[k] += float(v) / len(questions)
            key = max(probs, key=probs.get)
            action = actions[list(descriptions).index(key)]
            rows.append(
                dict(
                    expected=expected,
                    variant=variant,
                    selected=action,
                    probabilities=probs,
                    correct=action == expected,
                    latency_ms=round((time.monotonic() - start) * 1000, 2),
                )
            )
    print(
        json.dumps(
            dict(
                model=args.model,
                rows=rows,
                summary={
                    v: sum(r["correct"] for r in rows if r["variant"] == v)
                    for v in sorted(set(r["variant"] for r in rows))
                },
            )
        )
    )


if __name__ == "__main__":
    main()
