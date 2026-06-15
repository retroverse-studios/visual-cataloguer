"""Tests for the identifier module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from cataloguer.processor.identifier import (
    IDENTIFICATION_PROMPT,
    UNIFIED_PROMPT,
    IdentificationResult,
    ItemIdentifier,
    ItemType,
    UnifiedResult,
    check_claude_available,
    check_ollama_available,
    detect_provider,
)


class TestItemType:
    """Tests for ItemType enum."""

    def test_item_type_values(self) -> None:
        """Test that all expected item types exist."""
        assert ItemType.GAME.value == "game"
        assert ItemType.CONSOLE.value == "console"
        assert ItemType.CONTROLLER.value == "controller"
        assert ItemType.ACCESSORY.value == "accessory"
        assert ItemType.PERIPHERAL.value == "peripheral"
        assert ItemType.BOOK.value == "book"
        assert ItemType.VINYL.value == "vinyl"
        assert ItemType.CD.value == "cd"
        assert ItemType.TRADING_CARD.value == "trading_card"
        assert ItemType.OTHER.value == "other"


class TestItemIdentifier:
    """Tests for ItemIdentifier class."""

    def test_init_claude_without_api_key_raises(self) -> None:
        """Test that Claude provider without API key raises ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY if it exists
            with patch("os.environ.get", return_value=None):
                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                    ItemIdentifier(provider="claude")

    def test_init_claude_with_env_api_key(self) -> None:
        """Test that Claude provider reads API key from environment."""
        # clear=True so CLAUDE_MODEL isn't inherited from the real environment,
        # letting the default model apply.
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-api-key"}, clear=True):
            identifier = ItemIdentifier(provider="claude")
            assert identifier.api_key == "test-api-key"
            assert identifier.model == "claude-haiku-4-5-20251001"

    def test_init_claude_with_explicit_api_key(self) -> None:
        """Test that explicit API key overrides environment."""
        identifier = ItemIdentifier(provider="claude", api_key="explicit-key")
        assert identifier.api_key == "explicit-key"

    def test_init_claude_with_custom_model(self) -> None:
        """Test custom model specification."""
        identifier = ItemIdentifier(
            provider="claude", api_key="key", model="claude-3-5-sonnet-20241022"
        )
        assert identifier.model == "claude-3-5-sonnet-20241022"

    def test_init_ollama(self) -> None:
        """Test Ollama provider initialization."""
        identifier = ItemIdentifier(provider="ollama")
        assert identifier.provider == "ollama"
        assert identifier.model == "llava"
        assert identifier.api_key is None

    def test_init_ollama_custom_model(self) -> None:
        """Test Ollama with custom model."""
        identifier = ItemIdentifier(provider="ollama", model="llava:13b")
        assert identifier.model == "llava:13b"

    def test_init_unknown_provider_raises(self) -> None:
        """Test that unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            ItemIdentifier(provider="unknown")

    def test_parse_response_valid_json(self) -> None:
        """Test parsing a valid JSON response."""
        identifier = ItemIdentifier(provider="ollama")

        response = json.dumps(
            {
                "item_type": "game",
                "title": "Super Mario Bros",
                "platform": "NES",
                "brand": "Nintendo",
                "region": "NTSC-U",
                "condition": "good",
                "completeness": "loose",
                "year": "1985",
                "description": "Classic NES game cartridge",
                "confidence": "high",
            }
        )

        result = identifier._parse_response(response)

        assert result.item_type == ItemType.GAME
        assert result.title == "Super Mario Bros"
        assert result.platform == "NES"
        assert result.brand == "Nintendo"
        assert result.region == "NTSC-U"
        assert result.condition == "good"
        assert result.completeness == "loose"
        assert result.year == "1985"
        assert result.confidence == "high"

    def test_parse_response_json_in_markdown(self) -> None:
        """Test parsing JSON wrapped in markdown code blocks."""
        identifier = ItemIdentifier(provider="ollama")

        response = """Here's the identification:
