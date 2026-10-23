# Accounting validation

Run the default, conservative policy:

```bash
python validate.py
```

It reads `outputs/table.json` and writes `outputs/validation.json`. It does not read
the reference, reopen the PDF, or modify extracted values. It builds relations from
the row hierarchy and explicit Japanese subtotal/net/depreciation labels, not
hardcoded fixture row IDs or amounts.

## Relations

Six section totals and four net-asset groups are identified, each in two periods:
20 potential checks. Section components use child-section totals and, for gross
asset groups, net amounts instead of adding gross, depreciation, and net together.
Net checks add gross to the signed accumulated depreciation. Positive accumulated
depreciation is separately flagged for review.

The implementation supports the baseline's section/subtotal naming convention
and gross/depreciation/net pattern. Unsupported relations are reported as structural
issues, not treated as successful checks. This is not a general accounting engine.

## Tolerance assumption

For a relation with n displayed integer operands and one reported result, assume
each displayed quantity differs from its exact underlying quantity by less than
one displayed unit. If the exact underlying relation holds, the absolute residual
is less than n+1. The residual is integer-valued, so it is at most n. We therefore
use `abs(reported - sum(signed operands)) <= n` as a conservative conditional bound.

This rule was chosen from an explicit error model, not adjusted until the sample
passed. It does not establish how this issuer rounded or truncated its amounts.
All nonzero residuals are retained with "cause unverified". Figures are never fixed.

| Status | Meaning |
| --- | --- |
| `exact` | Reported result equals the calculation |
| `within_tolerance` | Nonzero residual within the assumed bound; cause unverified |
| `beyond_tolerance` | Residual exceeds that bound; investigate |
| `not_evaluated` | A required amount has no numeric interpretation |

All amounts, residuals, and tolerances remain in displayed thousand-yen units.
This arithmetic result is a diagnostic, not reference-based extraction accuracy.

## Dashes and missing amounts

Default `--dash-policy skip` preserves the meaning of an explicit dash as unknown
for numeric arithmetic. Two prior-year checks consequently remain unevaluated:
tangible assets (construction in progress has a dash) and investments/other assets
(long-term loans have a dash). `complete=false` exposes this incomplete coverage.

For a separately labelled sensitivity analysis only:

```bash
python validate.py --dash-policy assume-zero --output outputs/validation_assuming_dash_zero.json
```

This provisionally treats dash operands as zero and records the assumption on each
affected check. The original `raw`, `status`, and null `value` remain intact; a
separate `arithmetic_value` stores zero. Blank cells and missing reported totals are
never imputed. No claim is made that the issuer intended a zero.

## Results on the supplied page

| Policy | Exact | Within tolerance | Beyond tolerance | Not evaluated |
| --- | ---: | ---: | ---: | ---: |
| Default: skip dashes | 7 | 11 | 0 | 2 |
| Conditional: assume dash operands zero | 7 | 13 | 0 | 0 |

The nonzero residuals include current assets (+3 and +2), prior-year fixed assets
(+2), current-year assets (+1), and buildings/leases net figures (-1 where noted in
the reference audit). The output enumerates every identified relationship.

The CLI returns 1 on beyond-tolerance results, unexpected depreciation signs, or
unsupported relation structures; 2 on invalid input/graph or IO errors. Exit 0
means no such review trigger; it does not mean all relationships were evaluated
or the table is correct. Always inspect `complete` and `not_evaluated` as well.

## Calibration checks and blind spots

Regression tests retain the source residuals and check that a digit transposition
in cash (2,002,429 -> 2,002,492) produces a beyond-tolerance result. Removing a
depreciation minus marker produces a large discrepancy and a sign warning.
These mutations are made in extracted JSON; they test arithmetic detection, not
PDF extraction robustness. Real document perturbations belong to the next stage.

A one-unit cash error can remain within tolerance. Compensating errors can cancel.
Changing an amount and its reported total consistently may evade these checks.
Arithmetic cannot verify labels, period identity, all hierarchy decisions, or
negative zero. Those still need reference comparison or other review signals.
Zero beyond-tolerance findings must not be described as proof of correctness.
