# Japanese Financial Table Parser

A reproducible baseline for extracting the supplied corrected Japanese consolidated
balance-sheet page into a traceable financial table. It preserves Japanese labels,
the two reporting periods, units, indentation hierarchy, negative markers, explicit
dashes, and blanks. Amounts are never changed to make totals balance.

## Current stage

Implemented: JSON Schema, separately entered visual reference, text-layer parser,
CSV/JSON exports, reference comparison, accounting diagnostics, page-level routing,
and fourteen synthetic PDF robustness scenarios with regression checks. A conservative
word-coordinate fallback supports borderless copies with the same declared structure.

The design and findings are in `docs/REPORT.md`. Independent human reference review
and attaching the actual complete AI chat log remain submission steps. OCR and VLM
execution are not implemented; the router recommends the next action.

## Quick start

Python 3.10+ is required. Run from this project's root directory in an activated
virtual environment:

```bash
python -m pip install -r requirements-dev.txt
python parse.py data/balance_sheet_after_correction.pdf --output outputs
python evaluate.py
python validate.py
python route.py data/balance_sheet_after_correction.pdf
python robustness.py
python -m unittest discover -s tests -v
```

Production extraction only needs `requirements.txt`; JSON Schema validation in the
tests additionally uses `jsonschema` from `requirements-dev.txt`. Synthetic PDF
generation/tests use the PyMuPDF development dependency. No API key or GPU is needed.
The default output files are:

| File | Contents |
| --- | --- |
| `outputs/table.json` | Metadata, ordered rows, hierarchy, typed values, source boxes |
| `outputs/table.csv` | Long-form records, one per row and period, with raw text and status |
| `outputs/page_1_wide.csv` | Three-column visual inspection table, retaining original amounts |
| `outputs/evaluation.json` | Reference comparison, metric counts, provenance, and mismatches |
| `outputs/validation.json` | Arithmetic diagnostics; default skips operands with explicit dashes |
| `outputs/validation_assuming_dash_zero.json` | Separately labelled conditional analysis with dash operands assumed zero |
| `outputs/routing.json` | Page-level action recommendations and diagnostic summaries |
| `outputs/robustness/report.json` | Fourteen synthetic routing scenarios, including accepted corruption blind spots |

CSV files are UTF-8 with BOM. Blank and dash values both have a null numeric value
in JSON and an empty numeric field in the long CSV, but their `status` and `raw`
fields distinguish them. The wide CSV is for inspection; JSON is authoritative for
hierarchy and typed semantics.

## Measured result on the supplied page

| Comparison | Correct / expected |
| --- | --- |
| Labels, row order, and hierarchy paths | 43 / 43 |
| Cell semantics, including path and reporting period | 86 / 86 |
| Numeric cells | 72 / 72 |
| Explicit dashes | 2 / 2 |
| Blank section cells | 12 / 12 |
| Negative markers, including negative zero | 10 / 10 |

Forty unittest cases pass, including mutation subcases that change an amount,
hierarchy, status, period ordering, negative-zero flag, and row coverage. These are
extraction/reference, arithmetic, routing, and synthetic PDF checks.

Arithmetic diagnostics identify 20 potential checks: 7 exact, 11 with nonzero
residuals within a documented conditional tolerance, and 2 skipped because a dash
has no numeric interpretation. No check is beyond tolerance on this page. This is
not proof of extraction correctness; see `docs/VALIDATION.md` for assumptions and
tested blind spots. No extracted value is corrected.

Fourteen synthetic PDF routing expectations are met. Two deliberately corrupted PDFs
are expected to be accepted (a one-unit error and compensating errors). This is
not a 100% error-detection result. See `docs/ROBUSTNESS.md` for the scenario table,
actual byte modifications, and limitations.
The four new borderless PDF fixtures are generated locally by `python robustness.py`;
their generator and results are committed, while the PDF payloads are excluded from Git.

This is a development-set result on one supplied page, not a generalization claim.
The same AI assistant authored the parser and the manually entered reference;
independent human verification is pending. See `docs/REFERENCE_AUDIT.md`.

## Extraction approach

1. Require a text layer. Prefer one detected three-column table per page; if no
   table is detected, try the conservative word-coordinate fallback.
