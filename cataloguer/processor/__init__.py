"""Image processing pipeline components."""

from .classifier import ClassificationResult, ImageClassifier, ImageType
from .pipeline import ProcessingPipeline, process_collection

__all__ = [
    "ClassificationResult",
    "ImageClassifier",
    "ImageType",
    "ProcessingPipeline",
    "process_collection",
]
