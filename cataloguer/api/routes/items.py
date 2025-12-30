"""Item routes for the API."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from cataloguer.api.deps import DbDep

router = APIRouter()


class ItemResponse(BaseModel):
    """Response model for an item."""

    model_config = ConfigDict(from_attributes=True)

    item_id: int
    location_id: str | None
    source_camera: str | None
    source_filename: str | None
    captured_at: str | None
    object_count: int | None
    completeness: str
    ocr_text_raw: str | None
    title_guess: str | None
    title_confidence: float | None
    platform_guess: str | None
    language: str
    title_manual: str | None
    platform_manual: str | None
    notes: str | None
    ebay_listed: bool
    ebay_listing_id: str | None
    needs_review: bool
    review_reason: str | None
    processed_at: str | None
    # New fields for AI identification
    item_type: str
    ai_identified: bool
    ai_description: str | None
    brand: str | None
    region: str | None
    year: str | None
    condition_notes: str | None


class ItemListResponse(BaseModel):
    """Response model for item list."""

    items: list[ItemResponse]
    total: int
    page: int
    per_page: int


class ItemUpdate(BaseModel):
    """Request model for updating an item."""

    location_id: str | None = None  # Allow reassigning to different location
    title_manual: str | None = None
    platform_manual: str | None = None
    completeness: str | None = None
    notes: str | None = None
    ebay_listed: bool | None = None
    ebay_listing_id: str | None = None
    needs_review: bool | None = None
    review_reason: str | None = None


def row_to_item(row: dict[str, Any]) -> ItemResponse:
    """Convert a database row to an ItemResponse."""
    return ItemResponse(
        item_id=row["item_id"],
        location_id=row["location_id"],
        source_camera=row["source_camera"],
        source_filename=row["source_filename"],
        captured_at=str(row["captured_at"]) if row["captured_at"] else None,
        object_count=row["object_count"],
        completeness=row["completeness"] or "unknown",
        ocr_text_raw=row["ocr_text_raw"],
        title_guess=row["title_guess"],
        title_confidence=row["title_confidence"],
        platform_guess=row["platform_guess"],
        language=row["language"] or "en",
        title_manual=row["title_manual"],
        platform_manual=row["platform_manual"],
        notes=row["notes"],
        ebay_listed=bool(row["ebay_listed"]),
        ebay_listing_id=row["ebay_listing_id"],
        needs_review=bool(row["needs_review"]),
        review_reason=row["review_reason"],
        processed_at=str(row["processed_at"]) if row["processed_at"] else None,
        # New fields
        item_type=row["item_type"] or "game",
        ai_identified=bool(row["ai_identified"]),
        ai_description=row["ai_description"],
        brand=row["brand"],
        region=row["region"],
        year=row["year"],
        condition_notes=row["condition_notes"],
    )


@router.get("", response_model=ItemListResponse)
def list_items(
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    location_id: str | None = None,
    platform: str | None = None,
    completeness: str | None = None,
    needs_review: bool | None = None,
    ebay_listed: bool | None = None,
    # New filters for curation
    unknown: bool | None = None,
    low_confidence: bool | None = None,
    item_type: str | None = None,
    ai_identified: bool | None = None,
) -> ItemListResponse:
    """List items with optional filtering and pagination."""
    with db.connection() as conn:
        # Build query
        conditions = []
        params: list[str | int | float] = []

        if location_id:
            conditions.append("location_id = ?")
            params.append(location_id)
        if platform:
            conditions.append("(platform_guess = ? OR platform_manual = ?)")
            params.extend([platform, platform])
        if completeness:
            conditions.append("completeness = ?")
            params.append(completeness)
        if needs_review is not None:
            conditions.append("needs_review = ?")
            params.append(1 if needs_review else 0)
        if ebay_listed is not None:
            conditions.append("ebay_listed = ?")
            params.append(1 if ebay_listed else 0)
        # New filters
        if unknown:
            conditions.append("(title_guess IS NULL OR title_guess = '')")
        if low_confidence:
            conditions.append("(title_confidence IS NULL OR title_confidence < 0.5)")
        if item_type:
            conditions.append("item_type = ?")
            params.append(item_type)
        if ai_identified is not None:
            conditions.append("ai_identified = ?")
            params.append(1 if ai_identified else 0)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Get total count
        count_sql = f"SELECT COUNT(*) FROM items{where_clause}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # Get paginated items
        offset = (page - 1) * per_page
        sql = f"""
            SELECT * FROM items{where_clause}
            ORDER BY item_id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])
        rows = conn.execute(sql, params).fetchall()

        items = [row_to_item(dict(row)) for row in rows]

        return ItemListResponse(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
        )


