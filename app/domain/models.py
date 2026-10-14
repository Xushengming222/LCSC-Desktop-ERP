"""Domain models mirroring domain/model/*.kt.

These are pure data classes used by repositories and view models. They are
deliberately framework-agnostic (no Qt / no DB imports) so they can be reused
across layers.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class ComponentDetail:
    part_number: str
    mpn: str | None = None
    name: str | None = None
    brand: str | None = None
    package_name: str | None = None
    category: str | None = None
    description: str | None = None
    stock_quantity: int | None = None
    price: float | None = None
    product_url: str | None = None
    datasheet_url: str | None = None
    image_local_path: str | None = None
    image_url: str | None = None
    specifications: dict[str, str] = field(default_factory=dict)


@dataclass
class InboundRecord:
    component: ComponentDetail
    quantity: int
    location_code: str
    source_type: str
    raw_payload: str | None = None
    inbound_at: int = 0

    def __post_init__(self) -> None:
        if not self.inbound_at:
            self.inbound_at = int(time.time() * 1000)


@dataclass
class ExistingStockLocation:
    location_code: str
    location_display_name: str | None
    quantity: int


@dataclass
class StorageLocation:
    id: int
    code: str
    display_name: str | None = None
    color_hex: str | None = None
    sort_mode: str = ""
    remark: str | None = None


@dataclass
class StockLocationCell:
    id: int
    code: str
    display_name: str | None
    color_hex: str | None
    sort_mode: str
    remark: str | None
    inventory_item_count: int
    total_quantity: int


@dataclass
class LocationInventoryItem:
    inventory_item_id: int
    component_id: int
    part_number: str
    mpn: str | None
    name: str | None
    brand: str | None
    package_name: str | None
    category: str | None
    description: str | None = None
    source_url: str | None = None
    specifications: dict[str, str] = field(default_factory=dict)
    image_local_path: str | None = None
    image_url: str | None = None
    quantity: int = 0
    last_inbound_at: int = 0


@dataclass
class SearchInventoryRecord:
    inventory_item_id: int
    component_id: int
    part_number: str
    mpn: str | None
    name: str | None
    brand: str | None
    package_name: str | None
    category: str | None
    description: str | None
    source_url: str | None = None
    specifications: dict[str, str] = field(default_factory=dict)
    image_local_path: str | None = None
    image_url: str | None = None
    quantity: int = 0
    location_id: int = 0
    location_code: str = ""
    location_display_name: str | None = None
    location_color_hex: str | None = None


@dataclass
class DashboardSummary:
    component_count: int = 0
    location_count: int = 0
    inventory_count: int = 0
    total_quantity: int = 0
    transaction_count: int = 0


@dataclass
class LocationCategoryProfile:
    location_id: int
    category: str | None
    package_name: str | None
    quantity: int


@dataclass
class DominantLocationCategoryProfile:
    category: str | None = None
    package_name: str | None = None


def _dominant_profile_value(
    profiles: list[LocationCategoryProfile],
    selector,
) -> str | None:
    counts: dict[str, int] = {}
    for p in profiles:
        raw = selector(p)
        if not raw:
            continue
        value = raw.strip()
        if not value:
            continue
        value = value.upper()
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    # sort by count desc, then key asc — matches Kotlin compareByDescending<{value}>().thenBy{key}
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def calculate_dominant_location_category_profile(
    profiles: list[LocationCategoryProfile],
) -> DominantLocationCategoryProfile:
    return DominantLocationCategoryProfile(
        category=_dominant_profile_value(profiles, lambda p: p.category),
        package_name=_dominant_profile_value(profiles, lambda p: p.package_name),
    )
