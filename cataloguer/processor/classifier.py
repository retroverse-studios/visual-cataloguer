"""Image classification for the visual cataloguer pipeline.

Classifies images into three types:
- LOCATION_DIVIDER: QR code or text indicating a new location/section
- BLACK_FRAME: Dark image signaling end of current location
- GAME_ITEM: Everything else (actual items to catalogue)
"""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np
import pytesseract

# RAW file extensions supported by LibRaw/rawpy
RAW_EXTENSIONS: set[str] = {
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


class ImageType(Enum):
    """Types of images in the cataloguing workflow."""

    LOCATION_DIVIDER = "location_divider"
    BLACK_FRAME = "black_frame"
    GAME_ITEM = "game_item"


@dataclass
class ClassificationResult:
    """Result of image classification."""

    image_type: ImageType
    confidence: float  # 0.0 - 1.0
    location_id: str | None = None  # For LOCATION_DIVIDER type
    detection_method: str | None = None  # 'qr', 'ocr_printed', 'ocr_handwritten'
    raw_text: str | None = None  # Any text detected
    needs_review: bool = False
    review_reason: str | None = None


class ImageClassifier:
    """Classifies images in the cataloguing pipeline."""

    # Box identifier patterns
    BOX_PATTERN_STRICT = re.compile(r"BOX[-\s]?(\d+)", re.IGNORECASE)
    BOX_PATTERN_FLEXIBLE = re.compile(r"([A-Z]+)[-\s]?(\d+)", re.IGNORECASE)

    # Thresholds
    BLACK_FRAME_THRESHOLD = 25  # Mean brightness below this = black frame
    OCR_HIGH_CONFIDENCE = 80  # Printed text threshold
    OCR_LOW_CONFIDENCE = 60  # Handwritten text threshold

    def __init__(
        self,
        black_threshold: int = 25,
        ocr_high_confidence: int = 80,
        ocr_low_confidence: int = 60,
    ):
        """Initialize the classifier.

        Args:
            black_threshold: Mean brightness threshold for black frame detection (0-255)
            ocr_high_confidence: Confidence threshold for printed text (0-100)
            ocr_low_confidence: Confidence threshold for handwritten text (0-100)
        """
        self.black_threshold = black_threshold
        self.ocr_high_confidence = ocr_high_confidence
        self.ocr_low_confidence = ocr_low_confidence

    def classify(self, image: np.ndarray) -> ClassificationResult:
        """Classify an image.

        Args:
            image: OpenCV image (BGR format)

        Returns:
            ClassificationResult with type and metadata
        """
        # Check for black frame first (fastest)
        if self._is_black_frame(image):
            return ClassificationResult(
                image_type=ImageType.BLACK_FRAME,
                confidence=1.0,
                detection_method="brightness",
            )

        # Try QR code detection
        qr_result = self._detect_qr_code(image)
        if qr_result:
            return qr_result

        # Try OCR for text-based dividers
        ocr_result = self._detect_text_divider(image)
        if ocr_result:
            return ocr_result

        # Default: game item
        return ClassificationResult(
            image_type=ImageType.GAME_ITEM,
            confidence=1.0,
        )

    def classify_file(self, file_path: Path) -> ClassificationResult:
        """Classify an image file.

        Args:
            file_path: Path to image file (JPG, PNG, or ARW)

        Returns:
            ClassificationResult with type and metadata
        """
        image = self._load_image(file_path)
        return self.classify(image)

    def _load_image(self, file_path: Path) -> np.ndarray:
        """Load an image file into OpenCV format.

        Supports JPEG, PNG, TIFF, and RAW files (Canon, Nikon, Sony, Fuji, etc.).
        """
        suffix = file_path.suffix.lower()

        if suffix in RAW_EXTENSIONS:
            return self._load_raw(file_path)
        else:
            # Standard image formats (JPEG, PNG, TIFF, etc.)
            image = cv2.imread(str(file_path))
            if image is None:
                raise ValueError(f"Failed to load image: {file_path}")
            return image

    def _load_raw(self, file_path: Path) -> np.ndarray:
        """Load a RAW file using rawpy (supports all major camera brands)."""
        import rawpy

        with rawpy.imread(str(file_path)) as raw:
            # Process with default parameters for quick preview
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=True,  # Faster processing for classification
                no_auto_bright=False,
            )
            # Convert RGB to BGR for OpenCV
            bgr: np.ndarray = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            return bgr

    def _is_black_frame(self, image: np.ndarray) -> bool:
        """Check if image is a black frame (sequence ender).

        A black frame has mean brightness < threshold (~10% of 255).
        """
        # Convert to grayscale if needed
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        mean_brightness = float(np.mean(gray))
        return mean_brightness < self.black_threshold

    def _detect_qr_code(self, image: np.ndarray) -> ClassificationResult | None:
        """Attempt to detect and decode a QR code using OpenCV.

        Returns ClassificationResult if a valid location divider QR is found.
        """
        detector = cv2.QRCodeDetector()

        # Try at multiple scales for large images
        height, width = image.shape[:2]
        scales = [1.0]
        if max(height, width) > 2000:
            scales = [0.5, 0.25, 1.0]  # Try smaller first (faster)
        elif max(height, width) > 1000:
            scales = [0.5, 1.0]

        for scale in scales:
            if scale == 1.0:
                test_image = image
            else:
                test_image = cv2.resize(
                    image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                )

            # Try to detect and decode
            data, _points, _ = detector.detectAndDecode(test_image)

            if data:
                data = data.strip()
                # Check if it matches location pattern
                location_id = self._extract_location_id(data)
                if location_id:
                    return ClassificationResult(
                        image_type=ImageType.LOCATION_DIVIDER,
                        confidence=1.0,
                        location_id=location_id,
                        detection_method="qr",
                        raw_text=data,
                    )

        return None

    def _detect_text_divider(self, image: np.ndarray) -> ClassificationResult | None:
        """Use OCR to detect text-based location dividers.

        Tries to find BOX-X, SHELF-X, or similar patterns in large text.
        """
        # Preprocess for OCR
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Resize for faster OCR while maintaining readability
        height, width = gray.shape
        max_dim = 1500
        if max(height, width) > max_dim:
            scale = max_dim / max(height, width)
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        # Apply some preprocessing to help OCR
        # Threshold to get high-contrast text
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Run OCR with confidence data
        try:
            ocr_data = pytesseract.image_to_data(
                thresh, output_type=pytesseract.Output.DICT, config="--psm 6"
            )
        except pytesseract.TesseractNotFoundError:
            # Tesseract not installed - skip OCR detection
            return None

        # Collect text with confidence
        texts_with_conf = []
        for i, text in enumerate(ocr_data["text"]):
            conf = int(ocr_data["conf"][i])
            if text.strip() and conf > 0:
                texts_with_conf.append((text.strip(), conf))

        if not texts_with_conf:
            return None

        # Combine adjacent text into potential identifiers
        full_text = " ".join(t[0] for t in texts_with_conf)
        avg_confidence = sum(t[1] for t in texts_with_conf) / len(texts_with_conf)

        # Try to extract location ID
        location_id = self._extract_location_id(full_text)

        if location_id:
            # Determine detection type based on confidence
            if avg_confidence >= self.ocr_high_confidence:
                method = "ocr_printed"
                confidence = avg_confidence / 100
                needs_review = False
            elif avg_confidence >= self.ocr_low_confidence:
                method = "ocr_handwritten"
                confidence = avg_confidence / 100
                needs_review = True
                review_reason = f"Low OCR confidence ({avg_confidence:.0f}%)"
            else:
                # Below even handwritten threshold - don't treat as divider
                return None

            return ClassificationResult(
                image_type=ImageType.LOCATION_DIVIDER,
                confidence=confidence,
                location_id=location_id,
                detection_method=method,
                raw_text=full_text,
                needs_review=needs_review,
                review_reason=review_reason if needs_review else None,
            )

        return None

    def _extract_location_id(self, text: str) -> str | None:
        """Extract a location identifier from text.

        Recognizes patterns like:
        - BOX-1, BOX 1, BOX1
        - SHELF-A3, GARAGE-2, ROOM1-RACK2
        """
        # Try strict BOX pattern first
        match = self.BOX_PATTERN_STRICT.search(text)
        if match:
            return f"BOX-{match.group(1)}"

        # Try flexible pattern (LABEL-NUMBER)
        match = self.BOX_PATTERN_FLEXIBLE.search(text)
        if match:
            label = match.group(1).upper()
            number = match.group(2)
            return f"{label}-{number}"

        return None

    def get_brightness_info(self, image: np.ndarray) -> dict[str, float | int | bool]:
        """Get brightness statistics for debugging."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        mean_val = float(np.mean(gray))
        return {
            "mean": mean_val,
            "std": float(np.std(gray)),
            "min": int(np.min(gray)),
            "max": int(np.max(gray)),
            "is_black": bool(mean_val < self.black_threshold),
        }
