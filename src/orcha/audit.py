"""Dataset integrity audit and diagnostic tools."""

from collections import Counter
from typing import Any

from orcha.repository import DatasetRepository

KNOWN_CURRENCIES = {"USD", "EUR", "INR", "ZAR", "IDR"}


def run_dataset_audit(repo: DatasetRepository) -> dict[str, Any]:
    """Perform comprehensive data integrity checks across all indexed entities in repo."""
    requests = repo.all_requests
    profiles = repo.all_profiles
    events = repo.all_events
    options = repo.all_payment_options
    messages = repo.all_messages
    images = repo.all_images
    fx = repo.fx_resolver

    # 1. Uniqueness / Duplicates
    req_ids = [r.request_id for r in requests]
    prof_uids = list(profiles.keys())
    event_ids = [e.event_id for e in events]
    opt_ids = [opt.payment_option_id for group in options.values() for opt in group]
    msg_ids = [m.message_id for m in messages]
    img_ids = [i.image_id for i in images]

    dup_reqs = [k for k, v in Counter(req_ids).items() if v > 1]
    dup_profs = [k for k, v in Counter(prof_uids).items() if v > 1]
    dup_events = [k for k, v in Counter(event_ids).items() if v > 1]
    dup_opts = [k for k, v in Counter(opt_ids).items() if v > 1]
    dup_msgs = [k for k, v in Counter(msg_ids).items() if v > 1]
    dup_imgs = [k for k, v in Counter(img_ids).items() if v > 1]

    # 2. Foreign Key Integrity
    all_uids = set(profiles.keys())
    all_eids = set(event_ids)
    all_rids = {r.request_id for r in requests} | {s.request_id for s in repo.sample_requests}

    missing_profile_requests = [r.request_id for r in requests if r.user_id not in all_uids]
    missing_profile_events = [e.event_id for e in events if e.user_id not in all_uids]
    requests_without_options = [
        r.request_id for r in requests if r.request_id not in options or not options[r.request_id]
    ]

    dangling_linked_events = [
        e.event_id for e in events if e.linked_event_id and e.linked_event_id not in all_eids
    ]
    dangling_msg_events = [
        m.message_id for m in messages if m.related_event_id and m.related_event_id not in all_eids
    ]
    dangling_msg_requests = [
        m.message_id for m in messages if m.request_id and m.request_id not in all_rids
    ]
    dangling_img_events = [
        i.image_id for i in images if i.related_event_id and i.related_event_id not in all_eids
    ]
    dangling_img_requests = [
        i.image_id for i in images if i.request_id and i.request_id not in all_rids
    ]

    # 3. Currency Audits
    event_currencies = Counter(e.currency for e in events)
    profile_currencies = Counter(p.home_currency for p in profiles.values())
    unknown_currencies = (
        set(event_currencies.keys()) | set(profile_currencies.keys())
    ) - KNOWN_CURRENCIES

    foreign_events = [e for e in events if e.is_foreign_currency]
    unresolved_fx_events = [
        e.event_id
        for e in foreign_events
        if e.amount is not None and e.amount_home_currency is None
    ]

    # 4. Blank Amounts & Multimodal Linkages
    blank_amount_events = [e.event_id for e in events if e.amount is None]
    img_linked_eids = {i.related_event_id for i in images if i.related_event_id}
    blank_amount_covered_by_image = [eid for eid in blank_amount_events if eid in img_linked_eids]
    blank_amount_uncovered = [eid for eid in blank_amount_events if eid not in img_linked_eids]

    # Distributions
    event_types = Counter(e.event_type.value for e in events)
    event_statuses = Counter(e.status.value for e in events)
    event_directions = Counter(e.direction.value for e in events)
    event_flexibilities = Counter(e.flexibility.value if e.flexibility else "none" for e in events)

    return {
        "counts": {
            "requests": len(requests),
            "profiles": len(profiles),
            "events": len(events),
            "payment_option_groups": len(options),
            "payment_options_total": len(opt_ids),
            "messages": len(messages),
            "images": len(images),
            "exchange_rate_pairs": len(fx.supported_pairs),
            "exchange_rate_dates": len(fx.supported_dates),
        },
        "duplicates": {
            "requests": dup_reqs,
            "profiles": dup_profs,
            "events": dup_events,
            "options": dup_opts,
            "messages": dup_msgs,
            "images": dup_imgs,
        },
        "integrity": {
            "requests_missing_profile": missing_profile_requests,
            "events_missing_profile": missing_profile_events,
            "requests_without_options": requests_without_options,
            "dangling_linked_events": dangling_linked_events,
            "dangling_msg_events": dangling_msg_events,
            "dangling_msg_requests": dangling_msg_requests,
            "dangling_img_events": dangling_img_events,
            "dangling_img_requests": dangling_img_requests,
            "unknown_currencies": list(unknown_currencies),
            "unresolved_fx_events": unresolved_fx_events,
        },
        "blank_amounts": {
            "total_blank": len(blank_amount_events),
            "covered_by_images": len(blank_amount_covered_by_image),
            "uncovered": blank_amount_uncovered,
        },
        "foreign_events": {
            "total_foreign": len(foreign_events),
            "covered_by_fx": len(foreign_events) - len(unresolved_fx_events),
        },
        "distributions": {
            "currencies": sorted(set(event_currencies.keys()) | set(profile_currencies.keys())),
            "event_types": dict(event_types),
            "event_statuses": dict(event_statuses),
            "event_directions": dict(event_directions),
            "event_flexibilities": dict(event_flexibilities),
        },
    }


