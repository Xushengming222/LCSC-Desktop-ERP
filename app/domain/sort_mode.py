"""StorageLocationSortMode — port of domain/model/StorageLocationSortMode.kt.

A storage location's ``sortMode`` column stores a serialized sort priority
string. Values are either one of the named constants (NAME / QUANTITY /
INBOUND_TIME) or a ``SPEC:<key>`` token that sorts by a secondary spec
attribute. Multiple priorities are joined with ``|``.
"""
from __future__ import annotations


class StorageLocationSortMode:
    NONE = ""
    NAME = "NAME"
    QUANTITY = "QUANTITY"
    INBOUND_TIME = "INBOUND_TIME"
    SECONDARY_LEGACY = "SECONDARY"
    _SPEC_PREFIX = "SPEC:"
    _SEPARATOR = "|"

    @classmethod
    def by_specification(cls, specification_key: str) -> str:
        return cls._SPEC_PREFIX + specification_key.strip()

    @classmethod
    def specification_key(cls, sort_mode: str) -> str | None:
        if not sort_mode.startswith(cls._SPEC_PREFIX):
            return None
        key = sort_mode[len(cls._SPEC_PREFIX):].strip()
        return key or None

    @classmethod
    def priorities(cls, sort_mode: str) -> list[str]:
        normalized = sort_mode.strip()
        if not normalized:
            return []
        result: list[str] = []
        for token in normalized.split(cls._SEPARATOR):
            t = token.strip()
            if not t:
                continue
            if t == cls.SECONDARY_LEGACY:
                continue
            if t in (cls.NAME, cls.QUANTITY, cls.INBOUND_TIME):
                result.append(t)
            elif cls.specification_key(t) is not None:
                result.append(t)
        # distinct preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for t in result:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique

    @classmethod
    def serialize(cls, priorities: list[str]) -> str:
        seen: set[str] = set()
        unique: list[str] = []
        for p in priorities:
            t = p.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            unique.append(t)
        return cls._SEPARATOR.join(unique)
