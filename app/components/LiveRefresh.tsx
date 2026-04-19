'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

interface Props {
  ticker: string;
}

/**
 * Subscribes to the SSE stream from /api/stream and triggers
 * router.refresh() whenever a state file matching this ticker changes.
 */
export function LiveRefresh({ ticker }: Props) {
  const router = useRouter();
  useEffect(() => {
    const es = new EventSource('/api/stream');
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as { event: string; path?: string };
        if (data.path && data.path.toUpperCase().startsWith(`${ticker.toUpperCase()}_`)) {
          router.refresh();
        }
      } catch {
        // ignore
      }
    };
    es.onerror = () => {
      // Let the browser reconnect automatically.
    };
    return () => es.close();
  }, [router, ticker]);
  return null;
}
