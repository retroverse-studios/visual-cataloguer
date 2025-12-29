"""Image routes for the API."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from cataloguer.api.deps import DbDep

router = APIRouter()


class ImageInfo(BaseModel):
    """Response model for image info."""

    image_id: int
    item_id: int
    image_type: str
    width: int | None
    height: int | None
    file_size: int | None
    is_cover: bool


class ItemImagesResponse(BaseModel):
    """Response model for item images list."""

    item_id: int
    images: list[ImageInfo]


@router.get("/items/{item_id}/images", response_model=ItemImagesResponse)
def get_item_images(item_id: int, db: DbDep) -> ItemImagesResponse:
    """Get all images for an item (metadata only, not the actual image data)."""
    with db.connection() as conn:
        # Check item exists
        item = conn.execute(
            "SELECT item_id FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # Get images
        rows = conn.execute(
            """
            SELECT image_id, item_id, image_type, width, height, file_size, is_cover
            FROM item_images
            WHERE item_id = ?
            ORDER BY is_cover DESC, image_type
            """,
            (item_id,),
        ).fetchall()

        images = [
            ImageInfo(
                image_id=row["image_id"],
                item_id=row["item_id"],
                image_type=row["image_type"],
                width=row["width"],
                height=row["height"],
                file_size=row["file_size"],
                is_cover=bool(row["is_cover"]),
            )
            for row in rows
        ]

        return ItemImagesResponse(item_id=item_id, images=images)


@router.get("/items/{item_id}/image/thumb")
def get_item_thumbnail(item_id: int, db: DbDep) -> Response:
    """Get the thumbnail image for an item."""
    with db.connection() as conn:
        # Try to get thumbnail first, then fall back to full image
        row = conn.execute(
            """
            SELECT image_blob FROM item_images
            WHERE item_id = ? AND image_type = 'thumb'
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()

        if not row:
            # Fall back to full image
            row = conn.execute(
                """
                SELECT image_blob FROM item_images
                WHERE item_id = ? AND image_type = 'full'
                LIMIT 1
                """,
                (item_id,),
            ).fetchone()

        if not row or not row["image_blob"]:
            raise HTTPException(status_code=404, detail="Image not found")

        return Response(
            content=row["image_blob"],
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},  # Cache for 1 day
        )


@router.get("/items/{item_id}/image/full")
def get_item_full_image(item_id: int, db: DbDep) -> Response:
    """Get the full-resolution image for an item."""
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT image_blob FROM item_images
            WHERE item_id = ? AND image_type = 'full'
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()

        if not row or not row["image_blob"]:
            raise HTTPException(status_code=404, detail="Image not found")

        return Response(
            content=row["image_blob"],
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},  # Cache for 1 day
        )


@router.get("/items/{item_id}/image/{image_type}")
def get_item_image_by_type(item_id: int, image_type: str, db: DbDep) -> Response:
    """Get a specific image type for an item."""
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT image_blob FROM item_images
            WHERE item_id = ? AND image_type = ?
            LIMIT 1
            """,
            (item_id, image_type),
        ).fetchone()

        if not row or not row["image_blob"]:
            raise HTTPException(status_code=404, detail="Image not found")

        return Response(
            content=row["image_blob"],
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )


@router.get("/images/{image_id}")
def get_image_by_id(image_id: int, db: DbDep) -> Response:
    """Get an image by its ID."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT image_blob FROM item_images WHERE image_id = ?",
            (image_id,),
        ).fetchone()

        if not row or not row["image_blob"]:
            raise HTTPException(status_code=404, detail="Image not found")

        return Response(
            content=row["image_blob"],
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
