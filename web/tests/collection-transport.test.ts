import assert from 'node:assert/strict';
import test from 'node:test';
import { checkLocalCollector, collectionResponseError, LocalCollectorConnectionError, requestCollection } from '../src/lib/collection-transport';

test('manual connection waits for permission beyond the default timeout', async t => {
  t.mock.method(globalThis, 'fetch', (_url: RequestInfo | URL, options?: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(Response.json({ ready: true, version: '1.0.0', busy: false })), 3200);
    options?.signal?.addEventListener('abort', () => {
      clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  }));
  assert.equal(await checkLocalCollector(), null);
  assert.deepEqual(await checkLocalCollector(undefined, { timeoutMs: 30000, throwOnFailure: true }), { ready: true, version: '1.0.0', busy: false });
});

test('a denied or unavailable connection gives an actionable local error', async t => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  assert.equal(await checkLocalCollector(), null);
  await assert.rejects(checkLocalCollector(undefined, { throwOnFailure: true }), error => {
    assert.ok(error instanceof LocalCollectorConnectionError);
    assert.equal(error.reason, 'unreachable');
    assert.match(error.message, /収集サービスの起動/);
    assert.match(error.message, /ローカルネットワーク接続の許可/);
    return true;
  });
});

test('connection timeout and user cancellation remain distinct', async t => {
  t.mock.method(globalThis, 'fetch', (_url: RequestInfo | URL, options?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  }));
  await assert.rejects(checkLocalCollector(undefined, { timeoutMs: 20, throwOnFailure: true }), error => {
    assert.ok(error instanceof LocalCollectorConnectionError);
    assert.equal(error.reason, 'timeout');
    return true;
  });
  const controller = new AbortController();
  const pending = checkLocalCollector(controller.signal, { timeoutMs: 30000, throwOnFailure: true });
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
});

test('a different or unhealthy local service asks for restart', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 500 }));
  for (const response of [new Response('', { status: 500 }), Response.json({ ready: false }), new Response('not JSON')]) {
    fetch.mock.mockImplementation(async () => response);
    await assert.rejects(checkLocalCollector(undefined, { throwOnFailure: true }), error => {
      assert.ok(error instanceof LocalCollectorConnectionError);
      assert.equal(error.reason, 'invalid-response');
      assert.match(error.message, /起動し直して/);
      return true;
    });
  }
});

test('a failed local collection never sends a request to the cloud', async t => {
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: RequestInfo | URL, options?: RequestInit) => {
    requests.push(String(url));
    assert.equal(options?.credentials, 'omit');
    throw new TypeError('Failed to fetch');
  });
  await assert.rejects(requestCollection('https://maps.app.goo.gl/ymUqcEYw1642mgqH6', 'local', new AbortController().signal), LocalCollectorConnectionError);
  assert.deepEqual(requests, ['http://127.0.0.1:38473/collect']);
});

test('cloud collection runs only when its source is explicitly requested', async t => {
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: RequestInfo | URL, options?: RequestInit) => {
    requests.push(String(url));
    assert.deepEqual(JSON.parse(String(options?.body)), { url: 'https://maps.app.goo.gl/ymUqcEYw1642mgqH6' });
    return new Response('data: {}\n\n');
  });
  await requestCollection('https://maps.app.goo.gl/ymUqcEYw1642mgqH6', 'cloud', new AbortController().signal);
  assert.deepEqual(requests, ['/api/collect']);
});

test('empty and non-JSON error responses retain the Japanese fallback', async () => {
  const fallback = '収集を開始できませんでした。時間をおいて再度お試しください。';
  assert.equal(await collectionResponseError(new Response('', { status: 500 })), fallback);
  assert.equal(await collectionResponseError(new Response('<html>Error</html>', { status: 500 })), fallback);
  assert.equal(await collectionResponseError(Response.json({ error: 'Googleマップの表示を確認してください。' }, { status: 400 })), 'Googleマップの表示を確認してください。');
});
