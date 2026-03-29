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

type Step = 'folder' | 'preview' | 'method' | 'options' | 'processing' | 'done';

/**
 * How the user organized their photos — determines how locations are assigned.
 *
 * 'dividers'   — QR codes / printed text in the photo stream mark location boundaries
 *                (the pipeline's state machine handles this automatically)
 * 'subfolders' — Each subfolder = a location, no divider detection needed
 * 'single'     — All photos belong to one location (user provides the name)
 */
type OrganizationMethod = 'dividers' | 'subfolders' | 'single';

export default function ImportWizard({ onClose, onComplete }: Props) {
  const [step, setStep] = useState<Step>('folder');
  const [folderPath, setFolderPath] = useState('');
  const [folderInfo, setFolderInfo] = useState<FolderInfo | null>(null);
  const [orgMethod, setOrgMethod] = useState<OrganizationMethod>('dividers');
  const [singleLocation, setSingleLocation] = useState('');
  const [offline, setOffline] = useState(false);
  const [provider, setProvider] = useState('auto');
  const [status, setStatus] = useState<ProcessStatus | null>(null);
  const [error, setError] = useState('');
  const [scanning, setScanning] = useState(false);
  const [aiRotate, setAiRotate] = useState(false);
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

      // Smart default: if subfolders exist, suggest subfolder method
      if (info.subfolder_count > 0) {
        setOrgMethod('subfolders');
      }

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

    // Build request based on organization method
    const body: Record<string, unknown> = {
      folder_path: folderPath.trim(),
      offline,
      provider: offline ? 'none' : provider,
      resume: true,
      ai_rotate: !offline && aiRotate,
    };

    if (orgMethod === 'single' && singleLocation.trim()) {
      body.default_location = singleLocation.trim();
      body.skip_divider_detection = true;
    } else if (orgMethod === 'subfolders') {
      body.use_subfolders_as_locations = true;
      body.skip_divider_detection = true;
    }
    // 'dividers' — no overrides, pipeline handles it naturally

    try {
      const res = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
  }, [folderPath, singleLocation, orgMethod, offline, provider, aiRotate]);

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

          {/* Step 1: Folder path */}
          {step === 'folder' && (
            <div className="wizard-step">
              <p className="wizard-desc">
                Enter the path to a folder of photos. The cataloguer will scan for images
                and identify each item.
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
                  <span className="summary-label">images found</span>
                </div>
                {folderInfo.subfolder_count > 0 && (
                  <div className="summary-stat">
                    <span className="summary-number">{folderInfo.subfolder_count}</span>
                    <span className="summary-label">subfolders</span>
                  </div>
                )}
              </div>

              {folderInfo.image_count === 0 ? (
                <>
                  <div className="wizard-error">No images found in this folder.</div>
                  <div className="form-actions">
                    <button className="btn btn-outline" onClick={() => setStep('folder')}>Back</button>
                  </div>
                </>
              ) : (
                <div className="form-actions">
                  <button className="btn btn-primary" onClick={() => setStep('method')}>Continue</button>
                  <button className="btn btn-outline" onClick={() => setStep('folder')}>Back</button>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Organization method */}
          {step === 'method' && (
            <div className="wizard-step">
              <h3 className="wizard-subtitle">How are your photos organized?</h3>
              <p className="wizard-desc">
                This determines how items are assigned to storage locations.
              </p>

              <div className="method-options">
                <label className={`method-card ${orgMethod === 'dividers' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="method"
                    checked={orgMethod === 'dividers'}
                    onChange={() => setOrgMethod('dividers')}
                  />
                  <div>
                    <strong>Visual Dividers</strong>
                    <p>I placed QR codes or printed labels between groups of items when photographing. The cataloguer will detect these and assign locations automatically.</p>
                  </div>
                </label>

                {folderInfo && folderInfo.subfolder_count > 0 && (
                  <label className={`method-card ${orgMethod === 'subfolders' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="method"
                      checked={orgMethod === 'subfolders'}
                      onChange={() => setOrgMethod('subfolders')}
                    />
                    <div>
                      <strong>Subfolder Names</strong>
                      <p>Each subfolder represents a location. Items in <code>{folderInfo.subfolders[0] || 'Box-1'}</code>{folderInfo.subfolders.length > 1 ? `, ${folderInfo.subfolders[1]}` : ''}{folderInfo.subfolders.length > 2 ? `, etc.` : ''} will be grouped accordingly.</p>
                    </div>
                  </label>
                )}

                <label className={`method-card ${orgMethod === 'single' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="method"
                    checked={orgMethod === 'single'}
                    onChange={() => setOrgMethod('single')}
                  />
                  <div>
                    <strong>Single Location</strong>
                    <p>All photos in this folder belong to one location. I'll sort them later.</p>
                  </div>
                </label>
              </div>

              {orgMethod === 'single' && (
                <div className="form-group">
                  <label>Location Name</label>
                  <input
                    type="text"
                    value={singleLocation}
                    onChange={(e) => setSingleLocation(e.target.value)}
                    placeholder="e.g. BOX-1, Shelf A, My Collection"
                  />
                </div>
              )}

              <div className="form-actions">
                <button
                  className="btn btn-primary"
                  onClick={() => setStep('options')}
                  disabled={orgMethod === 'single' && !singleLocation.trim()}
                >
                  Continue
                </button>
                <button className="btn btn-outline" onClick={() => setStep('preview')}>Back</button>
              </div>
            </div>
          )}

          {/* Step 4: AI options */}
          {step === 'options' && (
            <div className="wizard-step">
              <h3 className="wizard-subtitle">Identification</h3>
              <p className="wizard-desc">
                AI can identify titles, platforms, and condition. Or use offline mode for QR/OCR only.
              </p>

              <div className="form-group">
                <label>AI Provider</label>
                <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={offline}>
                  <option value="auto">Auto-detect (Ollama → Claude)</option>
                  <option value="claude">Claude</option>
                  <option value="ollama">Ollama (local)</option>
                </select>
              </div>

              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={offline}
                  onChange={(e) => setOffline(e.target.checked)}
                />
                Offline mode (QR/OCR only — no AI identification)
              </label>

              {!offline && (
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={aiRotate}
                    onChange={(e) => setAiRotate(e.target.checked)}
                  />
                  AI orientation fix (rotate sideways/upside-down items — no extra cost, uses existing AI call)
                </label>
              )}

              <div className="import-summary">
                <strong>Ready to import:</strong>
                <ul>
                  <li>{folderInfo?.image_count} images from <code>{folderPath.split('/').pop()}</code></li>
                  <li>Locations: {orgMethod === 'dividers' ? 'detected from visual dividers' : orgMethod === 'subfolders' ? `from ${folderInfo?.subfolder_count} subfolders` : `all → ${singleLocation}`}</li>
                  <li>Identification: {offline ? 'OCR only (offline)' : `AI (${provider})`}</li>
                </ul>
              </div>

              <div className="form-actions">
                <button className="btn btn-primary" onClick={handleStartProcessing}>
                  Start Import
                </button>
                <button className="btn btn-outline" onClick={() => setStep('method')}>Back</button>
              </div>
            </div>
          )}

          {/* Step 5: Processing */}
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
                    <span>{status.locations_found.length} locations</span>
                  )}
                </div>
              )}

              <div className="form-actions">
                <button className="btn btn-danger" onClick={handleCancel}>Cancel</button>
              </div>
            </div>
          )}

          {/* Step 6: Done */}
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
                      <span className="summary-label">processed</span>
                    </div>
                    <div className="summary-stat">
                      <span className="summary-number">{status?.items_created || 0}</span>
                      <span className="summary-label">items</span>
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
