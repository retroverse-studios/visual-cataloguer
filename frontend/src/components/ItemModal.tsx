import { useState } from 'react';
import { api } from '../api';
import type { Item, ItemUpdate } from '../api';

interface Props {
  item: Item;
  onClose: () => void;
  onSaved: () => void;
}

export default function ItemModal({ item, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(item.title_manual || item.title_guess || '');
  const [platform, setPlatform] = useState(item.platform_manual || item.platform_guess || '');
  const [completeness, setCompleteness] = useState(item.completeness || 'unknown');
  const [notes, setNotes] = useState(item.notes || '');
  const [saving, setSaving] = useState(false);
  const [reidentifying, setReidentifying] = useState(false);
  const [showAi, setShowAi] = useState(false);

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

  return (
    <div className="modal open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-content">
        <div className="modal-header">
          <h2>{item.title_manual || item.title_guess || `Item #${item.item_id}`}</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">
          <img className="modal-img" src={api.fullUrl(item.item_id)} alt="Item" />

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

          {/* Re-identify */}
          <div className="reidentify-bar">
            <span className="label">Re-identify with:</span>
            <button className="btn btn-sm" onClick={() => handleReidentify('claude')} disabled={reidentifying}>
              Claude
            </button>
            <button className="btn btn-sm" onClick={() => handleReidentify('ollama')} disabled={reidentifying}>
              Ollama
            </button>
            {reidentifying && <span className="spinner" />}
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
