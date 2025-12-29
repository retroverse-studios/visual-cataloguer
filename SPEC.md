# Game Collection Cataloguer

## Overview

A two-part system to catalogue ~5,000 retro game collection photos:

> **Why this doesn't exist yet:** The "visual divider" workflow pattern — photograph a marker, then batch items, then end marker — is intuitive for anyone cataloguing physical objects but strangely absent from existing tools. Most inventory apps assume barcode scanning (one item at a time) or manual data entry. This tool fills that gap.

**Generic applicability:** While built for retro games, the core pipeline works for any physical collection:
- 📚 Books / vinyl records / CDs
- 🔧 Tools / workshop inventory  
- 🎨 Art supplies / craft materials
- 🏺 Collectibles (coins, stamps, figures)
- 📦 Warehouse/storage box contents

1. **CLI Processing Tool** — Batch processes photos from two Sony cameras, detects box dividers, segments game items, extracts metadata via OCR, stores everything in a portable SQLite database
2. **Web Interface** — FastAPI + React app for searching/browsing the catalogue on mobile devices (iPad/phone), designed for creating eBay listings

---

## Part 1: CLI Processing Tool

### 1.1 Input Sources

| Camera | Format | Directory |
|--------|--------|-----------|
| Sony NEX-3N | `.ARW` (RAW) | `--input-dir-1` |
| Sony RX100M4 | `.JPG` | `--input-dir-2` |

Both directories are scanned and images merged into a single timeline using EXIF `DateTimeOriginal`.

### 1.2 Image Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                      For each image (chronological)             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │ Load Image   │────▶│ Classify     │────▶│ Process      │    │
│  │ (ARW/JPG)    │     │ Image Type   │     │ Accordingly  │    │
│  └──────────────┘     └──────────────┘     └──────────────┘    │
│                              │                                  │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│       ┌──────────┐    ┌──────────┐    ┌──────────┐             │
│       │ BOX      │    │ BLACK    │    │ GAME     │             │
│       │ DIVIDER  │    │ FRAME    │    │ ITEM     │             │
│       └──────────┘    └──────────┘    └──────────┘             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 State Machine

```
                    ┌─────────────────┐
                    │   NO_BOX_ACTIVE │◀──────────────────┐
                    │   (initial)     │                   │
                    └────────┬────────┘                   │
                             │                            │
                    BOX DIVIDER detected                  │
                    (QR or OCR text)                      │
                             │                            │
                             ▼                            │
                    ┌─────────────────┐          BLACK FRAME
                    │  BOX_ACTIVE     │          detected
                    │  current_box=X  │───────────────────┘
                    └────────┬────────┘
                             │
                    GAME ITEM detected
                    (while box active)
                             │
                             ▼
                    ┌─────────────────┐
                    │ Process & Store │
                    │ under current   │
                    │ box_id          │
                    └─────────────────┘
```

### 1.4 Image Classification Rules

#### Box Divider Detection

A photo is classified as a **BOX DIVIDER** if ANY of these succeed (in order):

1. **QR Code** — `pyzbar` detects a QR code
   - Extract data directly (e.g., `BOX-1`, `BOX-47`)
   - Expected format: `BOX-{number}` or `BOX-{number}-{optional-label}`
   
2. **Large Printed Text** — If no QR found, run OCR looking for identifier pattern
   - Regex: `BOX[-\s]?\d+` or `[A-Z]+[-\s]?\d+` (flexible)
   - Must be high confidence (>80%)

3. **Handwritten Text** — Same OCR approach, lower confidence threshold (>60%)
   - Flag for manual review if confidence is borderline
   - Works with thick marker on white paper

**Supported divider formats (all valid):**

