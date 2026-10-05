#!/usr/bin/env python3
"""Install the private-repository CLI into a user-owned virtual environment."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path
from urllib.parse import quote

REPOSITORY = "atsuki-sakai/google-maps-reviews"


def launcher_text(python_command: Path, settings: Path) -> str:
    return ("#!/bin/sh\n# Managed by google-maps-reviews installer\n"
            f"export GOOGLE_MAPS_REVIEWS_CONFIG={shlex.quote(str(settings))}\n"
            f"exec {shlex.quote(str(python_command))} \"$@\"\n")


def check_destination(prefix: Path):
    base = prefix / "share" / "google-maps-reviews"
    environment = base / "venv"
    command = prefix / "bin" / "google-maps-reviews"
    executable = environment / ("Scripts/google-maps-reviews.exe" if os.name == "nt" else "bin/google-maps-reviews")
    marker = base / "installation.json"
    settings = base / "settings.json"
    expected = launcher_text(executable, settings)
    owned_command = not command.exists()
    if command.is_file() and not command.is_symlink():
        try:
            owned_command = command.read_text(encoding="utf-8") == expected
        except (OSError, UnicodeError):
            owned_command = False
    if command.is_symlink() or not owned_command:
        raise RuntimeError(f"既存の別コマンドを上書きしません。--prefixで別の導入先を指定してください: {command}")
    identity = {"repository": REPOSITORY, "venv": str(environment), "command": str(command)}
    if marker.exists():
        try:
            if json.loads(marker.read_text(encoding="utf-8")) != identity:
                raise ValueError
        except (ValueError, OSError):
            raise RuntimeError(f"導入先の所有情報を確認できません。--prefixで別の導入先を指定してください: {base}") from None
    elif environment.exists():
        raise RuntimeError(f"既存の仮想環境を上書きしません。--prefixで別の導入先を指定してください: {environment}")
    return base, environment, command, executable, marker, settings, expected, identity


def fetch_source(ref: str, folder: Path) -> Path:
    archive_path = folder / "source.zip"
    with archive_path.open("wb") as stream:
        subprocess.run(["gh", "api", f"repos/{REPOSITORY}/zipball/{quote(ref, safe='')}"], stdout=stream, check=True)
    unpacked = folder / "source"
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (unpacked / member.filename).resolve()
            if not target.is_relative_to(unpacked.resolve()):
                raise RuntimeError("取得アーカイブのパスを確認できませんでした。")
        archive.extractall(unpacked)
    roots = [path for path in unpacked.iterdir() if path.is_dir() and (path / "pyproject.toml").is_file()]
    if len(roots) != 1:
        raise RuntimeError("取得アーカイブにパッケージが見つかりませんでした。")
    return roots[0]


def install_from_source(source: Path, destination, browser: str):
    base, environment, command, executable, marker, settings, expected, identity = destination
    if not (source / "pyproject.toml").is_file() or not (source / "src/google_maps_reviews/cli.py").is_file():
        raise RuntimeError("--sourceにはgoogle-maps-reviewsのリポジトリフォルダーを指定してください。")
    base.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", str(source)], check=True)
    subprocess.run([str(executable), "setup", "--browser", browser, "--config", str(settings)], check=True)
    command.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=command.parent, prefix=".google-maps-reviews-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(expected)
    try:
        temporary.chmod(0o755)
        # Recheck after installation so a command created meanwhile is preserved.
        check_destination(command.parent.parent)
        temporary.replace(command)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"\n導入が完了しました。起動: {command}")
    print(f"設定: {settings}\n仮想環境: {environment}")
    print(f"コマンド名で使う場合: export PATH={shlex.quote(str(command.parent))}:\"$PATH\"")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="利用者領域にCLIとブラウザーを準備します。sudoや認証トークンのコピーは使いません。")
    parser.add_argument("--prefix", type=Path, default=Path(os.environ.get("GOOGLE_MAPS_REVIEWS_PREFIX", "~/.local")), help="導入先（既定:~/.local、環境変数GOOGLE_MAPS_REVIEWS_PREFIXも使用可）")
    parser.add_argument("--source", type=Path, help="ローカルリポジトリを使用。省略時は認証済みghでprivateリポジトリのアーカイブを取得")
    parser.add_argument("--ref", default="main", help="取得するブランチまたはタグ（既定:main）")
    parser.add_argument("--browser", choices=("chrome", "chromium"), default="chrome", help="既存Chrome確認またはChromiumダウンロード（既定:chrome）")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error("Python 3.10以降が必要です。")
    if os.name == "nt":
        parser.error("このセットアップスクリプトはmacOS/Linux用です。Windowsではpipxなどでパッケージを導入してください。")
    try:
        destination = check_destination(args.prefix.expanduser().resolve())
        if args.source:
            install_from_source(args.source.expanduser().resolve(), destination, args.browser)
        else:
            if not shutil.which("gh"):
                raise RuntimeError("GitHub CLI (gh)が必要です。gh auth loginでアクセス権のあるアカウントを認証するか--sourceを指定してください。")
            with tempfile.TemporaryDirectory(prefix="google-maps-reviews-source-") as folder:
                source = fetch_source(args.ref, Path(folder))
                install_from_source(source, destination, args.browser)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(f"導入できませんでした: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
