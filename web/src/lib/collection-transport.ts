const localCollectorUrl = 'http://127.0.0.1:38473';

export type CollectionSource = 'local' | 'cloud';
export type LocalCollectorHealth = { ready: true; version: string; busy: boolean };

export class LocalCollectorConnectionError extends Error {
  constructor(public readonly reason: 'timeout' | 'unreachable' | 'invalid-response', message: string) {
    super(message); this.name = 'LocalCollectorConnectionError';
  }
}

export async function checkLocalCollector(signal?: AbortSignal, { timeoutMs = 3000, throwOnFailure = false }: { timeoutMs?: number; throwOnFailure?: boolean } = {}): Promise<LocalCollectorHealth | null> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  const failure = (reason: LocalCollectorConnectionError['reason'], message: string) => {
    if (throwOnFailure) throw new LocalCollectorConnectionError(reason, message);
    return null;
  };
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch(`${localCollectorUrl}/health`, { cache: 'no-store', credentials: 'omit', signal: controller.signal });
    if (!response.ok) return failure('invalid-response', 'このMacの収集サービスが接続確認に応答できませんでした。収集サービスを起動し直してください。');
    const health: unknown = await response.json().catch(error => { if (controller.signal.aborted) throw error; return null; });
    if (!health || typeof health !== 'object'
      || !('ready' in health) || health.ready !== true
      || !('version' in health) || typeof health.version !== 'string'
      || !('busy' in health) || typeof health.busy !== 'boolean') return failure('invalid-response', 'このMacの収集サービスから正しい接続情報を受信できませんでした。収集サービスを起動し直してください。');
    return { ready: true, version: health.version, busy: health.busy };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof LocalCollectorConnectionError) throw error;
    return timedOut
      ? failure('timeout', 'このMacへの接続確認が時間切れになりました。ブラウザーの接続確認で「許可」を選び、「接続を再確認」を押してください。')
      : failure('unreachable', 'このMacに接続できません。収集サービスの起動と、このサイトのローカルネットワーク接続の許可を確認してください。');
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
}

export async function requestCollection(url: string, source: CollectionSource, signal: AbortSignal): Promise<Response> {
  try {
    return await fetch(source === 'local' ? `${localCollectorUrl}/collect` : '/api/collect', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }), credentials: 'omit', signal,
    });
  } catch (error) {
    if (signal.aborted) throw error;
    if (source === 'local') throw new LocalCollectorConnectionError('unreachable', 'このMacとの通信に失敗しました。収集サービスの起動と、このサイトのローカルネットワーク接続の許可を確認してください。');
    throw new Error('通信に失敗しました。時間をおいて再度お試しください。');
  }
}

export async function collectionResponseError(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  return body && typeof body === 'object' && 'error' in body && typeof body.error === 'string' && body.error.trim()
    ? body.error : '収集を開始できませんでした。時間をおいて再度お試しください。';
}

export function needsGoogleLogin(message: string): boolean {
  return /Google|ログイン/i.test(message) && /制限|ログイン|確認画面|captcha/i.test(message);
}