@router.get("/unlisted", response_model=ItemListResponse)
def list_unlisted_items(
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ItemListResponse:
    """List items not yet listed on eBay."""
    with db.connection() as conn:
        # Get total count
        total = conn.execute(
            "SELECT COUNT(*) FROM items WHERE ebay_listed = 0"
        ).fetchone()[0]

        # Get paginated items
        offset = (page - 1) * per_page
        rows = conn.execute(
            """
            SELECT * FROM items
            WHERE ebay_listed = 0
            ORDER BY item_id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        ).fetchall()

        items = [row_to_item(dict(row)) for row in rows]

        return ItemListResponse(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
        )


@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: int, db: DbDep) -> ItemResponse:
    """Get a single item by ID."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Item not found")

        return row_to_item(dict(row))


@router.patch("/{item_id}", response_model=ItemResponse)
def update_item(item_id: int, update: ItemUpdate, db: DbDep) -> ItemResponse:
    """Update an item."""
    with db.connection() as conn:
        # Check item exists
        row = conn.execute(
            "SELECT * FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Item not found")

        # Build update query
        updates = []
        params: list[str | int | None] = []

        update_data = update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            updates.append(f"{key} = ?")
            params.append(value)

        if not updates:
            return row_to_item(dict(row))

        # Add updated_at timestamp
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(item_id)

        sql = f"UPDATE items SET {', '.join(updates)} WHERE item_id = ?"
        conn.execute(sql, params)

        # Return updated item
        updated_row = conn.execute(
            "SELECT * FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        return row_to_item(dict(updated_row))


@router.delete("/{item_id}")
def delete_item(item_id: int, db: DbDep) -> dict[str, str]:
    """Delete an item."""
    with db.connection() as conn:
        # Check item exists
        row = conn.execute(
            "SELECT * FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Item not found")

        # Delete item (cascades to images)
        conn.execute("DELETE FROM items WHERE item_id = ?", (item_id,))

        return {"status": "deleted", "item_id": str(item_id)}


@router.patch("/{item_id}/mark-listed", response_model=ItemResponse)
def mark_item_listed(
    item_id: int,
    db: DbDep,
    ebay_listing_id: str | None = None,
) -> ItemResponse:
    """Mark an item as listed on eBay."""
    with db.connection() as conn:
        # Check item exists
        row = conn.execute(
            "SELECT * FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Item not found")

        # Update item
        if ebay_listing_id:
            conn.execute(
                """
                UPDATE items
                SET ebay_listed = 1, ebay_listing_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE item_id = ?
                """,
                (ebay_listing_id, item_id),
            )
        else:
            conn.execute(
                """
                UPDATE items
                SET ebay_listed = 1, updated_at = CURRENT_TIMESTAMP
                WHERE item_id = ?
                """,
                (item_id,),
            )

        # Return updated item
        updated_row = conn.execute(
            "SELECT * FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        return row_to_item(dict(updated_row))


class ReidentifyRequest(BaseModel):
    """Request model for re-identification."""

    provider: str = "claude"
    model: str | None = None


@router.post("/{item_id}/reidentify", response_model=ItemResponse)
def reidentify_item(
    item_id: int,
    request: ReidentifyRequest,
    db: DbDep,
) -> ItemResponse:
    """Re-run AI identification on an item using its stored image."""
    from cataloguer.processor.identifier import ItemIdentifier

    # Get item
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Get stored image
    image_data = db.get_item_image(item_id, "full")
    if not image_data:
        raise HTTPException(
            status_code=400,
            detail="No image found for item. Upload an image first.",
        )

    # Initialize identifier
    try:
        identifier = ItemIdentifier(provider=request.provider, model=request.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # Run identification
    try:
        result = identifier.identify_bytes(image_data, "image/jpeg")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Identification failed: {e}",
        ) from None

    # Map confidence to numeric
    confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
    title_confidence = None
    if result.confidence and result.confidence in confidence_map:
        title_confidence = confidence_map[result.confidence]

    # Map completeness
    completeness = "unknown"
    if result.completeness:
        completeness_map = {
            "loose": "loose",
            "boxed": "boxed",
            "complete": "complete_set",
            "sealed": "complete_set",
        }
        completeness = completeness_map.get(result.completeness, "unknown")

    # Update item
    db.update_item(
        item_id,
        item_type=result.item_type.value,
        title_guess=result.title,
        title_confidence=title_confidence,
        platform_guess=result.platform,
        brand=result.brand,
        region=result.region,
        year=result.year,
        completeness=completeness,
        condition_notes=result.condition_notes,
        ai_identified=True,
        ai_description=json.dumps(result.raw_response),
    )

    # Return updated item
    with db.connection() as conn:
        updated_row = conn.execute(
            "SELECT * FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return row_to_item(dict(updated_row))
