import { useCallback, useRef, useState } from 'react';
import { api } from '../api';
import type { Item, ItemUpdate, PriceEstimate } from '../api';

interface Props {
  item: Item;
  onClose: () => void;
  onSaved: () => void;
  /** Notify the parent that this item's image changed, so its grid thumbnail can refresh. */
  onImageChanged?: (itemId: number) => void;
}

export default function ItemModal({ item, onClose, onSaved, onImageChanged }: Props) {
  const [title, setTitle] = useState(item.title_manual || item.title_guess || '');
  const [platform, setPlatform] = useState(item.platform_manual || item.platform_guess || '');
  const [completeness, setCompleteness] = useState(item.completeness || 'unknown');
  const [notes, setNotes] = useState(item.notes || '');
  const [saving, setSaving] = useState(false);
  const [reidentifying, setReidentifying] = useState(false);
  const [showAi, setShowAi] = useState(false);
  const [generatingDesc, setGeneratingDesc] = useState(false);
  const [pricing, setPricing] = useState(false);
  const [priceResult, setPriceResult] = useState<PriceEstimate | null>(null);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [imgKey, setImgKey] = useState(0);
  const [editingImage, setEditingImage] = useState(false);
  const [cropping, setCropping] = useState(false);

  const bustCache = () => {
    setImgKey((k) => k + 1);
    onImageChanged?.(item.item_id);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const update: ItemUpdate = {
        title_manual: title || null,
        platform_manual: platform || null,
        completeness,
        notes: notes || null,
      };
      await api.updateItem(item.item_id, update);
      onSaved();
    } catch (e) {
      console.error('Save failed:', e);
    } finally {
      setSaving(false);
    }
  };

  const handleMarkListed = async () => {
    try {
      await api.markListed(item.item_id);
      onSaved();
    } catch (e) {
      console.error('Mark listed failed:', e);
    }
  };

  const handleDelete = async () => {
    if (!confirm('Delete this item permanently?')) return;
    try {
      await api.deleteItem(item.item_id);
      onSaved();
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  const handleReidentify = async (provider: string) => {
    setReidentifying(true);
    try {
      const updated = await api.reidentify(item.item_id, provider);
      setTitle(updated.title_manual || updated.title_guess || '');
      setPlatform(updated.platform_manual || updated.platform_guess || '');
    } catch (e) {
      console.error('Reidentify failed:', e);
    } finally {
      setReidentifying(false);
    }
  };

  const handleResearchPrice = async () => {
    setPricing(true);
    setPriceError(null);
    try {
      const res = await fetch(`/api/items/${item.item_id}/price-research`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        setPriceResult(null);
        setPriceError(data.detail || 'Price research failed');
        return;
      }
      setPriceResult(data as PriceEstimate);
    } catch (e) {
      console.error('Price research failed:', e);
      setPriceError('Price research failed — is the server running?');
    } finally {
      setPricing(false);
    }
  };

  const handleRotate = async (dir: 'cw' | 'ccw') => {
    setEditingImage(true);
    try {
      await api.rotateImage(item.item_id, dir);
      bustCache();
    } catch (e) {
      console.error('Rotate failed:', e);
    } finally {
      setEditingImage(false);
    }
  };

  const handleAutoEnhance = async () => {
    setEditingImage(true);
    try {
      await api.autoEnhance(item.item_id);
      bustCache();
    } catch (e) {
      console.error('Auto-enhance failed:', e);
    } finally {
      setEditingImage(false);
    }
  };

  const handleCropConfirm = async (x: number, y: number, w: number, h: number) => {
    setEditingImage(true);
    setCropping(false);
    try {
      await api.cropImage(item.item_id, x, y, w, h);
      bustCache();
    } catch (e) {
      console.error('Crop failed:', e);
    } finally {
      setEditingImage(false);
    }
  };

  return (
    <div className="modal open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-content">
        <div className="modal-header">
          <h2>{item.title_manual || item.title_guess || `Item #${item.item_id}`}</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">
          {cropping ? (
            <CropOverlay
              src={`${api.fullUrl(item.item_id)}?t=${imgKey}`}
              onConfirm={handleCropConfirm}
              onCancel={() => setCropping(false)}
            />
          ) : (
            <img className="modal-img" src={`${api.fullUrl(item.item_id)}?t=${imgKey}`} alt="Item" />
          )}

          {/* Image editing toolbar */}
          <div className="image-edit-bar">
            <button className="btn btn-sm" onClick={() => handleRotate('ccw')} disabled={editingImage} title="Rotate Left">
              &#x21BA; Left
            </button>
            <button className="btn btn-sm" onClick={() => handleRotate('cw')} disabled={editingImage} title="Rotate Right">
              &#x21BB; Right
            </button>
            <button className="btn btn-sm" onClick={handleAutoEnhance} disabled={editingImage} title="Auto crop and deskew">
              Auto Enhance
            </button>
            <button className="btn btn-sm" onClick={() => setCropping(!cropping)} disabled={editingImage}>
              {cropping ? 'Cancel Crop' : 'Crop'}
            </button>
            {editingImage && <span className="spinner" />}
          </div>

          {/* AI Info - hidden by default */}
          {item.ai_description && (
            <div className="ai-info" onClick={() => setShowAi(!showAi)} style={{ cursor: 'pointer' }}>
              <span className="ai-label">AI</span>
              {showAi ? <span>{item.ai_description}</span> : <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Click to show AI response</span>}
            </div>
          )}

          {/* Detail chips */}
          <div className="detail-chips">
            {item.brand && <span className="chip">{item.brand}</span>}
            {item.region && <span className="chip">{item.region}</span>}
            {item.year && <span className="chip">{item.year}</span>}
            {item.item_type && <span className="chip">{item.item_type}</span>}
            {item.location_id && <span className="chip">📦 {item.location_id}</span>}
            {item.condition_notes && <span className="chip">{item.condition_notes}</span>}
          </div>

          <div className="form-group">
            <label>Title</label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Platform</label>
              <input type="text" value={platform} onChange={(e) => setPlatform(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Location</label>
              <input type="text" value={item.location_id || ''} readOnly className="readonly" />
            </div>
            <div className="form-group">
              <label>Completeness</label>
              <select value={completeness} onChange={(e) => setCompleteness(e.target.value)}>
                <option value="unknown">Unknown</option>
                <option value="loose">Loose</option>
                <option value="boxed">Boxed</option>
                <option value="partial">Partial</option>
                <option value="complete_set">Complete Set</option>
              </select>
            </div>
          </div>
          <div className="form-group">
            <label>Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </div>

          {item.ocr_text_raw && (
            <div className="form-group">
              <label>OCR Text</label>
              <textarea value={item.ocr_text_raw} readOnly className="readonly" rows={2} />
            </div>
          )}

          {/* Price research */}
          <div className="reidentify-bar">
            <button className="btn btn-sm btn-primary" onClick={handleResearchPrice} disabled={pricing}>
              {pricing ? 'Searching eBay...' : 'Research Price'}
            </button>
            {pricing && <span className="spinner" />}
          </div>
          {priceError && <div className="price-error">{priceError}</div>}
          {priceResult && (
            <div className="price-panel">
              <div className="price-stats">
                <div className="price-stat">
                  <span className="price-stat-label">Low</span>
                  <span className="price-stat-value">{priceResult.currency} {priceResult.price_low.toFixed(2)}</span>
                </div>
                <div className="price-stat price-stat-median">
                  <span className="price-stat-label">Median</span>
                  <span className="price-stat-value">{priceResult.currency} {priceResult.price_median.toFixed(2)}</span>
                </div>
                <div className="price-stat">
                  <span className="price-stat-label">High</span>
                  <span className="price-stat-value">{priceResult.currency} {priceResult.price_high.toFixed(2)}</span>
                </div>
              </div>
              <div className="price-meta">
                Based on {priceResult.sample_size} recent sales
                {priceResult.most_recent_sale && <> · most recent {priceResult.most_recent_sale}</>}
                {priceResult.oldest_sale && <> · oldest sampled {priceResult.oldest_sale}</>}
              </div>
              <ul className="price-listings">
                {priceResult.listings.slice(0, 5).map((l, i) => (
                  <li key={i}>
                    <span className="price-listing-price">{l.currency} {l.price.toFixed(2)}</span>
                    <span className="price-listing-date">{l.sold_date || ''}</span>
                    {l.url ? <a href={l.url} target="_blank" rel="noreferrer">{l.title}</a> : <span>{l.title}</span>}
                  </li>
                ))}
              </ul>
              <a className="price-search-link" href={priceResult.search_url} target="_blank" rel="noreferrer">
                View all sold listings on eBay →
              </a>
            </div>
          )}

          {/* Re-identify & eBay */}
          <div className="reidentify-bar">
            <button className="btn btn-sm" onClick={async () => {
              setGeneratingDesc(true);
              try {
                const res = await fetch(`/api/items/${item.item_id}/ebay-description`, { method: 'POST' });
                const data = await res.json();
                if (!res.ok) {
                  alert('Failed: ' + (data.detail || 'Unknown error'));
                  return;
                }
                const desc = data.description || '';
                if (desc) {
                  setNotes(notes ? notes + '\n\n--- eBay Description ---\n' + desc : desc);
                }
              } catch (e) { console.error('Failed:', e); }
              finally { setGeneratingDesc(false); }
            }} disabled={generatingDesc}>
              {generatingDesc ? 'Generating...' : 'Generate eBay Description'}
            </button>
            <span className="label" style={{ marginLeft: '1rem' }}>Re-identify:</span>
            <button className="btn btn-sm" onClick={() => handleReidentify('claude')} disabled={reidentifying}>
              Claude
            </button>
            <button className="btn btn-sm" onClick={() => handleReidentify('ollama')} disabled={reidentifying}>
              Ollama
            </button>
            {(reidentifying || generatingDesc) && <span className="spinner" />}
          </div>

          <div className="form-actions">
            <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
            {!item.ebay_listed && (
              <button className="btn btn-success" onClick={handleMarkListed}>Mark Listed</button>
            )}
            <button className="btn btn-danger" onClick={handleDelete}>Delete</button>
            <button className="btn btn-outline" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}


/* ── Crop Overlay Component ── */

interface CropOverlayProps {
  src: string;
  onConfirm: (x: number, y: number, w: number, h: number) => void;
  onCancel: () => void;
}

function CropOverlay({ src, onConfirm, onCancel }: CropOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [naturalSize, setNaturalSize] = useState({ w: 0, h: 0 });
  const [selection, setSelection] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const startRef = useRef({ x: 0, y: 0 });

  const handleImgLoad = () => {
    if (imgRef.current) {
      setNaturalSize({ w: imgRef.current.naturalWidth, h: imgRef.current.naturalHeight });
    }
  };

  const getRelPos = useCallback((e: React.MouseEvent) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: Math.max(0, Math.min(e.clientX - rect.left, rect.width)),
      y: Math.max(0, Math.min(e.clientY - rect.top, rect.height)),
    };
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const pos = getRelPos(e);
    startRef.current = pos;
    setSelection({ x: pos.x, y: pos.y, w: 0, h: 0 });
    setDragging(true);
  }, [getRelPos]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging) return;
    const pos = getRelPos(e);
    const sx = startRef.current.x;
    const sy = startRef.current.y;
    setSelection({
      x: Math.min(sx, pos.x),
      y: Math.min(sy, pos.y),
      w: Math.abs(pos.x - sx),
      h: Math.abs(pos.y - sy),
    });
  }, [dragging, getRelPos]);

  const handleMouseUp = useCallback(() => {
    setDragging(false);
  }, []);

  const handleConfirm = () => {
    if (!selection || !imgRef.current || selection.w < 10 || selection.h < 10) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;

    // Map displayed coordinates to actual image pixel coordinates
    const scaleX = naturalSize.w / rect.width;
    const scaleY = naturalSize.h / rect.height;
    onConfirm(
      Math.round(selection.x * scaleX),
      Math.round(selection.y * scaleY),
      Math.round(selection.w * scaleX),
      Math.round(selection.h * scaleY),
    );
  };

  return (
    <div className="crop-container">
      <div
        ref={containerRef}
        className="crop-area"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <img ref={imgRef} src={src} alt="Crop" onLoad={handleImgLoad} draggable={false} />
        {selection && selection.w > 0 && (
          <div
            className="crop-selection"
            style={{
              left: selection.x,
              top: selection.y,
              width: selection.w,
              height: selection.h,
            }}
          />
        )}
      </div>
      <div className="crop-actions">
        <span className="form-hint">Click and drag to select crop area</span>
        <button
          className="btn btn-sm btn-primary"
          onClick={handleConfirm}
          disabled={!selection || selection.w < 10 || selection.h < 10}
        >
          Apply Crop
        </button>
        <button className="btn btn-sm btn-outline" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