```
┌─────────────────────────────────────────────────────────────────┐
│  OPTION A: QR + Printed Text (recommended)                      │
│                                                                 │
│     ┌─────────────────────────────────────┐                     │
│     │                                     │                     │
│     │   BOX-1            [QR CODE]        │                     │
│     │                                     │                     │
│     └─────────────────────────────────────┘                     │
│                                                                 │
│  OPTION B: Printed Text Only (no QR)                            │
│                                                                 │
│     ┌─────────────────────────────────────┐                     │
│     │                                     │                     │
│     │          BOX-1                      │                     │
│     │                                     │                     │
│     └─────────────────────────────────────┘                     │
│                                                                 │
│  OPTION C: Handwritten (marker on white A4)                     │
│                                                                 │
│     ┌─────────────────────────────────────┐                     │
│     │                                     │                     │
│     │        "Box 7"  (handwritten)       │                     │
│     │                                     │                     │
│     └─────────────────────────────────────┘                     │
│                                                                 │
│  OPTION D: Custom identifier (any pattern)                      │
│                                                                 │
│     ┌─────────────────────────────────────┐                     │
│     │                                     │                     │
│     │       SHELF-A3  or  GARAGE-2        │                     │
│     │                                     │                     │
│     └─────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

**Handwriting tips for best OCR results:**
- Use thick black marker (Sharpie, whiteboard marker)
- Write on plain white paper (A4)
- Large letters (5cm+ height)
- Block capitals preferred
- Keep it simple: `BOX 1` or `BOX-1` or `B1`

**Visual characteristics of your divider photos:**
- White A4 paper on cardboard background
- Bold "BOX-X" text on left
- QR code on right encoding the same value (optional)
- Some cardboard/background visible at edges (not a problem)

#### Black Frame Detection

A photo is classified as a **BLACK FRAME** (sequence ender) if:
- Mean brightness < 10% (approximately RGB average < 25)
- This clears `current_box_id` — subsequent game items go to "UNASSIGNED" until next divider

#### Game Item Detection

Everything else is a **GAME ITEM**. Processing:

1. **Background removal** — White sheet background, detect largest contours
2. **Object counting** — Count distinct objects (1-3 typically, 4+ = flag as `complete_set`)
3. **Bounding box** — Crop to encompass all detected objects with padding
4. **Deskew** — Rotate based on dominant edge orientation
5. **OCR** — Extract all readable text
6. **Store** — Save processed image + metadata to database

### 1.5 Object Counting & Completeness

| Objects Detected | Interpretation | `completeness` Value |
|------------------|----------------|----------------------|
| 1 | Single item (could be boxed game OR loose cart) | `unknown` (manual review) |
| 2 | Likely: game + case OR game + manual | `partial` |
| 3 | Likely: game + case + manual | `complete_set` |
| 4+ | Unusual — flag for review | `complete_set` (with flag) |

**Note:** A single boxed PS2 game (case with manual inside) appears as 1 object. The `completeness` field can be manually adjusted in the web UI.

### 1.6 OCR & Game Identification

**Text Extraction:**
- Run Tesseract on cropped/deskewed image
- Attempt to isolate text regions (spines, labels) before OCR
- Store ALL extracted text in `ocr_text_raw` field
- Language: English primary. If non-ASCII detected, flag `language = 'foreign'`

**Game Identification (best effort):**
- Parse extracted text for game title patterns
- Optional: IGDB API lookup for metadata enrichment (future enhancement)
- Store guessed title in `title_guess`, confidence in `title_confidence`
- Unknown fields = `'UNK'`

### 1.7 Processed Image Storage Strategy

**Decision: Store images AS BLOBS in SQLite**

Rationale:
- Single portable file — your son just needs the `.db` file
- No broken links if moved between machines
- SQLite handles BLOBs efficiently up to ~100MB per row

**What gets stored for each item:**

```
┌─────────────────────────────────────────────────────────────────┐
│  SCENARIO A: Single object detected (1 game in photo)           │
│                                                                 │
│  Creates 1 item record with these images:                       │
│    • image_type='full'    → Cropped/deskewed full resolution    │
│    • image_type='thumb'   → 400px thumbnail for grid view       │
│    • image_type='original'→ Original uncropped (for re-process) │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  SCENARIO B: Multiple objects detected (2-3 items in photo)     │
│                                                                 │
│  Creates 1 item record PER OBJECT with:                         │
│    • item.object_index = 1, 2, or 3 (position in original)      │
│    • item.source_item_group = shared UUID linking siblings      │
│                                                                 │
│  Each item gets:                                                │
│    • image_type='full'   → Individual cropped object            │
│    • image_type='thumb'  → Individual thumbnail                 │
│    • image_type='context'→ Original photo with THIS object      │
│                           highlighted (bounding box drawn)      │
│                                                                 │
│  Additionally, ONE shared record stores:                        │
│    • image_type='group_original' → Full original photo          │
│      (attached to first item in group, avoids duplication)      │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  EXAMPLE: Photo with game + case + manual (3 objects)           │
│                                                                 │
│  ┌──────────────────────────────────────┐                       │
│  │  Original photo (white background)   │                       │
│  │  ┌─────┐  ┌─────────┐  ┌──────┐     │                       │
│  │  │CART │  │  CASE   │  │MANUAL│     │                       │
│  │  │     │  │         │  │      │     │                       │
│  │  └─────┘  └─────────┘  └──────┘     │                       │
│  └──────────────────────────────────────┘                       │
│                    ↓                                            │
│  Creates 3 items (linked by source_item_group):                 │
│    Item 1: cropped cart image                                   │
│    Item 2: cropped case image  ← LARGEST = primary/cover art    │
│    Item 3: cropped manual image                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Which image is "the" game art for eBay listing?**

The system uses these heuristics to pick the `primary_image`:

1. **Largest bounding box** — The case/box art is usually the biggest object
2. **Most text detected** — Cover art has the title prominently displayed
3. **Aspect ratio** — Game cases have predictable aspect ratios per platform:
   - PS2/DVD cases: ~1:1.4 (portrait)
   - NES cartridges: ~1:1.2 (landscape-ish)
   - SNES cartridges: ~1:1.1

```sql
-- New column in items table
ALTER TABLE items ADD COLUMN is_primary_image BOOLEAN DEFAULT FALSE;
ALTER TABLE items ADD COLUMN source_item_group TEXT;  -- UUID linking multi-object splits
ALTER TABLE items ADD COLUMN object_index INTEGER;    -- 1, 2, 3 position in original photo
```

**Web UI handling:**

When displaying an item that's part of a multi-object group:
- Show the primary image large
- Show siblings as "related images" below
- Allow user to change which is primary (one click)
- "View original photo" button shows full context

**Storage format:**
- **Full resolution:** JPEG, quality 85, stored in `image_blob`
- **Thumbnail:** JPEG, 400px max dimension
- Original dimensions preserved in metadata

### 1.8 Database Schema

