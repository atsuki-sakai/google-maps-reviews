import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { createServer as createNetServer } from 'node:net';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { collectReviews, PublicCollectionError } from '../src/lib/collector';
import { validateMapsUrl, type CollectionEvent } from '../src/lib/reviews';

export const COLLECTOR_PORT = 38473;
const origins = new Set(['https://google-maps-reviews.vercel.app', 'http://localhost:3000', 'http://localhost:3100']);
const safeError = '口コミの収集に失敗しました。専用Chromeの表示を確認して、再度お試しください。';

type Options = {
  collect?: typeof collectReviews;
  ready?: () => Promise<boolean>;
};

function reply(response: ServerResponse, status: number, value: unknown) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(value));
}

async function readUrl(request: IncomingMessage) {
  const chunks: Buffer[] = [];
  let length = 0;
  for await (const chunk of request) {
    const bytes = Buffer.from(chunk);
    length += bytes.length;
    if (length > 16384) throw new Error('URLを確認してください。');
    chunks.push(bytes);
  }
  let value: unknown;
  try { value = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new Error('URLを確認してください。'); }
  const url = (value as { url?: unknown } | null)?.url;
  if (typeof url !== 'string' || url.length > 8192) throw new Error('URLを確認してください。');
  return validateMapsUrl(url);
}

export function createCollectorServer({ collect = collectReviews, ready = async () => true }: Options = {}) {
  let busy = false;
  const server = createServer(async (request, response) => {
    const origin = request.headers.origin;
    if (!origin || !origins.has(origin)) {
      reply(response, 403, { error: 'この収集サービスはReview Portの画面から利用してください。' });
      return;
    }
    response.setHeader('Access-Control-Allow-Origin', origin);
    response.setHeader('Vary', 'Origin');
    if (request.method === 'OPTIONS') {
      response.writeHead(204, {
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Private-Network': 'true',
        'Access-Control-Max-Age': '600',
      });
      response.end();
      return;
    }
    if (request.url === '/health' && request.method === 'GET') {
      reply(response, 200, { ready: await ready().catch(() => false), version: '1.0.0', busy });
      return;
    }
    if (request.url !== '/collect' || request.method !== 'POST') {
      reply(response, 404, { error: 'この操作には対応していません。' });
      return;
    }
    let url: string;
    try { url = await readUrl(request); }
    catch (error) {
      reply(response, 400, { error: error instanceof Error ? error.message : 'URLを確認してください。' });
      return;
    }
    if (busy) {
      reply(response, 409, { error: 'このMacでは口コミを収集中です。完了するまでお待ちください。' });
      return;
    }
    busy = true;
    const abort = new AbortController();
    const cancel = () => abort.abort();
    response.on('close', cancel);
    const timeout = setTimeout(cancel, 280000);
    response.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Accel-Buffering': 'no',
    });
    response.flushHeaders();
    const emit = (event: CollectionEvent) => {
      if (!response.destroyed && !abort.signal.aborted) response.write(`data: ${JSON.stringify(event)}\n\n`);
    };
    try { await collect(url, emit, abort.signal); }
    catch (error) {
      if (!abort.signal.aborted) {
        if (error instanceof Error && !(error instanceof PublicCollectionError)) {
          // Record operation codes only; URLs, browser credentials and raw errors stay private.
          console.error(JSON.stringify({ kind: error.name,
            operation: error.message.match(/^[a-zA-Z.]+(?=:)/)?.[0],
            network: error.message.match(/net::ERR_[A-Z_]+/)?.[0],
            timeout: error.message.includes('Timeout'), closed: error.message.includes('closed') }));
        }
        emit({ type: 'error', message: error instanceof PublicCollectionError ? error.message : safeError });
      }
    } finally {
      clearTimeout(timeout);
      response.off('close', cancel);
      if (!response.destroyed) response.end();
      busy = false;
    }
  });
  return server;
}

async function freePort() {
  const server = createNetServer();
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('起動用ポートを準備できません。');
  await new Promise<void>(resolve => server.close(() => resolve()));
  return address.port;
}

async function main() {
  if (process.platform !== 'darwin') throw new Error('この起動コマンドはMac用です。');
  const profile = join(homedir(), 'Library', 'Application Support', 'Review Port', 'Browser');
  await mkdir(profile, { recursive: true, mode: 0o700 });
  const cdpPort = await freePort();
  const cdpUrl = `http://127.0.0.1:${cdpPort}`;
  process.env.BROWSER_CDP_URL = cdpUrl;
  const ready = async () => (await fetch(`${cdpUrl}/json/version`, { signal: AbortSignal.timeout(1500) })).ok;
  const server = createCollectorServer({ ready });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(COLLECTOR_PORT, '127.0.0.1', resolve);
  });
  const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
    `--user-data-dir=${profile}`, `--remote-debugging-port=${cdpPort}`, '--remote-debugging-address=127.0.0.1',
    '--no-first-run', '--no-default-browser-check', 'https://www.google.com/maps/?hl=ja',
  ], { stdio: 'ignore' });
  const stop = () => {
    server.close();
    chrome.kill('SIGTERM');
    setTimeout(() => process.exit(0), 1500).unref();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  chrome.once('error', () => {
    console.error('専用Chromeを起動できません。Google Chromeをインストールしてください。');
    stop();
  });
  chrome.once('exit', () => server.close(() => process.exit(0)));
  let connected = false;
  for (let attempt = 0; attempt < 30; attempt++) {
    if (await ready().catch(() => false)) { connected = true; break; }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  if (!connected) {
    console.error('専用Chromeへ接続できません。Review Port用Chromeを閉じて収集サービスを起動し直してください。');
    stop();
    return;
  }
  console.log('Review Portの収集サービスが起動しました。専用ChromeでGoogleにログインしてください。');
  console.log('公開サイトで初回のローカルネットワーク接続を許可すると、このMacで口コミを収集できます。');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => {
    console.error('収集サービスを起動できません。既に起動していないか、ChromeとNode.js 22を確認してください。');
    process.exitCode = 1;
  });
}
