"""HomeViewModel — port of feature/home/HomeViewModel.kt.

Combines the dashboard summary, storage locations and the default location
preference into a single ``HomeUiState``. Mirrors the Kotlin ``combine`` +
``stateIn`` pipeline: any of the three sources emitting triggers a recompute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QThreadPool

from ..data.inventory_repository import InventoryRepositoryImpl
from ..data.preferences import UserPreferencesRepository
from ..domain.models import DashboardSummary, StorageLocation
from .base import ViewModel


@dataclass
class HomeUiState:
    summary: DashboardSummary = field(default_factory=DashboardSummary)
    locations: list[StorageLocation] = field(default_factory=list)
    default_location_code: Optional[str] = None


class HomeViewModel(ViewModel):
    def __init__(
        self,
        inventory_repository: InventoryRepositoryImpl,
        user_preferences_repository: UserPreferencesRepository,
        thread_pool: Optional[QThreadPool] = None,
    ) -> None:
        super().__init__(thread_pool)
        self._inventory_repository = inventory_repository
        self._preferences = user_preferences_repository

        # Wire sources -> recompute (mirrors combine(...).stateIn)
        self._inventory_repository.changed.connect(self._schedule_recompute)
        self._preferences.preferences_changed.connect(self._schedule_recompute)

        # init { bootstrapDefaults() } — runs on first event-loop tick
        self._run_async(
            lambda: self._inventory_repository.bootstrap_defaults(),
            lambda _result, _error: self._schedule_recompute(),
        )

        self._recompute()

    def _recompute(self) -> None:
        prefs = self._preferences.preferences
        self._state = HomeUiState(
            summary=self._inventory_repository.observe_dashboard_summary(),
            locations=self._inventory_repository.observe_storage_locations(),
            default_location_code=prefs.default_location_code,
        )
