"""Price research routes — estimate item value from recent eBay sales."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cataloguer.api.deps import DbDep
from cataloguer.api.routes.settings import resolve_setting
from cataloguer.services.pricing import (
    EbaySoldPricingProvider,
    PricingError,
    build_search_keywords,
)

router = APIRouter()


class SoldListingResponse(BaseModel):
    """One sold listing backing an estimate."""

    title: str
    price: float
    currency: str
    sold_date: str | None
    url: str | None


class PriceEstimateResponse(BaseModel):
    """Summary of recent sold prices for an item."""

    item_id: int
    source: str
    query: str
    search_url: str
    currency: str
    price_low: float
    price_median: float
    price_high: float
    sample_size: int
    most_recent_sale: str | None
    oldest_sale: str | None
    listings: list[SoldListingResponse]


class PriceSnapshotResponse(BaseModel):
    """A stored price research snapshot."""

    estimate_id: int
    source: str | None
    query: str | None
    currency: str | None
    price_low: float | None
    price_median: float | None
    price_high: float | None
    sample_size: int | None
    most_recent_sale: str | None
    search_url: str | None
    fetched_at: str | None


def _make_provider(db: DbDep) -> EbaySoldPricingProvider:
    """Build the pricing provider from settings. Split out for testability."""
    site = resolve_setting(db, "ebay_site") or "www.ebay.com.au"
    return EbaySoldPricingProvider(site=site)


@router.post("/{item_id}/price-research", response_model=PriceEstimateResponse)
def research_price(item_id: int, db: DbDep) -> PriceEstimateResponse:
    """Search recent eBay sold listings for this item and store a snapshot."""
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    keywords = build_search_keywords(
        title=item.title_manual or item.title_guess,
        platform=item.platform_manual or item.platform_guess,
        ocr_text=item.ocr_text_raw,
    )
    if not keywords:
        raise HTTPException(
            status_code=400,
            detail="Item has no title to search with. Set a title first.",
        )

    provider = _make_provider(db)
    try:
        estimate = provider.research(keywords)
    except PricingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None

    db.add_price_estimate(
        item_id=item_id,
        source=estimate.source,
        query=estimate.query,
        currency=estimate.currency,
        price_low=estimate.price_low,
        price_median=estimate.price_median,
        price_high=estimate.price_high,
        sample_size=estimate.sample_size,
        most_recent_sale=(
            estimate.most_recent_sale.isoformat() if estimate.most_recent_sale else None
        ),
        search_url=estimate.search_url,
    )

    return PriceEstimateResponse(
        item_id=item_id,
        source=estimate.source,
        query=estimate.query,
        search_url=estimate.search_url,
        currency=estimate.currency,
        price_low=estimate.price_low,
        price_median=estimate.price_median,
        price_high=estimate.price_high,
        sample_size=estimate.sample_size,
        most_recent_sale=(
            estimate.most_recent_sale.isoformat() if estimate.most_recent_sale else None
        ),
        oldest_sale=estimate.oldest_sale.isoformat() if estimate.oldest_sale else None,
        listings=[
            SoldListingResponse(
                title=listing.title,
                price=listing.price,
                currency=listing.currency,
                sold_date=listing.sold_date.isoformat() if listing.sold_date else None,
                url=listing.url,
            )
            for listing in estimate.listings
        ],
    )


@router.get("/{item_id}/price-history", response_model=list[PriceSnapshotResponse])
def price_history(item_id: int, db: DbDep) -> list[PriceSnapshotResponse]:
    """Stored price research snapshots for an item, newest first."""
    if not db.get_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return [
        PriceSnapshotResponse(
            estimate_id=row["estimate_id"],
            source=row["source"],
            query=row["query"],
            currency=row["currency"],
            price_low=row["price_low"],
            price_median=row["price_median"],
            price_high=row["price_high"],
            sample_size=row["sample_size"],
            most_recent_sale=row["most_recent_sale"],
            search_url=row["search_url"],
            fetched_at=str(row["fetched_at"]) if row["fetched_at"] else None,
        )
        for row in db.get_price_estimates(item_id)
    ]
