# visual-cataloguer

Batch catalogue physical collections using visual dividers (QR codes) and automated image processing.

## The Problem

You have thousands of items (retro games, books, vinyl, tools) in boxes. You need them in a searchable database. Manual entry would take weeks.

## The Solution

1. Print QR code dividers (one per box)
2. Photograph: `divider → items → items → black frame → divider → ...`
3. Run `viscatalog process ./photos`
4. Browse your collection

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
     │   BOX    │    │  BLACK   │    │   GAME   │
     │ DIVIDER  │    │  FRAME   │    │   ITEM   │
     └──────────┘    └──────────┘    └──────────┘
```

- **Box Divider**: QR code or text (e.g., "BOX-1") - starts a new box
- **Black Frame**: Dark image - ends current box
- **Game Item**: Everything else - catalogued with OCR

## Features

- Merges photos from multiple cameras by EXIF timestamp
- QR code detection (OpenCV) + OCR fallback (Tesseract)
- RAW file support (.ARW Sony files via rawpy)
- SQLite database with JPEG BLOBs (single portable file)
- SHA256 deduplication for resume capability

## Installation

```bash
# Clone and install
git clone https://github.com/retroverse-studios/visual-cataloguer.git
cd visual-cataloguer
uv sync
```

**System dependencies:**
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) - `brew install tesseract`

## Usage

```bash
# Process images from two cameras
viscatalog process \
    --input-dir-1 ./NEX3N \
    --input-dir-2 ./RX100 \
    --database ./collection.db

# View statistics
viscatalog stats -d ./collection.db

# List boxes
viscatalog list --boxes -d ./collection.db

# Search items
viscatalog search "zelda" -d ./collection.db
```

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
