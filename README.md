# Googleマップ口コミ収集ツール

Googleマップのブラウザー画面に読み込まれた口コミを収集し、デスクトップの `GoogleMap口コミ` フォルダーへCSV・Excel・JSONを保存するコマンドラインツールです。画面の表示要素を読み取り、本文の「もっと見る」を展開して自動スクロールします。

## インストール

### 1コマンドでセットアップ

Python 3.10以上とGitHub CLI（`gh`）が必要です。このリポジトリは非公開なので、アクセス権のあるGitHubアカウントで `gh auth login` を済ませてください。Google Chromeを使う場合は、Chromeもインストールしておきます。

```bash
bash -o pipefail -c 'gh api repos/atsuki-sakai/google-maps-reviews/contents/install-cli.py -H "Accept: application/vnd.github.raw+json" | python3 - --browser chrome'
```

ソースの取得、専用のPython環境の作成、依存パッケージのインストール、Chromeの確認を行います。管理者権限は使いません。Chromeの代わりにChromiumを準備する場合は、末尾を `--browser chromium` にします。

```bash
google-maps-reviews
```

コマンドが見つからない場合は `~/.local/bin/google-maps-reviews` で起動できます。今のターミナルにPATHを追加するには `export PATH="$HOME/.local/bin:$PATH"` を実行します。利用者のシェル設定ファイルは自動で変更しません。

既定のインストール先は `~/.local` です。専用環境は `share/google-maps-reviews/venv`、コマンドは `bin/google-maps-reviews`、保存設定は `share/google-maps-reviews/settings.json` に置きます。既存の別ツールやpipx版コマンドを上書きしません。pipx版の更新は下の「更新・削除」を使ってください。

取得済みのリポジトリからセットアップする場合：

```bash
python3 install-cli.py --source . --browser chrome
# インストール先を変更する場合
python3 install-cli.py --source . --browser chrome --prefix "$HOME/Tools/review-port"
```

### pipxによるインストール

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

## 対話メニュー

ターミナルで `google-maps-reviews` を実行すると、番号で選べるメニューが開きます。

```text
Googleマップ口コミ収集
  1. 口コミを収集
  2. 設定を変更して保存
  3. ブラウザーをセットアップ
  4. 終了
```

収集時に店舗URL、全件または件数上限、手動操作、表示分のみの収集、スクロール後の待機秒数、制限時間、保存先、ChromeまたはChromiumを選べます。Enterで表示された既定値を使います。設定を保存すると、次回の対話でも同じ値を使えます。`Control+C` や入力終了で対話を終了できます。

```bash
# メニューを明示して開く
google-maps-reviews --interactive

# 保存設定の表示・対話で変更・初期化
google-maps-reviews settings show
google-maps-reviews settings edit
google-maps-reviews settings reset

# ブラウザーの準備だけを実行
google-maps-reviews setup --browser chrome
google-maps-reviews setup --browser chromium

# 保存設定で非対話実行。明示したオプションを優先
google-maps-reviews "https://maps.app.goo.gl/店舗の共有URL" --use-settings --all
```

pipx版などの設定ファイルは `~/.config/google-maps-reviews/settings.json` です。`--config ファイル名` または環境変数 `GOOGLE_MAPS_REVIEWS_CONFIG` で変更できます。パイプやジョブで無引数起動しても入力待ちにはならず、使い方を表示して終了します。既存のURL・オプション指定で実行する場合は従来の既定値を使い、保存設定を使う時だけ `--use-settings` を指定します。

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

1コマンドでセットアップした版は、同じセットアップコマンドを再実行すると更新できます。`--prefix` を使った場合は同じ導入先を指定してください。保存設定は専用Python環境とは別のファイルに保持します。

pipx版はリポジトリのフォルダーで実行します。

```bash
git pull --ff-only
pipx reinstall google-maps-reviews
```

pipx版を削除する場合：

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

GitHub Actionsは使用しません。ローカルのPythonテストで抽出リソースの同梱、コマンド起動、サンプル出力、重複排除と総件数の照合を確認できます。生成した口コミファイル、仮想環境、ブラウザープロファイルはGit管理の対象に含めません。


## Web画面（Next.js + shadcn/ui）

