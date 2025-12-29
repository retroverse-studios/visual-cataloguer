"""Tests for the image classifier."""

from pathlib import Path

import pytest

from cataloguer.processor.classifier import ImageClassifier, ImageType

# Sample data paths
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def classifier() -> ImageClassifier:
    """Create a classifier instance."""
    return ImageClassifier()


class TestBoxDividerDetection:
    """Tests for box divider detection (QR code and OCR)."""

    def test_detect_qr_code_divider(self, classifier: ImageClassifier) -> None:
        """Test detection of box divider with QR code."""
        result = classifier.classify_file(FIXTURES_DIR / "divider.jpg")

        assert result.image_type == ImageType.BOX_DIVIDER
        assert result.box_id == "BOX-1"
        assert result.detection_method == "qr"
        assert result.confidence == 1.0


class TestBlackFrameDetection:
    """Tests for black frame (sequence ender) detection."""

    def test_detect_black_frame(self, classifier: ImageClassifier) -> None:
        """Test detection of black frame."""
        result = classifier.classify_file(FIXTURES_DIR / "black-frame.jpg")

        assert result.image_type == ImageType.BLACK_FRAME
        assert result.detection_method == "brightness"
        assert result.confidence == 1.0


class TestBrightnessAnalysis:
    """Tests for brightness analysis helper."""

    def test_brightness_info_black_frame(self, classifier: ImageClassifier) -> None:
        """Test brightness info for black frame."""
        import cv2

        image = cv2.imread(str(FIXTURES_DIR / "black-frame.jpg"))
        info = classifier.get_brightness_info(image)

        assert info["is_black"] is True
        assert info["mean"] < 25

    def test_brightness_info_normal_image(self, classifier: ImageClassifier) -> None:
        """Test brightness info for normal image."""
        import cv2

        image = cv2.imread(str(FIXTURES_DIR / "divider.jpg"))
        info = classifier.get_brightness_info(image)

        assert info["is_black"] is False
        assert info["mean"] > 25
