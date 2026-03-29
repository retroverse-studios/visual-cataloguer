import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import type { Item, PaginatedItems } from './api';
import StatsBar from './components/StatsBar';
import ItemCard from './components/ItemCard';
import ItemModal from './components/ItemModal';
import Pagination from './components/Pagination';
import LocationsView from './components/LocationsView';
import ImportWizard from './components/ImportWizard';
import SettingsModal from './components/SettingsModal';

type Tab = 'items' | 'locations';
type Filter = 'all' | 'unlisted' | 'review';

export default function App() {
  const [tab, setTab] = useState<Tab>('items');
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PaginatedItems | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [platformFilter, setPlatformFilter] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [showImport, setShowImport] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [isEmpty, setIsEmpty] = useState(false);
  const [version, setVersion] = useState('');

  const PER_PAGE = 24;

  useEffect(() => {
    api.platforms().then((d) => setPlatforms(d.platforms)).catch(() => {});
    api.stats().then(() => {}).catch(() => {});
    fetch('/api/health').then(r => r.json()).then(d => setVersion(d.version || '')).catch(() => {});
  }, []);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      let result: PaginatedItems;

      if (search) {
        const searchData = await api.search(search, {
          page,
          per_page: PER_PAGE,
          ...(platformFilter ? { platform: platformFilter } : {}),
        });
        result = { items: searchData.results, total: searchData.total, page: searchData.page, per_page: PER_PAGE };
      } else if (filter === 'unlisted') {
        result = await api.itemsUnlisted(page, PER_PAGE);
      } else {
        const params: Record<string, string | number | boolean> = { page, per_page: PER_PAGE };
        if (filter === 'review') params.needs_review = true;
        if (platformFilter) params.platform = platformFilter;
        result = await api.items(params);
      }

      setData(result);
      // Detect empty collection (no items, no search, no filters)
      if (!search && filter === 'all' && !platformFilter && result.total === 0) {
        setIsEmpty(true);
      } else {
        setIsEmpty(false);
      }
    } catch (e) {
      console.error('Failed to load items:', e);
    } finally {
      setLoading(false);
    }
  }, [search, filter, page, platformFilter]);

  useEffect(() => {
    if (tab === 'items') loadItems();
  }, [tab, loadItems, refreshKey]);

  const handleSearch = () => {
    setSearch(searchInput);
    setPage(1);
  };

  const handleFilterChange = (f: Filter) => {
    setFilter(f);
    setPage(1);
    setSearch('');
    setSearchInput('');
  };

  const handlePageChange = (p: number) => {
    setPage(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleItemSaved = () => {
    setSelectedItem(null);
    setRefreshKey((k) => k + 1);
  };

  return (
    <>
      <header>
        <div className="container">
          <div className="header-row">
            <h1>Visual Cataloguer <span className="version-label">v{version}</span></h1>
            <div className="header-actions">
              <button className="btn btn-primary btn-sm" onClick={() => setShowImport(true)}>
                + Import
              </button>
              <button className="btn btn-outline btn-sm" onClick={() => setShowSettings(true)}>
                Settings
              </button>
              <StatsBar key={refreshKey} />
            </div>
          </div>
        </div>
      </header>

      <main className="container">
        <div className="tabs">
          <button className={`tab ${tab === 'items' ? 'active' : ''}`} onClick={() => setTab('items')}>
            Items
          </button>
          <button className={`tab ${tab === 'locations' ? 'active' : ''}`} onClick={() => setTab('locations')}>
            Locations
          </button>
        </div>

        {tab === 'items' && (
          <>
            <div className="toolbar">
              <div className="search-box">
                <input
                  type="text"
                  placeholder="Search items..."
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                />
                <button onClick={handleSearch}>Search</button>
              </div>

              <div className="filter-row">
                <div className="filters">
                  {(['all', 'unlisted', 'review'] as Filter[]).map((f) => (
                    <button
                      key={f}
                      className={`filter-btn ${filter === f ? 'active' : ''}`}
                      onClick={() => handleFilterChange(f)}
                    >
                      {f === 'all' ? 'All' : f === 'unlisted' ? 'Unlisted' : 'Needs Review'}
                    </button>
                  ))}
                </div>

                {platforms.length > 0 && (
                  <select
                    className="platform-select"
                    value={platformFilter}
                    onChange={(e) => { setPlatformFilter(e.target.value); setPage(1); }}
                  >
                    <option value="">All Platforms</option>
                    {platforms.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            {loading ? (
              <div className="empty-state">Loading...</div>
            ) : isEmpty ? (
              <div className="onboarding">
                <div className="onboarding-icon">📦</div>
                <h2>Welcome to Visual Cataloguer</h2>
                <p>Import a folder of photos to start cataloguing your collection. Use QR code dividers to organise by location, or just import and sort later.</p>
                <button className="btn btn-primary" onClick={() => setShowImport(true)}>Import Your First Photos</button>
              </div>
            ) : !data || data.items.length === 0 ? (
              <div className="empty-state">No items found</div>
            ) : (
              <>
                <div className="results-count">{data.total} item{data.total !== 1 ? 's' : ''}</div>
                <div className="grid">
                  {data.items.map((item) => (
                    <ItemCard key={item.item_id} item={item} onClick={setSelectedItem} />
                  ))}
                </div>
                <Pagination
                  total={data.total}
                  page={data.page}
                  perPage={PER_PAGE}
                  onPageChange={handlePageChange}
                />
              </>
            )}
          </>
        )}

        {tab === 'locations' && <LocationsView onItemClick={setSelectedItem} />}
      </main>

      {selectedItem && (
        <ItemModal item={selectedItem} onClose={() => setSelectedItem(null)} onSaved={handleItemSaved} />
      )}

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}

      {showImport && (
        <ImportWizard
          onClose={() => setShowImport(false)}
          onComplete={() => setRefreshKey((k) => k + 1)}
        />
      )}
    </>
  );
}
