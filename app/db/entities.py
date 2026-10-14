"""Database entities and projection dataclasses (mirror core/database/entity & model)."""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class ComponentEntity:
    id: int = 0
    part_number: str = ""
    mpn: str | None = None
    name: str | None = None
    brand: str | None = None
    package_name: str | None = None
    category: str | None = None
    spec_json: str | None = None
    description: str | None = None
    source_url: str | None = None
    image_local_path: str | None = None
    image_url: str | None = None
    updated_at: int = 0

    def __post_init__(self) -> None:
        if not self.updated_at:
            self.updated_at = int(time.time() * 1000)


@dataclass
class StorageLocationEntity:
    id: int = 0
    code: str = ""
    display_name: str | None = None
    color_hex: str | None = None
    sort_mode: str = ""
    inbound_category: str | None = None
    inbound_package_name: str | None = None
    inbound_profile_updated_at: int = 0
    remark: str | None = None
    created_at: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = int(time.time() * 1000)


@dataclass
class InventoryItemEntity:
    id: int = 0
    component_id: int = 0
    location_id: int = 0
    quantity: int = 0
    last_inbound_at: int = 0
    updated_at: int = 0

    def __post_init__(self) -> None:
        now = int(time.time() * 1000)
        if not self.last_inbound_at:
            self.last_inbound_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class InventoryTransactionEntity:
    id: int = 0
    component_id: int = 0
    location_id: int = 0
    txn_type: str = ""
    quantity_delta: int = 0
    source_type: str = ""
    source_ref: str | None = None
    raw_payload: str | None = None
    created_at: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = int(time.time() * 1000)


# ---- Projections ----


@dataclass
class DashboardSummaryProjection:
    component_count: int = 0
    location_count: int = 0
    inventory_count: int = 0
    total_quantity: int = 0
    transaction_count: int = 0


@dataclass
class StorageLocationSummaryProjection:
    id: int
    code: str
    display_name: str | None
    color_hex: str | None
    sort_mode: str
    remark: str | None
    inventory_item_count: int
    total_quantity: int


@dataclass
class LocationInventoryProjection:
    inventory_item_id: int
    component_id: int
    part_number: str
    mpn: str | None
    name: str | None
    brand: str | None
    package_name: str | None
    category: str | None
    description: str | None
    source_url: str | None
    spec_json: str | None
    image_local_path: str | None
    image_url: str | None
    quantity: int
    last_inbound_at: int


@dataclass
class SearchInventoryProjection:
    inventory_item_id: int
    component_id: int
    part_number: str
    mpn: str | None
    name: str | None
    brand: str | None
    package_name: str | None
    category: str | None
    description: str | None
    source_url: str | None
    spec_json: str | None
    image_local_path: str | None
    image_url: str | None
    quantity: int
    location_id: int
    location_code: str
    location_display_name: str | None
    location_color_hex: str | None


@dataclass
class ExistingStockLocationProjection:
    location_code: str
    location_display_name: str | None
    quantity: int


@dataclass
class LocationCategoryProfileProjection:
    location_id: int
    category: str | None
    package_name: str | None
    quantity: int
