"""Processing routes — import and process image folders from the frontend."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cataloguer.api.deps import DbDep
from cataloguer.api.routes.settings import resolve_setting
from cataloguer.database.models import Database

router = APIRouter()


def _resolve_import_folder(folder_path: str) -> Path:
    """Resolve and validate a user-supplied folder path for import/scanning.

    Without this, an unauthenticated caller can point /process or /scan-folder
    at any directory on the host ("/", "/etc", ...) and enumerate or ingest it.

    If the VISCATALOG_IMPORT_ROOT environment variable is set, the resolved path
    must stay within it (otherwise 403). When it is unset the path is still
    resolved (collapsing any "..") but not otherwise confined, preserving the
    local single-user workflow of importing from anywhere on the machine — the
    primary protection there is binding the server to localhost.
    """
    if not folder_path:
        raise HTTPException(status_code=400, detail="No folder path provided")

    folder = Path(folder_path).resolve()

    import_root = os.environ.get("VISCATALOG_IMPORT_ROOT")
    if import_root:
        root = Path(import_root).resolve()
        if folder != root and root not in folder.parents:
            raise HTTPException(
                status_code=403,
                detail="Folder is outside the permitted import root",
            )

    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Folder not found: {folder_path}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {folder_path}")

    return folder


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
    ai_rotate: bool = False


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
    folder = _resolve_import_folder(req.folder_path)

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
            ai_rotate=req.ai_rotate,
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
                subfolder_name = rel.parts[0] if len(rel.parts) > 1 else folder.name
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
                    pipeline._process_single_file, file_info, None, req.resume
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
    ai_rotate: bool = False


# Background job state — shared across requests
_enhance_job: dict[str, object] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "enhanced": 0,
    "message": "",
    "phase": "idle",  # idle, enhancing, complete, error
}

# Hold a reference to the running task so it isn't garbage-collected mid-run
# (asyncio only keeps a weak reference to fire-and-forget tasks).
_enhance_task: asyncio.Task[None] | None = None


@router.get("/auto-enhance-status")
def get_enhance_status() -> dict[str, object]:
    """Get the current status of the background auto-enhance job."""
    return dict(_enhance_job)


@router.post("/auto-enhance-all")
async def auto_enhance_all(req: AutoEnhanceRequest, db: DbDep) -> dict[str, str]:
    """Start background auto-enhance job. Returns immediately."""
    if _enhance_job["running"]:
        raise HTTPException(status_code=409, detail="Auto-enhance already running")

    # Reset state
    _enhance_job.update(
        running=True, total=0, processed=0, enhanced=0,
        message="Starting...", phase="enhancing",
    )

    # Launch background task, keeping a reference so it can't be GC'd mid-run.
    global _enhance_task
    _enhance_task = asyncio.create_task(_enhance_background(db, req))

    return {"status": "started"}


async def _enhance_background(db: Database, req: AutoEnhanceRequest) -> None:
    """Run auto-enhance in the background, updating _enhance_job state."""
    import numpy as np

    from cataloguer.processor.image_ops import (
        auto_crop as do_crop,
    )
    from cataloguer.processor.image_ops import (
        auto_rotate as do_rotate,
    )
    from cataloguer.processor.image_ops import (
        create_thumbnail,
        decode_jpeg,
        encode_jpeg,
        rotate_by_degrees,
    )

    # Set up AI identifier if AI rotation requested
    identifier = None
    if req.ai_rotate:
        try:
            from cataloguer.processor.identifier import ItemIdentifier

            provider = resolve_setting(db, "ai_provider")
            if provider == "auto":
                provider = "claude"
            identifier = ItemIdentifier(
                provider=provider,
                model=resolve_setting(db, f"{provider}_model") or None,
                api_key=resolve_setting(db, "anthropic_api_key") or None,
                ollama_host=resolve_setting(db, "ollama_host"),
            )
        except Exception as e:
            _enhance_job.update(running=False, phase="error", message=f"Failed to set up AI: {e}")
            return

    try:
        item_ids = db.get_all_item_ids()
        total = len(item_ids)
        _enhance_job.update(total=total, message=f"Processing {total} items...")

        enhanced_count = 0
        for i, item_id in enumerate(item_ids):
            try:
                blob = db.get_item_image(item_id, "full")
                if not blob:
                    continue

                image = await asyncio.to_thread(decode_jpeg, blob)
                original = image  # ops below return new arrays, so identity/compare is safe

                # AI-based rotation detection
                if req.ai_rotate and identifier:
                    try:
                        import cv2
                        h, w = image.shape[:2]
                        if max(h, w) > 1024:
                            scale = 1024 / max(h, w)
                            small = cv2.resize(image, None, fx=scale, fy=scale)
                        else:
                            small = image
                        small_jpeg = await asyncio.to_thread(encode_jpeg, small, 70)
                        result = await asyncio.to_thread(
                            identifier.classify_and_identify, small_jpeg
                        )
                        if result.rotation_needed:
                            image = rotate_by_degrees(image, result.rotation_needed)
                    except Exception:
                        pass

                if req.auto_crop:
                    image = await asyncio.to_thread(do_crop, image)
                if req.auto_rotate:
                    image = await asyncio.to_thread(do_rotate, image)

                changed = image.shape != original.shape or not np.array_equal(image, original)
                if changed:
                    h, w = image.shape[:2]
                    full_jpeg = await asyncio.to_thread(encode_jpeg, image)
                    thumb = await asyncio.to_thread(create_thumbnail, image)
                    th, tw = thumb.shape[:2]
                    thumb_jpeg = await asyncio.to_thread(encode_jpeg, thumb)

                    await asyncio.to_thread(db.replace_image, item_id, "full", full_jpeg, w, h)
                    await asyncio.to_thread(db.replace_image, item_id, "thumb", thumb_jpeg, tw, th)
                    enhanced_count += 1
            except Exception:
                pass

            _enhance_job.update(
                processed=i + 1,
                enhanced=enhanced_count,
                message=f"Processed {i + 1}/{total}...",
            )
            # Yield control so the status endpoint can respond
            await asyncio.sleep(0)

        _enhance_job.update(
            phase="complete",
            processed=total, enhanced=enhanced_count,
            message=f"Done! Enhanced {enhanced_count} of {total} items.",
        )

    except Exception as e:
        _enhance_job.update(phase="error", message=str(e))
    finally:
        # Always clear the running flag — otherwise a crash or cancellation
        # wedges the job at running=True and every future start returns 409.
        _enhance_job["running"] = False


@router.post("/scan-folder")
async def scan_folder(body: dict[str, str]) -> FolderInfo:
    """Preview a folder before processing — count images, detect subfolders."""
    folder = _resolve_import_folder(body.get("folder_path", ""))

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
