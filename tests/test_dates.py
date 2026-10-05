import csv
import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from openpyxl import load_workbook
from google_maps_reviews import cli, console
from google_maps_reviews.dates import date_bounds, iso_date, select_period


class DateRangeTest(unittest.TestCase):
    def test_relative_labels_remain_ranges_and_edited_dates_are_unknown(self):
        today = date(2026, 10, 6)
        for text in ("5 か月前", "a month ago", "2 years ago", "3 日前", "1週間前"):
            with self.subTest(text=text):
                lower, upper, precision = date_bounds(text, today)
                self.assertLess(lower, upper)
                self.assertIn("推定", precision)
                self.assertLessEqual(upper, today)
        self.assertEqual(date_bounds("最終編集: 1 年前", today)[:2], (None, None))
        self.assertEqual(date_bounds("not a date", today)[:2], (None, None))

    def test_exact_date_and_calendar_month_end(self):
        self.assertEqual(date_bounds("2026年9月30日", date(2026, 10, 6))[:2], (date(2026, 9, 30),) * 2)
        lower, upper, _ = date_bounds("1か月前", date(2024, 3, 31))
        self.assertLessEqual(lower, date(2024, 1, 31))
        self.assertEqual(upper, date(2024, 3, 31))
        with self.assertRaises(argparse.ArgumentTypeError):
            iso_date("2026-02-30")
        with self.assertRaises(argparse.ArgumentTypeError):
            iso_date("2026-1-1")

    def test_period_includes_endpoints_and_retains_boundary_unknown(self):
        rows = [{"review_id": str(i), "date_text": text} for i, text in enumerate(
            ("2026-09-01", "2026-09-30", "2026-08-31", "1 か月前", "最終編集: 1 年前"))]
        selected, uncertain, excluded = select_period(rows, "2026-09-01", "2026-09-30", date(2026, 10, 6))
        self.assertEqual([row["review_id"] for row in selected], ["0", "1"])
        self.assertEqual([row["review_id"] for row in uncertain], ["3", "4"])
        self.assertEqual(excluded, 1)
        self.assertNotIn("date_precision", rows[0])

    def test_period_conflicts_and_reversed_range_fail_before_browser(self):
        with patch.object(cli, "collection_browser", side_effect=AssertionError("no browser")), redirect_stderr(io.StringIO()):
            for arguments in (["--from", "2026-01-01", "--all"], ["--from", "2026-01-01", "--max", "5"], ["--to", "2026-01-01", "--visible-only"], ["--from", "2026-09-30", "--to", "2026-09-01"]):
                with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                    cli.main(["https://maps.app.goo.gl/store"] + arguments)

    def test_settings_do_not_leak_period_into_an_explicit_all_run(self):
        settings = dict(console.default_settings(), scope="period", date_from="2026-01-01", date_to="2026-06-30")
        args = console.apply_settings(cli.build_parser().parse_args(["--all"]), settings, ["--all"])
        self.assertIsNone(args.date_from)
        self.assertTrue(args.all)
        args = console.apply_settings(cli.build_parser().parse_args([]), settings, [])
        self.assertEqual(args.date_from, "2026-01-01")
        self.assertFalse(args.all)

    def test_interactive_period_settings_can_be_saved(self):
        answers = ["https://maps.app.goo.gl/store", "4", "2026-01-01", "2026-09-30", "", "", "", "", ""]
        with patch("builtins.input", side_effect=answers), redirect_stdout(io.StringIO()):
            settings = console.edit_settings(console.default_settings())
        self.assertEqual(settings["scope"], "period")
        self.assertEqual(settings["date_to"], "2026-09-30")

    def test_period_collection_scans_all_and_saves_uncertainty_in_same_workbook(self):
        page = MagicMock(url="https://www.google.com/maps/test")
        reviews = [{"review_id": str(i), "author": "架空", "rating": 4, "text": "", "date_text": text} for i, text in enumerate(
            ("2026-09-01", "2026-09-30", "2026-08-31", "最終編集: 1 年前"))]
        page.evaluate.return_value = {"place_name": "テスト", "source_url": page.url, "displayed_total": 4, "reviews": reviews}
        context = MagicMock(pages=[page])
        with tempfile.TemporaryDirectory() as folder, patch("playwright.sync_api.sync_playwright"), patch.object(cli, "collection_browser") as launch, patch.object(cli, "prepare_reviews"), patch.object(cli, "expand_text"), patch.object(cli, "blocked", return_value=False), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            launch.return_value.__enter__.return_value = context
            code = cli.main([page.url, "--from", "2026-09-01", "--to", "2026-09-30", "--output-dir", folder])
            self.assertEqual(code, 2)
            data = json.loads(next(Path(folder).glob("*.json")).read_text())
            self.assertEqual(len(data["reviews"]), 2)
            self.assertEqual(len(data["uncertain_reviews"]), 1)
            self.assertEqual(data["metadata"]["scanned_count"], 4)
            self.assertEqual(data["metadata"]["missing_count"], 0)
            self.assertTrue(data["metadata"]["scan_coverage_verified"])
            self.assertFalse(data["metadata"]["full_coverage_verified"])
            with next(Path(folder).glob("*.csv")).open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 2)
            book = load_workbook(next(Path(folder).glob("*.xlsx")))
            self.assertEqual(book.sheetnames, ["口コミ", "期間境界・日付不明", "取得情報"])
            book.close()

    def test_empty_period_result_still_saves_valid_files_after_scan(self):
        selected, uncertain, excluded = select_period([{"date_text": "2020-01-01"}], "2026-01-01", "2026-09-30", date(2026, 10, 6))
        self.assertEqual((selected, uncertain, excluded), ([], [], 1))
        with tempfile.TemporaryDirectory() as folder:
            paths = cli.export_reviews([], {"count": 0}, Path(folder), "empty")
            self.assertEqual(len(paths), 3)
            with paths[0].open(encoding="utf-8-sig") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])

    def test_preview_opens_complete_list_and_reloads_stale_dom_once(self):
        page = MagicMock()
        button, sort = MagicMock(), MagicMock()
        page.get_by_role.side_effect = lambda role, name: MagicMock(first=sort if "並べ替え" in name.pattern else button)
        button.is_visible.return_value = True
        button.wait_for.side_effect = [TimeoutError("preview remains"), None]
        self.assertTrue(cli.open_full_reviews(page))
        page.reload.assert_called_once()
        button.click.assert_called_once()
        button.is_visible.return_value = False
        self.assertFalse(cli.open_full_reviews(page))

    def test_google_restriction_is_detected_even_when_review_cards_exist(self):
        page = MagicMock()
        page.locator.return_value.inner_text.return_value = "本文ありの口コミ\nGoogle マップの表示が制限されています。"
        self.assertTrue(cli.reviews_restricted(page))
        page.locator.return_value.inner_text.return_value = "口コミの本文のみ"
        self.assertFalse(cli.reviews_restricted(page))


if __name__ == "__main__":
    unittest.main()
