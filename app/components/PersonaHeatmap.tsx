import type { PersonaSignal, Signal } from '../types/signals';
import { PERSONAS } from '../types/signals';

interface Props {
  personas: PersonaSignal[];
}

const SIGNAL_BG: Record<Signal, string> = {
  bullish: 'border-emerald-900 bg-emerald-950/60 text-emerald-300',
  bearish: 'border-rose-900 bg-rose-950/60 text-rose-300',
  neutral: 'border-zinc-800 bg-zinc-900/60 text-zinc-400',
};

function tileSizeClass(confidence: number) {
  return confidence > 80 ? 'sm:col-span-2 sm:row-span-2 sm:min-h-[10rem]' : '';
}

function findPersona(personas: PersonaSignal[], name: string): PersonaSignal | undefined {
  return personas.find(
    (p) => (p.persona ?? '').toLowerCase() === name.toLowerCase(),
  );
}

export function PersonaHeatmap({ personas }: Props) {
  return (
    <section className="mt-6">
      <h2 className="mb-3 font-mono text-sm uppercase tracking-wider text-zinc-400">
        Persona heatmap
      </h2>
      <div className="grid auto-rows-[6rem] grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {PERSONAS.map((personaName) => {
          const sig = findPersona(personas, personaName);
          if (!sig) {
            return (
              <div
                key={personaName}
                className="flex flex-col justify-between rounded-md border border-dashed border-zinc-800 bg-zinc-950/40 p-3 text-zinc-600"
              >
                <span className="font-mono text-xs uppercase tracking-wider">
                  {personaName}
                </span>
                <span className="font-mono text-[0.7rem]">no data</span>
              </div>
            );
          }
          const cls = SIGNAL_BG[sig.signal] ?? SIGNAL_BG.neutral;
          const big = tileSizeClass(sig.confidence);
          return (
            <div
              key={personaName}
              className={`flex flex-col justify-between rounded-md border p-3 ${cls} ${big}`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs uppercase tracking-wider">
                  {personaName}
                </span>
                <span className="font-mono text-[0.7rem] uppercase opacity-80">
                  {sig.signal}
                </span>
              </div>
              <div className="flex items-end justify-between">
                <span className="font-mono text-2xl">{sig.confidence}</span>
                {sig.fair_value ? (
                  <span className="font-mono text-[0.7rem] opacity-80">
                    fv {String(sig.fair_value)}
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
