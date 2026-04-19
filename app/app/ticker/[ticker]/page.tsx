import Link from 'next/link';
import { getTickerData } from '../../../lib/state-parser';
import { TickerHeader } from '../../../components/TickerHeader';
import { PersonaHeatmap } from '../../../components/PersonaHeatmap';
import { SignalBadge } from '../../../components/SignalBadge';
import { LiveRefresh } from '../../../components/LiveRefresh';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function TickerPage({ params }: PageProps) {
  const { ticker: rawTicker } = await params;
  const ticker = rawTicker.toUpperCase();
  const data = getTickerData(ticker);

  return (
    <main>
      <LiveRefresh ticker={ticker} />
      <TickerHeader
        ticker={ticker}
        lastUpdated={data.lastUpdated}
        subtitle={`${data.analysts.length} analyst report(s) • ${data.personas.length} persona signal(s)`}
      />

      <section>
        <h2 className="mb-3 font-mono text-sm uppercase tracking-wider text-zinc-400">
          Analyst signals
        </h2>
        {data.analysts.length === 0 ? (
          <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4 text-zinc-500">
            No analyst reports yet.
          </div>
        ) : (
          <div className="flex flex-wrap gap-3">
            {data.analysts.map((a) => (
              <SignalBadge
                key={a.agent}
                label={a.agent.replace(/-analyst$/, '')}
                signal={a.signal}
                confidence={a.confidence}
              />
            ))}
          </div>
        )}
      </section>

      <PersonaHeatmap personas={data.personas} />

      <nav className="mt-8 flex flex-wrap gap-3">
        <Link
          href={`/debate/${ticker}`}
          className="rounded-md border border-zinc-800 bg-zinc-900/40 px-4 py-2 font-mono text-sm hover:border-zinc-600 hover:bg-zinc-900"
        >
          Debate stream &rarr;
        </Link>
        <Link
          href={`/plan/${ticker}`}
          className="rounded-md border border-zinc-800 bg-zinc-900/40 px-4 py-2 font-mono text-sm hover:border-zinc-600 hover:bg-zinc-900"
        >
          Trade plan &amp; risk verdict &rarr;
        </Link>
        <Link
          href={`/backtest/${ticker}`}
          className="rounded-md border border-zinc-800 bg-zinc-900/40 px-4 py-2 font-mono text-sm hover:border-zinc-600 hover:bg-zinc-900"
        >
          Backtest &rarr;
        </Link>
      </nav>
    </main>
  );
}