```sql
-- Box/container tracking
CREATE TABLE boxes (
    box_id          TEXT PRIMARY KEY,      -- e.g., "BOX-1", "BOX-47", "SHELF-A3"
    label           TEXT,                  -- Optional friendly name
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Individual game items
CREATE TABLE items (
    item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    box_id          TEXT REFERENCES boxes(box_id),  -- NULL if unassigned
    
    -- Source info
    source_camera   TEXT,                  -- "NEX-3N" or "RX100M4"  
    source_filename TEXT,                  -- Original filename
    source_hash     TEXT,                  -- SHA256 of original file (for resume)
    captured_at     DATETIME,              -- EXIF DateTimeOriginal
    
    -- Multi-object grouping (when 2-3 items in one photo)
    source_item_group TEXT,                -- UUID linking items from same photo
    object_index    INTEGER DEFAULT 1,     -- 1, 2, 3... position in original
    is_primary_image BOOLEAN DEFAULT TRUE, -- Best image for this game (largest/clearest)
    
    -- Processing results
    object_count    INTEGER,               -- Total objects detected in source photo
    completeness    TEXT DEFAULT 'unknown', -- 'unknown', 'loose', 'boxed', 'partial', 'complete_set'
    
    -- OCR & identification
    ocr_text_raw    TEXT,                  -- All extracted text
    title_guess     TEXT,                  -- Best guess at game title
    title_confidence REAL,                 -- 0.0 - 1.0
    platform_guess  TEXT,                  -- e.g., "PS2", "NES", "SNES"
    language        TEXT DEFAULT 'en',     -- 'en', 'jp', 'foreign', 'unknown'
    
    -- Manual overrides (set via web UI)
    title_manual    TEXT,                  -- Human-corrected title
    platform_manual TEXT,
    notes           TEXT,
    ebay_listed     BOOLEAN DEFAULT FALSE,
    ebay_listing_id TEXT,
    
    -- Flags
    needs_review    BOOLEAN DEFAULT FALSE,
    review_reason   TEXT,                  -- Why flagged
    
    -- Timestamps
    processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- Unique constraint: same source file + object index
    UNIQUE(source_hash, object_index)
);

-- Images stored as BLOBs for portability
CREATE TABLE item_images (
    image_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER REFERENCES items(item_id) ON DELETE CASCADE,
    image_type      TEXT,                  -- 'full', 'thumb', 'context', 'group_original'
    image_blob      BLOB,                  -- JPEG data
    width           INTEGER,
    height          INTEGER,
    file_size       INTEGER,               -- Bytes
    is_cover        BOOLEAN DEFAULT FALSE, -- Recommended image for listings
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Processing log for resume capability
CREATE TABLE processing_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path     TEXT,
    source_hash     TEXT UNIQUE,           -- Unique to prevent re-processing
    status          TEXT,                  -- 'success', 'failed', 'skipped'
    items_created   INTEGER,               -- How many items resulted (1, 2, or 3)
    error_message   TEXT,
    processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_items_box ON items(box_id);
CREATE INDEX idx_items_title ON items(title_guess);
CREATE INDEX idx_items_platform ON items(platform_guess);
CREATE INDEX idx_items_needs_review ON items(needs_review);
CREATE INDEX idx_items_ebay ON items(ebay_listed);
CREATE INDEX idx_items_group ON items(source_item_group);
CREATE INDEX idx_log_hash ON processing_log(source_hash);
CREATE INDEX idx_images_item ON item_images(item_id);
CREATE INDEX idx_images_cover ON item_images(is_cover);
```

### 1.9 CLI Interface

#### Processing Commands

```bash
# Basic usage
python cataloguer.py process \
    --input-dir-1 /path/to/NEX3N/photos \
    --input-dir-2 /path/to/RX100/photos \
    --database ./collection.db \
    --done-dir ./processed_originals

# Options
    --workers 4              # Parallel processing workers (default: CPU count - 1)
    --resume                 # Skip already-processed files (checks source_hash)
    --dry-run                # Show what would be processed, don't execute
    --verbose                # Detailed logging
    --failure-log ./failures.txt  # Log failed files here
```

#### Query Commands (TUI/CLI)

For users who prefer command-line workflows over the web UI:

```bash
# Search items
viscatalog search "zelda"                          # Full-text search
viscatalog search "mario" --platform NES           # Filter by platform
viscatalog search --box BOX-7                      # All items in a box
viscatalog search --unlisted --limit 50            # Items not yet on eBay

# Display formats
viscatalog search "zelda" --format table           # Rich table (default)
viscatalog search "zelda" --format json            # JSON output
viscatalog search "zelda" --format csv             # CSV for spreadsheets

# Item details
viscatalog show 1234                               # Full details for item ID
viscatalog show 1234 --open                        # Open image in default viewer

# List/browse
viscatalog list --boxes                            # List all boxes with item counts
viscatalog list --box BOX-7                        # Items in specific box
viscatalog list --needs-review                     # Flagged items
viscatalog list --recent 20                        # Last 20 processed

# Statistics
viscatalog stats                                   # Collection overview
viscatalog stats --by-platform                     # Breakdown by platform
viscatalog stats --by-box                          # Items per box

# Bulk operations
viscatalog mark-listed 1234 1235 1236              # Mark items as eBay listed
viscatalog set-platform 1234 1235 --platform PS2   # Bulk update platform
viscatalog export --unlisted --format csv > todo.csv

# Database management
viscatalog reprocess --item-id 1234                # Re-run processing on item
viscatalog vacuum                                  # Compact database
viscatalog backup --output ./backup.db            # Create backup copy
```

**Example TUI output:**

```
$ viscatalog search "zelda" --format table

┏━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┓
┃ ID    ┃ Title                      ┃ Platform ┃ Completeness┃ Box    ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━┩
│ 1042  │ Legend of Zelda            │ NES      │ loose       │ BOX-3  │
│ 1043  │ Zelda II: Adventure of Link│ NES      │ loose       │ BOX-3  │
│ 2156  │ Link to the Past           │ SNES     │ boxed       │ BOX-12 │
│ 3891  │ Ocarina of Time            │ N64      │ complete    │ BOX-24 │
│ 4102  │ Wind Waker                 │ GCN      │ complete    │ BOX-31 │
└───────┴────────────────────────────┴──────────┴─────────────┴────────┘

5 items found. Use 'viscatalog show <ID>' for details.
```

#### Other Commands

```bash
# Divider generation
viscatalog generate-dividers --start 1 --end 50 --output ./dividers.pdf

# Web server
viscatalog serve --database ./collection.db --port 8000
viscatalog serve --database ./collection.db --port 8000 --auth  # Enable login
```

### 1.10 Deduplication Strategy

**The Problem:**
Users may accidentally try to process the same photos twice, especially when:
- Re-running after a partial failure
- Copying files between folders (changing paths)
- Re-importing via web UI
- Testing with the same images

