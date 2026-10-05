() => {
  // Only rendered DOM text and attributes; no internal API or application state.
  const rendered = el => el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const text = el => el ? el.innerText.trim() : '';
  const first = (root, selector) => Array.from(root.querySelectorAll(selector)).find(rendered);
  const cards = Array.from(document.querySelectorAll('[data-review-id]'))
    .filter(el => rendered(el) && !el.parentElement?.closest('[data-review-id]'));
  const rows = cards.map(card => {
    const rating = first(card, '[role="img"][aria-label*="星"], [role="img"][aria-label*="star"], .kvMYJc');
    const label = rating?.getAttribute('aria-label') || '';
    const number = label.match(/([1-5](?:[.,]\d+)?)\s*(?:つ星|星|stars?)/i)
      || label.match(/(?:星|rated)\s*([1-5](?:[.,]\d+)?)/i);
    const body = first(card, '.MyEned .wiI7pd, .MyEned, [data-review-text]');
    const owner = first(card, '.CDe7pd, [data-owner-response]');
    const response = owner ? first(owner, '.wiI7pd, [data-response-text]') : null;
    const links = Array.from(card.querySelectorAll('a[href]')).filter(rendered);
    const reviewLink = links.find(a => /(?:reviewid=|\/reviews\/)/i.test(a.href));
    const authorLink = links.find(a => /\/contrib\//.test(a.href));
    const author = first(card, '.d4r55, [data-review-author]');
    return {
      review_id: card.getAttribute('data-review-id') || '',
      author: text(author),
      rating: number ? Number(number[1].replace(',', '.')) : null,
      rating_label: label,
      date_text: text(first(card, '.rsqaWe, [data-review-date]')),
      text: text(body),
      owner_reply: text(response) || text(owner),
      review_url: reviewLink?.href || '',
      author_url: authorLink?.href || '',
      text_may_be_truncated: Array.from(card.querySelectorAll('button')).some(b =>
        rendered(b) && /^(もっと見る|全文を表示|More|See more|Read more)$/i.test(text(b))),
      raw_visible_text: text(card),
    };
  });
  const title = Array.from(document.querySelectorAll('h1')).find(rendered);
  const main = first(document, '[role="main"][aria-label]');
  const count = text(main).match(/([\d,]+)\s*件の(?:クチコミ|口コミ)/)
    || text(main).match(/([\d,]+)\s+reviews\b/i);
  return { place_name: text(title) || main?.getAttribute('aria-label') || '',
    source_url: location.href, displayed_total: count ? Number(count[1].replaceAll(',', '')) : null,
    reviews: rows };
}
