import { spawnSync } from 'node:child_process';
import { mkdir, writeFile, unlink } from 'node:fs/promises';
import { homedir, userInfo } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

if (process.platform !== 'darwin') throw new Error('この設定コマンドはMac用です。');
const web = resolve(fileURLToPath(new URL('..', import.meta.url)));
const label = 'app.review-port.collector';
const domain = `gui/${userInfo().uid}`;
const agentFile = join(homedir(), 'Library', 'LaunchAgents', `${label}.plist`);
const logs = join(homedir(), 'Library', 'Logs', 'Review Port');
const command = process.argv[2] || 'install';
const ctl = (...args) => spawnSync('launchctl', args, { stdio: 'ignore' }).status;

if (command === 'stop' || command === 'uninstall') {
  ctl('bootout', `${domain}/${label}`);
  if (command === 'uninstall') await unlink(agentFile).catch(() => {});
  console.log('収集サービスを停止しました。Googleのログインは専用Chromeに保持されます。');
} else if (command === 'install' || command === 'start') {
  await mkdir(join(homedir(), 'Library', 'LaunchAgents'), { recursive: true });
  await mkdir(logs, { recursive: true, mode: 0o700 });
  const xml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const args = [process.execPath, join(web, 'node_modules', 'tsx', 'dist', 'cli.mjs'), join(web, 'scripts', 'local-collector.ts')];
  await writeFile(agentFile, `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array>${args.map(arg => `<string>${xml(arg)}</string>`).join('')}</array>
<key>WorkingDirectory</key><string>${xml(web)}</string>
<key>RunAtLoad</key><true/>
<key>ThrottleInterval</key><integer>30</integer>
<key>StandardOutPath</key><string>${xml(join(logs, 'collector.log'))}</string>
<key>StandardErrorPath</key><string>${xml(join(logs, 'collector-error.log'))}</string>
</dict></plist>
`, { mode: 0o600 });
  // bootout returns before the old service and Chrome finish shutting down.
  if (ctl('bootout', `${domain}/${label}`) === 0) await new Promise(resolve => setTimeout(resolve, 1500));
  let status;
  for (let attempt = 0; attempt < 12; attempt++) {
    status = ctl('bootstrap', domain, agentFile);
    if (status === 0) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  if (status !== 0) throw new Error('自動起動を設定できませんでした。npm run collectorで起動できます。');
  let ready = false;
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      const response = await fetch('http://127.0.0.1:38473/health', {
        headers: { Origin: 'https://google-maps-reviews.vercel.app' }, signal: AbortSignal.timeout(1000),
      });
      if (response.ok && (await response.json()).ready === true) { ready = true; break; }
    } catch { /* The service may still be starting. */ }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  if (!ready) throw new Error('専用Chromeを起動できませんでした。Review Port用Chromeを閉じてから、もう一度起動してください。');
  console.log('収集サービスを設定しました。次回のMacログイン時にも自動起動します。');
  console.log('収集はターミナルで google-maps-reviews "店舗の共有URL" --all を実行してください。');
} else {
  throw new Error('install / start / stop / uninstallを指定してください。');
}
