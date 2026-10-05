import { Terminal, FileSpreadsheet, MapPin } from 'lucide-react';

const install = "bash -o pipefail -c 'curl -fsSL https://raw.githubusercontent.com/atsuki-sakai/google-maps-reviews/main/install-cli.py | python3 -'";
const collect = 'google-maps-reviews "https://maps.app.goo.gl/店舗の共有URL" --all';

export default function Home() {
  return <div className="cli-shell">
    <header className="cli-header"><span className="cli-brand"><MapPin aria-hidden="true" />google-maps-reviews</span><span>Mac専用 / MITライセンス</span></header>
    <main>
      <section className="cli-hero">
        <div><h1>ターミナルから、<br />口コミをファイルに。</h1><p>Googleマップの店舗URLを指定して、<br />口コミをCSV・Excel・JSONへ。<br />収集も保存も、あなたのMacで完結します。</p></div>
        <div className="cli-terminal" aria-label="ターミナルでの実行例">
          <div className="cli-terminal-title"><Terminal aria-hidden="true" /><span>ターミナル</span></div>
          <pre><code>{collect}</code></pre>
          <p className="cli-example-label">出力例</p>
          <pre className="cli-output"><code>{'取得済み: 10件 / 画面の総件数: 30\n取得済み: 20件 / 画面の総件数: 30\n取得済み: 30件 / 画面の総件数: 30\n\n30件を保存しました。'}</code></pre>
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
        <p>店舗ページの「共有」でコピーしたURLを指定します。画面の総件数と重複なしの取得件数が一致すると、自動保存して終了します。</p>
        <pre><code>{collect}</code></pre>
        <p>対話で設定を選ぶ場合は、コマンド名だけで起動します。</p>
        <pre><code>google-maps-reviews</code></pre>
        <p>ログインや口コミ画面の手動操作が必要な場合は <code>--manual</code> を付け、開いた専用ブラウザーで操作してからターミナルでEnterを押してください。ログイン状態はMacに保持します。</p>
      </section>
      <section className="cli-guide cli-limits" aria-labelledby="limits-title">
        <h2 id="limits-title">取得結果を確認</h2>
        <p>Googleの表示制限や確認画面により、全件を取得できない場合があります。Excelの「取得情報」で画面総件数・保存件数・停止理由・本文の省略件数を確認してください。</p>
      </section>
    </main>
    <footer className="cli-footer"><span>google-maps-reviews</span><span>CSV / Excel / JSON</span></footer>
  </div>;
}
