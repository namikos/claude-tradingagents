import type { DebateMessage } from '../types/signals';

interface Props {
  messages: DebateMessage[];
}

export function DebateStream({ messages }: Props) {
  if (messages.length === 0) {
    return (
      <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-6 text-zinc-400">
        No debate messages yet.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      {messages.map((m, i) => {
        const isBull = m.speaker === 'BULL';
        return (
          <div
            key={i}
            className={`flex ${isBull ? 'justify-start' : 'justify-end'}`}
          >
            <div
              className={`max-w-[80%] rounded-md border p-4 ${
                isBull
                  ? 'border-emerald-900 bg-emerald-950/40 text-emerald-100'
                  : 'border-rose-900 bg-rose-950/40 text-rose-100'
              }`}
            >
              <div
                className={`mb-2 font-mono text-xs uppercase tracking-wider ${
                  isBull ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {m.speaker}
              </div>
              <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed">
                {m.body}
              </pre>
            </div>
          </div>
        );
      })}
    </div>
  );
}
