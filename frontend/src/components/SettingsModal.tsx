import { useEffect, useState } from 'react';
import { api } from '../api';

interface SettingsData {
  settings: Record<string, string>;
  sources: Record<string, string>;
}

interface Props {
  onClose: () => void;
}

const LABELS: Record<string, { label: string; placeholder: string; type: string; help?: string }> = {
  ai_provider: {
    label: 'Default AI Provider',
    placeholder: '',
    type: 'select',
    help: 'Used when "Auto" is selected during import.',
  },
  anthropic_api_key: {
    label: 'Anthropic API Key',
    placeholder: 'sk-ant-...',
    type: 'password',
    help: 'Required for Claude identification. Get one at console.anthropic.com',
  },
  claude_model: {
    label: 'Claude Model',
    placeholder: 'claude-haiku-4-5-20251001',
    type: 'text',
  },
  ollama_host: {
    label: 'Ollama Host',
    placeholder: 'http://localhost:11434',
    type: 'text',
    help: 'URL of your Ollama server.',
  },
  ollama_model: {
    label: 'Ollama Model',
    placeholder: 'llava',
    type: 'text',
    help: 'Must support vision (e.g. llava, llava-llama3).',
  },
};

const PROVIDER_OPTIONS = [
  { value: 'auto', label: 'Auto-detect (Ollama → Claude)' },
  { value: 'claude', label: 'Claude (Anthropic)' },
  { value: 'ollama', label: 'Ollama (Local)' },
];

const SOURCE_LABELS: Record<string, string> = {
  env: 'Set by environment variable (read-only)',
  db: 'Saved in database',
  default: 'Default',
};

export default function SettingsModal({ onClose }: Props) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [normalising, setNormalising] = useState(false);
  const [normaliseResult, setNormaliseResult] = useState<string | null>(null);
  const [enhancing, setEnhancing] = useState(false);
  const [enhanceProgress, setEnhanceProgress] = useState('');
  const [enhanceResult, setEnhanceResult] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/settings')
      .then((r) => r.json())
      .then((d: SettingsData) => {
        setData(d);
        setEdits({ ...d.settings });
      })
      .catch(console.error);
  }, []);

  const handleSave = async () => {
    if (!data) return;
    setSaving(true);

    // Only send values that changed from what we loaded
    const updates: Record<string, string | null> = {};
    for (const [key, value] of Object.entries(edits)) {
      if (value !== data.settings[key]) {
        updates[key] = value || null;
      }
    }

    if (Object.keys(updates).length === 0) {
      onClose();
      return;
    }

    try {
      const res = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: updates }),
      });
      const updated: SettingsData = await res.json();
      setData(updated);
      setSaved(true);
      setTimeout(() => onClose(), 800);
    } catch (e) {
      console.error('Failed to save settings:', e);
    } finally {
      setSaving(false);
    }
  };

  if (!data) {
    return (
      <div className="modal open">
        <div className="modal-content">
          <div className="modal-body"><div className="empty-state">Loading settings...</div></div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-content settings-modal">
        <div className="modal-header">
          <h2>Settings</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">
          {saved && <div className="settings-saved">Settings saved!</div>}

          {Object.entries(LABELS).map(([key, meta]) => {
            const source = data.sources[key];
            const isEnvLocked = source === 'env';

            return (
              <div className="form-group" key={key}>
                <label>
                  {meta.label}
                  {isEnvLocked && <span className="source-badge env">ENV</span>}
                  {source === 'db' && <span className="source-badge db">SAVED</span>}
                </label>

                {meta.type === 'select' ? (
                  <select
                    value={edits[key] || ''}
                    onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                    disabled={isEnvLocked}
                  >
                    {PROVIDER_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={meta.type}
                    value={edits[key] || ''}
                    onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                    placeholder={meta.placeholder}
                    disabled={isEnvLocked}
                  />
                )}

                {meta.help && <span className="form-hint">{meta.help}</span>}
                {isEnvLocked && <span className="form-hint">{SOURCE_LABELS.env}</span>}
              </div>
            );
          })}
        </div>

        <div className="modal-body" style={{ borderTop: '1px solid var(--border)' }}>
          <h3 style={{ margin: '0 0 0.5rem' }}>Platform Normalisation</h3>
          <p className="form-hint" style={{ margin: '0 0 0.75rem' }}>
            Standardise platform names across your collection (e.g. &quot;PlayStation 2&quot; &rarr; &quot;PS2&quot;, &quot;Nintendo Entertainment System&quot; &rarr; &quot;NES&quot;). New imports are normalised automatically.
          </p>
          <button
            className="btn btn-outline"
            disabled={normalising}
            onClick={async () => {
              setNormalising(true);
              setNormaliseResult(null);
              try {
                const res = await api.normalisePlatforms();
                if (res.changes.length === 0) {
                  setNormaliseResult('All platforms are already normalised.');
                } else {
                  const summary = res.changes
                    .map((c) => `${c.from} \u2192 ${c.to} (${c.count})`)
                    .join(', ');
                  setNormaliseResult(`Updated ${res.total_updated} items: ${summary}`);
                }
              } catch {
                setNormaliseResult('Failed to normalise platforms.');
              } finally {
                setNormalising(false);
              }
            }}
          >
            {normalising ? 'Normalising...' : 'Normalise Platforms'}
          </button>
          {normaliseResult && (
            <p className="form-hint" style={{ marginTop: '0.5rem' }}>{normaliseResult}</p>
          )}
        </div>

        <div className="modal-body" style={{ borderTop: '1px solid var(--border)' }}>
          <h3 style={{ margin: '0 0 0.5rem' }}>Image Auto-Enhancement</h3>
          <p className="form-hint" style={{ margin: '0 0 0.75rem' }}>
            Auto-crop and deskew all item images. Detects items on plain backgrounds and tightens the framing. New imports are enhanced automatically.
          </p>
          <button
            className="btn btn-outline"
            disabled={enhancing}
            onClick={() => {
              setEnhancing(true);
              setEnhanceResult(null);
              setEnhanceProgress('Starting...');
              fetch('/api/auto-enhance-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ auto_crop: true, auto_rotate: true }),
              }).then(async (res) => {
                const reader = res.body?.getReader();
                if (!reader) { setEnhancing(false); return; }
                const decoder = new TextDecoder();
                let buffer = '';
                let finished = false;
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) break;
                  buffer += decoder.decode(value, { stream: true });
                  const lines = buffer.split('\n');
                  buffer = lines.pop() || '';
                  for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                      const data = JSON.parse(line.slice(6));
                      if (data.phase === 'enhancing') {
                        setEnhanceProgress(`${data.processed}/${data.total} (${data.enhanced} enhanced)`);
                      } else if (data.phase === 'complete') {
                        setEnhanceResult(data.message);
                        setEnhancing(false);
                        finished = true;
                      } else if (data.phase === 'error') {
                        setEnhanceResult(`Error: ${data.message}`);
                        setEnhancing(false);
                        finished = true;
                      }
                    } catch { /* skip */ }
                  }
                }
                if (!finished) setEnhancing(false);
              }).catch(() => {
                setEnhanceResult('Failed to start auto-enhancement.');
                setEnhancing(false);
              });
            }}
          >
            {enhancing ? `Enhancing... ${enhanceProgress}` : 'Auto-Enhance All Items'}
          </button>
          {enhanceResult && (
            <p className="form-hint" style={{ marginTop: '0.5rem' }}>{enhanceResult}</p>
          )}
        </div>

        <div className="form-actions" style={{ padding: '0.75rem 1rem' }}>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
          <button className="btn btn-outline" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
