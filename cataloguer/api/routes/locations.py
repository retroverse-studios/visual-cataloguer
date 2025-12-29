"""Location routes for the API."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cataloguer.api.deps import DbDep

router = APIRouter()


class LocationResponse(BaseModel):
    """Response model for a location."""

    location_id: str
    label: str | None
    notes: str | None
    created_at: str | None
    item_count: int


class LocationListResponse(BaseModel):
    """Response model for location list."""

    locations: list[LocationResponse]
    total: int


class LocationItemResponse(BaseModel):
    """Simplified item response for location listings."""

    item_id: int
    title_guess: str | None
    title_manual: str | None
    platform_guess: str | None
    platform_manual: str | None
    completeness: str
    ebay_listed: bool
    needs_review: bool


class LocationItemsResponse(BaseModel):
    """Response model for items in a location."""

    location_id: str
    items: list[LocationItemResponse]
    total: int
    page: int
    per_page: int


@router.get("", response_model=LocationListResponse)
def list_locations(db: DbDep) -> LocationListResponse:
    """List all locations with item counts."""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT l.location_id, l.label, l.notes, l.created_at,
                   COUNT(i.item_id) as item_count
            FROM locations l
            LEFT JOIN items i ON l.location_id = i.location_id
            GROUP BY l.location_id
            ORDER BY l.location_id
            """
        ).fetchall()

        locations = [
            LocationResponse(
                location_id=row["location_id"],
                label=row["label"],
                notes=row["notes"],
                created_at=str(row["created_at"]) if row["created_at"] else None,
                item_count=row["item_count"],
            )
            for row in rows
        ]

        return LocationListResponse(locations=locations, total=len(locations))


@router.get("/{location_id}", response_model=LocationResponse)
def get_location(location_id: str, db: DbDep) -> LocationResponse:
    """Get a single location by ID."""
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT l.location_id, l.label, l.notes, l.created_at,
                   COUNT(i.item_id) as item_count
            FROM locations l
            LEFT JOIN items i ON l.location_id = i.location_id
            WHERE l.location_id = ?
            GROUP BY l.location_id
            """,
            (location_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Location not found")

        return LocationResponse(
            location_id=row["location_id"],
            label=row["label"],
            notes=row["notes"],
            created_at=str(row["created_at"]) if row["created_at"] else None,
            item_count=row["item_count"],
        )


@router.get("/{location_id}/items", response_model=LocationItemsResponse)
def get_location_items(
    location_id: str,
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LocationItemsResponse:
    """Get items in a specific location."""
    with db.connection() as conn:
        # Check location exists
        location = conn.execute(
            "SELECT location_id FROM locations WHERE location_id = ?", (location_id,)
        ).fetchone()

        if not location:
            raise HTTPException(status_code=404, detail="Location not found")

        # Get total count
        total = conn.execute(
            "SELECT COUNT(*) FROM items WHERE location_id = ?", (location_id,)
        ).fetchone()[0]

        # Get paginated items
        offset = (page - 1) * per_page
        rows = conn.execute(
            """
            SELECT item_id, title_guess, title_manual, platform_guess, platform_manual,
                   completeness, ebay_listed, needs_review
            FROM items
            WHERE location_id = ?
            ORDER BY item_id
            LIMIT ? OFFSET ?
            """,
            (location_id, per_page, offset),
        ).fetchall()

        items = [
            LocationItemResponse(
                item_id=row["item_id"],
                title_guess=row["title_guess"],
                title_manual=row["title_manual"],
                platform_guess=row["platform_guess"],
                platform_manual=row["platform_manual"],
                completeness=row["completeness"] or "unknown",
                ebay_listed=bool(row["ebay_listed"]),
                needs_review=bool(row["needs_review"]),
            )
            for row in rows
        ]

        return LocationItemsResponse(
            location_id=location_id,
            items=items,
            total=total,
            page=page,
            per_page=per_page,
        )
