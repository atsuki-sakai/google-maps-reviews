# CLIの説明ページ

Mac専用の `google-maps-reviews` CLIのセットアップ、実行コマンド、保存先を説明するページです。URL入力、口コミ収集、CSVダウンロードの機能はありません。CLI利用者はこのページを起動する必要がありません。

Node.js 22で開発します。

```bash
npm ci
npm run dev
npm run lint
npm test
npm run build
```

GitHubのmain更新をVercelのGit Integrationで自動反映します。GitHub Actionsは使用しません。Root Directoryは `web` です。

`/api/collect` は旧クライアント向けに410を返し、収集を実行しません。`scripts/local-collector.ts` と対応するライブラリーは旧版CLIのMac収集サービスとの互換性を保つために残しています。新規のCLIセットアップにはNode.jsもこのサービスも不要です。
