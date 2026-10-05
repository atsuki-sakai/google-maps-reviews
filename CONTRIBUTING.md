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

## 構成

- `src/google_maps_reviews/cli.py`: ブラウザー操作、重複排除、件数照合、ファイル出力
- `src/google_maps_reviews/console.py`: 対話メニュー、設定、ブラウザーのセットアップ
- `src/google_maps_reviews/browser.py`: 専用Chromeの起動、同時実行の防止、終了処理
- `src/google_maps_reviews/extract_reviews.js`: 表示された口コミカードの抽出
- `install-cli.py`: GitHub認証不要のMac用インストーラー
- `tests/`: インストーラー、CLI、出力の回帰テスト
- `web/`: ツールの説明ページと旧版のローカル収集サービスの互換コード。CLIの導入・通常利用には不要

説明ページを編集するときだけNode.js 22で `cd web && npm ci` を実行し、`npm run lint`、`npm test`、`npm run build` を確認してください。公開された画面から口コミを収集する機能はありません。GitHub Actionsは使用しません。

## 不具合報告

macOS・Python・Chrome・ツールのバージョン、実行したオプション、表示された件数と停止理由を添えてください。URLは公開店舗のURLだけを記載します。口コミの本文、投稿者情報、Cookie、ブラウザープロファイル、認証情報を添付しないでください。

変更はMITライセンスで提供してください。
