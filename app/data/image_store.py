"""Component image store — port of data/repository/ComponentImageStore.kt.

Downloads component preview images and persists them to a local directory
keyed by part number. The Android version uses OkHttp; here we use ``requests``.
"""
from __future__ import annotations

import re
from pathlib import Path

import requests


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


class ComponentImageStore:
    def __init__(self, image_dir: str | Path, timeout: float = 15.0) -> None:
        self._dir = Path(image_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._session = requests.Session()

    @property
    def image_dir(self) -> Path:
        return self._dir

    def persist_image(self, part_number: str, image_url: str | None) -> str | None:
        normalized_url = (image_url or "").strip()
        if not normalized_url:
            return None
        target = self._dir / self._build_file_name(part_number, normalized_url)
        if target.exists() and target.stat().st_size > 0:
            return str(target)
        try:
            response = self._session.get(normalized_url, timeout=self._timeout)
            if response.status_code != 200:
                return None
            target.write_bytes(response.content)
        except requests.RequestException:
            return None
        if target.exists() and target.stat().st_size > 0:
            return str(target)
        return None

    def persist_image_bytes(
        self, part_number: str, source_name: str | None, bytes_data: bytes
    ) -> str | None:
        if not bytes_data:
            return None
        name = source_name or f"{part_number}.jpg"
        target = self._dir / self._build_file_name(part_number, name)
        try:
            target.write_bytes(bytes_data)
        except OSError:
            return None
        if target.exists() and target.stat().st_size > 0:
            return str(target)
        return None

    @staticmethod
    def _build_file_name(part_number: str, image_url: str) -> str:
        safe_part = _SAFE_NAME_RE.sub("_", part_number)
        without_query = image_url.split("?", 1)[0]
        ext = "jpg"
        if "." in without_query:
            candidate = without_query.rsplit(".", 1)[1].lower()
            if 2 <= len(candidate) <= 5:
                ext = candidate
        return f"{safe_part}.{ext}"