**What survives file operations:**

| Identifier | Copy | Rename | Re-export | Move to cloud & back |
|------------|------|--------|-----------|---------------------|
| File path | ❌ | ❌ | ❌ | ❌ |
| Modified timestamp | ❌ | ✅ | ❌ | ❌ |
| EXIF DateTimeOriginal | ✅ | ✅ | ✅ | ✅ |
| SHA256 (file content) | ✅ | ✅ | ❌ | ✅ |
| pHash (perceptual) | ✅ | ✅ | ✅ | ✅ |

**Solution: Two-tier deduplication**

```
┌─────────────────────────────────────────────────────────────────┐
│  TIER 1: SHA256 Hash (fast, exact)                              │
│                                                                 │
│  Before processing any file:                                    │
│  1. Compute SHA256 of file content                              │
│  2. Check processing_log.source_hash                            │
│  3. If exists → SKIP (definitely already processed)             │
│                                                                 │
│  Cost: ~50ms per file (just reads bytes, no decode)             │
├─────────────────────────────────────────────────────────────────┤
│  TIER 2: Perceptual Hash (optional, catches re-exports)         │
│                                                                 │
│  If SHA256 is new but we want extra safety:                     │
│  1. Decode image, compute pHash (64-bit fingerprint)            │
│  2. Compare against existing items' pHash                       │
│  3. If hamming distance < 5 → WARN "looks similar to item #X"   │
│                                                                 │
│  Cost: ~200ms per file (requires decode)                        │
│  Default: OFF (enable with --check-similar)                     │
├─────────────────────────────────────────────────────────────────┤
│  NOT USED: Cosine similarity / CLIP embeddings                  │
│                                                                 │
│  Why not:                                                       │
│  - Much slower (~2s per image for embedding)                    │
│  - Requires comparing against ALL existing embeddings           │
│  - Overkill for duplicate detection                             │
│  - Better saved for "find similar games" feature (V2)           │
└─────────────────────────────────────────────────────────────────┘
```

**Database addition for pHash:**

```sql
ALTER TABLE items ADD COLUMN phash TEXT;  -- 64-bit perceptual hash as hex string
CREATE INDEX idx_items_phash ON items(phash);
```

### 1.11 Web UI Import Considerations

The web UI can offer a "Import from folder" feature, but with important caveats:

**Architecture for web-based import:**

```
┌─────────────────────────────────────────────────────────────────┐
│  Option A: Server-side folder access                            │
│                                                                 │
│  User specifies path on server filesystem:                      │
│    POST /api/import { "path": "/mnt/photos/batch1" }            │
│                                                                 │
│  Pros: Handles large batches, resume works via DB               │
│  Cons: User must have files on server (or mounted share)        │
├─────────────────────────────────────────────────────────────────┤
│  Option B: Browser upload (drag & drop)                         │
│                                                                 │
│  User drags folder into browser:                                │
│    Files uploaded via chunked multipart POST                    │
│                                                                 │
│  Pros: Works from any device                                    │
│  Cons: 5,000 RAW files = ~80GB upload, impractical              │
│        Browser crashes lose progress                            │
├─────────────────────────────────────────────────────────────────┤
│  RECOMMENDATION: Hybrid approach                                │
│                                                                 │
│  • CLI for initial bulk import (5,000 files)                    │
│  • Web UI for small additions (< 100 files at a time)           │
│  • Web UI shows import progress via polling/websocket           │
│  • All imports use same dedup logic (SHA256 check)              │
└─────────────────────────────────────────────────────────────────┘
```

**Web import safeguards:**

1. **Pre-scan phase:** Before processing, scan folder and show:
   - Total files found
   - Already processed (will skip): N files
   - New files to process: M files
   - Estimated time

2. **Batch processing with checkpoints:**
   - Process in batches of 50
   - Commit to DB after each batch
   - If interrupted, resume from last committed batch

3. **Progress persistence:**
   - Store `import_job` record with status
   - Web UI can poll `/api/import/{job_id}/status`
   - Resume button if job was interrupted

4. **Warning for suspicious patterns:**
   - "47 files have pHash matches with existing items. View duplicates?"
   - "No QR codes detected in first 100 images. Are you using dividers?"

**API endpoints for web import:**

```
POST   /api/import/scan     { "path": "/mnt/photos" }  → Preview what would be imported
POST   /api/import/start    { "path": "/mnt/photos" }  → Begin import job
GET    /api/import/{id}     → Job status + progress
POST   /api/import/{id}/pause
POST   /api/import/{id}/resume
DELETE /api/import/{id}     → Cancel job
```

### 1.12 Resume & Safety

**Resume capability:**
- Before processing, compute SHA256 of source file
- Check `processing_log` table for existing entry
- Skip if already processed successfully

**Original file safety:**
- After successful processing: move original to `--done-dir` preserving camera subdirectory structure
- After failed processing: leave in place, log to `--failure-log`
- NEVER delete originals

**Directory structure after processing:**
```
processed_originals/
├── NEX3N/
│   ├── DSC01169.ARW
│   └── DSC01170.ARW
└── RX100/
    ├── DSC00427.JPG
    └── DSC00428.JPG
```

### 1.13 Error Handling

**Philosophy:** Log and continue. Don't stop for individual failures.

```python
# Pseudo-code
for image in sorted_timeline:
    try:
        result = process_image(image)
        log_success(image, result)
        move_to_done(image)
    except Exception as e:
        log_failure(image, str(e))
        # Continue to next image
```

**Failure log format:**
```
2024-01-15T10:23:45 | FAILED | /path/to/DSC00500.ARW | QR decode failed, OCR confidence too low (0.32)
2024-01-15T10:24:12 | FAILED | /path/to/DSC00512.JPG | No contours detected (possible blank image)
```

### 1.14 Dependencies

