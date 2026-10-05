# Googleマップ口コミ収集ツール

Googleマップのブラウザー画面に読み込まれた口コミを収集し、デスクトップの `GoogleMap口コミ` フォルダーへCSV・Excel・JSONを保存するコマンドラインツールです。画面の表示要素を読み取り、本文の「もっと見る」を展開して自動スクロールします。

## インストール

Python 3.10以上、Google Chrome、pipxが必要です。リポジトリは非公開のため、アクセス権のあるGitHubアカウントで取得します。

```bash
gh auth login
gh repo clone atsuki-sakai/google-maps-reviews
cd google-maps-reviews
pipx install .
pipx ensurepath
```

必要ならターミナルを開き直し、次で確認します。

```bash
google-maps-reviews --version
google-maps-reviews --help
```

pipxがないMacでは `brew install pipx` で準備できます。pipxの代わりに `uv tool install .` も使えます。PyPIへの公開は行っていません。

## 全件取得

```bash
google-maps-reviews --all --manual --timeout 1200
```

1. 開いた専用Chromeで店舗を検索します。
2. 必要に応じてGoogleにログインします。
3. 店舗の「口コミ」を開き、「すべてのクチコミ」を選択します。
4. ターミナルに戻ってEnterを押すと、自動収集が始まります。
5. 完了するまでChromeを閉じずに待ちます。

未ログイン時に「Google マップの表示が制限されています」と表示され、口コミタブが出ない場合があります。ログインは専用Chrome上で行います。実行ごとに一時的なプロファイルを使うため、ログイン状態は次回に引き継ぎません。

店舗URLを指定する場合：

```bash
google-maps-reviews "https://maps.app.goo.gl/店舗の共有URL" --all --manual --timeout 1200
```

URLはGoogleマップの「共有」で取得したHTTPS URLを使います。URLを指定して `--manual` を省略すると、口コミ画面を自動で開こうとし、開けない場合は手動操作に切り替わります。

`--all` は件数上限を外します。画面の総件数と重複なし口コミIDの保存件数が一致した場合のみ、取得情報の「総件数と重複なし保存件数の一致」をTrueにします。総件数が不明または一致しない場合も取得分を保存しますが、全件取得未確認として終了コード2を返します。この照合は件数の確認で、本文の省略有無は別の項目で確認します。

## その他の実行例

```bash
# 最大100件
google-maps-reviews "https://www.google.com/maps/店舗のURL" --max 100

# 画面に読み込まれた分だけ保存
google-maps-reviews --manual --visible-only

# 保存先を変更
google-maps-reviews --all --manual --timeout 1200 --output-dir "$HOME/Desktop/口コミ出力"

# 架空の1件でファイル出力を確認
google-maps-reviews --demo
```

初期設定は最大100件、収集時間5分、スクロール後の待機2秒です。`--timeout` は秒単位で、ログインや手動操作の時間を除きます。`--delay` で待機時間を変更できます。`--all` と `--max`、`--all` と `--visible-only` は同時に指定できません。

途中で `Control+C` を押すと、それまでに取得した口コミを保存します。終了コードは0が正常終了、1が起動・保存失敗または取得0件、2が一部取得・全件取得未確認です。件数を指定した場合の0は指定範囲の成功を意味します。

## 保存される内容

- 店舗名、投稿者、星評価、投稿日（「1か月前」等の画面表記）
- 口コミ本文、店舗側の返信、口コミID
- 画面から取得できたURL、取得日時、省略表示の有無、カード全体の表示テキスト

Excelには「口コミ」と「取得情報」の2シートがあります。CSVはUTF-8 BOM付きです。JSONには加工前の文字列と取得情報を保存します。同じ口コミIDの重複をまとめ、本文のない星評価も保存します。ファイル名に店舗名と実行日時を含め、以前の結果を上書きしません。

Excelの「取得情報」で画面の総件数、保存件数、停止理由、本文の省略表示が残った件数を確認してください。本文や返信はGoogleによる翻訳を含む場合があります。投稿日から正確な日付を推定することはありません。

## 更新・削除

リポジトリのフォルダーで実行します。

```bash
git pull --ff-only
pipx reinstall google-maps-reviews
```

削除する場合：

```bash
pipx uninstall google-maps-reviews
```

## 開発・従来の起動方法

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --editable .
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v
```

従来の `./run.command` も使用できます。初回に専用の `.venv` にパッケージをインストールします。

Chromeがない場合は、開発用環境でChromiumを準備して実行できます。

```bash
.venv/bin/python -m playwright install chromium
.venv/bin/google-maps-reviews --browser chromium --all --manual --timeout 1200
```

GitHub ActionsではPython 3.10・3.12・3.14で配布用wheelをビルド・インストールし、抽出リソースの同梱、コマンド起動、サンプル出力、重複排除と総件数の照合をテストします。Googleへのログインや実店舗の収集はCIの対象外です。生成した口コミファイル、仮想環境、ブラウザープロファイルはGit管理の対象に含めません。

## 実店舗の確認状況

2026年10月5日、「いっかくじゅう」の実際の口コミ画面で全331件を収集し、CSV・Excel・JSONに保存しました。画面総件数331件、重複なし口コミID331件、ファイル331行が一致し、省略表示の残った本文は0件でした。星評価別も5つ星217件・4つ星54件・3つ星35件・2つ星8件・1つ星17件で一致しました。

この確認にはログイン済みのCodex内ブラウザーと同梱の抽出・保存処理を使用しています。専用Chromeでのコマンド通し実行による全件収集は、まだ未確認です。Google側の表示変更、ログイン、確認画面、通信状況で停止する場合があります。店舗ごとに取得情報で件数を確認してください。

実装で参照した公式ドキュメント：[Pythonのパッケージ設定](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)、[GitHub ActionsでのPythonテスト](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)、[Playwrightの要素操作](https://playwright.dev/python/docs/api/class-locator)。
