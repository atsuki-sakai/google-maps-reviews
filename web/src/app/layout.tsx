import type { Metadata } from 'next';
import { Manrope, Noto_Sans_JP } from 'next/font/google';
import './globals.css';

const japanese = Noto_Sans_JP({ variable: '--font-japanese', subsets: ['latin'], weight: ['400', '500', '600', '700', '800'], display: 'swap' });
const logo = Manrope({ variable: '--font-logo', subsets: ['latin'], display: 'swap' });
export const metadata: Metadata = { title: 'google-maps-reviews | Mac専用の口コミ収集CLI', description: 'MacのターミナルからGoogleマップの本文あり口コミだけをCSV・Excel・JSONに保存するOSS。セットアップと使い方を紹介します。' };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ja" className={`${japanese.variable} ${logo.variable}`}><body>{children}</body></html>;
}
