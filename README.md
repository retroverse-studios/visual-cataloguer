# visual-cataloguer

Batch catalogue physical collections using visual dividers (QR codes) and automated image processing.

## The Problem

You have thousands of items (retro games, books, vinyl, tools) in boxes. You need them in a searchable database. Manual entry would take weeks.

## The Solution

1. Print QR code dividers (one per location/box/shelf)
2. Photograph: `divider → items → items → black frame → divider → ...`
3. Run `viscatalog process ./photos`
4. Browse your collection via web UI or CLI

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Load Image  │────▶│  Classify   │────▶│   Process   │
│ (ARW/JPG)   │     │ Image Type  │     │ Accordingly │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
     ┌──────────┐    ┌──────────┐    ┌──────────┐
     │ LOCATION │    │  BLACK   │    │   GAME   │
     │ DIVIDER  │    │  FRAME   │    │   ITEM   │
     └──────────┘    └──────────┘    └──────────┘
```

- **Location Divider**: QR code or text (e.g., "BOX-1", "SHELF-A3") - starts a new location
- **Black Frame**: Dark image - ends current location
- **Game Item**: Everything else - catalogued with OCR

## Features

- Merges photos from multiple cameras by EXIF timestamp
- QR code detection (OpenCV) + OCR fallback (Tesseract)
- RAW file support (.ARW Sony files via rawpy)
- SQLite database with JPEG BLOBs (single portable file)
- SHA256 deduplication for resume capability
- **Web interface** for browsing, searching, and editing
- Mobile-friendly UI (works on iPad/phone)
- Robust error recovery (auto-creates UNKNOWN boxes for missed dividers)

## Installation

```bash
# From PyPI
pip install visual-cataloguer

# With web interface support
pip install visual-cataloguer[web]

# Or clone and install
git clone https://github.com/retroverse-studios/visual-cataloguer.git
cd visual-cataloguer
uv sync --extra web
```

**System dependencies:**
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) - `brew install tesseract`

## Usage

### Process Images

```bash
# Process all images in a directory (scans recursively)
viscatalog process -i ./photos -d ./collection.db

# Works with any folder structure:
#   ./photos/
#   ├── camera1/         (RAW files)
#   ├── camera2/         (JPEGs)
#   └── day2/
#       ├── alice/       (mixed formats)
#       └── bob/

# View statistics
viscatalog stats -d ./collection.db

# List locations
viscatalog list --locations -d ./collection.db

# Search items
viscatalog search "zelda" -d ./collection.db
```

### Web Interface

```bash
# Start the web server
viscatalog serve -d ./collection.db --port 8000

# Then open http://localhost:8000
```

The web interface provides:
- **Browse**: Grid view of all items with thumbnails
- **Search**: Full-text search across titles and OCR text
- **Filter**: By location, platform, completeness, listed/unlisted status
- **Edit**: Update titles, platforms, notes, and location assignments
- **eBay workflow**: Mark items as listed

### API

The web server exposes a REST API:

```bash
# List items
curl http://localhost:8000/api/items

# Search
curl "http://localhost:8000/api/search?q=zelda"

# Get item details
curl http://localhost:8000/api/items/123

# Update item (e.g., reassign to different location)
curl -X PATCH http://localhost:8000/api/items/123 \
  -H "Content-Type: application/json" \
  -d '{"location_id": "SHELF-A3", "title_manual": "Legend of Zelda"}'

# Mark as listed on eBay
curl -X PATCH http://localhost:8000/api/items/123/mark-listed

# Get stats
curl http://localhost:8000/api/stats
```

Full API docs at `http://localhost:8000/docs`

## Development

```bash
# Run tests
uv run pytest

# Type checking
uv run mypy cataloguer

# Linting
uv run ruff check cataloguer
```

## License

MIT License - see [LICENSE](LICENSE)
