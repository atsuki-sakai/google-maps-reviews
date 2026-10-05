"""CLI orchestration for the installed Codex Skill and its local artifacts."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from . import reporting


def install_skill(destination: Path | None = None) -> Path:
    root = destination or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills"
    root = root.expanduser().resolve()
    target = root / "google-review-report"
    marker = target / ".google-maps-reviews-skill"
    if target.exists() and (not marker.is_file() or marker.read_text(encoding="utf-8") != "google-maps-reviews\n"):
        raise ValueError(f"別のSkillを上書きしません。--pathで別の導入先を指定してください: {target}")
    if target.is_symlink():
        raise ValueError(f"Skillのシンボリックリンクを上書きしません: {target}")
    root.mkdir(parents=True, exist_ok=True)
    # Stage all package resources before replacing our own installed Skill.
    with tempfile.TemporaryDirectory(prefix=".review-skill-", dir=root) as temporary:
        staged = Path(temporary) / "google-review-report"
        shutil.copytree(reporting.SKILL_DIR, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (staged / ".google-maps-reviews-skill").write_text("google-maps-reviews\n", encoding="utf-8")
        backup = Path(temporary) / "previous"
        if target.exists():
            target.rename(backup)
        try:
            staged.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise
    return target


def skill_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="google-maps-reviews skill", description="口コミ分析SkillをCodexに導入します。")
    parser.add_argument("action", choices=("install", "path"), nargs="?", default="install")
    parser.add_argument("--path", type=Path, help="Skillを置く親フォルダー（既定: ~/.codex/skills）")
    args = parser.parse_args(argv)
    if args.action == "path":
        print(reporting.SKILL_DIR)
    else:
        target = install_skill(args.path)
        print(f"Skillを導入しました: {target}\nCodexで $google-review-report 口コミ.csvのパス と指定してください。新しく導入したSkillは、新しい会話から使えます。")
    return 0


def new_output(path: Path | None = None) -> Path:
    if path:
        output = path.expanduser().resolve()
        if output.exists() and any(output.iterdir()):
            raise ValueError("保存先に既存ファイルがあります。別のフォルダーを指定するか、Skillに既存の分析フォルダーを渡して続けてください。")
        output.mkdir(parents=True, exist_ok=True)
        return output
    parent = Path.home() / "Desktop" / "GoogleMap口コミレポート"
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return Path(tempfile.mkdtemp(prefix=f"口コミ分析_{stamp}_", dir=parent))


def prepare_input(args) -> Path:
    source = args.input.expanduser().resolve()
    if source.suffix.lower() != ".csv":
        raise ValueError("口コミCSVを--inputで指定してください。URLからの収集は収集CLIで行ってください。")
    reporting.source_data(source)
    if args.context:
        args.context.expanduser().read_text(encoding="utf-8")
    output = new_output(args.output_dir)
    result = reporting.prepare(source, output, context=args.context.expanduser() if args.context else None,
                               batch_size=args.batch_size, reply_drafts=args.reply_drafts)
    manifest = reporting.read_json(result / "manifest.json")
    print(f"CSV分析の準備: {manifest['place_name']} / 口コミ{manifest['coverage']['count']}件、本文{manifest['coverage']['text_count']}件\n保存先: {result}")
    print("指定されたCSVの全行を分析します。Googleマップの総件数・全件取得はCSV単体では確認できません。")
    return result


def report_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="google-maps-reviews report", description="CSV分析Skillの補助コマンド。ブラウザー収集やAIの自動起動は行いません。")
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare", help="指定CSVから分析用ファイルを準備")
    prepare.add_argument("--input", type=Path, required=True, help="口コミCSV（UTF-8）")
    prepare.add_argument("--output-dir", type=Path)
    prepare.add_argument("--context", type=Path, help="確認済みの事業情報Markdown")
    prepare.add_argument("--batch-size", type=int, choices=range(1, 51), default=20, metavar="1〜50")
    replies = prepare.add_mutually_exclusive_group()
    replies.add_argument("--with-replies", dest="reply_drafts", action="store_true")
    replies.add_argument("--no-replies", dest="reply_drafts", action="store_false")
    prepare.set_defaults(reply_drafts=False)
    for action in ("validate", "stats", "render"):
        command = actions.add_parser(action)
        command.add_argument("workspace", type=Path)
        if action == "render":
            command.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "prepare":
        prepare_input(args)
        return 0
    output = args.workspace.expanduser().resolve()
    if args.action == "validate":
        manifest, keys, rows = reporting.load_annotations(output)
        reporting.load_synthesis(output, manifest, keys)
        print(f"検証済み: {len(rows)}件 / 本文{manifest['coverage']['text_count']}件。引用と口コミIDを照合しました。")
    elif args.action == "stats":
        manifest, _, rows = reporting.load_annotations(output)
        reporting.write_json(output / "statistics.json", reporting.statistics(manifest, rows))
        print(output / "statistics.json")
    else:
        path = reporting.render(output)
        print(f"レポートを生成しました: {path}\nExcel: {output / '口コミ分析.xlsx'}")
        if not args.no_open:
            subprocess.run(["open", str(path)], check=False)
    return 0
