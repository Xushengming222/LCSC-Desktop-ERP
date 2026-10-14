"""Inventory page — port of feature/inventory/InventoryScreen.kt.

Two stacked views:
* Overview: a grid of storage-location cells (code, item count, total qty).
* Detail: the selected location's inventory items in a table, with per-item
  actions (edit quantity, transfer, delete), batch select + transfer/delete,
  print location label, and a location-settings dialog (code, name, color,
  sort mode).

Cross-tab deep links (``pending_open_request`` from Search/Inbound) scroll the
detail to the requested part number and clear the request.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..data.preferences import PRESET_LOCATION_COLORS
from ..domain.models import StockLocationCell
from ..domain.sort_mode import StorageLocationSortMode
from ..i18n import tr
from ..viewmodels.inventory_viewmodel import InventoryViewModel
from .widgets import Card, ColorSwatch, ComponentDetailDialog, ComponentThumbnail, DangerButton, Heading, LabelPrintDialog, OutlineButton, SuccessButton, TextButton


def _format_ts(ts: int) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return "—"


class LocationCellButton(QPushButton):
    """A grid tile representing one storage location."""

    clicked_cell = Signal(int)  # location id

    def __init__(self, cell: StockLocationCell, parent=None) -> None:
        super().__init__(parent)
        self._cell = cell
        self.setFixedHeight(96)
        self.setCursor(Qt.PointingHandCursor)
        bg = cell.color_hex or theme.SURFACE
        fg = theme.text_color_for(cell.color_hex)
        self.setStyleSheet(
            f"LocationCellButton {{ background: {bg}; color: {fg};"
            f" border: 1px solid {theme.OUTLINE_VARIANT}; border-radius: 12px;"
            f" text-align: left; padding: 12px 14px; }}"
            f"LocationCellButton:hover {{ border: 2px solid {theme.PRIMARY}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        code = QLabel(cell.code)
        code.setStyleSheet(f"color: {fg}; font-size: 20px; font-weight: 700; background: transparent; border: none;")
        code.setObjectName("h2")
        layout.addWidget(code)
        summary = QLabel(tr("inventory_cell_count", cell.inventory_item_count))
        summary.setStyleSheet(f"color: {fg}; background: transparent; border: none;")
        layout.addWidget(summary)
        qty = QLabel(tr("inventory_item_quantity", str(cell.total_quantity)))
        qty.setStyleSheet(f"color: {fg}; background: transparent; border: none;")
        layout.addWidget(qty)
        self.clicked.connect(lambda: self.clicked_cell.emit(cell.id))


class AddLocationDialog(QDialog):
    def __init__(self, recent_colors: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("inventory_add_location"))
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._code = QLineEdit()
        self._code.setPlaceholderText(tr("inventory_add_location_hint"))
        form.addRow(tr("inventory_location_code"), self._code)
        self._name = QLineEdit()
        form.addRow(tr("inventory_location_name"), self._name)
        layout.addLayout(form)

        layout.addWidget(QLabel(tr("inventory_location_color")))
        self._color: Optional[str] = None
        self._swatch_row = QHBoxLayout()
        for color in (recent_colors or PRESET_LOCATION_COLORS)[:5]:
            sw = ColorSwatch(color)
            sw.color_selected.connect(self._set_color)
            self._swatch_row.addWidget(sw)
        self._swatch_row.addStretch()
        layout.addLayout(self._swatch_row)

        self._custom_color = TextButton(tr("inventory_location_pick_color"))
        self._custom_color.clicked.connect(self._pick_custom_color)
        layout.addWidget(self._custom_color)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("common_confirm"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("common_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_color(self, color_hex: str) -> None:
        self._color = color_hex

    def _pick_custom_color(self) -> None:
        color = QColorDialog.getColor(QColor(theme.PRIMARY), self, tr("inventory_location_pick_color"))
        if color.isValid():
            self._color = color.name().upper()

    def code(self) -> str:
        return self._code.text().strip()

    def display_name(self) -> Optional[str]:
        text = self._name.text().strip()
        return text or None

    def color_hex(self) -> Optional[str]:
        return self._color


class LocationSettingsDialog(QDialog):
    def __init__(
        self,
        cell: StockLocationCell,
        locations: list,
        recent_colors: list[str],
        sort_attributes: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cell = cell
        self.setWindowTitle(tr("inventory_location_settings"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._code = QLineEdit(cell.code)
        form.addRow(tr("inventory_location_code"), self._code)
        self._name = QLineEdit(cell.display_name or "")
        form.addRow(tr("inventory_location_name"), self._name)

        self._color = cell.color_hex
        self._color_preview = QLabel()
        self._update_color_preview()
        pick = TextButton(tr("inventory_location_pick_color"))
        pick.clicked.connect(self._pick_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self._color_preview)
        color_row.addWidget(pick)
        color_row.addStretch()
        form.addRow(tr("inventory_location_color"), color_row)

        # Sort priorities
        layout.addLayout(form)
        layout.addWidget(QLabel(tr("inventory_location_sort_mode")))
        layout.addWidget(QLabel(tr("inventory_sort_mode_priority_hint")))
        self._priority_boxes: list[QComboBox] = []
        self._priorities = StorageLocationSortMode.priorities(cell.sort_mode)
        attrs = list(sort_attributes)
        for level in range(3):
            combo = QComboBox()
            combo.addItem("—", "")
            combo.addItem(tr("inventory_sort_mode_name"), StorageLocationSortMode.NAME)
            combo.addItem(tr("inventory_sort_mode_quantity"), StorageLocationSortMode.QUANTITY)
            combo.addItem(tr("inventory_sort_mode_inbound_time"), StorageLocationSortMode.INBOUND_TIME)
            for attr in attrs:
                combo.addItem(
                    f"{tr('inventory_sort_mode_secondary')} · {attr}",
                    StorageLocationSortMode.by_specification(attr),
                )
            if level < len(self._priorities):
                target = self._priorities[level]
                for i in range(combo.count()):
                    if combo.itemData(i) == target:
                        combo.setCurrentIndex(i)
                        break
            self._priority_boxes.append(combo)
            layout.addWidget(combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("common_save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("common_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_color(self) -> None:
        initial = QColor(self._color) if self._color else QColor(theme.PRIMARY)
        color = QColorDialog.getColor(initial, self, tr("inventory_location_pick_color"))
        if color.isValid():
            self._color = color.name().upper()
            self._update_color_preview()

    def _update_color_preview(self) -> None:
        if self._color:
            self._color_preview.setStyleSheet(
                f"background: {self._color}; border: 1px solid {theme.OUTLINE_VARIANT};"
                f" border-radius: 12px;"
            )
            self._color_preview.setFixedSize(48, 32)
        else:
            self._color_preview.setText("—")

    def code(self) -> str:
        return self._code.text().strip()

    def display_name(self) -> Optional[str]:
        text = self._name.text().strip()
        return text or None

    def color_hex(self) -> Optional[str]:
        return self._color

    def sort_mode(self) -> str:
        priorities = [
            box.currentData()
            for box in self._priority_boxes
            if box.currentData()
        ]
        return StorageLocationSortMode.serialize(priorities)


class InventoryPage(QWidget):
    def __init__(self, view_model: InventoryViewModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._vm = view_model

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        self._heading = Heading(tr("inventory_title"), tr("inventory_subtitle"))
        root.addWidget(self._heading)

        self._stack = QStackedWidget()
        self._overview = self._build_overview()
        self._detail = self._build_detail()
        self._stack.addWidget(self._overview)
        self._stack.addWidget(self._detail)
        root.addWidget(self._stack, 1)

        self._vm.ui_state_changed.connect(self.refresh)
        self.refresh()

    # ---- overview ----
    def _build_overview(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)
        top_row = QHBoxLayout()
        self._add_btn = OutlineButton(tr("inventory_add_location"))
        self._add_btn.clicked.connect(self._on_add_location)
        top_row.addWidget(self._add_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._error_label = QLabel()
        self._error_label.setStyleSheet(f"color: {theme.ERROR};")
        layout.addWidget(self._error_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._grid = QGridLayout(inner)
        self._grid.setSpacing(12)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        return panel

    def _on_add_location(self) -> None:
        state = self._vm.ui_state
        dialog = AddLocationDialog(state.recent_location_colors if state else [], self)
        if dialog.exec() == QDialog.Accepted:
            self._vm.add_storage_location(dialog.code(), dialog.display_name(), dialog.color_hex())

    def _rebuild_overview(self, cells: list[StockLocationCell]) -> None:
        # clear grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        # Show all locations (including empty ones)
        if not cells:
            # Show empty state — no warehouses created yet
            empty_label = QLabel(tr("inventory_empty_locations"))
            empty_label.setObjectName("subtitle")
            empty_label.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(empty_label, 0, 0, 1, 4)
            self._grid.setRowStretch(1, 1)
            return
        cols = 4
        for index, cell in enumerate(cells):
            btn = LocationCellButton(cell)
            btn.clicked_cell.connect(self._on_cell_clicked)
            self._grid.addWidget(btn, index // cols, index % cols)
        # spacer
        self._grid.setRowStretch((len(cells) + cols - 1) // cols, 1)

    def _on_cell_clicked(self, location_id: int) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        cell = next((c for c in state.cells if c.id == location_id), None)
        if cell is not None:
            self._vm.on_location_selected(cell)
            self._stack.setCurrentIndex(1)

    # ---- detail ----
    def _build_detail(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        self._back_btn = TextButton(tr("common_back"))
        self._back_btn.clicked.connect(self._on_back)
        header_row.addWidget(self._back_btn)
        self._detail_title = QLabel()
        self._detail_title.setObjectName("h2")
        header_row.addWidget(self._detail_title, 1)
        self._print_label_btn = OutlineButton(tr("inventory_print_location_label"))
        self._print_label_btn.clicked.connect(self._on_print_location_label)
        header_row.addWidget(self._print_label_btn)
        self._settings_btn = OutlineButton(tr("inventory_location_settings"))
        self._settings_btn.clicked.connect(self._on_location_settings)
        header_row.addWidget(self._settings_btn)
        self._delete_location_btn = DangerButton(tr("inventory_delete_location"))
        self._delete_location_btn.clicked.connect(self._on_delete_location)
        header_row.addWidget(self._delete_location_btn)
        layout.addLayout(header_row)

        # batch actions
        batch_row = QHBoxLayout()
        self._batch_label = QLabel()
        self._batch_label.setObjectName("subtitle")
        batch_row.addWidget(self._batch_label)
        batch_row.addStretch()
        self._batch_transfer_btn = OutlineButton(tr("inventory_batch_transfer"))
        self._batch_transfer_btn.clicked.connect(self._on_batch_transfer)
        batch_row.addWidget(self._batch_transfer_btn)
        self._batch_delete_btn = DangerButton(tr("common_delete"))
        self._batch_delete_btn.clicked.connect(self._on_batch_delete)
        batch_row.addWidget(self._batch_delete_btn)
        layout.addLayout(batch_row)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            "",  # checkbox
            tr("inbound_component_image"),
            tr("inbound_component_number"),
            tr("inbound_component_name"),
            tr("inbound_component_package"),
            tr("inventory_quantity_label"),
            tr("inventory_inbound_time"),
            tr("common_edit"),
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Fixed)
        self._table.horizontalHeader().setMinimumSectionSize(80)
        self._table.setColumnWidth(0, 16)  # checkbox column - very narrow
        self._table.setColumnWidth(1, 120)  # image column
        self._table.setColumnWidth(2, 120)  # part number column
        self._table.setColumnWidth(7, 420)  # action column
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(120)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.doubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._table, 1)

        self._detail_error = QLabel()
        self._detail_error.setStyleSheet(f"color: {theme.ERROR};")
        layout.addWidget(self._detail_error)
        return panel

    def _on_back(self) -> None:
        self._vm.dismiss_location_detail()
        self._stack.setCurrentIndex(0)

    def _on_print_location_label(self) -> None:
        state = self._vm.ui_state
        if state is None or state.selected_location is None:
            return
        cell = state.selected_location
        from ..data.label_exporter import create_location_label_image
        from .printing import save_label_image, print_image_at_size
        from .widgets import LabelPrintDialog

        try:
            # Generate the label image first
            image = create_location_label_image(cell, len(state.selected_location_items))

            # Convert to QPixmap for preview
            from PySide6.QtGui import QPixmap
            from io import BytesIO
            buf = BytesIO()
            image.save(buf, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue(), "PNG")

            # Show dialog for mode selection
            dialog = LabelPrintDialog(pixmap, self)
            if dialog.exec() == QDialog.Accepted:
                mode = dialog.mode()
                size_cm = dialog.selected_size_cm()

                # Always save the image
                path = save_label_image(image, f"location_{cell.code}")

                if mode == "save":
                    QMessageBox.information(
                        self,
                        tr("inventory_print_location_label"),
                        tr("inventory_location_label_saved", str(path)),
                    )
                elif mode == "print":
                    print_image_at_size(image, size_cm[0], size_cm[1], self)
                    QMessageBox.information(
                        self,
                        tr("inventory_print_location_label"),
                        tr("printer_print_success"),
                    )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                tr("inventory_print_location_label"),
                tr("inventory_location_label_export_failed") + f"\n\n{exc}",
            )

    def _on_location_settings(self) -> None:
        state = self._vm.ui_state
        if state is None or state.selected_location is None:
            return
        dialog = LocationSettingsDialog(
            cell=state.selected_location,
            locations=state.locations,
            recent_colors=state.recent_location_colors,
            sort_attributes=state.settings_location_sort_attributes,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._vm.update_location(
                location_id=state.selected_location.id,
                code=dialog.code(),
                display_name=dialog.display_name(),
                color_hex=dialog.color_hex(),
                sort_mode=dialog.sort_mode(),
                on_completed=lambda error: self._show_detail_error(error),
            )

    def _show_detail_error(self, error: Optional[str]) -> None:
        self._detail_error.setText(error or "")

    def _on_delete_location(self) -> None:
        state = self._vm.ui_state
        if state is None or state.selected_location is None:
            return
        cell = state.selected_location
        item_count = cell.inventory_item_count

        if item_count > 0:
            # Warehouse has items — warn and offer force delete
            reply = QMessageBox.question(
                self,
                tr("inventory_delete_location"),
                tr("inventory_delete_location_confirm_with_items", str(item_count)),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._vm.force_delete_location(
                cell.id,
                lambda error: (
                    QMessageBox.warning(self, tr("inventory_delete_location"), error)
                    if error
                    else None
                ),
            )
        else:
            # Empty warehouse — simple delete
            reply = QMessageBox.question(
                self,
                tr("inventory_delete_location"),
                tr("inventory_delete_location_confirm"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._vm.delete_location(
                cell.id,
                lambda error: (
                    QMessageBox.warning(self, tr("inventory_delete_location"), error)
                    if error
                    else None
                ),
            )

    def _selected_item_ids(self) -> list[int]:
        ids: list[int] = []
        for row in range(self._table.rowCount()):
            checkbox = self._table.cellWidget(row, 0)
            if isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                ids.append(int(checkbox.property("item_id")))
        return ids

    def _on_batch_transfer(self) -> None:
        state = self._vm.ui_state
        ids = self._selected_item_ids()
        if not ids or state is None:
            return
        target_code = self._prompt_target_location(state)
        if not target_code:
            return

        def _on_done(error):
            if error is None:
                QMessageBox.information(self, tr("inventory_batch_transfer"), tr("inventory_batch_transfer_completed"))
            else:
                QMessageBox.warning(self, tr("inventory_batch_transfer"), error)

        self._vm.transfer_inventory_items(ids, target_code, _on_done)

    def _on_batch_delete(self) -> None:
        ids = self._selected_item_ids()
        if not ids:
            return
        confirm = QMessageBox.question(
            self,
            tr("inventory_batch_delete_title"),
            tr("inventory_batch_delete_message", len(ids)),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        def _on_done(error):
            if error is None:
                QMessageBox.information(self, tr("inventory_batch_delete_title"), tr("inventory_batch_delete_completed"))
            else:
                QMessageBox.warning(self, tr("inventory_batch_delete_title"), error)

        self._vm.delete_inventory_items(ids, _on_done)

    def _prompt_target_location(self, state) -> Optional[str]:
        if not state.locations:
            QMessageBox.information(self, tr("inventory_batch_transfer"), tr("inventory_no_available_locations"))
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("inventory_select_target_location"))
        layout = QVBoxLayout(dialog)
        combo = QComboBox()
        current_code = state.selected_location.code if state.selected_location else None
        for loc in state.locations:
            if loc.code == current_code:
                continue
            label = loc.display_name or loc.code
            combo.addItem(f"{label} ({loc.code})", loc.code)
        if combo.count() == 0:
            QMessageBox.information(self, tr("inventory_batch_transfer"), tr("inventory_no_available_locations"))
            return None
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("inventory_batch_transfer_confirm"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("common_cancel"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            return combo.currentData()
        return None

    # ---- refresh ----
    def refresh(self) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        self._error_label.setText(state.add_location_error or "")
        self._detail_error.setText(state.update_location_error or "")
        self._rebuild_overview(state.cells)

        if state.selected_location is not None:
            cell = state.selected_location
            self._detail_title.setText(
                f"{cell.display_name or cell.code} ({cell.code})"
            )
            self._rebuild_items(state.selected_location_items)
            self._stack.setCurrentIndex(1)
            # handle pending open request (cross-tab deep link)
            if state.pending_open_request is not None:
                self._scroll_to_part(state.pending_open_request.part_number)
                self._vm.clear_pending_open_request()

    def _rebuild_items(self, items) -> None:
        self._table.setRowCount(0)
        self._table.setRowCount(len(items))
        self._items_by_row = list(items)
        for row, item in enumerate(items):
            self._table.setRowHeight(row, 120)

            checkbox = QCheckBox()
            checkbox.setFixedWidth(18)
            checkbox.setProperty("item_id", item.inventory_item_id)
            checkbox.stateChanged.connect(self._update_batch_label)
            self._table.setCellWidget(row, 0, checkbox)

            thumbnail = ComponentThumbnail(104)
            thumbnail.set_image_info(
                item.image_local_path,
                image_url=item.image_url,
                part_number=item.part_number,
            )
            self._table.setCellWidget(row, 1, thumbnail)

            self._table.setItem(row, 2, QTableWidgetItem(item.part_number))
            self._table.setItem(row, 3, QTableWidgetItem(item.name or "—"))
            self._table.setItem(row, 4, QTableWidgetItem(item.package_name or "—"))
            self._table.setItem(row, 5, QTableWidgetItem(str(item.quantity)))
            self._table.setItem(row, 6, QTableWidgetItem(_format_ts(item.last_inbound_at)))

            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)
            detail_btn = TextButton(tr("inventory_view_detail"))
            detail_btn.setToolTip(tr("inventory_view_detail"))
            detail_btn.clicked.connect(
                lambda _checked=False, iid=item.inventory_item_id, r=row: self._show_detail_for_row(r)
            )
            actions_layout.addWidget(detail_btn)
            edit_btn = TextButton(tr("inventory_edit_quantity"))
            edit_btn.setToolTip(tr("inventory_edit_quantity"))
            edit_btn.clicked.connect(lambda _checked=False, iid=item.inventory_item_id: self._edit_quantity(iid))
            transfer_btn = TextButton(tr("inventory_transfer_location"))
            transfer_btn.setToolTip(tr("inventory_transfer_location"))
            transfer_btn.clicked.connect(lambda _checked=False, iid=item.inventory_item_id: self._transfer_item(iid))
            delete_btn = DangerButton(tr("common_delete"))
            delete_btn.setToolTip(tr("common_delete"))
            delete_btn.clicked.connect(lambda _checked=False, iid=item.inventory_item_id: self._delete_item(iid))
            actions_layout.addWidget(edit_btn)
            actions_layout.addWidget(transfer_btn)
            actions_layout.addWidget(delete_btn)
            actions_layout.addStretch()
            self._table.setCellWidget(row, 7, actions)
        self._update_batch_label()

    def _item_at_row(self, row: int):
        items = getattr(self, "_items_by_row", None)
        if not items or row < 0 or row >= len(items):
            return None
        return items[row]

    def _show_detail_for_row(self, row: int) -> None:
        item = self._item_at_row(row)
        if item is None:
            return
        dialog = ComponentDetailDialog(item, self)
        dialog.exec()

    def _on_item_double_clicked(self, index) -> None:
        self._show_detail_for_row(index.row())

    def _update_batch_label(self) -> None:
        count = len(self._selected_item_ids())
        self._batch_label.setText(tr("inventory_batch_selected_count", count) if count else "")

    def _edit_quantity(self, inventory_item_id: int) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        item = next(
            (it for it in state.selected_location_items if it.inventory_item_id == inventory_item_id),
            None,
        )
        current_qty = item.quantity if item else 0
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("inventory_edit_quantity"))
        layout = QVBoxLayout(dialog)
        spin = QSpinBox()
        spin.setRange(0, 1_000_000)
        spin.setValue(current_qty)
        layout.addWidget(spin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("inventory_save_quantity"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("common_cancel"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self._vm.update_inventory_item_quantity(
                inventory_item_id, spin.value(),
                lambda error: QMessageBox.warning(self, tr("inventory_edit_quantity"), error) if error else None,
            )

    def _transfer_item(self, inventory_item_id: int) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        target_code = self._prompt_target_location(state)
        if not target_code:
            return
        self._vm.transfer_inventory_item(
            inventory_item_id, target_code,
            lambda error: QMessageBox.warning(self, tr("inventory_transfer_location"), error) if error else None,
        )

    def _delete_item(self, inventory_item_id: int) -> None:
        confirm = QMessageBox.question(
            self, tr("inventory_delete_item"), tr("inventory_delete_item"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._vm.delete_inventory_item(
            inventory_item_id,
            lambda error: QMessageBox.warning(self, tr("inventory_delete_item"), error) if error else None,
        )

    def _scroll_to_part(self, part_number: str) -> None:
        target = part_number.strip().upper()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 2)
            if item and item.text().strip().upper() == target:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return

    # ---- external hook (cross-tab navigation) ----
    def open_inventory_item(self, location_code: str, part_number: str) -> None:
        self._vm.open_inventory_item(location_code, part_number)
        self._stack.setCurrentIndex(1)

    def retranslate_ui(self) -> None:
        self._heading.set_title(tr("inventory_title"))
        self._heading.set_subtitle(tr("inventory_subtitle"))
        self._add_btn.setText(tr("inventory_add_location"))
        self._back_btn.setText(tr("common_back"))
        self._print_label_btn.setText(tr("inventory_print_location_label"))
        self._settings_btn.setText(tr("inventory_location_settings"))
        self._delete_location_btn.setText(tr("inventory_delete_location"))
        self._batch_transfer_btn.setText(tr("inventory_batch_transfer"))
        self._batch_delete_btn.setText(tr("common_delete"))
        self._table.setHorizontalHeaderLabels([
            "",
            tr("inbound_component_image"),
            tr("inbound_component_number"),
            tr("inbound_component_name"),
            tr("inbound_component_package"),
            tr("inventory_quantity_label"),
            tr("inventory_inbound_time"),
            tr("common_edit"),
        ])
        self.refresh()
