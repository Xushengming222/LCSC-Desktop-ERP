"""Home page — port of feature/home/HomeScreen.kt.

Dashboard with summary stat cards.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..i18n import tr
from ..viewmodels.home_viewmodel import HomeViewModel
from .widgets import Card, Heading, StatCard, Subtitle


class HomePage(QWidget):
    def __init__(self, view_model: HomeViewModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._vm = view_model

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # Spacer on top to push everything to center
        root.addStretch(1)

        self._heading = Heading(tr("home_title"))
        # Center the heading
        self._heading.setAlignment(Qt.AlignCenter) if hasattr(self._heading, "setAlignment") else None
        root.addWidget(self._heading, 0, Qt.AlignHCenter)

        # Stat grid — centered with a max width via outer container
        center_row = QHBoxLayout()
        center_row.addStretch(1)
        self._stat_grid = QGridLayout()
        self._stat_grid.setSpacing(14)
        center_row.addLayout(self._stat_grid, 2)
        center_row.addStretch(1)
        root.addLayout(center_row, 0)

        self._stat_component = StatCard(tr("summary_component_count"))
        self._stat_location = StatCard(tr("summary_location_count"))
        self._stat_inventory = StatCard(tr("summary_inventory_count"))
        self._stat_quantity = StatCard(tr("summary_total_quantity"))
        self._stat_transaction = StatCard(tr("summary_transaction_count"))
        self._stats = [
            self._stat_component,
            self._stat_location,
            self._stat_inventory,
            self._stat_quantity,
            self._stat_transaction,
        ]
        for index, card in enumerate(self._stats):
            self._stat_grid.addWidget(card, index // 3, index % 3)

        # Bottom spacer to complete centering
        root.addStretch(2)

        self._vm.ui_state_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        summary = state.summary
        self._stat_component.set_value(str(summary.component_count))
        self._stat_location.set_value(str(summary.location_count))
        self._stat_inventory.set_value(str(summary.inventory_count))
        self._stat_quantity.set_value(str(summary.total_quantity))
        self._stat_transaction.set_value(str(summary.transaction_count))

    def retranslate_ui(self) -> None:
        self._heading.set_title(tr("home_title"))
        self._stat_component.set_label(tr("summary_component_count"))
        self._stat_location.set_label(tr("summary_location_count"))
        self._stat_inventory.set_label(tr("summary_inventory_count"))
        self._stat_quantity.set_label(tr("summary_total_quantity"))
        self._stat_transaction.set_label(tr("summary_transaction_count"))
        self.refresh()
