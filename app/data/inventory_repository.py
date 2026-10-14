"""Inventory repository — port of data/repository/InventoryRepositoryImpl.kt.

Wraps the five DAOs with business logic (inbound upsert, transfers, location
category profile refresh, manual-inbound part-number sequencing). The Android
``Flow``-based observers become a ``changed`` Signal: view models re-query
snapshots via the ``observe_*`` methods whenever it fires.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from ..db.dao import (
    ComponentDao,
    DashboardDao,
    InventoryItemDao,
    InventoryTransactionDao,
    StorageLocationDao,
)
from ..db.entities import (
    ComponentEntity,
    InventoryItemEntity,
    InventoryTransactionEntity,
    StorageLocationEntity,
)
from ..domain.models import (
    DashboardSummary,
    ExistingStockLocation,
    InboundRecord,
    LocationCategoryProfile,
    LocationInventoryItem,
    SearchInventoryRecord,
    StockLocationCell,
    StorageLocation,
    calculate_dominant_location_category_profile,
)
from ..domain.sort_mode import StorageLocationSortMode
from .image_store import ComponentImageStore

_LOG = logging.getLogger(__name__)
_LOCATION_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*$")


class InventoryRepositoryImpl(QObject):
    changed = Signal()

    def __init__(
        self,
        conn,
        component_dao: ComponentDao,
        dashboard_dao: DashboardDao,
        storage_location_dao: StorageLocationDao,
        inventory_item_dao: InventoryItemDao,
        inventory_transaction_dao: InventoryTransactionDao,
        component_image_store: ComponentImageStore,
        enrichment_scheduler: Callable[[str], None] | None = None,
        tr: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._component_dao = component_dao
        self._dashboard_dao = dashboard_dao
        self._storage_location_dao = storage_location_dao
        self._inventory_item_dao = inventory_item_dao
        self._inventory_transaction_dao = inventory_transaction_dao
        self._image_store = component_image_store
        self._schedule_enrichment = enrichment_scheduler or (lambda _pn: None)
        self._tr = tr or (lambda key: key)
        self._lock = threading.RLock()

    # ---- transaction helper ----
    @contextmanager
    def _transaction(self):
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _emit_changed(self) -> None:
        # Defer signal emission so callers can batch; emitted on the same thread.
        self.changed.emit()

    # ---- observers (snapshots) ----
    def observe_dashboard_summary(self) -> DashboardSummary:
        s = self._dashboard_dao.observe_summary()
        return DashboardSummary(
            component_count=s.component_count,
            location_count=s.location_count,
            inventory_count=s.inventory_count,
            total_quantity=s.total_quantity,
            transaction_count=s.transaction_count,
        )

    def observe_storage_locations(self) -> list[StorageLocation]:
        return [
            StorageLocation(
                id=loc.id,
                code=loc.code,
                display_name=loc.display_name,
                color_hex=loc.color_hex,
                sort_mode=loc.sort_mode,
                remark=loc.remark,
            )
            for loc in self._storage_location_dao.get_all()
        ]

    def observe_stock_location_cells(self) -> list[StockLocationCell]:
        return [
            StockLocationCell(
                id=loc.id,
                code=loc.code,
                display_name=loc.display_name,
                color_hex=loc.color_hex,
                sort_mode=loc.sort_mode,
                remark=loc.remark,
                inventory_item_count=loc.inventory_item_count,
                total_quantity=loc.total_quantity,
            )
            for loc in self._storage_location_dao.observe_location_summaries()
        ]

    def observe_location_inventory(self, location_id: int) -> list[LocationInventoryItem]:
        return [
            LocationInventoryItem(
                inventory_item_id=item.inventory_item_id,
                component_id=item.component_id,
                part_number=item.part_number,
                mpn=item.mpn,
                name=item.name,
                brand=item.brand,
                package_name=item.package_name,
                category=item.category,
                description=item.description,
                source_url=item.source_url,
                specifications=_parse_specifications(item.spec_json),
                image_local_path=item.image_local_path,
                image_url=item.image_url,
                quantity=item.quantity,
                last_inbound_at=item.last_inbound_at,
            )
            for item in self._inventory_item_dao.observe_items_by_location(location_id)
        ]

    def observe_location_category_profiles(self) -> list[LocationCategoryProfile]:
        # Mirrors the Kotlin impl: profiles come from storage_location inbound
        # profile columns (not the per-item projection), with quantity=1 sentinel.
        result: list[LocationCategoryProfile] = []
        for loc in self._storage_location_dao.get_all():
            if loc.inbound_profile_updated_at <= 0:
                continue
            result.append(
                LocationCategoryProfile(
                    location_id=loc.id,
                    category=loc.inbound_category,
                    package_name=loc.inbound_package_name,
                    quantity=1,
                )
            )
        return result

    def observe_search_inventory_records(self) -> list[SearchInventoryRecord]:
        return [
            SearchInventoryRecord(
                inventory_item_id=item.inventory_item_id,
                component_id=item.component_id,
                part_number=item.part_number,
                mpn=item.mpn,
                name=item.name,
                brand=item.brand,
                package_name=item.package_name,
                category=item.category,
                description=item.description,
                source_url=item.source_url,
                specifications=_parse_specifications(item.spec_json),
                image_local_path=item.image_local_path,
                image_url=item.image_url,
                quantity=item.quantity,
                location_id=item.location_id,
                location_code=item.location_code,
                location_display_name=item.location_display_name,
                location_color_hex=item.location_color_hex,
            )
            for item in self._inventory_item_dao.observe_search_inventory_records()
        ]

    def find_existing_stock_locations(self, part_number: str) -> list[ExistingStockLocation]:
        return [
            ExistingStockLocation(
                location_code=item.location_code,
                location_display_name=item.location_display_name,
                quantity=item.quantity,
            )
            for item in self._inventory_item_dao.find_existing_stock_locations(
                part_number.strip().upper()
            )
        ]

    # ---- profile refresh ----
    def refresh_missing_location_category_profiles(self) -> None:
        with self._transaction():
            for loc in self._storage_location_dao.find_locations_missing_inbound_profile():
                self._refresh_location_category_profile_internal(loc.id)
        self._emit_changed()

    def refresh_all_location_category_profiles(self) -> None:
        with self._transaction():
            profiles_by_location: dict[int, list[LocationCategoryProfile]] = {}
            for projection in self._inventory_item_dao.get_all_location_category_profiles():
                profile = LocationCategoryProfile(
                    location_id=projection.location_id,
                    category=projection.category,
                    package_name=projection.package_name,
                    quantity=projection.quantity,
                )
                profiles_by_location.setdefault(profile.location_id, []).append(profile)
            for loc in self._storage_location_dao.get_all():
                profile = calculate_dominant_location_category_profile(
                    profiles_by_location.get(loc.id, [])
                )
                self._storage_location_dao.update_inbound_profile(
                    location_id=loc.id,
                    category=profile.category,
                    package_name=profile.package_name,
                    updated_at=int(time.time() * 1000),
                )
        self._emit_changed()

    def refresh_location_category_profile(self, location_id: int) -> None:
        with self._transaction():
            self._refresh_location_category_profile_internal(location_id)
        self._emit_changed()

    def _refresh_location_category_profile_internal(self, location_id: int) -> None:
        profile = calculate_dominant_location_category_profile(
            [
                LocationCategoryProfile(
                    location_id=p.location_id,
                    category=p.category,
                    package_name=p.package_name,
                    quantity=p.quantity,
                )
                for p in self._inventory_item_dao.get_location_category_profiles(location_id)
            ]
        )
        self._storage_location_dao.update_inbound_profile(
            location_id=location_id,
            category=profile.category,
            package_name=profile.package_name,
            updated_at=int(time.time() * 1000),
        )

    # ---- manual inbound sequencing ----
    def get_next_manual_inbound_part_number(self) -> str:
        in_stock = self._inventory_item_dao.get_in_stock_c0_prefixed_part_numbers()
        parsed = [idx for idx in (_parse_manual_inbound_index(pn) for pn in in_stock) if idx is not None]
        next_index = (max(parsed) + 1) if parsed else 1
        return _format_manual_inbound_part_number(next_index)

    # ---- bootstrap ----
    def bootstrap_defaults(self) -> None:
        """No-op: warehouses are created on-demand during inbound.

        Previously this method created 15 default PCB-reference warehouses
        (R, C, U, D, L, Q, J, K, Y, F, SW, T, BZ, BAT, TP) on every startup.
        Now warehouses are only created when the user actually confirms an
        inbound (via ``_find_or_create_location``), keeping the warehouse
        list clean and free of empty entries.
        """
        return

    def ensure_location_code(self, code: str) -> StorageLocationEntity:
        """Return the location with ``code``, creating it if it does not yet exist.

        Supports numbered location codes like ``U1``, ``R2``, etc.
        The base letter (e.g. ``U``) is extracted to look up the category label,
        but the full code (e.g. ``U1``) is used as the actual storage location code.
        """
        import re

        normalized = (code or "").strip().upper()
        if not normalized:
            raise ValueError("location code is required")

        existing = self._storage_location_dao.find_by_code(normalized)
        if existing is not None:
            return existing

        # Extract base letter(s) from numbered code (e.g. "U1" → "U", "SW2" → "SW")
        base_match = re.match(r'^([A-Za-z]+)', normalized)
        base_code = base_match.group(1) if base_match else normalized

        from ..domain.category_mapping import default_location_codes

        # Check if base code is a valid default location code
        if base_code not in default_location_codes():
            # Unknown code — let _find_or_create_location handle it later.
            raise LookupError(f"Unknown default location code: {normalized}")

        labels = {
            "R": "电阻",
            "C": "电容",
            "L": "电感/磁珠",
            "D": "二极管/LED",
            "Q": "三极管/MOS管",
            "U": "IC/芯片",
            "J": "连接器",
            "K": "继电器",
            "Y": "晶振",
            "F": "保险丝",
            "SW": "开关",
            "T": "变压器",
            "BZ": "蜂鸣器",
            "BAT": "电池",
            "TP": "测试点",
        }

        # Display name uses the code itself (e.g. "U1") rather than Chinese label
        with self._transaction():
            new_id = self._storage_location_dao.insert(
                StorageLocationEntity(
                    code=normalized,
                    display_name=normalized,  # Default to code, not Chinese label
                    sort_mode=StorageLocationSortMode.NONE,
                    remark=f"{labels.get(base_code, base_code)}库位",
                )
            )
            self._emit_changed()
        created = self._storage_location_dao.find_by_code(normalized)
        if created is None:
            raise RuntimeError(f"Failed to ensure location {normalized}")
        return created

    # ---- inbound ----
    def add_inbound(self, record: InboundRecord) -> None:
        prepared = self._prepare_inbound_record(record)
        inbound_at = prepared.inbound_at
        with self._transaction():
            location = self._find_or_create_location(prepared.location_code)
            component_id = self._upsert_component(prepared)
            existing_item = self._inventory_item_dao.find_by_component_and_location(
                component_id, location.id
            )
            if existing_item is None:
                self._inventory_item_dao.insert(
                    InventoryItemEntity(
                        component_id=component_id,
                        location_id=location.id,
                        quantity=record.quantity,
                        last_inbound_at=inbound_at,
                        updated_at=inbound_at,
                    )
                )
            else:
                self._inventory_item_dao.update(
                    InventoryItemEntity(
                        id=existing_item.id,
                        component_id=existing_item.component_id,
                        location_id=existing_item.location_id,
                        quantity=existing_item.quantity + record.quantity,
                        last_inbound_at=inbound_at,
                        updated_at=inbound_at,
                    )
                )
            self._inventory_transaction_dao.insert(
                InventoryTransactionEntity(
                    component_id=component_id,
                    location_id=location.id,
                    txn_type="INBOUND",
                    quantity_delta=prepared.quantity,
                    source_type=prepared.source_type,
                    source_ref=prepared.component.part_number,
                    raw_payload=prepared.raw_payload,
                    created_at=inbound_at,
                )
            )
            self._refresh_location_category_profile_internal(location.id)
        if prepared.source_type != "MANUAL_INPUT":
            self._schedule_enrichment(prepared.component.part_number)
        self._emit_changed()

    # ---- location CRUD ----
    def update_location(
        self,
        location_id: int,
        code: str,
        display_name: str | None,
        color_hex: str | None,
        sort_mode: str,
    ) -> str | None:
        location = self._storage_location_dao.find_by_id(location_id)
        if location is None:
            return self._tr("inventory_error_location_not_found")
        normalized_code = code.strip().upper()
        if not _LOCATION_CODE_RE.match(normalized_code):
            return self._tr("inventory_error_location_code_format")
        duplicated = self._storage_location_dao.find_by_code(normalized_code)
        if duplicated is not None and duplicated.id != location_id:
            return self._tr("inventory_error_location_code_exists")
        with self._transaction():
            self._storage_location_dao.update(
                StorageLocationEntity(
                    id=location.id,
                    code=normalized_code,
                    display_name=display_name if display_name and display_name.strip() else None,
                    color_hex=color_hex if color_hex and color_hex.strip() else None,
                    sort_mode=sort_mode,
                    inbound_category=location.inbound_category,
                    inbound_package_name=location.inbound_package_name,
                    inbound_profile_updated_at=location.inbound_profile_updated_at,
                    remark=location.remark,
                    created_at=location.created_at,
                )
            )
        self._emit_changed()
        return None

    def add_storage_location(
        self, code: str, display_name: str | None, color_hex: str | None
    ) -> bool:
        normalized_code = code.strip().upper()
        if not _LOCATION_CODE_RE.match(normalized_code):
            return False
        if self._storage_location_dao.find_by_code(normalized_code) is not None:
            return False
        new_id = self._storage_location_dao.insert(
            StorageLocationEntity(
                code=normalized_code,
                display_name=(display_name.strip() if display_name and display_name.strip() else normalized_code),
                color_hex=color_hex if color_hex and color_hex.strip() else None,
                sort_mode=StorageLocationSortMode.NONE,
            )
        )
        if new_id > 0:
            self._emit_changed()
            return True
        return False

    def delete_location(self, location_id: int) -> str | None:
        with self._transaction():
            location = self._storage_location_dao.find_by_id(location_id)
            if location is None:
                return self._tr("inventory_error_location_not_found")
            if self._inventory_item_dao.count_by_location(location_id) > 0:
                return self._tr("inventory_error_location_has_items")
            self._inventory_transaction_dao.delete_by_location_id(location.id)
            self._storage_location_dao.delete_by_id(location.id)
        self._emit_changed()
        return None

    def force_delete_location(self, location_id: int) -> str | None:
        with self._transaction():
            location = self._storage_location_dao.find_by_id(location_id)
            if location is None:
                return self._tr("inventory_error_location_not_found")
            self._inventory_transaction_dao.delete_by_location_id(location.id)
            self._inventory_item_dao.delete_by_location_id(location.id)
            self._refresh_location_category_profile_internal(location.id)
            self._storage_location_dao.delete_by_id(location.id)
        self._emit_changed()
        return None

    # ---- inventory item ops ----
    def update_inventory_item_quantity(self, inventory_item_id: int, quantity: int) -> str | None:
        if quantity < 0:
            return self._tr("inventory_error_quantity_negative")
        with self._transaction():
            item = self._inventory_item_dao.find_by_id(inventory_item_id)
            if item is None:
                return self._tr("inventory_error_item_not_found")
            if item.quantity == quantity:
                return None
            delta = quantity - item.quantity
            component = self._component_dao.find_by_id(item.component_id)
            self._inventory_item_dao.update(
                InventoryItemEntity(
                    id=item.id,
                    component_id=item.component_id,
                    location_id=item.location_id,
                    quantity=quantity,
                    last_inbound_at=item.last_inbound_at,
                    updated_at=int(time.time() * 1000),
                )
            )
            self._inventory_transaction_dao.insert(
                InventoryTransactionEntity(
                    component_id=item.component_id,
                    location_id=item.location_id,
                    txn_type="ADJUST",
                    quantity_delta=delta,
                    source_type="MANUAL_EDIT",
                    source_ref=component.part_number if component else None,
                )
            )
            self._refresh_location_category_profile_internal(item.location_id)
        self._emit_changed()
        return None

    def update_inventory_item_source(self, inventory_item_id: int, source_url: str | None) -> str | None:
        with self._transaction():
            item = self._inventory_item_dao.find_by_id(inventory_item_id)
            if item is None:
                return self._tr("inventory_error_item_not_found")
            component = self._component_dao.find_by_id(item.component_id)
            if component is None:
                return self._tr("inventory_error_item_not_found")
            normalized_url = source_url.strip() if source_url and source_url.strip() else None
            if component.source_url == normalized_url:
                return None
            self._component_dao.update(
                ComponentEntity(
                    id=component.id,
                    part_number=component.part_number,
                    mpn=component.mpn,
                    name=component.name,
                    brand=component.brand,
                    package_name=component.package_name,
                    category=component.category,
                    spec_json=component.spec_json,
                    description=component.description,
                    source_url=normalized_url,
                    image_local_path=component.image_local_path,
                    updated_at=int(time.time() * 1000),
                )
            )
        self._emit_changed()
        return None

    def transfer_inventory_item(self, inventory_item_id: int, target_location_code: str) -> str | None:
        normalized_code = target_location_code.strip().upper()
        if not normalized_code:
            return self._tr("inventory_error_target_location_required")
        with self._transaction():
            item = self._inventory_item_dao.find_by_id(inventory_item_id)
            if item is None:
                return self._tr("inventory_error_item_not_found")
            target_location = self._storage_location_dao.find_by_code(normalized_code)
            if target_location is None:
                return self._tr("inventory_error_target_location_not_found")
            if target_location.id == item.location_id:
                return self._tr("inventory_error_target_location_same")
            component = self._component_dao.find_by_id(item.component_id)
            target_item = self._inventory_item_dao.find_by_component_and_location(
                item.component_id, target_location.id
            )
            now = int(time.time() * 1000)
            if target_item is None:
                self._inventory_item_dao.update(
                    InventoryItemEntity(
                        id=item.id,
                        component_id=item.component_id,
                        location_id=target_location.id,
                        quantity=item.quantity,
                        last_inbound_at=item.last_inbound_at,
                        updated_at=now,
                    )
                )
            else:
                self._inventory_item_dao.update(
                    InventoryItemEntity(
                        id=target_item.id,
                        component_id=target_item.component_id,
                        location_id=target_item.location_id,
                        quantity=target_item.quantity + item.quantity,
                        last_inbound_at=target_item.last_inbound_at,
                        updated_at=now,
                    )
                )
                self._inventory_item_dao.delete_by_id(item.id)
            source_ref = component.part_number if component else None
            self._inventory_transaction_dao.insert(
                InventoryTransactionEntity(
                    component_id=item.component_id,
                    location_id=item.location_id,
                    txn_type="TRANSFER_OUT",
                    quantity_delta=-item.quantity,
                    source_type="MANUAL_TRANSFER",
                    source_ref=source_ref,
                )
            )
            self._inventory_transaction_dao.insert(
                InventoryTransactionEntity(
                    component_id=item.component_id,
                    location_id=target_location.id,
                    txn_type="TRANSFER_IN",
                    quantity_delta=item.quantity,
                    source_type="MANUAL_TRANSFER",
                    source_ref=source_ref,
                )
            )
            self._refresh_location_category_profile_internal(item.location_id)
            self._refresh_location_category_profile_internal(target_location.id)
        self._emit_changed()
        return None

    def delete_inventory_item(self, inventory_item_id: int) -> str | None:
        with self._transaction():
            item = self._inventory_item_dao.find_by_id(inventory_item_id)
            if item is None:
                return self._tr("inventory_error_item_not_found")
            component = self._component_dao.find_by_id(item.component_id)
            self._inventory_item_dao.delete_by_id(item.id)
            self._inventory_transaction_dao.insert(
                InventoryTransactionEntity(
                    component_id=item.component_id,
                    location_id=item.location_id,
                    txn_type="DELETE",
                    quantity_delta=-item.quantity,
                    source_type="MANUAL_DELETE",
                    source_ref=component.part_number if component else None,
                )
            )
            self._refresh_location_category_profile_internal(item.location_id)
        self._emit_changed()
        return None

    # ---- inbound helpers ----
    def _find_or_create_location(self, code: str) -> StorageLocationEntity:
        normalized_code = code.strip().upper()
        existing = self._storage_location_dao.find_by_code(normalized_code)
        if existing is not None:
            return existing
        self._storage_location_dao.insert(
            StorageLocationEntity(
                code=normalized_code,
                display_name=normalized_code,
                sort_mode=StorageLocationSortMode.NONE,
            )
        )
        return self._storage_location_dao.find_by_code(normalized_code) or StorageLocationEntity(
            code=normalized_code,
            display_name=normalized_code,
            sort_mode=StorageLocationSortMode.NONE,
        )

    def _prepare_inbound_record(self, record: InboundRecord) -> InboundRecord:
        existing_path = record.component.image_local_path
        if existing_path and existing_path.strip():
            try:
                if Path(existing_path).exists() and Path(existing_path).stat().st_size > 0:
                    return record
            except OSError:
                pass
        persisted = self._image_store.persist_image(
            part_number=record.component.part_number,
            image_url=record.component.image_url,
        )
        if not persisted:
            return record
        return InboundRecord(
            component=replace(record.component, image_local_path=persisted),
            quantity=record.quantity,
            location_code=record.location_code,
            source_type=record.source_type,
            raw_payload=record.raw_payload,
            inbound_at=record.inbound_at,
        )

    def _upsert_component(self, record: InboundRecord) -> int:
        normalized_part_number = record.component.part_number.strip().upper()
        existing = self._component_dao.find_by_part_number(normalized_part_number)
        spec_json = (
            json.dumps(record.component.specifications, ensure_ascii=False)
            if record.component.specifications
            else None
        )
        now = int(time.time() * 1000)
        if existing is not None:
            should_reset_stale = (
                record.source_type == "MANUAL_INPUT"
                and self._inventory_item_dao.count_by_component(existing.id) == 0
            )
            if should_reset_stale:
                updated = ComponentEntity(
                    id=existing.id,
                    part_number=normalized_part_number,
                    mpn=record.component.mpn,
                    name=record.component.name,
                    brand=record.component.brand,
                    package_name=record.component.package_name,
                    category=record.component.category,
                    spec_json=spec_json,
                    description=record.component.description,
                    source_url=record.component.product_url,
                    image_local_path=record.component.image_local_path,
                    image_url=record.component.image_url,
                    updated_at=now,
                )
            else:
                updated = ComponentEntity(
                    id=existing.id,
                    part_number=normalized_part_number,
                    mpn=existing.mpn or record.component.mpn,
                    name=existing.name or record.component.name,
                    brand=existing.brand or record.component.brand,
                    package_name=existing.package_name or record.component.package_name,
                    category=existing.category or record.component.category,
                    spec_json=existing.spec_json or spec_json,
                    description=existing.description or record.component.description,
                    source_url=existing.source_url or record.component.product_url,
                    image_local_path=existing.image_local_path or record.component.image_local_path,
                    image_url=existing.image_url or record.component.image_url,
                    updated_at=now,
                )
            if _component_differs(updated, existing):
                self._component_dao.update(updated)
            return existing.id
        insert_id = self._component_dao.insert(
            ComponentEntity(
                part_number=normalized_part_number,
                mpn=record.component.mpn,
                name=record.component.name,
                brand=record.component.brand,
                package_name=record.component.package_name,
                category=record.component.category,
                spec_json=spec_json,
                description=record.component.description,
                source_url=record.component.product_url,
                image_local_path=record.component.image_local_path,
                image_url=record.component.image_url,
            )
        )
        if insert_id > 0:
            return insert_id
        fallback = self._component_dao.find_by_part_number(normalized_part_number)
        if fallback is not None:
            return fallback.id
        raise RuntimeError(f"Failed to resolve component id for {normalized_part_number}")


def _component_differs(a: ComponentEntity, b: ComponentEntity) -> bool:
    return (
        a.part_number != b.part_number
        or a.mpn != b.mpn
        or a.name != b.name
        or a.brand != b.brand
        or a.package_name != b.package_name
        or a.category != b.category
        or a.spec_json != b.spec_json
        or a.description != b.description
        or a.source_url != b.source_url
        or a.image_local_path != b.image_local_path
        or a.image_url != b.image_url
        or a.updated_at != b.updated_at
    )


def _parse_specifications(spec_json: str | None) -> dict[str, str]:
    if not spec_json or not spec_json.strip():
        return {}
    try:
        obj = json.loads(spec_json)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(obj, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in obj.items():
        text = value if isinstance(value, str) else (str(value) if value is not None else "")
        if text.strip() and text != "null":
            result[str(key)] = text
    return result


def _parse_manual_inbound_index(part_number: str | None) -> int | None:
    if not part_number:
        return None
    normalized = part_number.strip().upper()
    if not re.match(r"^C0\d+$", normalized):
        return None
    try:
        return int(normalized[2:])
    except ValueError:
        return None


def _format_manual_inbound_part_number(index: int) -> str:
    return f"C0{index}"
