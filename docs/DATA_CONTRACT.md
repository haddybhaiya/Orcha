# Data Contract

This document defines the schema, data types, and normalization rules for all datasets in `dataset/` and the evaluation output.

---

## 1. Input Datasets

### `dataset/requests.csv` (Evaluation Targets)
| Column | Type | Example | Description |
| --- | --- | --- | --- |
| `request_id` | `str` | `request_26` | Unique request identifier (must preserve string ID) |
| `user_id` | `str` | `user_26` | Identifier of requesting user |
| `request_date` | `date (YYYY-MM-DD)` | `2025-08-03` | Date of evaluation |
| `request_type` | `enum` | `family_transfer` | One of: `purchase`, `travel`, `education`, `family_transfer`, `debt_repayment`, `investment`, `housing`, `emergency_expense`, `other` |
| `requested_amount` | `Decimal` | `15656000` | Target expense amount in user home currency |
| `desired_completion_date` | `date (YYYY-MM-DD)` | `2025-10-07` | Target completion deadline |
| `allows_partial_payment` | `bool` | `false` | Whether partial payment is permitted by provider |
| `request_text` | `str` | `"..."` | Natural language text of the user request |

### `dataset/financial_profiles.csv`
| Column | Type | Description |
| --- | --- | --- |
| `user_id` | `str` | Unique user ID |
| `home_currency` | `str` | Currency code: `ZAR`, `IDR`, `EUR`, `INR`, `USD` |
| `current_available_balance` | `Decimal` | Starting liquid balance |
| `minimum_balance_to_keep` | `Decimal` | Minimum liquid balance safety floor |
| `financial_priorities` | `list[str]` | Pipe-separated priority categories |
| `expense_categories_to_protect` | `list[str]` | Non-negotiable spending categories |
| `expense_categories_user_is_willing_to_reduce` | `list[str]` | Categories eligible for `reduce_to` |
| `expense_categories_user_is_willing_to_stop` | `list[str]` | Categories eligible for `stop` |
| `payment_methods_user_will_consider` | `list[enum]` | Allowed payment methods (`full_payment`, `partial_payment`, `installments`) |
| `max_installment_months` | `Optional[int]` | Maximum tenure for installments (blank if installments rejected) |

### `dataset/financial_events.csv`
| Column | Type | Description |
| --- | --- | --- |
| `event_id` | `str` | Unique event ID |
| `user_id` | `str` | User ID |
| `event_type` | `enum` | `expense`, `debt_payment`, `subscription`, `income`, `refund`, `investment_purchase`, `investment_valuation`, `investment_sale` |
| `description` | `str` | Description |
| `category` | `str` | Expense or income category |
| `direction` | `enum` | `debit`, `credit`, `non_cash` |
| `amount` | `Optional[Decimal]` | Transaction amount; if blank, extract from linked image |
| `currency` | `str` | Transaction currency |
| `event_date` | `date` | Transaction initiation date |
| `settlement_date` | `Optional[date]` | Actual settlement date |
| `status` | `enum` | `settled`, `cancelled`, `pending`, `scheduled`, `failed`, `unrealized` |
| `linked_event_id` | `Optional[str]` | Earlier event in same lifecycle |
| `flexibility` | `Optional[enum]` | `fixed`, `stoppable`, `reducible`, `reducible_or_stoppable` |
| `minimum_allowed_amount` | `Optional[Decimal]` | Minimum lower bound for reduction |

### `dataset/request_payment_options.csv`
| Column | Type | Description |
| --- | --- | --- |
| `payment_option_id` | `str` | Unique option ID |
| `request_id` | `str` | Request ID |
| `payment_method` | `enum` | `full_payment`, `installments` |
| `payment_amount` | `Decimal` | Amount per payment |
| `number_of_payments` | `int` | Payment count |
| `first_payment_date` | `date` | Start date |
| `payment_frequency_days` | `Optional[int]` | Days between payments (blank for full_payment) |
| `financing_fee` | `Decimal` | Financing fee included |
| `total_payable_amount` | `Decimal` | Total cost |

