import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import test, { type TestContext } from 'node:test';
import { chromium, type Browser, type Page } from 'playwright-core';
import { POST } from '../src/app/api/collect/route';
import { collectReviews } from '../src/lib/collector';
import { isFullCoverage, mergeReviews, toCsv, validateMapsUrl, type CollectionEvent, type Review } from '../src/lib/reviews';
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

function mockCollectionPage(t: TestContext, options: {
  body?: string;
  entries?: { role: 'tab' | 'button'; label: string; availableAt?: number; visible?: boolean }[];
  overviewCount?: number;
  reviews?: Review[];
}) {
  let now = 0;
  let opened = false;
  const clicked: string[] = [];
  const closed: string[] = [];
  const reviews = options.reviews || [row];
  t.mock.method(Date, 'now', () => now);
  const previous = process.env.BROWSER_CDP_URL;
  process.env.BROWSER_CDP_URL = 'http://browser.invalid';
  t.after(() => {
    if (previous === undefined) delete process.env.BROWSER_CDP_URL;
    else process.env.BROWSER_CDP_URL = previous;
  });
  const cardCount = () => opened ? reviews.length : options.overviewCount || 0;
  const cards = {
    async count() { return cardCount(); },
    first: () => ({
      async waitFor() { if (!cardCount()) throw new Error('DUMMY_REVIEW_SECRET'); },
      async evaluate() { return { total: 100, atEnd: true, x: 10, y: 10 }; },
    }),
    nth: (index: number) => ({
      async getAttribute() { return reviews[index % reviews.length].review_id; },
      getByRole: () => ({ async count() { return 0; } }),
    }),
  };
  const page = {
    setDefaultTimeout() {},
    async goto() {},
    getByRole: (role: string) => {
      if (role === 'main') return { first: () => ({ async waitFor() {} }) };
      const entries = (options.entries || []).filter(entry => entry.role === role && (entry.availableAt || 0) <= now);
      return {
        async count() { return entries.length; },
        nth: (index: number) => ({
          async isVisible() { return entries[index].visible !== false; },
          async getAttribute() { return entries[index].label; },
          async innerText() { return entries[index].label; },
          async click() { clicked.push(entries[index].label); opened = true; },
        }),
      };
    },
    locator: (selector: string) => selector === 'body'
      ? { async innerText() { return options.body || ''; } } : cards,
    async evaluate() { return { place_name: 'テスト店舗', source_url: 'https://www.google.com/maps/test', displayed_total: reviews.length, reviews }; },
    mouse: { async move() {}, async wheel() {} },
    async waitForTimeout(ms: number) { now += ms; },
    async close() { closed.push('collection-page'); },
  } as unknown as Page;
  const loginPage = { async close() { closed.push('login-page'); } };
  const context = {
    async newPage() { return page; },
    pages: () => [loginPage, page],
    async close() { closed.push('default-context'); },
  };
  const browser = { contexts: () => [context], async close() { closed.push('disconnect'); } } as unknown as Browser;
  t.mock.method(chromium, 'connectOverCDP', async () => browser);
  return { page, clicked, closed, elapsed: () => now };
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
  for (const [body, message] of [
    ['Google マップの表示が制限されています。もっと見る', 'Googleマップで口コミの表示が制限されています。専用ブラウザーで表示内容を確認し、必要に応じてログインしてください。ログインしても取得できない場合があります。'],
    ['ログイン', '口コミ一覧が見つかりません。店舗ページの共有URLを確認してください。'],
  ]) {
    await t.test(body, async (fixture) => {
      const page = mockCollectionPage(fixture, { body });
      const output = await (await POST(collectRequest())).text();
      assert.doesNotMatch(output, /DUMMY_REVIEW_SECRET/);
      const events = output.trim().split('\n\n').map(line => JSON.parse(line.slice('data: '.length)));
      assert.deepEqual(events.at(-1), { type: 'error', message });
      assert.deepEqual(page.closed, ['collection-page', 'disconnect']);
      if (body === 'ログイン') assert.equal(page.elapsed(), 30000);
    });
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

test('遅れて現れる口コミタブを待ち、概要の少数口コミから一覧を開く', async (t) => {
  const fixture = mockCollectionPage(t, {
    overviewCount: 3,
    entries: [{ role: 'tab', label: 'クチコミ', availableAt: 2000 }],
  });
  const events: CollectionEvent[] = [];
  await collectReviews('https://www.google.com/maps/test', event => events.push(event), new AbortController().signal);
  assert.deepEqual(fixture.clicked, ['クチコミ']);
  assert.equal(events.at(-1)?.type, 'done');
  assert.deepEqual(fixture.closed, ['collection-page', 'disconnect']);
});

test('投稿ボタンと非表示タブを除外し、遅れて現れる口コミ件数ボタンを開く', async (t) => {
  const fixture = mockCollectionPage(t, {
    body: 'ログイン',
    entries: [
      { role: 'tab', label: 'Reviews', visible: false },
      { role: 'button', label: 'クチコミを書く' },
      { role: 'button', label: 'Write a review' },
      { role: 'button', label: '331 件のクチコミ', availableAt: 1500 },
    ],
  });
  const events: CollectionEvent[] = [];
  await collectReviews('https://www.google.com/maps/test', event => events.push(event), new AbortController().signal);
  assert.deepEqual(fixture.clicked, ['331 件のクチコミ']);
  assert.equal(events.at(-1)?.type, 'done');
  assert.deepEqual(fixture.closed, ['collection-page', 'disconnect']);
});

test('CDPのnewPage待ち中の取消でも専用ページだけ閉じてから切断する', async (t) => {
  const previous = process.env.BROWSER_CDP_URL;
  process.env.BROWSER_CDP_URL = 'http://browser.invalid';
  t.after(() => {
    if (previous === undefined) delete process.env.BROWSER_CDP_URL;
    else process.env.BROWSER_CDP_URL = previous;
  });
  const closed: string[] = [];
  let navigated = 0;
  let resolvePage!: (page: Page) => void;
  let notifyNewPage!: () => void;
  const newPageStarted = new Promise<void>(resolve => { notifyNewPage = resolve; });
  const newPage = new Promise<Page>(resolve => { resolvePage = resolve; });
  const page = { async goto() { navigated++; }, async close() { closed.push('collection-page'); } } as unknown as Page;
  const context = {
    newPage() { notifyNewPage(); return newPage; },
    async close() { closed.push('default-context'); },
  };
  const browser = { contexts: () => [context], async close() { closed.push('disconnect'); } } as unknown as Browser;
  t.mock.method(chromium, 'connectOverCDP', async () => browser);
  const abort = new AbortController();
  const collecting = collectReviews('https://www.google.com/maps/test', () => {}, abort.signal);
  await newPageStarted;
  abort.abort();
  resolvePage(page);
  await collecting;
  assert.equal(navigated, 0);
  assert.deepEqual(closed, ['collection-page', 'disconnect']);
});

test('実行中の取消では専用ページのclose完了を待ってからCDPを切断する', async (t) => {
  const fixture = mockCollectionPage(t, {});
  let notifyNavigation!: () => void;
  let rejectNavigation!: (error: Error) => void;
  let finishClose!: () => void;
  const navigationStarted = new Promise<void>(resolve => { notifyNavigation = resolve; });
  const pageClosed = new Promise<void>(resolve => { finishClose = resolve; });
  t.mock.method(fixture.page, 'goto', () => {
    notifyNavigation();
    return new Promise<null>((_resolve, reject) => { rejectNavigation = reject; });
  });
  t.mock.method(fixture.page, 'close', () => {
    fixture.closed.push('collection-page');
    rejectNavigation(new Error('DUMMY_REVIEW_SECRET'));
    return pageClosed;
  });
  const abort = new AbortController();
  const events: CollectionEvent[] = [];
  const collecting = collectReviews('https://www.google.com/maps/test', event => events.push(event), abort.signal);
  await navigationStarted;
  abort.abort();
  assert.deepEqual(fixture.closed, ['collection-page']);
  finishClose();
  await collecting;
  assert.deepEqual(fixture.closed, ['collection-page', 'disconnect']);
  assert.deepEqual(events.map(event => event.type), ['status']);
});

test('本文省略のフラグは保持し、verifiedは全件数確認として扱う', async (t) => {
  const fixture = mockCollectionPage(t, {
    entries: [{ role: 'tab', label: 'クチコミ' }],
    reviews: [{ ...row, text_may_be_truncated: true }],
  });
  const events: CollectionEvent[] = [];
  await collectReviews('https://www.google.com/maps/test', event => events.push(event), new AbortController().signal);
  const done = events.at(-1);
  assert.equal(done?.type, 'done');
  if (done?.type === 'done') {
    assert.equal(done.data.verified, true);
    assert.equal(done.data.reviews[0].text_may_be_truncated, true);
  }
  assert.deepEqual(fixture.closed, ['collection-page', 'disconnect']);
});
