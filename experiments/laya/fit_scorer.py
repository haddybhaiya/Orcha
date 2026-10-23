"""Freeze Laya and adapt only its 768-parameter final linear option scorer."""


def main() -> None:
    import base64
    import hashlib
    import json
    import random
    import time

    import laya
    import torch
    from safetensors.torch import save_file
    from service import CRITERIA

    torch.set_num_threads(2)
    torch.manual_seed(23)
    random.seed(23)
    started = time.monotonic()
    agent = laya.load("/opt/laya-model", device="cpu")
    model = agent.model
    model.eval()
    actions = list(CRITERIA)
    question = {
        "next_action": dict(
            type="choice",
            instructions=(
                "Choose the next financial-assistant workflow action from the "
                "flags. Any issues_count above zero requires clarification. Never "
                "skip validation."
            ),
            criteria=CRITERIA,
        )
    }

    def cases(documents, issues):
        rows = []
        for docs in documents:
            for action in actions:
                for count in issues if action == "ask_clarification" else [0]:
                    state = dict(
                        interpreted=action in ["run_forecast", "explain_result"],
                        evidence_valid=action in ["run_forecast", "explain_result"],
                        result_verified=action == "explain_result",
                        issues_count=count,
                        document_count=docs,
                    )
                    rows.append(dict(state=state, expected=action))
        return rows

    splits = {
        "train": cases([0, 2, 6], [1, 9, 32]),
        "validation": cases([3, 5], [2, 11]),
        "test": cases([1, 4, 7, 8], [3, 17, 99]),
    }
    cached = {}
    captured = []
    hook = model.scorer[-1].register_forward_pre_hook(
        lambda module, args: captured.append(args[0].detach().cpu().numpy().copy())
    )
    for name, rows in splits.items():
        features = []
        for row in rows:
            captured.clear()
            output = agent.predict(
                json.dumps(
                    {k: v for k, v in row["state"].items() if k != "document_count"}
                    | {"issues_count": int(row["state"]["issues_count"] > 0)},
                    sort_keys=True,
                ),
                question,
                max_len=512,
            )
            row["baseline"] = output["answers"]["next_action"]["choice"]
            features.append(torch.tensor(captured[-1][0]))
        cached[name] = (
            torch.stack(features),
            torch.tensor([actions.index(r["expected"]) for r in rows]),
        )
    hook.remove()
    weight = model.scorer[-1].weight.detach().clone().requires_grad_()
    features, targets = cached["train"]
    counts = torch.bincount(targets, minlength=4).float()
    class_weights = 1 / counts
    optimizer = torch.optim.LBFGS(
        [weight],
        lr=1,
        max_iter=500,
        tolerance_grad=1e-9,
        tolerance_change=1e-12,
        line_search_fn="strong_wolfe",
    )

    def closure():
        optimizer.zero_grad()
        logits = torch.einsum("bkd,od->bk", features, weight)
        loss = torch.nn.functional.cross_entropy(logits, targets, weight=class_weights)
        loss.backward()
        return loss

    optimizer.step(closure)
    with torch.no_grad():
        model.scorer[-1].weight.copy_(weight)
    results = {}
    for name, (features, _targets) in cached.items():
        with torch.no_grad():
            logits = torch.einsum("bkd,od->bk", features, weight)
            probabilities = logits.softmax(-1)
            predictions = logits.argmax(-1)
        rows = splits[name]
        for i, row in enumerate(rows):
            row["selected"] = actions[int(predictions[i])]
            row["confidence"] = round(float(probabilities[i].max()), 4)
            row["probabilities"] = {
                a: round(float(probabilities[i, j]), 6) for j, a in enumerate(actions)
            }
        results[name] = dict(
            total=len(rows),
            baseline_correct=sum(r["baseline"] == r["expected"] for r in rows),
            adapted_correct=sum(r["selected"] == r["expected"] for r in rows),
            minimum_confidence=round(float(probabilities.max(-1).values.min()), 4),
            rows=rows,
        )
    path = "/tmp/orcha-workflow-scorer.safetensors"
    save_file({"weight": weight.detach().contiguous()}, path)
    raw = open(path, "rb").read()
    # Check the public Agent API after attaching the learned scorer, not just cached features.
    public = []
    for row in splits["test"][:4]:
        answer = agent.predict(
            json.dumps(
                {k: v for k, v in row["state"].items() if k != "document_count"}
                | {"issues_count": int(row["state"]["issues_count"] > 0)},
                sort_keys=True,
            ),
            question,
            max_len=512,
        )["answers"]["next_action"]
        public.append(
            dict(
                expected=row["expected"],
                selected=answer["choice"],
                confidence=answer["answer_confidence"],
            )
        )
    print(
        json.dumps(
            dict(
                results=results,
                public_api=public,
                adapter_b64=base64.b64encode(raw).decode(),
                adapter_sha256=hashlib.sha256(raw).hexdigest(),
                trainable_parameters=weight.numel(),
                steps=500,
                elapsed_seconds=round(time.monotonic() - started, 2),
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