### `dataset/exchange_rates.csv`
| Column | Type | Description |
| --- | --- | --- |
| `rate_date` | `date` | Conversion rate date |
| `from_currency` | `str` | Source currency |
| `to_currency` | `str` | Target currency |
| `rate` | `Decimal` | Conversion multiplier ($\text{target} = \text{source} \times \text{rate}$) |

### `dataset/messages.csv` & `dataset/images.csv`
Provide supporting contextual evidence linking to `request_id` and/or `related_event_id`.

---

## 2. Required Output Contract (`output.csv`)

The output CSV must contain exactly 8 columns in this order:

```text
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

### Allowed Enum Values
- **`affordability_status`**:
  - `affordable_now`
  - `affordable_with_plan`
  - `affordable_later`
  - `not_affordable`
- **`recommended_payment_method`**:
  - `full_payment`
  - `partial_payment`
  - `installments`
  - `wait`
  - `not_recommended`

### Formatting Constraints
- `amount_safe_to_pay`: Decimal number formatted cleanly (no scientific notation, $0 \le \text{amount} \le \text{requested\_amount}$).
- `payment_plan`: Chronological `YYYY-MM-DD:amount|...` or `none`.
- `earliest_date_for_full_payment`: `YYYY-MM-DD` or empty string. Equal to `request_date` when `affordable_now`.
- `spending_changes_needed`: `none` or up to 3 actions (`stop:<event_id>` or `reduce_to:<event_id>:<new_amount>`).
- `decision_explanation`: Concise, factual explanation.
---

## 3. Normalization Pipeline & Real Schema Verification

### Data Pipeline Architecture: Raw → Typed → Normalized
1. **Raw CSV**: Ingested via UTF-8 DictReader preserving exact string identifiers and date strings.
2. **Typed Domain Models**: String amounts converted to exact `Decimal`; dates to `datetime.date`.
3. **Canonical Normalized Models**: Events mapped to user `home_currency` via `DatasetRepository` and `ExchangeRateResolver`.

### Discovered Real Schema Statistics
- **Evaluation Requests**: 250 rows (`request_26` through `request_275`).
- **Sample Requests**: 25 rows (`request_01` through `request_25`).
- **Financial Profiles**: 275 users, zero duplicate IDs, zero missing profiles.
- **Financial Events**: 25,342 rows.
  - `event_type`: `expense` (20,525), `subscription` (2,488), `income` (1,696), `debt_payment` (567), `investment_purchase` (29), `refund` (22), `investment_valuation` (10), `investment_sale` (5).
  - `status`: `settled` (25,148), `pending` (71), `scheduled` (70), `cancelled` (22), `failed` (21), `unrealized` (10).
  - `direction`: `debit` (23,609), `credit` (1,723), `non_cash` (10).
  - `flexibility`: `fixed` (21,138), `reducible` (2,682), `stoppable` (1,297), `reducible_or_stoppable` (225).
  - `linked_event_id`: 58 events point to earlier lifecycle events (0 dangling references).

### Foreign Currency & Exchange Rate Resolution
- **Currencies**: `EUR`, `IDR`, `INR`, `USD`, `ZAR`.
- **Exchange Rates**: 134 records covering 5 currency pairs across 39 distinct settlement dates:
  - `EUR -> USD`, `EUR -> ZAR`, `USD -> EUR`, `USD -> IDR`, `USD -> INR`.
- **Foreign Currency Events**: Exactly 140 events occur in non-home currency:
  - USD -> INR: 54 events
  - USD -> IDR: 28 events
  - USD -> EUR: 22 events
  - EUR -> ZAR: 20 events
  - EUR -> USD: 16 events
  - **100% direct coverage**: All 140 foreign events have an exact matching direct exchange rate on their settlement date.

### Blank Event Amounts & Multimodal Linkage
- Exactly 16 financial events have a blank `amount`.
- 100% of these 16 events have a corresponding entry in `images.csv` and a PNG receipt in `dataset/media/images/<image_id>.png`.
- Blank amounts remain `None` in `NormalizedFinancialEvent.amount` and `amount_home_currency` until resolved from validated evidence.