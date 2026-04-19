import type { Signal } from '../types/signals';

interface Props {
  signal: Signal;
  confidence?: number;
  label?: string;
  className?: string;
}

const STYLES: Record<Signal, string> = {
  bullish: 'text-emerald-400 bg-emerald-950 border-emerald-900',
  bearish: 'text-rose-400 bg-rose-950 border-rose-900',
  neutral: 'text-zinc-400 bg-zinc-900 border-zinc-800',
};

export function SignalBadge({ signal, confidence, label, className }: Props) {
  const cls = STYLES[signal] ?? STYLES.neutral;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs uppercase tracking-wider ${cls} ${className ?? ''}`}
    >
      {label ? <span className="not-italic">{label}</span> : null}
      <span>{signal}</span>
      {typeof confidence === 'number' ? (
        <span className="text-[0.7rem] opacity-80">{confidence}%</span>
      ) : null}
    </span>
  );
}
