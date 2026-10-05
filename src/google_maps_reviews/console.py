"""Interactive terminal flow and reusable collection preferences."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import cli


def config_path(value: Path | None = None) -> Path:
    return (value or Path(os.environ.get("GOOGLE_MAPS_REVIEWS_CONFIG", "~/.config/google-maps-reviews/settings.json"))).expanduser()


def default_settings() -> dict:
    return {"url": "", "scope": "max", "max": 100, "timeout": 300, "delay": 2.0,
            "output_dir": str(Path.home() / "Desktop" / "GoogleMap口コミ"), "browser": "chrome", "manual": False}


def validate_settings(settings: dict) -> dict:
    result = default_settings()
    if not isinstance(settings, dict) or set(settings) - set(result):
        raise ValueError("設定ファイルの項目を確認してください。")
    result.update(settings)
    if not isinstance(result["url"], str) or not isinstance(result["output_dir"], str) or not result["output_dir"].strip():
        raise ValueError("URLと保存先の設定を確認してください。")
    if result["url"]:
        cli.maps_url(result["url"])
    if result["scope"] not in ("all", "max", "visible") or result["browser"] not in ("chrome", "chromium") or type(result["manual"]) is not bool:
        raise ValueError("収集範囲とブラウザーの設定を確認してください。")
    for key in ("max", "timeout"):
        if type(result[key]) is not int:
            raise ValueError("件数と制限時間には整数を指定してください。")
        result[key] = cli.positive_int(str(result[key]))
    if isinstance(result["delay"], bool) or not isinstance(result["delay"], (int, float)):
        raise ValueError("待機時間には数値を指定してください。")
    result["delay"] = cli.positive_seconds(str(result["delay"]))
    return result


def load_settings(path: Path) -> dict:
    if not path.exists():
        return default_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError
        return validate_settings(data["settings"])
    except (OSError, ValueError, KeyError, TypeError, argparse.ArgumentTypeError) as error:
        raise ValueError(f"設定ファイルを読めません。settings resetで初期化するか--configで別のファイルを指定してください: {path}") from error


def save_settings(path: Path, settings: dict):
    data = {"version": 1, "settings": validate_settings(settings)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".settings-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def prompt(label: str, default, validator=lambda value: value):
    while True:
        value = input(f"{label} [{default}]: ").strip()
        try:
            return validator(value or str(default))
        except (ValueError, argparse.ArgumentTypeError) as error:
            print(f"入力を確認してください: {error}")


def choose(label: str, choices: dict[str, tuple[str, object]], current):
    print(label)
    for key, (title, _value) in choices.items():
        print(f"  {key}. {title}")
    default = next(key for key, (_title, value) in choices.items() if value == current)
    def selected(value):
        if value not in choices:
            raise ValueError("表示された番号を選んでください。")
        return choices[value][1]
    return prompt("番号", default, selected)


def edit_settings(current: dict) -> dict:
    settings = dict(current)
    print("Enterで現在の設定を使います。店舗URLの「-」はブラウザーで店舗を選ぶ指定です。")
    settings["url"] = prompt("店舗URL（未指定ならブラウザーで選択）", settings["url"],
                             lambda value: "" if value in ("", "-") else cli.maps_url(value))
    settings["scope"] = choose("収集範囲", {"1": ("全件を目指す（取得の保証はありません）", "all"),
                                        "2": ("最大件数を指定", "max"), "3": ("現在読み込まれた口コミのみ", "visible")}, settings["scope"])
    if settings["scope"] != "all":
        settings["max"] = prompt("最大保存件数", settings["max"], cli.positive_int)
    settings["timeout"] = prompt("収集の制限時間（秒、手動操作時間を除く）", settings["timeout"], cli.positive_int)
    settings["delay"] = prompt("スクロール後の待機時間（0.5〜60秒）", settings["delay"], cli.positive_seconds)
    settings["output_dir"] = prompt("保存先", settings["output_dir"], lambda value: str(Path(value).expanduser()))
    settings["browser"] = choose("ブラウザー", {"1": ("インストール済みのGoogle Chrome", "chrome"),
                                            "2": ("このツールで準備したChromium", "chromium")}, settings["browser"])
    settings["manual"] = choose("口コミ一覧の開き方", {"1": ("自動で開く（必要ならターミナルで手動操作）", False),
                                             "2": ("自分で口コミ一覧を開いてから収集", True)}, settings["manual"])
    return validate_settings(settings)


def apply_settings(args, settings: dict, argv: list[str]):
    destinations = ("url", "max", "timeout", "delay", "output_dir", "browser", "manual", "all", "visible_only")
    specified_parser = cli.build_parser()
    specified_parser.set_defaults(**dict.fromkeys(destinations))
    # Reuse argparse's option resolution so accepted abbreviations remain explicit.
    specified = vars(specified_parser.parse_args(argv))
    explicit = {key for key in destinations if specified[key] is not None}
    if args.url is None:
        args.url = settings["url"] or None
    for key in ("max", "timeout", "delay", "output_dir", "browser", "manual"):
        if key not in explicit:
            setattr(args, key, Path(settings[key]) if key == "output_dir" else settings[key])
    if not explicit & {"all", "max", "visible_only"}:
        args.all = settings["scope"] == "all"
        args.visible_only = settings["scope"] == "visible"
    return args


def setup_browser(browser: str, path: Path) -> int:
    if not all(importlib.util.find_spec(package) for package in ("playwright", "openpyxl")):
        print("依存パッケージが不足しています。配布用セットアップを再実行してください。", file=sys.stderr)
        return 1
    if browser == "chromium":
        result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
        if result.returncode:
            print("Chromiumの準備に失敗しました。ネットワーク接続を確認してsetupを再実行してください。", file=sys.stderr)
            return 1
    else:
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        for folder in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if folder:
                candidates.append(Path(folder) / "Google/Chrome/Application/chrome.exe")
        if not any(candidate.is_file() for candidate in candidates) and not any(shutil.which(command) for command in ("google-chrome", "google-chrome-stable")):
            print("Google Chromeが見つかりません。Chromeを導入するか、google-maps-reviews setup --browser chromiumを実行してください。", file=sys.stderr)
            return 1
    settings = load_settings(path)
    settings["browser"] = browser
    save_settings(path, settings)
    print(f"準備が完了しました。ブラウザー: {browser}\n設定: {path}\n起動: google-maps-reviews")
    return 0


def interactive_menu(args, path: Path, argv: list[str]) -> int:
    current = load_settings(path)
    apply_settings(args, current, argv)
    current.update(url=args.url or "", max=args.max, timeout=args.timeout, delay=args.delay,
                   output_dir=str(args.output_dir), browser=args.browser, manual=args.manual,
                   scope="all" if args.all else "visible" if args.visible_only else "max")
    last_code = 0
    while True:
        action = choose("\nGoogleマップ口コミ収集", {"1": ("口コミを収集", "collect"), "2": ("設定を変更して保存", "settings"),
                                             "3": ("ブラウザーをセットアップ", "setup"), "4": ("終了", "exit")}, "collect")
        if action == "exit":
            return last_code
        if action == "setup":
            browser = choose("準備するブラウザー", {"1": ("既存Chromeを確認（ダウンロードなし）", "chrome"),
                                                   "2": ("Chromiumを利用者領域にダウンロード", "chromium")}, current["browser"])
            last_code = setup_browser(browser, path)
            if not last_code:
                current = load_settings(path)
            continue
        current = edit_settings(current)
        save_settings(path, current)
        print(f"設定を保存しました: {path}")
        if action == "collect":
            collection = cli.build_parser().parse_args(["--demo"] if args.demo else [])
            apply_settings(collection, current, [])
            last_code = cli.run_collection(collection)


def dispatch(argv: list[str], parser) -> int:
    try:
        if argv and argv[0] in ("setup", "settings"):
            command = argv[0]
            subparser = argparse.ArgumentParser(prog=f"google-maps-reviews {command}")
            subparser.add_argument("--config", type=Path, help="設定ファイル")
            if command == "setup":
                subparser.add_argument("--browser", choices=("chrome", "chromium"), default="chromium", help="Chrome確認またはChromiumダウンロード（既定:chromium）")
                args = subparser.parse_args(argv[1:])
                return setup_browser(args.browser, config_path(args.config))
            subparser.add_argument("action", nargs="?", choices=("show", "edit", "reset"), default="show")
            args = subparser.parse_args(argv[1:])
            path = config_path(args.config)
            if args.action == "reset":
                save_settings(path, default_settings())
                print(f"設定を初期化しました: {path}")
            elif args.action == "show":
                print(f"設定ファイル: {path}\n" + json.dumps(load_settings(path), ensure_ascii=False, indent=2))
            else:
                if not sys.stdin.isatty():
                    subparser.error("設定変更にはターミナルが必要です。settings showで現在の設定を確認できます。")
                save_settings(path, edit_settings(load_settings(path)))
                print(f"設定を保存しました: {path}")
            return 0
        args = parser.parse_args(argv)
        path = config_path(args.config)
        if args.all and args.visible_only:
            parser.error("--allと--visible-onlyは同時に指定できません。")
        if args.interactive or not argv:
            if not sys.stdin.isatty():
                if args.interactive:
                    parser.error("--interactiveにはターミナルが必要です。URLとオプションを直接指定してください。")
                parser.print_help()
                return 0
            return interactive_menu(args, path, argv)
        if args.use_settings:
            apply_settings(args, load_settings(path), argv)
        if args.all and args.visible_only:
            parser.error("--allと--visible-onlyは同時に指定できません。")
        if not args.demo and not sys.stdin.isatty() and (args.manual or not args.url):
            parser.error("手動操作にはターミナルが必要です。非対話実行では店舗URLを指定し--manualを外してください。")
        return cli.run_collection(args)
    except EOFError:
        print("\n終了しました。")
        return 0
    except KeyboardInterrupt:
        print("\n終了しました。")
        return 130
    except (OSError, ValueError, argparse.ArgumentTypeError) as error:
        print(f"実行できませんでした: {error}", file=sys.stderr)
        return 1
