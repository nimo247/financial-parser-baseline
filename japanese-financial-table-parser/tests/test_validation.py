import copy
import json
from pathlib import Path
import unittest

from validate import validate_document

ROOT = Path(__file__).resolve().parents[1]


class AccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / "outputs/table.json").read_text(encoding="utf-8"))

    def check_for(self, report, row_id, period="2026-03-31"):
        return next(c for c in report["checks"] if c["target"]["row_id"] == row_id and c["period"] == period)

    def test_source_residuals_remain_visible(self):
        report = validate_document(self.document)
        for row_id, period, expected in [
            ("r013", "2025-03-31", 3), ("r013", "2026-03-31", 2),
            ("r042", "2025-03-31", 2), ("r043", "2026-03-31", 1),
            ("r018", "2026-03-31", -1), ("r025", "2025-03-31", -1),
            ("r025", "2026-03-31", -1),
        ]:
            with self.subTest(row_id=row_id, period=period):
                check = self.check_for(report, row_id, period)
                self.assertEqual(check["residual"], expected)
                self.assertEqual(check["status"], "within_tolerance")
                self.assertIn("cause unverified", check["reason"])
        self.assertEqual(report["summary"]["checks"], 20)
        self.assertEqual(report["summary"]["beyond_tolerance"], 0)

    def test_dashes_are_skipped_by_default(self):
        report = validate_document(self.document)
        self.assertEqual(report["summary"]["not_evaluated"], 2)
        self.assertFalse(report["summary"]["complete"])
        check = self.check_for(report, "r030", "2025-03-31")
        self.assertIsNone(check["computed"])
        self.assertEqual(check["status"], "not_evaluated")

    def test_optional_zero_policy_is_recorded_without_mutating_nulls(self):
        report = validate_document(self.document, "assume-zero")
        self.assertEqual(report["summary"]["not_evaluated"], 0)
        check = self.check_for(report, "r030", "2025-03-31")
        dash = next(t for t in check["operands"] if t["status"] == "dash")
        self.assertIsNone(dash["value"])
        self.assertEqual(dash["arithmetic_value"], 0)
        self.assertTrue(dash["assumed_zero"])
        self.assertTrue(check["assumptions"])

    def test_net_amounts_replace_gross_groups_in_subtotals(self):
        check = self.check_for(validate_document(self.document), "r030")
        self.assertEqual(check["computed"], 1352607)
        self.assertEqual([t["row_id"] for t in check["operands"]],
                         ["r018", "r021", "r022", "r025", "r026", "r029"])

    def test_large_digit_error_triggers_review(self):
        bad = copy.deepcopy(self.document)
        bad["pages"][0]["rows"][2]["cells"]["c1"].update(raw="2,002,492", value=2002492)
        report = validate_document(bad)
        check = self.check_for(report, "r013", "2025-03-31")
        self.assertEqual(check["residual"], -60)
        self.assertEqual(check["status"], "beyond_tolerance")
        self.assertTrue(report["summary"]["requires_review"])

    def test_dropped_negative_sign_triggers_review(self):
        bad = copy.deepcopy(self.document)
        bad["pages"][0]["rows"][16]["cells"]["c2"].update(raw="1,640,253", value=1640253)
        report = validate_document(bad)
        check = self.check_for(report, "r018")
        self.assertEqual(check["status"], "beyond_tolerance")
        self.assertIn("sign_issue", check)
        self.assertTrue(report["summary"]["requires_review"])

    def test_small_error_is_not_claimed_detectable(self):
        bad = copy.deepcopy(self.document)
        bad["pages"][0]["rows"][2]["cells"]["c1"]["value"] += 1
        check = self.check_for(validate_document(bad), "r013", "2025-03-31")
        self.assertEqual(check["status"], "within_tolerance")
        self.assertEqual(check["residual"], 2)

    def test_blank_operand_is_not_imputed_even_with_zero_policy(self):
        bad = copy.deepcopy(self.document)
        bad["pages"][0]["rows"][2]["cells"]["c1"].update(raw="", status="blank", value=None)
        check = self.check_for(validate_document(bad, "assume-zero"), "r013", "2025-03-31")
        self.assertEqual(check["status"], "not_evaluated")

    def test_no_input_changes_and_no_hardcoded_sample_row_ids(self):
        before = copy.deepcopy(self.document)
        validate_document(self.document)
        self.assertEqual(self.document, before)
        renamed = copy.deepcopy(self.document)
        for row in renamed["pages"][0]["rows"]:
            row["id"] = "renamed_" + row["id"]
            if row["parent_id"]:
                row["parent_id"] = "renamed_" + row["parent_id"]
        self.assertEqual(validate_document(renamed)["summary"], validate_document(before)["summary"])

    def test_unsupported_structure_is_reported(self):
        bad = copy.deepcopy(self.document)
        bad["pages"][0]["rows"][12]["kind"] = "item"
        report = validate_document(bad)
        self.assertTrue(report["structural_issues"])
        self.assertTrue(report["summary"]["requires_review"])
        self.assertFalse(report["summary"]["complete"])

    def test_invalid_parent_graph_is_rejected(self):
        bad = copy.deepcopy(self.document)
        bad["pages"][0]["rows"][2]["parent_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "parent"):
            validate_document(bad)


if __name__ == "__main__":
    unittest.main()
