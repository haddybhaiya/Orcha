"""Command-line interface for the Orcha financial assistant."""

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from orcha import __version__
from orcha.audit import format_audit_report, run_dataset_audit
from orcha.config import AppConfig
from orcha.evaluation import (
    generate_production_output,
    sample_earliest_date_report,
    sample_safe_amount_report,
    validate_serialized_output,
)
from orcha.evidence.images import ImageEvidenceExtractor
from orcha.evidence.messages import MessageEvidenceExtractor
from orcha.evidence.models import EvidenceType
from orcha.ledger.lifecycle import resolve_event_lifecycles
from orcha.ledger.models import ForecastBehavior
from orcha.ledger.recurrence import detect_recurrence_patterns
from orcha.ledger.resolve import resolve_canonical_ledger
from orcha.loaders import DatasetLoader
from orcha.models import (
    AffordabilityStatus,
    OutputRow,
    RecommendedPaymentMethod,
)
from orcha.output import OUTPUT_COLUMNS, validate_output_rows
from orcha.repository import DatasetRepository
from orcha.simulation.engine import BaselineEngine
from orcha.simulation.timeline import get_forecast_window


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orcha",
        description="Orcha financial assistant with verified payment recommendations.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Path to dataset directory containing financial CSV files (default: dataset/).",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate all production predictions and fail closed on final financial checks.",
    )
    parser.add_argument(
        "--validate-output",
        action="store_true",
        help="Independently validate the serialized --output file against production inputs.",
    )
    parser.add_argument(
        "--audit-safe-amounts",
        action="store_true",
        help="Write an oracle-only sample safe-amount diagnostic under evaluation/.",
    )
    parser.add_argument(
        "--audit-earliest-dates",
        action="store_true",
        help="Write an oracle-only sample earliest-date diagnostic under evaluation/.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to output CSV destination (default: output.csv).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Check dataset files and schema validity without generating predictions.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run fast offline smoke verification of data loaders, models, and output contract.",
    )
    parser.add_argument(
        "--audit-data",
        action="store_true",
        help="Run comprehensive dataset integrity audit and print concise diagnostics.",
    )
    parser.add_argument(
        "--audit-evidence",
        action="store_true",
        help="Run unstructured evidence and canonical ledger diagnostics.",
    )
    parser.add_argument(
        "--resolve-user",
        type=str,
        default=None,
        help="Resolve and print canonical ledger breakdown for a given user_id.",
    )
    parser.add_argument(
        "--forecast",
        type=str,
        default=None,
        metavar="REQUEST_ID",
        help="Run 90-day cash-flow simulation and baseline affordability for a specific request.",
    )
    parser.add_argument(
        "--check-baselines",
        "--baseline-samples",
        action="store_true",
        dest="check_baselines",
        help="Evaluate baseline affordability across sample requests and report match rates.",
    )
    parser.add_argument(
        "--check-samples",
        action="store_true",
        dest="check_samples",
        help=("Evaluate full planning decisions across sample requests and report accuracy."),
    )
    parser.add_argument(
        "--decision",
        type=str,
        default=None,
        metavar="REQUEST_ID",
        dest="decision",
        help="Evaluate full decision recommendation and explanation for a specific request.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def run_smoke_test(dataset_dir: Path) -> int:
    """Execute fast offline smoke check of repository indexing and output validation."""
    print("[SMOKE] Validating required dataset files...")
    loader = DatasetLoader(dataset_dir)
    loader.validate()

    print("[SMOKE] Building indexed DatasetRepository and normalizing financial events...")
    repo = DatasetRepository.load_from_dir(dataset_dir)

    print(
        f"[SMOKE] Loaded {len(repo.all_requests)} requests, {len(repo.all_profiles)} profiles, "
        f"{len(repo.all_payment_options)} option groups, {len(repo.all_events)} events, "
        f"{len(repo.all_messages)} messages, and {len(repo.all_images)} images."
    )

    # Validate index lookups
    first_req = repo.all_requests[0]
    first_prof = repo.get_profile(first_req.user_id)
    user_events = repo.get_events_for_user(first_req.user_id)
    assert first_prof is not None
    assert len(user_events) > 0

    # Validate canonical ledger resolution for the first request user
    print("[SMOKE] Verifying canonical ledger resolution...")
    resolved = resolve_canonical_ledger(
        repository=repo,
        user_id=first_req.user_id,
        request_date=first_req.request_date,
        request_id=first_req.request_id,
    )
    assert len(resolved) > 0

    # Validate 90-day simulation and baseline affordability
    print("[SMOKE] Verifying 90-day simulation and baseline affordability...")
    engine = BaselineEngine(repository=repo)
    baseline_res = engine.evaluate(first_req.request_id)
    assert baseline_res.amount_safe_to_pay >= Decimal("0")
    assert baseline_res.amount_safe_to_pay <= first_req.requested_amount
    assert baseline_res.baseline_simulation is not None
    assert len(baseline_res.baseline_simulation.daily_records) == 90

    # Validate payment planning and the decision engine
    print("[SMOKE] Verifying payment planning and the decision engine...")
    from orcha.planning.engine import DecisionEngine

    decision_engine = DecisionEngine(repository=repo)
    dec_res = decision_engine.evaluate_request(first_req.request_id)
    assert dec_res.request_id == first_req.request_id
    assert dec_res.affordability_status in (
        AffordabilityStatus.AFFORDABLE_NOW,
        AffordabilityStatus.AFFORDABLE_WITH_PLAN,
        AffordabilityStatus.AFFORDABLE_LATER,
        AffordabilityStatus.NOT_AFFORDABLE,
    )
    assert dec_res.recommended_payment_method in (
        RecommendedPaymentMethod.FULL_PAYMENT,
        RecommendedPaymentMethod.PARTIAL_PAYMENT,
        RecommendedPaymentMethod.INSTALLMENTS,
        RecommendedPaymentMethod.WAIT,
        RecommendedPaymentMethod.NOT_RECOMMENDED,
    )
    assert len(dec_res.decision_explanation) > 0

    # Validate output contract using a synthetic row
    print("[SMOKE] Validating output contract schema...")
    dummy_row = OutputRow(
        request_id="request_smoke_01",
        amount_safe_to_pay=Decimal("5000"),
        affordability_status=AffordabilityStatus.AFFORDABLE_NOW,
        recommended_payment_method=RecommendedPaymentMethod.FULL_PAYMENT,
        payment_plan="2026-09-13:5000",
        earliest_date_for_full_payment=first_req.request_date,
        spending_changes_needed="none",
        decision_explanation="Smoke test synthetic verification row.",
    )
    validate_output_rows([dummy_row])

    print("[SMOKE] All checks passed successfully!")
    return 0


def run_validate_only(loader: DatasetLoader) -> int:
    """Validate dataset structure and file presence."""
    print(f"[VALIDATE] Validating dataset at: {loader.dataset_dir}")
    missing = loader.check_missing_files()
    if missing:
        print(f"[ERROR] Missing required dataset files: {', '.join(missing)}", file=sys.stderr)
        return 1

    requests = loader.load_all_requests()
    profiles = loader.load_all_profiles()
    print(f"[VALIDATE] Dataset valid. Requests: {len(requests)}, Profiles: {len(profiles)}.")
    return 0


def run_audit_command(dataset_dir: Path) -> int:
    """Load dataset into repository and print formatted audit summary."""
    try:
        repo = DatasetRepository.load_from_dir(dataset_dir)
        audit_results = run_dataset_audit(repo)
        print(format_audit_report(audit_results))
        return 0
    except Exception as e:
        print(f"[ERROR] Audit failed: {e}", file=sys.stderr)
        return 1


def run_audit_evidence_command(dataset_dir: Path) -> int:
    """Audit unstructured evidence extraction, image resolution, and lifecycle linkages."""
    try:
        repo = DatasetRepository.load_from_dir(dataset_dir)
        img_extractor = ImageEvidenceExtractor()
        msg_extractor = MessageEvidenceExtractor()

        # Check image resolution
        blank_events = [e for e in repo.all_events if e.amount is None]
        resolved_blanks = []
        for event in blank_events:
            evidence = img_extractor.get_by_event_id(event.event_id)
            source = repo.get_image_for_event(event.event_id)
            if (
                evidence is not None
                and source is not None
                and evidence.image_id == source.image_id
                and evidence.user_id == event.user_id
                and (dataset_dir / "media" / "images" / f"{source.image_id}.png").is_file()
            ):
                resolved_blanks.append(event)

        # Check messages
        all_msgs = msg_extractor.all_records()
        source_messages = {
            message.message_id: message.message_text for message in repo.all_messages
        }
        cached_messages = {message.message_id: message.raw_text for message in all_msgs}
        source_message_ids = set(source_messages)
        cached_message_ids = set(cached_messages)
        unclassified_messages = [
            message
            for message in all_msgs
            if message.evidence_type == EvidenceType.GENERAL_NOTIFICATION
        ]

        # Check total recurrence patterns across users
        total_recurrence_patterns = 0
        neutralized_transfer_ids: set[str] = set()
        transfer_message_count = 0
        for uid in repo.all_profiles:
            evs = repo.get_events_for_user(uid)
            u_msgs = msg_extractor.get_for_user(uid)
            pats = detect_recurrence_patterns(evs, u_msgs)
            total_recurrence_patterns += len(pats)
            transfer_message_count += sum(
                message.evidence_type == EvidenceType.INTERNAL_TRANSFER for message in u_msgs
            )
            neutralized_transfer_ids.update(
                resolve_event_lifecycles(evs, u_msgs).neutralized_internal_transfer_ids
            )

        linked_count = sum(event.linked_event_id is not None for event in repo.all_events)
        unresolved_blanks = len(blank_events) - len(resolved_blanks)
        cache_id_mismatch = source_message_ids.symmetric_difference(cached_message_ids)
        cache_text_mismatch = sum(
            source_messages[message_id] != cached_messages[message_id]
            for message_id in source_message_ids & cached_message_ids
        )
        errors = unresolved_blanks + len(cache_id_mismatch) + cache_text_mismatch
        resolved_transfer_pairs = len(neutralized_transfer_ids) // 2
        transfer_ambiguities = max(0, transfer_message_count - resolved_transfer_pairs)
        warnings = len(unclassified_messages) + transfer_ambiguities
        status = "PASS" if errors == 0 else "ATTENTION"

        print("==================================================================")
        print("          ORCHA EVIDENCE & LEDGER AUDIT")
        print("==================================================================")
        print(f"Status: {status} ({errors} errors, {warnings} warnings)\n")
        print("--- UNSTRUCTURED EVIDENCE ---")
        print(f"  Messages Total           : {len(repo.all_messages)}")
        print(f"  Cache Records            : {len(all_msgs)}")
        print(f"  Classified Evidence      : {len(all_msgs) - len(unclassified_messages)}")
        print(f"  Informational/Unclassified: {len(unclassified_messages)}")
        print(f"  Images Total             : {len(repo.all_images)}")
        print(f"  Images Resolved          : {img_extractor.total_resolved}")
        resolved_count = len(resolved_blanks)
        total_blanks = len(blank_events)
        resolved_pct = (100 * resolved_count / total_blanks) if total_blanks else 100
        print(
            f"  Blank Amounts Resolved   : {resolved_count} / {total_blanks} "
            f"({resolved_pct:.0f}% resolved)\n"
        )
        print("--- LIFECYCLE & RECURRENCE ---")
        print(f"  Linked Lifecycle Records : {linked_count}")
        print(f"  Recurring Patterns Active: {total_recurrence_patterns}")
        print(f"  Internal Transfers Neutral: {resolved_transfer_pairs} verified pairs")
        print(f"  Unresolved Transfer Evidence: {transfer_ambiguities}")
        print("==================================================================")
        return 0 if errors == 0 else 1
    except Exception as e:
        print(f"[ERROR] Evidence audit failed: {e}", file=sys.stderr)
        return 1


def run_resolve_user_command(dataset_dir: Path, user_id: str) -> int:
    """Resolve and display canonical financial ledger breakdown for a single user."""
    try:
        repo = DatasetRepository.load_from_dir(dataset_dir)
        if user_id not in repo.all_profiles:
            print(f"[ERROR] User ID '{user_id}' not found in dataset.", file=sys.stderr)
            return 1

        prof = repo.get_profile(user_id)
        # Find request date if user has a request, else default to today
        user_reqs = [r for r in repo.all_requests if r.user_id == user_id]
        req_date = user_reqs[0].request_date if user_reqs else date.today()
        req_id = user_reqs[0].request_id if user_reqs else None

        resolved = resolve_canonical_ledger(
            repository=repo,
            user_id=user_id,
            request_date=req_date,
            request_id=req_id,
        )

        inflows = [e for e in resolved if e.is_future_cash_inflow]
        outflows = [e for e in resolved if e.is_future_cash_outflow]
        historical = [
            e
            for e in resolved
            if e.forecast_behavior == ForecastBehavior.HISTORICAL_ALREADY_IN_BALANCE
        ]
        ignored = [
            e
            for e in resolved
            if e.forecast_behavior
            in (
                ForecastBehavior.IGNORED_PENDING_CREDIT,
                ForecastBehavior.IGNORED_CANCELLED,
                ForecastBehavior.IGNORED_FAILED,
                ForecastBehavior.IGNORED_UNREALIZED,
                ForecastBehavior.IGNORED_NON_CASH,
            )
        ]

        total_inflow = sum((e.amount_home_currency for e in inflows), Decimal("0"))
        total_outflow = sum((e.amount_home_currency for e in outflows), Decimal("0"))

        print("==================================================================")
        print(f"        CANONICAL LEDGER RESOLUTION: {user_id}")
        print("==================================================================")
        print(f"Home Currency               : {prof.home_currency}")
        print(f"Reference Request Date      : {req_date.isoformat()}")
        avail_str = f"{prof.current_available_balance:,.2f} {prof.home_currency}"
        print(f"Current Available Balance   : {avail_str}")
        min_bal_str = f"{prof.minimum_balance_to_keep:,.2f} {prof.home_currency}\n"
        print(f"Minimum Balance to Keep     : {min_bal_str}")
        print("--- RESOLVED EVENTS BREAKDOWN ---")
        print(f"  Total Resolved Events     : {len(resolved)}")
        print(f"  Historical (in balance)   : {len(historical)}")
        inflow_str = f"{total_inflow:,.2f} {prof.home_currency}"
        print(f"  Future Confirmed Inflows  : {len(inflows)} (Total: {inflow_str})")
        outflow_str = f"{total_outflow:,.2f} {prof.home_currency}"
        print(f"  Future Obligations/Outflow: {len(outflows)} (Total: {outflow_str})")
        print(f"  Ignored / Excluded Events : {len(ignored)}")
        print("==================================================================")
        return 0
    except Exception as e:
        print(f"[ERROR] Resolve user failed: {e}", file=sys.stderr)
        return 1


def run_forecast_command(dataset_dir: Path, request_id: str) -> int:
    """Run 90-day cash-flow simulation and baseline affordability for a specific request."""
    try:
        repo = DatasetRepository.load_from_dir(dataset_dir)
        try:
            req = repo.get_request(request_id)
        except KeyError:
            print(f"[ERROR] Request ID '{request_id}' not found in dataset.", file=sys.stderr)
            return 1

        prof = repo.get_profile(req.user_id)
        engine = BaselineEngine(repo)
        baseline = engine.evaluate(request_id)
        sim = baseline.baseline_simulation
        assert sim is not None
        start_date, end_date = get_forecast_window(req.request_date, horizon_days=90)

        earliest_str = (
            baseline.earliest_date_for_full_payment.isoformat()
            if baseline.earliest_date_for_full_payment
            else "None within 90 days"
        )

        print("==================================================================")
        print(f"        90-DAY CASH-FLOW FORECAST: {req.request_id}")
        print("==================================================================")
        print(f"User ID                     : {req.user_id}")
        print(f"Home Currency               : {prof.home_currency}")
        print(f"Request Date                : {req.request_date.isoformat()}")
        amt_str = f"{req.requested_amount:,.2f} {prof.home_currency}"
        print(f"Requested Amount            : {amt_str}")
        print(f"Desired Completion Date     : {req.desired_completion_date.isoformat()}")
        print(f"Allows Partial Payment      : {req.allows_partial_payment}")
        avail_str = f"{prof.current_available_balance:,.2f} {prof.home_currency}"
        print(f"Current Available Balance   : {avail_str}")
        min_bal_str = f"{prof.minimum_balance_to_keep:,.2f} {prof.home_currency}"
        print(f"Minimum Balance to Keep     : {min_bal_str}\n")
        print("--- 90-DAY SIMULATION & CAPACITY ---")
        window_str = f"{start_date.isoformat()} to {end_date.isoformat()} (90 days)"
        print(f"  Forecast Window           : {window_str}")
        min_proj_str = f"{sim.min_balance_projected:,.2f} {prof.home_currency}"
        print(f"  Projected Minimum Balance : {min_proj_str} (on {sim.min_balance_date})")
        min_head_str = f"{sim.min_headroom_projected:,.2f} {prof.home_currency}"
        print(f"  Projected Minimum Headroom: {min_head_str} (on {sim.min_headroom_date})")
        safe_str = f"{baseline.amount_safe_to_pay:,.2f} {prof.home_currency}"
        print(f"  Amount Safe to Pay Today  : {safe_str}")
        print(f"  Earliest Safe Full Payment: {earliest_str}")
        print(f"  Breach Days Detected      : {len(sim.breach_dates)}")
        print(f"  Baseline Safe (No Payment): {sim.is_safe}")
        print("==================================================================")
        return 0
    except Exception as e:
        print(f"[ERROR] Forecast failed: {e}", file=sys.stderr)
        return 1


def run_check_baselines_command(dataset_dir: Path) -> int:
    """Evaluate baseline affordability across all 25 sample requests and report match rates."""
    import csv

    sample_file = dataset_dir / "sample_requests.csv"
    if not sample_file.is_file():
        print(f"[ERROR] Sample requests file not found: {sample_file}", file=sys.stderr)
        return 1

    try:
        repo = DatasetRepository.load_from_dir(dataset_dir, include_samples=True)
        engine = BaselineEngine(repo)

        with sample_file.open("r", encoding="utf-8-sig") as f:
            samples = list(csv.DictReader(f))

        safe_matches = 0
        earliest_matches = 0
        total = len(samples)

        print("==================================================================")
        print("         SAMPLE REQUESTS BASELINE AFFORDABILITY CHECK")
        print("==================================================================")
        print(f"{'Request ID':<12} {'Safe Match':<12} {'Earliest Match':<16} {'Notes'}")
        print("-" * 66)

        for s in samples:
            rid = s["request_id"]
            expected_safe = Decimal(s["amount_safe_to_pay"])
            expected_earliest = s["earliest_date_for_full_payment"].strip() or None

            b = engine.evaluate_sample(rid)
            actual_safe = b.amount_safe_to_pay
            actual_earliest = (
                b.earliest_date_for_full_payment.isoformat()
                if b.earliest_date_for_full_payment
                else None
            )

            sm = actual_safe == expected_safe
            em = actual_earliest == expected_earliest

            if sm:
                safe_matches += 1
            if em:
                earliest_matches += 1

            note = ""
            if not sm:
                note += f"safe: {actual_safe} vs exp {expected_safe}"
            if not em:
                sep = "; " if note else ""
                note += f"{sep}earliest: {actual_earliest} vs exp {expected_earliest}"

            safe_status = "MATCH" if sm else "DIFF"
            earliest_status = "MATCH" if em else "DIFF"
            print(f"{rid:<12} {safe_status:<12} {earliest_status:<16} {note}")

        print("==================================================================")
        print(
            f"Summary: Safe Matches: {safe_matches}/{total} "
            f"({100 * safe_matches / total:.0f}%) | "
            f"Earliest Matches: {earliest_matches}/{total} "
            f"({100 * earliest_matches / total:.0f}%)"
        )
        print("Note: Diffs reflect sample cases requiring optional spending changes")
        print("      or custom plan adjustments (e.g. stop/reduce actions).")
        print("==================================================================")
        return 0
    except Exception as e:
        print(f"[ERROR] Baseline check failed: {e}", file=sys.stderr)
        return 1


def run_check_samples_command(dataset_dir: Path) -> int:
    """Evaluate full decision planning across all 25 sample requests and report accuracy."""
    import csv

    sample_file = dataset_dir / "sample_requests.csv"
    if not sample_file.is_file():
        print(f"[ERROR] Sample requests file not found: {sample_file}", file=sys.stderr)
        return 1

    try:
        repo = DatasetRepository.load_from_dir(dataset_dir, include_samples=True)
        from orcha.planning.engine import DecisionEngine

        engine = DecisionEngine(repo)

        with sample_file.open("r", encoding="utf-8-sig") as f:
            samples = list(csv.DictReader(f))

        field_matches = {column: 0 for column in OUTPUT_COLUMNS}
        exact_rows = 0
        total = len(samples)

        print("==================================================================")
        print("         SAMPLE REQUESTS FULL DECISION PLANNING CHECK")
        print("==================================================================")
        print(f"{'Request ID':<14} {'Exact fields':<14} Mismatches")
        print("-" * 75)

        for s in samples:
            rid = s["request_id"]
            actual = engine.evaluate_sample_request(rid).to_csv_dict()
            expected = {column: (s.get(column) or "").strip() for column in OUTPUT_COLUMNS}
            # Normalize only representation, never meaning or labels.
            actual["amount_safe_to_pay"] = str(Decimal(actual["amount_safe_to_pay"]))
            expected["amount_safe_to_pay"] = str(Decimal(expected["amount_safe_to_pay"]))
            actual["decision_explanation"] = " ".join(actual["decision_explanation"].split())
            expected["decision_explanation"] = " ".join(expected["decision_explanation"].split())
            mismatches = []
            for column in OUTPUT_COLUMNS:
                if actual[column] == expected[column]:
                    field_matches[column] += 1
                else:
                    mismatches.append(column)
            if not mismatches:
                exact_rows += 1
            print(
                f"{rid:<14} {len(OUTPUT_COLUMNS) - len(mismatches)}/{len(OUTPUT_COLUMNS):<12} "
                f"{', '.join(mismatches) or 'none'}"
            )

        print("==================================================================")
        print(f"Exact rows: {exact_rows}/{total}")
        print(
            "Per-field: "
            + " | ".join(f"{column}={field_matches[column]}/{total}" for column in OUTPUT_COLUMNS)
        )
        print("==================================================================")
        return 0
    except Exception as e:
        print(f"[ERROR] Sample decision check failed: {e}", file=sys.stderr)
        return 1


def run_decision_command(dataset_dir: Path, request_id: str) -> int:
    """Evaluate and print full decision recommendation for a specific request."""
    try:
        repo = DatasetRepository.load_from_dir(dataset_dir)
        from orcha.planning.engine import DecisionEngine

        engine = DecisionEngine(repo)
        res = engine.evaluate_request(request_id)
        req = repo.get_request(request_id)
        prof = repo.get_profile(req.user_id)

        print("==================================================================")
        print(f"         DECISION EVALUATION: {request_id}")
        print("==================================================================")
        print(f"User ID:                    {req.user_id}")
        print(f"Request Date:               {req.request_date}")
        print(f"Requested Amount:           {prof.home_currency} {req.requested_amount}")
        print(f"Desired Completion Date:    {req.desired_completion_date}")
        print(f"Allows Partial Payment:     {req.allows_partial_payment}")
        print(f"Request Text:               {req.request_text}")
        print("-" * 66)
        print(f"Amount Safe To Pay:         {prof.home_currency} {res.amount_safe_to_pay}")
        print(f"Affordability Status:       {res.affordability_status.value}")
        print(f"Recommended Payment Method: {res.recommended_payment_method.value}")
        print(f"Payment Plan:               {res.payment_plan}")
        earliest_str = (
            res.earliest_date_for_full_payment.isoformat()
            if res.earliest_date_for_full_payment
            else "none"
        )
        print(f"Earliest Date Full Payment: {earliest_str}")
        print(f"Spending Changes Needed:    {res.spending_changes_needed}")
        print("-" * 66)
        print(f"Decision Explanation:\n  {res.decision_explanation}")
        print("==================================================================")
        return 0
    except Exception as e:
        print(f"[ERROR] Decision evaluation failed: {e}", file=sys.stderr)
        return 1


def run_generate_command(dataset_dir: Path, output_path: Path) -> int:
    """Generate final production output after independent verification."""
    try:
        summary = generate_production_output(dataset_dir, output_path)
        print(f"[GENERATE] Wrote {summary.rows} validated predictions to {output_path}")
        print(f"[GENERATE] Statuses: {summary.status_counts}")
        print(f"[GENERATE] Methods: {summary.method_counts}")
        print(f"[GENERATE] Currencies: {summary.currency_counts}")
        return 0
    except Exception as error:
        print(f"[ERROR] Final generation failed: {error}", file=sys.stderr)
        return 1


def run_validate_output_command(dataset_dir: Path, output_path: Path) -> int:
    """Validate final serialized output with a fresh production repository."""
    try:
        summary = validate_serialized_output(output_path, dataset_dir)
        print(f"[OUTPUT] Validated {summary.rows} rows in {output_path}")
        return 0
    except Exception as error:
        print(f"[ERROR] Output validation failed: {error}", file=sys.stderr)
        return 1


def run_safe_amount_audit_command(dataset_dir: Path) -> int:
    """Write a report that uses sample labels only after calculations complete."""
    try:
        summary = sample_safe_amount_report(
            dataset_dir, Path("evaluation") / "safe_amount_audit.md"
        )
        print(f"[AUDIT] Safe amount matches: {summary['safe_amount_matches']}/{summary['samples']}")
        return 0
    except Exception as error:
        print(f"[ERROR] Safe amount audit failed: {error}", file=sys.stderr)
        return 1


def run_earliest_date_audit_command(dataset_dir: Path) -> int:
    """Write a report that uses labels only after earliest dates are calculated."""
    try:
        summary = sample_earliest_date_report(
            dataset_dir, Path("evaluation") / "earliest_date_audit.md"
        )
        print(f"[AUDIT] Earliest-date matches: {summary['earliest_matches']}/{summary['samples']}")
        return 0
    except Exception as error:
        print(f"[ERROR] Earliest-date audit failed: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = AppConfig.from_env_or_args(
        dataset=args.dataset,
        output=args.output,
        validate_only=args.validate_only,
        smoke=args.smoke,
        audit_data=args.audit_data,
        audit_evidence=args.audit_evidence,
        resolve_user=args.resolve_user,
        forecast_request_id=args.forecast,
        check_baselines=args.check_baselines,
        check_samples=args.check_samples,
        decision_request_id=args.decision,
        generate_output=args.generate,
        validate_output=args.validate_output,
        audit_safe_amounts=args.audit_safe_amounts,
        audit_earliest_dates=args.audit_earliest_dates,
    )

    loader = DatasetLoader(config.dataset_dir)

    try:
        if config.decision_request_id:
            return run_decision_command(config.dataset_dir, config.decision_request_id)

        if config.generate_output:
            return run_generate_command(config.dataset_dir, config.output_path)

        if config.validate_output:
            return run_validate_output_command(config.dataset_dir, config.output_path)

        if config.audit_safe_amounts:
            return run_safe_amount_audit_command(config.dataset_dir)

        if config.audit_earliest_dates:
            return run_earliest_date_audit_command(config.dataset_dir)

        if config.check_samples:
            return run_check_samples_command(config.dataset_dir)

        if config.forecast_request_id:
            return run_forecast_command(config.dataset_dir, config.forecast_request_id)

        if config.check_baselines:
            return run_check_baselines_command(config.dataset_dir)

        if config.resolve_user:
            return run_resolve_user_command(config.dataset_dir, config.resolve_user)

        if config.audit_evidence:
            return run_audit_evidence_command(config.dataset_dir)

        if config.audit_data:
            return run_audit_command(config.dataset_dir)

        if config.smoke:
            return run_smoke_test(config.dataset_dir)

        if config.validate_only:
            return run_validate_only(loader)

        # Default action: validate inputs and report available engine capabilities
        print("[INFO] Running Orcha financial assistant")
        missing = loader.check_missing_files()
        if missing:
            print(f"[ERROR] Missing required dataset files: {', '.join(missing)}", file=sys.stderr)
            return 1

        requests = loader.load_all_requests()
        print(f"[INFO] Dataset ready. {len(requests)} requests detected.")
        print(
            "[INFO] The engine supports 90-day deterministic simulation, "
            "minimum-balance enforcement, and payment planning."
        )
        print("[INFO] Use --decision REQUEST_ID for a verified payment recommendation.")
        return 0

    except Exception as e:
        print(f"[ERROR] Execution failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
