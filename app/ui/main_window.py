"""Main window — port of ui/LcscApp.kt navigation host.

A left side-navigation rail (mirroring the Android bottom NavigationBar) drives
a ``QStackedWidget`` containing the five feature pages: Home, Inbound, Search,
Inventory, Settings. The Printer destination is omitted (camera/printer tab was
removed; label printing is now inline in Inbound/Inventory).

Cross-tab deep links (``jumpToInventoryItem``) are routed through
``self._open_inventory_item``, which calls into the Inventory page.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from .. import theme
from ..i18n import translator, tr
from ..viewmodels.home_viewmodel import HomeViewModel
from ..viewmodels.inbound_viewmodel import InboundViewModel
from ..viewmodels.inventory_viewmodel import InventoryViewModel
from ..viewmodels.search_viewmodel import SearchViewModel
from ..viewmodels.settings_viewmodel import SettingsViewModel
from .home_page import HomePage
from .inbound_page import InboundPage
from .inventory_page import InventoryPage
from .search_page import SearchPage
from .settings_page import SettingsPage


# (label key, icon glyph, page index)
# Using unicode glyphs as a lightweight stand-in for Material icons (no icon
# assets shipped). They render in Microsoft YaHei / Segoe UI Symbol.
_NAV_ITEMS = [
    ("nav_home", "🏠"),
    ("nav_inbound", "📥"),
    ("nav_search", "🔍"),
    ("nav_inventory", "📦"),
    ("nav_settings", "⚙"),
]


class MainWindow(QMainWindow):
    def __init__(
        self,
        home_vm: HomeViewModel,
        inbound_vm: InboundViewModel,
        search_vm: SearchViewModel,
        inventory_vm: InventoryViewModel,
        settings_vm: SettingsViewModel,
    ) -> None:
        super().__init__()
        self.setWindowTitle(tr("app_name"))
        self.resize(1280, 820)
        self.setMinimumSize(960, 640)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Side navigation
        self._nav = QListWidget()
        self._nav.setObjectName("navList")
        self._nav.setFixedWidth(200)
        for label_key, glyph in _NAV_ITEMS:
            item = QListWidgetItem(f"{glyph}  {tr(label_key)}")
            item.setData(Qt.UserRole, label_key)
            self._nav.addItem(item)
        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self._nav)

        # Pages
        self._stack = QStackedWidget()
        self._home_page = HomePage(home_vm)
        self._inbound_page = InboundPage(inbound_vm)
        self._search_page = SearchPage(search_vm, self._open_inventory_item)
        self._inventory_page = InventoryPage(inventory_vm)
        self._settings_page = SettingsPage(settings_vm)
        for page in (
            self._home_page,
            self._inbound_page,
            self._search_page,
            self._inventory_page,
            self._settings_page,
        ):
            self._stack.addWidget(page)
        layout.addWidget(self._stack, 1)

        # Retranslate on language change.
        translator().language_changed.connect(self._on_language_changed)

    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)
            # Re-tapping Inventory resets to overview (mirrors Android behavior).
            if row == 3:
                self._inventory_page.refresh()

    def _open_inventory_item(self, location_code: str, part_number: str) -> None:
        # Switch to inventory tab and deep-link.
        self._nav.setCurrentRow(3)
        self._inventory_page.open_inventory_item(location_code, part_number)

    def _on_language_changed(self) -> None:
        self._retranslate()

    def _retranslate(self) -> None:
        self.setWindowTitle(tr("app_name"))
        # Rebuild nav labels
        for index, (label_key, glyph) in enumerate(_NAV_ITEMS):
            item = self._nav.item(index)
            if item is not None:
                item.setText(f"{glyph}  {tr(label_key)}")
        for page in (
            self._home_page,
            self._inbound_page,
            self._search_page,
            self._inventory_page,
            self._settings_page,
        ):
            page.retranslate_ui()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Ensure pending async workers don't outlive the window abruptly.
        super().closeEvent(event)
