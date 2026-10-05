import { chromium as playwright, type Browser, type Page } from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { extractorSource } from './extractor';
import { isFullCoverage, mergeReviews, type Collection, type CollectionEvent, type Review } from './reviews';

const cardsSelector = '[data-review-id]:not([data-review-id] [data-review-id])';
type Extracted = { place_name: string; source_url: string; displayed_total: number | null; reviews: Review[] };

export class PublicCollectionError extends Error {}

async function checkMapsRestriction(page: Page) {
  const body = await page.locator('body').innerText({ timeout: 1000 }).catch(() => '');
  if (/captcha|通常と異なるトラフィック|unusual traffic|Google\s*マップの表示が制限|Google\s*Maps[^\n]{0,80}(restricted|limited)/i.test(body))
    throw new PublicCollectionError('Googleマップで口コミの表示が制限されています。専用ブラウザーで表示内容を確認し、必要に応じてログインしてください。ログインしても取得できない場合があります。');
}

export async function prepareReviews(page: Page, isCancelled: () => boolean) {
  const deadline = Date.now() + 30000;
  const cards = page.locator(cardsSelector);
  const sort = page.getByRole('button', { name: /並べ替え|sort/i }).first();
  while (!isCancelled() && Date.now() < deadline) {
    for (const role of ['tab', 'button'] as const) {
      const candidates = page.getByRole(role, { name: /クチコミ|口コミ|レビュー|reviews?/i });
      for (let i = 0; i < Math.min(await candidates.count(), 8) && Date.now() < deadline; i++) {
        if (isCancelled()) return;
        const candidate = candidates.nth(i);
        try {
          if (!await candidate.isVisible()) continue;
          const label = (await candidate.getAttribute('aria-label', { timeout: 500 }) || '')
            + ' ' + await candidate.innerText({ timeout: 500 });
          if (/書く|投稿|追加|write|add\s+(a\s+)?review|leave\s+(a\s+)?review/i.test(label)) continue;
          if (isCancelled()) return;
          await candidate.click({ timeout: Math.min(3000, Math.max(1, deadline - Date.now())) });
          // The overview also contains preview review cards. Wait for the full
          // review panel's visible sort control before accepting those cards.
          await sort.waitFor({ state: 'visible', timeout: Math.min(8000, Math.max(1, deadline - Date.now())) });
          await cards.first().waitFor({ state: 'visible', timeout: Math.min(8000, Math.max(1, deadline - Date.now())) });
          return;
        } catch { /* Another visible review entry may still become available. */ }
      }
    }
    if (!await cards.count()) await checkMapsRestriction(page);
    await page.waitForTimeout(Math.min(500, Math.max(0, deadline - Date.now())));
  }
  if (isCancelled() || (await sort.isVisible() && await cards.count())) return;
  await checkMapsRestriction(page);
  throw new PublicCollectionError('口コミ一覧が見つかりません。店舗ページの共有URLを確認してください。');
}

