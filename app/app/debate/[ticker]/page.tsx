import { getTickerData } from '../../../lib/state-parser';
import { TickerHeader } from '../../../components/TickerHeader';
import { DebateStream } from '../../../components/DebateStream';
import { LiveRefresh } from '../../../components/LiveRefresh';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function DebatePage({ params }: PageProps) {
  const { ticker: rawTicker } = await params;
  const ticker = rawTicker.toUpperCase();
  const data = getTickerData(ticker);

  return (
    <main>
      <LiveRefresh ticker={ticker} />
      <TickerHeader
        ticker={ticker}
        lastUpdated={data.lastUpdated}
        subtitle={`Bull/Bear debate — ${data.debateMessages.length} message(s)`}
      />
      <DebateStream messages={data.debateMessages} />
    </main>
  );
}
