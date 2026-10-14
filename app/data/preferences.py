"""User preferences — port of core/datastore/UserPreferencesRepository.kt.

The Android app uses Jetpack DataStore (protobuf-backed). Here we use a simple
JSON file with the same key schema. The repository is a QObject so it can emit
``preferences_changed`` to which view models subscribe (the Kotlin code uses a
``Flow<UserPreferences>``).
"""
from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LANGUAGE_ZH = "zh"
LANGUAGE_EN = "en"

PRINTER_TYPE_AUTO = "auto"
PRINTER_TYPE_DELI_Q5 = "deli_q5"

PRESET_LOCATION_COLORS = ["#C8E6C9", "#B3E5FC", "#F8BBD0", "#D1C4E9", "#FFE0B2"]

_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$")


@dataclass
class UserPreferences:
    default_location_code: str | None = None
    app_language_tag: str = LANGUAGE_ZH
    recent_manual_searches: list[str] = field(default_factory=list)
    bom_part_bindings: dict[str, str] = field(default_factory=dict)
    recent_location_colors: list[str] = field(default_factory=lambda: list(PRESET_LOCATION_COLORS))
    printer_type: str = PRINTER_TYPE_AUTO


def _normalize_color(color_hex: str) -> str | None:
    normalized = color_hex.strip().upper()
    return normalized if _COLOR_RE.match(normalized) else None


def _parse_recent_manual_searches(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split("\n") if p.strip()]


