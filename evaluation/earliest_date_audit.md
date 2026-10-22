# Earliest Full-Payment Oracle Diagnostic

> Historical Orcha engine diagnostic from the earlier dataset. These results were
> not regenerated in this checkout. See [current status](../docs/CURRENT_STATE.md).

This is post-decision diagnostics only; production code never reads sample labels.

| request_id | expected | actual | independent actual | minimum balance | threshold | minimum date | confirmed credits | recurring events | evidence | suspected general-rule cause |
| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- |
| request_08 | 2025-04-15 | none | none | 1070.65 | 800 | 2025-02-13 | rec_salary_category_user_08_2025-02-15:1422.85, rec_salary_category_user_08_2025-03-15:1422.85, rec_salary_category_user_08_2025-04-15:1422.85 | 157 events: event_652, event_678, event_704, event_653, event_679 | message_06 | message/image amendment timing or amount |
| request_11 | 2025-07-15 | 2025-05-15 | 2025-05-15 | 46611424.54 | 34140600 | 2025-05-14 | rec_salary_base_salary_user_11_2025-05-15:23256000, rec_salary_monthly_sales_commission_user_11_2025-05-24:8502888.2, rec_salary_performance_commission_user_11_2025-05-24:15989420 | 134 events: event_981, event_950, event_968, event_951, event_969 | none | recurrence timing or cadence reconstruction |
| request_12 | 2026-04-05 | none | none | 100990.43 | 43200 | 2026-07-01 | none | 97 events: event_1019, event_1037, event_1046, event_1020, event_1021 | none | no confirmed future income within the forecast |
| request_13 | 2024-05-15 | 2024-03-07 | 2024-03-07 | 2455.90 | 1300 | 2024-03-14 | event_1161:1343.54, rec_salary_primary_household_salary_user_13_2024-03-15:1343.54, rec_salary_second_household_income_user_13_2024-03-20:881.45 | 161 events: event_1096, event_1122, event_1148, event_1097, event_1123 | none | recurrence timing or cadence reconstruction |
| request_21 | 2026-04-15 | 2026-04-03 | 2026-04-03 | 3452.34 | 1800 | 2026-04-12 | event_1858:2256, rec_salary_category_user_21_2026-05-15:2256, rec_salary_category_user_21_2026-06-15:2256 | 102 events: event_1819, event_1837, event_1846, event_1820, event_1821 | none | recurrence timing or cadence reconstruction |

## Root-cause grouping

| suspected class | mismatch count |
| --- | ---: |
| message/image amendment timing or amount | 1 |
| no confirmed future income within the forecast | 1 |
| recurrence timing or cadence reconstruction | 3 |
