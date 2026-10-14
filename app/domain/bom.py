"""BOM-related UI models — port of feature/search/SearchUiState.kt models.

The Android app colocates these with the SearchUiState because they are only
consumed by the search screen. We keep the same grouping here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import ComponentDetail, ExistingStockLocation, SearchInventoryRecord


class SearchMode(Enum):
    MANUAL = "Manual"
    BOM = "Bom"


class BomMatchFilter(Enum):
    ALL = "All"
    MATCHED = "Matched"
    UNMATCHED = "Unmatched"


@dataclass
class SearchResultLocationUiModel:
    code: str
    display_name: str | None
    color_hex: str | None
    quantity: int


@dataclass
class SearchResultUiModel:
    part_number: str
    mpn: str | None
    name: str | None
    brand: str | None
    package_name: str | None
    category: str | None
    description: str | None
    source_url: str | None
    specifications: dict[str, str]
    image_local_path: str | None
    total_quantity: int
    locations: list[SearchResultLocationUiModel]
    records: list[SearchInventoryRecord]
    image_url: str | None = None


@dataclass
class BomSearchEntry:
    row_number: str
    quantity: int | None = None
    comment: str | None = None
    designator: str | None = None
    footprint: str | None = None
    value: str | None = None
    manufacturer_part: str | None = None
    manufacturer: str | None = None
    supplier_part: str | None = None
    supplier: str | None = None


@dataclass
class ParsedBomDocument:
    file_name: str
    entries: list[BomSearchEntry]


@dataclass
class BomSearchRowUiModel:
    entry: BomSearchEntry
    matched_results: list[SearchResultUiModel]
    is_bound: bool = False
    is_persistent_binding: bool = False


@dataclass
class BomDirectInboundLookupResult:
    component: ComponentDetail | None = None
    existing_stock_locations: list[ExistingStockLocation] = field(default_factory=list)
    error_message: str | None = None
