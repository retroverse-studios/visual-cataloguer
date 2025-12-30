# visual-cataloguer

Batch catalogue physical collections using visual dividers (QR codes) and automated image processing.

## The Problem

You have thousands of items (retro games, books, vinyl, trading cards) stored in boxes. You need them in a searchable database so you can find things and list them on eBay. Manual entry would take weeks.

## The Solution

1. Print QR code dividers (one per storage location)
2. Photograph items one at a time, using dividers to mark location changes
3. Run `viscatalog process ./photos --ai-identify`
4. Search and browse your collection via CLI or web UI

## Scope & Philosophy

**This tool does one thing well:** Process a folder of photographs into a searchable inventory database.

**What it handles:**
- One item per photograph (a "complete in box" game with box + manual + cartridge counts as one item)
- QR code dividers to track storage locations (BOX-1, SHELF-A3, etc.)
- Black frame images to end location sequences
- AI identification of items (title, platform, condition, completeness)
- Reference-quality images for verification (not eBay listing photos)

**What it doesn't do:**
- Multi-item segmentation (photographing 5 cartridges and splitting them)
- Image preprocessing (rotation, cropping, alignment)
- eBay-ready photo processing

The images stored are for *verifying the database is correct*, not for direct use in listings. When you're ready to list an item, you'll retrieve it from storage and take proper detailed photos.

## Workflow

### 1. Prepare Dividers

**Option A: QR codes (recommended)**
Print QR codes containing location IDs:
```
BOX-1    BOX-2    SHELF-A1    GARAGE-BIN-3
```

**Option B: Hand-written/printed text**
Write the location ID on white paper. When AI mode is enabled, the tool will read text dividers automatically. Keep the paper clean - just the location text on white background.

**Black frames:** Put your hand over the lens to create a black image. This signals the end of a location sequence.

### 2. Photograph Your Collection

```
[QR: BOX-1] → [Item] → [Item] → [Item] → [BLACK] → [QR: BOX-2] → [Item] → ...
```

**Rules:**
- One item per photo
- Complete sets (box + game + manual) in one photo = one item
- QR code starts a new location
- Black frame ends the current location (optional, but helps with organization)
- Multiple cameras OK - images merge by EXIF timestamp

### 3. Process Images

```bash
# Default: Auto-detects AI (tries Ollama first, then Claude)
viscatalog process ./photos

# Force a specific provider
viscatalog process ./photos --provider ollama
viscatalog process ./photos --provider claude

# Offline mode: QR/OCR only, no AI
viscatalog process ./photos --offline

# Use a specific model
viscatalog process ./photos --provider ollama --model llava:13b
```

The tool auto-detects available AI providers: Ollama (free, local) is preferred, with Claude as fallback if `ANTHROPIC_API_KEY` is set.

### 4. Review & Correct

```bash
# View stats
viscatalog stats

# List items needing review
viscatalog list --unknown           # No title identified
viscatalog list --low-confidence    # AI uncertain
viscatalog list --needs-review      # Flagged for review

# View item details
viscatalog show 42

# Manually correct
viscatalog edit 42 --title "Super Mario Bros." --platform NES

# Re-run AI identification
viscatalog reidentify 42 --provider claude
```

### 5. Browse & Search

```bash
# Search
viscatalog search "zelda"

# List by location
viscatalog list --location BOX-1

# Web interface
viscatalog serve --port 8000
# Open http://localhost:8000
```

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Load Image  │────▶│     AI      │────▶│   Process   │
│ (ARW/JPG)   │     │  Classify   │     │ Accordingly │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
     ┌──────────┐    ┌──────────┐    ┌──────────┐
     │ LOCATION │    │  BLACK   │    │   ITEM   │
     │ DIVIDER  │    │  FRAME   │    │          │
     └──────────┘    └──────────┘    └──────────┘
          │               │               │
          ▼               ▼               ▼
     Set current     Clear current    Store item
     location        location         in database
