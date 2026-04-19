import fs from 'node:fs';
import path from 'node:path';
import { getStateDir, stateFile } from './state-paths';
import type {
  AnalystSignal,
  AnySignal,
  DebateMessage,
  PersonaSignal,
  TickerSnapshot,
} from '../types/signals';
import { ANALYST_SLUGS } from '../types/signals';

const FENCED_JSON_RE = /```json\s*([\s\S]*?)```/gi;

/**
 * Find the LAST fenced ```json``` block in a markdown file and JSON.parse it.
 * Returns null if no valid block is found.
 */
export function parseSignalFromMarkdown(content: string): AnySignal | null {
  if (!content) return null;
  const matches = [...content.matchAll(FENCED_JSON_RE)];
  if (matches.length === 0) return null;
  // Walk from the back so we get the LAST valid JSON block.
  for (let i = matches.length - 1; i >= 0; i--) {
    const raw = matches[i][1].trim();
    try {
      const parsed = JSON.parse(raw) as AnySignal;
      if (parsed && typeof parsed === 'object') return parsed;
    } catch {
      // try the next-most-recent block
    }
  }
  return null;
}

/** Lists unique uppercase ticker prefixes from the state directory. */
export function listTickers(): string[] {
  const dir = getStateDir();
  if (!fs.existsSync(dir)) return [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const tickers = new Set<string>();
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    if (!entry.name.endsWith('.md')) continue;
    const m = entry.name.match(/^([A-Z][A-Z0-9.\-]*)_/);
    if (m) tickers.add(m[1]);
  }
  return [...tickers].sort();
}

/** Files in the state directory whose name matches `{TICKER}_*.md`. */
function listTickerFiles(ticker: string): string[] {
  const dir = getStateDir();
  if (!fs.existsSync(dir)) return [];
  const prefix = `${ticker}_`;
  return fs
    .readdirSync(dir)
    .filter((name) => name.startsWith(prefix) && name.endsWith('.md'));
}

function readIfExists(file: string): string | undefined {
  const p = stateFile(file);
  if (!fs.existsSync(p)) return undefined;
  try {
    return fs.readFileSync(p, 'utf-8');
  } catch {
    return undefined;
  }
}

function mostRecentMtime(files: string[]): string | undefined {
  let best = 0;
  for (const f of files) {
    try {
      const stat = fs.statSync(stateFile(f));
      if (stat.mtimeMs > best) best = stat.mtimeMs;
    } catch {
      // ignore
    }
  }
  return best ? new Date(best).toISOString() : undefined;
}

/** Parse a debate transcript into a series of `## BULL` / `## BEAR` blocks. */
export function parseDebate(content: string): DebateMessage[] {
  if (!content) return [];
  const messages: DebateMessage[] = [];
  // Split on H2 headers that read BULL or BEAR (case-insensitive).
  const re = /^##\s+(BULL|BEAR)\b.*$/gim;
  const indices: { speaker: 'BULL' | 'BEAR'; start: number; end: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    indices.push({
      speaker: m[1].toUpperCase() as 'BULL' | 'BEAR',
      start: m.index + m[0].length,
      end: -1,
    });
  }
  for (let i = 0; i < indices.length; i++) {
    indices[i].end = i + 1 < indices.length ? indices[i + 1].start - (indices[i + 1].speaker.length + 4) : content.length;
    const body = content.slice(indices[i].start, indices[i].end).trim();
    if (body) messages.push({ speaker: indices[i].speaker, body });
  }
  return messages;
}

/**
 * Reads every state file for a ticker and returns a fully-typed snapshot.
 * Missing files are simply omitted.
 */
export function getTickerData(ticker: string): TickerSnapshot {
  const files = listTickerFiles(ticker);

  const analysts: AnalystSignal[] = [];
  const personas: PersonaSignal[] = [];

  for (const slug of ANALYST_SLUGS) {
    const filename = `${ticker}_${slug}.md`;
    const content = readIfExists(filename);
    if (!content) continue;
    const sig = parseSignalFromMarkdown(content);
    if (sig) {
      analysts.push({
        agent: (sig.agent as string) || `${slug}-analyst`,
        signal: sig.signal,
        confidence: Number(sig.confidence ?? 0),
        horizon: sig.horizon as string | undefined,
        key_points: sig.key_points as string[] | undefined,
        key_risks: sig.key_risks as string[] | undefined,
      });
    }
  }

  for (const file of files) {
    const m = file.match(new RegExp(`^${ticker}_persona_(.+)\\.md$`));
    if (!m) continue;
    const personaName = m[1];
    const content = readIfExists(file);
    if (!content) continue;
    const sig = parseSignalFromMarkdown(content);
    if (sig) {
      personas.push({
        ...(sig as Record<string, unknown>),
        agent: (sig.agent as string) || `persona-${personaName}`,
        persona: ((sig as PersonaSignal).persona as string) || personaName,
        signal: sig.signal,
        confidence: Number(sig.confidence ?? 0),
      } as PersonaSignal);
    }
  }

  const debate = readIfExists(`${ticker}_debate.md`);
  const plan = readIfExists(`${ticker}_trader_plan.md`);
  const decision = readIfExists(`${ticker}_decision.md`);

  return {
    ticker,
    analysts,
    personas,
    debate,
    debateMessages: debate ? parseDebate(debate) : [],
    plan,
    decision,
    lastUpdated: mostRecentMtime(files),
  };
}

/**
 * Strip the trailing JSON code block (and an optional `FINAL TRANSACTION
 * PROPOSAL:` line) from a markdown file so the prose can be rendered cleanly.
 */
export function stripSignalFooter(markdown: string): string {
  if (!markdown) return '';
  let out = markdown.replace(/```json[\s\S]*?```\s*$/i, '').trim();
  out = out.replace(/^FINAL TRANSACTION PROPOSAL:.*$/im, '').trim();
  return out;
}

/** Resolve which ticker (if any) a watcher event filename refers to. */
export function tickerFromFilename(filename: string): string | null {
  if (!filename) return null;
  const name = path.basename(filename);
  const m = name.match(/^([A-Z][A-Z0-9.\-]*)_/);
  return m ? m[1] : null;
}
