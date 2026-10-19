"""Loads the Owner's Spotify credentials and Authorization date.

The only source is secrets.json next to this file (gitignored). Environment
variable support can be added later behind load_config() without touching callers.
"""
import datetime
import json
from collections import namedtuple
from pathlib import Path

SECRETS_PATH = Path(__file__).resolve().parent / "secrets.json"

Config = namedtuple("Config", ["client_id", "client_secret", "refresh_token", "authorized_at"])


class ConfigError(Exception):
    """secrets.json is missing, unreadable, or incomplete."""


def load_config():
    try:
        raw = json.loads(SECRETS_PATH.read_text())
    except (OSError, ValueError) as e:
        raise ConfigError("cannot read {}: {}".format(SECRETS_PATH.name, e))
    if not isinstance(raw, dict):
        raise ConfigError("{} must contain a JSON object".format(SECRETS_PATH.name))

    values = {}
    for key in Config._fields:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError("missing or empty key: {}".format(key))
        values[key] = value.strip()

    try:
        values["authorized_at"] = datetime.date.fromisoformat(values["authorized_at"])
    except ValueError:
        # Also catches the template placeholder, i.e. the token script hasn't been run yet.
        raise ConfigError("authorized_at must be a YYYY-MM-DD date")

    return Config(**values)
