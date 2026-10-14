"""SearchViewModel — port of feature/search/SearchViewModel.kt.

Two modes: Manual (search local inventory by keyword) and BOM (import a BOM
spreadsheet and match each row against local inventory). The Kotlin ``combine``
pipeline over inventoryRecords / persistentBindings / temporaryBindings /
ignoredEntryKeys / mode / query / page / parsedBomDocument / bomFilter /
bomError / isParsingBom / locations / defaultLocationCode becomes a single
``_recompute`` that folds all these sources into ``SearchUiState``.

BOM matching preserves the Android precedence: bound part number > supplier
part > manufacturer part > passive-footprint heuristic (resistor/capacitor).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from PySide6.QtCore import QThreadPool

from ..data.bom_parser import parse_bom_file
from ..data.catalog_repository import LcscCatalogRepositoryImpl
from ..data.inventory_repository import InventoryRepositoryImpl
from ..data.preferences import UserPreferencesRepository
from ..domain.bom import (
    BomDirectInboundLookupResult,
    BomMatchFilter,
    BomSearchEntry,
    BomSearchRowUiModel,
    ParsedBomDocument,
    SearchMode,
    SearchResultLocationUiModel,
    SearchResultUiModel,
)
from ..domain.category_mapping import suggest_location_code
from ..domain.models import ComponentDetail, ExistingStockLocation, SearchInventoryRecord, StorageLocation
from ..i18n import tr
from .base import ViewModel
from .inbound_viewmodel import _is_network_available

PAGE_SIZE = 10

_RESISTOR_FOOTPRINT_RE = re.compile(r"^R\d{4}$")
_CAPACITOR_FOOTPRINT_RE = re.compile(r"^C\d{4}$")
_PACKAGE_DIGITS_RE = re.compile(r"(\d{4})")


@dataclass
class SearchUiState:
    mode: SearchMode = SearchMode.MANUAL
    query: str = ""
    default_location_code: Optional[str] = None
    locations: list[StorageLocation] = field(default_factory=list)
    all_inventory_results: list[SearchResultUiModel] = field(default_factory=list)
    results: list[SearchResultUiModel] = field(default_factory=list)
    paged_results: list[SearchResultUiModel] = field(default_factory=list)
    inventory_record_count: int = 0
    current_page: int = 1
    page_count: int = 1
    bom_file_name: Optional[str] = None
    bom_filter: BomMatchFilter = BomMatchFilter.ALL
    bom_rows: list[BomSearchRowUiModel] = field(default_factory=list)
    all_bom_rows: list[BomSearchRowUiModel] = field(default_factory=list)
    bom_matched_count: int = 0
    bom_error: Optional[str] = None
    is_parsing_bom: bool = False


class _PassiveFootprintType(Enum):
    RESISTOR = "Resistor"
    CAPACITOR = "Capacitor"


def _bom_entry_key(entry: BomSearchEntry) -> str:
    parts = [
        entry.row_number,
        entry.supplier_part or "",
        entry.manufacturer_part or "",
        entry.designator or "",
        entry.value or "",
    ]
    return "|".join(p.strip().upper() for p in parts)


def _normalize_passive_value(value: str) -> str:
    return (
        value.strip()
        .upper()
        .replace(" ", "")
        .replace("Ω", "")
        .replace("OHM", "")
        .replace("欧姆", "")
        .replace("µ", "U")
        .replace("μ", "U")
    )


def _normalize_package_name(package_name: Optional[str]) -> Optional[str]:
    normalized = (package_name or "").strip().upper()
    match = _PACKAGE_DIGITS_RE.search(normalized)
    return match.group(1) if match else None


def _parse_passive_footprint_type(footprint: str) -> Optional[_PassiveFootprintType]:
    if _RESISTOR_FOOTPRINT_RE.match(footprint):
        return _PassiveFootprintType.RESISTOR
    if _CAPACITOR_FOOTPRINT_RE.match(footprint):
        return _PassiveFootprintType.CAPACITOR
    return None


def _parse_passive_footprint_package(footprint: str) -> Optional[str]:
    rest = footprint[1:]
    if len(rest) == 4 and rest.isdigit():
        return rest
    return None


def _build_search_tokens(record: SearchInventoryRecord) -> list[str]:
    tokens: list[str] = [record.part_number]
    for candidate in (
        record.mpn,
        record.name,
        record.brand,
        record.package_name,
        record.category,
        record.description,
        record.location_code,
        record.location_display_name,
    ):
        if candidate:
            tokens.append(candidate)
    for key, value in record.specifications.items():
        tokens.append(key)
        tokens.append(value)
    return [t.strip().lower() for t in tokens if t and t.strip()]


def _filter_records(records: list[SearchInventoryRecord], query_text: str) -> list[SearchInventoryRecord]:
    normalized_query = (query_text or "").strip().lower()
    if not normalized_query:
        return records
    return [
        record
        for record in records
        if any(token.find(normalized_query) != -1 for token in _build_search_tokens(record))
    ]


def _primary_result_key(model: SearchResultUiModel) -> str:
    name = (model.name or "").strip()
    if name:
        return name
    mpn = (model.mpn or "").strip()
    if mpn:
        return mpn
    return model.part_number


def _group_records(records: list[SearchInventoryRecord]) -> list[SearchResultUiModel]:
    grouped: dict[str, list[SearchInventoryRecord]] = {}
    for record in records:
        key = f"{record.part_number}|{record.mpn or ''}"
        grouped.setdefault(key, []).append(record)
    result: list[SearchResultUiModel] = []
    for group in grouped.values():
        first = group[0]
        group_sorted = sorted(group, key=lambda r: r.location_code)
        result.append(
            SearchResultUiModel(
                part_number=first.part_number,
                mpn=first.mpn,
                name=first.name,
                brand=first.brand,
                package_name=first.package_name,
                category=first.category,
                description=first.description,
                source_url=first.source_url,
                specifications=first.specifications,
                image_local_path=first.image_local_path,
                image_url=first.image_url,
                total_quantity=sum(r.quantity for r in group),
                locations=[
                    SearchResultLocationUiModel(
                        code=r.location_code,
                        display_name=r.location_display_name,
                        color_hex=r.location_color_hex,
                        quantity=r.quantity,
                    )
                    for r in group_sorted
                ],
                records=group_sorted,
            )
        )
    result.sort(key=lambda m: (_primary_result_key(m), m.part_number))
    return result


def _matches_passive_footprint_entry(record: SearchInventoryRecord, entry: BomSearchEntry) -> bool:
    footprint = (entry.footprint or "").strip().upper()
    passive_type = _parse_passive_footprint_type(footprint)
    if passive_type is None:
        return False
    normalized_package = _parse_passive_footprint_package(footprint)
    if normalized_package is None:
        return False
    record_package = _normalize_package_name(record.package_name)
    if record_package is None or record_package != normalized_package:
        return False
    category = (record.category or "")
    if passive_type is _PassiveFootprintType.RESISTOR:
        matches_category = "电阻" in category
    else:
        matches_category = "电容" in category
    if not matches_category:
        return False
    raw_value = entry.value if entry.value and entry.value.strip() else (entry.comment or "")
    bom_value = _normalize_passive_value(raw_value)
    if not bom_value:
        return False
    spec_keys = ["阻值"] if passive_type is _PassiveFootprintType.RESISTOR else ["容值"]
    for key in spec_keys:
        raw = record.specifications.get(key)
        if raw:
            normalized = _normalize_passive_value(raw)
            if normalized and normalized == bom_value:
                return True
    return False


def _matches_bom_entry(
    record: SearchInventoryRecord, entry: BomSearchEntry, bound_part_number: Optional[str]
) -> bool:
    if bound_part_number:
        return record.part_number.strip().upper() == bound_part_number
    supplier_part = (entry.supplier_part or "").strip().upper()
    if supplier_part:
        return record.part_number.strip().upper() == supplier_part
    manufacturer_part = (entry.manufacturer_part or "").strip().upper()
    if manufacturer_part:
        mpn = (record.mpn or "").strip().upper()
        return mpn == manufacturer_part
    return _matches_passive_footprint_entry(record, entry)


def _build_bom_rows(
    inventory_records: list[SearchInventoryRecord],
    document: Optional[ParsedBomDocument],
    persistent_bindings: dict[str, str],
    temporary_bindings: dict[str, str],
    ignored_entry_keys: set[str],
) -> list[BomSearchRowUiModel]:
    if document is None:
        return []
    result: list[BomSearchRowUiModel] = []
    for entry in document.entries:
        key = _bom_entry_key(entry)
        if key in ignored_entry_keys:
            continue
        persistent_pn: Optional[str] = None
        supplier_part = (entry.supplier_part or "").strip().upper()
        if supplier_part:
            persistent_pn = persistent_bindings.get(supplier_part)
        temporary_pn = temporary_bindings.get(key)
        bound_pn = persistent_pn or temporary_pn
        matched = [
            record
            for record in inventory_records
            if _matches_bom_entry(record, entry, bound_pn)
        ]
        result.append(
            BomSearchRowUiModel(
                entry=entry,
                matched_results=_group_records(matched),
                is_bound=bound_pn is not None,
                is_persistent_binding=persistent_pn is not None,
            )
        )
    return result


class SearchViewModel(ViewModel):
    def __init__(
        self,
        inventory_repository: InventoryRepositoryImpl,
        user_preferences_repository: UserPreferencesRepository,
        lcsc_catalog_repository: LcscCatalogRepositoryImpl,
        thread_pool: Optional[QThreadPool] = None,
    ) -> None:
        super().__init__(thread_pool)
        self._inventory_repository = inventory_repository
        self._preferences = user_preferences_repository
        self._catalog = lcsc_catalog_repository

        self._mode = SearchMode.MANUAL
        self._query = ""
        self._current_page = 1
        self._parsed_bom_document: Optional[ParsedBomDocument] = None
        self._bom_filter = BomMatchFilter.ALL
        self._temporary_bom_bindings: dict[str, str] = {}
        self._ignored_bom_entry_keys: set[str] = set()
        self._bom_error: Optional[str] = None
        self._is_parsing_bom = False

        self._inventory_repository.changed.connect(self._schedule_recompute)
        self._preferences.preferences_changed.connect(self._schedule_recompute)

        self._recompute()

    # ---- state assembly ----
    def _recompute(self) -> None:
        prefs = self._preferences.preferences
        records = self._inventory_repository.observe_search_inventory_records()
        persistent_bindings = prefs.bom_part_bindings

        all_results = _group_records(records)
        filtered_records = _filter_records(records, self._query)
        grouped_results = _group_records(filtered_records)
        page_count = max(1, (len(grouped_results) + PAGE_SIZE - 1) // PAGE_SIZE)
        safe_page = max(1, min(self._current_page, page_count))

        all_bom_rows = _build_bom_rows(
            inventory_records=records,
            document=self._parsed_bom_document,
            persistent_bindings=persistent_bindings,
            temporary_bindings=self._temporary_bom_bindings,
            ignored_entry_keys=self._ignored_bom_entry_keys,
        )

        # apply bom filter (consistent with bom_exporter._filtered_rows)
        if self._bom_filter is BomMatchFilter.MATCHED:
            bom_rows = [row for row in all_bom_rows if row.is_bound or bool(row.matched_results)]
        elif self._bom_filter is BomMatchFilter.UNMATCHED:
            bom_rows = [row for row in all_bom_rows if not (row.is_bound or bool(row.matched_results))]
        else:
            bom_rows = all_bom_rows

        self._state = SearchUiState(
            mode=self._mode,
            query=self._query,
            all_inventory_results=all_results,
            results=grouped_results,
            paged_results=grouped_results[: safe_page * PAGE_SIZE],
            inventory_record_count=len(records),
            current_page=safe_page,
            page_count=page_count,
            bom_file_name=self._parsed_bom_document.file_name if self._parsed_bom_document else None,
            bom_filter=self._bom_filter,
            bom_rows=bom_rows,
            all_bom_rows=all_bom_rows,
            bom_matched_count=sum(1 for row in all_bom_rows if row.is_bound or bool(row.matched_results)),
            bom_error=self._bom_error,
            is_parsing_bom=self._is_parsing_bom,
            default_location_code=prefs.default_location_code,
            locations=self._inventory_repository.observe_storage_locations(),
        )

    # ---- mode / query / paging ----
    def update_mode(self, value: SearchMode) -> None:
        self._mode = value
        self._do_recompute()

    def update_query(self, value: str) -> None:
        self._current_page = 1
        self._query = value
        self._do_recompute()

    def go_to_next_page(self) -> None:
        self._current_page += 1
        self._do_recompute()

    # ---- BOM import ----
    def start_bom_import(self) -> None:
        self._is_parsing_bom = True
        self._bom_error = None
        self._do_recompute()

    def on_bom_import_success(self, document: ParsedBomDocument) -> None:
        self._parsed_bom_document = document
        self._bom_filter = BomMatchFilter.ALL
        self._temporary_bom_bindings = {}
        self._ignored_bom_entry_keys = set()
        self._bom_error = None
        self._is_parsing_bom = False
        self._do_recompute()

    def on_bom_import_failed(self, message: str) -> None:
        self._bom_error = message
        self._is_parsing_bom = False
        self._do_recompute()

    def import_bom_file(self, file_path: str) -> None:
        self.start_bom_import()

        def _work():
            return parse_bom_file(file_path)

        def _on_done(document, error):
            if error is not None:
                self.on_bom_import_failed(str(error) or tr("search_bom_import_failed"))
                return
            self.on_bom_import_success(document)

        self._run_async(_work, _on_done)

    def update_bom_filter(self, filter_value: BomMatchFilter) -> None:
        self._bom_filter = filter_value
        self._do_recompute()

    def ignore_bom_entry(self, entry: BomSearchEntry) -> None:
        self._ignored_bom_entry_keys = self._ignored_bom_entry_keys | {_bom_entry_key(entry)}
        self._do_recompute()

    def bind_bom_entry(self, entry: BomSearchEntry, local_part_number: str) -> None:
        normalized_pn = (local_part_number or "").strip().upper()
        if not normalized_pn:
            return
        supplier_part = (entry.supplier_part or "").strip().upper()
        if supplier_part:
            self._preferences.set_bom_part_binding(supplier_part, normalized_pn)
            # preferences_changed will trigger recompute
        else:
            self._temporary_bom_bindings = dict(self._temporary_bom_bindings)
            self._temporary_bom_bindings[_bom_entry_key(entry)] = normalized_pn
        self._ignored_bom_entry_keys = self._ignored_bom_entry_keys - {_bom_entry_key(entry)}
        self._do_recompute()

    def _latest_location_code(self, base_code: str) -> Optional[str]:
        """Return the highest-numbered existing location code for ``base_code``.

        If base_code is "U" and locations U1, U3 exist, returns "U3".
        If no numbered locations exist, returns None.
        """
        locations = self._inventory_repository.observe_storage_locations()
        base_upper = base_code.upper()

        # Find all locations matching the pattern: base_code + number
        numbered_codes = []
        for loc in locations:
            code_upper = loc.code.upper()
            # Match base_code followed by digits only (e.g., U1, U2, R3)
            match = re.match(rf'^{re.escape(base_upper)}(\d+)$', code_upper)
            if match:
                numbered_codes.append(int(match.group(1)))

        if numbered_codes:
            # Return the highest-numbered existing location (most recent)
            return f"{base_upper}{max(numbered_codes)}"
        return None

    def suggested_location_code_for(self, component: ComponentDetail) -> Optional[str]:
        """Return the best warehouse code for a component based on its category.

        Mirrors InboundViewModel.suggested_location_code_for.
        This method ONLY suggests a code — it does NOT create the warehouse.
        The warehouse is created on-demand during confirm-inbound.
        """
        suggested = suggest_location_code(component.category, component.name)
        if suggested:
            locations = self._inventory_repository.observe_storage_locations()
            loc_codes = {loc.code.upper() for loc in locations}

            # Check if exact suggested code exists first (e.g., "U" or "U1")
            if suggested.upper() in loc_codes:
                return suggested

            # Get base letter (strip trailing digits from suggested, e.g. "U1" → "U")
            base_upper = suggested.upper()
            base_match = re.match(r'^([A-Za-z]+)', base_upper)
            if base_match:
                base = base_match.group(1)

                # Reuse the latest existing numbered location with this base
                latest = self._latest_location_code(base)
                if latest:
                    # Reuse existing warehouse
                    return latest

                # No location with this base exists — suggest "{base}1"
                # (NOT created here; created during confirm-inbound)
                return f"{base}1"

        prefs = self._preferences.preferences
        return prefs.default_location_code

    def lookup_bom_direct_inbound(
        self, part_number: str, on_completed: Callable[[BomDirectInboundLookupResult], None]
    ) -> None:
        normalized_pn = (part_number or "").strip().upper()
        if not normalized_pn:
            on_completed(BomDirectInboundLookupResult(error_message=tr("search_bom_direct_inbound_no_part")))
            return
        if not _is_network_available():
            message = tr("common_network_unavailable")
            on_completed(BomDirectInboundLookupResult(error_message=message))
            return

        def _work():
            component = self._catalog.lookup_by_part_number(normalized_pn)
            existing: list[ExistingStockLocation] = []
            if component is not None:
                existing = self._inventory_repository.find_existing_stock_locations(component.part_number)
            return component, existing

        def _on_done(payload_pair, error):
            if error is not None:
                on_completed(
                    BomDirectInboundLookupResult(
                        error_message=tr("search_bom_direct_inbound_not_found", normalized_pn)
                    )
                )
                return
            component, existing = payload_pair
            if component is None:
                on_completed(
                    BomDirectInboundLookupResult(
                        error_message=tr("search_bom_direct_inbound_not_found", normalized_pn)
                    )
                )
                return
            on_completed(
                BomDirectInboundLookupResult(
                    component=component,
                    existing_stock_locations=existing,
                )
            )

        self._run_async(_work, _on_done)

    def add_bom_inbound(
        self,
        component: ComponentDetail,
        quantity: int,
        location_code: str,
        on_completed: Callable[[Optional[str]], None],
    ) -> None:
        normalized_location = (location_code or "").strip().upper()
        if quantity < 0 or not normalized_location:
            on_completed(tr("search_bom_direct_inbound_invalid_input"))
            return
        from ..domain.models import InboundRecord

        def _work():
            self._inventory_repository.add_inbound(
                InboundRecord(
                    component=component,
                    quantity=quantity,
                    location_code=normalized_location,
                    source_type="BOM",
                )
            )

        def _on_done(_result, error):
            on_completed(None if error is None else (str(error) or tr("search_bom_direct_inbound_invalid_input")))

        self._run_async(_work, _on_done)

    # ---- inventory item ops (delegated, same as InventoryViewModel) ----
    def update_inventory_item_quantity(
        self, inventory_item_id: int, quantity: int, on_completed: Callable[[Optional[str]], None]
    ) -> None:
        on_completed(self._inventory_repository.update_inventory_item_quantity(inventory_item_id, quantity))

    def update_inventory_item_source(
        self, inventory_item_id: int, source_url: Optional[str], on_completed: Callable[[Optional[str]], None]
    ) -> None:
        on_completed(self._inventory_repository.update_inventory_item_source(inventory_item_id, source_url))

    def transfer_inventory_item(
        self, inventory_item_id: int, target_location_code: str, on_completed: Callable[[Optional[str]], None]
    ) -> None:
        on_completed(self._inventory_repository.transfer_inventory_item(inventory_item_id, target_location_code))

    def delete_inventory_item(
        self, inventory_item_id: int, on_completed: Callable[[Optional[str]], None]
    ) -> None:
        on_completed(self._inventory_repository.delete_inventory_item(inventory_item_id))
