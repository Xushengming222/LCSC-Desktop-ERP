"""InboundViewModel — port of feature/inbound/InboundViewModel.kt.

Drives the inbound screen: manual LCSC keyword search, QR-payload parse +
catalog lookup, and confirm-inbound. The Kotlin ``MutableStateFlow`` +
``combine`` pipeline becomes a plain ``_inbound_state`` dict that is folded
into ``InboundUiState`` on every recompute. Async work (search, lookup,
inbound) runs on the thread pool and dispatches its state mutation back to the
GUI thread via ``_run_async``.
"""
from __future__ import annotations

import locale
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QThreadPool

from ..data.catalog_repository import LcscCatalogRepositoryImpl
from ..data.inventory_repository import InventoryRepositoryImpl
from ..data.preferences import UserPreferencesRepository
from ..data.qr_parser import InboundQrPayload, parse_lcsc_qr
from ..domain.category_mapping import suggest_location_code
from ..domain.models import ComponentDetail, ExistingStockLocation, LocationCategoryProfile, StorageLocation
from ..i18n import tr
from .base import ViewModel


def _is_network_available() -> bool:
    """Best-effort connectivity probe — mirrors Android ``isNetworkAvailable``."""
    import socket

    try:
        socket.create_connection(("www.szlcsc.com", 443), timeout=2.0).close()
        return True
    except OSError:
        return False


def _upper(value: Optional[str]) -> str:
    return (value or "").strip().upper()


@dataclass
class InboundUiState:
    default_location_code: Optional[str] = None
    next_manual_inbound_part_number: str = "C01"
    locations: list[StorageLocation] = field(default_factory=list)
    location_category_profiles: list[LocationCategoryProfile] = field(default_factory=list)
    recent_manual_searches: list[str] = field(default_factory=list)
    manual_search_results: list[ComponentDetail] = field(default_factory=list)
    is_searching_manual: bool = False
    manual_search_error: Optional[str] = None
    parsed_payload: Optional[InboundQrPayload] = None
    component_detail: Optional[ComponentDetail] = None
    is_loading_component: bool = False
    component_lookup_error: Optional[str] = None
    last_raw_text: Optional[str] = None
    parse_error: Optional[str] = None
    existing_stock_by_part_number: dict[str, list[ExistingStockLocation]] = field(default_factory=dict)


