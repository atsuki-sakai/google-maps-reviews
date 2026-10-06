#!/usr/bin/env python3
"""Collect Google Maps reviews from rendered browser UI and export local files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shlex
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import __version__
from .browser import collection_browser
from .dates import iso_date, partition_period, select_period

ROOT = Path(__file__).resolve().parent
REVIEW_CARD_SELECTOR = '[data-review-id]:not([data-review-id] [data-review-id])'
FIELDS = [
    ("place_name", "店舗名"), ("author", "投稿者"), ("rating", "星評価"),
    ("date_text", "投稿日（画面表記）"), ("text", "口コミ本文"),
    ("owner_reply", "店舗側の返信"), ("review_id", "口コミID"),
    ("review_url", "口コミURL（表示された場合）"), ("author_url", "投稿者URL"),
    ("source_url", "店舗URL"), ("collected_at", "取得日時"),
    ("text_may_be_truncated", "本文の省略あり"), ("raw_visible_text", "カード全体の表示テキスト"),
    ("date_earliest", "日付範囲の開始（推定を含む）"), ("date_latest", "日付範囲の終了（推定を含む）"),
    ("date_precision", "日付の精度"), ("period_match", "期間判定"),
]


def maps_url(value: str) -> str:
    value = value.strip()
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


def place_identity(value: str) -> tuple[str, str] | None:
    """Read a stable place identifier when the Maps URL contains one."""
    value = unquote(value)
    query = parse_qs(urlparse(value).query)
    pair = re.search(r"!1s0x[0-9a-f]+:0x([0-9a-f]+)(?:!|[?&#]|$)", value, re.I)
    if pair:
        return "cid", str(int(pair.group(1), 16))
    cid = query.get("cid", [""])[0]
    if re.fullmatch(r"[0-9]+", cid):
        return "cid", str(int(cid))
    place_id = query.get("query_place_id", query.get("place_id", [""]))[0]
    encoded = re.search(r"!1s(ChIJ[\w-]+)(?:!|[?&#]|$)", value)
    if place_id or encoded:
        return "place_id", place_id or encoded.group(1)
    entity = re.search(r"!(?:16|1)s(/(?:g|m)/[\w-]+)(?:!|[?&#]|$)", value)
    return ("entity", entity.group(1)) if entity else None


def ensure_same_place(expected: str, actual: str):
    first, second = place_identity(expected), place_identity(actual)
    if first and second and first[0] == second[0] and first != second:
        raise ValueError("指定URLとは別施設の口コミ画面です。指定施設の口コミを開いて再実行してください。")


def resolve_maps_url(value: str) -> str:
    """Resolve a share link before opening an owned collection tab."""
    if urlparse(value).hostname not in {"maps.app.goo.gl", "goo.gl"}:
        return value

    class MapsRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            maps_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = build_opener(ProxyHandler({}), MapsRedirects())
    with opener.open(Request(value), timeout=20) as response:
        resolved = maps_url(response.geturl())
    if place_identity(resolved) is None:
        raise ValueError("共有URLから対象店舗を確認できません。店舗ページのURLを指定してください。")
    return resolved


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
        # Expanded text takes precedence over length: a collapsed view may
        # include extra labels and be longer than the actual expanded body.
        old_text = old.get("text", "") if old else ""
        next_text = row.get("text", "")
        old_truncated = bool(old and old.get("text_may_be_truncated"))
        next_truncated = bool(row.get("text_may_be_truncated"))
        if old_text and (not next_text or (not old_truncated and next_truncated)
                         or (old_truncated == next_truncated and len(old_text) > len(next_text))):
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


def has_review_text(row: dict) -> bool:
    """Only the customer's body qualifies; owner replies and stars do not."""
    return bool(row.get("text", "").strip())


def export_reviews(rows: list[dict], metadata: dict, output_dir: Path, stem: str) -> list[Path]:
    if metadata.get("review_filter") == "text_only":
        groups = (rows, metadata.get("period_uncertain_reviews", []), metadata.get("period_excluded_reviews", []))
        if any(not has_review_text(row) for group in groups for row in group):
            raise ValueError("保存対象に本文のない投稿が混入しています。")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, xlsx_path, json_path = [output_dir / f"{stem}.{ext}" for ext in ("csv", "xlsx", "json")]
    # A JSON snapshot is saved first so original text survives spreadsheet failures.
    tmp_json = json_path.with_suffix(".json.tmp")
    metadata = dict(metadata)
    snapshot = {"metadata": metadata, "reviews": rows}
    for group in ("uncertain", "excluded"):
        key = f"period_{group}_reviews"
        if key in metadata:
            snapshot[f"{group}_reviews"] = metadata.pop(key)
    tmp_json.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(json_path)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([title for _, title in FIELDS])
        for row in rows:
            writer.writerow([csv_text(row.get(key, "")) for key, _ in FIELDS])
    write_review_excel(snapshot, xlsx_path)
    return [csv_path, xlsx_path, json_path]


