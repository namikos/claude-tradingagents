import Link from 'next/link';
import { listTickers } from '../lib/state-parser';

export const dynamic = 'force-dynamic';

export default function HomePage() {
  const tickers = listTickers();
  return (
    <main>
      <h1 className="font-mono text-3xl">Available tickers</h1>
      <p className="mt-2 text-zinc-400">
        Detected from <code className="font-mono text-zinc-300">../state/</code>.
        Trigger a new analysis from Claude Code with{' '}
        <code className="font-mono text-zinc-300">/analyze TICKER</code>.
      </p>
      {tickers.length === 0 ? (
        <div className="mt-8 rounded-md border border-zinc-800 bg-zinc-900/40 p-6 text-zinc-400">
          No state files found yet. Once an agent writes a{' '}
          <code className="font-mono text-zinc-300">{'{TICKER}_*.md'}</code> file
          to the state directory, it will appear here.
        </div>
      ) : (
        <ul className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {tickers.map((t) => (
            <li key={t}>
              <Link
                href={`/ticker/${t}`}
                className="block rounded-md border border-zinc-800 bg-zinc-900/40 p-4 font-mono text-lg hover:border-zinc-600 hover:bg-zinc-900"
              >
                {t}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
