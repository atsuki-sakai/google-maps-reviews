# Review Port

公開URL：[Review Port](https://google-maps-reviews.vercel.app/)

Googleマップの店舗URLから口コミを収集し、CSVに保存するNext.js + shadcn/uiの画面です。セットアップ、制限、Vercel自動更新の設定は[リポジトリのREADME](../README.md)を参照してください。

```bash
npm ci
npm run dev
```

公開版の収集はVercel上のChromiumで行います。Googleがログインを求める場合は、ログイン済みの収集用ブラウザーの接続設定が必要です。画面が公開されていることと、実店舗の全件収集が成功したことは別に確認します。

```bash
npm run lint
npm test
npm run build
npm run test:browser
```
