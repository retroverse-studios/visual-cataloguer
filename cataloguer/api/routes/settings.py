"""Settings routes — manage app configuration from the frontend."""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from cataloguer.api.deps import DbDep

router = APIRouter()

# Settings keys that are safe to read/write from the frontend.
# Maps setting key → (env var override, default value)
KNOWN_SETTINGS: dict[str, tuple[str, str]] = {
    "ai_provider": ("", "auto"),
    "anthropic_api_key": ("ANTHROPIC_API_KEY", ""),
    "claude_model": ("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
    "ollama_host": ("OLLAMA_HOST", "http://localhost:11434"),
    "ollama_model": ("OLLAMA_MODEL", "llava"),
}

# Keys that contain secrets — return masked in GET responses
SECRET_KEYS = {"anthropic_api_key"}


class SettingsResponse(BaseModel):
    settings: dict[str, str]
    sources: dict[str, str]  # Where each value came from: "env", "db", "default"


class SettingsUpdate(BaseModel):
    settings: dict[str, str | None]  # key → value (None to delete)


@router.get("/settings")
def get_settings(db: DbDep) -> SettingsResponse:
    """Get all settings with their effective values and sources."""
    db_settings = db.get_all_settings()
    result: dict[str, str] = {}
    sources: dict[str, str] = {}

    for key, (env_var, default) in KNOWN_SETTINGS.items():
        # Priority: env var > database > default
        env_val = os.environ.get(env_var) if env_var else None

        if env_val:
            result[key] = env_val
            sources[key] = "env"
        elif key in db_settings:
            result[key] = db_settings[key]
            sources[key] = "db"
        else:
            result[key] = default
            sources[key] = "default"

        # Mask secrets
        if key in SECRET_KEYS and result[key]:
            val = result[key]
            if len(val) > 8:
                result[key] = val[:4] + "•" * (len(val) - 8) + val[-4:]
            elif val:
                result[key] = "••••••••"

    return SettingsResponse(settings=result, sources=sources)


@router.patch("/settings")
def update_settings(body: SettingsUpdate, db: DbDep) -> SettingsResponse:
    """Update settings. Only writes to database (env vars always take priority)."""
    for key, value in body.settings.items():
        if key not in KNOWN_SETTINGS:
            continue

        # Don't write if env var is set (it would be ignored anyway)
        env_var = KNOWN_SETTINGS[key][0]
        if env_var and os.environ.get(env_var):
            continue  # Silently skip — env var wins

        db.set_setting(key, value)

    return get_settings(db)


def resolve_setting(db: DbDep | None, key: str) -> str:
    """Resolve a setting value: env var > database > default.

    Use this from other routes to get the effective value of a setting.
    """
    if key not in KNOWN_SETTINGS:
        return ""

    env_var, default = KNOWN_SETTINGS[key]

    # 1. Environment variable (highest priority)
    if env_var:
        env_val = os.environ.get(env_var)
        if env_val:
            return env_val

    # 2. Database setting
    if db is not None:
        db_val = db.get_setting(key)
        if db_val is not None:
            return db_val

    # 3. Default
    return default
