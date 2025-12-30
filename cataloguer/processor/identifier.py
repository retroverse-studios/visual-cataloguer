"""LLM-based item identification for the visual cataloguer.

Uses vision LLMs (Claude, Ollama) to identify items from images when OCR
fails or for better accuracy. Extracts structured data about games,
consoles, controllers, books, vinyl, and other collectibles.
"""

import base64
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

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
            "text": IDENTIFICATION_PROMPT,
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

        # Extract JSON from response - first text block
        response_text = ""
        for block in message.content:
            if hasattr(block, "text"):
                response_text = block.text
                break
        return self._parse_response(response_text)

    def _identify_ollama(self, base64_image: str) -> IdentificationResult:
        """Use Ollama API for identification."""
        response = httpx.post(
            f"{self.ollama_host}/api/generate",
            json={
                "model": self.model,
                "prompt": IDENTIFICATION_PROMPT,
                "images": [base64_image],
                "stream": False,
            },
            timeout=120.0,  # Vision models can be slow
        )
        response.raise_for_status()

        result = response.json()
        response_text = result.get("response", "")
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
