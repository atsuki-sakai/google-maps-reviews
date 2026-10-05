# google-maps-reviews

**Mac専用のGoogleマップ口コミ収集CLI。** 店舗URLを指定すると、専用ブラウザーに表示された口コミを収集して、デスクトップへCSV・Excel・JSONを保存します。MITライセンスのOSSです。

```bash
google-maps-reviews "https://maps.app.goo.gl/店舗の共有URL" --all
```

- 本文の「もっと見る」を展開し、口コミ一覧を自動スクロール
- 口コミIDで重複を除外し、画面の総件数と保存件数を照合
- 件数が一致したら自動保存して終了
- 無引数で対話メニューを開き、パラメータを番号で選択
- 収集から保存まで利用者のMacで実行

## 必要なもの

| 項目 | 要件 |
| --- | --- |
| OS | macOS専用。Windows・Linuxはサポート対象外 |
| Python | 3.10以上。`python3 --version` で確認 |
| ブラウザー | Google Chrome。Chromiumをツールで導入することも可能 |
| 通信 | GitHub、Pythonパッケージの配布先、Googleマップへの接続 |

CLIの利用にNode.js、Vercel、GitHubアカウント、APIキーは不要です。

PythonやChromeがない場合は、Homebrewを導入済みのMacで次を実行できます。

```bash
brew install python
brew install --cask google-chrome
```

## セットアップ

ターミナルに次の1コマンドを貼り付けます。公開リポジトリからソースを取得し、利用者専用のPython環境とコマンドを準備します。`sudo` やGitHubへのログインは不要です。

```bash
bash -o pipefail -c 'curl -fsSL https://raw.githubusercontent.com/atsuki-sakai/google-maps-reviews/main/install-cli.py | python3 -'
```

続けて確認します。

```bash
google-maps-reviews --version
```

`command not found` と表示された場合は、PATHを追加します。

```bash
export PATH="$HOME/.local/bin:$PATH"
```

次回のターミナルでも使うには、上の行を `~/.zshrc` に追加します。セットアップはシェル設定を自動で書き換えません。PATHを設定する前でも `~/.local/bin/google-maps-reviews` で実行できます。

Chromeの代わりにChromiumを準備する場合は、セットアップの末尾に `--browser chromium` を付けます。その後の収集にも `--browser chromium` を付けるか、対話メニューでChromiumを選択してください。

## 使い方

### URLを指定して全件を収集

Googleマップの店舗ページで「共有」からURLをコピーします。

```bash
google-maps-reviews "https://maps.app.goo.gl/店舗の共有URL" --all
```

専用ブラウザーを開いて収集します。Googleにログインを求められたら、そのブラウザーで操作してください。自動で口コミ一覧を開けない場合は、手動モードを使います。

```bash
google-maps-reviews "https://maps.app.goo.gl/店舗の共有URL" --all --manual
```

専用ブラウザーで店舗の「口コミ」を開き、必要に応じて「すべてのクチコミ」を選びます。ターミナルでEnterを押すと収集が始まります。収集が終わるまでブラウザーを閉じないでください。ログイン状態は専用プロファイルに保持され、次回も利用できます。

保存先は `~/Desktop/GoogleMap口コミ/` です。

```text
店舗名_口コミ_実行日時.csv
店舗名_口コミ_実行日時.xlsx
店舗名_口コミ_実行日時.json
```

### 対話メニューで選ぶ

```bash
google-maps-reviews
```

```text
Googleマップ口コミ収集
  1. 口コミを収集
  2. 設定を変更して保存
  3. ブラウザーをセットアップ
  4. 終了
```

URL、収集範囲、最大件数、制限時間、待機時間、保存先、ブラウザー、手動操作の有無を選べます。Enterで表示中の値を使います。対話で保存した設定は次回のメニューに引き継がれます。

### よく使う指定

```bash
# 最大50件
google-maps-reviews "店舗の共有URL" --max 50

# 収集時間を20分に延長（手動操作の時間は含まない）
google-maps-reviews "店舗の共有URL" --all --timeout 1200

# 保存先を変更
google-maps-reviews "店舗の共有URL" --all --output-dir "$HOME/Desktop/口コミ出力"

# スクロールせず、現在読み込まれた分だけ保存
google-maps-reviews "店舗の共有URL" --visible-only

# 保存済み設定で実行。明示したオプションを優先
google-maps-reviews "店舗の共有URL" --use-settings --all

# 実在しないサンプルでファイル出力を確認
google-maps-reviews --demo
```

| オプション | 内容 | 既定値 |
| --- | --- | --- |
| `--all` | 件数上限を外し、画面総件数との一致を確認 | 指定なし |
| `--max N` | 最大保存件数 | 100 |
| `--manual` | 自分で口コミ画面を開いてから収集 | 自動 |
| `--visible-only` | スクロールせず読み込み済みの分を保存 | 指定なし |
| `--timeout 秒` | 収集の制限時間 | 300秒 |
| `--delay 秒` | スクロール後の待機時間（0.5〜60秒） | 2秒 |
| `--output-dir パス` | 出力先 | `~/Desktop/GoogleMap口コミ` |
| `--browser chrome\|chromium` | 収集ブラウザー | chrome |
| `--use-settings` | 保存設定を利用 | 指定なし |
| `--config パス` | 設定ファイルの場所を変更 | 下記参照 |

