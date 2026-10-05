const localCollectorUrl = 'http://127.0.0.1:38473';

export type CollectionSource = 'local' | 'cloud';
export type LocalCollectorHealth = { ready: true; version: string; busy: boolean };

export async function checkLocalCollector(signal?: AbortSignal, { timeoutMs = 3000 }: { timeoutMs?: number } = {}): Promise<LocalCollectorHealth | null> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timeout = setTimeout(abort, timeoutMs);
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch(`${localCollectorUrl}/health`, { cache: 'no-store', credentials: 'omit', signal: controller.signal });
    if (!response.ok) return null;
    const health: unknown = await response.json();
    if (!health || typeof health !== 'object'
      || !('ready' in health) || health.ready !== true
      || !('version' in health) || typeof health.version !== 'string'
      || !('busy' in health) || typeof health.busy !== 'boolean') return null;
    return { ready: true, version: health.version, busy: health.busy };
  } catch (error) {
    if (signal?.aborted) throw error;
    return null;
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
    throw new Error(source === 'local'
      ? 'このMacとの通信に失敗しました。収集サービスが起動しているか確認して、再度お試しください。'
      : '通信に失敗しました。時間をおいて再度お試しください。');
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