```json
{
    "item_type": "console",
    "title": "PlayStation 2",
    "platform": null,
    "brand": "Sony",
    "description": "Fat PS2 console",
    "confidence": "high"
}
```
"""
        result = identifier._parse_response(response)

        assert result.item_type == ItemType.CONSOLE
        assert result.title == "PlayStation 2"
        assert result.brand == "Sony"

    def test_parse_response_json_in_plain_code_block(self) -> None:
        """Test parsing JSON wrapped in plain code blocks."""
        identifier = ItemIdentifier(provider="ollama")

        response = """```
{"item_type": "controller", "title": "DualShock 2", "brand": "Sony", "description": "PS2 controller"}
```"""
        result = identifier._parse_response(response)

        assert result.item_type == ItemType.CONTROLLER
        assert result.title == "DualShock 2"

    def test_parse_response_invalid_json(self) -> None:
        """Test parsing invalid JSON falls back gracefully."""
        identifier = ItemIdentifier(provider="ollama")

        response = "This is not JSON at all, just a description of a game."
        result = identifier._parse_response(response)

        assert result.item_type == ItemType.OTHER
        assert result.title is None
        assert result.confidence == "low"
        assert "This is not JSON" in result.description

    def test_parse_response_unknown_item_type(self) -> None:
        """Test parsing unknown item type falls back to OTHER."""
        identifier = ItemIdentifier(provider="ollama")

        response = json.dumps(
            {"item_type": "unknown_type", "title": "Something", "description": "Test"}
        )
        result = identifier._parse_response(response)

        assert result.item_type == ItemType.OTHER


class TestIdentifyClaudeMocked:
    """Tests for Claude API identification with mocking."""

    @patch("anthropic.Anthropic")
    def test_identify_claude_success(self, mock_anthropic: MagicMock) -> None:
        """Test successful Claude API call."""
        # Setup mock
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client

        mock_text_block = MagicMock()
        mock_text_block.text = json.dumps(
            {
                "item_type": "game",
                "title": "Zelda",
                "platform": "NES",
                "brand": "Nintendo",
                "description": "Legend of Zelda cartridge",
                "confidence": "high",
            }
        )

        mock_message = MagicMock()
        mock_message.content = [mock_text_block]
        mock_client.messages.create.return_value = mock_message

        # Test
        identifier = ItemIdentifier(provider="claude", api_key="test-key")
        result = identifier._identify_claude("base64data", "image/jpeg")

        assert result.item_type == ItemType.GAME
        assert result.title == "Zelda"
        assert result.platform == "NES"


class TestIdentifyOllamaMocked:
    """Tests for Ollama API identification with mocking."""

    @patch("httpx.post")
    def test_identify_ollama_success(self, mock_post: MagicMock) -> None:
        """Test successful Ollama API call."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps(
                {
                    "item_type": "vinyl",
                    "title": "Dark Side of the Moon",
                    "brand": "Pink Floyd",
                    "description": "Classic album",
                    "confidence": "high",
                }
            )
        }
        mock_post.return_value = mock_response

        identifier = ItemIdentifier(provider="ollama")
        result = identifier._identify_ollama("base64data")

        assert result.item_type == ItemType.VINYL
        assert result.title == "Dark Side of the Moon"
        assert result.brand == "Pink Floyd"

        # Verify API call
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "api/generate" in call_kwargs[0][0]
        assert call_kwargs[1]["json"]["model"] == "llava"
        assert call_kwargs[1]["json"]["images"] == ["base64data"]


class TestIdentificationPrompt:
    """Tests for the identification prompt."""

    def test_prompt_contains_required_fields(self) -> None:
        """Test that prompt mentions all required JSON fields."""
        assert "item_type" in IDENTIFICATION_PROMPT
        assert "title" in IDENTIFICATION_PROMPT
        assert "platform" in IDENTIFICATION_PROMPT
        assert "brand" in IDENTIFICATION_PROMPT
        assert "region" in IDENTIFICATION_PROMPT
        assert "condition" in IDENTIFICATION_PROMPT
        assert "completeness" in IDENTIFICATION_PROMPT
        assert "year" in IDENTIFICATION_PROMPT
        assert "description" in IDENTIFICATION_PROMPT
        assert "confidence" in IDENTIFICATION_PROMPT

    def test_prompt_mentions_item_types(self) -> None:
        """Test that prompt mentions various item types."""
        assert "game" in IDENTIFICATION_PROMPT.lower()
        assert "console" in IDENTIFICATION_PROMPT.lower()
        assert "controller" in IDENTIFICATION_PROMPT.lower()
        assert "book" in IDENTIFICATION_PROMPT.lower()
        assert "vinyl" in IDENTIFICATION_PROMPT.lower()


