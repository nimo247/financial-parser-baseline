import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from jsonschema import Draft202012Validator, ValidationError

from evaluate import evaluate
from parse import ExtractionError, extract_page, parse_cell, parse_document

ROOT = Path(__file__).resolve().parents[1]


class ValueTests(unittest.TestCase):
    def test_negative_zero_keeps_evidence(self):
        cell = parse_cell("△0")
        self.assertEqual(cell["value"], 0)
        self.assertEqual(cell["raw"], "△0")
        self.assertTrue(cell["negative_zero"])

    def test_dash_blank_and_zero_are_distinct(self):
        cells = [parse_cell(s) for s in ["－", "", "0"]]
        self.assertEqual([c["status"] for c in cells], ["dash", "blank", "number"])
        self.assertEqual([c["value"] for c in cells], [None, None, 0])

    def test_nfkc_does_not_overwrite_original(self):
        cell = parse_cell("△１，２３４")
        self.assertEqual(cell["value"], -1234)
        self.assertEqual(cell["normalized"], "△1,234")
        self.assertEqual(cell["raw"], "△１，２３４")

    def test_unknown_tokens_are_rejected(self):
        for token in ["12,34", "1.2", "1,234注", "△", "1 2\n3", "N/A"]:
            with self.subTest(token=token), self.assertRaises(ExtractionError):
                parse_cell(token)

    def test_no_text_layer_is_explicit_error(self):
        page = Mock(chars=[])
        with self.assertRaisesRegex(ExtractionError, "OCR required"):
            extract_page(page, 1)


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = parse_document(ROOT / "data/balance_sheet_after_correction.pdf")
        cls.reference = json.loads((ROOT / "reference/expected.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "schema/table.schema.json").read_text(encoding="utf-8"))

    def test_full_page_matches_separately_entered_reference(self):
        report = evaluate(self.document, self.reference)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["metrics"]["cell_semantics"]["total"], 86)

    def test_schema_and_coordinate_bounds(self):
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.document)
        page = self.document["pages"][0]
        for row in page["rows"]:
            for cell in row["cells"].values():
                x0, top, x1, bottom = cell["source_bbox"]
                self.assertTrue(0 <= x0 < x1 <= page["width"])
                self.assertTrue(0 <= top < bottom <= page["height"])

    def test_schema_rejects_dash_as_zero(self):
        bad = copy.deepcopy(self.document)
        bad["pages"][0]["rows"][25]["cells"]["c1"]["value"] = 0
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.schema).validate(bad)

    def test_dashes_do_not_shift_current_period(self):
        rows = self.document["pages"][0]["rows"]
        for index, amount in [(25, 4553), (37, 62000)]:
            self.assertEqual(rows[index]["cells"]["c1"]["status"], "dash")
            self.assertEqual(rows[index]["cells"]["c2"]["value"], amount)

    def test_repeated_labels_have_distinct_context(self):
        rows = self.document["pages"][0]["rows"]
        repeated = [r for r in rows if r["label"] == "減価償却累計額"]
        self.assertEqual(len(repeated), 4)
        self.assertEqual(len({tuple(r["path"]) for r in repeated}), 4)

    def test_evaluation_detects_amount_hierarchy_status_period_and_missing_row(self):
        for mutation in ["amount", "hierarchy", "status", "period", "missing", "negative_zero", "extra"]:
            bad = copy.deepcopy(self.document)
            page = bad["pages"][0]
            if mutation == "amount":
                page["rows"][2]["cells"]["c1"]["value"] += 1
            elif mutation == "hierarchy":
                page["rows"][16]["path"] = ["wrong"]
            elif mutation == "status":
                page["rows"][25]["cells"]["c1"]["status"] = "blank"
            elif mutation == "period":
                page["metadata"]["columns"].reverse()
            elif mutation == "negative_zero":
                page["rows"][11]["cells"]["c2"]["negative_zero"] = False
            elif mutation == "extra":
                extra = copy.deepcopy(page["rows"][-1])
                extra["id"] = "r999"
                page["rows"].append(extra)
            else:
                page["rows"].pop()
            with self.subTest(mutation=mutation):
                self.assertFalse(evaluate(bad, self.reference)["passed"])


if __name__ == "__main__":
    unittest.main()
