# Robustness and routing

## Run

```bash
python -m pip install -r requirements-dev.txt
python route.py data/balance_sheet_after_correction.pdf
python robustness.py
python -m unittest discover -s tests -v
```

The production router uses pdfplumber. PyMuPDF is only needed to generate synthetic
PDF fixtures and run the development tests. No API key, OCR model, or VLM is used.

`route.py` writes `outputs/routing.json`. `robustness.py` generates nine modified
PDFs and exercises ten scenarios including the unchanged source; it writes the
aggregate `outputs/robustness/report.json` and individual routing reports.

## Decisions

| Decision | Evidence / next action |
| --- | --- |
| `accept_with_diagnostics` | Supported text and structure; no arithmetic review trigger. Preserve residuals and skipped checks. Acceptance does not prove correctness. |
| `ocr_required` | Image content with no extractable text. Run an OCR pipeline externally, then apply the same schema and checks. |
| `extraction_review` | Suspicious decoded glyphs, absent CJK for expected Japanese input, or invalid amount tokens. Try alternate extraction; consider OCR if text decoding failed. |
| `structure_review` | Unsupported table, section, period ordering, relationship, or empty/vector-only page. Inspect layout and semantics. |
| `human_review` | Arithmetic discrepancy beyond the assumed bound or unexpected depreciation sign. Compare source and another extractor to investigate. |

These are routing recommendations. An alternate extractor, OCR/VLM execution,
and actual human review are not implemented. In a multi-page document the router
records a separate decision for each page; it does not silently drop failed pages.

Return codes: 0 means all pages received `accept_with_diagnostics`; 1 means at least
one page needs an action; 2 means an input/IO failure. A review exit code is a
routing result, not a crashed parser.

## Synthetic PDF results

| Scenario | Actual change | Observed decision |
| --- | --- | --- |
| Original | No change | Accept with diagnostics |
| Translated page | Shift whole page by 20 pt horizontally / 10 pt vertically, expand canvas | Accept; semantic content identical |
| Rasterized scan | Render at 150 dpi and embed as image-only PDF | OCR required |
| Shifted amount alignment | Move current-year cash amount 18 pt left inside its existing cell | Accept; semantic content identical |
| Digit transposition | Prior cash 2,002,429 -> 2,002,492 | Human review |
| Unknown section | Replace investment section label with readable 未分類資産 | Structural review |
| Column collision | Move current cash into the prior-year amount region, creating overlapping text | Extraction review |
| One-unit error | Prior cash 2,002,429 -> 2,002,430 | Accepted: known arithmetic blind spot |
| Compensating errors | Increase prior cash by 63 and decrease receivables by 63 | Accepted: known arithmetic blind spot |
| Dropped negative sign | Remove triangle from current buildings' accumulated depreciation | Human review |

All ten routing expectations were met. This explicitly includes TWO expected
accepted corruptions. It is not 100% error detection, a held-out accuracy result,
or evidence of broad document generalization. Geometry-preserving cases are
compared with the original parser's semantic content, not an independent new
reference. The original source is separately compared with the entered reference.

Unlike the arithmetic unit tests that mutate extracted JSON, these scenarios change
actual PDF bytes and re-run text extraction, table interpretation, and routing.
Fixture edits use redaction without adding fill rectangles that would inadvertently
alter table detection, followed by replacement text where necessary. A synthetic
collision is deliberately malformed and is not representative of every layout shift.
All generated fixtures were rendered and visually inspected during development.

## Limits

- One supplied source page and synthetic variants do not cover unseen filings.
- CJK checks only identify obvious decoding anomalies; plausible but wrong decoded
  Japanese can pass. A missing CJK signal can also mean an unsupported document type.
- The six supported section labels are explicit baseline vocabulary, not a general
  Japanese accounting taxonomy. New readable labels need interpretation, not
  automatic OCR.
- Layout testing covers a whole-page translation and one shifted value inside a
  cell. It does not establish support for arbitrary column resizing or merged headers.
- Small errors can fit within tolerance; compensating errors can preserve totals.
  Some unsupported structures can also evade heuristics. Review/reference checks
  remain necessary for high-confidence use.
- Image-only detection recommends OCR but does not demonstrate successful OCR.
- Runtime/cost benchmarks and real held-out document evaluation are future work.
