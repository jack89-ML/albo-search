"""Configuration: bundled defaults + XDG user override, merged at runtime.

Precedence (first match wins per top-level key):
1. explicit path passed with ``--sources``
2. ``$ALBO_SEARCH_CONFIG`` (user-set config path)
3. ``$ALBO_SOURCES`` (legacy alias of the above)
4. ``$XDG_CONFIG_HOME/albo-search/sources.json`` or
   ``~/.config/albo-search/sources.json`` (XDG Base Directory)
5. the ``sources.json`` packaged inside the module

User overrides are merged over the bundled defaults (bar-council lists are
merged per platform: same-name entries are replaced, new ones appended), so
a local file may add or replace individual bar councils without touching the
installed package.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .errors import RegistryError

PACKAGED = Path(__file__).parent / "data" / "sources.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read sources file {path}: {exc}") from exc


def default_sources() -> dict:
    return _load(PACKAGED)


def xdg_config_path() -> Path | None:
    """User config location per the XDG Base Directory specification."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    candidate = root / "albo-search" / "sources.json"
    return candidate if candidate.is_file() else None


def _override_paths(explicit: str | None) -> list[Path]:
    """Candidate override paths in order of precedence.

    An explicitly requested path that does not exist is a hard error, never
    a silent fallback to another configuration source.
    """
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise RegistryError(f"sources file not found: {explicit}")
        return [path]
    paths: list[Path] = []
    for raw in (os.environ.get("ALBO_SEARCH_CONFIG"),
                os.environ.get("ALBO_SOURCES")):
        if raw:
            paths.append(Path(raw).expanduser().resolve())
    xdg = xdg_config_path()
    if xdg:
        paths.append(xdg)
    return paths


def _merge_lawyers(base: list, overlay: list) -> list:
    """Merge two platform lists (e.g. sferabit bars).

    Entries with the same ``name`` are replaced by the overlay entry;
    new names are appended. Bundled entries therefore survive overrides
    that only add or replace a single bar council.
    """
    merged = list(base)
    for item in overlay:
        name = str(item.get("name", "")).upper()
        for index, existing in enumerate(merged):
            if str(existing.get("name", "")).upper() == name:
                merged[index] = item
                break
        else:
            merged.append(item)
    return merged


def _deep_merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if key == "lawyers" and isinstance(value, dict):
            lawyers = dict(result.get("lawyers", {}))
            for platform in ("sferabit", "iscrivo"):
                if platform in value and isinstance(value[platform], list):
                    lawyers[platform] = _merge_lawyers(
                        list(lawyers.get(platform, [])), value[platform])
            result["lawyers"] = lawyers
        else:
            result[key] = value
    return result


def resolve_sources(override: str | None = None) -> dict:
    """Bundled defaults merged with the first existing user override."""
    cfg = default_sources()
    for path in _override_paths(override):
        if not path.is_file():
            continue
        local = _load(path)
        cfg = _deep_merge(cfg, local)
        break  # first existing override wins
    return cfg


def _lawyer_names(cfg: dict) -> list[str]:
    names = [str(item.get("name", "?")).upper()
             for item in cfg.get("lawyers", {}).get("sferabit", [])]
    names += [str(item.get("name", "?")).upper()
              for item in cfg.get("lawyers", {}).get("iscrivo", [])]
    return names


def find_lawyer_bar(cfg: dict, name: str) -> tuple[str, dict]:
    """Resolve a bar-council name to its platform adapter.

    Returns ``("sferabit", item)`` or ``("iscrivo", item)``; raises
    :class:`RegistryError` when the name is not configured on either
    platform. Callers dispatch on the returned platform string, so a
    failure inside one adapter can never be masked as a lookup of the
    other.
    """
    target = name.upper()
    for platform in ("sferabit", "iscrivo"):
        for item in cfg.get("lawyers", {}).get(platform, []):
            if str(item.get("name", "")).upper() == target:
                return platform, item
    available = ", ".join(_lawyer_names(cfg)) or "none"
    raise RegistryError(f"unknown bar '{name}'. Available: {available}")