class TestUnifiedResult:
    """Tests for UnifiedResult dataclass."""

    def test_unified_result_divider(self) -> None:
        """Test creating a divider result."""
        result = UnifiedResult(image_type="divider", location_id="BOX-1")
        assert result.image_type == "divider"
        assert result.location_id == "BOX-1"
        assert result.item_type is None

    def test_unified_result_black_frame(self) -> None:
        """Test creating a black frame result."""
        result = UnifiedResult(image_type="black_frame")
        assert result.image_type == "black_frame"
        assert result.location_id is None

    def test_unified_result_item(self) -> None:
        """Test creating an item result."""
        result = UnifiedResult(
            image_type="item",
            item_type=ItemType.GAME,
            title="Super Mario Bros",
            platform="NES",
            confidence="high",
        )
        assert result.image_type == "item"
        assert result.item_type == ItemType.GAME
        assert result.title == "Super Mario Bros"


class TestUnifiedPrompt:
    """Tests for the unified classification prompt."""

    def test_unified_prompt_mentions_all_types(self) -> None:
        """Test that unified prompt covers all image types."""
        assert "divider" in UNIFIED_PROMPT.lower()
        assert "black" in UNIFIED_PROMPT.lower()
        assert "item" in UNIFIED_PROMPT.lower()

    def test_unified_prompt_contains_json_format(self) -> None:
        """Test that unified prompt shows JSON format."""
        assert "image_type" in UNIFIED_PROMPT
        assert "location_id" in UNIFIED_PROMPT


class TestParseUnifiedResponse:
    """Tests for parsing unified AI responses."""

    def test_parse_divider_response(self) -> None:
        """Test parsing a divider response."""
        identifier = ItemIdentifier(provider="ollama")
        response = json.dumps({"image_type": "divider", "location_id": "SHELF-A1"})

        result = identifier._parse_unified_response(response)

        assert result.image_type == "divider"
        assert result.location_id == "SHELF-A1"

    def test_parse_divider_normalizes_location(self) -> None:
        """Test that location IDs are normalized to uppercase."""
        identifier = ItemIdentifier(provider="ollama")
        response = json.dumps({"image_type": "divider", "location_id": "box-5"})

        result = identifier._parse_unified_response(response)

        assert result.location_id == "BOX-5"

    def test_parse_black_frame_response(self) -> None:
        """Test parsing a black frame response."""
        identifier = ItemIdentifier(provider="ollama")
        response = json.dumps({"image_type": "black_frame"})

        result = identifier._parse_unified_response(response)

        assert result.image_type == "black_frame"

    def test_parse_item_response(self) -> None:
        """Test parsing an item response."""
        identifier = ItemIdentifier(provider="ollama")
        response = json.dumps(
            {
                "image_type": "item",
                "item_type": "game",
                "title": "Final Fantasy VII",
                "platform": "PlayStation",
                "brand": "Square",
                "region": "NTSC-U",
                "completeness": "complete",
                "condition_notes": "Minor scratches on disc",
                "confidence": "high",
            }
        )

        result = identifier._parse_unified_response(response)

        assert result.image_type == "item"
        assert result.item_type == ItemType.GAME
        assert result.title == "Final Fantasy VII"
        assert result.platform == "PlayStation"
        assert result.completeness == "complete"
        assert result.condition_notes == "Minor scratches on disc"

    def test_parse_item_with_markdown(self) -> None:
        """Test parsing item response wrapped in markdown."""
        identifier = ItemIdentifier(provider="ollama")
        response = """```json
{
    "image_type": "item",
    "item_type": "console",
    "title": "Nintendo 64",
    "brand": "Nintendo",
    "confidence": "high"
}
```"""

        result = identifier._parse_unified_response(response)

        assert result.image_type == "item"
        assert result.item_type == ItemType.CONSOLE
        assert result.title == "Nintendo 64"

    def test_parse_invalid_json_defaults_to_item(self) -> None:
        """Test that invalid JSON defaults to item with low confidence."""
        identifier = ItemIdentifier(provider="ollama")
        response = "This is not valid JSON"

        result = identifier._parse_unified_response(response)

        assert result.image_type == "item"
        assert result.item_type == ItemType.OTHER
        assert result.confidence == "low"

    def test_parse_unknown_item_type_defaults_to_other(self) -> None:
        """Test that unknown item types default to OTHER."""
        identifier = ItemIdentifier(provider="ollama")
        response = json.dumps(
            {"image_type": "item", "item_type": "widget", "title": "Unknown Thing"}
        )

        result = identifier._parse_unified_response(response)

        assert result.item_type == ItemType.OTHER


