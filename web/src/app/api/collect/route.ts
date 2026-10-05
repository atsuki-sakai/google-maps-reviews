// Retire the former web collector without starting a browser or handling a URL.
export async function POST() {
  return Response.json({ error: '口コミの収集はMac専用CLIから実行してください。' }, { status: 410 });
}
