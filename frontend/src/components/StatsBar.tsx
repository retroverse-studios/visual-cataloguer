import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Stats } from '../api';

export default function StatsBar() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch(console.error);
  }, []);

  if (!stats) return <div className="stats-bar">Loading...</div>;

  return (
    <div className="stats-bar">
      <span><strong>{stats.total_items}</strong> items</span>
      <span><strong>{stats.total_locations}</strong> locations</span>
      <span><strong>{stats.needs_review}</strong> need review</span>
      <span><strong>{stats.ebay_listed}</strong> listed</span>
    </div>
  );
}
