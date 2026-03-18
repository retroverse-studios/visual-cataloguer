import { useState, useRef, useCallback } from 'react';

interface ProcessStatus {
  phase: string;
  total_files: number;
  processed: number;
  current_file: string;
  items_created: number;
  locations_found: string[];
  message: string;
}

interface FolderInfo {
  path: string;
  image_count: number;
  image_files: string[];
  subfolder_count: number;
  subfolders: string[];
}

interface Props {
  onClose: () => void;
  onComplete: () => void;
}

type Step = 'folder' | 'preview' | 'options' | 'processing' | 'done';

export default function ImportWizard({ onClose, onComplete }: Props) {
  const [step, setStep] = useState<Step>('folder');
  const [folderPath, setFolderPath] = useState('');
  const [folderInfo, setFolderInfo] = useState<FolderInfo | null>(null);
  const [defaultLocation, setDefaultLocation] = useState('');
  const [useSubfoldersAsLocations, setUseSubfoldersAsLocations] = useState(false);
  const [offline, setOffline] = useState(false);
  const [provider, setProvider] = useState('auto');
  const [status, setStatus] = useState<ProcessStatus | null>(null);
  const [error, setError] = useState('');
  const [scanning, setScanning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const handleScanFolder = async () => {
    if (!folderPath.trim()) return;
    setScanning(true);
    setError('');
    try {
      const res = await fetch('/api/scan-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_path: folderPath.trim() }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to scan folder');
      }
      const info: FolderInfo = await res.json();
      setFolderInfo(info);
      setStep('preview');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setScanning(false);
    }
  };

  const handleStartProcessing = useCallback(async () => {
    setStep('processing');
    setError('');
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          folder_path: folderPath.trim(),
          default_location: defaultLocation.trim() || null,
          offline,
          provider,
          resume: true,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Processing failed');
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) throw new Error('No response stream');

      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data: ProcessStatus = JSON.parse(line.slice(6));
              setStatus(data);
              if (data.phase === 'complete' || data.phase === 'error') {
                setStep('done');
                if (data.phase === 'error') setError(data.message);
              }
            } catch {
              // Skip malformed events
            }
          }
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError((e as Error).message);
        setStep('done');
      }
    }
  }, [folderPath, defaultLocation, offline, provider]);

  const handleCancel = () => {
    abortRef.current?.abort();
    onClose();
  };

  const progressPct = status && status.total_files > 0
    ? Math.round((status.processed / status.total_files) * 100)
    : 0;

  return (
    <div className="modal open" onClick={(e) => e.target === e.currentTarget && step !== 'processing' && onClose()}>
      <div className="modal-content import-wizard">
        <div className="modal-header">
          <h2>Import Images</h2>
          {step !== 'processing' && (
            <button className="modal-close" onClick={onClose}>&times;</button>
          )}
        </div>
        <div className="modal-body">

          {/* Step 1: Enter folder path */}
          {step === 'folder' && (
            <div className="wizard-step">
              <p className="wizard-desc">
                Enter the path to a folder of photos. The cataloguer will scan for images,
                detect QR code dividers, and identify each item using AI.
              </p>
              <div className="form-group">
                <label>Folder Path</label>
                <input
                  type="text"
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleScanFolder()}
                  placeholder="/path/to/your/photos"
                  autoFocus
                />
              </div>
              {error && <div className="wizard-error">{error}</div>}
              <div className="form-actions">
                <button className="btn btn-primary" onClick={handleScanFolder} disabled={scanning || !folderPath.trim()}>
                  {scanning ? 'Scanning...' : 'Scan Folder'}
                </button>
                <button className="btn btn-outline" onClick={onClose}>Cancel</button>
              </div>
            </div>
          )}

          {/* Step 2: Preview */}
          {step === 'preview' && folderInfo && (
            <div className="wizard-step">
              <div className="wizard-summary">
                <div className="summary-stat">
                  <span className="summary-number">{folderInfo.image_count}</span>
                  <span className="summary-label">images</span>
                </div>
                <div className="summary-stat">
                  <span className="summary-number">{folderInfo.subfolder_count}</span>
                  <span className="summary-label">subfolders</span>
                </div>
              </div>

              {folderInfo.subfolders.length > 0 && (
                <div className="wizard-subfolders">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={useSubfoldersAsLocations}
                      onChange={(e) => setUseSubfoldersAsLocations(e.target.checked)}
                    />
                    Use subfolder names as locations
                  </label>
                  <div className="subfolder-list">
                    {folderInfo.subfolders.slice(0, 10).map((sf) => (
                      <span key={sf} className="chip">{sf}</span>
                    ))}
                    {folderInfo.subfolders.length > 10 && (
                      <span className="chip">+{folderInfo.subfolders.length - 10} more</span>
                    )}
                  </div>
                </div>
              )}

              <div className="form-group">
                <label>Default Location (if no QR dividers found)</label>
                <input
                  type="text"
                  value={defaultLocation}
                  onChange={(e) => setDefaultLocation(e.target.value)}
                  placeholder="e.g. BOX-1, SHELF-A, My Collection"
                />
                <span className="form-hint">Leave blank to auto-detect from QR codes</span>
              </div>

              <div className="form-actions">
                <button className="btn btn-primary" onClick={() => setStep('options')}>
                  Configure &amp; Import
                </button>
                <button className="btn btn-outline" onClick={() => setStep('folder')}>Back</button>
              </div>
            </div>
          )}

          {/* Step 3: Options */}
          {step === 'options' && (
            <div className="wizard-step">
              <h3 className="wizard-subtitle">Processing Options</h3>

              <div className="form-group">
                <label>AI Provider</label>
                <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                  <option value="auto">Auto-detect (Ollama → Claude)</option>
                  <option value="claude">Claude</option>
                  <option value="ollama">Ollama (local)</option>
                  <option value="none">None (offline)</option>
                </select>
              </div>

              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={offline}
                  onChange={(e) => setOffline(e.target.checked)}
                />
                Offline mode (QR/OCR only, no AI identification)
              </label>

              <div className="form-actions">
                <button className="btn btn-primary" onClick={handleStartProcessing}>
                  Start Import
                </button>
                <button className="btn btn-outline" onClick={() => setStep('preview')}>Back</button>
              </div>
            </div>
          )}

          {/* Step 4: Processing */}
          {step === 'processing' && (
            <div className="wizard-step">
              <div className="progress-container">
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${progressPct}%` }} />
                </div>
                <div className="progress-text">
                  {status?.processed || 0} / {status?.total_files || '?'} images ({progressPct}%)
                </div>
              </div>

              {status?.current_file && (
                <div className="progress-current">Processing: {status.current_file}</div>
              )}

              {status && status.items_created > 0 && (
                <div className="progress-stats">
                  <span>{status.items_created} items catalogued</span>
                  {status.locations_found.length > 0 && (
                    <span>{status.locations_found.length} locations detected</span>
                  )}
                </div>
              )}

              <div className="form-actions">
                <button className="btn btn-danger" onClick={handleCancel}>Cancel</button>
              </div>
            </div>
          )}

          {/* Step 5: Done */}
          {step === 'done' && (
            <div className="wizard-step">
              {error ? (
                <div className="wizard-error">{error}</div>
              ) : (
                <>
                  <div className="wizard-success">Import complete!</div>
                  <div className="wizard-summary">
                    <div className="summary-stat">
                      <span className="summary-number">{status?.processed || 0}</span>
                      <span className="summary-label">images processed</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-number">{status?.items_created || 0}</span>
                      <span className="summary-label">items catalogued</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-number">{status?.locations_found.length || 0}</span>
                      <span className="summary-label">locations</span>
                    </div>
                  </div>
                </>
              )}
              <div className="form-actions">
                <button className="btn btn-primary" onClick={() => { onComplete(); onClose(); }}>
                  View Collection
                </button>
                <button className="btn btn-outline" onClick={() => { setStep('folder'); setError(''); }}>
                  Import More
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
