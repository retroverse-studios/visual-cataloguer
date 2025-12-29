"""Box routes for the API."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cataloguer.api.deps import DbDep

router = APIRouter()


class BoxResponse(BaseModel):
    """Response model for a box."""

    box_id: str
    label: str | None
    notes: str | None
    created_at: str | None
    item_count: int


class BoxListResponse(BaseModel):
    """Response model for box list."""

    boxes: list[BoxResponse]
    total: int


class BoxItemResponse(BaseModel):
    """Simplified item response for box listings."""

    item_id: int
    title_guess: str | None
    title_manual: str | None
    platform_guess: str | None
    platform_manual: str | None
    completeness: str
    ebay_listed: bool
    needs_review: bool


class BoxItemsResponse(BaseModel):
    """Response model for items in a box."""

    box_id: str
    items: list[BoxItemResponse]
    total: int
    page: int
    per_page: int


@router.get("", response_model=BoxListResponse)
def list_boxes(db: DbDep) -> BoxListResponse:
    """List all boxes with item counts."""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT b.box_id, b.label, b.notes, b.created_at, COUNT(i.item_id) as item_count
            FROM boxes b
            LEFT JOIN items i ON b.box_id = i.box_id
            GROUP BY b.box_id
            ORDER BY b.box_id
            """
        ).fetchall()

        boxes = [
            BoxResponse(
                box_id=row["box_id"],
                label=row["label"],
                notes=row["notes"],
                created_at=str(row["created_at"]) if row["created_at"] else None,
                item_count=row["item_count"],
            )
            for row in rows
        ]

        return BoxListResponse(boxes=boxes, total=len(boxes))


@router.get("/{box_id}", response_model=BoxResponse)
def get_box(box_id: str, db: DbDep) -> BoxResponse:
    """Get a single box by ID."""
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT b.box_id, b.label, b.notes, b.created_at, COUNT(i.item_id) as item_count
            FROM boxes b
            LEFT JOIN items i ON b.box_id = i.box_id
            WHERE b.box_id = ?
            GROUP BY b.box_id
            """,
            (box_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Box not found")

        return BoxResponse(
            box_id=row["box_id"],
            label=row["label"],
            notes=row["notes"],
            created_at=str(row["created_at"]) if row["created_at"] else None,
            item_count=row["item_count"],
        )


@router.get("/{box_id}/items", response_model=BoxItemsResponse)
def get_box_items(
    box_id: str,
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BoxItemsResponse:
    """Get items in a specific box."""
    with db.connection() as conn:
        # Check box exists
        box = conn.execute(
            "SELECT box_id FROM boxes WHERE box_id = ?", (box_id,)
        ).fetchone()

        if not box:
            raise HTTPException(status_code=404, detail="Box not found")

        # Get total count
        total = conn.execute(
            "SELECT COUNT(*) FROM items WHERE box_id = ?", (box_id,)
        ).fetchone()[0]

        # Get paginated items
        offset = (page - 1) * per_page
        rows = conn.execute(
            """
            SELECT item_id, title_guess, title_manual, platform_guess, platform_manual,
                   completeness, ebay_listed, needs_review
            FROM items
            WHERE box_id = ?
            ORDER BY item_id
            LIMIT ? OFFSET ?
            """,
            (box_id, per_page, offset),
        ).fetchall()

        items = [
            BoxItemResponse(
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

        return BoxItemsResponse(
            box_id=box_id,
            items=items,
            total=total,
            page=page,
            per_page=per_page,
        )
