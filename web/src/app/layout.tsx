import type { Metadata } from 'next';
import { Manrope, Noto_Sans_JP } from 'next/font/google';
import './globals.css';

const japanese = Noto_Sans_JP({ variable: '--font-japanese', subsets: ['latin'], weight: ['400', '500', '600', '700', '800'], display: 'swap' });
const logo = Manrope({ variable: '--font-logo', subsets: ['latin'], display: 'swap' });
export const metadata: Metadata = { title: 'Review Port | Googleマップの口コミをCSVに', description: '店舗のGoogleマップURLから口コミを収集。本文・評価・投稿日をCSVに保存できます。' };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ja" className={`${japanese.variable} ${logo.variable}`}><body>{children}</body></html>;
}
