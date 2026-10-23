# Financial Table Parser

A take-home document-intelligence prototype for a supplied Japanese consolidated
balance-sheet page. It extracts a traceable table, evaluates it against a separately
entered reference, reports arithmetic residuals, and demonstrates routing on
synthetic PDF variants. A conservative word-coordinate fallback also supports
borderless variants of the declared layout.

The implementation is in [japanese-financial-table-parser](japanese-financial-table-parser/).

- [Setup, outputs, scope, and measured results](japanese-financial-table-parser/README.md)
- [Design and findings](japanese-financial-table-parser/docs/REPORT.md)
- [Reference provenance](japanese-financial-table-parser/docs/REFERENCE_AUDIT.md)
- [Accounting-validation assumptions](japanese-financial-table-parser/docs/VALIDATION.md)
- [Robustness scenarios and routing limits](japanese-financial-table-parser/docs/ROBUSTNESS.md)

## Run

Use Python 3.10+ in a virtual environment. From the repository root:

```bash
cd japanese-financial-table-parser
python -m pip install -r requirements-dev.txt
python parse.py data/balance_sheet_after_correction.pdf --output outputs
python evaluate.py
python validate.py
python route.py data/balance_sheet_after_correction.pdf
python robustness.py
python -m unittest discover -s tests -v
```

## Results and limits

The supplied page matches the development reference at 43 rows and 86 period cells.
Forty tests pass. Twenty potential arithmetic checks produce 7 exact results,
11 nonzero residuals within a conditional tolerance, and 2 skipped checks because
dashes are not assigned numeric values.

Fourteen synthetic PDF scenarios meet the expected routing outcomes, including two
corrupted cases intentionally accepted to demonstrate blind spots. This is not
100% error detection or evidence of accuracy on unseen filings. Independent human
reference review is pending. OCR/VLM execution is not implemented; routing records
the recommended next action. The complete AI chat log accompanies submission
separately.

The evaluator currently matches sequential row IDs; inserted or dropped rows can
cause cascading mismatches. Human visual verification of the reference is still
pending and is not implied by a text-layer cross-check.
