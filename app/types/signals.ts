export type Signal = 'bullish' | 'bearish' | 'neutral';

export type AnalystKind =
  | 'fundamentals-analyst'
  | 'technical-analyst'
  | 'news-analyst'
  | 'sentiment-analyst'
  | string;

/** Signal footer shape produced by the four analyst roles. */
export interface AnalystSignal {
  agent: AnalystKind;
  signal: Signal;
  confidence: number; // 0-100
  horizon?: string;
  key_points?: string[];
  key_risks?: string[];
  // Allow additional unknown keys without losing them.
  [key: string]: unknown;
}

/** Signal footer shape produced by persona files. */
export interface PersonaSignal extends AnalystSignal {
  persona: string;
  fair_value?: number | string;
  thesis_break_level?: number | string;
}

export type AnySignal = AnalystSignal | PersonaSignal;

export interface DebateMessage {
  speaker: 'BULL' | 'BEAR';
  body: string;
}

export interface TickerSnapshot {
  ticker: string;
  analysts: AnalystSignal[];
  personas: PersonaSignal[];
  debate?: string;
  debateMessages: DebateMessage[];
  plan?: string;
  decision?: string;
  /** ISO timestamp of the most recently modified file for this ticker. */
  lastUpdated?: string;
}

/** Canonical analyst slugs used to identify the four analyst roles. */
export const ANALYST_SLUGS = [
  'fundamentals',
  'technical',
  'news',
  'sentiment',
] as const;

export type AnalystSlug = (typeof ANALYST_SLUGS)[number];

/** The 13 personas the heatmap displays tiles for. Must match agents/personas/. */
export const PERSONAS: readonly string[] = [
  'buffett',
  'graham',
  'munger',
  'pabrai',
  'burry',
  'taleb',
  'ackman',
  'wood',
  'lynch',
  'fisher',
  'druckenmiller',
  'damodaran',
  'jhunjhunwala',
];
