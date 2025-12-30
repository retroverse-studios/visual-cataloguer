"""Image routes for the API."""

import io
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image
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


class ImageUploadResponse(BaseModel):
    """Response model for image upload."""

    image_id: int
    item_id: int
    image_type: str
    width: int
    height: int
    file_size: int
    is_cover: bool


@router.post("/items/{item_id}/images", response_model=ImageUploadResponse)
async def upload_item_image(
    item_id: int,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    image_type: str = "full",
    is_cover: bool = False,
) -> ImageUploadResponse:
    """Upload an image for an item.

    Args:
        item_id: The item to add the image to
        file: The image file (JPEG, PNG, etc.)
        image_type: Type of image ('full', 'thumb', 'context')
        is_cover: Whether this should be the cover image
    """
    # Check item exists
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Read and validate image
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
        width, height = img.size

        # Convert to JPEG if needed
        if img.format != "JPEG":
            output = io.BytesIO()
            # Convert to RGB if necessary (for PNG with alpha, etc.)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(output, format="JPEG", quality=85)
            contents = output.getvalue()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image file: {e}",
        ) from None

    # Add to database
    image_id = db.add_image(
        item_id=item_id,
        image_type=image_type,
        image_blob=contents,
        width=width,
        height=height,
        is_cover=is_cover,
    )

    return ImageUploadResponse(
        image_id=image_id,
        item_id=item_id,
        image_type=image_type,
        width=width,
        height=height,
        file_size=len(contents),
        is_cover=is_cover,
    )