`--all` と `--max`、`--all` と `--visible-only` は併用できません。途中でControl+Cを押すと、取得済みの口コミを保存します。

## 保存される項目と取得の確認

店舗名、投稿者、星評価、画面表記の投稿日、口コミ本文、店舗からの返信、口コミID、取得元URL、取得日時、省略表示の有無を保存します。評価のみの口コミも含めます。CSVはUTF-8 BOM付きで、改行と引用符を保持します。

Excelの「取得情報」シートまたはJSONの `metadata` で、次を確認できます。

| 項目 | 意味 |
| --- | --- |
| 保存件数 | 取得・保存した口コミの件数 |
| 画面総件数 | Googleマップに表示された件数 |
| 総件数と重複なし保存件数の一致 | 有効な口コミIDが重複せず、件数も一致したか |
| 本文の省略表示が残った件数 | 本文がすべて展開されたかの確認 |
| 停止理由 | 件数一致、時間切れ、中断、エラーなど |

`--all` は全件取得を試みる指定です。Google側の表示制限、確認画面、画面変更、通信状況によって取得できない場合があります。総件数が不明・不一致の場合は取得分を保存して全件未確認とします。件数の一致と本文の完全性は別に確認します。投稿日は画面表記のままで、正確な日付を推定しません。本文にはGoogleの翻訳が含まれる場合があります。

| 終了コード | 意味 |
| --- | --- |
| 0 | 正常終了。`--all` では総件数との一致を確認 |
| 1 | 起動・保存失敗、または取得0件 |
| 2 | 一部取得、全件未確認、取得後のエラー |

`--max` 使用時の0は指定範囲の保存成功、`--demo` の0はサンプル出力の成功です。

## 設定・ログイン状態

```bash
google-maps-reviews settings show
google-maps-reviews settings edit
google-maps-reviews settings reset
google-maps-reviews setup --browser chrome
```

通常のインストーラー版は `~/.local/share/google-maps-reviews/settings.json`、pipx版は `~/.config/google-maps-reviews/settings.json` に設定を保存します。`--config` または環境変数 `GOOGLE_MAPS_REVIEWS_CONFIG` で変更できます。URLを直接指定する通常実行は既定値を使い、保存設定を使う場合は `--use-settings` を付けます。

専用ブラウザーのデータは `~/Library/Application Support/google-maps-reviews/chrome/` または `chromium/` に保存します。普段使っているChromeのプロファイルは使用しません。同じ専用ブラウザーで同時に複数の収集を実行しないでください。

旧版のMac収集サービスを導入済みの場合、既定の `URL --all` はその専用Chromeを引き続き使います。新規導入ではサービスのセットアップは不要です。

## 更新

セットアップと同じ1コマンドを再実行すると最新のmainへ更新できます。設定と出力ファイルは保持します。既存のpipx版も所有情報を確認して更新します。別ツールのコマンドは上書きしません。

バージョンを固定する場合は、セットアップに `--ref v0.3.0` を付けます。

### pipxから導入する場合

```bash
brew install pipx
pipx install 'git+https://github.com/atsuki-sakai/google-maps-reviews.git@v0.3.0'
pipx ensurepath
google-maps-reviews setup --browser chrome
```

PyPIには公開していません。

## 削除

通常のインストーラー版は次で削除できます。

```bash
rm "$HOME/.local/bin/google-maps-reviews"
rm -r "$HOME/.local/share/google-maps-reviews"
```

pipxで管理されている場合は `pipx uninstall google-maps-reviews` を使用してください。ブラウザーを閉じた後、専用プロファイルや設定が不要なら上記の保存先を別途削除できます。デスクトップの口コミファイルは自動削除しません。

## 困ったとき

- **コマンドが見つからない**: PATHを確認するか `~/.local/bin/google-maps-reviews` で実行します。
- **Pythonが古い**: `python3 --version` を確認し、3.10以上を準備します。
- **口コミを自動で開けない・表示制限が出る**: `--manual` で専用ブラウザーを開き、ログインや口コミ一覧の表示を自分で確認します。
- **専用ブラウザーを起動できない**: 前回の収集が終了しているか、ツールの専用ブラウザーが残っていないかを確認します。
- **全件未確認になる**: Excelの「取得情報」で画面総件数・保存件数・停止理由を確認します。必要なら `--timeout` を延長して再実行します。
- **同名の別コマンドがある**: セットアップに `--prefix "$HOME/Tools/google-maps-reviews"` を付け、表示されたコマンドパスで利用します。

## OSS・開発

[MITライセンス](LICENSE)で公開しています。ライセンスはプログラムに適用され、取得した口コミの権利を変更するものではありません。取得データの利用・再配布は、権利やGoogleの利用条件を確認してください。

開発方法と不具合報告は [CONTRIBUTING.md](CONTRIBUTING.md)、脆弱性の非公開報告は [SECURITY.md](SECURITY.md) を参照してください。

`web/` はツールの説明用です。CLIの導入・利用にWebサイトへのアクセスやローカルネットワークの許可は不要です。