```
# requirements.txt
rawpy>=0.18.0          # ARW/RAW file handling
opencv-python>=4.8.0   # Image processing
numpy>=1.24.0
pillow>=10.0.0         # Image manipulation
pyzbar>=0.1.9          # QR code detection
pytesseract>=0.3.10    # OCR
tqdm>=4.65.0           # Progress bars
multiprocessing        # (stdlib)
exifread>=3.0.0        # EXIF data extraction
```

---

## Part 2: Web Interface

### 2.1 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client (React)                         │
│                    Mobile-first responsive UI                   │
│                    (iPad / Phone browser)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP/REST
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                            │
│                                                                 │
│  • Serves React static build                                    │
│  • REST API for CRUD operations                                 │
│  • Image serving (decode BLOBs → JPEG response)                 │
│  • Optional: Simple auth (username/password)                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SQLite Database                             │
│                     (collection.db)                             │
│                                                                 │
│  • Portable single file                                         │
│  • Contains all images as BLOBs                                 │
│  • Can be copied to any server                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 API Endpoints

```
# Items
GET    /api/items                    # List with filtering/pagination
GET    /api/items/{id}               # Single item details
PATCH  /api/items/{id}               # Update item (title, completeness, notes, etc.)
DELETE /api/items/{id}               # Delete item

# Images
GET    /api/items/{id}/image/thumb   # Thumbnail JPEG
GET    /api/items/{id}/image/full    # Full-res JPEG
GET    /api/items/{id}/images        # All images for item

# Boxes
GET    /api/boxes                    # List all boxes
GET    /api/boxes/{id}/items         # Items in specific box

# Search
GET    /api/search?q=zelda&platform=NES&completeness=boxed

# Stats
GET    /api/stats                    # Collection overview

# eBay helpers
PATCH  /api/items/{id}/mark-listed   # Mark as listed on eBay
GET    /api/items/unlisted           # Items not yet listed
```

### 2.3 Frontend Features

**Search & Browse:**
- Full-text search across title, OCR text, notes
- Filter by: box, platform, completeness, needs_review, ebay_listed
- Sort by: date added, title, box, platform
- Thumbnail grid view (mobile-optimized)

**Item Detail View:**
- Large zoomable image (pinch-zoom on mobile)
- All metadata fields
- Edit: title, platform, completeness, notes
- "Mark as Listed on eBay" button
- "Flag for Review" button

**Workflow for eBay Listing:**
1. Search/filter to find item
2. View item details & image
3. (In separate tab) Create eBay listing, copy details
4. Return to app, click "Mark as Listed"
5. Optionally paste eBay listing ID

### 2.3 Simple Mode (Non-Technical Users)

For users who've never opened a terminal, the Electron app (or web UI) provides a guided workflow:

**First-Run Experience:**

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   📦 Welcome to Visual Cataloguer                               │
│                                                                 │
│   Catalogue your collection in 3 steps:                         │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  STEP 1: Print Dividers                                 │   │
│   │                                                         │   │
│   │  Download and print these QR code sheets.               │   │
│   │  Place one between each box/section when photographing. │   │
│   │                                                         │   │
│   │  [Download Dividers PDF (BOX 1-50)]                     │   │
│   │                                                         │   │
│   │  Or just write "BOX 1", "BOX 2" etc. on paper           │   │
│   │  with a thick black marker — that works too!            │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  STEP 2: Photograph Your Collection                     │   │
│   │                                                         │   │
│   │  📷 Divider photo (BOX-1)                               │   │
│   │  📷 Item photo                                          │   │
│   │  📷 Item photo                                          │   │
│   │  📷 Item photo                                          │   │
│   │  📷 Black/dark photo (signals end of box)               │   │
│   │  📷 Divider photo (BOX-2)                               │   │
│   │  📷 Item photo                                          │   │
│   │  ... and so on                                          │   │
│   │                                                         │   │
│   │  Tip: Use a white background (tablecloth, sheet)        │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  STEP 3: Import Photos                                  │   │
│   │                                                         │   │
│   │  ┌─────────────────────────────────────────────────┐    │   │
│   │  │                                                 │    │   │
│   │  │     Drag & drop your photo folder here         │    │   │
│   │  │                                                 │    │   │
│   │  │        📁  or click to browse                  │    │   │
│   │  │                                                 │    │   │
│   │  └─────────────────────────────────────────────────┘    │   │
│   │                                                         │   │
│   │  Supported: JPG, PNG, ARW, CR2, NEF (RAW files)         │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Import Progress Screen:**

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   📷 Processing your photos...                                  │
│                                                                 │
│   ████████████████░░░░░░░░░░░░░░░░░░  847 / 2,341 photos       │
│                                                                 │
│   Current box: BOX-7                                            │
│   Items found: 312                                              │
│   Time remaining: ~8 minutes                                    │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Latest items:                                          │   │
│   │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐               │   │
│   │  │     │ │     │ │     │ │     │ │     │               │   │
│   │  │ 📀  │ │ 📀  │ │ 📀  │ │ 📀  │ │ 📀  │               │   │
│   │  │     │ │     │ │     │ │     │ │     │               │   │
│   │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘               │   │
│   │  Mario   Zelda   Sonic   Tetris  ???                    │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   ⚠️  3 photos couldn't be read (will show at end)              │
│                                                                 │
│   [Pause]                                      [Cancel Import]  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Post-Import Summary:**

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   ✅ Import Complete!                                           │
│                                                                 │
│   ┌──────────────────────┬──────────────────────┐               │
│   │  Photos processed    │  2,341               │               │
│   │  Items catalogued    │  2,156               │               │
│   │  Boxes created       │  24                  │               │
│   │  Need review         │  47                  │               │
│   │  Failed              │  3                   │               │
│   └──────────────────────┴──────────────────────┘               │
│                                                                 │
│   [Browse Collection]    [Review Problem Items]                 │
│                                                                 │
│   Your database: ~/Documents/my_collection.db                   │
│   (You can back this up or share it)                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key UX Decisions for Simple Mode:**