export async function collectReviews(url: string, emit: (event: CollectionEvent) => void, signal: AbortSignal, timeoutMs = 300000) {
  let browser: Browser | undefined;
  let ownedPage: Page | undefined;
  let closingPage: Promise<void> | undefined;
  const closeOwnedPage = () => {
    if (ownedPage && !closingPage) closingPage = ownedPage.close().catch(() => {});
    return closingPage;
  };
  const cdpUrl = process.env.BROWSER_CDP_URL;
  const rows = new Map<string, Review>();
  let result: Collection = { place: '', sourceUrl: url, displayedTotal: null, reviews: [], verified: false, reason: '' };
  let cancelled = signal.aborted;
  const abort = () => { cancelled = true; void closeOwnedPage(); };
  signal.addEventListener('abort', abort, { once: true });
  try {
    if (cancelled) throw new PublicCollectionError('収集を中止しました。');
    emit({ type: 'status', message: 'Googleマップの店舗ページを開いています。' });
    if (cdpUrl) {
      browser = await playwright.connectOverCDP(cdpUrl, { timeout: 25000 });
    } else if (process.platform === 'linux') {
      browser = await playwright.launch({ executablePath: await chromium.executablePath(), args: chromium.args });
    } else {
      browser = await playwright.launch({ channel: 'chrome', headless: true });
    }
    if (cancelled) return;
    const context = (cdpUrl && browser.contexts()[0])
      || await browser.newContext({ locale: 'ja-JP', viewport: { width: 1280, height: 900 } });
    if (cancelled) return;
    ownedPage = await context.newPage();
    if (cancelled) return;
    const page = ownedPage;
    page.setDefaultTimeout(8000);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    try { await page.getByRole('main').first().waitFor({ state: 'visible', timeout: 30000 }); }
    catch (error) { await checkMapsRestriction(page); throw error; }
    await prepareReviews(page, () => cancelled);
    if (cancelled) return;
    emit({ type: 'status', message: '口コミを読み込み、本文の省略を展開しています。' });
    const started = Date.now();
    const expanded = new Set<string>();
    let stalled = 0;
    while (!cancelled && Date.now() - started < timeoutMs) {
      const before = rows.size;
      const cards = page.locator(cardsSelector);
      // Read IDs in one browser call. Revisiting every old card through CDP on
      // every page used most of the time budget on large review lists.
      const candidates = await cards.evaluateAll(elements => elements.map((card, index) => ({
        id: card.getAttribute('data-review-id'), index,
      })));
      for (const { id, index } of candidates) {
        if (!id || expanded.has(id)) continue;
        const card = cards.nth(index);
        const more = card.getByRole('button', { name: /^(もっと見る|全文を表示|More|See more|Read more)$/i });
        if (await more.count()) {
          try { await more.first().click({ timeout: 2500 }); } catch { /* A remaining button is reported in the exported row. */ }
        }
        expanded.add(id);
      }
      const data = await page.evaluate('(' + extractorSource + ')()') as Extracted;
      mergeReviews(rows, data.reviews);
      if (data.reviews.length && !rows.size) throw new PublicCollectionError('口コミの投稿者または評価を読み取れません。表示形式の対応が必要です。');
      result = { place: data.place_name, sourceUrl: data.source_url, displayedTotal: data.displayed_total ?? result.displayedTotal,
        reviews: [...rows.values()], verified: false, reason: '' };
      emit({ type: 'progress', data: result });
      if (isFullCoverage(result.reviews, result.displayedTotal)) {
        result.reason = '画面の総件数と重複なしの保存件数が一致したため終了しました。';
        break;
      }
      const state = await page.locator(cardsSelector).first().evaluate(card => {
        for (let el = card.parentElement; el; el = el.parentElement) {
          const rect = el.getBoundingClientRect();
          if (/(auto|scroll)/.test(getComputedStyle(el).overflowY) && el.clientHeight > 0 && rect.width > 0)
            return { total: el.scrollHeight, height: el.clientHeight,
              atEnd: el.scrollTop + el.clientHeight >= el.scrollHeight - 8,
              x: Math.max(1, Math.min(innerWidth - 1, rect.x + rect.width / 2)),
              y: Math.max(1, Math.min(innerHeight - 1, rect.y + rect.height / 2)) };
        }
        return null;
      });
      if (!state) throw new PublicCollectionError('口コミ一覧のスクロール領域を確認できません。');
      stalled = before === rows.size && state.atEnd ? stalled + 1 : 0;
      // The end of the currently loaded DOM is not the end of all reviews.
      // When a known total is still missing, retry until the collection deadline.
      if (stalled >= 8 && result.displayedTotal === null) {
        result.reason = '画面の総件数が不明で追加読み込みがないため停止（全件取得は未確認）'; break;
      }
      await page.mouse.move(state.x, state.y);
      if (stalled > 0 && stalled % 3 === 0) {
        emit({ type: 'status', message: '追加読み込みを待ち、口コミ一覧を再スクロールしています。' });
        await page.mouse.wheel(0, -state.height);
        await page.waitForTimeout(500);
      }
      await page.mouse.wheel(0, state.total);
      await page.waitForTimeout(1600);
    }
    result.reason ||= cancelled ? '収集を中止しました。' : '収集の制限時間に到達しました。取得分を保存できます。';
    result.verified = !cancelled && isFullCoverage(result.reviews, result.displayedTotal);
    if (!result.reviews.length) throw new PublicCollectionError('口コミを取得できませんでした。');
    emit({ type: 'done', data: result });
  } catch (error) {
    if (cancelled) return;
    if (rows.size) emit({ type: 'done', data: { ...result, verified: false, reason: '途中で停止しました。取得済みの口コミを保存できます。' } });
    else throw error;
  } finally {
    signal.removeEventListener('abort', abort);
    await closeOwnedPage();
    await browser?.close().catch(() => {});
  }
}
