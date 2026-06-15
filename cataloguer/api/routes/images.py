"""Image routes for the API."""

import io
from typing import Annotated

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from cataloguer.api.deps import DbDep
from cataloguer.database.models import Database
from cataloguer.processor.image_ops import (
    auto_crop,
    auto_rotate,
    create_thumbnail,
    decode_jpeg,
    encode_jpeg,
    manual_crop,
    rotate_90,
)

router = APIRouter()

# Guard against decompression-bomb DoS on uploads: cap the raw request body and
# the decoded pixel count. A small crafted file can otherwise expand to GBs of
# RAM when decoded.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB on the wire
MAX_IMAGE_PIXELS = 50_000_000  # 50 megapixels decoded

# Make PIL itself raise on absurdly large images rather than warn-and-continue.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


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
            headers={"Cache-Control": "no-cache"},
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
            headers={"Cache-Control": "no-cache"},
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


class RotateRequest(BaseModel):
    """Request to rotate an image."""
    direction: str  # "cw" or "ccw"


class CropRequest(BaseModel):
    """Request to crop an image."""
    x: int
    y: int
    width: int
    height: int


class ImageEditResponse(BaseModel):
    """Response after editing an image."""
    item_id: int
    width: int
    height: int


def _apply_and_save(
    db: Database, item_id: int, image: np.ndarray
) -> ImageEditResponse:
    """Encode, save full + thumbnail, return dimensions."""
    h, w = image.shape[:2]
    full_jpeg = encode_jpeg(image)
    thumb = create_thumbnail(image)
    th, tw = thumb.shape[:2]
    thumb_jpeg = encode_jpeg(thumb)
    db.replace_image(item_id, "full", full_jpeg, w, h)
    db.replace_image(item_id, "thumb", thumb_jpeg, tw, th)
    return ImageEditResponse(item_id=item_id, width=w, height=h)


def _load_full_image(db: Database, item_id: int) -> np.ndarray:
    """Load the full image for an item as a numpy array."""
    blob = db.get_item_image(item_id, "full")
    if not blob:
        raise HTTPException(status_code=404, detail="Image not found")
    return decode_jpeg(blob)


@router.post("/items/{item_id}/image/rotate", response_model=ImageEditResponse)
def rotate_item_image(item_id: int, req: RotateRequest, db: DbDep) -> ImageEditResponse:
    """Rotate an item image 90 degrees."""
    if req.direction not in ("cw", "ccw"):
        raise HTTPException(status_code=400, detail="direction must be 'cw' or 'ccw'")
    image = _load_full_image(db, item_id)
    rotated = rotate_90(image, req.direction)
    return _apply_and_save(db, item_id, rotated)


@router.post("/items/{item_id}/image/crop", response_model=ImageEditResponse)
def crop_item_image(item_id: int, req: CropRequest, db: DbDep) -> ImageEditResponse:
    """Crop an item image to the specified rectangle."""
    image = _load_full_image(db, item_id)
    cropped = manual_crop(image, req.x, req.y, req.width, req.height)
    return _apply_and_save(db, item_id, cropped)


@router.post("/items/{item_id}/image/auto-enhance", response_model=ImageEditResponse)
def auto_enhance_item_image(item_id: int, db: DbDep) -> ImageEditResponse:
    """Auto-crop and deskew an item image."""
    image = _load_full_image(db, item_id)
    enhanced = auto_crop(image)
    enhanced = auto_rotate(enhanced)
    return _apply_and_save(db, item_id, enhanced)


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
        contents = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image exceeds maximum upload size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )
        img = Image.open(io.BytesIO(contents))
        width, height = img.size
        if width * height > MAX_IMAGE_PIXELS:
            raise HTTPException(
                status_code=413,
                detail=f"Image exceeds maximum of {MAX_IMAGE_PIXELS // 1_000_000} megapixels",
            )

        # Convert to JPEG if needed
        if img.format != "JPEG":
            output = io.BytesIO()
            # Convert to RGB if necessary (for PNG with alpha, etc.)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(output, format="JPEG", quality=85)
            contents = output.getvalue()
    except HTTPException:
        raise  # size/pixel limits already carry the right status code
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
