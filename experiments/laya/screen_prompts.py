"""Bounded cloud-only prompt screening; contains no customer data or credentials."""


def main() -> None:
    import argparse
    import json
    import os
    import resource
    import time

    os.environ["USE_TF"] = "0"
    import laya
    import torch

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/opt/laya-model")
    args = parser.parse_args()
    torch.set_num_threads(2)
    started = time.monotonic()
    agent = laya.load(args.model, device="cpu")
    actions = ["interpret_request", "ask_clarification", "run_forecast", "explain_result"]
    original = {
        "interpret_request": "No interpretation yet and no blocking issues: interpret the request.",
        "ask_clarification": (
            "There are blocking issues or unresolved facts: ask for clarification."
        ),
        "run_forecast": (
            "Interpretation and evidence validation are complete, no issues, result not verified."
        ),
        "explain_result": (
            "The financial result is already independently verified and there are no issues."
        ),
    }
    criteria = {
        "interpret_request": (
            "Read and understand a new request. Its meaning has not been "
            "extracted and no problems are reported."
        ),
        "ask_clarification": (
            "Ask the user to resolve missing, conflicting or blocked "
            "information. At least one problem is reported."
        ),
        "run_forecast": (
            "Calculate a financial forecast. Request meaning and evidence are "
            "checked, with no problems; there is no verified result yet."
        ),
        "explain_result": (
            "Present a completed financial result. Both evidence and result "
            "have passed their checks, with no problems."
        ),
    }

    def describe(state):
        return " ".join(
            [
                "Request meaning: "
                + ("understood." if state["interpreted"] else "not yet understood."),
                "Supporting evidence: "
                + ("checked and valid." if state["evidence_valid"] else "not checked."),
                "Financial result: "
                + ("checked and verified." if state["result_verified"] else "not verified."),
                "Unresolved problems: " + str(state["issues_count"]) + ".",
                "Attached documents: " + str(state["document_count"]) + ".",
            ]
        )

    rows = []
    for documents in [0, 2]:
        for expected in actions:
            state = dict(
                interpreted=expected in ["run_forecast", "explain_result"],
                evidence_valid=expected in ["run_forecast", "explain_result"],
                result_verified=expected == "explain_result",
                issues_count=1 if expected == "ask_clarification" else 0,
                document_count=documents,
            )
            for variant in ["original_json", "english", "neutral", "rotations"]:
                options = original if variant == "original_json" else criteria
                mapping = {str(i): action for i, action in enumerate(actions)}
                if variant in ["neutral", "rotations"]:
                    options = {key: criteria[action] for key, action in mapping.items()}
                question = dict(
                    type="choice",
                    instructions=(
                        "Choose the next financial-assistant workflow action from the flags. "
                        "Any issues_count above zero requires clarification. Never skip validation."
                        if variant == "original_json"
                        else (
                            "Which operation should happen next? Match the current state to "
                            "the operation requirements."
                        )
                    ),
                    criteria=options,
                )
                questions = {"next": question}
                if variant == "rotations":
                    questions = {
                        str(i): dict(question, option_order=[(i + j) % 4 for j in range(4)])
                        for i in range(4)
                    }
                tick = time.monotonic()
                result = agent.predict(
                    json.dumps(state, sort_keys=True)
                    if variant == "original_json"
                    else describe(state),
                    questions,
                    max_len=512,
                )
                answers = result["answers"]
                probabilities = {action: 0.0 for action in actions}
                for answer in answers.values():
                    for key, value in answer["probabilities"].items():
                        action = mapping[key] if variant in ["neutral", "rotations"] else key
                        probabilities[action] += float(value) / len(answers)
                selected = max(probabilities, key=probabilities.get)
                rows.append(
                    dict(
                        variant=variant,
                        state=state,
                        expected=expected,
                        selected=selected,
                        probabilities=probabilities,
                        correct=selected == expected,
                        latency_ms=round((time.monotonic() - tick) * 1000, 2),
                    )
                )
    summaries = {}
    for variant in ["original_json", "english", "neutral", "rotations"]:
        selected = [r for r in rows if r["variant"] == variant]
        summaries[variant] = dict(
            correct=sum(r["correct"] for r in selected),
            total=len(selected),
            mean_ms=round(sum(r["latency_ms"] for r in selected) / len(selected), 2),
        )
    print(
        json.dumps(
            dict(
                model=args.model,
                summary=summaries,
                rows=rows,
                elapsed_seconds=round(time.monotonic() - started, 2),
                max_rss_kb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
