"""Component enrichment manager — port of data/repository/ComponentEnrichmentManager.kt.

Schedules background enrichment of component records by looking the part number
up on LCSC and updating the local DB (mpn, name, brand, package, specs, image).
Execution is serialized (one at a time) with a 1-second delay between items,
mirroring the Kotlin ``limitedParallelism(1)`` + ``delay(1000)`` pattern.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ..db.dao import ComponentDao
from ..domain.models import ComponentDetail

_LOG = logging.getLogger(__name__)


@dataclass
class ComponentEnrichmentState:
    is_running: bool = False
    total_count: int = 0
    completed_count: int = 0
    active_count: int = 0

    @property
    def progress(self) -> float:
        return self.completed_count / self.total_count if self.total_count > 0 else 0.0


class ComponentEnrichmentManager(QObject):
    enriched = Signal(int)  # component id
    state_changed = Signal()

    def __init__(
        self,
        component_dao: ComponentDao,
        catalog_lookup,  # Callable[[str], ComponentDetail | None]
        image_store,  # ComponentImageStore
    ) -> None:
        super().__init__()
        self._component_dao = component_dao
        self._catalog_lookup = catalog_lookup
        self._image_store = image_store
        self._running_part_numbers: set[str] = set()
        self._running_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._enrich_lock = threading.Lock()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._state = ComponentEnrichmentState()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    @property
    def state(self) -> ComponentEnrichmentState:
        with self._state_lock:
            return ComponentEnrichmentState(
                is_running=self._state.is_running,
                total_count=self._state.total_count,
                completed_count=self._state.completed_count,
                active_count=self._state.active_count,
            )

    def schedule(self, part_number: str) -> None:
        normalized = part_number.strip().upper()
        if not normalized:
            return
        with self._running_lock:
            if normalized in self._running_part_numbers:
                return
            self._running_part_numbers.add(normalized)
        self._begin_session_if_idle()
        with self._state_lock:
            reset_session = not self._state.is_running
            if reset_session:
                self._state = ComponentEnrichmentState(is_running=True)
            base = self._state
            self._state = ComponentEnrichmentState(
                is_running=True,
                total_count=base.total_count + 1,
                completed_count=base.completed_count,
                active_count=base.active_count + 1,
            )
        self.state_changed.emit()
        self._queue.put(normalized)

    def schedule_all(self, part_numbers) -> None:
        for pn in part_numbers:
            self.schedule(pn)

    def enrich_now(self, part_numbers) -> None:
        """Synchronously enrich the given part numbers (used by backup export)."""
        seen: set[str] = set()
        for raw in part_numbers:
            normalized = raw.strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            with self._enrich_lock:
                try:
                    self._enrich(normalized)
                except Exception as error:  # noqa: BLE001
                    _LOG.warning("enrichNow failed partNumber=%s err=%s", normalized, error)
                time.sleep(1.0)

    # ---- internal ----
    def _begin_session_if_idle(self) -> None:
        # session reset is handled inline in schedule() via reset_session check
        pass

    def _run_loop(self) -> None:
        while True:
            part_number = self._queue.get()
            if part_number is None:
                continue
            try:
                with self._enrich_lock:
                    try:
                        self._enrich(part_number)
                    except Exception as error:  # noqa: BLE001
                        _LOG.warning("enrich failed partNumber=%s err=%s", part_number, error)
                    time.sleep(1.0)
            finally:
                with self._running_lock:
                    self._running_part_numbers.discard(part_number)
                self._complete_one()

    def _complete_one(self) -> None:
        with self._state_lock:
            current = self._state
            next_active = max(current.active_count - 1, 0)
            next_completed = min(current.completed_count + 1, current.total_count)
            if next_active == 0:
                self._state = ComponentEnrichmentState(
                    is_running=False,
                    active_count=0,
                    completed_count=next_completed,
                )
            else:
                self._state = ComponentEnrichmentState(
                    is_running=True,
                    total_count=current.total_count,
                    completed_count=next_completed,
                    active_count=next_active,
                )
        self.state_changed.emit()

    def _enrich(self, part_number: str) -> None:
        existing = self._component_dao.find_by_part_number(part_number)
        if existing is None:
            return
        detail: ComponentDetail | None = self._catalog_lookup(part_number)
        if detail is None:
            return
        local_image_path = self._image_store.persist_image(
            part_number=part_number, image_url=detail.image_url
        )
        import json
        spec_json = (
            json.dumps(detail.specifications, ensure_ascii=False)
            if detail.specifications
            else None
        )
        from ..db.entities import ComponentEntity
        updated = ComponentEntity(
            id=existing.id,
            part_number=existing.part_number,
            mpn=detail.mpn,
            name=detail.name,
            brand=detail.brand,
            package_name=detail.package_name,
            category=detail.category,
            spec_json=spec_json,
            description=detail.description,
            source_url=detail.product_url,
            image_local_path=local_image_path or existing.image_local_path,
            image_url=detail.image_url,
            updated_at=int(time.time() * 1000),
        )
        self._component_dao.update(updated)
        self.enriched.emit(existing.id)
