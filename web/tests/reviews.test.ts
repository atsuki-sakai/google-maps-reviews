import assert from 'node:assert/strict';
import test, { type TestContext } from 'node:test';
import { chromium, type Browser, type Page } from 'playwright-core';
import { POST } from '../src/app/api/collect/route';
import { collectReviews, PublicCollectionError } from '../src/lib/collector';
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

function mockCollectionPage(t: TestContext, options: {
  body?: string;
  entries?: { role: 'tab' | 'button'; label: string; availableAt?: number; visible?: boolean }[];
  overviewCount?: number;
  reviews?: Review[];
  displayedTotal?: number | null;
  atEnd?: boolean;
  loadAfterWheels?: { wheels: number; reviews: Review[] };
}) {
  let now = 0;
  let opened = false;
  const clicked: string[] = [];
  const closed: string[] = [];
  let wheels = 0;
  const reviews = () => options.loadAfterWheels && wheels >= options.loadAfterWheels.wheels
    ? options.loadAfterWheels.reviews : options.reviews || [row];
  t.mock.method(Date, 'now', () => now);
  const previous = process.env.BROWSER_CDP_URL;
  process.env.BROWSER_CDP_URL = 'http://browser.invalid';
  t.after(() => {
    if (previous === undefined) delete process.env.BROWSER_CDP_URL;
    else process.env.BROWSER_CDP_URL = previous;
  });
  const cardCount = () => opened ? reviews().length : options.overviewCount || 0;
  const cards = {
    async count() { return cardCount(); },
    async evaluateAll() { return reviews().map((review, index) => ({ id: review.review_id, index })); },
    first: () => ({
      async waitFor() { if (!cardCount()) throw new Error('DUMMY_REVIEW_SECRET'); },
      async evaluate() { return { total: 100, height: 40, atEnd: options.atEnd ?? true, x: 10, y: 10 }; },
    }),
    nth: (index: number) => ({
      async getAttribute() { return reviews()[index % reviews().length].review_id; },
      getByRole: () => ({ async count() { return 0; } }),
    }),
  };
  const page = {
    setDefaultTimeout() {},
    async goto() {},
    getByRole: (role: string, optionsForRole?: { name?: RegExp }) => {
      if (role === 'main') return { first: () => ({ async waitFor() {} }) };
      if (role === 'button' && optionsForRole?.name?.test('並べ替え')) {
        return { first: () => ({
          async isVisible() { return opened; },
          async waitFor({ timeout }: { timeout: number }) {
            if (!opened) { now += timeout; throw new Error('Review panel not open'); }
          },
        }) };
      }
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
    async evaluate() { return { place_name: 'テスト店舗', source_url: 'https://www.google.com/maps/test', displayed_total: options.displayedTotal === undefined ? reviews().length : options.displayedTotal, reviews: reviews() }; },
    mouse: { async move() {}, async wheel() { wheels++; } },
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

test('総件数に一致したら末尾に未到達でも追加スクロールせず完了する', async (t) => {
  const fixture = mockCollectionPage(t, {
    entries: [{ role: 'tab', label: '口コミ' }], atEnd: false,
  });
  const wheel = t.mock.method(fixture.page.mouse, 'wheel', async () => { throw new Error('完了後にスクロールしました'); });
  const events: CollectionEvent[] = [];
  await collectReviews('https://www.google.com/maps/test', event => events.push(event), new AbortController().signal);
  const done = events.at(-1);
  assert.equal(done?.type, 'done');
  if (done?.type !== 'done') assert.fail('完了イベントがありません');
  assert.equal(done.data.verified, true);
  assert.match(done.data.reason, /保存件数が一致/);
  assert.equal(wheel.mock.callCount(), 0);
  assert.equal(fixture.elapsed(), 0);
  assert.deepEqual(fixture.closed, ['collection-page', 'disconnect']);
});

test('総件数が不明なら停滞で未確認終了、未達なら指定時間まで回復を試す', async (t) => {
  for (const displayedTotal of [null, 2]) {
    await t.test(String(displayedTotal), async (fixtureTest) => {
      const fixture = mockCollectionPage(fixtureTest, {
        entries: [{ role: 'tab', label: '口コミ' }], displayedTotal,
      });
      const wheel = fixtureTest.mock.method(fixture.page.mouse, 'wheel', async () => {});
      const events: CollectionEvent[] = [];
      await collectReviews('https://www.google.com/maps/test', event => events.push(event), new AbortController().signal, 20000);
      const done = events.at(-1);
      assert.equal(done?.type, 'done');
      if (done?.type !== 'done') assert.fail('完了イベントがありません');
      assert.equal(done.data.verified, false);
      assert.match(done.data.reason, displayedTotal === null ? /総件数が不明/ : /制限時間/);
      assert.ok(events.some(event => event.type === 'status' && /再スクロール/.test(event.message)));
      assert.ok(wheel.mock.callCount() > 0);
    });
  }
});

test('末尾で5回以上止まった後の追加口コミも収集し、総件数一致で終了する', async (t) => {
  const fixture = mockCollectionPage(t, {
    entries: [{ role: 'tab', label: '口コミ' }], displayedTotal: 2,
    loadAfterWheels: { wheels: 9, reviews: [row, { ...row, review_id: 'rating-only', text: '' }] },
  });
  const wheel = t.mock.method(fixture.page.mouse, 'wheel', fixture.page.mouse.wheel);
  const events: CollectionEvent[] = [];
  await collectReviews('https://www.google.com/maps/test', event => events.push(event), new AbortController().signal);
  const done = events.at(-1);
  if (done?.type !== 'done') assert.fail('完了イベントがありません');
  assert.equal(done.data.verified, true);
  assert.equal(done.data.reviews.length, 2);
  assert.ok(wheel.mock.calls.some(call => call.arguments[1] < 0));
  assert.deepEqual(fixture.closed, ['collection-page', 'disconnect']);
});

test('旧Web APIは収集を始めずCLIへの案内を返す', async (t) => {
  const connect = t.mock.method(chromium, 'connectOverCDP', async () => { throw new Error('ブラウザーを起動しました'); });
  const response = await POST();
  assert.equal(response.status, 410);
  assert.deepEqual(await response.json(), { error: '口コミの収集はMac専用CLIから実行してください。' });
  assert.equal(connect.mock.callCount(), 0);
});

test('ローカル収集ではGoogleの表示制限と口コミURL確認を案内する', async (t) => {
  for (const [body, message] of [
    ['Google マップの表示が制限されています。もっと見る', 'Googleマップで口コミの表示が制限されています。専用ブラウザーで表示内容を確認し、必要に応じてログインしてください。ログインしても取得できない場合があります。'],
    ['ログイン', '口コミ一覧が見つかりません。店舗ページの共有URLを確認してください。'],
  ]) {
    await t.test(body, async (fixture) => {
      const page = mockCollectionPage(fixture, { body });
      await assert.rejects(collectReviews('https://www.google.com/maps/test', () => {}, new AbortController().signal), error => {
        assert.ok(error instanceof PublicCollectionError);
        assert.equal(error.message, message);
        return true;
      });
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
