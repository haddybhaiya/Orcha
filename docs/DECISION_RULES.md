# Decision Rules and Plan Ranking

This document defines the deterministic rules for plan evaluation, affordability status determination, plan ranking, and conflict resolution.

---

## 1. Affordability Status Criteria

| Status | Condition |
| --- | --- |
| `affordable_now` | Full payment is safe on `request_date` without optional spending changes, and the user accepts `full_payment`. |
| `affordable_with_plan` | Full amount is completed safely on or before `desired_completion_date` via partial payment, an eligible installment plan, or permitted spending changes (`stop`/`reduce_to`). |
| `affordable_later` | The full amount is safe to pay as a single lump sum on a future date without spending changes, and user accepts `full_payment`, but cannot safely pay today. |
| `not_affordable` | The full requested amount cannot be safely completed within the 90-day forecast window under any eligible plan or permitted spending changes. |

---

## 2. Payment Method Eligibility

1. **Immediate Methods** (`full_payment`, `partial_payment`, `installments`):
   - Only eligible if present in `payment_methods_user_will_consider`.
   - Installments further require the installment duration in months $\le \text{max\_installment\_months}$.
2. **`wait`**:
   - Eligible when `earliest_date_for_full_payment` exists, is after `request_date`, and the user accepts `full_payment`.
3. **`not_recommended`**:
   - Fallback when no safe eligible plan exists.

---

## 3. Plan Ranking Order

When multiple eligible plans are determined to be safe by the 90-day cash-flow simulation, rank them in this strict order:

1. **Completion Deadline**: Complete the full request on or before `desired_completion_date`.
2. **Zero Spending Changes**: Prefer plans requiring `none` for `spending_changes_needed`.
3. **Minimize Total Cost**: Prefer plans with lower total payable amount (including financing fees).
4. **Earliest Start Date**: Prefer plans whose first payment occurs earlier.
5. **Fewer Payments**: Prefer plans with fewer total payment installments.
6. **Tie-Breaker**: Lowest `payment_option_id` lexicographically.

---

## 4. Conflict Resolution Hierarchy

When data points, messages, or transaction records conflict, apply the following precedence:

1. **Explicit Override**: Explicit cancellation, settlement confirmation, or amendment takes precedence.
2. **Newest Timestamp**: A newer record from the same source overrides an older record.
3. **Settled State**: A settled bank/ledger event overrides an unconfirmed estimate, forecast, or informal notice.
4. **Conservatism Principle**: When a conflict cannot be resolved, adopt the financially safer interpretation (higher expense, lower liquid balance, later income date).