公開URL：[Review Port](https://google-maps-reviews.vercel.app/)

`web/` にURL入力・収集状況・口コミ一覧・CSVダウンロード画面を同梱しています。

```bash
cd web
npm ci
npm run dev
```

ブラウザーで `http://localhost:3000` を開き、Googleマップの店舗URLを貼り付けて「このMacで収集する」を押します。CSVには日本語用BOMを付け、改行と引用符を保持します。

### Macで初回設定

Googleがログインしていないブラウザーで口コミを非表示にする店舗では、Macの専用Chromeを使います。通常のChromeとは別の収集用プロファイルを用意し、Googleログインを保持します。

1. Google ChromeとNode.js 22を準備し、このリポジトリの `start-web-collector.command` を開きます。
2. 新しく開いた専用ChromeでGoogleマップを確認し、ログインを求められる場合はログインします。パスワードをこのツールへ入力する必要はありません。
3. Google Chromeで[公開サイト](https://google-maps-reviews.vercel.app/)を開き、「このMacと接続」を押して、ブラウザーが求めるローカルネットワーク接続を許可します。
4. 店舗URLを貼り付けて「このMacで収集する」を押し、完了後に「CSVをダウンロード」を押します。

設定後はMacにログインすると収集サービスと専用Chromeが起動します。収集中はMacを起動し、専用Chromeを開いたままにしてください。接続した画面から口コミだけを収集でき、専用Chromeの操作用ポートをインターネットへ公開する構成ではありません。取得データはブラウザーへ直接返します。

収集サービスを停止するには `stop-web-collector.command` を開きます。再開には `start-web-collector.command` を開きます。ターミナルからも利用できます。

```bash
cd web
npm ci
npm run collector:install  # 自動起動を設定して起動
npm run collector:stop     # 停止
npm run collector          # 自動起動を使わず手動で起動
node scripts/install-local-collector.mjs uninstall  # 自動起動設定を削除
```

Mac用の収集サービスは `127.0.0.1:38473` で待ち受けます。公開サイトとローカル開発画面のOriginだけを許可し、同時収集は1件です。ログイン済みブラウザーのセッションをコピーしてVercelへ送ることはありません。

### クラウドで収集する場合

「このMacで収集する」はMacの収集サービスに接続して実行します。接続が許可されていない場合やサービスが停止している場合は、接続の案内を表示して停止します。Vercel側へ自動で切り替えることはありません。

クラウド収集は「オンラインで収集を試す」を明示的に押した場合だけVercel上のChromiumを使います。Googleが口コミ表示を制限する場合は停止し、Mac用の初回設定を案内します。通常のログインボタンがあるだけで表示制限とは判定しません。未ログインのitachiyaとUnfound Projectでは、Google自身が「Google マップの表示が制限されています」と表示することを確認しました。

Macを使わずに運用するには、別途ログイン済みのクラウド収集用ブラウザーが必要です。サーバー側の環境変数 `BROWSER_CDP_URL` に接続先を設定します。接続先はGitに登録せず、公開用の `NEXT_PUBLIC_` 変数には設定しません。収集処理が作ったタブを閉じた後に接続を切り、ログイン用のタブは保持します。クラウドブラウザーの契約やGoogleログインの代行は行いません。

サーバーの実行時間内に取得できた分をCSVに保存します。画面総件数と重複なし取得件数が一致した場合のみ全件確認済みにします。途中停止や件数不一致では部分取得として表示します。

### Vercelによる自動更新

GitHubリポジトリ `atsuki-sakai/google-maps-reviews` は[Vercelプロジェクト](https://vercel.com/atsukisakais-projects/google-maps-reviews)とGit Integrationで接続しています。Root Directoryは `web`、FrameworkはNext.js、Node.jsは22、Production Branchは `main` です。`main` へのpushでVercelが自動ビルドし、成功したデプロイを本番URLに反映します。GitHub Actionsのワークフローはありません。

Build Commandは `npm run lint && npm test && npm run build`。Vercel上のブラウザー起動とGoogleの表示制限は、静的ビルドの成功とは別に実際の収集で確認が必要です。

ビルド設定は `web/vercel.json`、Node.js 22の指定は `web/package.json` に保存しています。初回の連携でLogin Connectionを求められた場合は、[VercelのAuthentication設定](https://vercel.com/account/settings/authentication)でGitHubアカウントを接続し、このリポジトリへのアクセスを許可してください。

```bash
# 静的チェック・純粋関数のテスト・本番ビルド
npm run lint
npm test
npm run build

# MacのChromeで通常形式・宿泊施設形式を確認（架空のHTML）
npm run test:browser
```

Python CLIとWeb版は同じ `extract_reviews.js` を利用します。変更時は `npm run sync` でWeb用の抽出ソースを更新します（dev/buildの前にも自動実行）。

## 実店舗の確認状況

2026年10月5日、公開サイトのフォームからUnfound Projectの口コミを収集し、「CSVをダウンロード」で保存しました。表示総件数30件、重複なし口コミID30件、ダウンロードCSV30行が一致し、星5が29件・星4が1件、本文の省略表示が残った件数は0件でした。取得はこのMacの専用Chromeを使い、画面の初回ローカルネットワーク接続許可を付与したテストブラウザーから行っています。画面に表示した先頭20件だけでなく、CSVには30件すべてを保存できることを確認しました。

2026年10月5日、「いっかくじゅう」の実際の口コミ画面で全331件を収集し、CSV・Excel・JSONに保存しました。画面総件数331件、重複なし口コミID331件、ファイル331行が一致し、省略表示の残った本文は0件でした。星評価別も5つ星217件・4つ星54件・3つ星35件・2つ星8件・1つ星17件で一致しました。

この確認にはログイン済みのCodex内ブラウザーと同梱の抽出・保存処理を使用しています。専用Chromeでのコマンド通し実行による全件収集は、まだ未確認です。Google側の表示変更、ログイン、確認画面、通信状況で停止する場合があります。店舗ごとに取得情報で件数を確認してください。

実装で参照した公式ドキュメント：[Pythonのパッケージ設定](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)、[VercelとGitHubの連携](https://vercel.com/docs/git/vercel-for-github)、[Playwrightの要素操作](https://playwright.dev/python/docs/api/class-locator)。

宿泊施設の「5/5」形式にも対応しています。itachiyaの実画面では表示総件数6件に対し、7件の口コミカードを読み取れました。この不一致は全件確認済みとしません。