1. **No configuration required**
   - Database auto-created in Documents folder
   - Sensible defaults for all settings
   - "It just works"

2. **Forgiving input**
   - Mixed formats OK (JPG + RAW in same folder)
   - Photos from multiple cameras OK (sorted by timestamp)
   - No dividers detected? Puts everything in "UNSORTED" box
   - Black frame optional (next QR code also closes previous box)

3. **Progress is never lost**
   - Processing state saved after each photo
   - Close app mid-import? Resume where you left off
   - "Continue previous import" shown on restart

4. **Errors don't block**
   - Failed photos logged, shown at end
   - User can manually add these later
   - "47 items need review" is a task, not an error

5. **Plain language**
   - "Photos that couldn't be read" not "OCR confidence below threshold"
   - "Need review" not "flagged items requiring manual intervention"
   - No mention of SHA256, pHash, EXIF, contours, etc.

**Electron App - Additional Simple Mode Features:**

```
┌─────────────────────────────────────────────────────────────────┐
│  File  Edit  View  Help                              _ □ ✕     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  📁 Open Database...     (if they have existing .db file)       │
│  📷 New Import...        (start fresh)                          │
│  📤 Export to CSV...     (for spreadsheets)                     │
│  🖨️ Print Dividers...    (generate PDF)                         │
│                                                                 │
│  Recent:                                                        │
│  • my_games.db (2,156 items)                                    │
│  • garage_tools.db (847 items)                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Mobile Considerations (for Web UI on iPad/Phone):**

Since your son will use this on iPad:
- Touch-friendly buttons (48px+ tap targets)
- Swipe to mark as listed
- Pinch-zoom on images
- Camera icon to add photos directly from device camera
- Works offline once database is loaded (PWA)

**Ultra-Simple Flow for Absolute Beginners:**

```
Download app → Print dividers → Take photos → Drop folder → Done
     ↓              ↓               ↓            ↓          ↓
  30 seconds    2 minutes      30 minutes    1 click    Browse!
```

No account creation, no cloud sync, no subscription. Your data stays on your device.

### 2.5 Authentication (Optional)

For hosting on VPS:

```python
# Simple HTTP Basic Auth or session-based
# Environment variables:
CATALOGUE_USERNAME=admin
CATALOGUE_PASSWORD=secretpassword
```

For internal LAN: Can be disabled entirely.

### 2.6 Deployment Options

**Option A: Local LAN (simplest)**
```bash
# On home server/NAS
python -m uvicorn app:app --host 0.0.0.0 --port 8000
# Access via http://192.168.1.x:8000 from iPad
```

**Option B: VPS with Auth**
```bash
# Docker deployment
docker run -d \
  -v /path/to/collection.db:/data/collection.db \
  -e CATALOGUE_USERNAME=admin \
  -e CATALOGUE_PASSWORD=secret \
  -p 443:8000 \
  game-cataloguer
```

---

## Part 3: Repository Structure & Deployment

### 3.1 Monorepo Structure

```
game-cataloguer/
├── README.md
├── LICENSE                      # MIT or similar
├── pyproject.toml               # Python package config (for PyPI)
├── Dockerfile
├── docker-compose.yml
│
├── cataloguer/                  # Python package (CLI + API)
│   ├── __init__.py
│   ├── __main__.py              # Entry point: python -m cataloguer
│   ├── cli.py                   # Click-based CLI
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── pipeline.py          # Main processing orchestration
│   │   ├── classifier.py        # Image type detection (divider/black/item)
│   │   ├── qr_detector.py       # QR + OCR fallback for dividers
│   │   ├── item_processor.py    # Contour detection, cropping, deskew
│   │   ├── ocr.py               # Tesseract wrapper
│   │   └── raw_handler.py       # ARW/RAW file support
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── migrations/          # Alembic migrations (future-proofing)
│   │   └── queries.py           # Common query helpers
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI application
│   │   ├── routes/
│   │   │   ├── items.py
│   │   │   ├── boxes.py
│   │   │   ├── images.py
│   │   │   └── search.py
│   │   └── auth.py              # Optional simple auth
│   └── config.py                # Settings via environment variables
│
├── frontend/                    # React application
│   ├── package.json
│   ├── vite.config.js
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── ItemGrid.jsx     # Thumbnail grid view
│   │   │   ├── ItemDetail.jsx   # Full item view + edit
│   │   │   ├── SearchBar.jsx
│   │   │   ├── FilterPanel.jsx
│   │   │   └── ImageViewer.jsx  # Pinch-zoom for mobile
│   │   ├── pages/
│   │   │   ├── Browse.jsx
│   │   │   ├── BoxView.jsx
│   │   │   └── Stats.jsx
│   │   └── api/
│   │       └── client.js        # Fetch wrapper for API calls
│   └── dist/                    # Built assets (served by FastAPI)
│
├── electron/                    # Electron wrapper (optional desktop app)
│   ├── package.json
│   ├── main.js                  # Electron main process
│   ├── preload.js
│   └── build/                   # electron-builder config
│
├── tests/
│   ├── test_classifier.py
│   ├── test_processor.py
│   ├── test_api.py
│   └── fixtures/                # Sample images for testing
│       ├── box_divider_qr.jpg
│       ├── box_divider_handwritten.jpg
│       ├── black_frame.jpg
│       └── game_item_2_objects.jpg
│
└── docs/
    ├── SPEC.md                  # This document
    ├── WORKFLOW.md              # Photography workflow guide
    └── DIVIDER_TEMPLATES/       # Printable QR code sheets
        ├── box_dividers.pdf
        └── generate_dividers.py # Script to generate new QR sheets
