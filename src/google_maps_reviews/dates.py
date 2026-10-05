"""Conservative date ranges for the dates visibly shown on review cards."""
from __future__ import annotations

import argparse
import calendar
import re
from datetime import date, timedelta


def iso_date(value: str) -> str:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日付はYYYY-MM-DD形式で指定してください。") from error
    return value


def shift_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def date_bounds(text: str, anchor: date) -> tuple[date | None, date | None, str]:
    text = text.strip().lower()
    if re.search(r"編集|edited|サンプル", text):
        return None, None, "投稿日不明（編集日など）"
    exact = re.fullmatch(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", text)
    if exact:
        try:
            day = date(*map(int, exact.groups()))
            return day, day, "日付表示"
        except ValueError:
            return None, None, "日付不明"
    if text in ("今日", "today", "just now", "たった今"):
        return anchor - timedelta(days=1), anchor, "相対表示からの推定範囲"
    if text in ("昨日", "yesterday"):
        return anchor - timedelta(days=2), anchor, "相対表示からの推定範囲"
    match = re.fullmatch(r"(\d+)\s*(分|時間|日|週間?|[かヶケ]月|年)前", text)
    english = re.fullmatch(r"(\d+|a|an)\s+(minute|hour|day|week|month|year)s?\s+ago", text)
    if match:
        number, unit = int(match[1]), match[2]
        unit = {"分": "minute", "時間": "hour", "日": "day", "週": "week", "週間": "week",
                "か月": "month", "ヶ月": "month", "ケ月": "month", "年": "year"}[unit]
    elif english:
        number, unit = (1 if english[1] in ("a", "an") else int(english[1])), english[2]
    else:
        return None, None, "日付不明"
    # Google does not show a precise timestamp or rounding rule here. Keep a
    # range around the label; never turn "one month ago" into an exact date.
    try:
        if unit in ("month", "year"):
            step = 12 if unit == "year" else 1
            lower = shift_months(anchor, -(number + 1) * step) - timedelta(days=1)
            upper = shift_months(anchor, -max(0, number - 1) * step) + timedelta(days=1)
        else:
            step = {"minute": 0, "hour": 0, "day": 1, "week": 7}[unit]
            lower = anchor - timedelta(days=(number + 1) * step + 1)
            upper = anchor - timedelta(days=max(0, number - 1) * step) + timedelta(days=1)
        return lower, min(anchor, upper), "相対表示からの推定範囲"
    except (ValueError, OverflowError):
        return None, None, "日付不明"


def select_period(rows: list[dict], start: str | None, end: str | None, anchor: date):
    lower_filter = date.fromisoformat(start) if start else date.min
    upper_filter = date.fromisoformat(end) if end else anchor
    if lower_filter > upper_filter:
        raise ValueError("開始日は終了日以前を指定してください。")
    selected, uncertain = [], []
    excluded = 0
    for original in rows:
        row = dict(original)
        lower, upper, precision = date_bounds(row.get("date_text", ""), anchor)
        row.update(date_earliest=lower.isoformat() if lower else "",
                   date_latest=upper.isoformat() if upper else "", date_precision=precision)
        if lower is None or upper is None:
            row["period_match"] = "日付不明"
            uncertain.append(row)
        elif upper < lower_filter or lower > upper_filter:
            excluded += 1
        elif lower >= lower_filter and upper <= upper_filter:
            row["period_match"] = "期間内（日付範囲による判定）"
            selected.append(row)
        else:
            row["period_match"] = "期間境界・要確認"
            uncertain.append(row)
    return selected, uncertain, excluded
