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
from cataloguer.database.models import Database

router = APIRouter()


class ProcessRequest(BaseModel):
    """Request to process a folder of images."""

    folder_path: str
    default_location: str | None = None
    offline: bool = False
    provider: str = "auto"
    resume: bool = True


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
        )

        # If a provider is specified and not offline, set up identifier
        if not req.offline and req.provider != "none":
            try:
                from cataloguer.processor.identifier import ItemIdentifier

                identifier = ItemIdentifier(provider=req.provider)
                pipeline.identifier = identifier
            except Exception:
                pass  # Fall back to offline

        # Override starting location if provided
        if req.default_location:
            pipeline.current_location_id = req.default_location
            db.ensure_location(req.default_location)

        # Phase 1: Scan
        yield _sse(ProcessStatus(phase="scanning", message="Scanning folder..."))
        await asyncio.sleep(0)  # Yield control

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

        # Phase 2: Process
        processed = 0
        items_created = 0
        locations: set[str] = set()

        for file_info in files:
            processed += 1
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
                    pipeline.process_single_file, file_info
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