class InboundViewModel(ViewModel):
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

        self._inbound_state: dict = {
            "next_manual_inbound_part_number": "C01",
            "manual_search_results": [],
            "is_searching_manual": False,
            "manual_search_error": None,
            "parsed_payload": None,
            "component_detail": None,
            "is_loading_component": False,
            "component_lookup_error": None,
            "last_raw_text": None,
            "parse_error": None,
            "existing_stock_by_part_number": {},
        }

        self._inventory_repository.changed.connect(self._schedule_recompute)
        self._preferences.preferences_changed.connect(self._schedule_recompute)

        # init { bootstrapDefaults(); refreshMissingLocationCategoryProfiles(); refreshNextManual... }
        def _init():
            self._inventory_repository.bootstrap_defaults()
            self._inventory_repository.refresh_missing_location_category_profiles()
            try:
                return self._inventory_repository.get_next_manual_inbound_part_number()
            except Exception:  # noqa: BLE001
                return None

        def _on_init(next_pn, error):
            if error is None and next_pn:
                self._inbound_state["next_manual_inbound_part_number"] = next_pn
            self._schedule_recompute()

        self._run_async(_init, _on_init)
        self._recompute()

    # ---- state assembly ----
    def _recompute(self) -> None:
        prefs = self._preferences.preferences
        s = self._inbound_state
        self._state = InboundUiState(
            default_location_code=prefs.default_location_code,
            next_manual_inbound_part_number=s["next_manual_inbound_part_number"],
            locations=self._inventory_repository.observe_storage_locations(),
            location_category_profiles=self._inventory_repository.observe_location_category_profiles(),
            recent_manual_searches=prefs.recent_manual_searches,
            manual_search_results=s["manual_search_results"],
            is_searching_manual=s["is_searching_manual"],
            manual_search_error=s["manual_search_error"],
            parsed_payload=s["parsed_payload"],
            component_detail=s["component_detail"],
            is_loading_component=s["is_loading_component"],
            component_lookup_error=s["component_lookup_error"],
            last_raw_text=s["last_raw_text"],
            parse_error=s["parse_error"],
            existing_stock_by_part_number=dict(s["existing_stock_by_part_number"]),
        )

    # ---- manual search ----
    def search_manual(self, keyword: str) -> None:
        normalized = (keyword or "").strip()
        if not normalized:
            self._inbound_state.update(
                manual_search_results=[],
                is_searching_manual=False,
                manual_search_error=None,
            )
            self._do_recompute()
            return

        if not _is_network_available():
            message = tr("common_network_unavailable")
            self._inbound_state.update(
                manual_search_results=[],
                is_searching_manual=False,
                manual_search_error=message,
            )
            self._do_recompute()
            return

        self._inbound_state.update(is_searching_manual=True, manual_search_error=None)
        self._do_recompute()

        def _work():
            self._preferences.add_recent_manual_search(normalized)
            results = self._catalog.search_by_keyword(normalized)
            existing = {}
            for component in results:
                pn = component.part_number
                if pn and pn not in existing:
                    existing[pn] = self._inventory_repository.find_existing_stock_locations(pn)
            # sort: items with existing stock first
            sorted_results = sorted(
                results,
                key=lambda c: (not existing.get(c.part_number)),
                reverse=False,
            )
            # stable sort preserves order within groups; we want stock-first so invert
            sorted_results = sorted(
                results,
                key=lambda c: 0 if existing.get(c.part_number) else 1,
            )
            return sorted_results, existing

        def _on_done(payload, error):
            if error is not None:
                self._inbound_state.update(
                    manual_search_results=[],
                    is_searching_manual=False,
                    manual_search_error=tr("inbound_manual_empty"),
                )
            else:
                results, existing = payload
                self._inbound_state.update(
                    manual_search_results=results,
                    is_searching_manual=False,
                    manual_search_error=tr("inbound_manual_empty") if not results else None,
                    existing_stock_by_part_number=existing,
                )
            self._do_recompute()

        self._run_async(_work, _on_done)

    def refresh_existing_stock(self, part_number: str) -> None:
        normalized = _upper(part_number)
        if not normalized:
            existing = dict(self._inbound_state["existing_stock_by_part_number"])
            existing.pop(part_number, None)
            self._inbound_state["existing_stock_by_part_number"] = existing
            self._do_recompute()
            return

        def _work():
            return self._inventory_repository.find_existing_stock_locations(normalized)

        def _on_done(result, error):
            if error is not None:
                return
            existing = dict(self._inbound_state["existing_stock_by_part_number"])
            existing[normalized] = result or []
            self._inbound_state["existing_stock_by_part_number"] = existing
            self._do_recompute()

        self._run_async(_work, _on_done)

    def refresh_next_manual_inbound_part_number(self) -> None:
        def _work():
            return self._inventory_repository.get_next_manual_inbound_part_number()

        def _on_done(result, error):
            if error is None and result:
                self._inbound_state["next_manual_inbound_part_number"] = result
                self._do_recompute()

        self._run_async(_work, _on_done)

    # ---- QR scan ----
    def on_qr_scanned(self, raw_text: str) -> None:
        current = self._inbound_state
        if (
            current["last_raw_text"] == raw_text
            and (current["is_loading_component"] or current["parsed_payload"] is not None)
        ):
            return

        payload = parse_lcsc_qr(raw_text)
        if payload is None:
            self._inbound_state.update(
                parsed_payload=None,
                component_detail=None,
                is_loading_component=False,
                component_lookup_error=None,
                last_raw_text=raw_text,
                parse_error=tr("inbound_scan_invalid_qr"),
            )
            self._do_recompute()
            return

        if not _is_network_available():
            message = tr("common_network_unavailable")
            self._inbound_state.update(
                parsed_payload=payload,
                component_detail=None,
                is_loading_component=False,
                component_lookup_error=message,
                last_raw_text=raw_text,
                parse_error=None,
            )
            self._do_recompute()
            return

        self._inbound_state.update(
            parsed_payload=payload,
            component_detail=None,
            is_loading_component=True,
            component_lookup_error=None,
            last_raw_text=raw_text,
            parse_error=None,
        )
        self._do_recompute()

        part_number = payload.part_number

        def _work():
            component = self._catalog.lookup_by_part_number(part_number)
            existing: list[ExistingStockLocation] = []
            if component is not None:
                existing = self._inventory_repository.find_existing_stock_locations(component.part_number)
            return component, existing

        def _on_done(payload_pair, error):
            if error is not None:
                self._inbound_state.update(
                    component_detail=None,
                    is_loading_component=False,
                    component_lookup_error=tr("inbound_scan_component_not_found", part_number),
                    existing_stock_by_part_number={},
                )
                self._do_recompute()
                return
            component, existing = payload_pair
            if component is None:
                self._inbound_state.update(
                    component_detail=None,
                    is_loading_component=False,
                    component_lookup_error=tr("inbound_scan_component_not_found", part_number),
                    existing_stock_by_part_number={},
                )
            else:
                self._inbound_state.update(
                    component_detail=component,
                    is_loading_component=False,
                    component_lookup_error=None,
                    existing_stock_by_part_number={component.part_number: existing},
                )
            self._do_recompute()

        self._run_async(_work, _on_done)

    def clear_scan_result(self) -> None:
        self._inbound_state.update(
            parsed_payload=None,
            component_detail=None,
            is_loading_component=False,
            component_lookup_error=None,
            last_raw_text=None,
            parse_error=None,
            existing_stock_by_part_number={},
        )
        self._do_recompute()

    # ---- suggested location by category ----
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

        This method ONLY suggests a code — it does NOT create the warehouse.
        The warehouse is created on-demand when the user actually confirms
        the inbound (via ``add_inbound`` → ``_find_or_create_location``).

        1. If the component already has existing stock, reuse that location.
        2. Otherwise, suggest a location based on the PCB reference designator
           mapping (e.g. resistors → ``R``).
        3. If the exact suggested code exists as a real storage location, use it.
        4. If any numbered location with the same base letter exists (e.g. U1),
           reuse the latest one (highest number).
        5. If no location with this base exists, suggest ``{base}1`` (created
           later during confirm-inbound).
        6. Fall back to the user's global ``default_location_code``.
        """
        existing = (self._inbound_state["existing_stock_by_part_number"] or {}).get(
            component.part_number, []
        )
        if existing:
            return existing[0].location_code

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

    # ---- confirm inbound ----
    def confirm_inbound(
        self,
        component: ComponentDetail,
        quantity: int,
        location_code: str,
        source_type: str,
        raw_payload: Optional[str] = None,
        on_completed: Optional[Callable[[Optional[str]], None]] = None,
    ) -> None:
        normalized_location = _upper(location_code)
        if quantity < 0 or not normalized_location:
            if on_completed:
                on_completed(tr("inbound_invalid_input"))
            return

        from ..domain.models import InboundRecord

        def _work():
            self._inventory_repository.add_inbound(
                InboundRecord(
                    component=component,
                    quantity=quantity,
                    location_code=normalized_location,
                    source_type=source_type,
                    raw_payload=raw_payload,
                )
            )
            existing = self._inventory_repository.find_existing_stock_locations(component.part_number)
            return existing

        def _on_done(existing, error):
            if error is not None:
                msg = str(error) or tr("inbound_invalid_input")
                if on_completed:
                    on_completed(msg)
                return
            stock_map = dict(self._inbound_state["existing_stock_by_part_number"])
            stock_map[component.part_number] = existing or []
            self._inbound_state["existing_stock_by_part_number"] = stock_map
            if source_type == "MANUAL_INPUT":
                # refresh next manual part number async
                self.refresh_next_manual_inbound_part_number()
            else:
                self._do_recompute()
            if on_completed:
                on_completed(None)

        self._run_async(_work, _on_done)