def format_audit_report(result: dict[str, Any]) -> str:
    """Format audit results as a concise, readable summary string."""
    c = result["counts"]
    d = result["distributions"]
    b = result["blank_amounts"]
    fe = result["foreign_events"]
    integ = result["integrity"]

    has_errors = (
        any(bool(v) for k, v in integ.items() if isinstance(v, list))
        or any(bool(v) for k, v in result["duplicates"].items() if isinstance(v, list))
        or bool(b["uncovered"])
    )

    status_str = (
        "PASS (Zero defects detected)" if not has_errors else "ATTENTION (Anomalies detected)"
    )

    fx_pairs = c["exchange_rate_pairs"]
    fx_dates = c["exchange_rate_dates"]
    pay_opts = c["payment_options_total"]

    lines = [
        "==================================================================",
        "             ORCHA DATASET INTEGRITY AUDIT",
        "==================================================================",
        f"Status: {status_str}",
        "",
        "--- ENTITY TOTALS ---",
        f"  Evaluation Requests : {c['requests']}",
        f"  Financial Profiles  : {c['profiles']}",
        f"  Financial Events    : {c['events']}",
        f"  Payment Options     : {pay_opts}",
        f"  Messages            : {c['messages']}",
        f"  Image Records       : {c['images']}",
        f"  FX Pairs / Dates    : {fx_pairs} pairs / {fx_dates} dates",
        "",
        "--- DISTRIBUTIONS ---",
        f"  Currencies          : {', '.join(d['currencies'])}",
        f"  Event Types         : {len(d['event_types'])} types",
        f"  Event Statuses      : {len(d['event_statuses'])} statuses",
        f"  Event Directions    : {len(d['event_directions'])} directions",
        "",
        "--- DATA INTEGRITY & LINKAGES ---",
        (
            f"  Duplicate IDs       : req={len(result['duplicates']['requests'])}, "
            f"ev={len(result['duplicates']['events'])}"
        ),
        (
            f"  Missing Profiles    : requests={len(integ['requests_missing_profile'])}, "
            f"events={len(integ['events_missing_profile'])}"
        ),
        (
            f"  Dangling References : events={len(integ['dangling_linked_events'])}, "
            f"msgs={len(integ['dangling_msg_events'])}, imgs={len(integ['dangling_img_events'])}"
        ),
        (
            f"  Foreign Events      : total={fe['total_foreign']}, "
            f"fx_matches={fe['covered_by_fx']}, unresolved={len(integ['unresolved_fx_events'])}"
        ),
        (
            f"  Blank Event Amounts : total={b['total_blank']}, "
            f"in_images={b['covered_by_images']}, uncovered={len(b['uncovered'])}"
        ),
        "==================================================================",
    ]
    return "\n".join(lines)
