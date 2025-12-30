"""Main processing pipeline for visual-cataloguer.

Orchestrates the image processing workflow:
1. Scan directories for images
2. Build timeline from EXIF data
3. Classify each image (box divider, black frame, game item)
4. Process game items (OCR, thumbnails)
5. Store results in database
"""

import hashlib
import io
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import cv2
import exifread
import numpy as np
from PIL import Image
from tqdm import tqdm

from cataloguer.database.models import Database, Item
from cataloguer.processor.classifier import ClassificationResult, ImageClassifier, ImageType
from cataloguer.processor.identifier import IdentificationResult, ItemIdentifier


@dataclass
class ImageFile:
    """Represents an image file with metadata."""

    path: Path
    camera: str  # "NEX-3N" or "RX100M4"
    captured_at: datetime | None
    file_hash: str


@dataclass
class ProcessingResult:
    """Result of processing a single image."""

    source_path: Path
    source_hash: str
    status: str  # 'success', 'failed', 'skipped'
    image_type: ImageType | None = None
    items_created: int = 0
    error_message: str | None = None
    location_id: str | None = None


class ProcessingPipeline:
    """Main processing pipeline for cataloguing images."""

    # RAW file extensions supported by LibRaw/rawpy
    RAW_EXTENSIONS: ClassVar[set[str]] = {
        ".arw", ".srf", ".sr2",  # Sony
        ".cr2", ".cr3", ".crw",  # Canon
        ".nef", ".nrw",          # Nikon
        ".raf",                   # Fuji
        ".orf",                   # Olympus
        ".rw2",                   # Panasonic
        ".pef",                   # Pentax
        ".dng",                   # Adobe DNG (universal)
        ".rwl",                   # Leica
        ".3fr",                   # Hasselblad
        ".erf",                   # Epson
        ".kdc", ".dcr",          # Kodak
        ".mrw",                   # Minolta
        ".x3f",                   # Sigma
    }

    # JPEG extensions
    JPEG_EXTENSIONS: ClassVar[set[str]] = {".jpg", ".jpeg"}

    # All supported extensions
    SUPPORTED_EXTENSIONS: ClassVar[set[str]] = RAW_EXTENSIONS | JPEG_EXTENSIONS | {".png", ".tiff", ".tif"}

    def __init__(
        self,
        database: Database,
        classifier: ImageClassifier | None = None,
        identifier: ItemIdentifier | None = None,
        ai_mode: str = "none",  # "none", "fallback", "all"
        jpeg_quality: int = 85,
        thumbnail_size: int = 400,
    ) -> None:
        """Initialize the pipeline.

        Args:
            database: Database instance for storing results
            classifier: Image classifier (creates default if not provided)
            identifier: Item identifier for AI-based identification
            ai_mode: When to use AI identification:
                     - "none": Never use AI (OCR only)
                     - "fallback": Use AI when OCR fails or low confidence
                     - "all": Use AI for all items
            jpeg_quality: JPEG quality for stored images (0-100)
            thumbnail_size: Max dimension for thumbnails
        """
        self.db = database
        self.classifier = classifier or ImageClassifier()
        self.identifier = identifier
        self.ai_mode = ai_mode
        self.jpeg_quality = jpeg_quality
        self.thumbnail_size = thumbnail_size

        # State machine
        self.current_location_id: str | None = None
        self.unknown_location_counter: int = 0  # Counter for auto-generated UNKNOWN locations
        # Track last processed image type to handle consecutive duplicates
        self.last_image_type: ImageType | None = None
        self.last_location_id: str | None = None

    def scan_directory(self, input_dir: Path) -> list[ImageFile]:
        """Scan input directory recursively for image files.

        Args:
            input_dir: Directory to scan (includes all subdirectories)

        Returns:
            List of ImageFile objects sorted by capture time
        """
        files: list[ImageFile] = []
        seen_paths: set[Path] = set()  # Avoid duplicates from case variations

        if not input_dir.exists():
            return files

        # Scan recursively for all supported extensions (case-insensitive)
        for ext in self.SUPPORTED_EXTENSIONS:
            # Lowercase pattern
            for path in input_dir.rglob(f"*{ext}"):
                if path.is_file() and path not in seen_paths:
                    seen_paths.add(path)
                    camera = self._detect_camera(path)
                    captured_at = self._get_capture_time(path)
                    file_hash = self._compute_hash(path)
                    files.append(ImageFile(path, camera, captured_at, file_hash))
            # Uppercase pattern
            for path in input_dir.rglob(f"*{ext.upper()}"):
                if path.is_file() and path not in seen_paths:
                    seen_paths.add(path)
                    camera = self._detect_camera(path)
                    captured_at = self._get_capture_time(path)
                    file_hash = self._compute_hash(path)
                    files.append(ImageFile(path, camera, captured_at, file_hash))

        # Sort by capture time (None values go to end)
        files.sort(key=lambda f: f.captured_at or datetime.max)
        return files

    def _detect_camera(self, path: Path) -> str:
        """Detect camera model from EXIF data or file extension."""
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f, stop_tag="Model", details=False)

            model = tags.get("Image Model")
            if model:
                return str(model).strip()
        except Exception:
            pass

        # Fallback: use extension to guess camera type
        ext = path.suffix.lower()
        extension_hints = {
            ".arw": "Sony", ".srf": "Sony", ".sr2": "Sony",
            ".cr2": "Canon", ".cr3": "Canon", ".crw": "Canon",
            ".nef": "Nikon", ".nrw": "Nikon",
            ".raf": "Fujifilm",
            ".orf": "Olympus",
            ".rw2": "Panasonic",
            ".pef": "Pentax",
            ".dng": "DNG",
            ".rwl": "Leica",
        }
        return extension_hints.get(ext, "UNKNOWN")

    def _get_capture_time(self, path: Path) -> datetime | None:
        """Extract capture time from EXIF data."""
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f, stop_tag="DateTimeOriginal", details=False)

            dt_tag = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
            if dt_tag:
                return datetime.strptime(str(dt_tag), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
        return None

    def _compute_hash(self, path: Path) -> str:
        """Compute SHA256 hash of file."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def process_files(
        self,
        files: list[ImageFile],
        done_dir: Path | None = None,
        resume: bool = True,
        progress_callback: Callable[[ProcessingResult], None] | None = None,
    ) -> list[ProcessingResult]:
        """Process a list of image files.

        Args:
            files: List of ImageFile objects to process
            done_dir: Directory to move processed files to
            resume: Skip already-processed files
            progress_callback: Optional callback for progress updates

        Returns:
            List of ProcessingResult objects
        """
        results: list[ProcessingResult] = []

        for image_file in tqdm(files, desc="Processing images"):
            result = self._process_single_file(
                image_file, done_dir=done_dir, resume=resume
            )
            results.append(result)

            if progress_callback:
                progress_callback(result)

        return results

    def _process_single_file(
        self,
        image_file: ImageFile,
        done_dir: Path | None = None,
        resume: bool = True,
    ) -> ProcessingResult:
        """Process a single image file."""
        # Check if already processed
        if resume and self.db.is_processed(image_file.file_hash):
            return ProcessingResult(
                source_path=image_file.path,
                source_hash=image_file.file_hash,
                status="skipped",
            )

        try:
            # Classify the image
            classification = self.classifier.classify_file(image_file.path)
            result = self._handle_classification(image_file, classification)

            # Log success
            self.db.log_processing(
                str(image_file.path),
                image_file.file_hash,
                "success",
                items_created=result.items_created,
            )

            # Move to done directory if provided
            if done_dir and result.status == "success":
                self._move_to_done(image_file.path, done_dir, image_file.camera)

            return result

        except Exception as e:
            error_msg = str(e)
            self.db.log_processing(
                str(image_file.path),
                image_file.file_hash,
                "failed",
                error_message=error_msg,
            )
            return ProcessingResult(
                source_path=image_file.path,
                source_hash=image_file.file_hash,
                status="failed",
                error_message=error_msg,
            )

    def _handle_classification(
        self, image_file: ImageFile, classification: ClassificationResult
    ) -> ProcessingResult:
        """Handle a classified image based on its type.

        Handles consecutive duplicate dividers:
        - Multiple BLACK_FRAMEs in a row: skip after the first (already cleared location)
        - Multiple LOCATION_DIVIDERs with same ID: skip duplicates
        - Multiple LOCATION_DIVIDERs with different IDs: use the new one
        """
        current_type = classification.image_type

        # Handle consecutive BLACK_FRAMEs - skip if we already cleared location
        if current_type == ImageType.BLACK_FRAME:
            if self.last_image_type == ImageType.BLACK_FRAME:
                # Consecutive black frame - skip it
                return ProcessingResult(
                    source_path=image_file.path,
                    source_hash=image_file.file_hash,
                    status="skipped",
                    image_type=ImageType.BLACK_FRAME,
                )
            # Process the black frame
            result = self._handle_black_frame(image_file)
            self.last_image_type = ImageType.BLACK_FRAME
            self.last_location_id = None
            return result

        # Handle consecutive LOCATION_DIVIDERs
        if current_type == ImageType.LOCATION_DIVIDER:
            new_location_id = classification.location_id
            if (
                self.last_image_type == ImageType.LOCATION_DIVIDER
                and self.last_location_id == new_location_id
            ):
                # Same location divider repeated - skip it
                return ProcessingResult(
                    source_path=image_file.path,
                    source_hash=image_file.file_hash,
                    status="skipped",
                    image_type=ImageType.LOCATION_DIVIDER,
                    location_id=new_location_id,
                )
            # Process the location divider (new location or first divider)
            result = self._handle_location_divider(image_file, classification)
            self.last_image_type = ImageType.LOCATION_DIVIDER
            self.last_location_id = new_location_id
            return result

        # Handle game item - always process, reset consecutive tracking
        result = self._handle_game_item(image_file, classification)
        self.last_image_type = ImageType.GAME_ITEM
        self.last_location_id = None
        return result

    def _handle_location_divider(
        self, image_file: ImageFile, classification: ClassificationResult
    ) -> ProcessingResult:
        """Handle a location divider image."""
        location_id = classification.location_id
        if location_id:
            self.current_location_id = location_id
            self.db.create_location(location_id)

        return ProcessingResult(
            source_path=image_file.path,
            source_hash=image_file.file_hash,
            status="success",
            image_type=ImageType.LOCATION_DIVIDER,
            location_id=location_id,
        )

    def _handle_black_frame(self, image_file: ImageFile) -> ProcessingResult:
        """Handle a black frame (sequence ender)."""
        self.current_location_id = None
        return ProcessingResult(
            source_path=image_file.path,
            source_hash=image_file.file_hash,
            status="success",
            image_type=ImageType.BLACK_FRAME,
        )

    def _handle_game_item(
        self, image_file: ImageFile, classification: ClassificationResult
    ) -> ProcessingResult:
        """Handle a game item image."""
        # If no active location, create an UNKNOWN location (missed divider recovery)
        if self.current_location_id is None:
            self.unknown_location_counter += 1
            self.current_location_id = f"UNKNOWN-{self.unknown_location_counter}"
            self.db.create_location(
                self.current_location_id, label="Auto-created (missing divider)"
            )

        # Load the image
        image = self._load_image(image_file.path)

        # Run OCR to extract text
        ocr_text = self._extract_text(image)
        ocr_title = self._guess_title(ocr_text)

        # Determine if we should use AI identification
        use_ai = self._should_use_ai(ocr_text, ocr_title)
        ai_result: IdentificationResult | None = None

        if use_ai and self.identifier:
            try:
                # Use JPEG for AI identification (more efficient than RAW)
                jpeg_for_ai = self._encode_jpeg(image)
                ai_result = self.identifier.identify_bytes(jpeg_for_ai)
            except Exception as e:
                # AI failed, fall back to OCR
                ai_result = None
                # Add note about AI failure
                classification = ClassificationResult(
                    image_type=classification.image_type,
                    confidence=classification.confidence,
                    needs_review=True,
                    review_reason=f"AI identification failed: {e}",
                )

        # Create thumbnail
        thumbnail = self._create_thumbnail(image)

        # Encode images as JPEG
        full_jpeg = self._encode_jpeg(image)
        thumb_jpeg = self._encode_jpeg(thumbnail)

        # Build item from OCR and/or AI results
        item = self._build_item(
            image_file=image_file,
            ocr_text=ocr_text,
            ocr_title=ocr_title,
            ai_result=ai_result,
            classification=classification,
        )

        item_id = self.db.create_item(item)

        # Store images
        h, w = image.shape[:2]
        self.db.add_image(item_id, "full", full_jpeg, w, h, is_cover=True)

        th, tw = thumbnail.shape[:2]
        self.db.add_image(item_id, "thumb", thumb_jpeg, tw, th)

        return ProcessingResult(
            source_path=image_file.path,
            source_hash=image_file.file_hash,
            status="success",
            image_type=ImageType.GAME_ITEM,
            items_created=1,
            location_id=self.current_location_id,
        )

    def _should_use_ai(self, ocr_text: str | None, ocr_title: str | None) -> bool:
        """Determine if AI identification should be used."""
        if self.ai_mode == "none":
            return False
        if self.ai_mode == "all":
            return True
        # "fallback" mode - use AI if OCR didn't give us a good title
        if not ocr_title or len(ocr_title) < 3:
            return True
        # Also use AI if OCR text is very short (likely no readable text)
        return not ocr_text or len(ocr_text.strip()) < 10

    def _build_item(
        self,
        image_file: ImageFile,
        ocr_text: str | None,
        ocr_title: str | None,
        ai_result: IdentificationResult | None,
        classification: ClassificationResult,
    ) -> Item:
        """Build an Item from OCR and AI identification results."""
        import json

        # Start with OCR-based defaults
        title_guess = ocr_title
        platform_guess = None
        item_type = "game"
        completeness = "unknown"
        brand = None
        region = None
        year = None
        ai_description = None
        ai_identified = False
        needs_review = classification.needs_review
        review_reason = classification.review_reason

        # Override with AI results if available
        if ai_result:
            ai_identified = True
            ai_description = json.dumps(ai_result.raw_response)

            # Use AI title if OCR didn't get one or AI has higher confidence
            if ai_result.title:
                title_guess = ai_result.title

            if ai_result.platform:
                platform_guess = ai_result.platform

            if ai_result.item_type:
                item_type = ai_result.item_type.value

            if ai_result.completeness:
                completeness = ai_result.completeness

            if ai_result.brand:
                brand = ai_result.brand

            if ai_result.region:
                region = ai_result.region

            if ai_result.year:
                year = ai_result.year

            # Flag low-confidence AI results for review
            if ai_result.confidence == "low":
                needs_review = True
                review_reason = "Low AI confidence"

        return Item(
            location_id=self.current_location_id,
            source_camera=image_file.camera,
            source_filename=image_file.path.name,
            source_hash=image_file.file_hash,
            captured_at=image_file.captured_at,
            source_item_group=str(uuid.uuid4()),
            object_index=1,
            is_primary_image=True,
            item_type=item_type,
            ai_description=ai_description,
            ai_identified=ai_identified,
            object_count=1,
            completeness=completeness,
            ocr_text_raw=ocr_text,
            title_guess=title_guess,
            platform_guess=platform_guess,
            brand=brand,
            region=region,
            year=year,
            needs_review=needs_review,
            review_reason=review_reason,
        )

    def _load_image(self, path: Path) -> np.ndarray:
        """Load an image file (supports RAW, JPEG, PNG, TIFF)."""
        suffix = path.suffix.lower()
        if suffix in self.RAW_EXTENSIONS:
            import rawpy

            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True)
                bgr: np.ndarray = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                return bgr
        else:
            image = cv2.imread(str(path))
            if image is None:
                raise ValueError(f"Failed to load image: {path}")
            return image

    def _extract_text(self, image: np.ndarray) -> str | None:
        """Extract text from image using OCR."""
        try:
            import pytesseract

            # Resize for faster OCR
            h, w = image.shape[:2]
            max_dim = 2000
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                image = cv2.resize(image, None, fx=scale, fy=scale)

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            text = pytesseract.image_to_string(gray, config="--psm 6")
            return text.strip() if text.strip() else None
        except Exception:
            return None

    def _guess_title(self, ocr_text: str | None) -> str | None:
        """Attempt to guess game title from OCR text."""
        if not ocr_text:
            return None

        # Simple heuristic: take first non-empty line that's reasonably long
        for line in ocr_text.split("\n"):
            line = line.strip()
            if len(line) > 3 and not line.isdigit():
                return line[:100]  # Limit length
        return None

    def _create_thumbnail(self, image: np.ndarray) -> np.ndarray:
        """Create a thumbnail of the image."""
        h, w = image.shape[:2]
        if max(h, w) <= self.thumbnail_size:
            return image.copy()

        scale = self.thumbnail_size / max(h, w)
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    def _encode_jpeg(self, image: np.ndarray) -> bytes:
        """Encode image as JPEG bytes."""
        # Convert BGR to RGB for PIL
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)

        buffer = io.BytesIO()
        pil_image.save(buffer, format="JPEG", quality=self.jpeg_quality)
        return buffer.getvalue()

    def _move_to_done(self, source: Path, done_dir: Path, camera: str) -> None:
        """Move processed file to done directory."""
        target_dir = done_dir / camera
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        shutil.move(str(source), str(target))


def process_collection(
    input_dir: Path,
    database_path: Path = Path("collection.db"),
    done_dir: Path | None = None,
    resume: bool = True,
) -> dict[str, int]:
    """Process a collection of images.

    High-level function for processing a complete collection.

    Args:
        input_dir: Input directory (scans recursively)
        database_path: Path to SQLite database
        done_dir: Directory to move processed files to
        resume: Skip already-processed files

    Returns:
        Dictionary with processing statistics
    """
    db = Database(database_path)
    pipeline = ProcessingPipeline(db)

    # Scan directory recursively
    files = pipeline.scan_directory(input_dir)
    print(f"Found {len(files)} files to process")

    # Process files
    results = pipeline.process_files(files, done_dir=done_dir, resume=resume)

    # Compute statistics
    stats = {
        "total_files": len(results),
        "successful": sum(1 for r in results if r.status == "success"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "items_created": sum(r.items_created for r in results),
        "location_dividers": sum(
            1 for r in results if r.image_type == ImageType.LOCATION_DIVIDER
        ),
        "black_frames": sum(1 for r in results if r.image_type == ImageType.BLACK_FRAME),
        "game_items": sum(1 for r in results if r.image_type == ImageType.GAME_ITEM),
    }

    return stats
