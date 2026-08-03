from pathlib import Path
import sys
import unittest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from openusd_production_inspector import inspect_stage


class InspectorTests(unittest.TestCase):
    def test_reports_valid_stage_metadata(self) -> None:
        report = inspect_stage(REPOSITORY_ROOT / "examples" / "minimal-valid.usda")
        self.assertEqual(report["default_prim"], "/World")
        self.assertEqual(report["prim_count"], 2)
        self.assertEqual(report["findings"], [])

    def test_reports_missing_asset_and_metadata(self) -> None:
        report = inspect_stage(REPOSITORY_ROOT / "examples" / "missing-asset.usda")
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("unresolved-asset", codes)
        self.assertIn("missing-up-axis", codes)
        self.assertIn("missing-meters-per-unit", codes)


if __name__ == "__main__":
    unittest.main()
