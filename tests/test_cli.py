import csv
import json
import subprocess
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from openpyxl import load_workbook


class InstalledCliTest(unittest.TestCase):
    def test_extractor_is_available_in_installed_package(self):
        source = files("google_maps_reviews").joinpath("extract_reviews.js").read_text(encoding="utf-8")
        self.assertIn("data-review-id", source)
        self.assertIn("displayed_total", source)

    def test_command_runs_from_another_directory_and_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                ["google-maps-reviews", "--demo", "--output-dir", folder],
                cwd=folder, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            paths = list(Path(folder).glob("*.json"))
            self.assertEqual(len(paths), 1)
            data = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertTrue(data["metadata"]["sample"])
            self.assertEqual(data["metadata"]["count"], 1)
            self.assertEqual(len(data["reviews"]), 1)
            with paths[0].with_suffix(".csv").open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.reader(stream))), 2)
            book = load_workbook(paths[0].with_suffix(".xlsx"))
            self.assertEqual(book["口コミ"].max_row, 2)
            book.close()

    def test_conflicting_scope_options_are_rejected(self):
        for options in [("--all", "--max", "5"), ("--all", "--visible-only")]:
            result = subprocess.run(
                ["google-maps-reviews", *options], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
