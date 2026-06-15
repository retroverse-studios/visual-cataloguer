import { useEffect, useState } from 'react';
import { api } from '../api';

/**
 * Shows a compact progress bar in the header when a background
 * auto-enhance job is running. Polls /api/auto-enhance-status.
 */
export default function EnhanceProgress() {
  const [status, setStatus] = useState<{
    running: boolean;
    phase: string;
    total: number;
    processed: number;
    enhanced: number;
    message: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const s = await api.autoEnhanceStatus();
        if (cancelled) return;
        setStatus(s);
        // Poll quickly while a job runs; back off when idle/finished so we're
        // not hammering the endpoint every few seconds for the app's lifetime.
        timer = setTimeout(poll, s.running ? 2000 : 10000);
      } catch {
        if (cancelled) return;
        timer = setTimeout(poll, 10000);
      }
    };

    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (!status || status.phase === 'idle') return null;

  const pct = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 0;
  const done = status.phase === 'complete' || status.phase === 'error';

  return (
    <div className={`enhance-progress ${done ? 'done' : ''}`}>
      {!done && (
        <div className="enhance-bar">
          <div className="enhance-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
      <span className="enhance-text">
        {status.phase === 'error'
          ? `Enhance failed: ${status.message}`
          : status.phase === 'complete'
            ? `Enhanced ${status.enhanced} items`
            : `Enhancing ${status.processed}/${status.total}`}
      </span>
    </div>
  );
}
