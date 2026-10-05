# 口コミから事業改善レポート

URLから口コミを収集し、Codexが本文の意味を読んで分析します。統計とHTML・CSVの生成はプログラムで行い、根拠の引用と口コミIDを照合します。

## 初回の準備

収集CLIの導入は [README](README.md#セットアップ) の1コマンドで行います。続けてSkillを導入してください。

```bash
google-maps-reviews skill install
```

Codexの新しい会話で使えます。

```text
$google-review-report https://maps.app.goo.gl/店舗の共有URL
```

Skillからの直接実行は現在のモデル・推論設定を使います。時間をかけて分析したい場合は高い推論設定を選んでください。Skillの文章だけで実行中のモデルの推論設定を変更することはできません。

Skillの導入先は `~/.codex/skills/google-review-report/`（`CODEX_HOME` 指定時はその `skills/`）。`skill install --path "親フォルダー"` で変更できます。本ツールが導入したSkillだけを更新します。CLI更新後に `skill install` を再実行すればSkillも更新できます。

## ターミナルの1コマンドで生成

[公式のCodex CLI導入方法](https://developers.openai.com/codex/cli/) に従いCLIを準備し、`codex login` でログインします。追加のAPIキーを前提にしません。

```bash
google-maps-reviews report "https://maps.app.goo.gl/店舗の共有URL"
```

既定で推論レベル `xhigh`、Codex CLIの既定モデルを使います。独立した分析実行のためCodexの `config.toml` は読み込みませんが、アカウントのログインは利用します。モデルは `--model モデル名`、推論レベルは `--effort high` で調整できます。指定モデルが使えない場合に低い推論レベルへ自動変更しません。

収集時間の上限は既定20分（`--timeout 1200`）で、AIの分析時間とは別です。分析には件数に応じて時間がかかります。Codexの利用枠を消費し、対象口コミをモデルへ送信します。途中でControl+Cを押すと、保存済みの分析ファイルを残します。

## レポートでできること

| 内容 | 使い道 |
| --- | --- |
| 星・本文感情・話題別分布 | 全体像と好評・不満の領域を把握 |
| 顧客体験の流れ | 来店前・受付・利用・会計などの摩擦と機会を整理 |
| 強み・課題・原因仮説 | 根拠口コミ、別の説明、現場の確認方法を検討 |
| 改善の実行計画 | 優先度の理由、担当案、工数、期間、指標、目標案を確認 |
| 個別の口コミと返信案 | 本文・星・感情・話題で検索し、下書きをコピー |

話題別感情分析（ABSA）、顧客体験の整理、仮説検証、影響と実行負荷による優先順位、PDCAを組み合わせます。5 Whysは現場の確認質問に使います。研究・一次資料と限界は [分析方法](src/google_maps_reviews/skills/google-review-report/references/methodology.md) を参照してください。

原因は仮説、担当・期間・目標は提案です。未確認の売上効果、改善済み、返金、アレルギーの安全性などを作りません。口コミは自発的な投稿なので全顧客の満足度・被害率・因果効果を推定しません。分類の確信度はモデルの判断であり、実測の正答率ではありません。

## 保存されるファイル

デスクトップの `GoogleMap口コミレポート/口コミ分析_日時_識別子/` に保存します。HTMLは外部ライブラリーを読み込まずオフラインで動きます。CSVのリンクを使うため、HTMLとCSVは同じフォルダーに置いてください。

```text
口コミレポート.html
分類済み口コミ.csv       原文・感情・カテゴリ・要約・確認事項
話題別根拠.csv           口コミID・話題・感情・引用
返信案.csv               原文・既存返信・言語・個別の下書き
カテゴリ集計.csv         言及数・肯否・本文ありの母数
改善アクション.csv       優先順位の理由・担当案・期間案・指標・根拠
source.json              元の口コミ
analysis.json            全行の分析
statistics.json          プログラムで計算した統計
manifest.json            原文ハッシュ・取得件数・分割ファイル
packets/                 本文ありの20件ずつの分析入力
annotations/             分析済みの分割ファイル
codex-analysis.log       CLI分析の実行ログ
```

返信案は下書きです。事実、表現、言語、既存返信を確認してから投稿します。自動投稿機能はありません。HTMLは投稿者名を省略しますが、本文に個人情報が含まれる場合があります。CSV・JSON・実行ログには原文や投稿者情報が含まれるため、共有先を選び、公開リポジトリには追加しないでください。

## 保存済みの口コミと事業情報

```bash
# 収集済みJSONから生成。再収集しない
google-maps-reviews report --input "$HOME/Desktop/GoogleMap口コミ/店舗_口コミ.json"

# 確認済みのメニュー・営業時間・返信方針などを反映
google-maps-reviews report "店舗URL" --context "$HOME/Desktop/事業情報.md"

# 保存場所の指定と、自動で開く動作を止める指定
google-maps-reviews report "店舗URL" --output-dir "$HOME/Desktop/店舗レポート" --no-open
```

事業情報は、確認済みの事実・実際の運営方針・返信の希望を書くMarkdownです。口コミから推論した内容を確認済み情報として書かないでください。

## 中断・検証・再生成

```bash
# 中断後、保存済みの分析から再開
google-maps-reviews report resume "保存先"

# Skillが直接分析するための準備だけ実行
google-maps-reviews report prepare "店舗URL"

# 引用・口コミID・全件分析・構造を検証
google-maps-reviews report validate "保存先"

# 全行から統計を計算
google-maps-reviews report stats "保存先"

# 検証済みの分析からHTML・CSVを再生成
google-maps-reviews report render "保存先" --no-open
```

0件、重複ID、未分析行、本文に存在しない引用は生成前にエラーにします。Googleの表示制限で部分取得になった場合は、取得した範囲としてレポートに明記します。取得件数の照合は意味の分析の正しさの保証ではありません。

エラーや不完全な分析ファイルがある場合は、エラーに書かれたkey・項目をCodexで修正して再検証します。`source.json` を変更するとハッシュが一致しなくなるので、元データを差し替える場合は別のフォルダーでprepareをやり直してください。分析の形式は [schema.md](src/google_maps_reviews/skills/google-review-report/references/schema.md) にあります。