```

### 3.2 PyPI Package

**Package name:** `visual-cataloguer` (or `viscatalog` for short CLI)

The visual divider workflow is generic enough to be useful beyond games. The PyPI package exposes:

```bash
# After: pip install visual-cataloguer

# CLI commands
viscatalog process --input ./photos --database ./collection.db
viscatalog serve --database ./collection.db --port 8000
viscatalog export --database ./collection.db --format csv

# Or as module
python -m cataloguer process ...
```

**pyproject.toml (key sections):**

```toml
[project]
name = "visual-cataloguer"
version = "0.1.0"
description = "Batch catalogue physical collections using visual dividers (QR codes) and automated image processing"
readme = "README.md"
license = {text = "MIT"}
authors = [
    {name = "Michael", email = "..."}
]
keywords = ["cataloguing", "inventory", "ocr", "qr-code", "collection", "retro-games"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "Intended Audience :: End Users/Desktop",
    "Topic :: Multimedia :: Graphics :: Capture",
    "Topic :: Database",
]

dependencies = [
    "rawpy>=0.18.0",
    "opencv-python>=4.8.0",
    "numpy>=1.24.0",
    "pillow>=10.0.0",
    "pyzbar>=0.1.9",
    "pytesseract>=0.3.10",
    "tqdm>=4.65.0",
    "exifread>=3.0.0",
    "click>=8.0.0",
    "fastapi>=0.100.0",
    "uvicorn>=0.23.0",
    "sqlalchemy>=2.0.0",
    "python-multipart>=0.0.6",
]

[project.optional-dependencies]
electron = ["pyinstaller"]  # For bundling with Electron
dev = ["pytest", "pytest-cov", "ruff", "mypy"]

[project.scripts]
viscatalog = "cataloguer.cli:main"

[project.urls]
Homepage = "https://github.com/yourusername/visual-cataloguer"
Documentation = "https://github.com/yourusername/visual-cataloguer#readme"
```

### 3.3 Docker Deployment

**Dockerfile:**

```dockerfile
# Multi-stage build
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for OpenCV, Tesseract, pyzbar
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    tesseract-ocr \
    libzbar0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python package
COPY pyproject.toml README.md ./
COPY cataloguer/ ./cataloguer/
RUN pip install --no-cache-dir .

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./cataloguer/api/static

# Default: run web server
ENV DATABASE_PATH=/data/collection.db
ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "cataloguer.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml:**

```yaml
version: '3.8'

services:
  cataloguer:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data                    # Database lives here
      - ./photos:/photos:ro             # Mount photos for processing (read-only)
      - ./processed:/processed          # Done folder
    environment:
      - DATABASE_PATH=/data/collection.db
      - AUTH_USERNAME=${AUTH_USERNAME:-}       # Optional
      - AUTH_PASSWORD=${AUTH_PASSWORD:-}       # Optional
    restart: unless-stopped

  # Optional: run processing as one-off
  # docker-compose run --rm cataloguer-cli process --input /photos --database /data/collection.db
  cataloguer-cli:
    build: .
    volumes:
      - ./data:/data
      - ./photos:/photos:ro
      - ./processed:/processed
    entrypoint: ["viscatalog"]
    profiles: ["cli"]  # Only runs when explicitly called
```

**Usage:**

```bash
# Start web UI
docker-compose up -d

# Run batch processing
docker-compose run --rm cataloguer-cli process \
    --input-dir-1 /photos/NEX3N \
    --input-dir-2 /photos/RX100 \
    --database /data/collection.db \
    --done-dir /processed

# Access web UI
open http://localhost:8000
```

### 3.4 Electron Desktop App

For a fully self-contained desktop experience (no Docker/Python install required):

**Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Electron Shell                           │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │  Main Process   │    │      Renderer (React UI)        │ │
│  │                 │    │                                 │ │
│  │  - Spawns       │◀──▶│  - Same React frontend          │ │
│  │    Python       │    │  - Talks to localhost:8000      │ │
│  │    subprocess   │    │                                 │ │
│  │  - File dialogs │    └─────────────────────────────────┘ │
│  │  - System tray  │                                        │
│  └────────┬────────┘                                        │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────────────────────────────────────────────┐│
│  │           Bundled Python + FastAPI                      ││
│  │           (PyInstaller frozen binary)                   ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

**electron/main.js (simplified):**

```javascript
const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

let pythonProcess;
let mainWindow;

function startPythonServer() {
  const pythonPath = path.join(__dirname, 'python', 'viscatalog');
  pythonProcess = spawn(pythonPath, ['serve', '--port', '8000']);
  
  pythonProcess.stdout.on('data', (data) => {
    console.log(`Python: ${data}`);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js')
    }
  });
  
  // Wait for server, then load
  setTimeout(() => {
    mainWindow.loadURL('http://localhost:8000');
  }, 2000);
}

app.whenReady().then(() => {
  startPythonServer();
  createWindow();
});

app.on('window-all-closed', () => {
  if (pythonProcess) pythonProcess.kill();
  app.quit();
});
```

**Build targets:**
- Windows: `.exe` installer
- macOS: `.dmg`
- Linux: `.AppImage`

### 3.5 Deployment Decision Matrix

| Scenario | Recommended Deployment |
|----------|----------------------|
| Tech-savvy user, has Python | `pip install visual-cataloguer` |
| Home server / NAS | Docker Compose |
| Non-technical user (your son) | Electron app |
| VPS hosting | Docker + nginx reverse proxy |
| Quick demo / development | `viscatalog serve` directly |

---

## Part 4: Future Enhancements (Out of Scope for V1)

These are NOT part of the initial build but noted for future consideration:

1. **IGDB Integration** — Auto-lookup game metadata from IGDB API
2. **Barcode Scanning** — Detect UPC codes for definitive identification  
3. **Vector Search** — Embed images with CLIP for visual similarity search
4. **eBay API Integration** — Create draft listings directly from app
5. **Price Estimation** — Pull recent sold prices from eBay API
6. **Batch Editing** — Select multiple items, apply same platform/completeness

