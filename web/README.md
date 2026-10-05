# Review Port

公開URL：[Review Port](https://google-maps-reviews.vercel.app/)

Googleマップの店舗URLから口コミを収集し、CSVに保存するNext.js + shadcn/uiの画面です。セットアップ、制限、Vercel自動更新の設定は[リポジトリのREADME](../README.md)を参照してください。

```bash
npm ci
npm run dev
```

「このMacで収集する」はこのMacの専用Chromeを使います。初回は収集サービスを起動し、公開サイトからのローカルネットワーク接続を許可してください。未接続時は接続方法を表示し、Vercel側へ自動で切り替えません。「オンラインで収集を試す」を明示的に押した場合のみVercel上のChromiumを使います。画面の公開と実店舗の全件収集は別に確認します。

```bash
npm run lint
npm test
npm run build
npm run test:browser
```
