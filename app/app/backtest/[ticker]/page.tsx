interface PageProps {
  params: Promise<{ ticker: string }>;
}

export default async function Page({ params }: PageProps) {
  const { ticker } = await params;
  return (
    <main className="p-8">
      <h1 className="text-2xl font-mono">Backtest View</h1>
      <p className="mt-4 text-zinc-400">
        TODO: Render equity curve, drawdown plot, and trade log from state/{ticker}_backtest_*.md.
      </p>
    </main>
  );
}
