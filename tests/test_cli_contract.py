import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_ROOT = REPOSITORY_ROOT.parent / "openusd-procedural-asset-pipeline"
VALID_ASSET = PIPELINE_ROOT / "fixtures" / "valid" / "industrial-crate" / "asset.usda"
INVALID_ASSET = PIPELINE_ROOT / "fixtures" / "invalid" / "missing-lod" / "asset.usda"
SCRIPT = REPOSITORY_ROOT / "scripts" / "inspect_stage.py"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class InspectorCliContractTests(unittest.TestCase):
    def test_summary_reports_stage_state_as_json(self) -> None:
        result = run_cli(str(VALID_ASSET), "summary", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["default_prim"], "/Asset")
        self.assertEqual(report["up_axis"], "Y")
        self.assertEqual(report["meters_per_unit"], 1.0)
        self.assertEqual(report["root_layer"], str(VALID_ASSET.resolve()).replace("\\", "/"))
        self.assertGreaterEqual(report["prim_count"], 6)
        self.assertIn("Cube", report["schemas"])
        self.assertTrue(report["loaded"])
        self.assertEqual(report["unloaded_prim_count"], 0)

    def test_dependencies_classify_payloads_references_and_missing_files(self) -> None:
        valid_result = run_cli(str(VALID_ASSET), "dependencies", "--format", "json")
        invalid_result = run_cli(str(INVALID_ASSET), "dependencies", "--format", "json")

        self.assertEqual(valid_result.returncode, 0, valid_result.stderr)
        valid = json.loads(valid_result.stdout)
        self.assertEqual(valid["missing"], [])
        self.assertEqual(
            {item["authored_path"] for item in valid["payloads"]},
            {"geometry/high.usda", "geometry/medium.usda", "geometry/low.usda"},
        )
        self.assertEqual(
            {item["authored_path"] for item in valid["references"]},
            {"looks/looks.usda"},
        )
        self.assertTrue(all(item["exists"] for item in valid["resolved"]))

        self.assertEqual(invalid_result.returncode, 0, invalid_result.stderr)
        invalid = json.loads(invalid_result.stdout)
        self.assertEqual([item["authored_path"] for item in invalid["missing"]], ["geometry/not-present.usda"])

    def test_dependencies_discover_texture_asset_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "textures").mkdir()
            (root / "textures" / "albedo.png").write_bytes(b"fixture")
            stage = root / "textured.usda"
            stage.write_text(
                """#usda 1.0
(
    defaultPrim = "Asset"
)
def Xform "Asset"
{
    def Shader "Texture"
    {
        uniform token info:id = "UsdUVTexture"
        asset inputs:file = @textures/albedo.png@
    }
}
""",
                encoding="utf-8",
            )

            result = run_cli(str(stage), "dependencies", "--format", "json")

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual([item["authored_path"] for item in report["textures"]], ["textures/albedo.png"])
            self.assertTrue(report["textures"][0]["exists"])

    def test_composition_reports_selected_prim_and_variants(self) -> None:
        result = run_cli(str(VALID_ASSET), "composition", "/Asset", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["prim"], "/Asset")
        self.assertEqual(report["variant_selections"]["lod"], "high")
        self.assertEqual(report["variant_selections"]["appearance"], "industrial-yellow")
        self.assertGreaterEqual(len(report["prim_stack"]), 1)
        self.assertGreaterEqual(len(report["layer_stack"]), 2)
        self.assertIn("geometry/high.usda", {item["authored_path"] for item in report["payloads"]})

    def test_validate_applies_six_rules_and_returns_validation_exit_code(self) -> None:
        valid_result = run_cli(str(VALID_ASSET), "validate", "--format", "json")
        invalid_result = run_cli(str(INVALID_ASSET), "validate", "--format", "json")

        self.assertEqual(valid_result.returncode, 0, valid_result.stderr)
        valid = json.loads(valid_result.stdout)
        self.assertTrue(valid["valid"])
        self.assertEqual(len(valid["checks"]), 6)
        self.assertEqual({check["status"] for check in valid["checks"]}, {"PASS"})

        self.assertEqual(invalid_result.returncode, 1, invalid_result.stderr)
        invalid = json.loads(invalid_result.stdout)
        self.assertFalse(invalid["valid"])
        failed_rules = {check["rule"] for check in invalid["checks"] if check["status"] == "FAIL"}
        self.assertEqual(
            failed_rules,
            {"up-axis-authored", "meters-per-unit-authored", "dependencies-resolve", "lod-variant-exists"},
        )

    def test_cli_uses_documented_argument_and_stage_error_codes(self) -> None:
        invalid_arguments = run_cli()
        unreadable_stage = run_cli("not-present.usda", "summary", "--format", "json")

        self.assertEqual(invalid_arguments.returncode, 2)
        self.assertEqual(unreadable_stage.returncode, 3)
        self.assertIn("Unable to open USD stage", unreadable_stage.stderr)
        self.assertNotIn("Traceback", unreadable_stage.stderr)


if __name__ == "__main__":
    unittest.main()
