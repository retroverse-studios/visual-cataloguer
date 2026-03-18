import { api } from '../api';
import type { Item } from '../api';

interface Props {
  item: Item;
  onClick: (item: Item) => void;
}

const NO_IMAGE = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect fill='%23f1f5f9' width='100' height='100'/%3E%3Ctext x='50' y='50' text-anchor='middle' dy='.3em' fill='%2394a3b8' font-size='12'%3ENo Image%3C/text%3E%3C/svg%3E";

export default function ItemCard({ item, onClick }: Props) {
  const title = item.title_manual || item.title_guess || 'Unknown';
  const platform = item.platform_manual || item.platform_guess || '';

  return (
    <div className="card" onClick={() => onClick(item)}>
      <img
        className="card-img"
        src={api.thumbUrl(item.item_id)}
        alt={title}
        loading="lazy"
        onError={(e) => { (e.target as HTMLImageElement).src = NO_IMAGE; }}
      />
      <div className="card-body">
        <div className="card-title" title={title}>{title}</div>
        <div className="card-meta">
          <span>{platform}</span>
          <span>
            {item.ebay_listed && <span className="badge badge-listed">Listed</span>}
            {item.needs_review && <span className="badge badge-review">Review</span>}
          </span>
        </div>
        {item.title_confidence != null && (
          <div className="confidence-bar">
            <div className="confidence-fill" style={{ width: `${Math.round(item.title_confidence * 100)}%` }} />
          </div>
        )}
      </div>
    </div>
  );
}
