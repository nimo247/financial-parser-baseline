# Reference provenance and audit

## Method

The assistant rendered the original PDF and visually read the table. It entered
labels, both raw amount columns, numeric interpretations, row types, indentation
depths, and explicit parent IDs into `reference/manual_reference.tsv` before running
the implemented baseline against it. The rendered page was used to check the
entered values and structure. The earlier exploratory extraction was visible in
the conversation, so this is not a blind annotation process.

`reference/build_reference.py` serializes those annotations. It does not calculate
the expected numeric amounts from raw text and does not infer parent IDs from PDF
geometry. Its only normalization step is NFKC on the manually entered labels;
paths are built from the explicitly assigned parent graph.

This is AI-assisted visual transcription and review by the SAME assistant that
wrote the implementation. It is independent of the implemented parser's output,
but is NOT independent human annotation, a second reviewer, or a held-out test.
The machine-readable provenance records that limitation.

## Checked source facts

- One physical PDF page; printed page 4; correction marker `（訂正後）`.
- Unit `千円`; dates 2025-03-31 and 2026-03-31.
- 43 body rows, including six blank-valued section headers.
- 86 period cells: 72 numeric, 2 explicit dashes, 12 blanks.
- Allowance row: `△2,979` and `△0` (preserve the negative-zero marker).
- Construction in progress: `－` and `4,553`.
- Long-term loans: `－` and `62,000`.
- Four accumulated-depreciation rows belong to distinct gross asset rows.
- Tangible and intangible lease assets have different parents.
- Net rows remain children of their gross asset row in the display hierarchy;
  that relationship must not be mistaken for an arithmetic summation rule.
- Original reported figures, including residuals discussed below, were preserved.

Source SHA-256:
`0764bba6f5f0e7984a837e4cc19d8bb95db4a7ac22c26f18c95bbe652c983c74`

## Source residuals to retain for the next stage

Residual means reported result minus calculation, in displayed thousand-yen units.
These observations are retained in the implemented validator and regression tests;
see `VALIDATION.md` for coverage, assumptions, and handling of explicit dashes.

| Relationship | Period | Calculation | Reported | Residual |
| --- | --- | ---: | ---: | ---: |
| Current assets: sum detail rows | 2025 | 5,863,681 | 5,863,684 | +3 |
| Current assets: sum detail rows | 2026 | 3,377,405 | 3,377,407 | +2 |
| Fixed assets: sum three reported category totals | 2025 | 1,670,424 | 1,670,426 | +2 |
| Total assets: current plus fixed | 2026 | 5,135,248 | 5,135,249 | +1 |
| Buildings: gross plus signed depreciation | 2026 | 239,829 | 239,828 | -1 |
| Tangible leases: gross plus signed depreciation | 2025 | 63,147 | 63,146 | -1 |
| Tangible leases: gross plus signed depreciation | 2026 | 41,873 | 41,872 | -1 |

Small residuals are consistent with presentation rounding or truncation, but their
cause is unverified. No figure was edited to eliminate a residual.

## Human review still needed

A human reviewer should compare every TSV row with the rendered page, including
the two raw columns, separately typed numeric values, and explicit parent IDs.
Record the reviewer, date, and corrections before describing this as independently
human-verified ground truth. Do not regenerate expected amounts from parser output.
