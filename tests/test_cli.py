import csv
import importlib.util
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr
from importlib.resources import files
from pathlib import Path
from unittest.mock import MagicMock, patch

from openpyxl import load_workbook
from google_maps_reviews import cli, console


class InstalledCliTest(unittest.TestCase):
    def setUp(self):
        guard = patch.object(cli, "collection_browser", side_effect=AssertionError("単体テストから実ブラウザーを起動しません。ブラウザーを明示的にモックしてください。"))
        self.browser_guard = guard.start()
        self.addCleanup(guard.stop)

    def test_place_identity_accepts_url_variants_and_rejects_a_different_place(self):
        original = "https://www.google.com/maps/place/Store/data=!1s0x123:0x456!9m1!1b1?hl=ja"
        variant = "https://www.google.com/maps/place/Store/data=%211s0x123%3A0x456!8m2!3d0!4d0?hl=en"
        cli.ensure_same_place(original, variant)
        cli.ensure_same_place(original, "https://maps.google.com/?cid=1110")
        with self.assertRaisesRegex(ValueError, "別施設"):
            cli.ensure_same_place(original, "https://www.google.com/maps/place/Other/data=!1s0x789:0xabc!9m1!1b1")
        self.assertIsNone(cli.place_identity("https://maps.app.goo.gl/unknown-target"))

    def test_no_service_never_connects_to_a_running_legacy_service(self):
        args = cli.build_parser().parse_args(["https://maps.app.goo.gl/requested-store", "--all", "--no-service"])
        with patch.object(cli, "build_opener") as opener:
            self.assertFalse(cli.collect_from_local_service(args, {}, {}))
            opener.assert_not_called()

    def test_default_collection_does_not_discover_a_legacy_service(self):
        args = cli.build_parser().parse_args(["https://maps.app.goo.gl/requested-store", "--all"])
        with patch.object(cli, "build_opener") as opener:
            self.assertFalse(cli.collect_from_local_service(args, {}, {}))
            opener.assert_not_called()

    def test_unsupported_os_does_not_start_collection(self):
        with patch.object(sys, "platform", "linux"), patch.object(cli, "run_collection") as collecting, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--demo"]), 1)
            collecting.assert_not_called()

    def test_preview_cards_wait_for_the_full_review_panel(self):
        page = MagicMock()
        events = []
        main = MagicMock()
        sort = MagicMock()
        sort.is_visible.return_value = True
        sort.wait_for.side_effect = lambda **_kwargs: events.append("sort-visible")
        candidate = MagicMock()
        candidate.get_attribute.return_value = "口コミ"
        candidate.inner_text.return_value = "口コミ"
        candidate.is_visible.return_value = True
        candidate.click.side_effect = lambda **_kwargs: events.append("open-reviews")
        tabs = MagicMock()
        tabs.count.return_value = 1
        tabs.nth.return_value = candidate
        def get_role(role, name=None):
            if role == "main":
                return MagicMock(first=main)
            if role == "button":
                return MagicMock(first=sort)
            return tabs
        page.get_by_role.side_effect = get_role
        page.locator.return_value.count.return_value = 3
        page.locator.return_value.first.wait_for.side_effect = lambda **_kwargs: events.append("cards-visible")
        cli.prepare_reviews(page, False)
        self.assertEqual(events, ["open-reviews", "sort-visible", "cards-visible"])

    def test_extractor_is_available_in_installed_package(self):
        source = files("google_maps_reviews").joinpath("extract_reviews.js").read_text(encoding="utf-8")
        self.assertIn("data-review-id", source)
        self.assertIn("displayed_total", source)

    def test_complete_text_outweighs_a_longer_collapsed_view(self):
        rows = {}
        base = {"review_id": "same", "author": "架空の投稿者", "rating": 5}
        collapsed = dict(base, text="料理が良い…もっと見る・表示上の追加ラベル", text_may_be_truncated=True)
        complete = dict(base, text="料理が良い", text_may_be_truncated=False)
        cli.merge_reviews(rows, [collapsed], "架空店舗", "")
        cli.merge_reviews(rows, [complete], "架空店舗", "")
        self.assertEqual(rows["same"]["text"], complete["text"])
        self.assertFalse(rows["same"]["text_may_be_truncated"])
        cli.merge_reviews(rows, [collapsed], "架空店舗", "")
        self.assertEqual(rows["same"]["text"], complete["text"])
        cli.merge_reviews(rows, [dict(base, text="", text_may_be_truncated=False)], "架空店舗", "")
        self.assertEqual(rows["same"]["text"], complete["text"])

    def test_failed_text_expansion_is_not_cached_and_uses_stable_id(self):
        page = MagicMock()
        cards, card = MagicMock(), MagicMock()
        candidates = [{"id": "stable-id", "selector": "[data-review-id=stable-id]"}]
        cards.evaluate_all.return_value = candidates
        page.locator.side_effect = lambda selector: cards if selector == cli.REVIEW_CARD_SELECTOR else card
        buttons = card.get_by_role.return_value
        buttons.count.return_value = 1
        button = buttons.nth.return_value
        button.is_visible.return_value = True
        button.click.side_effect = [RuntimeError("transient failure"), None]
        processed = set()
        cli.expand_text(page, processed)
        cli.expand_text(page, processed)
        self.assertEqual(button.click.call_count, 2)
        self.assertEqual(processed, set())
        cards.nth.assert_not_called()
        page.locator.assert_any_call(cli.REVIEW_CARD_SELECTOR + "[data-review-id=stable-id]")

    def test_expansion_stops_before_another_card_when_deadline_expires(self):
        page = MagicMock()
        page.locator.return_value.evaluate_all.return_value = [{"id": "pending", "selector": "[data-review-id=pending]"}]
        with patch.object(cli.time, "monotonic", return_value=11):
            cli.expand_text(page, set(), deadline=10)
        page.locator.assert_called_once_with(cli.REVIEW_CARD_SELECTOR)

    def test_empty_review_view_after_tab_switch_reloads_once(self):
        page = MagicMock()
        page.url = "https://www.google.com/maps/place/Test/data=!9m1!1b1"
        sort = MagicMock()
        sort.is_visible.return_value = True
        candidate = MagicMock()
        candidate.get_attribute.return_value = "クチコミ"
        candidate.inner_text.return_value = "クチコミ"
        tabs = MagicMock()
        tabs.count.return_value = 1
        tabs.nth.return_value = candidate
        page.get_by_role.side_effect = lambda role, **_kwargs: MagicMock(first=sort) if role == "button" else tabs
        cards = page.locator.return_value
        cards.count.return_value = 0
        cards.first.wait_for.side_effect = [RuntimeError("SPA did not load reviews"), None]
        cli.prepare_reviews(page, False)
        page.reload.assert_called_once_with(wait_until="domcontentloaded", timeout=15000)
        self.assertEqual(cards.first.wait_for.call_count, 2)

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
        for options in [("--all", "--max", "5"), ("--all", "--visible-only"), ("--visible-only", "--max", "5")]:
            result = subprocess.run(
                ["google-maps-reviews", *options], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)

    def test_non_terminal_never_waits_for_interactive_input(self):
        for options, expected in [([], 0), (["--help"], 0), (["--interactive"], 2),
                                  (["--manual", "https://www.google.com/maps/test"], 2),
                                  (["--max", "5"], 2)]:
            result = subprocess.run(["google-maps-reviews", *options], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, expected, result.stderr)
        result = subprocess.run([sys.executable, "-m", "google_maps_reviews", "--help"],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_interactive_collection_saves_and_reuses_all_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            output = Path(folder) / "reviews"
            responses = ["1", "https://www.google.com/maps/test", "2", "7", "45", "1.5", str(output), "1", "2", "4"]
            with patch.object(sys.stdin, "isatty", return_value=True), patch("builtins.input", side_effect=responses), redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--interactive", "--demo", "--config", str(path)]), 0)
            settings = console.load_settings(path)
            self.assertEqual(settings, {"url": "https://www.google.com/maps/test", "scope": "max", "max": 7,
                                       "timeout": 45, "delay": 1.5, "output_dir": str(output), "browser": "chrome", "manual": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch.object(sys.stdin, "isatty", return_value=False), redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--use-settings", "--demo", "--max", "3", "--config", str(path)]), 0)
            maxima = {json.loads(file.read_text(encoding="utf-8"))["metadata"]["requested_max"] for file in output.glob("*.json")}
            self.assertEqual(maxima, {3, 7})

    def test_saved_settings_are_opt_in_and_explicit_flags_override_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = dict(console.default_settings(), scope="all", max=50, timeout=40, delay=3.0, browser="chromium")
            console.save_settings(path, settings)
            with patch.object(sys.stdin, "isatty", return_value=False), patch.object(cli, "run_collection", return_value=0) as collecting:
                self.assertEqual(cli.main(["https://www.google.com/maps/test", "--config", str(path)]), 0)
                args = collecting.call_args.args[0]
                self.assertEqual((args.max, args.timeout, args.browser, args.all), (100, 300, "chrome", False))
                self.assertEqual(cli.main(["https://www.google.com/maps/test", "--use-settings", "--max=12", "--timeout", "99", "--config", str(path)]), 0)
                args = collecting.call_args.args[0]
                self.assertEqual((args.max, args.timeout, args.browser, args.all), (12, 99, "chromium", False))
                self.assertEqual(cli.main(["https://www.google.com/maps/test", "--demo", "--use-settings", "--time", "99", "--bro=chrome", "--man", "--config", str(path)]), 0)
                args = collecting.call_args.args[0]
                self.assertEqual((args.timeout, args.browser, args.manual), (99, "chrome", True))
            with patch.object(sys.stdin, "isatty", return_value=True), patch.object(console, "edit_settings", side_effect=lambda current: current), patch.object(cli, "run_collection", return_value=0) as collecting, patch("builtins.input", side_effect=["1", "4"]), redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--interactive", "--time", "99", "--bro", "chrome", "--man", "--config", str(path)]), 0)
                args = collecting.call_args.args[0]
                self.assertEqual((args.timeout, args.browser, args.manual), (99, "chrome", True))

    def test_menu_exit_eof_and_bad_configuration_do_not_start_a_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            with patch.dict("os.environ", {"GOOGLE_MAPS_REVIEWS_CONFIG": str(path)}), patch.object(sys.stdin, "isatty", return_value=True), patch.object(cli, "run_collection") as collecting, redirect_stdout(io.StringIO()):
                with patch("builtins.input", return_value="4"):
                    self.assertEqual(cli.main([]), 0)
                with patch("builtins.input", side_effect=EOFError):
                    self.assertEqual(cli.main(["--interactive", "--config", str(path)]), 0)
                collecting.assert_not_called()
            path.write_text('DUMMY_REVIEW_SECRET', encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(cli.main(["settings", "show", "--config", str(path)]), 1)
            self.assertNotIn("DUMMY_REVIEW_SECRET", errors.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["settings", "reset", "--config", str(path)]), 0)
            self.assertEqual(console.load_settings(path), console.default_settings())

    def test_settings_edit_requires_terminal_and_setup_uses_current_python(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            with patch.object(sys.stdin, "isatty", return_value=False), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    cli.main(["settings", "edit", "--config", str(path)])
                self.assertEqual(result.exception.code, 2)
            with patch.object(console.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as installing, redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["setup", "--browser", "chromium", "--config", str(path)]), 0)
                installing.assert_called_once_with([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
            self.assertEqual(console.load_settings(path)["browser"], "chromium")

    def test_setup_defaults_to_existing_chrome_without_a_download(self):
        with patch.object(console, "setup_browser", return_value=0) as setup:
            self.assertEqual(cli.main(["setup"]), 0)
            self.assertEqual(setup.call_args.args[0], "chrome")


class LocalServiceCliTest(unittest.TestCase):
    def setUp(self):
        guard = patch.object(cli, "collection_browser", side_effect=AssertionError("単体テストから実ブラウザーを起動しません。ブラウザーを明示的にモックしてください。"))
        self.browser_guard = guard.start()
        self.addCleanup(guard.stop)

    def test_missing_service_opt_in_fails_without_launching_real_chrome(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "build_opener") as opener, \
                patch("playwright.sync_api.sync_playwright"), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--output-dir", folder]), 1)
            self.browser_guard.assert_called_once()
            opener.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_termination_exits_the_caller_instead_of_continuing_with_partial_data(self):
        with tempfile.TemporaryDirectory() as folder, patch("playwright.sync_api.sync_playwright"), \
                patch.object(cli, "collection_browser", side_effect=SystemExit(143)), \
                patch.object(cli, "export_reviews") as exporting:
            with self.assertRaises(SystemExit) as result:
                cli.main(["https://www.google.com/maps/test", "--all", "--output-dir", folder])
            self.assertEqual(result.exception.code, 143)
            exporting.assert_not_called()

    def payload(self, count, total=2):
        return {"place": "検証店舗", "sourceUrl": "https://www.google.com/maps/test", "displayedTotal": total,
                "reviews": [{"review_id": f"id-{index}", "author": f"投稿者{index}", "rating": 5,
                             "text": "検証本文", "text_may_be_truncated": False} for index in range(count)],
                "reason": "画面の総件数と一致", "verified": count == total}

    def stream(self, events):
        return io.BytesIO(b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events))

    def test_all_reviews_from_service_are_exported_and_coverage_is_rechecked(self):
        events = [{"type": "status", "message": "収集開始"}, {"type": "progress", "data": self.payload(1)},
                  {"type": "done", "data": self.payload(2)}]
        opener = MagicMock()
        opener.open.side_effect = [io.BytesIO(b'{"ready":true,"version":"1.0.0","busy":false}'), self.stream(events)]
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "build_opener", return_value=opener), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--use-service", "--output-dir", folder]), 0)
            data = json.loads(next(Path(folder).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(data["metadata"]["count"], 2)
            self.assertTrue(data["metadata"]["full_coverage_verified"])
            self.assertEqual(data["metadata"]["collector"], "このMacの収集サービス")
            self.assertEqual(opener.open.call_args.args[0].full_url, "http://127.0.0.1:38473/collect")
            self.assertEqual(json.loads(opener.open.call_args.args[0].data), {"url": "https://www.google.com/maps/test", "timeout": 300})

    def test_stream_failure_preserves_partial_reviews_and_returns_incomplete(self):
        for ending in ([{"type": "error", "message": "収集エラー"}], []):
            opener = MagicMock()
            opener.open.side_effect = [io.BytesIO(b'{"ready":true,"version":"1.0.0"}'),
                                       self.stream([{"type": "progress", "data": self.payload(1)}, *ending])]
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as folder, patch.object(cli, "build_opener", return_value=opener), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--use-service", "--output-dir", folder]), 2)
                data = json.loads(next(Path(folder).glob("*.json")).read_text(encoding="utf-8"))
                self.assertEqual(data["metadata"]["count"], 1)
                self.assertFalse(data["metadata"]["full_coverage_verified"])
                self.assertTrue(data["metadata"]["incomplete"])
                self.assertIn("error", data["metadata"])
                self.assertEqual(opener.open.call_count, 2)

    def test_unchanged_progress_and_done_counts_are_printed_once(self):
        events = [{"type": kind, "data": self.payload(count)}
                  for kind, count in [("progress", 1), ("progress", 1), ("progress", 2), ("done", 2)]]
        opener = MagicMock()
        opener.open.side_effect = [io.BytesIO(b'{"ready":true,"version":"1.0.0"}'), self.stream(events)]
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "build_opener", return_value=opener), redirect_stdout(output):
            self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--use-service", "--output-dir", folder]), 0)
        self.assertEqual(output.getvalue().count("取得済み: 1件"), 1)
        self.assertEqual(output.getvalue().count("取得済み: 2件"), 1)

    def test_cli_browser_finishes_at_total_without_scrolling(self):
        page = MagicMock()
        page.url = "https://www.google.com/maps/test"
        payload = self.payload(2)
        page.evaluate.return_value = {"place_name": payload["place"], "source_url": payload["sourceUrl"],
                                      "displayed_total": 2, "reviews": payload["reviews"]}
        context = MagicMock(pages=[page])
        pw = MagicMock()
        pw.chromium.launch_persistent_context.return_value = context
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "collect_from_local_service", return_value=False), \
                patch("playwright.sync_api.sync_playwright") as playwright, patch.object(cli, "collection_browser") as launching, patch.object(cli, "prepare_reviews"), \
                patch.object(cli, "blocked", return_value=False), patch.object(cli, "expand_text"), \
                patch.object(cli, "scroll_reviews") as scrolling, patch.object(cli.Path, "home", return_value=Path(folder)), redirect_stdout(io.StringIO()):
            playwright.return_value.__enter__.return_value = pw
            launching.return_value.__enter__.return_value = context
            self.assertEqual(cli.main([page.url, "--all", "--output-dir", folder]), 0)
            scrolling.assert_not_called()
            page.evaluate.assert_called_once()
            launching.assert_called_once_with(pw, "chrome")
            launching.return_value.__exit__.assert_called_once()
            metadata = json.loads(next(Path(folder).glob("*.json")).read_text())["metadata"]
            self.assertTrue(metadata["full_coverage_verified"])
            self.assertIn("保存件数が一致", metadata["stop_reason"])

    def test_busy_service_does_not_start_another_collection(self):
        opener = MagicMock()
        opener.open.return_value = io.BytesIO(b'{"ready":true,"version":"1.0.0","busy":true}')
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "build_opener", return_value=opener), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--use-service", "--output-dir", folder]), 1)
            self.assertEqual(list(Path(folder).iterdir()), [])
            opener.open.assert_called_once()

    def test_cli_recovers_stalled_loading_and_collects_late_rating_only_review(self):
        page = MagicMock()
        page.url = "https://www.google.com/maps/test"
        initial = self.payload(1)
        complete = self.payload(2)
        complete["reviews"][1]["text"] = ""
        def extracted(data):
            return {"place_name": data["place"], "source_url": data["sourceUrl"], "displayed_total": 2, "reviews": data["reviews"]}
        page.evaluate.side_effect = [extracted(initial)] * 11 + [extracted(complete)]
        context = MagicMock(pages=[page])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "collect_from_local_service", return_value=False), \
                patch("playwright.sync_api.sync_playwright"), patch.object(cli, "collection_browser") as launching, \
                patch.object(cli, "prepare_reviews"), patch.object(cli, "blocked", return_value=False), \
                patch.object(cli, "expand_text"), patch.object(cli, "review_scroll_state", return_value={"at_end": True}), \
                patch.object(cli, "scroll_reviews") as scrolling, patch.object(cli.time, "sleep"), redirect_stdout(output):
            launching.return_value.__enter__.return_value = context
            self.assertEqual(cli.main([page.url, "--all", "--output-dir", folder]), 0)
            self.assertEqual(scrolling.call_count, 11)
            self.assertTrue(any(call.kwargs.get("recover") for call in scrolling.call_args_list))
            data = json.loads(next(Path(folder).glob("*.json")).read_text())
            self.assertEqual(data["metadata"]["count"], 2)
            self.assertTrue(data["metadata"]["full_coverage_verified"])
            self.assertEqual(data["reviews"][1]["text"], "")
            self.assertEqual(data["metadata"]["text_review_count"], 1)
            self.assertEqual(data["metadata"]["rating_only_count"], 1)
            self.assertEqual(data["metadata"]["missing_count"], 0)
            self.assertEqual(output.getvalue().count("取得済み: 1件"), 1)

    def test_visible_only_keeps_more_than_the_default_100_reviews_without_scrolling(self):
        page = MagicMock()
        page.url = "https://www.google.com/maps/test"
        payload = self.payload(125, total=331)
        page.evaluate.return_value = {"place_name": payload["place"], "source_url": payload["sourceUrl"],
                                      "displayed_total": 331, "reviews": payload["reviews"]}
        context = MagicMock(pages=[page])
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "collect_from_local_service", return_value=False), \
                patch("playwright.sync_api.sync_playwright"), patch.object(cli, "collection_browser") as launching, \
                patch.object(cli, "prepare_reviews"), patch.object(cli, "blocked", return_value=False), \
                patch.object(cli, "expand_text"), patch.object(cli, "scroll_reviews") as scrolling, redirect_stdout(io.StringIO()):
            launching.return_value.__enter__.return_value = context
            self.assertEqual(cli.main([page.url, "--visible-only", "--output-dir", folder]), 0)
            scrolling.assert_not_called()
            metadata = json.loads(next(Path(folder).glob("*.json")).read_text())["metadata"]
            self.assertEqual(metadata["count"], 125)
            self.assertEqual(metadata["missing_count"], 206)
            self.assertFalse(metadata["full_coverage_verified"])

    def test_invalid_destination_fails_before_starting_collection(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "already-a-file"
            file.write_text("keep this")
            with patch.object(cli, "collect_from_local_service") as collecting, redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--output-dir", str(file)]), 1)
                collecting.assert_not_called()
            self.assertEqual(file.read_text(), "keep this")

    def test_incomplete_retry_command_preserves_browser_and_collection_options(self):
        def partial(args, reviews, metadata):
            data = self.payload(1)
            cli.merge_reviews(reviews, data["reviews"], data["place"], data["sourceUrl"])
            metadata.update(place_name=data["place"], displayed_total_end=2, stop_reason="制限時間に到達")
            return True
        with tempfile.TemporaryDirectory(prefix="reviews folder ") as folder, \
                patch.object(cli, "collect_from_local_service", side_effect=partial), \
                patch.object(sys.stdin, "isatty", return_value=True), redirect_stdout(io.StringIO()):
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--manual", "--browser", "chromium",
                                           "--delay", "3", "--output-dir", folder]), 2)
            retry = next(line.split(": ", 1)[1] for line in errors.getvalue().splitlines() if line.startswith("待機時間を延ばして再実行:"))
            tokens = shlex.split(retry)
            self.assertIn("--manual", tokens)
            for option, expected in [("--timeout", "1200"), ("--browser", "chromium"), ("--delay", "3.0"), ("--output-dir", str(Path(folder).resolve()))]:
                self.assertEqual(tokens[tokens.index(option) + 1], expected)

    def test_custom_timeout_is_forwarded_to_the_local_collector(self):
        opener = MagicMock()
        opener.open.side_effect = [io.BytesIO(b'{"ready":true,"version":"1.0.0"}'),
                                   self.stream([{"type": "done", "data": self.payload(2)}])]
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "build_opener", return_value=opener), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--use-service", "--timeout", "1200", "--output-dir", folder]), 0)
            self.assertEqual(json.loads(opener.open.call_args.args[0].data)["timeout"], 1200)

    def test_unverified_service_result_is_not_reported_as_complete(self):
        data = dict(self.payload(2), verified=False, reason="途中で停止しました")
        opener = MagicMock()
        opener.open.side_effect = [io.BytesIO(b'{"ready":true,"version":"1.0.0"}'), self.stream([{"type": "done", "data": data}])]
        with tempfile.TemporaryDirectory() as folder, patch.object(cli, "build_opener", return_value=opener), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["https://www.google.com/maps/test", "--all", "--use-service", "--output-dir", folder]), 2)
            metadata = json.loads(next(Path(folder).glob("*.json")).read_text())["metadata"]
            self.assertEqual(metadata["count"], 2)
            self.assertFalse(metadata["full_coverage_verified"])

    def test_custom_options_and_unavailable_service_keep_the_cli_browser(self):
        for flags in (["--max", "5"], ["--all", "--manual"], ["--visible-only"],
                      ["--all", "--browser", "chromium"], ["--all", "--delay", "3"]):
            args = cli.build_parser().parse_args(["https://www.google.com/maps/test", *flags])
            with patch.object(cli, "build_opener") as opener:
                self.assertFalse(cli.collect_from_local_service(args, {}, {}))
                opener.assert_not_called()
        args = cli.build_parser().parse_args(["https://www.google.com/maps/test", "--all", "--use-service"])
        for response in (b'{"ready":false,"version":"1.0.0"}', b'{"ready":true,"version":"another-service"}'):
            opener = MagicMock()
            opener.open.return_value = io.BytesIO(response)
            with patch.object(cli, "build_opener", return_value=opener):
                self.assertFalse(cli.collect_from_local_service(args, {}, {}))
                opener.open.assert_called_once()


class InstallerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).resolve().parents[1] / "install-cli.py"
        spec = importlib.util.spec_from_file_location("review_cli_installer", script)
        cls.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.installer)

    def pipx_fixture(self, prefix):
        target = prefix / "pipx/venvs/google-maps-reviews/bin/google-maps-reviews"
        target.parent.mkdir(parents=True)
        target.write_text("pipx app", encoding="utf-8")
        command = prefix / "bin/google-maps-reviews"
        command.parent.mkdir()
        command.symlink_to(target)
        package = {"package": "google-maps-reviews", "apps": ["google-maps-reviews"],
                   "app_paths": [{"__Path__": str(target), "__type__": "Path"}]}
        data = {"venvs": {"google-maps-reviews": {"metadata": {"main_package": package}}}}
        return command, target, data

    def test_installer_rejects_non_mac_before_changing_files(self):
        with patch.object(sys, "platform", "linux"), patch.object(self.installer, "check_destination") as destination, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                self.installer.main([])
            self.assertEqual(result.exception.code, 2)
            destination.assert_not_called()

    def test_existing_pipx_is_updated_without_replacing_link_or_saved_settings(self):
        with tempfile.TemporaryDirectory(prefix="pipx space ") as folder:
            prefix = Path(folder).resolve()
            command, target, data = self.pipx_fixture(prefix)
            settings = prefix / "settings.json"
            settings.write_text('{"max":17}', encoding="utf-8")
            source = Path(__file__).resolve().parents[1]
            def run(args, **kwargs):
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(data))
            with patch.object(self.installer.shutil, "which", return_value="/bin/pipx"), patch.object(self.installer.subprocess, "run", side_effect=run) as running, patch.object(self.installer.venv, "EnvBuilder") as builder, patch.dict("os.environ", {"GOOGLE_MAPS_REVIEWS_CONFIG": str(settings)}), redirect_stdout(io.StringIO()):
                for _ in range(2):
                    self.assertEqual(self.installer.main(["--prefix", str(prefix), "--source", str(source), "--browser", "chrome"]), 0)
                builder.assert_not_called()
            self.assertTrue(command.is_symlink())
            self.assertEqual(command.resolve(), target)
            self.assertEqual(settings.read_text(encoding="utf-8"), '{"max":17}')
            cached = prefix / "share/google-maps-reviews/pipx-source"
            self.assertTrue((cached / "src/google_maps_reviews/extract_reviews.js").is_file())
            self.assertFalse((cached / "web").exists())
            installs = [call for call in running.call_args_list if call.args[0][1] == "install"]
            self.assertEqual(len(installs), 2)
            self.assertEqual(installs[0].args[0], ["/bin/pipx", "install", "--force", str(cached)])
            self.assertEqual(installs[0].kwargs["env"]["PIPX_BIN_DIR"], str(command.parent))
            self.assertEqual(running.call_args.args[0], [str(command), "setup", "--browser", "chrome"])

    def test_foreign_or_unregistered_symlink_is_not_updated(self):
        for invalid in ("wrong_target", "wrong_package", "missing_app", "invalid_json", "broken_link"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as folder:
                prefix = Path(folder)
                command, target, data = self.pipx_fixture(prefix)
                package = data["venvs"]["google-maps-reviews"]["metadata"]["main_package"]
                if invalid == "wrong_target":
                    package["app_paths"] = [str(prefix / "another-app")]
                elif invalid == "wrong_package":
                    package["package"] = "another-app"
                elif invalid == "missing_app":
                    package["apps"] = []
                elif invalid == "broken_link":
                    target.unlink()
                result = subprocess.CompletedProcess([], 0, stdout="invalid" if invalid == "invalid_json" else json.dumps(data))
                with patch.object(self.installer.shutil, "which", return_value="/bin/pipx"), patch.object(self.installer.subprocess, "run", return_value=result) as running, redirect_stderr(io.StringIO()):
                    self.assertEqual(self.installer.main(["--prefix", str(prefix), "--source", str(Path(__file__).resolve().parents[1])]), 1)
                self.assertTrue(command.is_symlink())
                self.assertFalse((prefix / "share").exists())
                self.assertTrue(all(call.args[0] == ["/bin/pipx", "list", "--json"] for call in running.call_args_list))

    def test_pipx_source_cache_requires_matching_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            _command, target, _data = self.pipx_fixture(prefix)
            cached = prefix / "share/google-maps-reviews/pipx-source"
            cached.mkdir(parents=True)
            existing = cached / "keep.txt"
            existing.write_text("keep", encoding="utf-8")
            with patch.object(self.installer.subprocess, "run") as running, self.assertRaises(RuntimeError):
                self.installer.install_with_pipx(Path(__file__).resolve().parents[1], (prefix, target, "/bin/pipx"), "chrome")
            running.assert_not_called()
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_unrelated_command_and_virtual_environment_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            command = prefix / "bin/google-maps-reviews"
            command.parent.mkdir()
            command.write_text("another application's command", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                self.installer.check_destination(prefix)
            self.assertEqual(command.read_text(encoding="utf-8"), "another application's command")
            command.unlink()
            environment = prefix / "share/google-maps-reviews/venv"
            environment.mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                self.installer.check_destination(prefix)

    def test_prefix_isolates_command_virtual_environment_and_configuration(self):
        with tempfile.TemporaryDirectory(prefix="cli install space ") as folder:
            prefix = (Path(folder) / "user prefix").resolve()
            source = Path(__file__).resolve().parents[1]
            with patch.object(self.installer.venv, "EnvBuilder") as builder, patch.object(self.installer.subprocess, "run") as running, redirect_stdout(io.StringIO()):
                self.assertEqual(self.installer.main(["--prefix", str(prefix), "--source", str(source), "--browser", "chrome"]), 0)
                self.assertEqual(self.installer.main(["--prefix", str(prefix), "--source", str(source), "--browser", "chrome"]), 0)
            environment = prefix / "share/google-maps-reviews/venv"
            settings = prefix / "share/google-maps-reviews/settings.json"
            command = prefix / "bin/google-maps-reviews"
            self.assertEqual(command.read_text(encoding="utf-8"), self.installer.launcher_text(environment / "bin/google-maps-reviews", settings))
            self.assertEqual(command.stat().st_mode & 0o777, 0o755)
            builder.return_value.create.assert_called_with(environment)
            self.assertEqual(running.call_args.args[0], [str(environment / "bin/google-maps-reviews"), "setup", "--browser", "chrome", "--config", str(settings)])

    def test_public_archive_is_downloaded_without_github_authentication(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("source-root/pyproject.toml", "[project]\nname='google-maps-reviews'\n")
                archive.writestr("source-root/src/google_maps_reviews/cli.py", "# source\n")
            with patch.object(self.installer, "urlopen", return_value=io.BytesIO(payload.getvalue())) as download:
                source = self.installer.fetch_source("main", Path(folder))
            download.assert_called_once_with("https://codeload.github.com/atsuki-sakai/google-maps-reviews/zip/main", timeout=60)
            self.assertTrue((source / "src/google_maps_reviews/cli.py").is_file())

    def test_archive_cannot_write_outside_temporary_source_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("../outside.txt", "unexpected")
            with patch.object(self.installer, "urlopen", return_value=io.BytesIO(payload.getvalue())), self.assertRaises(RuntimeError):
                self.installer.fetch_source("main", Path(folder))
            self.assertFalse((Path(folder) / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