2. Use pdfplumber's detected cell boundaries to assign each value to its column.
   Shaded rectangles and rules in this sample make default table detection work.
   We do not split flattened lines or select the last two numeric tokens.
3. Match date headers to column regions and read the title, explicit unit, correction
   marker, and printed page number. Dates and amounts are not hardcoded.
4. Normalize with NFKC for interpretation while retaining extracted `raw` strings.
   `raw` means text returned by the extractor, not PDF bytes or image glyphs.
5. Cluster label x-positions and use an indentation stack for parent/path assignment.
   Blank value rows are classified as sections; `合計` and `(純額)` identify subtotal
   and net rows. These are explicit baseline heuristics, not a financial ontology.
6. For borderless pages, group words into lines, identify the two period headers
   and date row, and infer numeric right-edge anchors from the body. Assign numeric
   and dash tokens by geometry. Reject ambiguous fragments, missing column evidence,
   crossing labels, partial amount rows, and outlying positions. Multiple or malformed
   detected tables still request review rather than silently using the fallback.
7. Export original and interpreted values with source regions and a PDF hash.
   Each page records `extraction_method`: `detected_cells` or `word_coordinates`.

The parser never reads `reference/`. The reference builder never imports the parser,
opens the PDF, or reads extraction outputs. Expected amounts and parent IDs were
entered separately in TSV; the builder only serializes them to JSON.

## Data contract

`schema/table.schema.json` is a strict Draft 2020-12 JSON Schema for extraction
output. `schema_version` is `1.1.0`. The reference is a separate annotation format,
not an extraction result; it deliberately has no invented coordinates.

Each numeric observation retains `raw`, NFKC `normalized`, integer-or-null `value`,
`status` (`number`, `dash`, `blank`), `negative_zero`, and its cell `source_bbox`.
Values remain in the displayed unit: `JPY` with `unit_multiplier=1000`. For example,
`△2,979` becomes -2979 thousand yen; it is not silently converted to yen.

`△0` is value 0 with `negative_zero=true`; `－` is null with `status=dash`, not zero.
A blank is null with `status=blank`. Dashes make no claim about the economic reason
for a missing amount.

Source boxes use `[x0, top, x1, bottom]` in PDF points, origin at top left. They are
cell regions, not tight glyph boxes. In the coordinate fallback these regions are
inferred from header bands and word-line spacing, not recovered borders.
`label_x0` records actual label indentation.
`page_index=1` is the physical PDF page; `printed_page_number=4` is the document's
visible footer. Row identity is `(page_index, row_id)`; full paths provide context
but are not assumed globally unique across arbitrary future documents.

## Limits and failure behaviour

- Supports this style of Japanese balance sheet with two Gregorian period columns
  and an explicit 千円 unit. It is not a universal financial-table parser.
- The detected-table path requires one table and no merged/missing cell regions.
  The borderless path requires two aligned period headers, one unambiguous date row,
  consistent body amount alignment, and single-line rows. Scans,
  wrapped labels, multiline value cells, partially blank amount rows, ambiguous
  headers, other units, and unrecognized amount tokens are rejected explicitly.
- Successful indentation inference can still be semantically wrong on an unfamiliar
  layout. Metadata/title heuristics and table detection need broader testing.
- The reference evaluator matches sequential row IDs, not independently aligned paths.
  An inserted/dropped row with renumbering can cascade into many later mismatches.
  Its per-cell score is meaningful for this fixed page; robust held-out evaluation
  would need sequence alignment using path/label context and explicit gap penalties.
- Explicit errors exit with code 2; reference mismatches exit with code 1.
  Extraction completes in memory before writing outputs. Existing outputs are not
  refreshed on an extraction error; check exit codes or use a fresh output directory.
- No translation, missing-value imputation, automatic amount correction, or issuer
  identification is attempted. None is necessary to preserve this page's table.
- JSON Schema checks shape and local cell semantics. Cross-row/path relationships
  are checked separately; accounting checks are documented in `docs/VALIDATION.md`.

## Submission preparation

Include the code, supplied fixture, outputs, evaluation, and design limitations.
Export and attach the actual complete AI conversation separately when submitting;
this repository does not contain a fabricated or summarized replacement chat log.
