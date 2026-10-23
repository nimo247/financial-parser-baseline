from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import fitz
import pdfplumber

from parse import parse_document
from robustness import content_projection, generate_variants
from route import preflight, route_document

ROOT = Path(__file__).resolve().parents[1]


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.source = ROOT / "data/balance_sheet_after_correction.pdf"
        cls.variants = {v["name"]: v for v in generate_variants(cls.source, Path(cls.temp.name))}
        cls.routes = {name: route_document(v["path"]) for name, v in cls.variants.items()}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def decision(self, name):
        return self.routes[name]["pages"][0]["decision"]

    def test_control_retains_incomplete_validation_diagnostic(self):
        report = self.routes["original"]
        self.assertEqual(self.decision("original"), "accept_with_diagnostics")
        self.assertEqual(report["pages"][0]["validation_summary"]["not_evaluated"], 2)
        self.assertFalse(report["summary"]["action_required"])

    def test_geometry_changes_preserve_content(self):
        expected = content_projection(parse_document(self.source))
        for name in ["translated_page", "shifted_amount_alignment"]:
            with self.subTest(name=name):
                self.assertEqual(self.decision(name), "accept_with_diagnostics")
                self.assertEqual(content_projection(parse_document(self.variants[name]["path"])), expected)

    def test_scan_is_image_only_and_requests_ocr(self):
        with pdfplumber.open(self.variants["rasterized_scan"]["path"]) as doc:
            self.assertFalse(doc.pages[0].chars)
            self.assertTrue(doc.pages[0].images)
        self.assertEqual(self.decision("rasterized_scan"), "ocr_required")

    def test_numeric_corruptions_survive_extraction_and_request_human_review(self):
        digits = parse_document(self.variants["digit_transposition"]["path"])
        sign = parse_document(self.variants["dropped_negative_sign"]["path"])
        self.assertEqual(digits["pages"][0]["rows"][2]["cells"]["c1"]["value"], 2002492)
        self.assertEqual(sign["pages"][0]["rows"][16]["cells"]["c2"]["value"], 1640253)
        for name in ["digit_transposition", "dropped_negative_sign"]:
            self.assertEqual(self.decision(name), "human_review")

    def test_readable_unknown_section_requests_structure_review(self):
        parsed = parse_document(self.variants["unknown_section"]["path"])
        self.assertIn("未分類資産", [r["label"] for r in parsed["pages"][0]["rows"]])
        self.assertEqual(self.decision("unknown_section"), "structure_review")

    def test_column_collision_is_not_silently_accepted(self):
        self.assertEqual(self.decision("column_collision"), "extraction_review")

    def test_known_blind_spots_remain_visible(self):
        for name in ["one_unit_error", "compensating_errors"]:
            with self.subTest(name=name):
                self.assertEqual(self.decision(name), "accept_with_diagnostics")
                changed = parse_document(self.variants[name]["path"])
                self.assertNotEqual(changed["pages"][0]["rows"][2]["cells"]["c1"]["value"], 2002429)

    def test_suspicious_text_is_reviewed_before_table_detection(self):
        for text in ["\ufffd資産", "(cid:123)資産", "\ue001資産", "Only Latin text"]:
            page = Mock(chars=[{"text": text}], images=[])
            with self.subTest(text=text):
                self.assertEqual(preflight(page)[0], "extraction_review")

    def test_empty_page_does_not_automatically_request_ocr(self):
        self.assertEqual(preflight(Mock(chars=[], images=[]))[0], "structure_review")

    def test_mixed_document_routes_each_page(self):
        path = Path(self.temp.name) / "mixed_document.pdf"
        with fitz.open() as combined:
            for name in ["original", "rasterized_scan"]:
                with fitz.open(self.variants[name]["path"]) as source:
                    combined.insert_pdf(source)
            combined.save(path)
        report = route_document(path)
        self.assertEqual([p["decision"] for p in report["pages"]],
                         ["accept_with_diagnostics", "ocr_required"])
        self.assertTrue(report["summary"]["action_required"])


if __name__ == "__main__":
    unittest.main()
