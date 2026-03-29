"""Processing routes — import and process image folders from the frontend."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cataloguer.api.deps import DbDep
from cataloguer.api.routes.settings import resolve_setting
from cataloguer.database.models import Database

router = APIRouter()


class ProcessRequest(BaseModel):
    """Request to process a folder of images."""

    folder_path: str
    default_location: str | None = None
    use_subfolders_as_locations: bool = False
    skip_divider_detection: bool = False
    offline: bool = False
    provider: str = "auto"
    resume: bool = True
    auto_enhance: bool = True


class ProcessStatus(BaseModel):
    """Status of a processing job."""

    phase: str  # scanning, processing, complete, error
    total_files: int = 0
    processed: int = 0
    current_file: str = ""
    items_created: int = 0
    locations_found: list[str] = []
    message: str = ""


class FolderInfo(BaseModel):
    """Info about a folder before processing."""

    path: str
    image_count: int
    image_files: list[str]
    has_qr_codes: bool
    subfolder_count: int
    subfolders: list[str]


@router.post("/process")
async def process_folder(req: ProcessRequest, db: DbDep) -> StreamingResponse:
    """Process a folder of images. Streams progress as SSE events."""
    folder = Path(req.folder_path)
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.folder_path}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {req.folder_path}")

    return StreamingResponse(
        _process_stream(folder, db, req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _process_stream(
    folder: Path, db: Database, req: ProcessRequest
) -> AsyncGenerator[str, None]:
    """Stream processing progress as Server-Sent Events."""
    from cataloguer.processor.pipeline import ProcessingPipeline

    try:
        # Set default location if no dividers expected
        pipeline = ProcessingPipeline(
            database=db,
            identifier=None,
            offline_mode=req.offline,
            auto_enhance=req.auto_enhance,
        )

        # Set up AI identifier using resolved settings
        if not req.offline and req.provider != "none":
            try:
                from cataloguer.processor.identifier import ItemIdentifier

                # Resolve provider from request or settings
                provider = req.provider
                if provider == "auto":
                    provider = resolve_setting(db, "ai_provider")
                    if provider == "auto":
                        provider = "claude"  # Final fallback

                identifier = ItemIdentifier(
                    provider=provider,
                    model=resolve_setting(db, f"{provider}_model") or None,
                    api_key=resolve_setting(db, "anthropic_api_key") or None,
                    ollama_host=resolve_setting(db, "ollama_host"),
                )
                pipeline.identifier = identifier
            except Exception:
                pass  # Fall back to offline

        # Set up location strategy based on request
        if req.default_location:
            pipeline.current_location_id = req.default_location
            db.create_location(req.default_location)

        # Phase 1: Scan
        yield _sse(ProcessStatus(phase="scanning", message="Scanning folder..."))
        await asyncio.sleep(0)

        files = await asyncio.to_thread(pipeline.scan_directory, folder)

        yield _sse(ProcessStatus(
            phase="scanning",
            total_files=len(files),
            message=f"Found {len(files)} images",
        ))
        await asyncio.sleep(0)

        if not files:
            yield _sse(ProcessStatus(
                phase="complete",
                message="No images found in folder",
            ))
            return

        # If using subfolders as locations, group files by their parent directory
        # and set location before processing each group
        subfolder_map: dict[str, str] = {}
        if req.use_subfolders_as_locations:
            for f in files:
                rel = f.path.relative_to(folder)
                if len(rel.parts) > 1:
                    subfolder_name = rel.parts[0]
                else:
                    subfolder_name = folder.name
                subfolder_map[str(f.path)] = subfolder_name
                db.create_location(subfolder_name)

        # Phase 2: Process
        processed = 0
        items_created = 0
        locations: set[str] = set()

        for file_info in files:
            processed += 1

            # Set location from subfolder if using that method
            if req.use_subfolders_as_locations and str(file_info.path) in subfolder_map:
                pipeline.current_location_id = subfolder_map[str(file_info.path)]

            yield _sse(ProcessStatus(
                phase="processing",
                total_files=len(files),
                processed=processed,
                current_file=file_info.path.name,
                items_created=items_created,
                locations_found=sorted(locations),
                message=f"Processing {processed}/{len(files)}...",
            ))
            await asyncio.sleep(0)

            try:
                result = await asyncio.to_thread(
                    pipeline._process_single_file, file_info
                )
                if result and result.items_created > 0:
                    items_created += result.items_created
                if pipeline.current_location_id:
                    locations.add(pipeline.current_location_id)
            except Exception as e:
                yield _sse(ProcessStatus(
                    phase="processing",
                    total_files=len(files),
                    processed=processed,
                    message=f"Warning: {file_info.path.name}: {e}",
                ))

        # Phase 3: Complete
        yield _sse(ProcessStatus(
            phase="complete",
            total_files=len(files),
            processed=processed,
            items_created=items_created,
            locations_found=sorted(locations),
            message=f"Done! {items_created} items catalogued from {processed} images.",
        ))

    except Exception as e:
        yield _sse(ProcessStatus(phase="error", message=str(e)))


def _sse(status: ProcessStatus) -> str:
    """Format a ProcessStatus as an SSE event."""
    return f"data: {json.dumps(status.model_dump())}\n\n"


class AutoEnhanceRequest(BaseModel):
    """Request to auto-enhance all item images."""

    auto_crop: bool = True
    auto_rotate: bool = True


@router.post("/auto-enhance-all")
async def auto_enhance_all(req: AutoEnhanceRequest, db: DbDep) -> StreamingResponse:
    """Auto-crop and deskew all item images. Streams progress as SSE."""
    return StreamingResponse(
        _enhance_stream(db, req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _enhance_stream(
    db: Database, req: AutoEnhanceRequest
) -> AsyncGenerator[str, None]:
    """Stream auto-enhance progress."""
    from cataloguer.processor.image_ops import (
        auto_crop as do_crop,
        auto_rotate as do_rotate,
        create_thumbnail,
        decode_jpeg,
        encode_jpeg,
    )

    try:
        item_ids = db.get_all_item_ids()
        total = len(item_ids)

        yield f"data: {json.dumps({'phase': 'enhancing', 'total': total, 'processed': 0, 'enhanced': 0, 'message': f'Processing {total} items...'})}\n\n"
        await asyncio.sleep(0)

        enhanced_count = 0
        for i, item_id in enumerate(item_ids):
            try:
                blob = db.get_item_image(item_id, "full")
                if not blob:
                    continue

                image = await asyncio.to_thread(decode_jpeg, blob)
                original_shape = image.shape

                if req.auto_crop:
                    image = await asyncio.to_thread(do_crop, image)
                if req.auto_rotate:
                    image = await asyncio.to_thread(do_rotate, image)

                # Only save if something changed
                if image.shape != original_shape:
                    h, w = image.shape[:2]
                    full_jpeg = await asyncio.to_thread(encode_jpeg, image)
                    thumb = await asyncio.to_thread(create_thumbnail, image)
                    th, tw = thumb.shape[:2]
                    thumb_jpeg = await asyncio.to_thread(encode_jpeg, thumb)

                    await asyncio.to_thread(db.replace_image, item_id, "full", full_jpeg, w, h)
                    await asyncio.to_thread(db.replace_image, item_id, "thumb", thumb_jpeg, tw, th)
                    enhanced_count += 1
            except Exception:
                pass  # Skip individual failures

            if (i + 1) % 10 == 0 or i == total - 1:
                yield f"data: {json.dumps({'phase': 'enhancing', 'total': total, 'processed': i + 1, 'enhanced': enhanced_count, 'message': f'Processed {i + 1}/{total}...'})}\n\n"
                await asyncio.sleep(0)

        yield f"data: {json.dumps({'phase': 'complete', 'total': total, 'processed': total, 'enhanced': enhanced_count, 'message': f'Done! Enhanced {enhanced_count} of {total} items.'})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'phase': 'error', 'message': str(e)})}\n\n"


@router.post("/scan-folder")
async def scan_folder(body: dict[str, str]) -> FolderInfo:
    """Preview a folder before processing — count images, detect subfolders."""
    folder_path = body.get("folder_path", "")
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Invalid folder: {folder_path}")

    image_extensions = {
        ".jpg", ".jpeg", ".png", ".tiff", ".tif",
        ".arw", ".cr2", ".cr3", ".nef", ".raf",
        ".orf", ".rw2", ".pef", ".rwl", ".3fr",
        ".erf", ".kdc", ".dcr", ".mrw", ".x3f", ".dng",
    }

    image_files: list[str] = []
    subfolders: set[str] = set()

    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in image_extensions:
            image_files.append(str(p.relative_to(folder)))
            if p.parent != folder:
                subfolders.add(str(p.parent.relative_to(folder)))

    return FolderInfo(
        path=str(folder),
        image_count=len(image_files),
        image_files=image_files[:100],  # Preview first 100
        has_qr_codes=False,  # Would need to actually scan to know
        subfolder_count=len(subfolders),
        subfolders=sorted(subfolders)[:50],
    )
