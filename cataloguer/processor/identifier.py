"""LLM-based item identification for the visual cataloguer.

Uses vision LLMs (Claude, Ollama) to identify items from images when OCR
fails or for better accuracy. Extracts structured data about games,
consoles, controllers, books, vinyl, and other collectibles.
"""

import base64
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import httpx


class ItemType(str, Enum):
    """Types of items that can be identified."""

    GAME = "game"
    CONSOLE = "console"
    CONTROLLER = "controller"
    ACCESSORY = "accessory"  # Memory cards, cables, etc.
    PERIPHERAL = "peripheral"  # Dance mats, guitars, etc.
    BOOK = "book"
    VINYL = "vinyl"
    CD = "cd"
    TRADING_CARD = "trading_card"
    OTHER = "other"


@dataclass
class UnifiedResult:
    """Result from AI classification and identification.

    A single result type that handles all image types:
    - divider: Location divider (QR code, paper sign, handwritten label)
    - black_frame: Dark image signaling end of location sequence
    - item: Collectible item to catalogue
    """

    image_type: Literal["divider", "black_frame", "item"]

    # For dividers
    location_id: str | None = None

    # For items
    item_type: ItemType | None = None
    title: str | None = None
    platform: str | None = None
    brand: str | None = None
    region: str | None = None
    condition: str | None = None
    completeness: str | None = None
    year: str | None = None
    condition_notes: str | None = None
    description: str | None = None
    confidence: str | None = None

    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentificationResult:
    """Result of LLM-based item identification."""

    item_type: ItemType
    title: str | None  # Game title, book title, album name, etc.
    platform: str | None  # For games/accessories: NES, PS2, etc.
    brand: str | None  # Nintendo, Sony, Sega, etc.
    region: str | None  # NTSC-U, PAL, NTSC-J, etc.
    condition: str | None  # mint, good, fair, poor
    completeness: str | None  # For games: loose, boxed, complete, sealed
    year: str | None  # Release year if identifiable
    condition_notes: str | None  # Specific notes about physical condition
    description: str  # Full description from LLM
    confidence: str | None  # high, medium, low
    raw_response: dict[str, Any]  # Full JSON response for debugging


IDENTIFICATION_PROMPT = """Analyze this image of a collectible item and provide structured information.

The item could be:
- A video game (cartridge, disc, box, manual)
- A game console or handheld
- A controller or gaming accessory
- A peripheral (dance mat, guitar controller, etc.)
- A book, vinyl record, CD, or trading card
- Other collectible

Respond with JSON in this exact format:
{
  "item_type": "game|console|controller|accessory|peripheral|book|vinyl|cd|trading_card|other",
  "title": "Name of the item (game title, album name, book title, etc.)",
  "platform": "For games/accessories: NES, SNES, PS2, Xbox, etc. Null for non-gaming items",
  "brand": "Manufacturer or publisher (Nintendo, Sony, Activision, etc.)",
  "region": "NTSC-U, NTSC-J, PAL, or null if unclear",
  "condition": "mint, good, fair, poor, or null if can't determine",
  "completeness": "For games: loose, boxed, complete, sealed. Null for other items",
  "year": "Release year if identifiable, null otherwise",
  "condition_notes": "Specific observations about physical condition: scratches, wear, tears, fading, stickers, missing parts, etc. Null if item appears pristine or condition cannot be assessed",
  "description": "Brief description of what you see and any identifying features",
  "confidence": "high, medium, or low - how confident are you in this identification"
}

Important:
- For stylized game logos, try to identify the title even if text is decorative
- Be specific in condition_notes about any visible damage, wear, or issues
- If you can identify the specific variant or edition, mention it
- For Japanese items, provide both Japanese and English names if known
- Be specific about what you can and cannot determine

Respond ONLY with the JSON object, no other text."""


UNIFIED_PROMPT = """Analyze this image and determine what type it is.

There are exactly 3 types:

1. **LOCATION DIVIDER**: A piece of paper, sign, or QR code showing a location code.
   Examples: BOX-1, SHELF-A3, GARAGE-2, ROOM1-RACK2
   These are simple labels used to organize items by storage location.

2. **BLACK FRAME**: A completely dark/black image (lens cap on, hand over lens).
   Used to signal the end of a location sequence. Very dark, nearly all black.

3. **ITEM**: A collectible item to catalogue - a game, console, controller, book, vinyl, etc.
   This is the default if the image shows an actual product or collectible.

Respond with JSON in this format:

For a LOCATION DIVIDER:
{"image_type": "divider", "location_id": "BOX-1"}

For a BLACK FRAME:
{"image_type": "black_frame"}

For an ITEM (include all identification details):
{
  "image_type": "item",
  "item_type": "game|console|controller|accessory|peripheral|book|vinyl|cd|trading_card|other",
  "title": "Name of the item",
  "platform": "NES, SNES, PS2, etc. (null for non-gaming items)",
  "brand": "Nintendo, Sony, etc.",
  "region": "NTSC-U, NTSC-J, PAL, or null",
  "condition": "mint, good, fair, poor, or null",
  "completeness": "loose, boxed, complete, sealed (for games), or null",
  "year": "Release year or null",
  "condition_notes": "Physical condition observations (scratches, wear, etc.) or null",
  "description": "Brief description of what you see",
  "confidence": "high, medium, or low"
}

Important:
- Location dividers are SIMPLE labels - just text/QR on paper. Not product boxes.
- Black frames are VERY dark - average brightness near zero.
- When in doubt, classify as "item" and identify it.
- For stylized logos, identify the title even if decorative.
- For Japanese items, provide both Japanese and English names if known.

Respond ONLY with the JSON object."""


