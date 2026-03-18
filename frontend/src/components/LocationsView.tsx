import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Item, Location } from '../api';
import ItemCard from './ItemCard';

interface Props {
  onItemClick: (item: Item) => void;
}

export default function LocationsView({ onItemClick }: Props) {
  const [locations, setLocations] = useState<Location[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.locations().then((data) => {
      setLocations(data.locations);
      setLoading(false);
    }).catch(console.error);
  }, []);

  useEffect(() => {
    if (!selected) {
      setItems([]);
      return;
    }
    setLoading(true);
    api.locationItems(selected, 1, 50).then((data) => {
      setItems(data.items);
      setLoading(false);
    }).catch(console.error);
  }, [selected]);

  if (loading && locations.length === 0) {
    return <div className="empty-state">Loading locations...</div>;
  }

  return (
    <div>
      <div className="locations-grid">
        {locations.map((loc) => (
          <div
            key={loc.location_id}
            className={`location-card ${selected === loc.location_id ? 'active' : ''}`}
            onClick={() => setSelected(loc.location_id)}
          >
            <h3>{loc.label || loc.location_id}</h3>
            <span>{loc.item_count} items</span>
            {loc.notes && <p className="location-notes">{loc.notes}</p>}
          </div>
        ))}
      </div>

      {selected && (
        <>
          <h3 className="section-title">Items in {selected}</h3>
          {loading ? (
            <div className="empty-state">Loading...</div>
          ) : items.length === 0 ? (
            <div className="empty-state">No items in this location</div>
          ) : (
            <div className="grid">
              {items.map((item) => (
                <ItemCard key={item.item_id} item={item} onClick={onItemClick} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
