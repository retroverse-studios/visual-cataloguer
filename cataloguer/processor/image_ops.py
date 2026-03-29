"""Image operations: auto-crop, auto-rotate, manual crop/rotate.

All functions operate on BGR numpy arrays (OpenCV convention).
"""

import io

import cv2
import numpy as np
from PIL import Image


def auto_crop(image: np.ndarray, padding_pct: float = 0.02) -> np.ndarray:
    """Crop tight around the item, removing plain background.

    Uses Otsu thresholding to separate foreground from a white/plain background,
    then finds the bounding rectangle of the foreground region.

    Returns the original image unchanged if the detected region already fills
    more than 90% of the frame (nothing meaningful to crop).
    """
    h, w = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)

    # Otsu threshold to separate foreground from background
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # If background is dark (unusual), the inversion above is wrong — check mean
    # of original grayscale; if background is bright (>160), our BINARY_INV is correct
    border_mean = np.mean([
        gray[:10, :].mean(),       # top
        gray[-10:, :].mean(),      # bottom
        gray[:, :10].mean(),       # left
        gray[:, -10:].mean(),      # right
    ])
    if border_mean < 128:
        # Dark background — re-threshold without inversion
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Morphological close to fill small gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # Find bounding rect of all foreground pixels
    coords = cv2.findNonZero(binary)
    if coords is None:
        return image

    x, y, bw, bh = cv2.boundingRect(coords)

    # Skip if item already fills >90% of frame
    if (bw * bh) / (w * h) > 0.90:
        return image

    # Add padding
    pad_x = int(w * padding_pct)
    pad_y = int(h * padding_pct)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(w, x + bw + pad_x)
    y2 = min(h, y + bh + pad_y)

    # Don't crop if result would be tiny
    if (x2 - x1) < 50 or (y2 - y1) < 50:
        return image

    return image[y1:y2, x1:x2].copy()


def auto_rotate(image: np.ndarray) -> np.ndarray:
    """Deskew image by detecting dominant line angle.

    Only corrects small angles (up to 15 degrees). For 90-degree rotation,
    use rotate_90() manually — automatic 90-degree detection is unreliable.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                            minLineLength=100, maxLineGap=10)

    if lines is None or len(lines) < 5:
        return image

    # Compute angles of all detected lines
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Normalise to [-45, 45] range (ignore near-vertical/horizontal ambiguity)
        angle = angle % 90
        if angle > 45:
            angle -= 90
        angles.append(angle)

    # Use median angle to be robust against outliers
    median_angle = float(np.median(angles))

    # Only correct if skew is noticeable but not extreme
    if abs(median_angle) < 0.5 or abs(median_angle) > 15:
        return image

    h, w = image.shape[:2]
    center = (w / 2, h / 2)
    matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)

    # Calculate new bounding dimensions
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)

    matrix[0, 2] += (new_w - w) / 2
    matrix[1, 2] += (new_h - h) / 2

    # Use white border fill (matches typical photography background)
    rotated: np.ndarray = cv2.warpAffine(image, matrix, (new_w, new_h),
                                         borderMode=cv2.BORDER_CONSTANT,
                                         borderValue=(255, 255, 255))
    return rotated


def rotate_90(image: np.ndarray, direction: str) -> np.ndarray:
    """Rotate image 90 degrees clockwise or counter-clockwise.

    Args:
        direction: "cw" for clockwise, "ccw" for counter-clockwise
    """
    if direction == "cw":
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif direction == "ccw":
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        raise ValueError(f"Invalid direction: {direction!r}, must be 'cw' or 'ccw'")


def rotate_by_degrees(image: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate image by exactly 0, 90, 180, or 270 degrees clockwise.

    Returns the image unchanged if degrees is 0 or invalid.
    """
    if degrees == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif degrees == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    elif degrees == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def manual_crop(image: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Crop image to the specified rectangle.

    Coordinates are clamped to image bounds.
    """
    img_h, img_w = image.shape[:2]
    x1 = max(0, min(x, img_w - 1))
    y1 = max(0, min(y, img_h - 1))
    x2 = max(1, min(x + w, img_w))
    y2 = max(1, min(y + h, img_h))
    return image[y1:y2, x1:x2].copy()


def create_thumbnail(image: np.ndarray, max_dim: int = 400) -> np.ndarray:
    """Create a thumbnail, resizing so largest dimension is max_dim."""
    h, w = image.shape[:2]
    if max(h, w) <= max_dim:
        return image.copy()
    scale = max_dim / max(h, w)
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def decode_jpeg(data: bytes) -> np.ndarray:
    """Decode JPEG bytes to BGR numpy array."""
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Failed to decode JPEG data")
    return image


def encode_jpeg(image: np.ndarray, quality: int = 85) -> bytes:
    """Encode BGR numpy array to JPEG bytes."""
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)
    buffer = io.BytesIO()
    pil_image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()
