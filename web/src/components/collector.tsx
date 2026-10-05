'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, MapPin, GitBranch, FileSpreadsheet, Check, Square, AlertCircle, Link as LinkIcon } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldGroup, FieldLabel, FieldDescription, FieldError } from '@/components/ui/field';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell, TableCaption } from '@/components/ui/table';
import { toCsv, validateMapsUrl, type Collection, type CollectionEvent } from '@/lib/reviews';

export function Collector() {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState<Collection | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    let target: string;
    try { target = validateMapsUrl(url); } catch (e) { setError((e as Error).message); return; }
    setError(''); setData(null); setBusy(true); setMessage('収集を開始しています。');
    const controller = new AbortController(); request.current = controller;
    let completed = false;
    try {
      const response = await fetch('/api/collect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: target }), signal: controller.signal });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(typeof body?.error === 'string' && body.error ? body.error : '収集を開始できませんでした。時間をおいて再度お試しください。');
      }
      if (!response.body) throw new Error('収集結果を受信できませんでした。');
      const reader = response.body.getReader();
      const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        let end: number;
        while ((end = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
          if (!frame.startsWith('data: ')) continue;
          const item = JSON.parse(frame.slice(6)) as CollectionEvent;
          if (item.type === 'status') setMessage(item.message);
          if (item.type === 'progress') { setData(item.data); setMessage('口コミを収集中です。'); }
          if (item.type === 'done') { setData(item.data); setMessage(item.data.reason); completed = true; }
          if (item.type === 'error') { setError(item.message); completed = true; }
        }
        if (chunk.done) break;
      }
      if (!completed) throw new Error('通信が途中で切れました。取得済みの口コミはCSVに保存できます。');
    } catch (e) {
      if (controller.signal.aborted) { setMessage('収集を中止しました。取得済みの口コミを保存できます。'); setData(old => old ? { ...old, verified: false } : null); }
      else setError(e instanceof Error ? e.message : '通信に失敗しました。再度お試しください。');
    } finally { setBusy(false); request.current = null; }
  }

  function download() {
    if (!data?.reviews.length) return;
    const blob = new Blob([toCsv(data)], { type: 'text/csv;charset=utf-8' });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a'); anchor.href = objectUrl;
    anchor.download = `${data.place.replace(/[\\/:*?"<>|]/g, '_') || '口コミ'}_口コミ_${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
  const count = data?.reviews.length ?? 0;
  const truncated = data?.reviews.filter(row => row.text_may_be_truncated).length ?? 0;
  return <div className="site-shell">
    <header className="site-header">
      <Link className="wordmark" href="/" aria-label="Review Port ホーム"><span className="brand-mark"><MapPin aria-hidden="true" /></span>Review Port</Link>
      <a className={buttonVariants({ variant: 'ghost' })} href="https://github.com/atsuki-sakai/google-maps-reviews" target="_blank" rel="noreferrer"><GitBranch data-icon="inline-start" />GitHub</a>
    </header>
    <main>
      <section className="hero">
        <div className="hero-copy">
          <h1>口コミを、<br />分析できるデータに。</h1>
          <p className="hero-description">Googleマップの店舗URLを貼り付けるだけ。<br className="desktop-break" />口コミの本文・評価・投稿日を、ひとつのCSVに。</p>
          <form onSubmit={start} className="collector-form" noValidate>
            <FieldGroup>
              <Field data-invalid={!!error} data-disabled={busy}>
                <FieldLabel htmlFor="maps-url">Googleマップの店舗URL</FieldLabel>
                <Input id="maps-url" name="url" type="url" value={url} onChange={event => { setUrl(event.target.value); setError(''); }} placeholder="https://maps.app.goo.gl/..." disabled={busy} aria-invalid={!!error} aria-describedby="url-help" required autoComplete="off" />
                <FieldDescription id="url-help">店舗ページの「共有」からURLをコピーしてください。</FieldDescription>
                {error && <FieldError>{error}</FieldError>}
              </Field>
              <div className="form-actions">
                <Button type="submit" size="lg" disabled={busy || !url.trim()}><LinkIcon data-icon="inline-start" />{busy ? '口コミを収集中…' : '口コミを収集する'}</Button>
                {busy && <Button type="button" variant="outline" onClick={() => request.current?.abort()}><Square data-icon="inline-start" />中止</Button>}
              </div>
            </FieldGroup>
          </form>
          <p className="privacy-note">収集結果は、この画面からCSVとして保存できます。</p>
        </div>
        <aside className="export-visual" aria-label="CSVに保存する項目">
          <div className="file-sheet">
            <div className="file-heading"><span className="file-symbol"><FileSpreadsheet aria-hidden="true" /></span><div><strong>口コミ.csv</strong><span>Excel・Googleスプレッドシートで分析</span></div><Badge variant="secondary">CSV</Badge></div>
            <div className="column-map"><span>店舗名</span><span>投稿者</span><span>評価</span><span>投稿日</span><span>口コミ本文</span></div>
            <div className="file-lines" aria-hidden="true">{[0, 1, 2, 3].map(i => <div key={i}><i /><i /><i /><i /><i /></div>)}</div>
            <Separator />
            <div className="file-notes"><span><Check aria-hidden="true" />口コミIDで重複を除外</span><span><Check aria-hidden="true" />画面の総件数と照合</span></div>
          </div>
          <p className="export-caption">読むための口コミから、使えるデータへ。</p>
        </aside>
      </section>
      {(busy || data) && <section className="results" aria-label="収集結果" aria-busy={busy}>
        <div className="results-header"><div><p className="result-description">収集結果</p><h2>{data?.place || '口コミを読み込んでいます'}</h2></div>
          {!!count && <Button onClick={download} disabled={busy} size="lg"><ArrowDownToLine data-icon="inline-start" />CSVをダウンロード</Button>}</div>
        <div className="collection-status" role="status" aria-live="polite"><span>{message}</span><span>{count}件取得{data?.displayedTotal !== null && data?.displayedTotal !== undefined ? ` / 画面 ${data.displayedTotal}件` : ''}</span></div>
        {busy && <Progress aria-label="口コミ収集の進行状況" value={data?.displayedTotal ? Math.min(100, count / data.displayedTotal * 100) : null} />}
        {!busy && data && <Alert><AlertCircle /><AlertTitle>{data.verified ? '画面の総件数と保存件数が一致しました。' : '全件取得は未確認です。取得できた分を保存できます。'}</AlertTitle><AlertDescription>取得 {count}件 / 画面の総件数 {data.displayedTotal ?? '不明'}件。本文の省略表示が残った口コミは{truncated}件です。</AlertDescription></Alert>}
        {count > 0 && <Table><TableCaption>取得した口コミの先頭20件。CSVには取得分すべてを保存します。</TableCaption><TableHeader><TableRow><TableHead>投稿者</TableHead><TableHead>評価</TableHead><TableHead>投稿日</TableHead><TableHead>口コミ本文</TableHead></TableRow></TableHeader><TableBody>{data?.reviews.slice(0, 20).map(row => <TableRow key={row.review_id}><TableCell>{row.author}</TableCell><TableCell><span className="rating">★ {row.rating}</span></TableCell><TableCell>{row.date_text}</TableCell><TableCell><div className="review-body">{row.text || '本文なし（評価のみ）'}</div></TableCell></TableRow>)}</TableBody></Table>}
      </section>}
      <section className="usage-note"><h2>取得範囲について</h2><p>Googleマップに表示される口コミを収集します。Google側の表示制限や確認画面で停止した場合は、その理由を表示します。画面の総件数と取得件数が一致した場合に、全件取得を確認済みと表示します。</p><p>本文はGoogleによる翻訳を含むことがあります。ログインが必要な店舗では、ログイン済みの収集環境またはMac用コマンドをご利用ください。</p></section>
    </main>
    <footer><span>Review Port</span><span>Googleマップの口コミを、CSVに。</span></footer>
  </div>;
}