def _parse_bom_part_bindings(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    result: dict[str, str] = {}
    for line in value.split("\n"):
        parts = line.split("\t", 1)
        key = parts[0].strip() if len(parts) > 0 else ""
        val = parts[1].strip() if len(parts) > 1 else ""
        if key and val:
            result[key] = val
    return result


def _parse_recent_location_colors(value: str | None, use_preset_fallback: bool = False) -> list[str]:
    if not value:
        return list(PRESET_LOCATION_COLORS) if use_preset_fallback else []
    parsed: list[str] = []
    seen: set[str] = set()
    for raw in value.split("\n"):
        normalized = _normalize_color(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            parsed.append(normalized)
        if len(parsed) >= 5:
            break
    if not parsed and use_preset_fallback:
        return list(PRESET_LOCATION_COLORS)
    return parsed


def _serialize_bom_part_bindings(bindings: dict[str, str]) -> str:
    return "\n".join(f"{k}\t{v}" for k, v in sorted(bindings.items()))


def _default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "LCSC_ERP"
    return Path.home() / ".lcsc_erp"


def _resolve_data_dir_from_config(config_ini_path: Path) -> Path:
    override = os.environ.get("LCSC_ERP_DATA_DIR")
    if override:
        return Path(override)
    if config_ini_path.exists():
        try:
            config = configparser.ConfigParser()
            config.read(config_ini_path, encoding="utf-8")
            if config.has_section("data") and config.has_option("data", "dir"):
                candidate = config.get("data", "dir").strip()
                if candidate:
                    return Path(candidate)
        except Exception:
            pass
    return _default_data_dir()


class UserPreferencesRepository(QObject):
    """JSON-backed preferences store with the same semantics as the DataStore version."""

    preferences_changed = Signal()

    def __init__(self, file_path: str | Path, config_ini_path: str | Path | None = None) -> None:
        super().__init__()
        self._path = Path(file_path)
        self._config_ini_path = Path(config_ini_path) if config_ini_path else None
        self._lock = threading.Lock()
        self._data: dict[str, str | None] = {}
        self._load()

    # ---- snapshot ----
    @property
    def preferences(self) -> UserPreferences:
        with self._lock:
            return self._build_preferences()

    def _build_preferences(self) -> UserPreferences:
        lang = self._data.get("app_language_tag") or LANGUAGE_ZH
        printer_raw = self._data.get("printer_type")
        printer = (
            printer_raw
            if printer_raw in (PRINTER_TYPE_AUTO, PRINTER_TYPE_DELI_Q5)
            else PRINTER_TYPE_AUTO
        )
        return UserPreferences(
            default_location_code=self._data.get("default_location_code"),
            app_language_tag=lang,
            recent_manual_searches=_parse_recent_manual_searches(
                self._data.get("recent_manual_searches")
            ),
            bom_part_bindings=_parse_bom_part_bindings(self._data.get("bom_part_bindings")),
            recent_location_colors=_parse_recent_location_colors(
                self._data.get("recent_location_colors"), use_preset_fallback=True
            ),
            printer_type=printer,
        )

    # ---- mutations ----
    def set_default_location(self, code: str | None) -> None:
        with self._lock:
            if not code or not code.strip():
                self._data.pop("default_location_code", None)
            else:
                self._data["default_location_code"] = code
            self._save()
        self.preferences_changed.emit()

    def set_app_language(self, language_tag: str) -> None:
        with self._lock:
            self._data["app_language_tag"] = language_tag
            self._save()
        self.preferences_changed.emit()

    def add_recent_manual_search(self, keyword: str) -> None:
        normalized = keyword.strip()
        if not normalized:
            return
        with self._lock:
            current = _parse_recent_manual_searches(self._data.get("recent_manual_searches"))
            updated = [normalized]
            for item in current:
                if item.lower() != normalized.lower():
                    updated.append(item)
            updated = updated[:5]
            self._data["recent_manual_searches"] = "\n".join(updated)
            self._save()
        self.preferences_changed.emit()

    def set_bom_part_binding(self, supplier_part: str, local_part_number: str) -> None:
        norm_supplier = supplier_part.strip().upper()
        norm_local = local_part_number.strip().upper()
        if not norm_supplier or not norm_local:
            return
        with self._lock:
            bindings = _parse_bom_part_bindings(self._data.get("bom_part_bindings"))
            bindings[norm_supplier] = norm_local
            self._data["bom_part_bindings"] = _serialize_bom_part_bindings(bindings)
            self._save()
        self.preferences_changed.emit()

    def set_printer_type(self, printer_type: str) -> None:
        normalized = PRINTER_TYPE_DELI_Q5 if printer_type.strip().lower() == PRINTER_TYPE_DELI_Q5 else PRINTER_TYPE_AUTO
        with self._lock:
            self._data["printer_type"] = normalized
            self._save()
        self.preferences_changed.emit()

    def add_recent_location_color(self, color_hex: str) -> None:
        normalized = _normalize_color(color_hex)
        if not normalized:
            return
        with self._lock:
            current = _parse_recent_location_colors(
                self._data.get("recent_location_colors"), use_preset_fallback=True
            )
            updated = [normalized]
            for item in current:
                if item.lower() != normalized.lower():
                    updated.append(item)
            updated = updated[:5]
            self._data["recent_location_colors"] = "\n".join(updated)
            self._save()
        self.preferences_changed.emit()

    def set_recent_location_colors(self, colors: list[str]) -> None:
        normalized: list[str] = []
        seen: set[str] = set()
        for c in colors:
            n = _normalize_color(c)
            if n and n not in seen:
                seen.add(n)
                normalized.append(n)
            if len(normalized) >= 5:
                break
        with self._lock:
            if not normalized:
                self._data.pop("recent_location_colors", None)
            else:
                self._data["recent_location_colors"] = "\n".join(normalized)
            self._save()
        self.preferences_changed.emit()

    # ---- data dir management ----
    @property
    def current_data_dir(self) -> Path:
        if self._config_ini_path:
            return _resolve_data_dir_from_config(self._config_ini_path)
        return _default_data_dir()

    @property
    def default_data_dir(self) -> Path:
        return _default_data_dir()

    @property
    def has_custom_data_dir(self) -> bool:
        if not self._config_ini_path or not self._config_ini_path.exists():
            return False
        try:
            config = configparser.ConfigParser()
            config.read(self._config_ini_path, encoding="utf-8")
            if config.has_section("data") and config.has_option("data", "dir"):
                candidate = config.get("data", "dir").strip()
                if candidate:
                    return True
        except Exception:
            pass
        return False

    def set_custom_data_dir(self, new_path: str | Path) -> None:
        """Write a custom data directory to config.ini in the project root.

        The change takes effect on the next app restart.
        """
        if not self._config_ini_path:
            return
        new_path = Path(new_path)
        new_path.mkdir(parents=True, exist_ok=True)
        config = configparser.ConfigParser()
        config["data"] = {"dir": str(new_path)}
        self._config_ini_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_ini_path, "w", encoding="utf-8") as fh:
            config.write(fh)

    def reset_data_dir(self) -> None:
        """Remove the custom data directory config, reverting to default."""
        if not self._config_ini_path or not self._config_ini_path.exists():
            return
        try:
            self._config_ini_path.unlink()
        except OSError:
            pass

    def copy_data_to(self, target_path: str | Path) -> int:
        """Copy current data (db, images, preferences) to a new directory.

        Returns the number of files copied.
        """
        target = Path(target_path)
        target.mkdir(parents=True, exist_ok=True)
        source_dir = self.current_data_dir
        count = 0
        for item in source_dir.iterdir():
            dest = target / item.name
            if item.is_file():
                shutil.copy2(item, dest)
                count += 1
            elif item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
                count += 1
        return count

    # ---- persistence ----
    def _load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._data = {}
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = {k: (v if isinstance(v, str) else (str(v) if v is not None else None)) for k, v in raw.items()}
                else:
                    self._data = {}
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        # caller holds self._lock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {k: v for k, v in self._data.items() if v is not None}
        self._path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
