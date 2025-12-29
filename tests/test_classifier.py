"""Tests for the image classifier."""

from pathlib import Path

import pytest

from cataloguer.processor.classifier import ClassificationResult, ImageClassifier, ImageType

# Sample data paths
DATA_DIR = Path(__file__).parent.parent / "data"
RX100_DIR = DATA_DIR / "RX100"
NEX3N_DIR = DATA_DIR / "NEX3N"


@pytest.fixture
def classifier() -> ImageClassifier:
    """Create a classifier instance."""
    return ImageClassifier()


class TestBoxDividerDetection:
    """Tests for box divider detection (QR code and OCR)."""

    def test_detect_qr_code_divider(self, classifier: ImageClassifier) -> None:
        """Test detection of box divider with QR code."""
        # DSC00427.JPG is a box divider with QR code containing "BOX-1"
        result = classifier.classify_file(RX100_DIR / "DSC00427.JPG")

        assert result.image_type == ImageType.BOX_DIVIDER
        assert result.box_id == "BOX-1"
        assert result.detection_method == "qr"
        assert result.confidence == 1.0


class TestBlackFrameDetection:
    """Tests for black frame (sequence ender) detection."""

    def test_detect_black_frame(self, classifier: ImageClassifier) -> None:
        """Test detection of black frame."""
        # DSC00478.JPG is a black frame
        result = classifier.classify_file(RX100_DIR / "DSC00478.JPG")

        assert result.image_type == ImageType.BLACK_FRAME
        assert result.detection_method == "brightness"
        assert result.confidence == 1.0


class TestGameItemDetection:
    """Tests for game item detection (default classification)."""

    def test_detect_game_item(self, classifier: ImageClassifier) -> None:
        """Test detection of game item."""
        # DSC00428.JPG is a game (Cricket 2004 PS2)
        result = classifier.classify_file(RX100_DIR / "DSC00428.JPG")

        assert result.image_type == ImageType.GAME_ITEM
        assert result.box_id is None
        assert result.confidence == 1.0


class TestRawFileSupport:
    """Tests for RAW file (ARW) support."""

    def test_load_arw_file(self, classifier: ImageClassifier) -> None:
        """Test that ARW files can be loaded and classified."""
        # DSC01169.ARW should be classifiable
        result = classifier.classify_file(NEX3N_DIR / "DSC01169.ARW")

        # Should return a valid classification (any type)
        assert result.image_type in [
            ImageType.BOX_DIVIDER,
            ImageType.BLACK_FRAME,
            ImageType.GAME_ITEM,
        ]
        assert result.confidence > 0


class TestBrightnessAnalysis:
    """Tests for brightness analysis helper."""

    def test_brightness_info_black_frame(self, classifier: ImageClassifier) -> None:
        """Test brightness info for black frame."""
        import cv2

        image = cv2.imread(str(RX100_DIR / "DSC00478.JPG"))
        info = classifier.get_brightness_info(image)

        assert info["is_black"] is True
        assert info["mean"] < 25

    def test_brightness_info_normal_image(self, classifier: ImageClassifier) -> None:
        """Test brightness info for normal image."""
        import cv2

        image = cv2.imread(str(RX100_DIR / "DSC00428.JPG"))
        info = classifier.get_brightness_info(image)

        assert info["is_black"] is False
        assert info["mean"] > 25
