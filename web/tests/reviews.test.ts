import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import test from 'node:test';
import { chromium, type Browser } from 'playwright-core';
import { POST } from '../src/app/api/collect/route';
import { collectReviews } from '../src/lib/collector';
import { isFullCoverage, mergeReviews, toCsv, validateMapsUrl, type Review } from '../src/lib/reviews';
const row: Review = { review_id: 'review-1', author: '投稿者', rating: 5, date_text: '2 年前', text: '全文\n2行目', owner_reply: '', author_url: '', text_may_be_truncated: false };

test('Googleマップ以外と認証情報を含むURLは拒否する', () => {
  for (const value of ['https://example.com/maps', 'http://google.com/maps', 'https://google.com.example.com/maps', 'https://x:y@google.com/maps', 'file:///tmp/a']) assert.throws(() => validateMapsUrl(value));
  assert.equal(validateMapsUrl('https://maps.app.goo.gl/example'), 'https://maps.app.goo.gl/example');
});
test('重複を除き、展開済みの長い本文を保持する', () => {
  const rows = new Map<string, Review>(); mergeReviews(rows, [row]);
  mergeReviews(rows, [{ ...row, text: '全文', text_may_be_truncated: true }]);
  assert.equal(rows.size, 1); assert.equal(rows.get(row.review_id)?.text, row.text);
  assert.equal(rows.get(row.review_id)?.text_may_be_truncated, false);
});
test('表示6件と取得7件を全件確認済みにしない', () => {
  const rows = Array.from({ length: 7 }, (_, i) => ({ ...row, review_id: String(i) }));
  assert.equal(isFullCoverage(rows, 6), false); assert.equal(isFullCoverage(rows, 7), true);
  assert.equal(isFullCoverage(rows, null), false);
  assert.equal(isFullCoverage([row, row], 2), false);
});
test('CSVは日本語、改行、引用符を保持し、数式を文字列にする', () => {
  const csv = toCsv({ place: 'テスト店舗', sourceUrl: 'https://www.google.com/maps/test', displayedTotal: 1, reviews: [{ ...row, author: '=1+1', text: '日本語, "引用"\n2行目' }], verified: true, reason: '' });
  assert.ok(csv.startsWith('\uFEFF')); assert.ok(csv.includes('"\'=1+1"'));
  assert.ok(csv.includes('"日本語, ""引用""\n2行目"')); assert.ok(csv.includes('テスト店舗'));
});

function collectRequest(body = JSON.stringify({ url: 'https://www.google.com/maps/test' })) {
  return new Request('http://localhost/api/collect', { method: 'POST', body });
}

test('CDPの接続秘密とPlaywrightの生例外をSSEに公開しない', async (t) => {
  const paths: string[] = [];
  const server = createServer((request, response) => {
    paths.push(request.url || '');
    response.writeHead(401);
    response.end('Unauthorized');
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const previous = process.env.BROWSER_CDP_URL;
  process.env.BROWSER_CDP_URL = `http://127.0.0.1:${address.port}?token=DUMMY_REVIEW_SECRET`;
  t.after(() => {
    if (previous === undefined) delete process.env.BROWSER_CDP_URL;
    else process.env.BROWSER_CDP_URL = previous;
  });
  const response = await POST(collectRequest());
  const output = await response.text();
  assert.equal(response.status, 200);
  assert.ok(paths.some(path => path.includes('token=DUMMY_REVIEW_SECRET')));
  assert.doesNotMatch(output, /DUMMY_REVIEW_SECRET|token=|connectOverCDP|127\.0\.0\.1/);
  const events = output.trim().split('\n\n').map(line => JSON.parse(line.slice('data: '.length)));
  assert.deepEqual(events.at(-1), { type: 'error', message: '口コミの収集に失敗しました。時間をおいて再度お試しください。' });
});

test('Googleの表示制限と口コミURL確認の案内はSSEに残す', async (t) => {
  const previous = process.env.BROWSER_CDP_URL;
  process.env.BROWSER_CDP_URL = 'http://browser.invalid';
  t.after(() => {
    if (previous === undefined) delete process.env.BROWSER_CDP_URL;
    else process.env.BROWSER_CDP_URL = previous;
  });
  for (const [body, message] of [
    ['unusual traffic', 'Googleがこの収集用ブラウザーでの口コミ表示を制限しています。ログイン済みの収集環境が必要です。MacのCLIではログイン後に収集できます。'],
    ['', '口コミ一覧が見つかりません。店舗ページの共有URLを確認してください。'],
  ]) {
    const page = {
      setDefaultTimeout() {},
      async goto() {},
      getByRole: () => ({ first: () => ({ async waitFor() {}, async count() { return 0; } }) }),
      locator: (selector: string) => selector === 'body'
        ? { async innerText() { return body; } }
        : { async count() { return 0; }, first: () => ({ async waitFor() { throw new Error('DUMMY_REVIEW_SECRET'); } }) },
    };
    const browser = { contexts: () => [{ async newPage() { return page; } }], async close() {} } as unknown as Browser;
    const connection = t.mock.method(chromium, 'connectOverCDP', async () => browser);
    const output = await (await POST(collectRequest())).text();
    connection.mock.restore();
    assert.doesNotMatch(output, /DUMMY_REVIEW_SECRET/);
    const events = output.trim().split('\n\n').map(line => JSON.parse(line.slice('data: '.length)));
    assert.deepEqual(events.at(-1), { type: 'error', message });
  }
});

test('CDP接続待ち中の中止後はページを開かずに接続を閉じる', async (t) => {
  const previous = process.env.BROWSER_CDP_URL;
  process.env.BROWSER_CDP_URL = 'http://browser.invalid';
  t.after(() => {
    if (previous === undefined) delete process.env.BROWSER_CDP_URL;
    else process.env.BROWSER_CDP_URL = previous;
  });
  let resolveConnection!: (browser: Browser) => void;
  const connection = new Promise<Browser>(resolve => { resolveConnection = resolve; });
  t.mock.method(chromium, 'connectOverCDP', () => connection);
  let contextsRead = 0;
  let contextCreated = 0;
  let closed = 0;
  const browser = {
    contexts() { contextsRead++; return []; },
    async newContext() { contextCreated++; throw new Error('中止後に実行されました。'); },
    async close() { closed++; },
  } as unknown as Browser;
  const abort = new AbortController();
  const events: string[] = [];
  const collecting = collectReviews('https://www.google.com/maps/test', event => events.push(event.type), abort.signal);
  abort.abort();
  resolveConnection(browser);
  await collecting;
  assert.equal(contextsRead, 0);
  assert.equal(contextCreated, 0);
  assert.equal(closed, 1);
  assert.deepEqual(events, ['status']);
});

test('JSON読み取り例外は安全なURL案内にし、URL検証の案内を保持する', async () => {
  const malformed = await POST(collectRequest('DUMMY_REVIEW_SECRET'));
  assert.equal(malformed.status, 400);
  assert.deepEqual(await malformed.json(), { error: 'URLを確認してください。' });
  for (const [url, error] of [
    ['not-a-url', 'Googleマップの店舗URLを貼り付けてください。'],
    ['https://example.com/maps', 'GoogleマップのHTTPS店舗URLを指定してください。'],
  ]) {
    const response = await POST(collectRequest(JSON.stringify({ url })));
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { error });
  }
});
