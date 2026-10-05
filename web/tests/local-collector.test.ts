import assert from 'node:assert/strict';
import test from 'node:test';
import type { Server } from 'node:http';
import { createCollectorServer } from '../scripts/local-collector';
import { PublicCollectionError } from '../src/lib/collector';

const origin = 'https://google-maps-reviews.vercel.app';
const headers = { Origin: origin, 'Content-Type': 'application/json' };
const requestBody = JSON.stringify({ url: 'https://www.google.com/maps/place/Test' });

async function listen(server: Server) {
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  return `http://127.0.0.1:${address.port}`;
}

async function close(server: Server) {
  server.closeAllConnections();
  await new Promise<void>(resolve => server.close(() => resolve()));
}

test('ローカル収集は許可した画面だけから呼べ、ネットワーク許可のpreflightに応答する', async () => {
  const server = createCollectorServer();
  const endpoint = await listen(server);
  try {
    for (const value of [undefined, 'https://evil.example', 'https://google-maps-reviews.vercel.app.evil.example', 'null']) {
      const response = await fetch(`${endpoint}/health`, { headers: value ? { Origin: value } : {} });
      assert.equal(response.status, 403);
      assert.equal(response.headers.get('Access-Control-Allow-Origin'), null);
    }
    const preflight = await fetch(`${endpoint}/collect`, { method: 'OPTIONS', headers: { Origin: origin, 'Access-Control-Request-Private-Network': 'true' } });
    assert.equal(preflight.status, 204);
    assert.equal(preflight.headers.get('Access-Control-Allow-Origin'), origin);
    assert.equal(preflight.headers.get('Access-Control-Allow-Private-Network'), 'true');
    const health = await fetch(`${endpoint}/health`, { headers });
    assert.deepEqual(await health.json(), { ready: true, version: '1.0.0', busy: false });
  } finally { await close(server); }
});

test('不正URLと大きな本文を収集開始前に拒否する', async () => {
  let called = 0;
  const server = createCollectorServer({ collect: async () => { called++; } });
  const endpoint = await listen(server);
  try {
    for (const body of ['bad-json', JSON.stringify({ url: 'https://evil.example/maps' }), JSON.stringify({ url: 'x'.repeat(20000) })]) {
      const response = await fetch(`${endpoint}/collect`, { method: 'POST', headers, body });
      assert.equal(response.status, 400);
      assert.doesNotMatch(await response.text(), /SyntaxError|Unexpected|bad-json/);
    }
    assert.equal(called, 0);
  } finally { await close(server); }
});

test('取得イベントを渡し、生例外の秘密は返さず、表示用エラーは保持する', async () => {
  for (const error of [new Error('CDP DUMMY_SECRET'), new PublicCollectionError('専用Chromeで口コミ表示を確認してください。')]) {
    const server = createCollectorServer({ collect: async (_url, emit) => { emit({ type: 'status', message: '店舗を開いています。' }); throw error; } });
    const endpoint = await listen(server);
    try {
      const response = await fetch(`${endpoint}/collect`, { method: 'POST', headers, body: requestBody });
      const output = await response.text();
      assert.equal(response.status, 200);
      assert.match(output, /店舗を開いています/);
      assert.doesNotMatch(output, /DUMMY_SECRET|CDP/);
      if (error instanceof PublicCollectionError) assert.match(output, /専用Chromeで口コミ表示を確認/);
      else assert.match(output, /口コミの収集に失敗/);
      const health = await fetch(`${endpoint}/health`, { headers });
      assert.equal((await health.json()).busy, false);
    } finally { await close(server); }
  }
});

test('同時収集を拒否し、画面の中止をブラウザーへ伝えて次の収集を可能にする', async () => {
  let began!: () => void;
  const started = new Promise<void>(resolve => { began = resolve; });
  let cancelled!: () => void;
  const stopped = new Promise<void>(resolve => { cancelled = resolve; });
  const server = createCollectorServer({ collect: async (_url, emit, signal) => {
    emit({ type: 'status', message: '収集中' });
    began();
    await new Promise<void>(resolve => signal.addEventListener('abort', () => { cancelled(); resolve(); }, { once: true }));
  } });
  const endpoint = await listen(server);
  const abort = new AbortController();
  try {
    const response = await fetch(`${endpoint}/collect`, { method: 'POST', headers, body: requestBody, signal: abort.signal });
    await started;
    const other = await fetch(`${endpoint}/collect`, { method: 'POST', headers, body: requestBody });
    assert.equal(other.status, 409);
    assert.match(await other.text(), /収集中/);
    abort.abort();
    await response.body?.cancel().catch(() => {});
    await stopped;
    const health = await fetch(`${endpoint}/health`, { headers });
    assert.equal((await health.json()).busy, false);
  } finally { abort.abort(); await close(server); }
});
