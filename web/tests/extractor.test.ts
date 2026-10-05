import assert from 'node:assert/strict';
import test from 'node:test';
import { chromium } from 'playwright-core';
import type { Review } from '../src/lib/reviews';
import { extractorSource } from '../src/lib/extractor';
import { prepareReviews } from '../src/lib/collector';

test('実ブラウザーのDOMから通常形式と宿泊施設形式を読み取る', async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<main role="main" aria-label="架空のテスト店舗"><p>3 件のクチコミ</p>
      <div data-review-id="normal"><div class="d4r55">通常形式の投稿者</div><span role="img" aria-label="4 つ星"></span><span class="rsqaWe">1 か月前</span><div class="MyEned"><span class="wiI7pd">通常形式の本文</span></div></div>
      <div data-review-id="hotel"><button data-href="https://www.google.com/maps/contrib/123/reviews"><div class="d4r55">宿泊形式の投稿者</div></button><span class="fzvQIb">5/5</span><span class="xRkPPb">2 年前（Google）</span><div class="MyEned"><span class="wiI7pd">宿泊形式の本文</span></div></div>
      <div data-review-id="rating-only"><div class="d4r55">評価のみの投稿者</div><span class="fzvQIb">1/5</span><span class="xRkPPb">3 年前（Google）</span></div>
      </main>`);
    const data = await page.evaluate('(' + extractorSource + ')()') as { reviews: Review[]; displayed_total: number };
    assert.deepEqual(data.reviews.map(r => r.rating), [4, 5, 1]);
    assert.equal(data.reviews[1].date_text, '2 年前（Google）');
    assert.equal(data.reviews[1].author_url, 'https://www.google.com/maps/contrib/123/reviews');
    assert.equal(data.reviews[2].text, '');
    assert.equal(data.displayed_total, 3);
  } finally { await browser.close(); }
});

test('一覧への切り替え中に残るプレビュー3件を全件一覧として扱わない', async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<button role="tab" id="reviews">クチコミ</button>
      <section id="cards">${Array.from({ length: 3 }, (_, i) => `<div data-review-id="preview-${i}">概要の口コミ</div>`).join('')}</section>
      <script>document.getElementById('reviews').onclick=()=>setTimeout(()=>{
        document.getElementById('cards').innerHTML='<button>並べ替え</button>'+
          Array.from({length:30},(_,i)=>'<div data-review-id="review-'+i+'">一覧の口コミ</div>').join('');
      },1500)</script>`);
    await prepareReviews(page, () => false);
    assert.equal(await page.getByRole('button', { name: '並べ替え' }).isVisible(), true);
    assert.equal(await page.locator('[data-review-id]').count(), 30);
  } finally { await browser.close(); }
});