def check_ollama_available(host: str = "http://localhost:11434") -> bool:
    """Check if Ollama is running and available."""
    try:
        response = httpx.get(f"{host}/api/tags", timeout=2.0)
        return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


def check_claude_available() -> bool:
    """Check if Claude API key is available."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def detect_provider(ollama_host: str = "http://localhost:11434") -> str | None:
    """Auto-detect the best available AI provider.

    Priority:
    1. Ollama (free, local) if running
    2. Claude if ANTHROPIC_API_KEY is set
    3. None if no provider available

    Returns:
        Provider name ("ollama" or "claude") or None
    """
    if check_ollama_available(ollama_host):
        return "ollama"
    if check_claude_available():
        return "claude"
    return None


class ItemIdentifier:
    """Identifies collectible items using vision LLMs."""

    def __init__(
        self,
        provider: str = "claude",
        model: str | None = None,
        api_key: str | None = None,
        ollama_host: str = "http://localhost:11434",
    ):
        """Initialize the identifier.

        Args:
            provider: LLM provider ("claude" or "ollama")
            model: Model name (defaults based on provider)
            api_key: API key (for Claude, reads ANTHROPIC_API_KEY if not provided)
            ollama_host: Ollama server URL (for ollama provider)
        """
        self.provider = provider
        self.ollama_host = ollama_host

        if provider == "claude":
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY environment variable not set. "
                    "Set it or pass api_key parameter."
                )
            self.model = model or "claude-3-haiku-20240307"
        elif provider == "ollama":
            self.api_key = None
            # Default to llava for vision tasks, but user can override
            self.model = model or "llava"
        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'claude' or 'ollama'.")

    def identify_file(self, file_path: Path) -> IdentificationResult:
        """Identify an item from an image file.

        Args:
            file_path: Path to the image file

        Returns:
            IdentificationResult with structured data about the item
        """
        # Read and encode image
        image_data = file_path.read_bytes()
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")

        # Determine media type
        suffix = file_path.suffix.lower()
        media_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = media_type_map.get(suffix, "image/jpeg")

        if self.provider == "claude":
            return self._identify_claude(base64_image, media_type)
        else:
            return self._identify_ollama(base64_image)

    def identify_bytes(
        self, image_data: bytes, media_type: str = "image/jpeg"
    ) -> IdentificationResult:
        """Identify an item from image bytes.

        Args:
            image_data: Raw image bytes
            media_type: MIME type of the image

        Returns:
            IdentificationResult with structured data about the item
        """
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")

        if self.provider == "claude":
            return self._identify_claude(base64_image, media_type)
        else:
            return self._identify_ollama(base64_image)

    def _identify_claude(
        self, base64_image: str, media_type: str
    ) -> IdentificationResult:
        """Use Claude API for identification."""
        response_text = self._query_claude(base64_image, media_type, IDENTIFICATION_PROMPT)
        return self._parse_response(response_text)

    def _identify_ollama(self, base64_image: str) -> IdentificationResult:
        """Use Ollama API for identification."""
        response_text = self._query_ollama(base64_image, IDENTIFICATION_PROMPT)
        return self._parse_response(response_text)

    def _parse_response(self, response_text: str) -> IdentificationResult:
        """Parse LLM response into IdentificationResult."""
        # Try to extract JSON from response
        try:
            # Handle case where LLM wraps JSON in markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()

            data = json.loads(response_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, return a basic result with the raw text
            return IdentificationResult(
                item_type=ItemType.OTHER,
                title=None,
                platform=None,
                brand=None,
                region=None,
                condition=None,
                completeness=None,
                year=None,
                condition_notes=None,
                description=response_text,
                confidence="low",
                raw_response={"error": "Failed to parse JSON", "raw": response_text},
            )

        # Map item_type string to enum
        item_type_str = data.get("item_type", "other").lower()
        try:
            item_type = ItemType(item_type_str)
        except ValueError:
            item_type = ItemType.OTHER

        return IdentificationResult(
            item_type=item_type,
            title=data.get("title"),
            platform=data.get("platform"),
            brand=data.get("brand"),
            region=data.get("region"),
            condition=data.get("condition"),
            completeness=data.get("completeness"),
            year=data.get("year"),
            condition_notes=data.get("condition_notes"),
            description=data.get("description", ""),
            confidence=data.get("confidence"),
            raw_response=data,
        )

    def identify_divider(
        self, image_data: bytes, media_type: str = "image/jpeg"
    ) -> tuple[bool, str | None]:
        """Check if an image is a location divider and extract the location ID.

        Used for text-based dividers (white paper with handwritten/printed location).

        Args:
            image_data: Raw image bytes
            media_type: MIME type of the image

        Returns:
            Tuple of (is_divider, location_id)
            - (True, "BOX-1") if it's a divider
            - (False, None) if it's not a divider
        """
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")

        prompt = """Look at this image. Is it a location divider (a piece of paper or sign with a location code written on it)?

