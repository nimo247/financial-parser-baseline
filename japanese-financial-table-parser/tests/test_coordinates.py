import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from jsonschema import Draft202012Validator
import pdfplumber

from parse import ExtractionError, coordinate_table, parse_document
from robustness import content_projection, generate_variants
from route import route_document

ROOT = Path(__file__).resolve().parents[1]


class CoordinateFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.source = ROOT / "data/balance_sheet_after_correction.pdf"
        cls.variants = {v["name"]: v for v in generate_variants(cls.source, cls.temp.name)}
        cls.reference = json.loads((ROOT / "reference/expected.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_original_keeps_detected_cell_path(self):
        document = parse_document(self.source)
        self.assertEqual(document["pages"][0]["extraction_method"], "detected_cells")

    def test_borderless_matches_entered_reference_and_schema(self):
        document = parse_document(self.variants["borderless"]["path"])
        page = document["pages"][0]
        self.assertEqual(page["extraction_method"], "word_coordinates")
        self.assertEqual(len(page["rows"]), len(self.reference["rows"]))
        for actual, expected in zip(page["rows"], self.reference["rows"]):
            for key in ["label_raw", "label", "path", "parent_id", "depth", "kind"]:
                self.assertEqual(actual[key], expected[key], (actual["id"], key))
            for column in ["c1", "c2"]:
                for key in ["raw", "value", "status", "negative_zero"]:
                    self.assertEqual(actual["cells"][column][key], expected["cells"][column][key],
                                     (actual["id"], column, key))
        schema = json.loads((ROOT / "schema/table.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(document)

    def test_borderless_preserves_all_text_but_has_no_drawing_objects(self):
        with pdfplumber.open(self.source) as before, pdfplumber.open(self.variants["borderless"]["path"]) as after:
            self.assertEqual(len(before.pages[0].chars), len(after.pages[0].chars))
            self.assertFalse(after.pages[0].rects)
            self.assertFalse(after.pages[0].lines)
            self.assertFalse(after.pages[0].curves)
            self.assertFalse(after.pages[0].find_tables())

    def test_borderless_shifted_amount_keeps_period_and_semantics(self):
        document = parse_document(self.variants["borderless_shifted_amount"]["path"])
        self.assertEqual(document["pages"][0]["extraction_method"], "word_coordinates")
        self.assertEqual(content_projection(document), content_projection(parse_document(self.source)))

    def test_borderless_collision_requests_extraction_review(self):
        report = route_document(self.variants["borderless_column_collision"]["path"])
        self.assertEqual(report["pages"][0]["decision"], "extraction_review")

    def test_borderless_missing_amount_is_not_shifted_or_imputed(self):
        path = self.variants["borderless_missing_amount"]["path"]
        with self.assertRaisesRegex(ExtractionError, "Partially blank"):
            parse_document(path)
        self.assertEqual(route_document(path)["pages"][0]["decision"], "structure_review")

    def test_ambiguous_headers_are_rejected(self):
        with pdfplumber.open(self.source) as doc:
            words = doc.pages[0].extract_words()
        header = next(w for w in words if w["text"] == "前連結会計年度")
        page = Mock()
        page.extract_words.return_value = words + [dict(header)]
        with self.assertRaisesRegex(ExtractionError, "period headers"):
            coordinate_table(page)

    def test_missing_numeric_column_evidence_is_rejected(self):
        with pdfplumber.open(self.source) as doc:
            page = doc.pages[0].filter(lambda obj: not (
                obj["object_type"] == "char" and obj["top"] > 145 and obj["x0"] > 400))
            with self.assertRaisesRegex(ExtractionError, "both numeric columns"):
                coordinate_table(page)


if __name__ == "__main__":
    unittest.main()