class TestClassifyAndIdentify:
    """Tests for classify_and_identify method."""

    @patch("httpx.post")
    def test_classify_and_identify_ollama(self, mock_post: MagicMock) -> None:
        """Test classify_and_identify with Ollama."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps(
                {
                    "image_type": "item",
                    "item_type": "game",
                    "title": "Sonic the Hedgehog",
                    "platform": "Genesis",
                    "confidence": "high",
                }
            )
        }
        mock_post.return_value = mock_response

        identifier = ItemIdentifier(provider="ollama")
        result = identifier.classify_and_identify(b"fake_image_data")

        assert result.image_type == "item"
        assert result.item_type == ItemType.GAME
        assert result.title == "Sonic the Hedgehog"

        # Verify unified prompt was used
        call_kwargs = mock_post.call_args
        assert "divider" in call_kwargs[1]["json"]["prompt"].lower()

    @patch("httpx.post")
    def test_classify_and_identify_divider(self, mock_post: MagicMock) -> None:
        """Test classify_and_identify returning a divider."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps({"image_type": "divider", "location_id": "BOX-42"})
        }
        mock_post.return_value = mock_response

        identifier = ItemIdentifier(provider="ollama")
        result = identifier.classify_and_identify(b"fake_image_data")

        assert result.image_type == "divider"
        assert result.location_id == "BOX-42"

    @patch("httpx.post")
    def test_classify_and_identify_black_frame(self, mock_post: MagicMock) -> None:
        """Test classify_and_identify returning a black frame."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps({"image_type": "black_frame"})
        }
        mock_post.return_value = mock_response

        identifier = ItemIdentifier(provider="ollama")
        result = identifier.classify_and_identify(b"fake_image_data")

        assert result.image_type == "black_frame"


class TestProviderDetection:
    """Tests for AI provider auto-detection."""

    @patch("httpx.get")
    def test_check_ollama_available_success(self, mock_get: MagicMock) -> None:
        """Test Ollama availability check when running."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        assert check_ollama_available() is True
        mock_get.assert_called_once()

    @patch("httpx.get")
    def test_check_ollama_available_not_running(self, mock_get: MagicMock) -> None:
        """Test Ollama availability check when not running."""
        import httpx

        mock_get.side_effect = httpx.ConnectError("Connection refused")

        assert check_ollama_available() is False

    @patch("httpx.get")
    def test_check_ollama_available_timeout(self, mock_get: MagicMock) -> None:
        """Test Ollama availability check on timeout."""
        import httpx

        mock_get.side_effect = httpx.TimeoutException("Timeout")

        assert check_ollama_available() is False

    def test_check_claude_available_with_key(self) -> None:
        """Test Claude availability with API key set."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            assert check_claude_available() is True

    def test_check_claude_available_without_key(self) -> None:
        """Test Claude availability without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.environ.get", return_value=None):
                assert check_claude_available() is False

    @patch("cataloguer.processor.identifier.check_ollama_available")
    @patch("cataloguer.processor.identifier.check_claude_available")
    def test_detect_provider_ollama_first(
        self, mock_claude: MagicMock, mock_ollama: MagicMock
    ) -> None:
        """Test that Ollama is preferred over Claude."""
        mock_ollama.return_value = True
        mock_claude.return_value = True

        assert detect_provider() == "ollama"

    @patch("cataloguer.processor.identifier.check_ollama_available")
    @patch("cataloguer.processor.identifier.check_claude_available")
    def test_detect_provider_claude_fallback(
        self, mock_claude: MagicMock, mock_ollama: MagicMock
    ) -> None:
        """Test Claude fallback when Ollama unavailable."""
        mock_ollama.return_value = False
        mock_claude.return_value = True

        assert detect_provider() == "claude"

    @patch("cataloguer.processor.identifier.check_ollama_available")
    @patch("cataloguer.processor.identifier.check_claude_available")
    def test_detect_provider_none_available(
        self, mock_claude: MagicMock, mock_ollama: MagicMock
    ) -> None:
        """Test None returned when no provider available."""
        mock_ollama.return_value = False
        mock_claude.return_value = False

        assert detect_provider() is None
