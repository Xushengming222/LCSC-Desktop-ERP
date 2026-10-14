"""Inbound page — port of feature/inbound/InboundScreen.kt (camera scan removed).

Two modes (mirrors the Android tab layout):
* 搜索入库 (Search): keyword search against the LCSC catalog, pick a result,
  confirm inbound into a chosen location.
* 手动入库 (Manual): enter component fields by hand (part number prefilled
  with the next ``C0N`` manual id), confirm inbound.

The camera/QR scan tab from the Android app is intentionally omitted per the
user's request — the ViewModel still exposes ``on_qr_scanned`` for API parity
but no UI is wired to it. Label image generation (printable via system dialog)
is retained.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..domain.models import ComponentDetail
from ..i18n import tr
from ..viewmodels.inbound_viewmodel import InboundViewModel
from .widgets import Card, Chip, ComponentDetailDialog, ComponentThumbnail, Heading, InfoRow, OutlineButton, SuccessButton, TextButton


class ResultCard(Card):
    """A single LCSC search-result row."""

    pick_clicked = Signal(object)
    view_detail = Signal(object)

    def __init__(self, component: ComponentDetail, existing_stock_text: Optional[str], parent=None) -> None:
        super().__init__(parent)
        self.component = component
        layout = QHBoxLayout()
        layout.setSpacing(12)
        self.thumbnail = ComponentThumbnail(72)
        self.thumbnail.set_image_info(
            component.image_local_path,
            image_url=component.image_url,
            part_number=component.part_number,
        )
        layout.addWidget(self.thumbnail)

        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel(component.part_number)
        title.setObjectName("h3")
        info.addWidget(title)
        if component.name:
            info.addWidget(QLabel(component.name))
        meta = QHBoxLayout()
        meta.setSpacing(10)
        if component.brand:
            meta.addWidget(QLabel(f"{tr('inbound_component_brand')}: {component.brand}"))
        if component.package_name:
            meta.addWidget(QLabel(f"{tr('inbound_component_package')}: {component.package_name}"))
        meta.addStretch()
        info.addLayout(meta)
        if existing_stock_text:
            info.addWidget(Chip(existing_stock_text))

        # Bottom row: detail link + stretch
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch()
        view_btn = TextButton(tr("inventory_view_detail"))
        view_btn.setCursor(Qt.PointingHandCursor)
        view_btn.clicked.connect(lambda: self.view_detail.emit(component))
        bottom_row.addWidget(view_btn)
        info.addLayout(bottom_row)

        layout.addLayout(info, 1)

        # Right side: action button only
        pick = SuccessButton(tr("inbound_manual_confirm_action"))
        pick.setMinimumWidth(100)
        pick.clicked.connect(lambda: self.pick_clicked.emit(component))
        layout.addWidget(pick, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.body.addLayout(layout)


class ConfirmInboundDialog(QDialog):
    """Dialog confirming an inbound for a chosen component (search mode)."""

    def __init__(
        self,
        component: ComponentDetail,
        locations: list,
        default_location_code: Optional[str],
        existing_stock: list,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.component = component
        self.setWindowTitle(tr("inbound_manual_dialog_title"))
        self.setMinimumWidth(520)
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(
            "ConfirmInboundDialog { background: white; }"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

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
        if component.category:
            detail.addWidget(InfoRow(tr("inbound_component_category"), component.category))
        if component.stock_quantity is not None:
            detail.addWidget(InfoRow(tr("inbound_component_stock"), str(component.stock_quantity)))
        if component.price is not None:
            detail.addWidget(InfoRow(tr("inbound_component_price"), f"¥{component.price}"))
        if component.description:
            detail.addWidget(InfoRow(tr("inbound_component_description"), component.description))
        layout.addWidget(detail)

        if existing_stock:
            stock_card = Card()
            stock_title = QLabel(tr("inbound_existing_stock_title"))
            stock_title.setObjectName("h3")
            stock_card.addWidget(stock_title)
            stock_card.addWidget(QLabel(tr("inbound_existing_stock_body")))
            for item in existing_stock:
                label = f"{item.location_code} · {tr('inventory_item_quantity', str(item.quantity))}"
                stock_card.addWidget(QLabel(label))
            layout.addWidget(stock_card)

        form = QFormLayout()
        form.setSpacing(8)
        self._qty = QSpinBox()
        self._qty.setRange(0, 1_000_000)
        self._qty.setValue(1)
        form.addRow(tr("inbound_quantity_label"), self._qty)

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
        form.addRow(tr("inbound_location_label"), self._location)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("common_confirm"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("common_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def quantity(self) -> int:
        return self._qty.value()

    def location_code(self) -> str:
        return self._location.currentData() or ""


class InboundPage(QWidget):
    def __init__(self, view_model: InboundViewModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._vm = view_model

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        self._heading = Heading(tr("inbound_title"))
        root.addWidget(self._heading)

        # Mode toggle
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._btn_search = QPushButton(tr("inbound_mode_search"))
        self._btn_search.setCheckable(True)
        self._btn_manual = QPushButton(tr("inbound_mode_manual"))
        self._btn_manual.setCheckable(True)
        self._mode_group.addButton(self._btn_search, 0)
        self._mode_group.addButton(self._btn_manual, 1)
        mode_row.addWidget(self._btn_search)
        mode_row.addWidget(self._btn_manual)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # Stacked content
        self._stack = QStackedWidget()
        self._search_panel = self._build_search_panel()
        self._manual_panel = self._build_manual_panel()
        self._stack.addWidget(self._search_panel)
        self._stack.addWidget(self._manual_panel)
        root.addWidget(self._stack, 1)

        self._btn_search.setChecked(True)
        self._stack.setCurrentIndex(0)
        self._mode_group.idToggled.connect(self._on_mode_toggled)

        self._vm.ui_state_changed.connect(self.refresh)
        self.refresh()

    def _on_mode_toggled(self, button_id: int, checked: bool) -> None:
        if checked:
            self._stack.setCurrentIndex(button_id)

    # ---- search panel ----
    def _build_search_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        search_row = QHBoxLayout()
        self._keyword = QLineEdit()
        self._keyword.setPlaceholderText(tr("inbound_manual_keyword_placeholder"))
        self._keyword.returnPressed.connect(self._on_search)
        search_row.addWidget(self._keyword, 1)
        self._search_btn = QPushButton(tr("inbound_manual_search_action"))
        self._search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self._search_btn)
        layout.addLayout(search_row)

        self._recent_label = QLabel(tr("inbound_recent_searches"))
        self._recent_label.setObjectName("subtitle")
        layout.addWidget(self._recent_label)
        self._recent_row = QHBoxLayout()
        layout.addLayout(self._recent_row)

        self._status_label = QLabel()
        self._status_label.setObjectName("subtitle")
        layout.addWidget(self._status_label)

        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(10)
        self._results_layout.addStretch()
        self._results_scroll.setWidget(self._results_container)
        layout.addWidget(self._results_scroll, 1)
        return panel

    def _on_search(self) -> None:
        self._vm.search_manual(self._keyword.text())

    def _rebuild_recent(self, recent: list[str]) -> None:
        while self._recent_row.count():
            item = self._recent_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for keyword in recent[:5]:
            chip = QPushButton(keyword)
            chip.setObjectName("textBtn")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda checked=False, k=keyword: self._rerun_recent(k))
            self._recent_row.addWidget(chip)
        self._recent_row.addStretch()
        self._recent_label.setVisible(bool(recent))

    def _rerun_recent(self, keyword: str) -> None:
        self._keyword.setText(keyword)
        self._vm.search_manual(keyword)

    # ---- manual panel ----
    def _build_manual_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        self._next_pn_label = QLabel()
        self._next_pn_label.setObjectName("h3")
        layout.addWidget(self._next_pn_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(8)

        self._m_part_number = QLineEdit()
        self._m_part_number.setPlaceholderText("C01")
        form.addRow(tr("inbound_component_number"), self._m_part_number)
        self._m_name = QLineEdit()
        form.addRow(tr("inbound_component_name"), self._m_name)
        self._m_brand = QLineEdit()
        form.addRow(tr("inbound_component_brand"), self._m_brand)
        self._m_package = QLineEdit()
        form.addRow(tr("inbound_component_package"), self._m_package)
        self._m_category = QLineEdit()
        form.addRow(tr("inbound_component_category"), self._m_category)
        self._m_description = QLineEdit()
        form.addRow(tr("inbound_component_description"), self._m_description)
        self._m_specs = QPlainTextEdit()
        self._m_specs.setPlaceholderText(tr("inbound_manual_entry_specifications_placeholder"))
        self._m_specs.setFixedHeight(90)
        form.addRow(tr("inbound_manual_entry_specifications_label"), self._m_specs)
        self._m_image_url = QLineEdit()
        self._m_image_url.setPlaceholderText("https://...")
        form.addRow(tr("inbound_manual_entry_image_url_label"), self._m_image_url)
        self._m_qty = QSpinBox()
        self._m_qty.setRange(0, 1_000_000)
        self._m_qty.setValue(1)
        form.addRow(tr("inbound_quantity_label"), self._m_qty)
        self._m_location = QComboBox()
        form.addRow(tr("inbound_location_label"), self._m_location)

        actions = QHBoxLayout()
        self._print_qr_btn = OutlineButton(tr("inbound_manual_print_qr"))
        self._print_qr_btn.clicked.connect(self._on_print_qr)
        actions.addWidget(self._print_qr_btn)
        actions.addStretch()
        self._confirm_manual_btn = SuccessButton(tr("common_confirm"))
        self._confirm_manual_btn.clicked.connect(self._on_confirm_manual)
        actions.addWidget(self._confirm_manual_btn)
        form.addRow(actions)

        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        return panel

    def _on_print_qr(self) -> None:
        part_number = self._m_part_number.text().strip().upper()
        if not part_number:
            QMessageBox.information(
                self,
                tr("inbound_manual_print_qr"),
                tr("inbound_manual_entry_part_number_required"),
            )
            return
        component = self._form_to_component(part_number)
        from .printing import save_and_print_component_label

        try:
            path = save_and_print_component_label(component, self, do_print=True)
            QMessageBox.information(
                self,
                tr("inbound_manual_print_qr"),
                tr("inbound_manual_print_qr_saved", str(path)),
            )
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, tr("inbound_manual_print_qr"), tr("inbound_manual_print_qr_failed"))

    def _form_to_component(self, part_number: str) -> ComponentDetail:
        specs: dict[str, str] = {}
        for line in self._m_specs.toPlainText().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value:
                    specs[key] = value
        return ComponentDetail(
            part_number=part_number,
            name=self._m_name.text().strip() or None,
            brand=self._m_brand.text().strip() or None,
            package_name=self._m_package.text().strip() or None,
            category=self._m_category.text().strip() or None,
            description=self._m_description.text().strip() or None,
            image_url=self._m_image_url.text().strip() or None,
            specifications=specs,
        )

    def _on_confirm_manual(self) -> None:
        part_number = self._m_part_number.text().strip().upper()
        if not part_number:
            QMessageBox.information(
                self,
                tr("inbound_manual_entry_dialog_title"),
                tr("inbound_manual_entry_part_number_required"),
            )
            return
        location_code = self._m_location.currentData() or ""
        component = self._form_to_component(part_number)
        quantity = self._m_qty.value()

        def _on_done(error):
            if error is None:
                QMessageBox.information(
                    self,
                    tr("inbound_manual_entry_dialog_title"),
                    tr("inbound_manual_entry_success", part_number),
                )
                self._clear_manual_form()
            else:
                QMessageBox.warning(self, tr("inbound_manual_entry_dialog_title"), error)

        self._vm.confirm_inbound(
            component=component,
            quantity=quantity,
            location_code=location_code,
            source_type="MANUAL_INPUT",
            on_completed=_on_done,
        )

    def _clear_manual_form(self) -> None:
        self._m_name.clear()
        self._m_brand.clear()
        self._m_package.clear()
        self._m_category.clear()
        self._m_description.clear()
        self._m_specs.clear()
        self._m_image_url.clear()
        self._m_qty.setValue(1)

    # ---- refresh ----
    def refresh(self) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        self._next_pn_label.setText(
            f"{tr('inbound_component_number')}: {state.next_manual_inbound_part_number}"
        )
        if not self._m_part_number.text().strip():
            self._m_part_number.setText(state.next_manual_inbound_part_number)

        self._repopulate_locations(state.locations, state.default_location_code)
        self._rebuild_recent(state.recent_manual_searches)

        if state.is_searching_manual:
            self._status_label.setText(tr("inbound_manual_searching"))
        elif state.manual_search_error:
            self._status_label.setText(state.manual_search_error)
        else:
            self._status_label.setText("")

        self._rebuild_results(state.manual_search_results, state.existing_stock_by_part_number)

    def _repopulate_locations(self, locations, default_code) -> None:
        current = self._m_location.currentData()
        self._m_location.clear()
        for loc in locations:
            label = loc.display_name or loc.code
            self._m_location.addItem(f"{label} ({loc.code})", loc.code)
        target = default_code or current
        if target:
            for i in range(self._m_location.count()):
                data = self._m_location.itemData(i)
                if data and data.upper() == target.upper():
                    self._m_location.setCurrentIndex(i)
                    break

    def _rebuild_results(self, results, existing_map) -> None:
        # Remove all existing cards (except the trailing stretch)
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Set parent to None to immediately remove from layout
                widget.setParent(None)
                widget.deleteLater()

        # Force layout update to prevent ghosting
        self._results_layout.update()
        self._results_container.update()

        for component in results:
            existing = existing_map.get(component.part_number) or []
            stock_text = tr("inbound_existing_stock_badge") if existing else None
            card = ResultCard(component, stock_text)
            card.pick_clicked.connect(self._on_pick_result)
            card.view_detail.connect(self._on_view_detail)
            self._results_layout.insertWidget(self._results_layout.count() - 1, card)

    def _on_view_detail(self, component: ComponentDetail) -> None:
        dialog = ComponentDetailDialog(component, self)
        dialog.exec()

    def _on_pick_result(self, component: ComponentDetail) -> None:
        suggested = self._vm.suggested_location_code_for(component)
        state = self._vm.ui_state
        existing = (
            (state.existing_stock_by_part_number or {}).get(component.part_number, []) if state else []
        )
        dialog = ConfirmInboundDialog(
            component=component,
            locations=state.locations if state else [],
            default_location_code=suggested,
            existing_stock=existing,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            quantity = dialog.quantity()
            location_code = dialog.location_code()

            def _on_done(error):
                if error is None:
                    QMessageBox.information(
                        self,
                        tr("inbound_manual_dialog_title"),
                        tr("inbound_manual_entry_success", component.part_number),
                    )
                else:
                    QMessageBox.warning(self, tr("inbound_manual_dialog_title"), error)

            self._vm.confirm_inbound(
                component=component,
                quantity=quantity,
                location_code=location_code,
                source_type="SEARCH",
                on_completed=_on_done,
            )

    def retranslate_ui(self) -> None:
        self._heading.set_title(tr("inbound_title"))
        self._btn_search.setText(tr("inbound_mode_search"))
        self._btn_manual.setText(tr("inbound_mode_manual"))
        self._keyword.setPlaceholderText(tr("inbound_manual_keyword_placeholder"))
        self._search_btn.setText(tr("inbound_manual_search_action"))
        self._recent_label.setText(tr("inbound_recent_searches"))
        self.refresh()
