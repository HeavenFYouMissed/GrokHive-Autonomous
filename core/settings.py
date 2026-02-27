"""
Settings Manager — Load/save user preferences to JSON.
"""
import os
import json
from config import DATA_DIR

SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

DEFAULTS = {
    # Grok API keys (up to 8 — one per agent for max rate-limit distribution)
    "api_keys": ["", "", "", "", "", "", "", ""],
    "model": "grok-4-0709",
    "tier": "medium",
    "safety_level": "confirmed",

    # Swarm behaviour
    "max_tool_rounds": 5,
    "request_timeout": 180,
    "auto_save_logs": True,

    # Window
    "window_opacity": 0.97,
    "always_on_top": False,
}


def load_settings() -> dict:
    """Load settings from JSON, filling in defaults for missing keys."""
    settings = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            settings.update(saved)
        except Exception:
            pass
    return settings


def save_settings(settings: dict):
    """Save settings dict to JSON."""
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
