"""Deployment-side version permissions, applied to the native protocol field."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import SUPPORTED_PROTOCOL, TARGET_APP_VERSION

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "versions.json"


@dataclass(frozen=True)
class VersionPolicy:
    app_version: str = TARGET_APP_VERSION
    protocol: str = SUPPORTED_PROTOCOL
    enabled: bool = True


def load_policy(path=DEFAULT_CONFIG, app_version=TARGET_APP_VERSION):
    with Path(path).open(encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict) or app_version not in config:
        raise ValueError(f"No permission configured for app version {app_version}.")
    entry = config[app_version]
    if not isinstance(entry, dict) or type(entry.get("enabled")) is not bool:
        raise ValueError("Version enabled must be a JSON boolean.")
    protocol = entry.get("gameServerProtocolVersion")
    if not isinstance(protocol, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", protocol):
        raise ValueError("gameServerProtocolVersion must contain three numeric components.")
    return VersionPolicy(app_version, protocol, entry["enabled"])
