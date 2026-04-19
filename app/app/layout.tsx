import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'TradingAgents Dashboard',
  description: 'Read-only view of the TradingAgents Substanz Edition state files.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0a0a0a] text-white antialiased">
        <div className="mx-auto max-w-6xl px-6 py-6">
          <header className="mb-8 flex items-center justify-between border-b border-zinc-800 pb-4">
            <a href="/" className="font-mono text-lg tracking-wide text-zinc-100">
              tradingagents
              <span className="ml-2 text-xs text-zinc-500">substanz edition</span>
            </a>
            <nav className="flex gap-4 text-sm text-zinc-400">
              <a className="hover:text-white" href="/">Tickers</a>
              <a className="hover:text-white" href="/compare">Compare</a>
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
