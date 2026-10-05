import assert from 'node:assert/strict';
import test from 'node:test';
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
