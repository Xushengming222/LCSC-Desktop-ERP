"""Dependency-injection container — port of core/AppContainer.kt.

Constructs the database connection, DAOs, repositories, enrichment manager,
backup manager and the five ViewModels, wiring Qt Signals between them. A
single ``AppContainer`` instance is created at process start (see ``main.py``)
and owns the lifetime of every component.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThreadPool

from .data.backup_manager import InventoryBackupManager
from .data.catalog_repository import LcscCatalogRepositoryImpl
from .data.enrichment_manager import ComponentEnrichmentManager
from .data.image_store import ComponentImageStore
from .data.inventory_repository import InventoryRepositoryImpl
from .data.preferences import UserPreferencesRepository
from .data.remote_data_source import LcscCatalogRemoteDataSource
from .db.database import open_connection
from .db.dao import (
    ComponentDao,
    DashboardDao,
    InventoryItemDao,
    InventoryTransactionDao,
    StorageLocationDao,
)
from .i18n import translator
from .viewmodels.home_viewmodel import HomeViewModel
from .viewmodels.inbound_viewmodel import InboundViewModel
from .viewmodels.inventory_viewmodel import InventoryViewModel
from .viewmodels.search_viewmodel import SearchViewModel
from .viewmodels.settings_viewmodel import SettingsViewModel

APP_VERSION_NAME = "desktop-1.0.0"
APP_VERSION_CODE = "1"


class AppContainer:
    def __init__(self, data_dir: str | Path, project_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._project_dir = Path(project_dir) if project_dir else self._data_dir.parent

        # Core infrastructure
        self._thread_pool = QThreadPool.globalInstance()
        self._conn = open_connection(self._data_dir / "lcsc_erp.db")

        # DAOs
        self._component_dao = ComponentDao(self._conn)
        self._storage_location_dao = StorageLocationDao(self._conn)
        self._inventory_item_dao = InventoryItemDao(self._conn)
        self._inventory_transaction_dao = InventoryTransactionDao(self._conn)
        self._dashboard_dao = DashboardDao(self._conn)

        # Image store + enrichment
        self._image_store = ComponentImageStore(self._data_dir / "images")
        self._remote_data_source = LcscCatalogRemoteDataSource()
        self._catalog_repository = LcscCatalogRepositoryImpl(self._remote_data_source)

        # Preferences (JSON-backed)
        config_ini_path = self._project_dir / "config.ini"
        self._user_preferences = UserPreferencesRepository(
            self._data_dir / "preferences.json",
            config_ini_path=config_ini_path,
        )

        # Enrichment manager needs the catalog lookup + image store.
        self._enrichment_manager = ComponentEnrichmentManager(
            component_dao=self._component_dao,
            catalog_lookup=self._catalog_repository.lookup_by_part_number,
            image_store=self._image_store,
        )

        # Inventory repository wires the DAOs + image store + enrichment scheduler.
        self._inventory_repository = InventoryRepositoryImpl(
            conn=self._conn,
            component_dao=self._component_dao,
            dashboard_dao=self._dashboard_dao,
            storage_location_dao=self._storage_location_dao,
            inventory_item_dao=self._inventory_item_dao,
            inventory_transaction_dao=self._inventory_transaction_dao,
            component_image_store=self._image_store,
            enrichment_scheduler=self._enrichment_manager.schedule,
            tr=lambda key, *args: translator().tr(key, *args),
        )

        # Backup manager
        self._backup_manager = InventoryBackupManager(
            storage_location_dao=self._storage_location_dao,
            component_dao=self._component_dao,
            inventory_item_dao=self._inventory_item_dao,
            inventory_transaction_dao=self._inventory_transaction_dao,
            image_store=self._image_store,
            enrichment_manager=self._enrichment_manager,
            user_preferences_repository=self._user_preferences,
            app_version_name=APP_VERSION_NAME,
            app_version_code=APP_VERSION_CODE,
            run_in_transaction=self._run_in_transaction,
        )

        # Apply saved language to the translator at startup.
        translator().set_language(self._user_preferences.preferences.app_language_tag)

        # View models (constructed last; they subscribe to repository signals)
        self.home_view_model = HomeViewModel(
            inventory_repository=self._inventory_repository,
            user_preferences_repository=self._user_preferences,
            thread_pool=self._thread_pool,
        )
        self.inbound_view_model = InboundViewModel(
            inventory_repository=self._inventory_repository,
            user_preferences_repository=self._user_preferences,
            lcsc_catalog_repository=self._catalog_repository,
            thread_pool=self._thread_pool,
        )
        self.inventory_view_model = InventoryViewModel(
            inventory_repository=self._inventory_repository,
            lcsc_catalog_repository=self._catalog_repository,
            user_preferences_repository=self._user_preferences,
            thread_pool=self._thread_pool,
        )
        self.search_view_model = SearchViewModel(
            inventory_repository=self._inventory_repository,
            user_preferences_repository=self._user_preferences,
            lcsc_catalog_repository=self._catalog_repository,
            thread_pool=self._thread_pool,
        )
        self.settings_view_model = SettingsViewModel(
            user_preferences_repository=self._user_preferences,
            inventory_backup_manager=self._backup_manager,
            translator=translator(),
            thread_pool=self._thread_pool,
        )

    # ---- transaction helper for backup restore ----
    def _run_in_transaction(self, fn) -> None:
        self._conn.execute("BEGIN")
        try:
            fn()
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ---- shutdown ----
    def close(self) -> None:
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass
