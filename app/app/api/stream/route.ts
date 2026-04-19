import path from 'node:path';
import chokidar from 'chokidar';
import { getStateDir } from '../../../lib/state-paths';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  const encoder = new TextEncoder();
  const stateDir = getStateDir();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const watcher = chokidar.watch(stateDir, {
        ignoreInitial: true,
        awaitWriteFinish: { stabilityThreshold: 200, pollInterval: 50 },
        ignored: (p: string) => p.includes(`${path.sep}cache${path.sep}`),
      });

      const send = (event: string, filePath: string) => {
        const filename = path.basename(filePath);
        const payload = JSON.stringify({ event, path: filename });
        try {
          controller.enqueue(encoder.encode(`data: ${payload}\n\n`));
        } catch {
          // controller closed
        }
      };

      watcher.on('all', (event, filePath) => {
        if (typeof filePath === 'string' && filePath.endsWith('.md')) {
          send(event, filePath);
        }
      });

      // Heartbeat every 25s so proxies don't kill the connection.
      const heartbeat = setInterval(() => {
        try {
          controller.enqueue(encoder.encode(`: ping\n\n`));
        } catch {
          clearInterval(heartbeat);
        }
      }, 25_000);

      // Send an initial hello so the client knows we're alive.
      try {
        controller.enqueue(
          encoder.encode(
            `data: ${JSON.stringify({ event: 'hello', path: '' })}\n\n`,
          ),
        );
      } catch {
        // ignore
      }

      // Cleanup when the consumer disconnects.
      const close = () => {
        clearInterval(heartbeat);
        watcher.close().catch(() => undefined);
        try {
          controller.close();
        } catch {
          // already closed
        }
      };

      // ReadableStream cancel is plumbed via the second arg to start().
      // We attach close to the controller so cancel() can find it.
      (controller as unknown as { __close?: () => void }).__close = close;
    },
    cancel() {
      const close = (this as unknown as { __close?: () => void }).__close;
      if (close) close();
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