---

## Appendix A: Sample Divider Photo Analysis

Based on your uploaded sample (`DSC00427.JPG`):

- **Format:** White A4 paper on cardboard box background
- **Content:** "BOX-1" text (left) + QR code (right)
- **QR Data:** Plain text `BOX-1`
- **Detection strategy:** Try QR first (fast, reliable), fall back to OCR

The cardboard background and slight paper wrinkles shouldn't affect detection. The QR code is large and high-contrast.

---

## Appendix B: Acceptance Tests

### Box Divider Detection
```
GIVEN an image of white paper with QR code containing "BOX-1"
WHEN processed by the classifier
THEN image_type = 'box_divider' AND box_id = 'BOX-1'
```

### Black Frame Detection
```
GIVEN an image with mean brightness < 10%
WHEN processed by the classifier  
THEN image_type = 'black_frame' AND current_box_id is cleared
```

### Game Item Processing
```
GIVEN an image of 2 objects on white background
WHEN box_id "BOX-1" is active
THEN create item with box_id='BOX-1', object_count=2, completeness='partial'
```

### Resume Capability
```
GIVEN database contains processing_log entry for file hash ABC123
WHEN CLI runs with --resume flag
THEN file with hash ABC123 is skipped
```

### Image Portability
```
GIVEN collection.db file copied to new machine
WHEN web UI loads item detail
THEN thumbnail and full image display correctly (served from BLOB)
```

---

## Appendix C: File Identification (Uniqueness)

**Primary key:** SHA256 hash of original file content

This handles:
- Duplicate filenames from different cameras (DSC00001.JPG from both)
- True duplicates (same file copied twice) — will be skipped on resume
- Multiple copies of same game — different photos = different hashes = different items

**Item ID:** Auto-incrementing integer, assigned at insert time. Used in URLs and cross-references.

---

## Appendix D: Divider Template Generator

The repo includes a utility to generate printable QR code divider sheets:

```bash
# Generate dividers for boxes 1-50
viscatalog generate-dividers --start 1 --end 50 --output ./dividers.pdf

# Custom format
viscatalog generate-dividers --start 1 --end 100 --prefix "STORAGE" --output ./storage_dividers.pdf
# Generates: STORAGE-1, STORAGE-2, ... STORAGE-100
```

**Output format:** A4 PDF, one divider per page, with:
- Large bold text (e.g., "BOX-1") on left — readable by OCR as fallback
- QR code on right — primary detection method
- Crop marks for trimming if desired

**Implementation:**

```python
# docs/DIVIDER_TEMPLATES/generate_dividers.py
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

def generate_divider_pdf(start: int, end: int, prefix: str, output_path: str):
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    
    for i in range(start, end + 1):
        label = f"{prefix}-{i}"
        
        # Large text on left
        c.setFont("Helvetica-Bold", 72)
        c.drawString(2*cm, height/2, label)
        
        # QR code on right
        qr = qrcode.make(label)
        qr_path = f"/tmp/qr_{label}.png"
        qr.save(qr_path)
        c.drawImage(qr_path, width - 10*cm, height/2 - 4*cm, 8*cm, 8*cm)
        
        c.showPage()
    
    c.save()
```

---

## Appendix F: CLI Output Example

```
$ python cataloguer.py process --input-dir-1 ./NEX3N --input-dir-2 ./RX100 --database ./collection.db

Game Collection Cataloguer v1.0
==============================

Scanning directories...
  NEX3N: 2,847 files (.ARW)
  RX100: 2,153 files (.JPG)
  Total: 5,000 files

Building timeline from EXIF data...
  Timeline built: 2024-01-10 09:15:32 → 2024-01-14 16:42:18

Processing with 4 workers...

BOX-1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 147/147
BOX-2 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 203/203
BOX-3 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 89/89
...
BOX-47 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 112/112

Processing complete!
==============================
Total images:     5,000
Items catalogued: 4,892
Boxes created:    47
Failed:           58 (see failures.txt)
Flagged review:   124

Database: ./collection.db (847 MB)
Originals moved to: ./processed_originals/
```

---

## Appendix G: PyPI Package Vision

**The pitch for `visual-cataloguer`:**

> *"Catalogue your physical stuff with your phone camera. Just print QR dividers, photograph batches, and let the tool sort it out."*

**Why it could get traction:**
1. No existing tool does this — verified by searching PyPI, GitHub, ProductHunt
2. Universal need — everyone has *something* they need to inventory
3. Low barrier — works with any camera, even phone photos
4. Offline-first — no cloud dependency, your data stays yours
5. 80-20 philosophy — gets 80% of the work done automatically, you fix the remaining 20%

**Target users:**
- eBay/Mercari sellers cataloguing inventory
- Collectors (games, books, vinyl, comics, cards)
- Estate sale organizers
- Small business inventory
- Hobbyists with workshop tools/supplies
- Anyone moving house who wants to know what's in each box

**Potential README hook:**

```markdown
# 📦 visual-cataloguer

Batch-catalogue your physical collection using visual dividers.

## The Problem
You have 5,000 retro games (or books, or vinyl, or tools) in boxes. 
You need them in a searchable database. Manual entry would take weeks.

## The Solution
1. Print QR code dividers (one per box)
2. Photograph: divider → items → items → items → black frame
3. Run `viscatalog process ./photos`
4. Done. Browse your collection at localhost:8000.

## How it works
- 📷 Merges photos from multiple cameras by timestamp
- 🔍 Detects QR codes (or OCR fallback) to track which box you're in
- ⬛ Black frame = "end of this box"
- ✂️ Auto-crops individual items from photos
- 📝 OCR extracts text (titles, labels)
- 💾 Everything stored in a single portable SQLite file
```