```

**AI-First Architecture:** A single AI call classifies the image type AND identifies item details. This handles QR codes, handwritten text, stylized logos, and Japanese text seamlessly.

## AI Identification

By default, the tool uses vision AI (Ollama) to classify and identify items:

| Field | Example |
|-------|---------|
| Title | "Super Mario Bros. 3" |
| Platform | "NES" |
| Item Type | game, console, controller, book, vinyl, etc. |
| Completeness | loose, boxed, complete_set, sealed |
| Brand | "Nintendo" |
| Region | NTSC-U, PAL, NTSC-J |
| Year | "1990" |
| Condition | mint, good, fair, poor |
| Condition Notes | "Box has shelf wear on corners, manual has light creasing" |

Supports:
- **Claude** (default) - requires `ANTHROPIC_API_KEY` environment variable
- **Ollama** - local, free, use `--ai-provider ollama`

## Features

- **Multi-camera support**: Merges photos from multiple cameras by EXIF timestamp
- **RAW file support**: Sony ARW, Canon CR2/CR3, Nikon NEF, and more via rawpy
- **QR code detection**: OpenCV-based with OCR fallback
- **SQLite database**: Single portable file with images stored as BLOBs
- **Resume capability**: SHA256 deduplication skips already-processed files
- **Web interface**: Browse, search, edit, and manage your collection
- **REST API**: Integrate with other tools
- **Duplicate divider handling**: Multiple QR codes or black frames in a row are handled gracefully

## Installation

```bash
# From PyPI
pip install visual-cataloguer

# With web interface
pip install visual-cataloguer[web]

# Or with uv
uv pip install visual-cataloguer[web]
```

**System dependencies:**
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract): `brew install tesseract` (macOS) or `apt install tesseract-ocr` (Linux)

**For AI identification:**
- Claude: Set `ANTHROPIC_API_KEY` environment variable
- Ollama: Install from [ollama.ai](https://ollama.ai) and run `ollama pull llava`

## CLI Reference

```bash
# Processing (auto-detects AI provider)
viscatalog process <input-dir> [--provider auto|ollama|claude] [--model MODEL] [--offline]

# Viewing
viscatalog stats
viscatalog list [--location LOC] [--platform PLAT] [--unknown] [--low-confidence] [--needs-review]
viscatalog search <query>
viscatalog show <item-id> [--json]

# Editing
viscatalog edit <item-id> [--title T] [--platform P] [--completeness C] [--notes N]
viscatalog reidentify <item-id> [--provider P] [--model M] [--image PATH]
viscatalog review <item-id> [--done | --flag --reason R]

# Export
viscatalog export <output-dir>                    # Export images by location
viscatalog export ./data.csv --format csv         # Export metadata as CSV
viscatalog export ./data.json --format json       # Export metadata as JSON
viscatalog export ./images --include-metadata     # Images + JSON sidecar files

# Web server
viscatalog serve [--port 8000] [--host 0.0.0.0]
```

## API Endpoints

```bash
# Items
GET    /api/items                    # List items (with filters)
GET    /api/items/{id}               # Get item
PATCH  /api/items/{id}               # Update item
DELETE /api/items/{id}               # Delete item
POST   /api/items/{id}/reidentify    # Re-run AI identification

# Images
GET    /api/items/{id}/images        # List item images
GET    /api/items/{id}/image/thumb   # Get thumbnail
GET    /api/items/{id}/image/full    # Get full image
POST   /api/items/{id}/images        # Upload image

# Other
GET    /api/locations                # List locations
GET    /api/search?q=query           # Search items
GET    /api/stats                    # Collection statistics
```

Full OpenAPI docs at `http://localhost:8000/docs`

## Database Schema

SQLite database with tables:
- `items` - Catalogued items with metadata
- `item_images` - Images stored as JPEG BLOBs (one-to-many with items)
- `locations` - Storage locations (BOX-1, SHELF-A3, etc.)
- `processing_log` - Tracks processed files for resume

## Development

```bash
git clone https://github.com/retroverse-studios/visual-cataloguer.git
cd visual-cataloguer
uv sync --extra web --extra dev

# Run tests
uv run pytest

# Type checking
uv run mypy cataloguer

# Linting
uv run ruff check cataloguer
```

## License

MIT License - see [LICENSE](LICENSE)