Location dividers are simple labels like:
- BOX-1, BOX-2, BOX-10
- SHELF-A1, SHELF-B3
- GARAGE-1, ROOM-2
- Any text in format: WORD-NUMBER or WORD-LETTER-NUMBER

If this IS a location divider, respond with JSON:
{"is_divider": true, "location_id": "BOX-1"}

If this is NOT a location divider (it's a game, book, product, or other item to catalog), respond with:
{"is_divider": false, "location_id": null}

Respond ONLY with the JSON object."""

        if self.provider == "claude":
            result = self._query_claude(base64_image, media_type, prompt)
        else:
            result = self._query_ollama(base64_image, prompt)

        # Parse response
        try:
            if "```json" in result:
                start = result.find("```json") + 7
                end = result.find("```", start)
                result = result[start:end].strip()
            elif "```" in result:
                start = result.find("```") + 3
                end = result.find("```", start)
                result = result[start:end].strip()

            data = json.loads(result)
            is_divider = data.get("is_divider", False)
            location_id = data.get("location_id")

            if is_divider and location_id:
                # Normalize location ID format
                location_id = location_id.upper().strip()
                return (True, location_id)
            return (False, None)
        except (json.JSONDecodeError, KeyError):
            return (False, None)

    def _query_claude(
        self, base64_image: str, media_type: str, prompt: str
    ) -> str:
        """Query Claude API with an image and prompt."""
        import anthropic
        from anthropic.types import ImageBlockParam, TextBlockParam

        client = anthropic.Anthropic(api_key=self.api_key)

        image_block: ImageBlockParam = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,  # type: ignore[typeddict-item]
                "data": base64_image,
            },
        }
        text_block: TextBlockParam = {
            "type": "text",
            "text": prompt,
        }

        message = client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [image_block, text_block],
                }
            ],
        )

        response_text = ""
        for block in message.content:
            if hasattr(block, "text"):
                response_text = block.text
                break
        return response_text

    def _query_ollama(self, base64_image: str, prompt: str) -> str:
        """Query Ollama API with an image and prompt."""
        response = httpx.post(
            f"{self.ollama_host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("response", "")

    def classify_and_identify(
        self, image_data: bytes, media_type: str = "image/jpeg"
    ) -> UnifiedResult:
        """Classify an image and identify its contents in a single AI call.

        This is the main entry point for AI-first processing. It determines
        whether the image is a divider, black frame, or item, and returns
        full identification details for items.

        Args:
            image_data: Raw image bytes
            media_type: MIME type of the image

        Returns:
            UnifiedResult with image type and relevant details
        """
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")

        if self.provider == "claude":
            response_text = self._query_claude(base64_image, media_type, UNIFIED_PROMPT)
        else:
            response_text = self._query_ollama(base64_image, UNIFIED_PROMPT)

        return self._parse_unified_response(response_text)

    def _parse_unified_response(self, response_text: str) -> UnifiedResult:
        """Parse the unified AI response into a UnifiedResult."""
        # Extract JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()

            data = json.loads(response_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, assume it's an item with low confidence
            return UnifiedResult(
                image_type="item",
                item_type=ItemType.OTHER,
                description=response_text,
                confidence="low",
                raw_response={"error": "Failed to parse JSON", "raw": response_text},
            )

        image_type = data.get("image_type", "item")

        if image_type == "divider":
            location_id = data.get("location_id")
            if location_id:
                location_id = location_id.upper().strip()
            return UnifiedResult(
                image_type="divider",
                location_id=location_id,
                raw_response=data,
            )

        if image_type == "black_frame":
            return UnifiedResult(
                image_type="black_frame",
                raw_response=data,
            )

        # Default: item
        item_type_str = data.get("item_type", "other")
        try:
            item_type = ItemType(item_type_str.lower() if item_type_str else "other")
        except ValueError:
            item_type = ItemType.OTHER

        return UnifiedResult(
            image_type="item",
            item_type=item_type,
            title=data.get("title"),
            platform=data.get("platform"),
            brand=data.get("brand"),
            region=data.get("region"),
            condition=data.get("condition"),
            completeness=data.get("completeness"),
            year=data.get("year"),
            condition_notes=data.get("condition_notes"),
            description=data.get("description"),
            confidence=data.get("confidence"),
            raw_response=data,
        )
