"""Search page — port of feature/search/SearchScreen.kt.

Two modes:
* Manual: keyword search over local inventory records (grouped by part
  number + mpn), with paging.
* BOM: import a ``.xlsx`` BOM, match each row against local inventory, bind
  unmatched rows to a local part, or direct-inbound a row from LCSC.

Clicking a result's "查看物料" deep-links into the Inventory tab via the
``view_inventory_item`` callback (mirrors ``onViewInventoryItem``).
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pathlib import Path

from .. import theme
from ..data.bom_exporter import build_bom_export_file_name, export_bom_rows_to_path
from ..domain.bom import BomMatchFilter, BomSearchEntry, BomSearchRowUiModel, SearchMode, SearchResultUiModel
from ..i18n import tr
from ..viewmodels.search_viewmodel import SearchViewModel
from .widgets import Card, Chip, ComponentDetailDialog, ComponentThumbnail, Heading, InfoRow, OutlineButton, SuccessButton, TextButton


class SearchResultCard(Card):
    """A grouped local-inventory search result."""

    view_item = Signal(str, str)  # location_code, part_number
    view_detail = Signal(object)  # SearchInventoryRecord

    def __init__(self, model: SearchResultUiModel, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        layout = QHBoxLayout()
        layout.setSpacing(12)
        self.thumbnail = ComponentThumbnail(72)
        self.thumbnail.set_image_info(
            model.image_local_path,
            image_url=model.image_url,
            part_number=model.part_number,
        )
        layout.addWidget(self.thumbnail)

        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel(model.part_number)
        title.setObjectName("h3")
        info.addWidget(title)
        if model.name:
            info.addWidget(QLabel(model.name))
        meta = QHBoxLayout()
        meta.setSpacing(10)
        if model.brand:
            meta.addWidget(QLabel(tr("search_brand", model.brand)))
        if model.package_name:
            meta.addWidget(QLabel(tr("search_package", model.package_name)))
        meta.addStretch()
        info.addLayout(meta)
        info.addWidget(QLabel(tr("search_total_quantity", str(model.total_quantity))))
        for loc in model.locations:
            row = QHBoxLayout()
            row.setSpacing(6)
            color = loc.color_hex or theme.SURFACE_VARIANT
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color};")
            row.addWidget(dot)
            label = f"{loc.display_name or loc.code} ({loc.code}) · {tr('search_location_quantity', str(loc.quantity))}"
            link = TextButton(label)
            link.clicked.connect(lambda _checked=False, lc=loc.code, pn=model.part_number: self.view_item.emit(lc, pn))
            row.addWidget(link)
            row.addStretch()
            info.addLayout(row)
        # Primary "view details" button at the bottom
        actions_row = QHBoxLayout()
        actions_row.addStretch()
        detail_btn = TextButton(tr("common_edit"))
        detail_btn.setText(tr("search_view_details"))
        detail_btn.clicked.connect(self._emit_detail)
        actions_row.addWidget(detail_btn)
        info.addLayout(actions_row)
        layout.addLayout(info, 1)
        self.body.addLayout(layout)

    def _emit_detail(self) -> None:
        # Use the first record if available; otherwise synthesize from the model.
        if self.model.records:
            self.view_detail.emit(self.model.records[0])
            return
        # Build a synthetic record — enough for the detail dialog.
        from ..domain.models import SearchInventoryRecord
        rec = SearchInventoryRecord(
            inventory_item_id=0,
            component_id=0,
            part_number=self.model.part_number,
            mpn=self.model.mpn,
            name=self.model.name,
            brand=self.model.brand,
            package_name=self.model.package_name,
            category=self.model.category,
            description=self.model.description,
            source_url=self.model.source_url,
            specifications=self.model.specifications,
            image_local_path=self.model.image_local_path,
            image_url=self.model.image_url,
            quantity=self.model.total_quantity,
            location_id=0,
            location_code=self.model.locations[0].code if self.model.locations else "",
            location_display_name=(
                self.model.locations[0].display_name if self.model.locations else None
            ),
            location_color_hex=(
                self.model.locations[0].color_hex if self.model.locations else None
            ),
        )
        self.view_detail.emit(rec)


class BomRowCard(Card):
    """A single BOM row with its matched local results + actions."""

    direct_inbound = Signal(object)  # BomSearchEntry
    bind_entry = Signal(object)  # BomSearchEntry
    ignore_entry = Signal(object)  # BomSearchEntry
    view_item = Signal(str, str)

    def __init__(self, row: BomSearchRowUiModel, parent=None) -> None:
        super().__init__(parent)
        self.row = row
        entry = row.entry
        layout = QVBoxLayout()
        layout.setSpacing(6)
        title = QLabel(tr("search_bom_row_title", entry.row_number, entry.quantity or 0))
        title.setObjectName("h3")
        layout.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(10)
        if entry.supplier_part:
            meta.addWidget(QLabel(f"{tr('search_bom_supplier_part')}: {entry.supplier_part}"))
        if entry.manufacturer_part:
            meta.addWidget(QLabel(f"{tr('search_bom_manufacturer_part')}: {entry.manufacturer_part}"))
        if entry.footprint:
            meta.addWidget(QLabel(f"{tr('search_bom_footprint')}: {entry.footprint}"))
        if entry.value:
            meta.addWidget(QLabel(f"{tr('search_bom_value')}: {entry.value}"))
        meta.addStretch()
        layout.addLayout(meta)

        if row.matched_results:
            layout.addWidget(QLabel(tr("search_bom_match_title", len(row.matched_results))))
            for result in row.matched_results:
                for loc in result.locations:
                    link = TextButton(
                        f"{loc.display_name or loc.code} ({loc.code}) · "
                        f"{result.part_number} · {tr('search_location_quantity', str(loc.quantity))}"
                    )
                    link.clicked.connect(
                        lambda _checked=False, lc=loc.code, pn=result.part_number: self.view_item.emit(lc, pn)
                    )
                    layout.addWidget(link)
        else:
            layout.addWidget(QLabel(tr("search_bom_unmatched")))

        actions = QHBoxLayout()
        actions.setSpacing(8)
        direct = SuccessButton(tr("search_bom_direct_inbound"))
        direct.clicked.connect(lambda: self.direct_inbound.emit(entry))
        actions.addWidget(direct)
        bind = OutlineButton(tr("search_bom_bind_match"))
        bind.clicked.connect(lambda: self.bind_entry.emit(entry))
        actions.addWidget(bind)
        ignore = TextButton(tr("search_bom_ignore"))
        ignore.clicked.connect(lambda: self.ignore_entry.emit(entry))
        actions.addWidget(ignore)
        actions.addStretch()
        layout.addLayout(actions)
        self.body.addLayout(layout)


class BindDialog(QDialog):
    """Pick a local part number to bind a BOM entry to."""

    def __init__(self, all_results: list[SearchResultUiModel], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("search_bom_bind_dialog_title"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("search_bom_bind_dialog_subtitle_fallback")))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("search_bom_bind_search_label"))
        self._filter.textChanged.connect(self._filter_results)
        layout.addWidget(self._filter)
        self._combo = QComboBox()
        for result in all_results:
            label = f"{result.part_number}"
            if result.name:
                label += f" · {result.name}"
            self._combo.addItem(label, result.part_number)
        layout.addWidget(self._combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("search_bom_bind_confirm"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("common_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._all_results = all_results

    def _filter_results(self, text: str) -> None:
        needle = text.strip().lower()
        self._combo.clear()
        for result in self._all_results:
            label = f"{result.part_number}"
            if result.name:
                label += f" · {result.name}"
            if not needle or needle in label.lower():
                self._combo.addItem(label, result.part_number)

    def selected_part_number(self) -> Optional[str]:
        return self._combo.currentData() or None


class DirectInboundDialog(QDialog):
    def __init__(self, component, locations, default_location_code, existing_stock, parent=None) -> None:
        super().__init__(parent)
        self.component = component
        self.setWindowTitle(tr("search_bom_direct_inbound"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        title = QLabel(component.part_number)
        title.setObjectName("h2")
        layout.addWidget(title)
        if component.name:
            layout.addWidget(QLabel(component.name))

        detail = Card()
        if component.brand:
            detail.addWidget(InfoRow(tr("inbound_component_brand"), component.brand))
        if component.package_name:
            detail.addWidget(InfoRow(tr("inbound_component_package"), component.package_name))
        if component.stock_quantity is not None:
            detail.addWidget(InfoRow(tr("inbound_component_stock"), str(component.stock_quantity)))
        if component.price is not None:
            detail.addWidget(InfoRow(tr("inbound_component_price"), f"¥{component.price}"))
        layout.addWidget(detail)

        form = QFormLayout()
        self._qty = QSpinBox()
        self._qty.setRange(0, 1_000_000)
        self._qty.setValue(1)
        form.addRow(tr("search_bom_direct_inbound_quantity"), self._qty)
        self._location = QComboBox()
        for loc in locations:
            label = loc.display_name or loc.code
            self._location.addItem(f"{label} ({loc.code})", loc.code)
        if default_location_code:
            # If the suggested code doesn't exist as a location yet, add it
            # as a temporary item so the user can select it. The warehouse
            # will be created during confirm-inbound.
            existing_codes = {
                self._location.itemData(i).upper()
                for i in range(self._location.count())
            }
            if default_location_code.upper() not in existing_codes:
                self._location.addItem(
                    f"{default_location_code} ({default_location_code})",
                    default_location_code,
                )
            for i in range(self._location.count()):
                data = self._location.itemData(i)
                if data and data.upper() == default_location_code.upper():
                    self._location.setCurrentIndex(i)
                    break
        form.addRow(tr("search_bom_direct_inbound_location"), self._location)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("search_bom_direct_inbound_confirm"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("common_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def quantity(self) -> int:
        return self._qty.value()

    def location_code(self) -> str:
        return self._location.currentData() or ""


class SearchPage(QWidget):
    def __init__(
        self,
        view_model: SearchViewModel,
        view_inventory_item: Callable[[str, str], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._vm = view_model
        self._view_inventory_item = view_inventory_item

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        self._heading = Heading(tr("search_title"))
        root.addWidget(self._heading)

        # Mode toggle
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._btn_manual = QPushButton(tr("search_mode_manual"))
        self._btn_manual.setCheckable(True)
        self._btn_bom = QPushButton(tr("search_mode_bom"))
        self._btn_bom.setCheckable(True)
        self._mode_group.addButton(self._btn_manual, 0)
        self._mode_group.addButton(self._btn_bom, 1)
        mode_row.addWidget(self._btn_manual)
        mode_row.addWidget(self._btn_bom)
        mode_row.addStretch()
        root.addLayout(mode_row)

        self._stack = QStackedWidget()
        self._manual_panel = self._build_manual_panel()
        self._bom_panel = self._build_bom_panel()
        self._stack.addWidget(self._manual_panel)
        self._stack.addWidget(self._bom_panel)
        root.addWidget(self._stack, 1)

        self._btn_manual.setChecked(True)
        self._stack.setCurrentIndex(0)
        self._mode_group.idToggled.connect(self._on_mode_toggled)

        self._vm.ui_state_changed.connect(self.refresh)
        self.refresh()

    def _on_mode_toggled(self, button_id: int, checked: bool) -> None:
        if checked:
            self._vm.update_mode(SearchMode.MANUAL if button_id == 0 else SearchMode.BOM)
            self._stack.setCurrentIndex(button_id)

    # ---- manual panel ----
    def _build_manual_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        self._query = QLineEdit()
        self._query.setPlaceholderText(tr("search_keyword_placeholder"))
        self._query.returnPressed.connect(self._on_query)
        search_row.addWidget(self._query, 1)
        self._search_btn = QPushButton(tr("inbound_manual_search_action"))
        self._search_btn.clicked.connect(self._on_query)
        search_row.addWidget(self._search_btn)
        layout.addLayout(search_row)

        self._summary_label = QLabel()
        self._summary_label.setObjectName("subtitle")
        layout.addWidget(self._summary_label)

        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        container = QWidget()
        self._results_layout = QVBoxLayout(container)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(10)
        self._results_layout.addStretch()
        self._results_scroll.setWidget(container)
        layout.addWidget(self._results_scroll, 1)
        return panel

    def _on_query(self) -> None:
        self._vm.update_query(self._query.text())

    # ---- BOM panel ----
    def _build_bom_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        pick_row = QHBoxLayout()
        self._pick_btn = OutlineButton(tr("search_bom_pick_file"))
        self._pick_btn.clicked.connect(self._on_pick_bom)
        pick_row.addWidget(self._pick_btn)
        self._bom_file_label = QLabel()
        self._bom_file_label.setObjectName("subtitle")
        pick_row.addWidget(self._bom_file_label, 1)
        layout.addLayout(pick_row)

        self._bom_summary = QLabel()
        self._bom_summary.setObjectName("subtitle")
        layout.addWidget(self._bom_summary)

        self._bom_error = QLabel()
        self._bom_error.setStyleSheet(f"color: {theme.ERROR};")
        layout.addWidget(self._bom_error)

        # filter row
        filter_row = QHBoxLayout()
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_all = QPushButton(tr("search_bom_filter_all"))
        self._filter_all.setCheckable(True)
        self._filter_matched = QPushButton(tr("search_bom_filter_matched"))
        self._filter_matched.setCheckable(True)
        self._filter_unmatched = QPushButton(tr("search_bom_filter_unmatched"))
        self._filter_unmatched.setCheckable(True)
        self._filter_group.addButton(self._filter_all, 0)
        self._filter_group.addButton(self._filter_matched, 1)
        self._filter_group.addButton(self._filter_unmatched, 2)
        self._filter_all.setChecked(True)
        self._filter_group.idToggled.connect(self._on_bom_filter)
        filter_row.addWidget(self._filter_all)
        filter_row.addWidget(self._filter_matched)
        filter_row.addWidget(self._filter_unmatched)
        filter_row.addStretch()
        self._export_btn = SuccessButton(tr("search_bom_export_excel"))
        self._export_btn.clicked.connect(self._on_export_bom)
        filter_row.addWidget(self._export_btn)
        layout.addLayout(filter_row)

        self._bom_scroll = QScrollArea()
        self._bom_scroll.setWidgetResizable(True)
        container = QWidget()
        self._bom_layout = QVBoxLayout(container)
        self._bom_layout.setContentsMargins(0, 0, 0, 0)
        self._bom_layout.setSpacing(10)
        self._bom_layout.addStretch()
        self._bom_scroll.setWidget(container)
        layout.addWidget(self._bom_scroll, 1)
        return panel

    def _on_pick_bom(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("search_bom_pick_file"), "", "Excel files (*.xlsx)"
        )
        if not path:
            return
        self._vm.import_bom_file(path)

    def _on_bom_filter(self, button_id: int, checked: bool) -> None:
        if not checked:
            return
        mapping = {0: BomMatchFilter.ALL, 1: BomMatchFilter.MATCHED, 2: BomMatchFilter.UNMATCHED}
        self._vm.update_bom_filter(mapping[button_id])

    def _on_export_bom(self) -> None:
        state = self._vm.ui_state
        if not state or not state.bom_file_name or not state.all_bom_rows:
            QMessageBox.information(self, tr("search_bom_export_excel"), tr("search_bom_export_empty"))
            return
        current_filter = state.bom_filter
        default_name = build_bom_export_file_name(current_filter, state.bom_file_name)
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("search_bom_export_excel"),
            default_name,
            "Excel files (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        error = export_bom_rows_to_path(
            rows=state.all_bom_rows,
            bom_filter=current_filter,
            path=path,
            source_file_name=state.bom_file_name,
        )
        if error:
            QMessageBox.warning(
                self,
                tr("search_bom_export_excel"),
                tr("search_bom_export_failed", error),
            )
        else:
            QMessageBox.information(
                self,
                tr("search_bom_export_excel"),
                tr("search_bom_export_success", path),
            )

    # ---- refresh ----
    def refresh(self) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        # manual
        self._summary_label.setText(
            tr("search_result_summary", len(state.results))
            if len(state.results)
            else tr("search_empty")
        )
        self._rebuild_results(state.results)

        # BOM
        self._bom_file_label.setText(
            tr("search_bom_file_name", state.bom_file_name) if state.bom_file_name else ""
        )
        self._bom_summary.setText(
            tr("search_bom_summary", len(state.bom_rows), state.bom_matched_count)
            if state.bom_file_name
            else tr("search_bom_empty_hint")
        )
        self._bom_error.setText(state.bom_error or "")
        self._rebuild_bom_rows(state.bom_rows)

    def _rebuild_results(self, results: list[SearchResultUiModel]) -> None:
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not results:
            empty = QLabel(tr("search_empty"))
            empty.setObjectName("subtitle")
            self._results_layout.insertWidget(0, empty)
            return
        for model in results:
            card = SearchResultCard(model)
            card.view_item.connect(self._on_view_item)
            card.view_detail.connect(self._on_view_detail)
            self._results_layout.insertWidget(self._results_layout.count() - 1, card)

    def _rebuild_bom_rows(self, rows: list[BomSearchRowUiModel]) -> None:
        while self._bom_layout.count() > 1:
            item = self._bom_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for row in rows:
            card = BomRowCard(row)
            card.direct_inbound.connect(self._on_direct_inbound)
            card.bind_entry.connect(self._on_bind_entry)
            card.ignore_entry.connect(self._on_ignore_entry)
            card.view_item.connect(self._on_view_item)
            self._bom_layout.insertWidget(self._bom_layout.count() - 1, card)

    def _on_view_item(self, location_code: str, part_number: str) -> None:
        self._view_inventory_item(location_code, part_number)

    def _on_view_detail(self, record) -> None:
        dialog = ComponentDetailDialog(record, self)
        dialog.exec()

    def _on_direct_inbound(self, entry: BomSearchEntry) -> None:
        part_number = (entry.supplier_part or entry.manufacturer_part or "").strip().upper()
        if not part_number:
            QMessageBox.information(self, tr("search_bom_direct_inbound"), tr("search_bom_direct_inbound_no_part"))
            return
        self._vm.lookup_bom_direct_inbound(part_number, self._on_lookup_done)

    def _on_lookup_done(self, result) -> None:
        if result.error_message:
            QMessageBox.warning(self, tr("search_bom_direct_inbound"), result.error_message)
            return
        state = self._vm.ui_state
        suggested = self._vm.suggested_location_code_for(result.component)
        dialog = DirectInboundDialog(
            component=result.component,
            locations=state.locations if state else [],
            default_location_code=suggested,
            existing_stock=result.existing_stock_locations,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._vm.add_bom_inbound(
                component=result.component,
                quantity=dialog.quantity(),
                location_code=dialog.location_code(),
                on_completed=lambda error: (
                    QMessageBox.information(
                        self,
                        tr("search_bom_direct_inbound"),
                        tr("search_bom_direct_inbound_success", result.component.part_number),
                    )
                    if error is None
                    else QMessageBox.warning(self, tr("search_bom_direct_inbound"), error)
                ),
            )

    def _on_bind_entry(self, entry: BomSearchEntry) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        dialog = BindDialog(state.all_inventory_results, self)
        if dialog.exec() == QDialog.Accepted:
            pn = dialog.selected_part_number()
            if pn:
                self._vm.bind_bom_entry(entry, pn)

    def _on_ignore_entry(self, entry: BomSearchEntry) -> None:
        self._vm.ignore_bom_entry(entry)

    def retranslate_ui(self) -> None:
        self._heading.set_title(tr("search_title"))
        self._btn_manual.setText(tr("search_mode_manual"))
        self._btn_bom.setText(tr("search_mode_bom"))
        self._query.setPlaceholderText(tr("search_keyword_placeholder"))
        self._search_btn.setText(tr("inbound_manual_search_action"))
        self._pick_btn.setText(tr("search_bom_pick_file"))
        self._filter_all.setText(tr("search_bom_filter_all"))
        self._filter_matched.setText(tr("search_bom_filter_matched"))
        self._filter_unmatched.setText(tr("search_bom_filter_unmatched"))
        self._export_btn.setText(tr("search_bom_export_excel"))
        self.refresh()
