"""Tests for the FastAPI web interface."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cataloguer.api.app import app
from cataloguer.api.deps import configure_database
from cataloguer.database.models import Database, Item


@pytest.fixture(autouse=True)
def reset_db() -> Generator[None, None, None]:
    """Reset database configuration for each test."""
    yield
    # Reset to a non-existent path after each test
    configure_database(Path("/tmp/nonexistent.db"))


@pytest.fixture
def temp_db() -> Generator[Path, None, None]:
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Initialize and configure
    configure_database(db_path)

    # Add some test data
    db = Database(db_path)
    db.create_location("BOX-1", "Test Box 1")
    db.create_location("BOX-2", "Test Box 2")

    # Create test items
    item1 = Item(
        location_id="BOX-1",
        title_guess="Test Game 1",
        platform_guess="NES",
        completeness="boxed",
    )
    item2 = Item(
        location_id="BOX-1",
        title_guess="Test Game 2",
        platform_guess="SNES",
        completeness="loose",
        needs_review=True,
    )
    item3 = Item(
        location_id="BOX-2",
        title_guess="Test Game 3",
        platform_guess="NES",
        ebay_listed=True,
    )

    db.create_item(item1)
    db.create_item(item2)
    db.create_item(item3)

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


@pytest.fixture
def client(temp_db: Path) -> TestClient:
    """Create a test client."""
    return TestClient(app)


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self, client: TestClient) -> None:
        """Test health check returns healthy status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestStats:
    """Tests for stats endpoint."""

    def test_get_stats(self, client: TestClient) -> None:
        """Test stats endpoint returns collection statistics."""
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 3
        assert data["total_locations"] == 2
        assert data["needs_review"] == 1
        assert data["ebay_listed"] == 1


class TestItemsEndpoint:
    """Tests for items endpoints."""

    def test_list_items(self, client: TestClient) -> None:
        """Test listing all items."""
        response = client.get("/api/items")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_list_items_pagination(self, client: TestClient) -> None:
        """Test pagination of items."""
        response = client.get("/api/items?page=1&per_page=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["per_page"] == 2

    def test_list_items_filter_by_platform(self, client: TestClient) -> None:
        """Test filtering items by platform."""
        response = client.get("/api/items?platform=NES")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert all(item["platform_guess"] == "NES" for item in data["items"])

    def test_list_unlisted_items(self, client: TestClient) -> None:
        """Test listing unlisted items."""
        response = client.get("/api/items/unlisted")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert all(not item["ebay_listed"] for item in data["items"])

    def test_get_item(self, client: TestClient) -> None:
        """Test getting a single item."""
        response = client.get("/api/items/1")
        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == 1
        assert data["title_guess"] == "Test Game 1"

    def test_get_item_not_found(self, client: TestClient) -> None:
        """Test getting a non-existent item."""
        response = client.get("/api/items/999")
        assert response.status_code == 404

    def test_update_item(self, client: TestClient) -> None:
        """Test updating an item."""
        response = client.patch(
            "/api/items/1",
            json={"title_manual": "Updated Title", "notes": "Test notes"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title_manual"] == "Updated Title"
        assert data["notes"] == "Test notes"

    def test_mark_item_listed(self, client: TestClient) -> None:
        """Test marking an item as listed on eBay."""
        response = client.patch("/api/items/1/mark-listed")
        assert response.status_code == 200
        data = response.json()
        assert data["ebay_listed"] is True

    def test_delete_item(self, client: TestClient) -> None:
        """Test deleting an item."""
        response = client.delete("/api/items/1")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verify it's gone
        response = client.get("/api/items/1")
        assert response.status_code == 404


class TestLocationsEndpoint:
    """Tests for locations endpoints."""

    def test_list_locations(self, client: TestClient) -> None:
        """Test listing all locations."""
        response = client.get("/api/locations")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["locations"]) == 2

    def test_get_location(self, client: TestClient) -> None:
        """Test getting a single location."""
        response = client.get("/api/locations/BOX-1")
        assert response.status_code == 200
        data = response.json()
        assert data["location_id"] == "BOX-1"
        assert data["item_count"] == 2

    def test_get_location_items(self, client: TestClient) -> None:
        """Test getting items in a location."""
        response = client.get("/api/locations/BOX-1/items")
        assert response.status_code == 200
        data = response.json()
        assert data["location_id"] == "BOX-1"
        assert data["total"] == 2
        assert len(data["items"]) == 2


class TestSearchEndpoint:
    """Tests for search endpoint."""

    def test_search_items(self, client: TestClient) -> None:
        """Test searching for items."""
        response = client.get("/api/search?q=Test")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "Test"
        assert data["total"] == 3

    def test_search_items_filtered(self, client: TestClient) -> None:
        """Test searching with filters."""
        response = client.get("/api/search?q=Test&platform=NES")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    def test_get_platforms(self, client: TestClient) -> None:
        """Test getting list of platforms."""
        response = client.get("/api/platforms")
        assert response.status_code == 200
        data = response.json()
        assert "NES" in data["platforms"]
        assert "SNES" in data["platforms"]

    def test_get_completeness_options(self, client: TestClient) -> None:
        """Test getting completeness options."""
        response = client.get("/api/completeness-options")
        assert response.status_code == 200
        data = response.json()
        assert "unknown" in data["options"]
        assert "complete_set" in data["options"]


class TestImageEndpoints:
    """Tests for image endpoints."""

    def test_get_item_images_no_images(self, client: TestClient) -> None:
        """Test getting images for item with no images."""
        response = client.get("/api/items/1/images")
        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == 1
        assert len(data["images"]) == 0

    def test_get_thumbnail_not_found(self, client: TestClient) -> None:
        """Test getting thumbnail when no image exists."""
        response = client.get("/api/items/1/image/thumb")
        assert response.status_code == 404
