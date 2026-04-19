interface Props {
  ticker: string;
  lastUpdated?: string;
  subtitle?: string;
}

export function TickerHeader({ ticker, lastUpdated, subtitle }: Props) {
  return (
    <div className="mb-6 flex flex-col gap-1 border-b border-zinc-800 pb-4">
      <div className="flex items-center justify-between">
        <h1 className="font-mono text-4xl tracking-wide">{ticker}</h1>
        {lastUpdated ? (
          <span className="font-mono text-xs text-zinc-500">
            updated {new Date(lastUpdated).toLocaleString()}
          </span>
        ) : null}
      </div>
      {subtitle ? <p className="text-sm text-zinc-400">{subtitle}</p> : null}
    </div>
  );
}
