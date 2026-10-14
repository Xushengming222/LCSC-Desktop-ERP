"""InventoryViewModel — port of feature/inventory/InventoryViewModel.kt.

The most state-heavy view model: it tracks the selected location, an optional
``pendingOpenRequest`` (cross-tab deep-link), a settings panel, and per-location
inventory items sorted by the location's configured sort mode (which can chain
NAME / QUANTITY / INBOUND_TIME / SPEC:<key> priorities).

The Kotlin ``flatMapLatest`` flows become plain recompute logic: whenever the
repository emits ``changed`` or the preferences change, we re-query the
selected location's items and re-sort them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QThreadPool

from ..data.catalog_repository import LcscCatalogRepositoryImpl
from ..data.inventory_repository import InventoryRepositoryImpl
from ..data.preferences import UserPreferencesRepository
from ..data.qr_parser import parse_lcsc_qr
from ..domain.models import ComponentDetail, LocationInventoryItem, StockLocationCell, StorageLocation
from ..domain.sort_mode import StorageLocationSortMode
from ..i18n import tr
from .base import ViewModel
from .inbound_viewmodel import _is_network_available


@dataclass
class InventoryOpenRequest:
    location_code: str
    part_number: str


@dataclass
class InventoryScanLookupResult:
    component: Optional[ComponentDetail] = None
    quantity: int = 0
    raw_payload: Optional[str] = None
    error_message: Optional[str] = None
    existing_stock_locations: list = field(default_factory=list)


@dataclass
class InventoryUiState:
    cells: list[StockLocationCell] = field(default_factory=list)
    locations: list[StorageLocation] = field(default_factory=list)
    selected_location: Optional[StockLocationCell] = None
    selected_location_items: list[LocationInventoryItem] = field(default_factory=list)
    pending_open_request: Optional[InventoryOpenRequest] = None
    settings_location_sort_attributes: list[str] = field(default_factory=list)
    recent_location_colors: list[str] = field(default_factory=list)
    add_material_search_results: list[ComponentDetail] = field(default_factory=list)
    is_searching_add_material: bool = False
    add_material_search_error: Optional[str] = None
    add_location_error: Optional[str] = None
    update_location_error: Optional[str] = None


_ENG_NUMBER_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([pnumkKMGTu]?)(?:[A-Za-z%ΩohmOHM]*)?.*$")


def _parse_engineering_number(raw_value: str) -> Optional[float]:
    normalized = (
        raw_value.strip()
        .replace("±", "")
        .replace("μ", "u")
        .replace("µ", "u")
        .replace(",", "")
    )
    if not normalized:
        return None
    match = _ENG_NUMBER_RE.match(normalized)
    if match is None:
        return None
    try:
        numeric = float(match.group(1))
    except ValueError:
        return None
    suffix = match.group(2)
    multipliers = {
        "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
        "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
    }
    return numeric * multipliers.get(suffix, 1.0)


def _primary_sort_key(item: LocationInventoryItem) -> str:
    name = (item.name or "").strip()
    if name:
        return name
    mpn = (item.mpn or "").strip()
    if mpn:
        return mpn
    return item.part_number


def _spec_value(item: LocationInventoryItem, key: str) -> str:
    raw = (item.specifications.get(key) or "").strip()
    return raw or _primary_sort_key(item)


def _sort_location_items(items: list[LocationInventoryItem], sort_mode: str) -> list[LocationInventoryItem]:
    priorities = StorageLocationSortMode.priorities(sort_mode)
    if not priorities:
        return sorted(items, key=lambda it: it.part_number)

    def comparator_key(item: LocationInventoryItem):
        # Build a tuple key honoring the priority chain; final tiebreak is part_number.
        keys = []
        for priority in priorities:
            if priority == StorageLocationSortMode.NAME:
                keys.append(_primary_sort_key(item))
            elif priority == StorageLocationSortMode.QUANTITY:
                keys.append(-item.quantity)  # descending
            elif priority == StorageLocationSortMode.INBOUND_TIME:
                keys.append(-item.last_inbound_at)  # descending
            else:
                spec_key = StorageLocationSortMode.specification_key(priority)
                if spec_key is None:
                    continue
                raw = (item.specifications.get(spec_key) or "").strip()
                missing = not raw
                numeric = _parse_engineering_number(raw) if raw else None
                keys.append((0 if missing else 1))  # present first
                if numeric is None:
                    keys.append(1)  # non-numeric last within present group
                    keys.append(float("inf"))
                else:
                    keys.append(0)
                    keys.append(numeric)
                keys.append(_spec_value(item, spec_key).lower())
        keys.append(item.part_number)
        return tuple(keys)

    return sorted(items, key=comparator_key)


def _supported_specification_keys(items: list[LocationInventoryItem]) -> list[str]:
    seen: dict[str, set[str]] = {}
    for item in items:
        for key, value in item.specifications.items():
            k = key.strip()
            if not k:
                continue
            v = (value or "").strip()
            if not v:
                continue
            seen.setdefault(k, set()).add(v)
    return sorted(k for k, values in seen.items() if len(values) > 1)


class InventoryViewModel(ViewModel):
    def __init__(
        self,
        inventory_repository: InventoryRepositoryImpl,
        lcsc_catalog_repository: LcscCatalogRepositoryImpl,
        user_preferences_repository: UserPreferencesRepository,
        thread_pool: Optional[QThreadPool] = None,
    ) -> None:
        super().__init__(thread_pool)
        self._inventory_repository = inventory_repository
        self._catalog = lcsc_catalog_repository
        self._preferences = user_preferences_repository

        self._selected_location: Optional[StockLocationCell] = None
        self._pending_open_request: Optional[InventoryOpenRequest] = None
        self._add_location_error: Optional[str] = None
        self._update_location_error: Optional[str] = None

        self._inventory_repository.changed.connect(self._schedule_recompute)
        self._preferences.preferences_changed.connect(self._schedule_recompute)

        # init { bootstrapDefaults() }
        self._run_async(
            lambda: self._inventory_repository.bootstrap_defaults(),
            lambda _r, _e: self._schedule_recompute(),
        )
        self._recompute()

    # ---- state assembly ----
    def _recompute(self) -> None:
        cells = self._inventory_repository.observe_stock_location_cells()
        locations = self._inventory_repository.observe_storage_locations()

        # If our selected location was deleted, drop it.
        selected = self._selected_location
        if selected is not None and selected.id not in {c.id for c in cells}:
            # refresh selected from latest cells (preserves selection by id)
            match = next((c for c in cells if c.id == selected.id), None)
            selected = match  # None if deleted
            self._selected_location = selected

        items: list[LocationInventoryItem] = []
        if selected is not None:
            items = self._inventory_repository.observe_location_inventory(selected.id)
            items = _sort_location_items(items, selected.sort_mode)

        # settings panel sort attributes come from the selected location's items
        sort_attrs = _supported_specification_keys(items)

        prefs = self._preferences.preferences
        self._state = InventoryUiState(
            cells=cells,
            locations=locations,
            selected_location=selected,
            selected_location_items=items,
            pending_open_request=self._pending_open_request,
            settings_location_sort_attributes=sort_attrs,
            recent_location_colors=list(prefs.recent_location_colors),
            add_location_error=self._add_location_error,
            update_location_error=self._update_location_error,
        )

    # ---- selection ----
    def on_location_selected(self, location: StockLocationCell) -> None:
        self._selected_location = location
        self._do_recompute()

    def dismiss_location_detail(self) -> None:
        self._selected_location = None
        self._do_recompute()

    def open_inventory_item(self, location_code: str, part_number: str) -> None:
        normalized_code = (location_code or "").strip().upper()
        normalized_pn = (part_number or "").strip().upper()
        if not normalized_code or not normalized_pn:
            return
        cells = self._inventory_repository.observe_stock_location_cells()
        target = next((c for c in cells if c.code.upper() == normalized_code), None)
        if target is None:
            return
        self._pending_open_request = InventoryOpenRequest(
            location_code=target.code,
            part_number=normalized_pn,
        )
        self._selected_location = target
        self._do_recompute()

    def clear_pending_open_request(self) -> None:
        self._pending_open_request = None
        self._do_recompute()

    # ---- error clearers ----
    def clear_add_location_error(self) -> None:
        self._add_location_error = None
        self._do_recompute()

    def clear_update_location_error(self) -> None:
        self._update_location_error = None
        self._do_recompute()

    # ---- location CRUD ----
    def add_storage_location(self, code: str, display_name: Optional[str], color_hex: Optional[str]) -> None:
        self._add_location_error = None
        created = self._inventory_repository.add_storage_location(code, display_name, color_hex)
        self._add_location_error = None if created else tr("inventory_add_location_invalid")
        self._do_recompute()

    def update_location(
        self,
        location_id: int,
        code: str,
        display_name: Optional[str],
        color_hex: Optional[str],
        sort_mode: str,
        on_completed: Optional[Callable[[Optional[str]], None]] = None,
    ) -> None:
        error = self._inventory_repository.update_location(
            location_id=location_id,
            code=code,
            display_name=display_name,
            color_hex=color_hex,
            sort_mode=sort_mode,
        )
        self._update_location_error = error
        if error is None and self._selected_location is not None and self._selected_location.id == location_id:
            self._selected_location = StockLocationCell(
                id=self._selected_location.id,
                code=code.strip().upper(),
                display_name=(display_name.strip() if display_name and display_name.strip() else None),
                color_hex=(color_hex.strip() if color_hex and color_hex.strip() else None),
                sort_mode=sort_mode,
                remark=self._selected_location.remark,
                inventory_item_count=self._selected_location.inventory_item_count,
                total_quantity=self._selected_location.total_quantity,
            )
        self._do_recompute()
        if on_completed:
            on_completed(error)

    def delete_location(self, location_id: int, on_completed: Callable[[Optional[str]], None]) -> None:
        self._update_location_error = None
        error = self._inventory_repository.delete_location(location_id)
        self._update_location_error = error
        if error is None and self._selected_location is not None and self._selected_location.id == location_id:
            self._selected_location = None
        self._do_recompute()
        on_completed(error)

    def force_delete_location(self, location_id: int, on_completed: Callable[[Optional[str]], None]) -> None:
        self._update_location_error = None
        error = self._inventory_repository.force_delete_location(location_id)
        self._update_location_error = error
        if error is None and self._selected_location is not None and self._selected_location.id == location_id:
            self._selected_location = None
        self._do_recompute()
        on_completed(error)

    # ---- inventory item ops ----
    def update_inventory_item_quantity(
        self, inventory_item_id: int, quantity: int, on_completed: Callable[[Optional[str]], None]
    ) -> None:
        error = self._inventory_repository.update_inventory_item_quantity(inventory_item_id, quantity)
        # repository emits changed -> recompute will fire
        on_completed(error)

    def update_inventory_item_source(
        self, inventory_item_id: int, source_url: Optional[str], on_completed: Callable[[Optional[str]], None]
    ) -> None:
        error = self._inventory_repository.update_inventory_item_source(inventory_item_id, source_url)
        on_completed(error)

    def transfer_inventory_item(
        self, inventory_item_id: int, target_location_code: str, on_completed: Callable[[Optional[str]], None]
    ) -> None:
        error = self._inventory_repository.transfer_inventory_item(inventory_item_id, target_location_code)
        on_completed(error)

    def transfer_inventory_items(
        self, inventory_item_ids: list[int], target_location_code: str, on_completed: Callable[[Optional[str]], None]
    ) -> None:
        normalized_target = (target_location_code or "").strip().upper()
        if not inventory_item_ids or not normalized_target:
            on_completed(tr("inventory_transfer_items_empty"))
            return
        last_error: Optional[str] = None
        for inventory_item_id in dict.fromkeys(inventory_item_ids):  # distinct, order-preserving
            error = self._inventory_repository.transfer_inventory_item(inventory_item_id, normalized_target)
            if error is not None:
                last_error = error
                break
        on_completed(last_error)

    def delete_inventory_item(self, inventory_item_id: int, on_completed: Callable[[Optional[str]], None]) -> None:
        error = self._inventory_repository.delete_inventory_item(inventory_item_id)
        on_completed(error)

    def delete_inventory_items(
        self, inventory_item_ids: list[int], on_completed: Callable[[Optional[str]], None]
    ) -> None:
        if not inventory_item_ids:
            on_completed(tr("inventory_delete_items_empty"))
            return
        last_error: Optional[str] = None
        for inventory_item_id in dict.fromkeys(inventory_item_ids):
            error = self._inventory_repository.delete_inventory_item(inventory_item_id)
            if error is not None:
                last_error = error
                break
        on_completed(last_error)

    # ---- scan-based inbound (mirrors lookupScannedComponent / addScannedInbound) ----
    def lookup_scanned_component(
        self, raw_text: str, on_completed: Callable[[InventoryScanLookupResult], None]
    ) -> None:
        payload = parse_lcsc_qr(raw_text)
        if payload is None:
            on_completed(InventoryScanLookupResult(error_message=tr("inbound_scan_invalid_qr")))
            return
        if not _is_network_available():
            message = tr("common_network_unavailable")
            on_completed(
                InventoryScanLookupResult(
                    quantity=payload.quantity,
                    raw_payload=payload.raw_text,
                    error_message=message,
                )
            )
            return

        part_number = payload.part_number

        def _work():
            component = self._catalog.lookup_by_part_number(part_number)
            existing: list = []
            if component is not None:
                existing = self._inventory_repository.find_existing_stock_locations(component.part_number)
            return component, existing

        def _on_done(payload_pair, error):
            if error is not None:
                on_completed(
                    InventoryScanLookupResult(
                        quantity=payload.quantity,
                        raw_payload=payload.raw_text,
                        error_message=tr("inbound_scan_component_not_found", part_number),
                    )
                )
                return
            component, existing = payload_pair
            if component is None:
                on_completed(
                    InventoryScanLookupResult(
                        quantity=payload.quantity,
                        raw_payload=payload.raw_text,
                        error_message=tr("inbound_scan_component_not_found", part_number),
                    )
                )
                return
            on_completed(
                InventoryScanLookupResult(
                    component=component,
                    quantity=payload.quantity,
                    raw_payload=payload.raw_text,
                    existing_stock_locations=existing,
                )
            )

        self._run_async(_work, _on_done)

    def add_scanned_inbound(
        self,
        component: ComponentDetail,
        quantity: int,
        location_code: str,
        raw_payload: Optional[str],
        on_completed: Callable[[], None],
    ) -> None:
        if quantity < 0 or not location_code or not location_code.strip():
            on_completed()
            return
        from ..domain.models import InboundRecord

        def _work():
            self._inventory_repository.add_inbound(
                InboundRecord(
                    component=component,
                    quantity=quantity,
                    location_code=location_code.strip().upper(),
                    source_type="LOCATION_SCAN",
                    raw_payload=raw_payload,
                )
            )

        def _on_done(_result, _error):
            on_completed()

        self._run_async(_work, _on_done)

    # ---- preferences ----
    def add_recent_location_color(self, color_hex: str) -> None:
        self._preferences.add_recent_location_color(color_hex)
