"""Final-run generation, independent verification, and oracle-only diagnostics."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from orcha.models import CandidatePlan, OutputRow, PlanPayment, SpendingChange
from orcha.output import OUTPUT_COLUMNS, validate_output_rows, write_output_csv
from orcha.planning.engine import DecisionEngine
from orcha.planning.installments import build_installment_plan
from orcha.planning.verify import apply_spending_changes_to_events, verify_plan_safety
from orcha.repository import DatasetRepository
from orcha.simulation.independent import (
    independently_find_earliest_full_payment,
    independently_replay,
    verify_capacity_boundary,
)
from orcha.simulation.timeline import get_forecast_window


@dataclass(frozen=True)
class FinalRunSummary:
    """Counts from a validated production prediction run."""

    rows: int
    status_counts: dict[str, int]
    method_counts: dict[str, int]
    spending_change_rows: int
    zero_safe_rows: int
    full_safe_rows: int
    no_earliest_rows: int
    currency_counts: dict[str, int]


def _parse_payments(value: str) -> list[PlanPayment]:
    if value == "none":
        return []
    return [PlanPayment.from_str(part) for part in value.split("|")]


def _parse_changes(value: str) -> list[SpendingChange]:
    if value == "none":
        return []
    return [SpendingChange.from_str(part) for part in value.split("|")]


def _candidate_from_output(row: OutputRow, repository: DatasetRepository) -> CandidatePlan:
    payments = _parse_payments(row.payment_plan)
    request = repository.get_request(row.request_id)
    options = repository.get_payment_options(request.request_id)
    option = next(
        (
            item
            for item in options
            if row.recommended_payment_method.value == "installments"
            and build_installment_plan(item, request).payments == payments
        ),
        None,
    )
    total_cost = (
        option.total_payable_amount
        if option is not None
        else sum((payment.amount for payment in payments), Decimal("0"))
    )
    return CandidatePlan(
        plan_id=f"output_{row.request_id}",
        recommended_payment_method=row.recommended_payment_method,
        payment_option_id=option.payment_option_id if option is not None else None,
        payments=payments,
        spending_changes=_parse_changes(row.spending_changes_needed),
        total_cost=total_cost,
        is_safe=False,
        completion_date=payments[-1].payment_date if payments else None,
    )


def validate_final_rows(rows: list[OutputRow], repository: DatasetRepository) -> FinalRunSummary:
    """Fail closed unless every emitted recommendation passes both replay paths."""
    expected_ids = [request.request_id for request in repository.all_requests]
    actual_ids = [row.request_id for row in rows]
    if actual_ids != expected_ids:
        raise ValueError(
            "output rows must contain each production request exactly once in input order"
        )
    validate_output_rows(rows)

    status_counts: Counter[str] = Counter()
    method_counts: Counter[str] = Counter()
    currency_counts: Counter[str] = Counter()
    spending_change_rows = zero_safe_rows = full_safe_rows = no_earliest_rows = 0
    engine = DecisionEngine(repository)
    for row in rows:
        request = repository.get_request(row.request_id)
        profile = repository.get_profile(request.user_id)
        if not Decimal("0") <= row.amount_safe_to_pay <= request.requested_amount:
            raise ValueError(f"{row.request_id}: safe amount violates request bounds")
        resolved = engine.baseline_engine.get_or_resolve_ledger(
            request.user_id, request.request_date, request.request_id
        )
        _, end_date = get_forecast_window(request.request_date)
        capacity_safe, next_is_unsafe = verify_capacity_boundary(
            profile,
            resolved,
            request.request_date,
            end_date,
            row.amount_safe_to_pay,
            request.requested_amount,
        )
        # A pre-existing baseline breach can make zero the only valid capacity;
        # that does not authorize a positive payment. Positive outputs must pass
        # independent replay, and every non-capped next cent must be unsafe.
        if (row.amount_safe_to_pay > 0 and not capacity_safe) or next_is_unsafe is False:
            raise ValueError(f"{row.request_id}: independent capacity boundary check failed")
        independently_earliest = independently_find_earliest_full_payment(
            profile,
            resolved,
            request.request_date,
            end_date,
            request.requested_amount,
        )
        if row.earliest_date_for_full_payment != independently_earliest:
            raise ValueError(
                f"{row.request_id}: earliest full-payment date fails independent replay"
            )

        if row.recommended_payment_method.value == "not_recommended":
            if row.payment_plan != "none" or row.spending_changes_needed != "none":
                raise ValueError(f"{row.request_id}: not_recommended must have no plan or changes")
        else:
            plan = _candidate_from_output(row, repository)
            contract_safe, _ = verify_plan_safety(
                profile,
                resolved,
                plan,
                request,
                repository.get_payment_options(request.request_id),
                end_date,
            )
            if not contract_safe:
                raise ValueError(f"{row.request_id}: emitted plan fails contract verification")
            independently_modified = apply_spending_changes_to_events(
                resolved, plan, request.request_date
            )
            independent = independently_replay(
                profile,
                independently_modified,
                request.request_date,
                end_date,
                tuple((payment.payment_date, payment.amount) for payment in plan.payments),
            )
            if not independent.is_safe:
                raise ValueError(f"{row.request_id}: emitted plan fails independent replay")

        if row.affordability_status.value == "affordable_now":
            if row.earliest_date_for_full_payment != request.request_date:
                raise ValueError(
                    f"{row.request_id}: affordable_now requires request-date earliest payment"
                )
        status_counts[row.affordability_status.value] += 1
        method_counts[row.recommended_payment_method.value] += 1
        currency_counts[profile.home_currency] += 1
        spending_change_rows += row.spending_changes_needed != "none"
        zero_safe_rows += row.amount_safe_to_pay == 0
        full_safe_rows += row.amount_safe_to_pay == request.requested_amount
        no_earliest_rows += row.earliest_date_for_full_payment is None

    return FinalRunSummary(
        rows=len(rows),
        status_counts=dict(sorted(status_counts.items())),
        method_counts=dict(sorted(method_counts.items())),
        spending_change_rows=spending_change_rows,
        zero_safe_rows=zero_safe_rows,
        full_safe_rows=full_safe_rows,
        no_earliest_rows=no_earliest_rows,
        currency_counts=dict(sorted(currency_counts.items())),
    )


def generate_production_output(dataset_dir: Path, output_path: Path) -> FinalRunSummary:
    """Generate and fail-closed validate all production predictions."""
    repository = DatasetRepository.load_from_dir(dataset_dir)
    engine = DecisionEngine(repository)
    rows = [engine.evaluate_request(request.request_id) for request in repository.all_requests]
    summary = validate_final_rows(rows, repository)
    write_output_csv(rows, output_path)
    return summary


def sample_safe_amount_report(dataset_dir: Path, report_path: Path) -> dict[str, int]:
    """Write an oracle-only diagnosis of safe-amount mismatches.

    The report reads labels only after predictions are complete and never feeds the
    repository or decision engine.
    """
    repository = DatasetRepository.load_from_dir(dataset_dir, include_samples=True)
    engine = DecisionEngine(repository)
    sample_path = dataset_dir / "sample_requests.csv"
    with sample_path.open(encoding="utf-8-sig", newline="") as handle:
        samples = list(csv.DictReader(handle))

    lines = [
        "# Safe-Amount Oracle Diagnostic",
        "",
        "This report is post-decision diagnostics only; it is not read by production code.",
        "",
        "| request_id | expected | actual | difference | actual minimum | threshold | "
        "minimum date | largest debits | confirmed credits | recurring events | evidence | "
        "suspected general-rule cause |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    mismatch_count = 0
    cause_counts: Counter[str] = Counter()
    for sample in samples:
        request_id = sample["request_id"]
        expected = Decimal(sample["amount_safe_to_pay"])
        baseline = engine.baseline_engine.evaluate_sample(request_id)
        actual = baseline.amount_safe_to_pay
        if actual == expected:
            continue
        mismatch_count += 1
        request = repository.get_sample_request(request_id)
        profile = repository.get_profile(request.user_id)
        resolved = engine.baseline_engine.get_or_resolve_ledger(
            request.user_id, request.request_date, request.request_id
        )
        future_debits = sorted(
            (event for event in resolved if event.is_future_cash_outflow),
            key=lambda event: event.amount_home_currency,
            reverse=True,
        )[:3]
        credits = [event for event in resolved if event.is_future_cash_inflow]
        recurring = [event for event in resolved if event.is_recurring]
        evidence = sorted(
            {
                evidence_id
                for event in resolved
                for evidence_id in (*event.message_evidence_ids, *event.image_evidence_ids)
            }
        )
        if not credits:
            cause = "no confirmed future income; recurrence and horizon exposure"
        elif any(event.resolved_status.value == "pending" for event in future_debits):
            cause = "pending-debit reservation timing"
        elif evidence:
            cause = "message/image amendment timing or amount"
        elif len(recurring) > 20:
            cause = "recurrence amount or cadence reconstruction"
        else:
            cause = "capacity/horizon reconstruction"
        cause_counts[cause] += 1
        lines.append(
            "| "
            + " | ".join(
                [
                    request_id,
                    str(expected),
                    str(actual),
                    str(actual - expected),
                    str(baseline.minimum_baseline_balance),
                    str(profile.minimum_balance_to_keep),
                    str(baseline.minimum_baseline_balance_date or ""),
                    ", ".join(
                        f"{event.canonical_event_id}:{event.amount_home_currency}"
                        for event in future_debits
                    ),
                    ", ".join(
                        f"{event.canonical_event_id}:{event.amount_home_currency}"
                        for event in credits[:3]
                    ),
                    f"{len(recurring)} events: "
                    + ", ".join(event.canonical_event_id for event in recurring[:5]),
                    ", ".join(evidence) or "none",
                    cause,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Root-cause grouping",
            "",
            "| suspected class | mismatch count |",
            "| --- | ---: |",
            *(f"| {cause} | {count} |" for cause, count in sorted(cause_counts.items())),
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"samples": len(samples), "safe_amount_matches": len(samples) - mismatch_count}


def sample_earliest_date_report(dataset_dir: Path, report_path: Path) -> dict[str, int]:
    """Write an oracle-only earliest-full-payment mismatch diagnosis."""
    repository = DatasetRepository.load_from_dir(dataset_dir, include_samples=True)
    engine = DecisionEngine(repository)
    with (dataset_dir / "sample_requests.csv").open(encoding="utf-8-sig", newline="") as handle:
        samples = list(csv.DictReader(handle))

    lines = [
        "# Earliest Full-Payment Oracle Diagnostic",
        "",
        "This is post-decision diagnostics only; production code never reads sample labels.",
        "",
        "| request_id | expected | actual | independent actual | minimum balance | threshold | "
        "minimum date | confirmed credits | recurring events | evidence | "
        "suspected general-rule cause |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    cause_counts: Counter[str] = Counter()
    mismatches = 0
    for sample in samples:
        request_id = sample["request_id"]
        baseline = engine.baseline_engine.evaluate_sample(request_id)
        decision = engine.evaluate_sample_request(request_id)
        actual = decision.earliest_date_for_full_payment
        expected = sample["earliest_date_for_full_payment"].strip() or None
        actual_text = actual.isoformat() if actual is not None else ""
        if (actual_text or None) == expected:
            continue
        mismatches += 1
        request = repository.get_sample_request(request_id)
        profile = repository.get_profile(request.user_id)
        resolved = engine.baseline_engine.get_or_resolve_ledger(
            request.user_id, request.request_date, request.request_id
        )
        _, end_date = get_forecast_window(request.request_date)
        independent = independently_find_earliest_full_payment(
            profile, resolved, request.request_date, end_date, request.requested_amount
        )
        credits = [event for event in resolved if event.is_future_cash_inflow]
        recurring = [event for event in resolved if event.is_recurring]
        evidence = sorted(
            {
                evidence_id
                for event in resolved
                for evidence_id in (*event.message_evidence_ids, *event.image_evidence_ids)
            }
        )
        if not credits:
            cause = "no confirmed future income within the forecast"
        elif evidence:
            cause = "message/image amendment timing or amount"
        elif recurring:
            cause = "recurrence timing or cadence reconstruction"
        else:
            cause = "forecast horizon or capacity reconstruction"
        cause_counts[cause] += 1
        lines.append(
            "| "
            + " | ".join(
                [
                    request_id,
                    expected or "none",
                    actual_text or "none",
                    independent.isoformat() if independent is not None else "none",
                    str(baseline.minimum_baseline_balance),
                    str(profile.minimum_balance_to_keep),
                    str(baseline.minimum_baseline_balance_date or ""),
                    ", ".join(
                        f"{event.canonical_event_id}:{event.amount_home_currency}"
                        for event in credits[:3]
                    )
                    or "none",
                    f"{len(recurring)} events: "
                    + ", ".join(event.canonical_event_id for event in recurring[:5]),
                    ", ".join(evidence) or "none",
                    cause,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Root-cause grouping",
            "",
            "| suspected class | mismatch count |",
            "| --- | ---: |",
            *(f"| {cause} | {count} |" for cause, count in sorted(cause_counts.items())),
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"samples": len(samples), "earliest_matches": len(samples) - mismatches}


def validate_serialized_output(output_path: Path, dataset_dir: Path) -> FinalRunSummary:
    """Read a serialized output file and verify it against production inputs."""
    with output_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != OUTPUT_COLUMNS:
            raise ValueError("output header does not match the required column order")
        rows = []
        for raw_row in reader:
            if raw_row.get("earliest_date_for_full_payment", "").strip() == "":
                raw_row["earliest_date_for_full_payment"] = None
            rows.append(OutputRow.model_validate(raw_row))
    return validate_final_rows(rows, DatasetRepository.load_from_dir(dataset_dir))