def write_review_excel(snapshot: dict, path: Path):
    """Format a collected snapshot without collecting or rewriting its evidence."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Font
    from .excel import OVERFLOW_SHEET, write_table

    metadata = snapshot["metadata"]
    book = Workbook()
    book.remove(book.active)
    widths = [20, 18, 8, 20, 72, 40, 26, 30, 30, 35, 28, 16, 65, 22, 22, 32, 20]
    hidden = {1, *range(7, 17)}
    if not metadata.get("date_from") and not metadata.get("date_to"):
        hidden.add(17)
    for key, title in (("reviews", "口コミ"), ("uncertain_reviews", "期間境界・日付不明"), ("excluded_reviews", "期間外")):
        if key != "reviews" and not snapshot.get(key):
            continue
        sheet = write_table(book, title, [title for _, title in FIELDS],
                            ([review.get(field, "") for field, _ in FIELDS] for review in snapshot.get(key, [])),
                            widths=widths, hidden_columns=hidden, freeze_panes="E2",
                            print_columns=(2, 17 if 17 not in hidden else 6))
        sheet.sheet_properties.tabColor = "B7791F" if key == "uncertain_reviews" else "64748B" if key == "excluded_reviews" else "243B53"
        sheet["E1"].comment = Comment(
            "本文は原文を保持しています。行高の上限を超える長文は「長文の続き」シートでも全文を読めます。非表示の確認用列にはID・URL・日付の推定範囲を残しています。", "google-maps-reviews")
    labels = {
        "place_name": "店舗名", "source_url": "取得元URL", "collected_at": "取得日時",
        "count": "保存件数", "stop_reason": "停止理由", "requested_max": "指定した最大件数",
        "coverage": "収集範囲", "error": "エラー", "sample": "サンプルデータ",
        "displayed_total_start": "開始時の画面総件数", "displayed_total_end": "終了時の画面総件数",
        "full_coverage_verified": "一覧照合後の本文あり全件保存確認", "truncated_count": "本文の省略表示が残った件数",
        "saved_text_truncated_count": "全保存区分で本文の省略が残った件数",
        "incomplete": "収集・期間抽出の要確認あり",
        "text_review_count": "本文ありの口コミ件数", "rating_only_count": "評価のみの口コミ件数",
        "missing_count": "画面総件数との差（未取得件数）",
        "date_from": "期間の開始日", "date_to": "期間の終了日", "scanned_count": "一覧の読取件数（評価のみを含む）",
        "review_filter": "保存対象", "scanned_text_review_count": "一覧の本文あり読取件数",
        "excluded_rating_only_count": "評価のみの除外件数",
        "scan_coverage_verified": "一覧全件の読取件数照合", "period_selection_verified": "期間境界・日付不明なし（丸め仮定を含む）",
        "period_date_accuracy_verified": "正確な表示日付による期間抽出の確認",
        "period_exact_date_count": "日付表示の読取件数", "period_estimated_date_count": "相対表示から推定した読取件数",
        "period_unknown_date_count": "投稿日不明の読取件数",
        "period_uncertain_count": "期間境界・日付不明件数", "period_excluded_count": "期間外件数", "date_filter_method": "日付の判定方法",
        "requested_url": "指定URL", "resolved_url": "共有URLの解決先", "collector": "収集方法",
        "service_verified": "収集サービスによる一覧照合", "manual_recovery_attempted": "画面操作による再開",
    }
    priority = ["place_name", "collected_at", "review_filter", "count", "scanned_text_review_count",
                "excluded_rating_only_count", "scanned_count", "displayed_total_end", "missing_count",
                "date_from", "date_to", "period_uncertain_count", "period_excluded_count",
                "scan_coverage_verified", "full_coverage_verified", "period_date_accuracy_verified",
                "saved_text_truncated_count", "incomplete", "stop_reason"]
    keys = [key for key in priority if key in metadata] + [key for key in metadata if key not in priority]
    entries = []
    for key in keys:
        value = metadata[key]
        if key == "review_filter" and value == "text_only":
            value = "本文ありの口コミのみ"
        elif isinstance(value, bool):
            value = ("要確認" if value else "なし") if key == "incomplete" else ("確認済み" if value else "未確認") if "verified" in key else ("はい" if value else "いいえ")
        elif value is None:
            value = "未確認"
        entries.append([labels.get(key, key), value])
    entries += [
        ["保存対象の説明", "口コミ本文のある投稿のみ。一覧の件数照合には評価のみも含めます。"],
        ["投稿日", "画面表記を保存。期間指定では相対表示を日付の範囲として推定し、期間内・要確認・期間外に分類します。正確な投稿日を保証しません。"],
        ["本文と返信", "画面に表示されたテキスト。Googleの翻訳や省略が含まれる場合があります。"],
        ["表示と確認用列", "口コミシートは投稿者・星評価・投稿日・本文・既存返信を表示します。非表示列のID・URL・日付推定は、必要なときに列を再表示して確認できます。"],
        ["長文の読み方", "行高の上限を超える本文・返信は「長文の続き」に分割して表示します。元シート・元セル・続き番号でたどれます。"],
        ["原本", "CSV・JSONに収集時のデータを保存しています。Excelの1セル上限は32,767文字。表示する長文は分割シートに全文を残します。制御文字はExcelから除き、原本に保持します。"],
    ]
    summary = write_table(book, "取得情報", ["項目", "内容"], entries, widths=[38, 88])
    summary.auto_filter.ref = None
    summary["B2"].font = Font(name="Arial", size=14, bold=True, color="243B53")
    summary.row_dimensions[2].height = max(36, summary.row_dimensions[2].height)
    book.move_sheet(summary, offset=-book.worksheets.index(summary))
    if OVERFLOW_SHEET in book.sheetnames:
        detail = book[OVERFLOW_SHEET]
        book.move_sheet(detail, offset=len(book.worksheets) - book.worksheets.index(detail) - 1)
    book.active = 0
    book.save(path)


def prepare_reviews(page, manual: bool):
    sort = page.get_by_role("button", name=re.compile(r"並べ替え|sort", re.I)).first
    if not manual:
        # Maps populates the place panel after DOMContentLoaded, especially in a
        # fresh Chrome profile. Do not fall back to stdin while it is still loading.
        try:
            page.get_by_role("main").first.wait_for(state="visible", timeout=45000)
        except Exception:
            pass
        # Even the overview can contain preview cards and a sort button.
        # Wait for the delayed review entry and select it before extracting.
        deadline = time.monotonic() + 30
        reloaded = False
        if "!9m1!1b1" in page.url and sort.is_visible() and page.locator(REVIEW_CARD_SELECTOR).count():
            return
        while time.monotonic() < deadline:
            for role in ("tab", "button"):
                target = page.get_by_role(role, name=re.compile(r"口コミ|クチコミ|レビュー|reviews?", re.I))
                for index in range(min(target.count(), 8)):
                    if time.monotonic() >= deadline:
                        break
                    try:
                        candidate = target.nth(index)
                        if not candidate.is_visible():
                            continue
                        label = (candidate.get_attribute("aria-label") or "") + " " + candidate.inner_text()
                        if re.search(r"書く|投稿|追加|write|add\s+(a\s+)?review|leave\s+(a\s+)?review", label, re.I):
                            continue
                        candidate.click(timeout=3000)
                        sort.wait_for(state="visible", timeout=8000)
                        page.locator(REVIEW_CARD_SELECTOR).first.wait_for(state="visible", timeout=8000)
                        return
                    except Exception:
                        # A Maps SPA transition can update the review URL and
                        # heading without loading its cards. Reload that view once.
                        if not reloaded and "!9m1!1b1" in page.url and sort.is_visible():
                            reloaded = True
                            try:
                                page.reload(wait_until="domcontentloaded", timeout=15000)
                                sort.wait_for(state="visible", timeout=8000)
                                page.locator(REVIEW_CARD_SELECTOR).first.wait_for(state="visible", timeout=8000)
                                return
                            except Exception:
                                pass
                        continue
            page.wait_for_timeout(500)
    body = page.locator("body").inner_text(timeout=3000)
    restricted = bool(re.search(r"Google\s*マップの表示が制限|Google\s*Maps[^\n]{0,80}(restricted|limited)", body, re.I))
    if restricted:
        print("Googleマップで口コミの表示が制限されています。専用ブラウザーでログインや表示内容を確認してください。", flush=True)
    print("専用ブラウザーで必要に応じてログインし、対象店舗の「口コミ」を開いてください。ログイン状態は次回も保持します。", flush=True)
    if not sys.stdin.isatty():
        raise RuntimeError("Googleマップで口コミの表示が制限されています。ターミナルで--manualを指定して確認してください。" if restricted
                           else "口コミ一覧を自動で開けませんでした。ターミナルで--manualを指定して再実行してください。")
    try:
        input("口コミが表示されたら、このターミナルでEnterを押してください: ")
    except EOFError as error:
        raise RuntimeError("手動操作にはターミナルが必要です。店舗URLを指定して再実行してください。") from error
    sort.wait_for(state="visible", timeout=15000)
    page.locator(REVIEW_CARD_SELECTOR).first.wait_for(state="visible", timeout=15000)


def expand_text(page, processed: set[str], deadline: float | None = None):
    cards = page.locator(REVIEW_CARD_SELECTOR)
    candidates = cards.evaluate_all("""cards => cards.map(card => ({
        id: card.getAttribute('data-review-id'),
        selector: '[data-review-id=' + CSS.escape(card.getAttribute('data-review-id') || '') + ']'
    }))""")
    for candidate in candidates:
        if deadline is not None and time.monotonic() >= deadline:
            break
        review_id = candidate["id"]
        if not review_id or review_id in processed:
            continue
        card = page.locator(REVIEW_CARD_SELECTOR + candidate["selector"])
        buttons = card.get_by_role("button", name=re.compile(r"^(もっと見る|全文を表示|More|See more|Read more)$", re.I))
        for button_index in range(buttons.count()):
            try:
                button = buttons.nth(button_index)
                if button.is_visible():
                    button.click(timeout=1200)
            except Exception:
                # Preserve partial text and record the remaining More button.
                continue
        # Cache only after extraction verifies that no collapsed text remains.


def open_full_reviews(page) -> bool:
    """Leave the five-card preview before scrolling the complete review list."""
    button = page.get_by_role("button", name=re.compile(
        r"クチコミをもっと見る|口コミをもっと見る|すべてのクチコミを表示|more reviews|see all reviews", re.I)).first
    if not button.is_visible():
        return False
    button.click(timeout=10000)
    page.get_by_role("button", name=re.compile(r"並べ替え|sort", re.I)).first.wait_for(state="visible", timeout=15000)
    page.locator(REVIEW_CARD_SELECTOR).first.wait_for(state="visible", timeout=15000)
    try:
        button.wait_for(state="hidden", timeout=5000)
    except Exception:
        # Maps sometimes changes the URL but keeps the preview DOM. Reload the
        # same place's review URL once, instead of scrolling the stale preview.
        page.reload(wait_until="domcontentloaded", timeout=45000)
        page.locator(REVIEW_CARD_SELECTOR).first.wait_for(state="visible", timeout=20000)
        try:
            button.wait_for(state="hidden", timeout=15000)
        except Exception as error:
            raise RuntimeError("全口コミへの切り替えが完了しません。--manualで専用Chromeの表示・ログインを確認してください。") from error
    return True


def reviews_restricted(page) -> bool:
    body = page.locator("body").inner_text(timeout=3000)
    return bool(re.search(r"Google\s*マップの表示が制限|Google\s*Maps[^\n]{0,80}(restricted|limited)", body, re.I))


def recover_restricted_reviews(page) -> bool:
    """Let a terminal user restore access without closing the owned browser."""
    if not sys.stdin.isatty():
        return False
    print("Googleマップの表示制限を検知しました。収集を一時停止し、専用ブラウザーを開いたまま待ちます。", flush=True)
    print("普段のChromeとはログイン状態が別です。この専用ブラウザーでログインし、同じ店舗の全口コミを開いてください。", flush=True)
    prepare_reviews(page, manual=True)
    if reviews_restricted(page):
        # Signing in in another tab does not refresh the existing Maps DOM.
        # Refresh once after the user finishes, without repeating the prompt.
        page.reload(wait_until="domcontentloaded", timeout=45000)
        page.locator(REVIEW_CARD_SELECTOR).first.wait_for(state="visible", timeout=15000)
    return True


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


def scroll_reviews(page, recover: bool = False) -> dict:
    state = review_scroll_state(page)
    if not state:
        raise RuntimeError("口コミ一覧のスクロール領域を特定できません。口コミタブを開いて再実行してください。")
    # Native wheel input triggers Maps' lazy loading. All currently loaded cards
    # are captured before this jump; expanding each review only once avoids resets.
    page.mouse.move(state["x"], state["y"])
    if recover:
        # Leaving and re-entering the loaded bottom re-triggers lazy loading.
        page.mouse.wheel(0, -state["height"])
        page.wait_for_timeout(500)
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
    parser = argparse.ArgumentParser(prog="google-maps-reviews", description="Googleマップの本文あり口コミだけをCSV・Excel・JSONに保存します。評価のみは除外。無引数で対話メニューを開きます。", epilog="準備: setup --browser chrome / 専用ブラウザーにログイン: login / 設定: settings show / CSV分析Skill導入: skill install（すべてgoogle-maps-reviewsに続けて指定）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("url", nargs="?", type=maps_url, help="店舗URL。省略時はブラウザーで店舗を選択")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--max", type=positive_int, default=100, help="本文ありの最大保存件数（既定:100）")
    scope.add_argument("--all", action="store_true", help="一覧全件を照合し、本文あり口コミを全件保存")
    scope.add_argument("--visible-only", action="store_true", help="スクロールせず現在読み込まれた本文あり口コミを保存")
    parser.add_argument("--from", dest="date_from", type=iso_date, help="期間の開始日 YYYY-MM-DD（当日を含む）")
    parser.add_argument("--to", dest="date_to", type=iso_date, help="期間の終了日 YYYY-MM-DD（当日を含む、省略時は取得日）")
    parser.add_argument("--manual", action="store_true", help="口コミの画面を自分で開いてから収集")
    parser.add_argument("--delay", type=positive_seconds, default=2.0, help="スクロール後の待機秒数（既定:2）")
    parser.add_argument("--timeout", type=positive_int, default=300, help="収集の制限秒数（既定:300、手動操作時間を除く）")
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "Desktop" / "GoogleMap口コミ")
    parser.add_argument("--browser", choices=("chrome", "chromium"), default="chrome")
    service = parser.add_mutually_exclusive_group()
    service.add_argument("--no-service", action="store_true", help="既存の収集サービスを使わずCLIの専用ブラウザーで収集")
    service.add_argument("--use-service", dest="no_service", action="store_false", help="互換用: 起動中の旧Web用収集サービスを使用")
    parser.set_defaults(no_service=False)
    parser.add_argument("--demo", action="store_true", help="実在の口コミではないサンプルで出力確認")
    parser.add_argument("--interactive", action="store_true", help="対話メニューを開く（ターミナル専用）")
    parser.add_argument("--use-settings", action="store_true", help="保存設定を使用。明示したオプションを優先")
    parser.add_argument("--config", type=Path, help="設定ファイルを指定（環境変数GOOGLE_MAPS_REVIEWS_CONFIGも使用可）")
    return parser


def main(argv=None) -> int:
    from .console import dispatch
    if sys.platform != "darwin":
        print("このツールはMac専用です。macOSで実行してください。", file=sys.stderr)
        return 1
    return dispatch(list(sys.argv[1:] if argv is None else argv), build_parser())


def collect_from_local_service(args, reviews: dict, metadata: dict) -> bool:
    # Preserve the collection environment used by earlier installations. A
    # fresh CLI installation works without this optional local service.
    if args.no_service or not args.url or not (args.all or args.date_from or args.date_to) or args.manual or args.visible_only or args.browser != "chrome" or args.delay != 2.0:
        return False
    endpoint = "http://127.0.0.1:38473"
    headers = {"Origin": "https://google-maps-reviews.vercel.app"}
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(Request(endpoint + "/health", headers=headers), timeout=1) as response:
            health = json.load(response)
        if health.get("ready") is not True or health.get("version") != "1.0.0":
            return False
    except (OSError, ValueError, AttributeError):
        return False
    metadata.update(collector="このMacの収集サービス", service_verified=False)
    last_progress = None
    try:
        if health.get("busy"):
            raise RuntimeError("このMacでは口コミを収集中です。完了後に再実行してください。")
        resolved = resolve_maps_url(args.url)
        metadata["resolved_url"] = resolved
        print("このMacの専用Chromeで収集しています。", flush=True)
        request = Request(endpoint + "/collect", data=json.dumps({"url": resolved, "timeout": args.timeout}).encode(),
                          headers=dict(headers, **{"Content-Type": "application/json"}))
        with opener.open(request, timeout=args.timeout + 120) as response:
            for line in response:
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
                ensure_same_place(resolved, data["sourceUrl"])
                if place_identity(resolved) and place_identity(data["sourceUrl"]) != place_identity(resolved):
                    raise ValueError("指定店舗と収集元の一致を確認できません。取得データは保存対象に追加しませんでした。")
                merge_reviews(reviews, data["reviews"], data["place"], data["sourceUrl"])
                metadata.update(place_name=data["place"], source_url=data["sourceUrl"],
                                displayed_total_end=data["displayedTotal"])
                if data["displayedTotal"] is not None:
                    metadata.setdefault("displayed_total_start", data["displayedTotal"])
                progress = (len(reviews), data["displayedTotal"])
                if progress != last_progress:
                    print(f"一覧読取: {progress[0]}件 / 画面の総件数: {progress[1]} / 本文あり: {sum(has_review_text(row) for row in reviews.values())}件", flush=True)
                    last_progress = progress
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
    period = bool(args.date_from or args.date_to)
    if period:
        if args.all or args.visible_only:
            raise ValueError("期間指定と--all・--visible-onlyは同時に指定できません。")
        select_period([], args.date_from, args.date_to, datetime.now().astimezone().date())
    limit = sys.maxsize if args.all or args.visible_only or period else args.max
    output_dir = args.output_dir.expanduser().resolve()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Check the chosen destination before opening Chrome or collecting data.
        with tempfile.TemporaryFile(dir=output_dir):
            pass
    except OSError as error:
        print(f"保存先を準備できません: {output_dir}\n{error}", file=sys.stderr)
        return 1
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    metadata = {"collected_at": now.isoformat(timespec="seconds"),
                "requested_url": args.url or "",
                "requested_max": "全件" if args.all else "読み込み済み全件" if args.visible_only else args.max,
                "review_filter": "text_only",
                "coverage": "画面から読み取れた口コミのみ。全件取得の保証はありません。"}
    print("保存対象は本文ありの口コミのみです。評価のみの投稿は一覧の件数照合に使い、保存から除外します。", flush=True)
    if period:
        metadata.update(date_from=args.date_from, date_to=args.date_to or now.date().isoformat(), requested_max="指定期間（一覧全件を確認して絞り込み）")
        print("画面の相対日付は推定で期間判定します。正確な投稿日での抽出とは異なり、境界・日付不明は確認用シートへ保存します。", flush=True)
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
            with sync_playwright() as pw, collection_browser(pw, args.browser) as context:
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(10000)
                    page.goto(args.url or "https://www.google.com/maps?hl=ja", wait_until="domcontentloaded", timeout=45000)
                    expected_url = page.url if args.url else ""
                    ensure_same_place(args.url or "", expected_url)
                    metadata.update(resolved_url=expected_url, collector="CLIの専用ブラウザー")
                    prepare_reviews(page, args.manual or not args.url)
                    metadata.update(source_url=page.url)
                    ensure_same_place(expected_url, page.url)
                    expected_url = page.url
                    started = time.monotonic()
                    stagnant = 0
                    expanded_ids = set()
                    final_expansion_passes = 0
                    last_progress = None
                    recovery_attempted = False
                    full_view_opened = False
                    no_progress_passes = 0
                    while True:
                        if blocked(page):
                            metadata["stop_reason"] = "確認画面のため停止"
                            break
                        expand_text(page, expanded_ids, deadline=started + args.timeout)
                        data = page.evaluate(extractor)
                        ensure_same_place(expected_url, data["source_url"])
                        for row in data["reviews"]:
                            if row.get("text_may_be_truncated"):
                                expanded_ids.discard(row["review_id"])
                            else:
                                expanded_ids.add(row["review_id"])
                        place = data["place_name"] or metadata.get("place_name") or "店舗名取得不可"
                        metadata.update(place_name=place, source_url=data["source_url"])
                        if data.get("displayed_total") is not None:
                            metadata.setdefault("displayed_total_start", data["displayed_total"])
                            metadata["displayed_total_end"] = data["displayed_total"]
                        added = merge_reviews(reviews, data["reviews"], place, data["source_url"])
                        no_progress_passes = 0 if added else no_progress_passes + 1
                        if data["reviews"] and not reviews:
                            raise RuntimeError("口コミは表示されていますが、投稿者または評価を読み取れません。ツールを更新してください。")
                        text_count = sum(has_review_text(row) for row in reviews.values())
                        progress = (len(reviews), metadata.get('displayed_total_end'), text_count)
                        if progress != last_progress:
                            print(f"一覧読取: {progress[0]}件 / 画面の総件数: {progress[1] if progress[1] is not None else '不明'} / 本文あり: {text_count}件", flush=True)
                            last_progress = progress
                        if args.visible_only:
                            metadata["stop_reason"] = "現在読み込まれた口コミのみ保存"
                            break
                        reached_limit = text_count >= limit
                        if reached_limit or full_coverage_verified(list(reviews.values()), metadata.get("displayed_total_end")):
                            selected_text = [row for row in reviews.values() if has_review_text(row)][:limit]
                            remaining = sum(bool(row.get("text_may_be_truncated")) for row in selected_text)
                            if remaining and final_expansion_passes < 3 and time.monotonic() - started < args.timeout:
                                final_expansion_passes += 1
                                status = "本文ありの指定件数に到達" if reached_limit else "一覧の件数照合済み"
                                print(f"{status}。省略が残る本文{remaining}件を再展開しています（{final_expansion_passes}/3）。", flush=True)
                                page.wait_for_timeout(300)
                                continue
                            metadata["stop_reason"] = ("本文ありの指定件数に到達" if reached_limit else
                                                       "画面の総件数と重複なしの読取件数が一致したため終了しました。")
                            break
                        if time.monotonic() - started >= args.timeout:
                            metadata["stop_reason"] = "制限時間に到達"
                            break
                        if not data["reviews"]:
                            raise RuntimeError("口コミカードを読み取れません。画面変更または未対応の表示形式です。")
                        # The same entry can reappear at the bottom of the full
                        # list. Clicking it repeatedly reloads the first page.
                        if not full_view_opened and open_full_reviews(page):
                            full_view_opened = True
                            no_progress_passes = 0
                            stagnant = 0
                            continue
                        # A notice alone does not prove loading is blocked.
                        # First attempt the normal transition and scrolling.
                        if no_progress_passes >= 3 and reviews_restricted(page):
                            if not recovery_attempted:
                                recovery_attempted = True
                                metadata["manual_recovery_attempted"] = True
                                paused = time.monotonic()
                                if recover_restricted_reviews(page):
                                    # Do not consume the collection timeout during login.
                                    started += time.monotonic() - paused
                                    ensure_same_place(expected_url, page.url)
                                    expanded_ids.clear()
                                    stagnant = 0
                                    no_progress_passes = 0
                                    continue
                            login = "google-maps-reviews login" + (f" --browser {args.browser}" if args.browser != "chrome" else "")
                            raise RuntimeError(f"Googleマップの表示制限が残っています。取得済み分を保存します。専用ブラウザーのログインは {login} で確認できます。ログインしてもGoogle側の制限が残る場合は収集できません。")
                        state = review_scroll_state(page)
                        stagnant = next_stagnant_count(stagnant, added, state)
                        if stagnant >= 8 and metadata.get("displayed_total_end") is None:
                            metadata["stop_reason"] = "画面の総件数が不明で追加読み込みがないため停止（全件取得は未確認）"
                            break
                        recover = stagnant > 0 and stagnant % 3 == 0
                        if recover:
                            print("追加読み込みを待ち、口コミ一覧を再スクロールしています。", flush=True)
                        scroll_reviews(page, recover=recover)
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
        except KeyboardInterrupt:
            metadata["stop_reason"] = "ユーザーが中断（取得済みデータを保存）"
        except Exception as error:
            metadata.update(stop_reason="エラーによる停止", error=str(error))
            print(f"収集中に停止しました: {error}", file=sys.stderr)
    scanned_rows = list(reviews.values())
    text_rows = [row for row in scanned_rows if has_review_text(row)]
    rows = text_rows[:limit]
    metadata.update(scanned_count=len(scanned_rows), scanned_text_review_count=len(text_rows),
                    excluded_rating_only_count=len(scanned_rows) - len(text_rows))
    if metadata.get("stop_reason", "").startswith("画面の総件数と"):
        metadata["stop_reason"] = metadata["stop_reason"].replace("保存件数", "読取件数")
    if period:
        rows, uncertain, excluded = partition_period(text_rows, args.date_from, args.date_to, now.date())
        dated_rows = rows + uncertain + excluded
        metadata.update(scanned_count=len(scanned_rows), period_uncertain_count=len(uncertain),
                        period_excluded_count=len(excluded), period_uncertain_reviews=uncertain,
                        period_excluded_reviews=excluded,
                        period_exact_date_count=sum(row["date_precision"] == "日付表示" for row in dated_rows),
                        period_estimated_date_count=sum("推定" in row["date_precision"] for row in dated_rows),
                        period_unknown_date_count=sum(not row["date_earliest"] for row in dated_rows),
                        date_filter_method="本文ありの画面日付を範囲として推定。範囲全体が指定期間内の行のみCSVに保存。Excel・JSONには本文ありを期間内・境界不明・期間外へ区分して保存。評価のみは除外。")
    metadata["count"] = len(rows)
    metadata["text_review_count"] = len(rows)
    metadata["rating_only_count"] = len(rows) - metadata["text_review_count"]
    if not args.demo:
        scan_verified = (full_coverage_verified(scanned_rows, metadata.get("displayed_total_end"))
                         and "error" not in metadata and metadata.get("service_verified", True) is True)
        metadata["scan_coverage_verified"] = scan_verified
        metadata["full_coverage_verified"] = scan_verified and not period and len(rows) == len(text_rows)
        metadata["truncated_count"] = sum(bool(row.get("text_may_be_truncated")) for row in rows)
        preserved = rows + metadata.get("period_uncertain_reviews", []) + metadata.get("period_excluded_reviews", [])
        metadata["saved_text_truncated_count"] = sum(bool(row.get("text_may_be_truncated")) for row in preserved)
        expected = metadata.get("displayed_total_end")
        metadata["missing_count"] = max(0, expected - len(scanned_rows)) if expected is not None else None
        if scan_verified:
            metadata["coverage"] = f"一覧{len(scanned_rows)}件の読取IDを画面総件数と照合。本文あり{len(text_rows)}件・評価のみ{metadata['excluded_rating_only_count']}件。本文ありのみ保存。"
            if args.all and metadata.get("stop_reason", "").startswith("口コミ一覧の末尾"):
                metadata["stop_reason"] = "口コミ一覧の末尾に到達し、画面の総件数との一致を確認"
        elif args.all or period or (not args.visible_only and len(rows) < limit):
            metadata["incomplete"] = True
            print(f"一覧の全件読取は未確認です。読取{len(scanned_rows)}件 / 画面{metadata.get('displayed_total_end', '不明')}件。" if period or args.all
                  else f"本文ありの指定件数は未達です。保存{len(rows)}件 / 指定{limit}件。", file=sys.stderr)
        if period:
            metadata["period_selection_verified"] = scan_verified and not metadata["period_uncertain_count"]
            metadata["period_date_accuracy_verified"] = (metadata["period_selection_verified"]
                                                         and metadata["period_exact_date_count"] == len(text_rows))
            metadata["incomplete"] = not metadata["period_date_accuracy_verified"]
            metadata["full_coverage_verified"] = False
        if metadata["saved_text_truncated_count"]:
            metadata["incomplete"] = True
    if not scanned_rows:
        print("口コミを取得できなかったため、口コミファイルは生成していません。", file=sys.stderr)
        if args.browser == "chromium":
            print("Chromium未導入の場合: google-maps-reviews setup --browser chromium", file=sys.stderr)
        return 1
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", metadata.get("place_name", "口コミ"))[:60].strip(" .") or "口コミ"
    stem = f"{'サンプル_' if args.demo else ''}{name}_口コミ_{stamp}"
    try:
        paths = export_reviews(rows, metadata, output_dir, stem)
    except Exception as error:
        print(f"ファイル保存に失敗しました: {error}", file=sys.stderr)
        return 1
    print(f"\n一覧読取: {metadata['scanned_count']}件 / 画面の総件数: {metadata.get('displayed_total_end') or '不明'}件。停止理由: {metadata['stop_reason']}")
    print(f"本文あり読取: {metadata['scanned_text_review_count']}件 / 評価のみ除外: {metadata['excluded_rating_only_count']}件")
    if period:
        estimated = metadata["period_estimated_date_count"] > 0
        print(f"期間内{'と推定' if estimated else ''}: {len(rows)}件（CSV） / 期間外{'と推定' if estimated else ''}: {metadata['period_excluded_count']}件 / 要確認: {metadata['period_uncertain_count']}件")
        print(f"Excel・JSONに本文あり{metadata['scanned_text_review_count']}件すべてを区分別に保存しました。")
    else:
        print(f"本文あり{len(rows)}件をCSV・Excel・JSONに保存しました。")
        if metadata.get("full_coverage_verified"):
            print("一覧の件数を照合し、本文ありの口コミを全件保存しました。")
    if period:
        print(f"期間: {metadata['date_from'] or '開始指定なし'}〜{metadata['date_to']} / 一覧読取: {metadata['scanned_count']}件 / 日付の要確認: {metadata['period_uncertain_count']}件（Excel別シート）")
        if not metadata.get("period_date_accuracy_verified", False):
            print(f"正確な投稿日による期間抽出は未確認です。相対表示: {metadata['period_estimated_date_count']}件 / 投稿日不明: {metadata['period_unknown_date_count']}件。", file=sys.stderr)
    if metadata.get("saved_text_truncated_count"):
        print(f"保存した本文に省略が残っています: {metadata['saved_text_truncated_count']}件（JSON・Excelの取得情報を確認してください）。", file=sys.stderr)
    if metadata.get("incomplete"):
        remaining = metadata.get("missing_count")
        if remaining:
            print(f"未取得: {remaining}件。", file=sys.stderr)
        elif remaining is None:
            print("画面の総件数を確認できませんでした。", file=sys.stderr)
        elif period and metadata.get("scan_coverage_verified"):
            print("一覧の件数は照合済みです。期間抽出の精度はExcelの「取得情報」で、要確認の行は「期間境界・日付不明」で確認してください。", file=sys.stderr)
        elif metadata.get("saved_text_truncated_count") and metadata.get("scan_coverage_verified"):
            print("一覧の件数は照合済みですが、本文の省略が残るため収集完了として扱いません。", file=sys.stderr)
        else:
            print("保存済みですが、全件取得の完了を確認できませんでした。", file=sys.stderr)
        if "error" not in metadata and args.url and not metadata["stop_reason"].startswith("ユーザーが中断") and not metadata.get("scan_coverage_verified"):
            retry = ["google-maps-reviews", args.url]
            if period:
                if args.date_from:
                    retry += ["--from", args.date_from]
                if args.date_to:
                    retry += ["--to", args.date_to]
            else:
                retry += ["--all"] if args.all else ["--max", str(args.max)]
            retry += ["--timeout", str(max(1200, args.timeout * 2))]
            if args.manual:
                retry.append("--manual")
            if args.no_service:
                retry.append("--no-service")
            if args.browser != "chrome":
                retry += ["--browser", args.browser]
            if args.delay != 2.0:
                retry += ["--delay", str(args.delay)]
            if output_dir != (Path.home() / "Desktop" / "GoogleMap口コミ").resolve():
                retry += ["--output-dir", str(output_dir)]
            print(f"待機時間を延ばして再実行: {shlex.join(retry)}", file=sys.stderr)
    for path in paths:
        print(path)
    return 2 if "error" in metadata or metadata.get("incomplete") else 0


if __name__ == "__main__":
    raise SystemExit(main())
