# 口コミCSVの分析レポート

収集と分析を分けて使います。CLIはURLから本文のある口コミだけをCSVへ保存し、Skillは渡されたCSVの全行を分析します。評価のみの投稿は収集結果の行に含めません。Skillがブラウザーを開いたり、過去の別店舗のデータを探したりすることはありません。

## 利用方法

まず収集します。

```bash
google-maps-reviews "店舗の共有URL" --all
# 指定期間だけをCSVへ保存する場合
google-maps-reviews "店舗の共有URL" --from 2026-01-01 --to 2026-09-30
```

期間指定では本文ありのうち日付の推定範囲全体が期間内の口コミをCSVに保存します。本文ありの境界・日付不明、期間外の口コミは同じExcelの別シートへ保存します。CSVを分析しても、要確認の口コミを含む正確な期間内全件の分析とは扱いません。Googleの相対日付は正確な投稿日ではありません。

Skillを一度導入します。

```bash
google-maps-reviews skill install
```

Codexの新しい会話でCSVのパスを渡します。

```text
$google-review-report /Users/利用者/Desktop/GoogleMap口コミ/店舗_口コミ_日時.csv
```

返信案の要否を開始時に確認します。不要なら返信案・返信方針を作らず、HTMLの返信欄やExcelの返信案シートも出力しません。現在の会話のモデル・推論設定を使い、時間をかけて本文を読みます。Skillの文面だけでは推論設定は変更できないので、高い推論設定を選んで利用してください。別のCodex CLIは自動起動しません。

SkillはCodexの `~/.codex/skills/google-review-report/` に導入します。Claude Codeでも使う場合は、次のコマンドでClaudeの個人用Skillフォルダーに導入できます。

```bash
google-maps-reviews skill install --path "$HOME/.claude/skills"
```

Claudeでは `/google-review-report CSVのパス` と指定します。利用環境のSkill読み込みに従い、現在のモデルで分析します。

## 入力CSV

UTF-8（BOM付きも可）のCSVです。0.7.0以降の収集CLIの出力は本文ありだけです。そのまま渡せます。必須列は「口コミ本文」「星評価」、または英語名 `text`・`rating`。旧版や外部のCSVに本文が空欄の行があれば、指定された入力を保持して評価のみとして別集計し、本文の分析は作りません。口コミIDがない場合はCSV行番号を分析用のIDにします。店舗名・投稿日・既存返信などは任意です。複数施設の混在、不正な評価、ID重複、列数の不一致はエラーにします。

平均星・話題の割合・傾向は、入力CSVの行に限定した統計です。本文ありだけのCSVの平均星を、評価のみも含むGoogleマップの店舗全体の評価として説明しません。

詳細は [CSV入力仕様](src/google_maps_reviews/skills/google-review-report/references/csv-input.md) を参照してください。CSVの行数からGoogleマップの全件取得を断定しません。レポートには「入力CSVの全行を分析」と表示します。

## レポートの内容

| 内容 | 使い道 |
| --- | --- |
| 星・本文感情・話題別分布 | 好評・不満の領域を把握 |
| 顧客体験の流れ | 来店前・受付・利用・会計などの摩擦を整理 |
| 強み・課題・原因仮説 | 根拠、別の説明、現場の確認方法を検討 |
| 改善の実行計画 | 優先順位、担当案、工数、期間、指標、目標案 |
| 個別の口コミ・任意の返信案 | 本文・星・感情・話題で検索 |

話題別感情分析（ABSA）、顧客体験の整理、仮説検証、影響と実行負荷による優先順位、PDCAを組み合わせます。5 Whysは現場の確認質問に使います。研究と限界は [分析方法](src/google_maps_reviews/skills/google-review-report/references/methodology.md) を参照してください。

原因は仮説、担当・期間・目標は提案です。未確認の売上効果や改善済みの主張は作りません。口コミは自発的な投稿であり、全顧客の満足度や因果効果を推定しません。分類の確信度はモデルの判断です。

## 出力

デスクトップの `GoogleMap口コミレポート/口コミ分析_日時_識別子/` に、オフラインHTMLと1つのExcelを保存します。

```text
口コミレポート.html
口コミ分析.xlsx          概要・分類済み口コミ・話題別根拠・カテゴリ集計・改善アクション・分析と提案
source.csv               指定CSVの原本（バイト単位で保持）
source.json              CSVから変換した解析用データ
analysis.json            全行の分析
statistics.json          プログラムで計算した統計
manifest.json            原本と解析用データのハッシュ・件数・分割情報
packets/                 本文ありの20件ずつの分析入力
annotations/             分析済みの分割ファイル
```

返信が必要な場合だけExcelに返信案シートを追加します。原文と要約は別列、数値は数値列、一覧はフィルター・見出し固定付きです。改善アクションの状態を未着手・進行中・完了・保留から選択できます。複数の分析CSVは作りません。

HTMLとExcelは同じフォルダーに置いてください。原文情報を含むCSV・Excel・JSONを公開リポジトリへ追加しないでください。返信は下書きであり、自動投稿しません。

## Skillの補助コマンド

以下はファイル準備・検証・描画だけを行います。意味の分析はSkillが担当します。

```bash
google-maps-reviews report prepare --input "口コミ.csv" --no-replies
# 返信ありにする場合は --with-replies
# 確認済み事業情報は --context "事業情報.md"、保存先は --output-dir "空のフォルダー"
google-maps-reviews report validate "保存先"
google-maps-reviews report stats "保存先"
google-maps-reviews report render "保存先" --no-open
```

中断後はSkillに分析フォルダーを明示して続けてください。有効な既存の分類を保持して残りを分析します。`report URL` や `report resume` による収集・AI自動起動は0.6.0で廃止しました。

0件、重複ID、未分析行、本文に存在しない引用は生成前にエラーにします。原本CSVまたはsource.jsonを変更するとハッシュ照合で拒否するため、入力を差し替える場合は新しいフォルダーで準備します。分析の形式は [schema.md](src/google_maps_reviews/skills/google-review-report/references/schema.md) にあります。
