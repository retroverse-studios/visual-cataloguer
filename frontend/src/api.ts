const BASE = '/api';

export interface Stats {
  total_items: number;
  total_locations: number;
  needs_review: number;
  ebay_listed: number;
  processed_files: number;
  failed_files: number;
}

export interface Item {
  item_id: number;
  location_id: string | null;
  source_camera: string | null;
  source_filename: string | null;
  captured_at: string | null;
  object_count: number | null;
  completeness: string;
  ocr_text_raw: string | null;
  title_guess: string | null;
  title_confidence: number | null;
  platform_guess: string | null;
  language: string | null;
  title_manual: string | null;
  platform_manual: string | null;
  notes: string | null;
  ebay_listed: boolean;
  ebay_listing_id: string | null;
  needs_review: boolean;
  review_reason: string | null;
  processed_at: string | null;
  item_type: string | null;
  ai_identified: boolean;
  ai_description: string | null;
  brand: string | null;
  region: string | null;
  year: string | null;
  condition_notes: string | null;
}

export interface ItemUpdate {
  location_id?: string | null;
  title_manual?: string | null;
  platform_manual?: string | null;
  completeness?: string;
  notes?: string | null;
  ebay_listed?: boolean;
  ebay_listing_id?: string | null;
  needs_review?: boolean;
  review_reason?: string | null;
}

export interface Location {
  location_id: string;
  label: string | null;
  notes: string | null;
  created_at: string | null;
  item_count: number;
}

export interface PaginatedItems {
  items: Item[];
  total: number;
  page: number;
  per_page: number;
}

export interface SearchResults {
  query: string;
  results: Item[];
  total: number;
  page: number;
  per_page: number;
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  stats: () => fetchJSON<Stats>(`${BASE}/stats`),

  items: (params: Record<string, string | number | boolean> = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
    }
    return fetchJSON<PaginatedItems>(`${BASE}/items?${qs}`);
  },

  itemsUnlisted: (page = 1, perPage = 24) =>
    fetchJSON<PaginatedItems>(`${BASE}/items/unlisted?page=${page}&per_page=${perPage}`),

  item: (id: number) => fetchJSON<Item>(`${BASE}/items/${id}`),

  updateItem: (id: number, data: ItemUpdate) =>
    fetchJSON<Item>(`${BASE}/items/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  deleteItem: (id: number) =>
    fetchJSON<{ status: string }>(`${BASE}/items/${id}`, { method: 'DELETE' }),

  markListed: (id: number, listingId?: string) => {
    const qs = listingId ? `?ebay_listing_id=${listingId}` : '';
    return fetchJSON<Item>(`${BASE}/items/${id}/mark-listed${qs}`, { method: 'PATCH' });
  },

  reidentify: (id: number, provider: string, model?: string) =>
    fetchJSON<Item>(`${BASE}/items/${id}/reidentify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model: model || null }),
    }),

  search: (q: string, params: Record<string, string | number | boolean> = {}) => {
    const qs = new URLSearchParams({ q, ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])) });
    return fetchJSON<SearchResults>(`${BASE}/search?${qs}`);
  },

  locations: () => fetchJSON<{ locations: Location[]; total: number }>(`${BASE}/locations`),

  locationItems: (id: string, page = 1, perPage = 24) =>
    fetchJSON<{ location_id: string; items: Item[]; total: number; page: number; per_page: number }>(
      `${BASE}/locations/${encodeURIComponent(id)}/items?page=${page}&per_page=${perPage}`,
    ),

  platforms: () => fetchJSON<{ platforms: string[] }>(`${BASE}/platforms`),

  normalisePlatforms: () =>
    fetchJSON<{ status: string; total_updated: number; changes: { from: string; to: string; count: number }[] }>(
      `${BASE}/platforms/normalise`,
      { method: 'POST' },
    ),

  rotateImage: (id: number, direction: 'cw' | 'ccw') =>
    fetchJSON<{ item_id: number; width: number; height: number }>(
      `${BASE}/items/${id}/image/rotate`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ direction }) },
    ),

  cropImage: (id: number, x: number, y: number, width: number, height: number) =>
    fetchJSON<{ item_id: number; width: number; height: number }>(
      `${BASE}/items/${id}/image/crop`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ x, y, width, height }) },
    ),

  autoEnhance: (id: number) =>
    fetchJSON<{ item_id: number; width: number; height: number }>(
      `${BASE}/items/${id}/image/auto-enhance`,
      { method: 'POST' },
    ),

  startAutoEnhanceAll: (opts: { auto_crop?: boolean; auto_rotate?: boolean; ai_rotate?: boolean } = {}) =>
    fetchJSON<{ status: string }>(`${BASE}/auto-enhance-all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_crop: true, auto_rotate: true, ...opts }),
    }),

  autoEnhanceStatus: () =>
    fetchJSON<{ running: boolean; phase: string; total: number; processed: number; enhanced: number; message: string }>(
      `${BASE}/auto-enhance-status`,
    ),

  thumbUrl: (id: number) => `${BASE}/items/${id}/image/thumb`,
  fullUrl: (id: number) => `${BASE}/items/${id}/image/full`,
};
