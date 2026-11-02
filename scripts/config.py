#!/usr/bin/env python3
"""MelodyMine configuration management.

Centralizes all configurable settings with environment variable overrides.
Configuration precedence (highest to lowest):
1. CLI arguments
2. Environment variables
3. Default values

Environment variables:
- MELODYMINE_PLEX_HOST: Plex server hostname (required for upload)
- MELODYMINE_PLEX_PORT: Plex server SSH port (default: 22)
- MELODYMINE_PLEX_USER: Plex server SSH user (default: current user)
- MELODYMINE_PLEX_KEY: SSH private key path (default: ~/.ssh/id_rsa)
- MELODYMINE_PLEX_DIR: Plex music directory (required for upload)
- MELODYMINE_OUTPUT: Default output directory (default: ~/Music/MelodyMine)
"""

import os
from pathlib import Path


def _get_env_int(name: str, default: int) -> int:
    """Get an integer from environment variable with default."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# ─── Plex Configuration ──────────────────────────────────────────────────

PLEX_HOST = os.environ.get("MELODYMINE_PLEX_HOST", "")
PLEX_PORT = _get_env_int("MELODYMINE_PLEX_PORT", 22)
PLEX_USER = os.environ.get("MELODYMINE_PLEX_USER", os.environ.get("USER", "user"))
PLEX_KEY = os.environ.get("MELODYMINE_PLEX_KEY", "~/.ssh/id_rsa")
PLEX_DIR = os.environ.get("MELODYMINE_PLEX_DIR", "")


# ─── Output Configuration ────────────────────────────────────────────────

def get_default_output() -> str:
    """Get default output directory from environment or home directory."""
    env_output = os.environ.get("MELODYMINE_OUTPUT")
    if env_output:
        return env_output
    
    # Default to ~/Music/MelodyMine
    home = Path.home()
    return str(home / "Music" / "MelodyMine")


DEFAULT_OUTPUT = get_default_output()


# ─── Proxy Configuration ─────────────────────────────────────────────────

# Common proxy ports to probe (Clash, Shadowsocks, etc.)
PROXY_PORTS = [7897, 7890, 1080, 2080, 8118]


# ─── Download Configuration ──────────────────────────────────────────────

# Default concurrent downloads for batch operations
DEFAULT_CONCURRENT = int(os.environ.get("MELODYMINE_CONCURRENT", "4"))

# Default audio format
DEFAULT_FORMAT = os.environ.get("MELODYMINE_FORMAT", "mp3")

# Default audio bitrate
DEFAULT_BITRATE = os.environ.get("MELODYMINE_BITRATE", "320K")
