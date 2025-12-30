"""SQLite database models for visual-cataloguer.

Uses raw sqlite3 for simplicity and portability - no ORM overhead.
The database stores images as BLOBs for single-file portability.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Location:
    """Location/container tracking (box, shelf, room, etc.)."""

    location_id: str  # e.g., "BOX-1", "SHELF-A3", "GARAGE-RACK2-BIN3"
    label: str | None = None
    notes: str | None = None
    created_at: datetime | None = None


@dataclass
class Item:
    """Individual game/item record."""

    item_id: int | None = None
    location_id: str | None = None

    # Source info
    source_camera: str | None = None  # "NEX-3N" or "RX100M4"
    source_filename: str | None = None
    source_hash: str | None = None  # SHA256 of original file
    captured_at: datetime | None = None  # EXIF DateTimeOriginal

    # Multi-object grouping
    source_item_group: str | None = None  # UUID linking items from same photo
    object_index: int = 1  # Position in original (1, 2, 3...)
    is_primary_image: bool = True  # Best image for this game

    # Item type and AI identification
    item_type: str = "game"  # game, console, controller, accessory, peripheral, etc.
    ai_description: str | None = None  # Full LLM description (JSON)
    ai_identified: bool = False  # Whether AI was used for identification

    # Processing results
    object_count: int | None = None  # Total objects detected in source photo
    completeness: str = "unknown"  # 'unknown', 'loose', 'boxed', 'partial', 'complete_set'

    # OCR & identification
    ocr_text_raw: str | None = None  # All extracted text
    title_guess: str | None = None  # Best guess at game title
    title_confidence: float | None = None  # 0.0 - 1.0
    platform_guess: str | None = None  # e.g., "PS2", "NES", "SNES"
    brand: str | None = None  # Nintendo, Sony, Sega, etc.
    region: str | None = None  # NTSC-U, PAL, NTSC-J
    year: str | None = None  # Release year
    language: str = "en"  # 'en', 'jp', 'foreign', 'unknown'
    condition_notes: str | None = None  # AI notes on physical condition

    # Manual overrides
    title_manual: str | None = None
    platform_manual: str | None = None
    notes: str | None = None
    ebay_listed: bool = False
    ebay_listing_id: str | None = None

    # Flags
    needs_review: bool = False
    review_reason: str | None = None

    # Perceptual hash for deduplication
    phash: str | None = None

    # Timestamps
    processed_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ItemImage:
    """Image stored as BLOB for portability."""

    image_id: int | None = None
    item_id: int | None = None
    image_type: str = "full"  # 'full', 'thumb', 'context', 'group_original'
    image_blob: bytes | None = None  # JPEG data
    width: int | None = None
    height: int | None = None
    file_size: int | None = None  # Bytes
    is_cover: bool = False  # Recommended image for listings
    created_at: datetime | None = None


@dataclass
class ProcessingLog:
    """Processing log for resume capability."""

    log_id: int | None = None
    source_path: str | None = None
    source_hash: str | None = None  # Unique to prevent re-processing
    status: str = "pending"  # 'success', 'failed', 'skipped'
    items_created: int = 0  # How many items resulted
    error_message: str | None = None
    processed_at: datetime | None = None


# SQL Schema
SCHEMA = """
-- Location/container tracking (box, shelf, room, etc.)
CREATE TABLE IF NOT EXISTS locations (
    location_id     TEXT PRIMARY KEY,
    label           TEXT,
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Individual items (games, consoles, controllers, books, vinyl, etc.)
CREATE TABLE IF NOT EXISTS items (
    item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id     TEXT REFERENCES locations(location_id),

    -- Source info
    source_camera   TEXT,
    source_filename TEXT,
    source_hash     TEXT,
    captured_at     DATETIME,

    -- Multi-object grouping
    source_item_group TEXT,
    object_index    INTEGER DEFAULT 1,
    is_primary_image BOOLEAN DEFAULT TRUE,

    -- Item type and AI identification
    item_type       TEXT DEFAULT 'game',
    ai_description  TEXT,
    ai_identified   BOOLEAN DEFAULT FALSE,

    -- Processing results
    object_count    INTEGER,
    completeness    TEXT DEFAULT 'unknown',

    -- OCR & identification
    ocr_text_raw    TEXT,
    title_guess     TEXT,
    title_confidence REAL,
    platform_guess  TEXT,
    brand           TEXT,
    region          TEXT,
    year            TEXT,
    language        TEXT DEFAULT 'en',
    condition_notes TEXT,

    -- Manual overrides
    title_manual    TEXT,
    platform_manual TEXT,
    notes           TEXT,
    ebay_listed     BOOLEAN DEFAULT FALSE,
    ebay_listing_id TEXT,

    -- Flags
    needs_review    BOOLEAN DEFAULT FALSE,
    review_reason   TEXT,

    -- Perceptual hash
    phash           TEXT,

    -- Timestamps
    processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Unique constraint
    UNIQUE(source_hash, object_index)
);

-- Images stored as BLOBs for portability
CREATE TABLE IF NOT EXISTS item_images (
    image_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER REFERENCES items(item_id) ON DELETE CASCADE,
    image_type      TEXT,
    image_blob      BLOB,
    width           INTEGER,
    height          INTEGER,
    file_size       INTEGER,
    is_cover        BOOLEAN DEFAULT FALSE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Processing log for resume capability
CREATE TABLE IF NOT EXISTS processing_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path     TEXT,
    source_hash     TEXT UNIQUE,
    status          TEXT,
    items_created   INTEGER,
    error_message   TEXT,
    processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_items_location ON items(location_id);
CREATE INDEX IF NOT EXISTS idx_items_title ON items(title_guess);
CREATE INDEX IF NOT EXISTS idx_items_platform ON items(platform_guess);
CREATE INDEX IF NOT EXISTS idx_items_item_type ON items(item_type);
CREATE INDEX IF NOT EXISTS idx_items_needs_review ON items(needs_review);
CREATE INDEX IF NOT EXISTS idx_items_ebay ON items(ebay_listed);
CREATE INDEX IF NOT EXISTS idx_items_group ON items(source_item_group);
CREATE INDEX IF NOT EXISTS idx_items_phash ON items(phash);
CREATE INDEX IF NOT EXISTS idx_log_hash ON processing_log(source_hash);
CREATE INDEX IF NOT EXISTS idx_images_item ON item_images(item_id);
CREATE INDEX IF NOT EXISTS idx_images_cover ON item_images(is_cover);
"""


def init_db(db_path: Path) -> None:
    """Initialize the database with schema."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


@contextmanager
def get_session(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Get a database connection as a context manager."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class Database:
    """Database operations for visual-cataloguer."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        init_db(db_path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_location(self, location_id: str, label: str | None = None) -> None:
        """Create or update a location record."""
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO locations (location_id, label) VALUES (?, ?)",
                (location_id, label),
            )

    def get_location(self, location_id: str) -> Location | None:
        """Get a location by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM locations WHERE location_id = ?", (location_id,)
            ).fetchone()
            if row:
                return Location(
                    location_id=row["location_id"],
                    label=row["label"],
                    notes=row["notes"],
                    created_at=row["created_at"],
                )
        return None

    def is_processed(self, source_hash: str) -> bool:
        """Check if a file has already been processed."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM processing_log WHERE source_hash = ? AND status = 'success'",
                (source_hash,),
            ).fetchone()
            return row is not None

    def log_processing(
        self,
        source_path: str,
        source_hash: str,
        status: str,
        items_created: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Log a processing result."""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processing_log
                (source_path, source_hash, status, items_created, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_path, source_hash, status, items_created, error_message),
            )

    def create_item(self, item: Item) -> int:
        """Create a new item and return its ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO items (
                    location_id, source_camera, source_filename, source_hash, captured_at,
                    source_item_group, object_index, is_primary_image,
                    item_type, ai_description, ai_identified,
                    object_count, completeness,
                    ocr_text_raw, title_guess, title_confidence, platform_guess,
                    brand, region, year, language, condition_notes,
                    needs_review, review_reason, phash, ebay_listed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.location_id,
                    item.source_camera,
                    item.source_filename,
                    item.source_hash,
                    item.captured_at,
                    item.source_item_group,
                    item.object_index,
                    item.is_primary_image,
                    item.item_type,
                    item.ai_description,
                    item.ai_identified,
                    item.object_count,
                    item.completeness,
                    item.ocr_text_raw,
                    item.title_guess,
                    item.title_confidence,
                    item.platform_guess,
                    item.brand,
                    item.region,
                    item.year,
                    item.language,
                    item.condition_notes,
                    item.needs_review,
                    item.review_reason,
                    item.phash,
                    item.ebay_listed,
                ),
            )
            return cursor.lastrowid or 0

    def add_image(
        self,
        item_id: int,
        image_type: str,
        image_blob: bytes,
        width: int,
        height: int,
        is_cover: bool = False,
    ) -> int:
        """Add an image to an item."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO item_images (item_id, image_type, image_blob, width, height, file_size, is_cover)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, image_type, image_blob, width, height, len(image_blob), is_cover),
            )
            return cursor.lastrowid or 0

    def get_stats(self) -> dict[str, int]:
        """Get collection statistics."""
        with self.connection() as conn:
            stats: dict[str, int] = {}

            row = conn.execute("SELECT COUNT(*) FROM items").fetchone()
            stats["total_items"] = row[0] if row else 0

            row = conn.execute("SELECT COUNT(*) FROM locations").fetchone()
            stats["total_locations"] = row[0] if row else 0

            row = conn.execute("SELECT COUNT(*) FROM items WHERE needs_review = 1").fetchone()
            stats["needs_review"] = row[0] if row else 0

            row = conn.execute("SELECT COUNT(*) FROM items WHERE ebay_listed = 1").fetchone()
            stats["ebay_listed"] = row[0] if row else 0

            row = conn.execute(
                "SELECT COUNT(*) FROM processing_log WHERE status = 'success'"
            ).fetchone()
            stats["processed_files"] = row[0] if row else 0

            row = conn.execute(
                "SELECT COUNT(*) FROM processing_log WHERE status = 'failed'"
            ).fetchone()
            stats["failed_files"] = row[0] if row else 0

            return stats

    def get_item(self, item_id: int) -> Item | None:
        """Get an item by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM items WHERE item_id = ?", (item_id,)
            ).fetchone()
            if not row:
                return None
            return Item(
                item_id=row["item_id"],
                location_id=row["location_id"],
                source_camera=row["source_camera"],
                source_filename=row["source_filename"],
                source_hash=row["source_hash"],
                captured_at=row["captured_at"],
                source_item_group=row["source_item_group"],
                object_index=row["object_index"] or 1,
                is_primary_image=bool(row["is_primary_image"]),
                item_type=row["item_type"] or "game",
                ai_description=row["ai_description"],
                ai_identified=bool(row["ai_identified"]),
                object_count=row["object_count"],
                completeness=row["completeness"] or "unknown",
                ocr_text_raw=row["ocr_text_raw"],
                title_guess=row["title_guess"],
                title_confidence=row["title_confidence"],
                platform_guess=row["platform_guess"],
                brand=row["brand"],
                region=row["region"],
                year=row["year"],
                language=row["language"] or "en",
                condition_notes=row["condition_notes"],
                title_manual=row["title_manual"],
                platform_manual=row["platform_manual"],
                notes=row["notes"],
                ebay_listed=bool(row["ebay_listed"]),
                ebay_listing_id=row["ebay_listing_id"],
                needs_review=bool(row["needs_review"]),
                review_reason=row["review_reason"],
                phash=row["phash"],
                processed_at=row["processed_at"],
                updated_at=row["updated_at"],
            )

    def update_item(self, item_id: int, **fields: str | int | float | bool | None) -> bool:
        """Update item fields. Returns True if item was updated."""
        if not fields:
            return False

        # Build dynamic UPDATE query
        valid_fields = {
            "location_id", "item_type", "completeness", "title_guess", "title_confidence",
            "platform_guess", "brand", "region", "year", "language", "condition_notes",
            "title_manual", "platform_manual", "notes", "ebay_listed", "ebay_listing_id",
            "needs_review", "review_reason", "ai_description", "ai_identified", "ocr_text_raw",
        }

        # Filter to only valid fields
        updates = {k: v for k, v in fields.items() if k in valid_fields}
        if not updates:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())
        values.append(item_id)

        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE items SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE item_id = ?",
                values,
            )
            return cursor.rowcount > 0

    def get_item_image(self, item_id: int, image_type: str = "full") -> bytes | None:
        """Get image blob for an item."""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT image_blob FROM item_images
                WHERE item_id = ? AND image_type = ?
                ORDER BY is_cover DESC, created_at DESC
                LIMIT 1
                """,
                (item_id, image_type),
            ).fetchone()
            if row:
                return bytes(row["image_blob"])
            # Fallback to any image if requested type not found
            if image_type != "full":
                row = conn.execute(
                    """
                    SELECT image_blob FROM item_images
                    WHERE item_id = ?
                    ORDER BY is_cover DESC, created_at DESC
                    LIMIT 1
                    """,
                    (item_id,),
                ).fetchone()
                if row:
                    return bytes(row["image_blob"])
            return None

    def get_item_images_info(self, item_id: int) -> list[dict[str, int | str | bool]]:
        """Get metadata about all images for an item."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT image_id, image_type, width, height, file_size, is_cover
                FROM item_images
                WHERE item_id = ?
                ORDER BY is_cover DESC, created_at DESC
                """,
                (item_id,),
            ).fetchall()
            return [
                {
                    "image_id": row["image_id"],
                    "image_type": row["image_type"],
                    "width": row["width"],
                    "height": row["height"],
                    "file_size": row["file_size"],
                    "is_cover": bool(row["is_cover"]),
                }
                for row in rows
            ]
