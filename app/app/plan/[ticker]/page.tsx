import { getTickerData } from '../../../lib/state-parser';
import { TickerHeader } from '../../../components/TickerHeader';
import { PlanCard } from '../../../components/PlanCard';
import { LiveRefresh } from '../../../components/LiveRefresh';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function PlanPage({ params }: PageProps) {
  const { ticker: rawTicker } = await params;
  const ticker = rawTicker.toUpperCase();
  const data = getTickerData(ticker);

  return (
    <main>
      <LiveRefresh ticker={ticker} />
      <TickerHeader
        ticker={ticker}
        lastUpdated={data.lastUpdated}
        subtitle="Trader plan and risk-manager verdict"
      />
      <PlanCard plan={data.plan} decision={data.decision} />
    </main>
  );
}
