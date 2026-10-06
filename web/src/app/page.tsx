import { Terminal, FileSpreadsheet, MapPin } from 'lucide-react';

const install = "bash -o pipefail -c 'curl -fsSL https://raw.githubusercontent.com/atsuki-sakai/google-maps-reviews/main/install-cli.py | python3 -'";
const collect = 'google-maps-reviews "https://maps.app.goo.gl/店舗の共有URL" --all';

export default function Home() {
  return <div className="cli-shell">
    <header className="cli-header"><span className="cli-brand"><MapPin aria-hidden="true" />google-maps-reviews</span><span>Mac専用 / MITライセンス</span></header>
    <main>
      <section className="cli-hero">
        <div><h1>ターミナルから、<br />口コミをファイルに。</h1><p>Googleマップの店舗URLを指定して、<br />本文のある口コミだけをCSV・Excel・JSONへ。<br />収集も保存も、あなたのMacで完結します。</p></div>
        <div className="cli-terminal" aria-label="ターミナルでの実行例">
          <div className="cli-terminal-title"><Terminal aria-hidden="true" /><span>ターミナル</span></div>
          <pre><code>{collect}</code></pre>
          <p className="cli-example-label">出力例</p>
          <pre className="cli-output"><code>{'一覧読取: 30件 / 画面の総件数: 30\n本文あり読取: 24件 / 評価のみ除外: 6件\n\n本文あり24件をCSV・Excel・JSONに保存しました。'}</code></pre>
          <p className="cli-save"><FileSpreadsheet aria-hidden="true" />デスクトップの「GoogleMap口コミ」に保存</p>
        </div>
      </section>
      <section className="cli-guide" aria-labelledby="setup-title">
        <h2 id="setup-title">はじめてのセットアップ</h2>
        <p>macOS・Python 3.10以上・Google Chromeを準備して、ターミナルで実行します。</p>
        <pre><code>{install}</code></pre>
        <p>GitHubへのログインやAPIキーは不要です。コマンドが見つからない場合は、次を実行します。</p>
        <pre><code>{'export PATH="$HOME/.local/bin:$PATH"'}</code></pre>
      </section>
      <section className="cli-guide" aria-labelledby="usage-title">
        <h2 id="usage-title">URLを指定して収集</h2>
        <p>店舗ページの「共有」でコピーしたURLを指定します。一覧の読取件数を画面総件数と照合してから、本文ありの口コミだけを保存します。評価のみ・店舗返信のみの投稿は保存しません。</p>
        <pre><code>{collect}</code></pre>
        <p>対話で設定を選ぶ場合は、コマンド名だけで起動します。</p>
        <pre><code>google-maps-reviews</code></pre>
        <p>ログインや口コミ画面の手動操作が必要な場合は <code>--manual</code> を付け、開いた専用ブラウザーで操作してからターミナルでEnterを押してください。ログイン状態はMacに保持します。</p>
      </section>
      <section className="cli-guide cli-limits" aria-labelledby="limits-title">
        <h2 id="limits-title">取得結果を確認</h2>
        <p>Googleの表示制限や確認画面により、全件を取得できない場合があります。Excelの「取得情報」で一覧の読取件数・本文ありの保存件数・評価のみの除外件数を確認してください。期間指定の日付には推定が含まれます。</p>
      </section>
    </main>
    <footer className="cli-footer"><span>google-maps-reviews</span><span>CSV / Excel / JSON</span></footer>
  </div>;
}
