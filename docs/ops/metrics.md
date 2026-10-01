# Delivery and maintenance metrics

Written by `scripts/realm/realm dora --write`, which the realm-scheduled workflow runs on the first
of each month. DORA's four keys come from the release records and the incidents; churn and the
kinds of work from git. A rising share of corrective work is the early warning.

## 2026-09

| Measure | Value | How |
|---|---|---|
| Deployment frequency | 0 promotion(s) | promotions in the release records |
| Lead time for changes | no changes shipped | each shipped commit's time to its promotion |
| Change failure rate | no promotions | promotions rolled back, or named by an incident |
| Time to restore | no incidents closed | incidents' Opened to Closed |
| 14-day churn | 4.9% (2276 of 46403 lines) | lines deleted within 14 days of being added |
| Maintenance | new capability 30 · other 28 · corrective 15 · adaptive 2 · preventive 1 · perfective 1 | commit types (DESIGN.md §7.8) |
