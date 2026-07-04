"""Tests for the price research service and API routes."""

import tempfile
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cataloguer.api.app import app
from cataloguer.api.deps import configure_database
from cataloguer.database.models import Database, Item
from cataloguer.services.pricing import (
    EbaySoldPricingProvider,
    PriceEstimate,
    SoldListing,
    _parse_price,
    _parse_sold_date,
    build_search_keywords,
    parse_sold_listings,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ebay_sold_search.html"


# ─── HTML parsing against a real saved results page ─────────────────────────


class TestParseSoldListings:
    @pytest.fixture(scope="class")
    def listings(self) -> list[SoldListing]:
        html = FIXTURE.read_text(encoding="utf-8", errors="replace")
        return parse_sold_listings(html, default_currency="AUD")

    def test_finds_a_substantial_sample(self, listings: list[SoldListing]) -> None:
        # The fixture page contains ~60 result cards.
        assert len(listings) >= 40

    def test_placeholder_cards_excluded(self, listings: list[SoldListing]) -> None:
        assert all(listing.title.lower() != "shop on ebay" for listing in listings)

    def test_all_have_positive_prices(self, listings: list[SoldListing]) -> None:
        assert all(listing.price > 0 for listing in listings)

    def test_all_have_sold_dates(self, listings: list[SoldListing]) -> None:
        assert all(listing.sold_date is not None for listing in listings)

    def test_majority_currency_is_aud(self, listings: list[SoldListing]) -> None:
        aud = [listing for listing in listings if listing.currency == "AUD"]
        assert len(aud) > len(listings) / 2

    def test_titles_are_real(self, listings: list[SoldListing]) -> None:
        assert any("mario" in listing.title.lower() for listing in listings)

    def test_urls_point_at_items(self, listings: list[SoldListing]) -> None:
        with_urls = [listing for listing in listings if listing.url]
        assert with_urls
        assert all("/itm/" in str(listing.url) for listing in with_urls)


class TestPriceParsing:
    def test_au_dollars(self) -> None:
        assert _parse_price("AU $55.98", "AUD") == (55.98, "AUD")

    def test_us_dollars(self) -> None:
        assert _parse_price("US $12.00", "AUD") == (12.0, "USD")

    def test_bare_dollars_use_site_default(self) -> None:
        assert _parse_price("$20.00", "AUD") == (20.0, "AUD")

    def test_thousands_separator(self) -> None:
        assert _parse_price("AU $1,444.65", "AUD") == (1444.65, "AUD")

    def test_range_takes_first_amount(self) -> None:
        assert _parse_price("AU $20.00 to AU $40.00", "AUD") == (20.0, "AUD")

    def test_pounds(self) -> None:
        assert _parse_price("£9.99", "AUD") == (9.99, "GBP")

    def test_garbage_returns_none(self) -> None:
        assert _parse_price("Free postage", "AUD") is None


class TestSoldDateParsing:
    def test_au_format(self) -> None:
        assert _parse_sold_date("Sold  4 Jul 2026") == date(2026, 7, 4)

    def test_us_format(self) -> None:
        assert _parse_sold_date("Sold Jul 4, 2026") == date(2026, 7, 4)

    def test_no_date(self) -> None:
        assert _parse_sold_date("or Best Offer") is None


class TestBuildSearchKeywords:
    def test_title_plus_platform(self) -> None:
        assert build_search_keywords("Super Mario 64", "N64") == "Super Mario 64 N64"

    def test_platform_already_in_title(self) -> None:
        assert build_search_keywords("Super Mario 64 N64 boxed", "N64") == "Super Mario 64 N64 boxed"

    def test_no_title_falls_back_to_ocr(self) -> None:
        assert build_search_keywords(None, "SNES", "Donkey Kong Country\nNintendo") == (
            "Donkey Kong Country SNES"
        )

    def test_nothing_available(self) -> None:
        assert build_search_keywords(None, "N64", None) == ""

    def test_search_url_encodes_keywords(self) -> None:
        provider = EbaySoldPricingProvider(site="www.ebay.com.au")
        url = provider.search_url("super mario 64 n64")
        assert url.startswith("https://www.ebay.com.au/sch/i.html?")
        assert "_nkw=super+mario+64+n64" in url
        assert "LH_Sold=1" in url
        assert "LH_Complete=1" in url


# ─── API routes ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_db() -> Generator[None, None, None]:
    """Reset database configuration for each test."""
    yield
    configure_database(Path("/tmp/nonexistent.db"))


@pytest.fixture
def temp_db() -> Generator[Path, None, None]:
    """Create a temporary database with one item."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    configure_database(db_path)
    db = Database(db_path)
    db.create_location("BOX-1", "Test Box 1")
    db.create_item(
        Item(location_id="BOX-1", title_guess="Super Mario 64", platform_guess="N64")
    )
    db.create_item(Item(location_id="BOX-1"))  # untitled item

    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def client(temp_db: Path) -> TestClient:
    return TestClient(app)


class _StubProvider:
    source = "ebay_sold"

    def research(self, keywords: str) -> PriceEstimate:
        return PriceEstimate(
            source=self.source,
            query=keywords,
            search_url="https://www.ebay.com.au/sch/i.html?_nkw=test",
            currency="AUD",
            price_low=10.0,
            price_median=25.5,
            price_high=90.0,
            sample_size=12,
            most_recent_sale=date(2026, 7, 1),
            oldest_sale=date(2026, 5, 2),
            listings=[
                SoldListing(
                    title="Super Mario 64 (N64) CIB",
                    price=25.5,
                    currency="AUD",
                    sold_date=date(2026, 7, 1),
                    url="https://www.ebay.com.au/itm/1",
                )
            ],
        )


class TestPriceRoutes:
    def test_research_stores_snapshot_and_returns_estimate(
        self, client: TestClient, temp_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cataloguer.api.routes import price as price_route

        monkeypatch.setattr(price_route, "_make_provider", lambda db: _StubProvider())

        response = client.post("/api/items/1/price-research")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "Super Mario 64 N64"
        assert data["price_median"] == 25.5
        assert data["sample_size"] == 12
        assert data["most_recent_sale"] == "2026-07-01"
        assert len(data["listings"]) == 1

        # Snapshot was stored
        history = client.get("/api/items/1/price-history")
        assert history.status_code == 200
        rows = history.json()
        assert len(rows) == 1
        assert rows[0]["price_median"] == 25.5
        assert rows[0]["source"] == "ebay_sold"

    def test_research_untitled_item_400(
        self, client: TestClient, temp_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cataloguer.api.routes import price as price_route

        monkeypatch.setattr(price_route, "_make_provider", lambda db: _StubProvider())

        response = client.post("/api/items/2/price-research")
        assert response.status_code == 400

    def test_research_missing_item_404(self, client: TestClient, temp_db: Path) -> None:
        assert client.post("/api/items/999/price-research").status_code == 404

    def test_history_missing_item_404(self, client: TestClient, temp_db: Path) -> None:
        assert client.get("/api/items/999/price-history").status_code == 404

    def test_history_empty_for_fresh_item(self, client: TestClient, temp_db: Path) -> None:
        response = client.get("/api/items/1/price-history")
        assert response.status_code == 200
        assert response.json() == []
