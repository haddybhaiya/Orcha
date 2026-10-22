"""Daily cash-flow timeline aggregation for 90-day simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from orcha.ledger.models import ResolvedFinancialEvent


def get_forecast_window(request_date: date, horizon_days: int = 90) -> tuple[date, date]:
    """Return the inclusive [start, end] 90-day forecast window for a request."""
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be at least 1, got {horizon_days}")
    return request_date, request_date + timedelta(days=horizon_days - 1)


@dataclass
class DailyCashFlow:
    """Aggregated confirmed and pending cash flows for a specific calendar date."""

    inflows: Decimal = Decimal("0")
    outflows: Decimal = Decimal("0")
    inflow_event_ids: list[str] = field(default_factory=list)
    outflow_event_ids: list[str] = field(default_factory=list)


def group_cash_flows_by_date(
    resolved_events: list[ResolvedFinancialEvent],
    start_date: date,
    end_date: date,
) -> tuple[dict[date, DailyCashFlow], tuple[str, ...], tuple[str, ...]]:
    """Group resolved cash flows by date within the forecast window.

    Deterministic same-day event handling and input-order invariance:
    Events are sorted canonically by (settlement_date, canonical_event_id).
    """
    # Deterministic canonical sort guarantees input row order never affects results
    sorted_events = sorted(
        resolved_events,
        key=lambda e: (e.settlement_date, e.canonical_event_id),
    )

    flows: dict[date, DailyCashFlow] = {}
    included_ids: list[str] = []
    ignored_ids: list[str] = []

    for ev in sorted_events:
        if ev.is_ignored:
            ignored_ids.append(ev.canonical_event_id)
            continue

        eff_date = ev.settlement_date

        # Pending debits initiated before request_date that remain pending
        # are reserved immediately on start_date
        if ev.is_future_cash_outflow and eff_date < start_date:
            eff_date = start_date

        if eff_date < start_date or eff_date > end_date:
            ignored_ids.append(ev.canonical_event_id)
            continue

        if eff_date not in flows:
            flows[eff_date] = DailyCashFlow()

        if ev.is_future_cash_inflow:
            flows[eff_date].inflows += ev.amount_home_currency
            flows[eff_date].inflow_event_ids.append(ev.canonical_event_id)
            included_ids.append(ev.canonical_event_id)
        elif ev.is_future_cash_outflow:
            flows[eff_date].outflows += ev.amount_home_currency
            flows[eff_date].outflow_event_ids.append(ev.canonical_event_id)
            included_ids.append(ev.canonical_event_id)
        else:
            ignored_ids.append(ev.canonical_event_id)

    return flows, tuple(included_ids), tuple(ignored_ids)
