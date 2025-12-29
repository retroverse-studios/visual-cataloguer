"""Search routes for the API."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from cataloguer.api.deps import DbDep

router = APIRouter()


class SearchResult(BaseModel):
    """Response model for a search result."""

    item_id: int
    location_id: str | None
    title_guess: str | None
    title_manual: str | None
    platform_guess: str | None
    platform_manual: str | None
    completeness: str
    ebay_listed: bool
    needs_review: bool
    ocr_text_raw: str | None


class SearchResponse(BaseModel):
    """Response model for search results."""

    query: str
    results: list[SearchResult]
    total: int
    page: int
    per_page: int


@router.get("/search", response_model=SearchResponse)
def search_items(
    db: DbDep,
    q: Annotated[str, Query(min_length=1, description="Search query")],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    location_id: str | None = None,
    platform: str | None = None,
    completeness: str | None = None,
    ebay_listed: bool | None = None,
    needs_review: bool | None = None,
) -> SearchResponse:
    """Search items by text query with optional filters."""
    with db.connection() as conn:
        # Build search conditions
        conditions = [
            "(title_guess LIKE ? OR title_manual LIKE ? OR ocr_text_raw LIKE ? OR notes LIKE ?)"
        ]
        search_term = f"%{q}%"
        params: list[str | int] = [search_term, search_term, search_term, search_term]

        if location_id:
            conditions.append("location_id = ?")
            params.append(location_id)
        if platform:
            conditions.append("(platform_guess = ? OR platform_manual = ?)")
            params.extend([platform, platform])
        if completeness:
            conditions.append("completeness = ?")
            params.append(completeness)
        if ebay_listed is not None:
            conditions.append("ebay_listed = ?")
            params.append(1 if ebay_listed else 0)
        if needs_review is not None:
            conditions.append("needs_review = ?")
            params.append(1 if needs_review else 0)

        where_clause = " WHERE " + " AND ".join(conditions)

        # Get total count
        count_sql = f"SELECT COUNT(*) FROM items{where_clause}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # Get paginated results
        offset = (page - 1) * per_page
        sql = f"""
            SELECT item_id, location_id, title_guess, title_manual, platform_guess,
                   platform_manual, completeness, ebay_listed, needs_review, ocr_text_raw
            FROM items{where_clause}
            ORDER BY
                CASE
                    WHEN title_guess LIKE ? THEN 1
                    WHEN title_manual LIKE ? THEN 1
                    ELSE 2
                END,
                item_id DESC
            LIMIT ? OFFSET ?
        """
        # Add priority params for ordering
        params.extend([search_term, search_term, per_page, offset])
        rows = conn.execute(sql, params).fetchall()

        results = [
            SearchResult(
                item_id=row["item_id"],
                location_id=row["location_id"],
                title_guess=row["title_guess"],
                title_manual=row["title_manual"],
                platform_guess=row["platform_guess"],
                platform_manual=row["platform_manual"],
                completeness=row["completeness"] or "unknown",
                ebay_listed=bool(row["ebay_listed"]),
                needs_review=bool(row["needs_review"]),
                ocr_text_raw=row["ocr_text_raw"],
            )
            for row in rows
        ]

        return SearchResponse(
            query=q,
            results=results,
            total=total,
            page=page,
            per_page=per_page,
        )


@router.get("/platforms")
def get_platforms(db: DbDep) -> dict[str, list[str]]:
    """Get list of unique platforms in the collection."""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT platform_guess FROM items
            WHERE platform_guess IS NOT NULL
            UNION
            SELECT DISTINCT platform_manual FROM items
            WHERE platform_manual IS NOT NULL
            ORDER BY 1
            """
        ).fetchall()

        platforms = [row[0] for row in rows if row[0]]
        return {"platforms": platforms}


@router.get("/completeness-options")
def get_completeness_options() -> dict[str, list[str]]:
    """Get list of valid completeness values."""
    return {
        "options": ["unknown", "loose", "boxed", "partial", "complete_set"]
    }
