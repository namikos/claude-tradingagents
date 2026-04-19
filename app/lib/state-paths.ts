import path from 'node:path';

/**
 * Resolves the absolute path to the parent project's state directory.
 * The Next.js app lives at <project>/app, so state is one level up.
 */
export function getStateDir(): string {
  return path.resolve(process.cwd(), '..', 'state');
}

/** Returns the absolute path for a given filename inside the state dir. */
export function stateFile(filename: string): string {
  return path.join(getStateDir(), filename);
}
