"""Internationalization: loads zh/en string tables and translates keys.

Mirrors Android strings.xml placeholders (%1$s, %2$d, ...).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QObject, Signal

_LANG_DIR = Path(__file__).resolve().parent / "i18n"
_PLACEHOLDER_RE = re.compile(r"%(\d+)\$[sdf]")


def _load_table(lang: str) -> dict:
    path = _LANG_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Translator(QObject):
    """Holds the current language and emits ``language_changed`` on switch."""

    language_changed = Signal()

    ZH = "zh"
    EN = "en"

    def __init__(self) -> None:
        super().__init__()
        self._tables = {
            self.ZH: _load_table(self.ZH),
            self.EN: _load_table(self.EN),
        }
        self._lang = self.ZH

    @property
    def language(self) -> str:
        return self._lang

    def set_language(self, lang: str) -> None:
        if lang not in self._tables or lang == self._lang:
            return
        self._lang = lang
        self.language_changed.emit()

    def tr(self, key: str, *args) -> str:
        table = self._tables.get(self._lang, {})
        text = table.get(key)
        if text is None:
            text = self._tables[self.ZH].get(key, key)
        if not args:
            return text
        return _format(text, args)


def _format(text: str, args: tuple) -> str:
    """Replace %1$s/%2$d style placeholders with positional args."""

    def repl(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        if 0 <= index < len(args):
            return str(args[index])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(repl, text)


# Module-level singleton
_translator = Translator()


def translator() -> Translator:
    return _translator


def tr(key: str, *args) -> str:
    return _translator.tr(key, *args)
