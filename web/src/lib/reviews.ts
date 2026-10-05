export type Review = {
  review_id: string;
  author: string;
  rating: number | null;
  date_text: string;
  text: string;
  owner_reply: string;
  author_url: string;
  source_url?: string;
  text_may_be_truncated: boolean;
};

export type Collection = {
  place: string;
  sourceUrl: string;
  displayedTotal: number | null;
  reviews: Review[];
  verified: boolean;
  reason: string;
};

export type CollectionEvent =
  | { type: 'status'; message: string }
  | { type: 'progress'; data: Collection }
  | { type: 'done'; data: Collection }
  | { type: 'error'; message: string };

export function validateMapsUrl(value: string): string {
  let url: URL;
  try { url = new URL(value.trim()); } catch { throw new Error('Googleマップの店舗URLを貼り付けてください。'); }
  const host = url.hostname.toLowerCase();
  const valid = host === 'maps.app.goo.gl'
    || (host === 'goo.gl' && url.pathname.startsWith('/maps'))
    || (['google.com', 'www.google.com', 'maps.google.com', 'google.co.jp', 'www.google.co.jp', 'maps.google.co.jp'].includes(host)
      && (host.startsWith('maps.') || url.pathname.startsWith('/maps')));
  if (url.protocol !== 'https:' || !valid || url.username || url.password)
    throw new Error('GoogleマップのHTTPS店舗URLを指定してください。');
  return url.href;
}

export function mergeReviews(existing: Map<string, Review>, rows: Review[]) {
  for (const row of rows) {
    if (!row.review_id || !row.author || row.rating === null) continue;
    const old = existing.get(row.review_id);
    const next = { ...row };
    // Complete text outranks length; collapsed views can include extra labels.
    if (old?.text && (!next.text || (!old.text_may_be_truncated && next.text_may_be_truncated)
      || (old.text_may_be_truncated === next.text_may_be_truncated && old.text.length > next.text.length))) {
      next.text = old.text;
      next.text_may_be_truncated = old.text_may_be_truncated;
    }
    if (old && old.owner_reply.length > next.owner_reply.length) next.owner_reply = old.owner_reply;
    existing.set(row.review_id, next);
  }
}

export function isFullCoverage(rows: Review[], expected: number | null) {
  return expected !== null && expected > 0 && rows.length === expected
    && rows.every(r => !!r.review_id) && new Set(rows.map(r => r.review_id)).size === expected;
}

export function toCsv(data: Collection) {
  const columns: [keyof Review | 'place', string][] = [
    ['place', '店舗名'], ['author', '投稿者'], ['rating', '星評価'], ['date_text', '投稿日（画面表記）'],
    ['text', '口コミ本文'], ['owner_reply', '店舗側の返信'], ['review_id', '口コミID'],
    ['source_url', '店舗URL'], ['author_url', '投稿者URL'], ['text_may_be_truncated', '本文の省略あり'],
  ];
  const quote = (value: unknown) => {
    let text = String(value ?? '');
    if (/^\s*[=+\-@]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  };
  return '\uFEFF' + [columns.map(([, label]) => quote(label)).join(','),
    ...data.reviews.map(row => columns.map(([key]) => quote(key === 'place' ? data.place
      : key === 'source_url' ? data.sourceUrl : row[key])).join(','))].join('\r\n') + '\r\n';
}
