interface Props {
  plan?: string;
  decision?: string;
}

function extractFinalProposal(text?: string): string | null {
  if (!text) return null;
  const m = text.match(/FINAL TRANSACTION PROPOSAL:\s*\*?\*?(BUY|HOLD|SELL)\*?\*?/i);
  return m ? m[1].toUpperCase() : null;
}

const PROPOSAL_STYLES: Record<string, string> = {
  BUY: 'border-emerald-900 bg-emerald-950 text-emerald-300',
  SELL: 'border-rose-900 bg-rose-950 text-rose-300',
  HOLD: 'border-amber-900 bg-amber-950 text-amber-300',
};

export function PlanCard({ plan, decision }: Props) {
  const proposal = extractFinalProposal(decision) ?? extractFinalProposal(plan);
  return (
    <div className="flex flex-col gap-6">
      {proposal ? (
        <div
          className={`flex items-center justify-between rounded-md border px-4 py-3 font-mono text-sm uppercase tracking-wider ${
            PROPOSAL_STYLES[proposal] ?? 'border-zinc-800 bg-zinc-900 text-zinc-300'
          }`}
        >
          <span>final transaction proposal</span>
          <span className="text-lg">{proposal}</span>
        </div>
      ) : null}
      <section>
        <h2 className="mb-2 font-mono text-sm uppercase tracking-wider text-zinc-400">
          Trader plan
        </h2>
        {plan ? (
          <pre className="whitespace-pre-wrap break-words rounded-md border border-zinc-800 bg-zinc-900/40 p-4 font-sans text-sm leading-relaxed text-zinc-200">
            {plan}
          </pre>
        ) : (
          <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4 text-zinc-500">
            No trader plan written yet.
          </div>
        )}
      </section>
      <section>
        <h2 className="mb-2 font-mono text-sm uppercase tracking-wider text-zinc-400">
          Risk verdict / final decision
        </h2>
        {decision ? (
          <pre className="whitespace-pre-wrap break-words rounded-md border border-zinc-800 bg-zinc-900/40 p-4 font-sans text-sm leading-relaxed text-zinc-200">
            {decision}
          </pre>
        ) : (
          <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4 text-zinc-500">
            Awaiting risk manager approval.
          </div>
        )}
      </section>
    </div>
  );
}
