#!/usr/bin/env python3
"""Collect Google Maps reviews from rendered browser UI and export local files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from . import __version__

ROOT = Path(__file__).resolve().parent
REVIEW_CARD_SELECTOR = '[data-review-id]:not([data-review-id] [data-review-id])'
FIELDS = [
    ("place_name", "店舗名"), ("author", "投稿者"), ("rating", "星評価"),
    ("date_text", "投稿日（画面表記）"), ("text", "口コミ本文"),
    ("owner_reply", "店舗側の返信"), ("review_id", "口コミID"),
    ("review_url", "口コミURL（表示された場合）"), ("author_url", "投稿者URL"),
    ("source_url", "店舗URL"), ("collected_at", "取得日時"),
    ("text_may_be_truncated", "本文の省略あり"), ("raw_visible_text", "カード全体の表示テキスト"),
]


def maps_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    valid = (
        host == "maps.app.goo.gl"
        or (host == "goo.gl" and parsed.path.startswith("/maps"))
        or (host in {"google.com", "www.google.com", "maps.google.com", "google.co.jp", "www.google.co.jp", "maps.google.co.jp"}
            and (host.startswith("maps.") or parsed.path.startswith("/maps")))
    )
    if parsed.scheme != "https" or not valid or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("GoogleマップのHTTPS URLを指定してください。")
    return value


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("1以上の数値を指定してください。")
    return result


def positive_seconds(value: str) -> float:
    result = float(value)
    if not (0.5 <= result <= 60):
        raise argparse.ArgumentTypeError("0.5〜60秒の範囲を指定してください。")
    return result


def merge_reviews(existing: dict, rows: list[dict], place: str, url: str) -> int:
    added = 0
    for row in rows:
        if not row.get("author") or row.get("rating") is None:
            continue
        row = dict(row)
        key = row.get("review_id") or hashlib.sha256(
            json.dumps([row.get(k) for k in ("author", "rating", "date_text")], ensure_ascii=False).encode()
        ).hexdigest()
        old = existing.get(key)
        # Keep an already expanded body when a later virtualized card is collapsed.
        if old and len(old.get("text", "")) > len(row.get("text", "")):
            row["text"] = old["text"]
            row["text_may_be_truncated"] = old.get("text_may_be_truncated", False)
        if old and len(old.get("owner_reply", "")) > len(row.get("owner_reply", "")):
            row["owner_reply"] = old["owner_reply"]
        row.update(place_name=place, source_url=url,
                   collected_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        existing[key] = row
        added += old is None
    return added


def csv_text(value):
    # Preserve literal review content in JSON; avoid formulas when CSV opens in Excel.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_reviews(rows: list[dict], metadata: dict, output_dir: Path, stem: str) -> list[Path]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    def spreadsheet_value(value):
        return ILLEGAL_CHARACTERS_RE.sub("", value)[:32767] if isinstance(value, str) else value

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, xlsx_path, json_path = [output_dir / f"{stem}.{ext}" for ext in ("csv", "xlsx", "json")]
    # A JSON snapshot is saved first so original text survives spreadsheet failures.
    tmp_json = json_path.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps({"metadata": metadata, "reviews": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(json_path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([title for _, title in FIELDS])
        for row in rows:
            writer.writerow([csv_text(row.get(key, "")) for key, _ in FIELDS])
    book = Workbook()
    sheet = book.active
    sheet.title = "口コミ"
    sheet.append([title for _, title in FIELDS])
    for row in rows:
        sheet.append([spreadsheet_value(row.get(key, "")) for key, _ in FIELDS])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = [26, 22, 10, 24, 70, 55, 26, 30, 30, 35, 30, 16, 65]
    for column, width in zip("ABCDEFGHIJKLM", widths):
        sheet.column_dimensions[column].width = width
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="203864")
        cell.font = Font(name="Arial", color="FFFFFF", bold=True)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str):
                cell.value = ILLEGAL_CHARACTERS_RE.sub("", cell.value)[:32767]
                cell.data_type = "s"
            cell.font = Font(name="Arial", size=11)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.row_dimensions[row[0].row].height = 75
    summary = book.create_sheet("取得情報")
    summary.append(["項目", "内容"])
    labels = {
        "place_name": "店舗名", "source_url": "取得元URL", "collected_at": "取得日時",
        "count": "保存件数", "stop_reason": "停止理由", "requested_max": "指定した最大件数",
        "coverage": "収集範囲", "error": "エラー", "sample": "サンプルデータ",
        "displayed_total_start": "開始時の画面総件数", "displayed_total_end": "終了時の画面総件数",
        "full_coverage_verified": "総件数と重複なし保存件数の一致", "truncated_count": "本文の省略表示が残った件数",
        "incomplete": "全件取得未確認",
    }
    for key, value in metadata.items():
        summary.append([labels.get(key, key), spreadsheet_value(str(value))])
    summary.append(["投稿日", "「1か月前」等の表示をそのまま保存。日付の推定はしていません。"])
    summary.append(["本文と返信", "画面に表示されたテキスト。翻訳や省略が含まれる場合があります。"])
    summary.append(["CSV", "Excelで数式扱いされる文字列の先頭にアポストロフィを付けています。元データはJSONに保存。"])
    summary.append(["長い本文", "Excelは1セル32,767文字まで。超過分と制御文字はCSV・JSONに保存されています。"])
    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 100
    for row in summary:
        for cell in row:
            cell.data_type = "s"
            cell.font = Font(name="Arial", size=11)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    book.save(xlsx_path)
    return [csv_path, xlsx_path, json_path]


def prepare_reviews(page, manual: bool):
    if not manual:
        # Maps populates the place panel after DOMContentLoaded, especially in a
        # fresh Chrome profile. Do not fall back to stdin while it is still loading.
        try:
            page.get_by_role("main").first.wait_for(state="visible", timeout=45000)
        except Exception:
            pass
        try:
            page.locator(REVIEW_CARD_SELECTOR).first.wait_for(state="visible", timeout=15000)
            return
        except Exception:
            pass
        for role in ("tab", "button"):
            target = page.get_by_role(role, name=re.compile(r"口コミ|クチコミ|reviews", re.I))
            for index in range(min(target.count(), 5)):
                try:
                    candidate = target.nth(index)
                    label = (candidate.get_attribute("aria-label") or "") + " " + candidate.inner_text()
                    if re.search(r"書く|投稿|write|add a review", label, re.I):
                        continue
                    if candidate.is_visible():
                        candidate.click(timeout=3000)
                        page.locator('[data-review-id]').first.wait_for(state="visible", timeout=10000)
                        return
                except Exception:
                    continue
    print("ブラウザーで対象店舗の「口コミ」を開いてください。並び順や絞り込みも画面で選べます。")
    if not sys.stdin.isatty():
        raise RuntimeError("口コミ一覧を自動で開けませんでした。ターミナルで--manualを指定して再実行してください。")
    try:
        input("口コミが表示されたら、このターミナルでEnterを押してください: ")
    except EOFError as error:
        raise RuntimeError("手動操作にはターミナルが必要です。店舗URLを指定して再実行してください。") from error
    page.locator('[data-review-id]').first.wait_for(state="visible", timeout=15000)


def expand_text(page, processed: set[str]):
    cards = page.locator(REVIEW_CARD_SELECTOR)
    for index in range(cards.count()):
        card = cards.nth(index)
        review_id = card.get_attribute("data-review-id")
        if review_id in processed:
            continue
        buttons = card.get_by_role("button", name=re.compile(r"^(もっと見る|全文を表示|More|See more|Read more)$", re.I))
        for button_index in range(buttons.count()):
            try:
                button = buttons.nth(button_index)
                if button.is_visible():
                    button.click(timeout=1200)
            except Exception:
                # Preserve partial text and record the remaining More button.
                continue
        if review_id:
            processed.add(review_id)


def review_scroll_state(page) -> dict:
    return page.locator(REVIEW_CARD_SELECTOR).first.evaluate("""card => {
        for (let el = card.parentElement; el; el = el.parentElement) {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            if (/(auto|scroll)/.test(style.overflowY) && el.clientHeight > 0 && rect.width > 0) {
                return {top: el.scrollTop, height: el.clientHeight, total: el.scrollHeight,
                    at_end: el.scrollTop + el.clientHeight >= el.scrollHeight - 8,
                    x: Math.max(1, Math.min(innerWidth - 1, rect.x + rect.width / 2)),
                    y: Math.max(1, Math.min(innerHeight - 1, rect.y + rect.height / 2))};
            }
        }
        return null;
    }""")


def scroll_reviews(page) -> dict:
    state = review_scroll_state(page)
    if not state:
        raise RuntimeError("口コミ一覧のスクロール領域を特定できません。口コミタブを開いて再実行してください。")
    # Native wheel input triggers Maps' lazy loading. All currently loaded cards
    # are captured before this jump; expanding each review only once avoids resets.
    page.mouse.move(state["x"], state["y"])
    page.mouse.wheel(0, max(state["total"], state["height"] * 3))
    return state


def next_stagnant_count(previous: int, added: int, state: dict | None) -> int:
    # Reading through already loaded long reviews is progress, even with zero new IDs.
    return previous + 1 if not added and state and state["at_end"] else 0


def full_coverage_verified(rows: list[dict], expected: int | None) -> bool:
    ids = [row.get("review_id") for row in rows]
    return bool(expected is not None and expected > 0 and len(rows) == expected
                and all(ids) and len(set(ids)) == expected)


def blocked(page) -> bool:
    if "/sorry/" in page.url or page.locator('iframe[src*="recaptcha"], #captcha-form').count():
        return True
    if page.locator('[data-review-id]').count():
        return False
    body = page.locator("body").inner_text(timeout=3000)
    return bool(re.search(r"unusual traffic|通常と異なるトラフィック|自動化されたクエリ", body, re.I))


def build_parser():
    parser = argparse.ArgumentParser(prog="google-maps-reviews", description="Googleマップの表示された口コミを読み取り、CSV・Excel・JSONに保存します。無引数で対話メニューを開きます。", epilog="準備: google-maps-reviews setup --browser chromium / 設定: google-maps-reviews settings show")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("url", nargs="?", type=maps_url, help="店舗URL。省略時はブラウザーで店舗を選択")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--max", type=positive_int, default=100, help="最大取得件数（既定:100）")
    scope.add_argument("--all", action="store_true", help="件数上限なしで収集し、画面の総件数との一致を確認")
    parser.add_argument("--manual", action="store_true", help="口コミの画面を自分で開いてから収集")
    parser.add_argument("--visible-only", action="store_true", help="スクロールせず現在読み込まれた口コミだけ保存")
    parser.add_argument("--delay", type=positive_seconds, default=2.0, help="スクロール後の待機秒数（既定:2）")
    parser.add_argument("--timeout", type=positive_int, default=300, help="収集の制限秒数（既定:300、手動操作時間を除く）")
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "Desktop" / "GoogleMap口コミ")
    parser.add_argument("--browser", choices=("chrome", "chromium"), default="chrome")
    parser.add_argument("--demo", action="store_true", help="実在の口コミではないサンプルで出力確認")
    parser.add_argument("--interactive", action="store_true", help="対話メニューを開く（ターミナル専用）")
    parser.add_argument("--use-settings", action="store_true", help="保存設定を使用。明示したオプションを優先")
    parser.add_argument("--config", type=Path, help="設定ファイルを指定（環境変数GOOGLE_MAPS_REVIEWS_CONFIGも使用可）")
    return parser


def main(argv=None) -> int:
    from .console import dispatch
    return dispatch(list(sys.argv[1:] if argv is None else argv), build_parser())


def collect_from_local_service(args, reviews: dict, metadata: dict) -> bool:
    # The Mac service owns a dedicated Chrome and its login state. Use it for
    # automatic all-review runs; custom scrolling/manual options use the CLI browser.
    if not args.url or not args.all or args.manual or args.visible_only or args.browser != "chrome" or args.delay != 2.0:
        return False
    endpoint = "http://127.0.0.1:38473"
    headers = {"Origin": "https://google-maps-reviews.vercel.app"}
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(Request(endpoint + "/health", headers=headers), timeout=1) as response:
            health = json.load(response)
        if health.get("ready") is not True or health.get("version") != "1.0.0":
            return False
    except (OSError, ValueError, AttributeError):
        return False
    metadata["collector"] = "このMacの収集サービス"
    started = time.monotonic()
    try:
        if health.get("busy"):
            raise RuntimeError("このMacでは口コミを収集中です。完了後に再実行してください。")
        print("このMacの専用Chromeで収集しています。", flush=True)
        request = Request(endpoint + "/collect", data=json.dumps({"url": args.url}).encode(),
                          headers=dict(headers, **{"Content-Type": "application/json"}))
        with opener.open(request, timeout=args.timeout) as response:
            for line in response:
                if time.monotonic() - started >= args.timeout:
                    raise RuntimeError("制限時間に到達しました。取得済みの口コミを保存します。")
                if not line.startswith(b"data: "):
                    continue
                event = json.loads(line[6:])
                if event["type"] == "error":
                    raise RuntimeError(event["message"])
                if event["type"] == "status":
                    print(event["message"], flush=True)
                    continue
                if event["type"] not in {"progress", "done"}:
                    continue
                data = event["data"]
                merge_reviews(reviews, data["reviews"], data["place"], data["sourceUrl"])
                metadata.update(place_name=data["place"], source_url=data["sourceUrl"],
                                displayed_total_end=data["displayedTotal"])
                if data["displayedTotal"] is not None:
                    metadata.setdefault("displayed_total_start", data["displayedTotal"])
                print(f"取得済み: {len(reviews)}件 / 画面の総件数: {data['displayedTotal']}", flush=True)
                if event["type"] == "done":
                    metadata["stop_reason"] = data["reason"]
                    metadata["service_verified"] = data["verified"] is True
                    return True
        raise RuntimeError("収集サービスとの接続が途中で終了しました。")
    except KeyboardInterrupt:
        metadata["stop_reason"] = "ユーザーが中断（取得済みデータを保存）"
    except Exception as error:
        metadata.update(stop_reason="エラーによる停止", error=str(error))
        print(f"収集中に停止しました: {error}", file=sys.stderr)
    return True


def run_collection(args) -> int:
    limit = sys.maxsize if args.all else args.max
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    metadata = {"collected_at": now.isoformat(timespec="seconds"), "requested_max": "全件" if args.all else args.max,
                "coverage": "画面から読み取れた口コミのみ。全件取得の保証はありません。"}
    reviews = {}
    if args.demo:
        merge_reviews(reviews, [{"review_id": "DEMO-001", "author": "サンプル投稿者（架空）", "rating": 4,
                      "date_text": "1か月前（サンプル）", "text": "動作確認用の架空の口コミです。\n実在する店舗の口コミではありません。",
                      "owner_reply": "サンプルの返信です。", "text_may_be_truncated": False}],
                      "サンプル店舗（架空）", "")
        metadata.update(place_name="サンプル店舗（架空）", source_url="", stop_reason="出力テスト", sample=True)
    elif collect_from_local_service(args, reviews, metadata):
        pass
    else:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("依存ライブラリがありません。ツールを再インストールしてください。", file=sys.stderr)
            return 1
        extractor = (ROOT / "extract_reviews.js").read_text(encoding="utf-8")
        context = None
        try:
            with tempfile.TemporaryDirectory(prefix="maps-reviews-") as profile, sync_playwright() as pw:
                try:
                    launch = {"headless": False, "locale": "ja-JP", "viewport": {"width": 1280, "height": 900}}
                    if args.browser == "chrome":
                        launch["channel"] = "chrome"
                    context = pw.chromium.launch_persistent_context(profile, **launch)
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(10000)
                    page.goto(args.url or "https://www.google.com/maps?hl=ja", wait_until="domcontentloaded", timeout=45000)
                    prepare_reviews(page, args.manual or not args.url)
                    metadata.update(source_url=page.url)
                    started = time.monotonic()
                    stagnant = 0
                    expanded_ids = set()
                    while True:
                        if blocked(page):
                            metadata["stop_reason"] = "確認画面のため停止"
                            break
                        expand_text(page, expanded_ids)
                        data = page.evaluate(extractor)
                        place = data["place_name"] or metadata.get("place_name") or "店舗名取得不可"
                        metadata.update(place_name=place, source_url=data["source_url"])
                        if data.get("displayed_total") is not None:
                            metadata.setdefault("displayed_total_start", data["displayed_total"])
                            metadata["displayed_total_end"] = data["displayed_total"]
                        added = merge_reviews(reviews, data["reviews"], place, data["source_url"])
                        if data["reviews"] and not reviews:
                            raise RuntimeError("口コミは表示されていますが、投稿者または評価を読み取れません。ツールを更新してください。")
                        print(f"取得済み: {min(len(reviews), limit)}件 / 画面の総件数: {metadata.get('displayed_total_end', '不明')}", flush=True)
                        if len(reviews) >= limit:
                            metadata["stop_reason"] = "指定件数に到達"
                            break
                        if args.visible_only:
                            metadata["stop_reason"] = "現在読み込まれた口コミのみ保存"
                            break
                        if time.monotonic() - started >= args.timeout:
                            metadata["stop_reason"] = "制限時間に到達"
                            break
                        if not data["reviews"]:
                            raise RuntimeError("口コミカードを読み取れません。画面変更または未対応の表示形式です。")
                        state = review_scroll_state(page)
                        stagnant = next_stagnant_count(stagnant, added, state)
                        if stagnant >= 8:
                            metadata["stop_reason"] = "口コミ一覧の末尾で追加読み込みがないため停止（全件取得は未確認）"
                            break
                        scroll_reviews(page)
                        time.sleep(args.delay)
                finally:
                    if context:
                        if sys.exc_info()[0] is not None:
                            try:
                                diagnostics = args.output_dir.expanduser().resolve()
                                diagnostics.mkdir(parents=True, exist_ok=True)
                                page.screenshot(path=str(diagnostics / f"収集エラー_{stamp}.png"))
                                (diagnostics / f"収集エラー_{stamp}.txt").write_text(
                                    page.url + "\n" + page.locator("body").inner_text(timeout=3000), encoding="utf-8")
                            except Exception:
                                pass
                        context.close()
        except KeyboardInterrupt:
            metadata["stop_reason"] = "ユーザーが中断（取得済みデータを保存）"
        except Exception as error:
            metadata.update(stop_reason="エラーによる停止", error=str(error))
            print(f"収集中に停止しました: {error}", file=sys.stderr)
    rows = list(reviews.values())[:limit]
    metadata["count"] = len(rows)
    if not args.demo:
        metadata["full_coverage_verified"] = (full_coverage_verified(rows, metadata.get("displayed_total_end"))
                                              and "error" not in metadata and metadata.get("service_verified", True) is True)
        metadata["truncated_count"] = sum(bool(row.get("text_may_be_truncated")) for row in rows)
        if metadata["full_coverage_verified"]:
            metadata["coverage"] = f"画面の総件数と口コミIDの重複なしの保存件数が一致: {len(rows)}件"
            if args.all and metadata.get("stop_reason", "").startswith("口コミ一覧の末尾"):
                metadata["stop_reason"] = "口コミ一覧の末尾に到達し、画面の総件数との一致を確認"
        elif args.all:
            metadata["incomplete"] = True
            print(f"全件取得は未確認です。保存{len(rows)}件 / 画面{metadata.get('displayed_total_end', '不明')}件。", file=sys.stderr)
    if not rows:
        print("口コミを取得できなかったため、口コミファイルは生成していません。", file=sys.stderr)
        if args.browser == "chromium":
            print("Chromium未導入の場合: google-maps-reviews setup --browser chromium", file=sys.stderr)
        return 1
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", metadata.get("place_name", "口コミ"))[:60].strip(" .") or "口コミ"
    stem = f"{'サンプル_' if args.demo else ''}{name}_口コミ_{stamp}"
    try:
        paths = export_reviews(rows, metadata, args.output_dir.expanduser().resolve(), stem)
    except Exception as error:
        print(f"ファイル保存に失敗しました: {error}", file=sys.stderr)
        return 1
    print(f"\n{len(rows)}件を保存しました。停止理由: {metadata['stop_reason']}")
    for path in paths:
        print(path)
    return 2 if "error" in metadata or metadata.get("incomplete") else 0


if __name__ == "__main__":
    raise SystemExit(main())
