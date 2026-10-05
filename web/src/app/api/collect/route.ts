import { collectReviews } from '@/lib/collector';
import { validateMapsUrl, type CollectionEvent } from '@/lib/reviews';

export const runtime = 'nodejs';
export const maxDuration = 300;

export async function POST(request: Request) {
  const origin = request.headers.get('origin');
  if (origin) {
    const requestHost = request.headers.get('host') || new URL(request.url).host;
    try {
      if (new URL(origin).host !== requestHost) throw new Error('Origin mismatch');
    } catch { return Response.json({ error: '許可されていないリクエストです。' }, { status: 403 }); }
  }
  let url: string;
  try {
    const body = await request.json();
    if (typeof body.url !== 'string' || body.url.length > 8192) throw new Error('店舗URLを確認してください。');
    url = validateMapsUrl(body.url);
  } catch (error) { return Response.json({ error: error instanceof Error ? error.message : 'URLを確認してください。' }, { status: 400 }); }
  const encoder = new TextEncoder();
  const abort = new AbortController();
  request.signal.addEventListener('abort', () => abort.abort(), { once: true });
  const stream = new ReadableStream({
    async start(controller) {
      let closed = false;
      const emit = (event: CollectionEvent) => { if (!closed) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); };
      try { await collectReviews(url, emit, abort.signal); }
      catch (error) { emit({ type: 'error', message: error instanceof Error ? error.message : '収集を開始できませんでした。' }); }
      finally { closed = true; try { controller.close(); } catch { /* The client may have already closed the stream. */ } }
    },
    cancel() { abort.abort(); },
  });
  return new Response(stream, { headers: { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no' } });
}
