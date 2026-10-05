# 開発・貢献

Mac専用のPython CLIです。IssueやPull Requestを歓迎します。

## 開発環境

macOS、Python 3.10以上、Google Chromeを準備します。

```bash
git clone https://github.com/atsuki-sakai/google-maps-reviews.git
cd google-maps-reviews
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
google-maps-reviews setup --browser chrome
```

## 確認

```bash
python -m unittest discover -s tests -v
google-maps-reviews --demo --output-dir /tmp/google-maps-reviews-demo
git diff --check
```

テストの口コミは架空のデータです。実店舗で確認した場合は、画面の総件数、重複なし口コミID数、保存行数、停止理由、本文の省略件数をそれぞれ報告してください。単体テストの成功を実店舗の全件取得として扱わないでください。

単体テストは実際の専用Chromeを起動しません。CLIのテストにはブラウザー起動を拒否する既定のガードがあり、ブラウザーを検証するテストだけ個別にモックします。プロファイル・ロックの検証には一時フォルダーを使います。終了シグナルの検証で起動する子プロセスも、架空のブラウザーを代わりにする短時間のPythonプロセスです。実ページの確認はテストスイートと分けて実行し、終了後に起動したプロセスが残っていないことを確認してください。

## 構成

- `src/google_maps_reviews/cli.py`: ブラウザー操作、重複排除、件数照合、ファイル出力
- `src/google_maps_reviews/console.py`: 対話メニュー、設定、ブラウザーのセットアップ
- `src/google_maps_reviews/browser.py`: 専用Chromeの起動、同時実行の防止、終了処理
- `src/google_maps_reviews/extract_reviews.js`: 表示された口コミカードの抽出
- `src/google_maps_reviews/dates.py`: 画面日付の範囲推定、期間内・境界・不明の判定
- `src/google_maps_reviews/report_cli.py`: Skill導入、CSVの準備・検証・描画の補助コマンド
- `src/google_maps_reviews/reporting.py`: 分類・引用・IDの検証、統計、Excel、HTML生成
- `src/google_maps_reviews/report_assets/`: 外部通信のないHTMLテンプレート・スタイル・操作
- `src/google_maps_reviews/skills/google-review-report/`: Skill本文、分析契約、方法の一次資料
- `install-cli.py`: GitHub認証不要のMac用インストーラー
- `tests/`: インストーラー、CLI、出力の回帰テスト
- `web/`: ツールの説明ページと旧版のローカル収集サービスの互換コード。CLIの導入・通常利用には不要

説明ページを編集するときだけNode.js 22で `cd web && npm ci` を実行し、`npm run lint`、`npm test`、`npm run build` を確認してください。公開された画面から口コミを収集する機能はありません。GitHub Actionsは使用しません。

## 不具合報告

分析を変更した場合、引用の一致、全行のID対応、評価のみを含む統計の母数、星と本文の独立、部分取得の表示、HTML/Excelの文字列処理を確認してください。架空データのレンダリングテストと実データの意味の分析は区別します。実店舗の口コミ、投稿者情報、分析ログ、レポートはリポジトリに追加しません。

macOS・Python・Chrome・ツールのバージョン、実行したオプション、表示された件数と停止理由を添えてください。URLは公開店舗のURLだけを記載します。口コミの本文、投稿者情報、Cookie、ブラウザープロファイル、認証情報を添付しないでください。

変更はMITライセンスで提供してください。
