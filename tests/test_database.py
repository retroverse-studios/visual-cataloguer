"""Tests for the database module."""

import tempfile
from pathlib import Path

import pytest

from cataloguer.database.models import Database, Item, init_db


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def db(temp_db: Path) -> Database:
    """Create a database instance."""
    return Database(temp_db)


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_init_creates_tables(self, temp_db: Path) -> None:
        """Test that init_db creates all required tables."""
        init_db(temp_db)

        import sqlite3

        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "boxes" in tables
        assert "items" in tables
        assert "item_images" in tables
        assert "processing_log" in tables


class TestBoxOperations:
    """Tests for box CRUD operations."""

    def test_create_box(self, db: Database) -> None:
        """Test creating a box."""
        db.create_box("BOX-1", "First Box")
        box = db.get_box("BOX-1")

        assert box is not None
        assert box.box_id == "BOX-1"
        assert box.label == "First Box"

    def test_get_nonexistent_box(self, db: Database) -> None:
        """Test getting a box that doesn't exist."""
        box = db.get_box("NONEXISTENT")
        assert box is None


class TestItemOperations:
    """Tests for item CRUD operations."""

    def test_create_item(self, db: Database) -> None:
        """Test creating an item."""
        db.create_box("BOX-1")
        item = Item(
            box_id="BOX-1",
            source_filename="test.jpg",
            source_hash="abc123",
            title_guess="Test Game",
        )
        item_id = db.create_item(item)

        assert item_id > 0


class TestProcessingLog:
    """Tests for processing log operations."""

    def test_is_processed_false(self, db: Database) -> None:
        """Test checking unprocessed file."""
        assert db.is_processed("nonexistent_hash") is False

    def test_is_processed_true(self, db: Database) -> None:
        """Test checking processed file."""
        db.log_processing("/path/to/file.jpg", "hash123", "success", items_created=1)
        assert db.is_processed("hash123") is True

    def test_is_processed_failed_not_counted(self, db: Database) -> None:
        """Test that failed processing is not counted as processed."""
        db.log_processing("/path/to/file.jpg", "hash456", "failed", error_message="Error")
        assert db.is_processed("hash456") is False


class TestStats:
    """Tests for statistics."""

    def test_empty_stats(self, db: Database) -> None:
        """Test stats on empty database."""
        stats = db.get_stats()

        assert stats["total_items"] == 0
        assert stats["total_boxes"] == 0
        assert stats["needs_review"] == 0
