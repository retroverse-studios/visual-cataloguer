"""Tests for the processing pipeline, especially consecutive divider handling."""

import tempfile
from datetime import datetime
from pathlib import Path
import pytest

from cataloguer.database.models import Database
from cataloguer.processor.classifier import ClassificationResult, ImageType
from cataloguer.processor.pipeline import ImageFile, ProcessingPipeline


@pytest.fixture
def temp_db() -> Path:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def db(temp_db: Path) -> Database:
    """Create a database instance."""
    return Database(temp_db)


@pytest.fixture
def pipeline(db: Database) -> ProcessingPipeline:
    """Create a pipeline instance."""
    return ProcessingPipeline(db)


def make_image_file(name: str = "test.jpg") -> ImageFile:
    """Create a mock ImageFile for testing."""
    return ImageFile(
        path=Path(f"/fake/{name}"),
        camera="TestCamera",
        captured_at=datetime.now(),
        file_hash=f"hash_{name}",
    )


def make_classification(
    image_type: ImageType, location_id: str | None = None
) -> ClassificationResult:
    """Create a classification result for testing."""
    return ClassificationResult(
        image_type=image_type,
        confidence=0.9,
        location_id=location_id,
    )


class TestConsecutiveBlackFrames:
    """Tests for handling multiple black frames in a row."""

    def test_first_black_frame_processed(self, pipeline: ProcessingPipeline) -> None:
        """First black frame should be processed normally."""
        image_file = make_image_file("black1.jpg")
        classification = make_classification(ImageType.BLACK_FRAME)

        result = pipeline._handle_classification(image_file, classification)

        assert result.status == "success"
        assert result.image_type == ImageType.BLACK_FRAME

    def test_second_consecutive_black_frame_skipped(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Second consecutive black frame should be skipped."""
        # Process first black frame
        image1 = make_image_file("black1.jpg")
        class1 = make_classification(ImageType.BLACK_FRAME)
        result1 = pipeline._handle_classification(image1, class1)
        assert result1.status == "success"

        # Process second black frame - should be skipped
        image2 = make_image_file("black2.jpg")
        class2 = make_classification(ImageType.BLACK_FRAME)
        result2 = pipeline._handle_classification(image2, class2)

        assert result2.status == "skipped"
        assert result2.image_type == ImageType.BLACK_FRAME

    def test_third_consecutive_black_frame_also_skipped(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Third+ consecutive black frames should also be skipped."""
        # Process multiple black frames
        for i in range(5):
            image = make_image_file(f"black{i}.jpg")
            classification = make_classification(ImageType.BLACK_FRAME)
            result = pipeline._handle_classification(image, classification)

            if i == 0:
                assert result.status == "success"
            else:
                assert result.status == "skipped"

    def test_black_frame_after_game_item_processed(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Black frame after a game item should be processed (not skipped)."""
        # Set last_image_type to GAME_ITEM (simulating we just processed a game)
        pipeline.last_image_type = ImageType.GAME_ITEM

        image = make_image_file("black.jpg")
        classification = make_classification(ImageType.BLACK_FRAME)
        result = pipeline._handle_classification(image, classification)

        assert result.status == "success"
        assert result.image_type == ImageType.BLACK_FRAME


class TestConsecutiveLocationDividers:
    """Tests for handling multiple QR code dividers in a row."""

    def test_first_location_divider_processed(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """First location divider should be processed normally."""
        image = make_image_file("qr1.jpg")
        classification = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")

        result = pipeline._handle_classification(image, classification)

        assert result.status == "success"
        assert result.image_type == ImageType.LOCATION_DIVIDER
        assert result.location_id == "BOX-1"
        assert pipeline.current_location_id == "BOX-1"

    def test_same_location_divider_skipped(self, pipeline: ProcessingPipeline) -> None:
        """Consecutive dividers with same location should be skipped."""
        # Process first divider
        image1 = make_image_file("qr1.jpg")
        class1 = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
        result1 = pipeline._handle_classification(image1, class1)
        assert result1.status == "success"

        # Process second divider with same location - should be skipped
        image2 = make_image_file("qr2.jpg")
        class2 = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
        result2 = pipeline._handle_classification(image2, class2)

        assert result2.status == "skipped"
        assert result2.image_type == ImageType.LOCATION_DIVIDER
        assert result2.location_id == "BOX-1"
        # Location should still be set
        assert pipeline.current_location_id == "BOX-1"

    def test_different_location_divider_processed(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Consecutive dividers with different locations should be processed."""
        # Process first divider
        image1 = make_image_file("qr1.jpg")
        class1 = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
        result1 = pipeline._handle_classification(image1, class1)
        assert result1.status == "success"
        assert pipeline.current_location_id == "BOX-1"

        # Process second divider with different location - should be processed
        image2 = make_image_file("qr2.jpg")
        class2 = make_classification(ImageType.LOCATION_DIVIDER, "BOX-2")
        result2 = pipeline._handle_classification(image2, class2)

        assert result2.status == "success"
        assert result2.image_type == ImageType.LOCATION_DIVIDER
        assert result2.location_id == "BOX-2"
        assert pipeline.current_location_id == "BOX-2"

    def test_multiple_same_dividers_skipped(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Multiple consecutive same-location dividers should all be skipped after first."""
        # Process multiple dividers with same location
        for i in range(5):
            image = make_image_file(f"qr{i}.jpg")
            classification = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
            result = pipeline._handle_classification(image, classification)

            if i == 0:
                assert result.status == "success"
            else:
                assert result.status == "skipped"

        # Location should still be correctly set
        assert pipeline.current_location_id == "BOX-1"

    def test_location_after_game_item_processed(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Location divider after game item should be processed."""
        # Simulate having just processed a game item
        pipeline.last_image_type = ImageType.GAME_ITEM
        pipeline.current_location_id = "BOX-1"

        # New location divider should be processed
        image = make_image_file("qr.jpg")
        classification = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
        result = pipeline._handle_classification(image, classification)

        assert result.status == "success"


class TestMixedSequences:
    """Tests for mixed sequences of dividers and items."""

    def test_black_frame_resets_for_location_divider(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """After black frame, location divider should be processed."""
        # Process black frame
        black = make_image_file("black.jpg")
        black_class = make_classification(ImageType.BLACK_FRAME)
        pipeline._handle_classification(black, black_class)

        # Location divider should be processed
        qr = make_image_file("qr.jpg")
        qr_class = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
        result = pipeline._handle_classification(qr, qr_class)

        assert result.status == "success"
        assert result.image_type == ImageType.LOCATION_DIVIDER

    def test_location_divider_resets_for_black_frame(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """After location divider, black frame should be processed."""
        # Process location divider
        qr = make_image_file("qr.jpg")
        qr_class = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
        pipeline._handle_classification(qr, qr_class)

        # Black frame should be processed
        black = make_image_file("black.jpg")
        black_class = make_classification(ImageType.BLACK_FRAME)
        result = pipeline._handle_classification(black, black_class)

        assert result.status == "success"
        assert result.image_type == ImageType.BLACK_FRAME

    def test_realistic_sequence_with_duplicates(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Test a realistic sequence: QR, QR, item, item, black, black, QR."""
        results = []

        # QR-1 (process)
        r = pipeline._handle_classification(
            make_image_file("qr1.jpg"),
            make_classification(ImageType.LOCATION_DIVIDER, "BOX-1"),
        )
        results.append(("QR-1", r.status))

        # QR-1 again (skip - same location)
        r = pipeline._handle_classification(
            make_image_file("qr2.jpg"),
            make_classification(ImageType.LOCATION_DIVIDER, "BOX-1"),
        )
        results.append(("QR-1-dup", r.status))

        # Simulate game item (mock the heavy processing)
        pipeline.last_image_type = ImageType.GAME_ITEM
        pipeline.last_location_id = None

        # Black frame (process)
        r = pipeline._handle_classification(
            make_image_file("black1.jpg"),
            make_classification(ImageType.BLACK_FRAME),
        )
        results.append(("BLACK-1", r.status))

        # Black frame again (skip)
        r = pipeline._handle_classification(
            make_image_file("black2.jpg"),
            make_classification(ImageType.BLACK_FRAME),
        )
        results.append(("BLACK-2", r.status))

        # Black frame third time (skip)
        r = pipeline._handle_classification(
            make_image_file("black3.jpg"),
            make_classification(ImageType.BLACK_FRAME),
        )
        results.append(("BLACK-3", r.status))

        # New QR-2 (process - different location)
        r = pipeline._handle_classification(
            make_image_file("qr3.jpg"),
            make_classification(ImageType.LOCATION_DIVIDER, "BOX-2"),
        )
        results.append(("QR-2", r.status))

        expected = [
            ("QR-1", "success"),
            ("QR-1-dup", "skipped"),
            ("BLACK-1", "success"),
            ("BLACK-2", "skipped"),
            ("BLACK-3", "skipped"),
            ("QR-2", "success"),
        ]
        assert results == expected


class TestStateTracking:
    """Tests for state tracking variables."""

    def test_initial_state(self, pipeline: ProcessingPipeline) -> None:
        """Initial state should have no last image type."""
        assert pipeline.last_image_type is None
        assert pipeline.last_location_id is None

    def test_black_frame_updates_state(self, pipeline: ProcessingPipeline) -> None:
        """Black frame should update last_image_type."""
        image = make_image_file("black.jpg")
        classification = make_classification(ImageType.BLACK_FRAME)
        pipeline._handle_classification(image, classification)

        assert pipeline.last_image_type == ImageType.BLACK_FRAME
        assert pipeline.last_location_id is None

    def test_location_divider_updates_state(
        self, pipeline: ProcessingPipeline
    ) -> None:
        """Location divider should update both state variables."""
        image = make_image_file("qr.jpg")
        classification = make_classification(ImageType.LOCATION_DIVIDER, "BOX-1")
        pipeline._handle_classification(image, classification)

        assert pipeline.last_image_type == ImageType.LOCATION_DIVIDER
        assert pipeline.last_location_id == "BOX-1"

    def test_skipped_frames_preserve_state(self, pipeline: ProcessingPipeline) -> None:
        """Skipped frames should preserve the state (not change it)."""
        # First black frame
        pipeline._handle_classification(
            make_image_file("black1.jpg"),
            make_classification(ImageType.BLACK_FRAME),
        )
        assert pipeline.last_image_type == ImageType.BLACK_FRAME

        # Second black frame (skipped) - state should still be BLACK_FRAME
        pipeline._handle_classification(
            make_image_file("black2.jpg"),
            make_classification(ImageType.BLACK_FRAME),
        )
        assert pipeline.last_image_type == ImageType.BLACK_FRAME
