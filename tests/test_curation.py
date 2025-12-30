"""Tests for curation features (database methods, CLI commands, API endpoints)."""

import tempfile
from pathlib import Path

import pytest

from cataloguer.database.models import Database, Item


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def db(temp_db: Path) -> Database:
    """Create a database instance."""
    return Database(temp_db)


@pytest.fixture
def sample_item(db: Database) -> int:
    """Create a sample item and return its ID."""
    db.create_location("BOX-1")
    item = Item(
        location_id="BOX-1",
        source_filename="test.jpg",
        source_hash="abc123",
        title_guess="Test Game",
        platform_guess="NES",
        item_type="game",
        title_confidence=0.8,
    )
    return db.create_item(item)


class TestDatabaseGetItem:
    """Tests for Database.get_item method."""

    def test_get_item_exists(self, db: Database, sample_item: int) -> None:
        """Test getting an existing item."""
        item = db.get_item(sample_item)

        assert item is not None
        assert item.item_id == sample_item
        assert item.title_guess == "Test Game"
        assert item.platform_guess == "NES"
        assert item.item_type == "game"
        assert item.title_confidence == 0.8

    def test_get_item_not_found(self, db: Database) -> None:
        """Test getting a non-existent item."""
        item = db.get_item(99999)
        assert item is None

    def test_get_item_returns_all_fields(self, db: Database) -> None:
        """Test that get_item returns all expected fields."""
        db.create_location("LOC-1")
        item = Item(
            location_id="LOC-1",
            source_filename="full_test.jpg",
            source_hash="full123",
            title_guess="Full Test",
            platform_guess="SNES",
            item_type="console",
            brand="Nintendo",
            region="NTSC-U",
            year="1995",
            completeness="boxed",
            needs_review=True,
            review_reason="Check condition",
        )
        item_id = db.create_item(item)

        retrieved = db.get_item(item_id)
        assert retrieved is not None
        assert retrieved.brand == "Nintendo"
        assert retrieved.region == "NTSC-U"
        assert retrieved.year == "1995"
        assert retrieved.completeness == "boxed"
        assert retrieved.needs_review is True
        assert retrieved.review_reason == "Check condition"


class TestDatabaseUpdateItem:
    """Tests for Database.update_item method."""

    def test_update_single_field(self, db: Database, sample_item: int) -> None:
        """Test updating a single field."""
        result = db.update_item(sample_item, title_manual="Super Mario Bros")

        assert result is True
        item = db.get_item(sample_item)
        assert item is not None
        assert item.title_manual == "Super Mario Bros"

    def test_update_multiple_fields(self, db: Database, sample_item: int) -> None:
        """Test updating multiple fields at once."""
        result = db.update_item(
            sample_item,
            title_manual="Updated Title",
            platform_manual="SNES",
            completeness="complete_set",
            brand="Nintendo",
        )

        assert result is True
        item = db.get_item(sample_item)
        assert item is not None
        assert item.title_manual == "Updated Title"
        assert item.platform_manual == "SNES"
        assert item.completeness == "complete_set"
        assert item.brand == "Nintendo"

    def test_update_review_fields(self, db: Database, sample_item: int) -> None:
        """Test updating review-related fields."""
        # Flag for review
        db.update_item(sample_item, needs_review=True, review_reason="Blurry image")
        item = db.get_item(sample_item)
        assert item is not None
        assert item.needs_review is True
        assert item.review_reason == "Blurry image"

        # Clear review
        db.update_item(sample_item, needs_review=False, review_reason=None)
        item = db.get_item(sample_item)
        assert item is not None
        assert item.needs_review is False
        assert item.review_reason is None

    def test_update_nonexistent_item(self, db: Database) -> None:
        """Test updating a non-existent item."""
        result = db.update_item(99999, title_manual="Test")
        assert result is False

    def test_update_no_fields(self, db: Database, sample_item: int) -> None:
        """Test update with no fields returns False."""
        result = db.update_item(sample_item)
        assert result is False

    def test_update_invalid_field_ignored(self, db: Database, sample_item: int) -> None:
        """Test that invalid fields are ignored."""
        result = db.update_item(sample_item, invalid_field="test", title_manual="Valid")
        assert result is True
        item = db.get_item(sample_item)
        assert item is not None
        assert item.title_manual == "Valid"


class TestDatabaseGetItemImage:
    """Tests for Database.get_item_image method."""

    def test_get_item_image_none_when_no_images(self, db: Database, sample_item: int) -> None:
        """Test getting image when no images exist."""
        image = db.get_item_image(sample_item, "full")
        assert image is None

    def test_get_item_image_returns_bytes(self, db: Database, sample_item: int) -> None:
        """Test getting image returns bytes."""
        # Add a test image
        test_data = b"fake jpeg data"
        db.add_image(sample_item, "full", test_data, 100, 100, is_cover=False)

        image = db.get_item_image(sample_item, "full")
        assert image == test_data

    def test_get_item_image_fallback(self, db: Database, sample_item: int) -> None:
        """Test fallback to any image when requested type not found."""
        test_data = b"full image data"
        db.add_image(sample_item, "full", test_data, 100, 100)

        # Request thumb, should fall back to full
        image = db.get_item_image(sample_item, "thumb")
        assert image == test_data


class TestDatabaseGetItemImagesInfo:
    """Tests for Database.get_item_images_info method."""

    def test_get_images_info_empty(self, db: Database, sample_item: int) -> None:
        """Test getting images info when no images."""
        info = db.get_item_images_info(sample_item)
        assert info == []

    def test_get_images_info_with_images(self, db: Database, sample_item: int) -> None:
        """Test getting images info with multiple images."""
        db.add_image(sample_item, "full", b"full data", 800, 600, is_cover=True)
        db.add_image(sample_item, "thumb", b"thumb data", 200, 150, is_cover=False)

        info = db.get_item_images_info(sample_item)

        assert len(info) == 2
        # Cover image should be first
        assert info[0]["is_cover"] is True
        assert info[0]["image_type"] == "full"
        assert info[0]["width"] == 800
        assert info[0]["height"] == 600


class TestCLIShowCommand:
    """Tests for the show CLI command."""

    def test_show_command_exists(self) -> None:
        """Test that show command is registered."""
        from cataloguer.cli import main

        assert "show" in [cmd.name for cmd in main.commands.values()]


class TestCLIEditCommand:
    """Tests for the edit CLI command."""

    def test_edit_command_exists(self) -> None:
        """Test that edit command is registered."""
        from cataloguer.cli import main

        assert "edit" in [cmd.name for cmd in main.commands.values()]


class TestCLIReidentifyCommand:
    """Tests for the reidentify CLI command."""

    def test_reidentify_command_exists(self) -> None:
        """Test that reidentify command is registered."""
        from cataloguer.cli import main

        assert "reidentify" in [cmd.name for cmd in main.commands.values()]


class TestCLIReviewCommand:
    """Tests for the review CLI command."""

    def test_review_command_exists(self) -> None:
        """Test that review command is registered."""
        from cataloguer.cli import main

        assert "review" in [cmd.name for cmd in main.commands.values()]


class TestCLIListFilters:
    """Tests for enhanced list command filters."""

    def test_list_command_has_new_filters(self) -> None:
        """Test that list command has new filter options."""
        from cataloguer.cli import list_items

        # Get parameter names from the click command
        param_names = [p.name for p in list_items.params]

        assert "unknown" in param_names
        assert "low_confidence" in param_names
        assert "item_type" in param_names
