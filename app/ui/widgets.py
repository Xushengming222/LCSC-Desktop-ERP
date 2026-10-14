"""Shared UI widgets — common building blocks for the desktop port.

These mirror the Material 3 composables used throughout the Android app
(``Card``, ``StatCard``, section headers, chips, color swatches, etc.) but are
implemented with PySide6 widgets + the QSS theme from ``app/theme.py``.
"""
from __future__ import annotations

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..i18n import tr


class Card(QFrame):
    """A rounded surface with a 1px outline — the QSS ``QGroupBox#card`` analog."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 18, 16, 16)
        self._layout.setSpacing(10)

    def addWidget(self, widget: QWidget) -> None:  # noqa: N802 - Qt-style API
        self._layout.addWidget(widget)

    def addLayout(self, layout: QLayout) -> None:  # noqa: N802
        self._layout.addLayout(layout)

    def addStretch(self) -> None:  # noqa: N802
        self._layout.addStretch()

    def addSpacing(self, size: int) -> None:  # noqa: N802
        self._layout.addSpacing(size)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class SectionTitle(QLabel):
    """Bold section header (mirrors Material ``headlineSmall``)."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("h2")


class Subtitle(QLabel):
    """Muted helper text under a section title."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("subtitle")
        self.setWordWrap(True)


class StatCard(QWidget):
    """Dashboard statistic tile: big value + label."""

    def __init__(self, label: str, value: str = "0", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(6)
        self._value_label = QLabel(value)
        self._value_label.setObjectName("value")
        self._label_label = QLabel(label)
        self._label_label.setObjectName("subtitle")
        outer.addWidget(self._value_label)
        outer.addWidget(self._label_label)

        frame = QFrame(self)
        frame.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE}; border: 1px solid {theme.OUTLINE_VARIANT};"
            f" border-radius: 12px; }}"
        )
        frame.setFixedHeight(0)
        self.setStyleSheet(
            f"StatCard {{ background: {theme.SURFACE}; border: 1px solid {theme.OUTLINE_VARIANT};"
            f" border-radius: 12px; }}"
        )

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_label(self, label: str) -> None:
        self._label_label.setText(label)


class OutlineButton(QPushButton):
    """Outline-style button (transparent bg, colored border)."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("outline")


class TextButton(QPushButton):
    """Text-only button (transparent bg)."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("textBtn")


class DangerButton(QPushButton):
    """Error-colored destructive action button."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("danger")


class SuccessButton(QPushButton):
    """Tertiary-colored confirm action button."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("success")


class ColorSwatch(QPushButton):
    """A small clickable color chip used in the location-color picker."""

    color_selected = Signal(str)

    def __init__(self, color_hex: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = color_hex
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(color_hex)
        self._apply_style()
        self.clicked.connect(lambda: self.color_selected.emit(self._color))

    def _apply_style(self) -> None:
        border_color = theme.ON_SURFACE if theme.luminance(self._color) < 0.5 else theme.OUTLINE
        self.setStyleSheet(
            f"ColorSwatch {{ background: {self._color}; border: 2px solid {border_color};"
            f" border-radius: 16px; }}"
            f"ColorSwatch:hover {{ border: 2px solid {theme.PRIMARY}; }}"
        )

    @property
    def color(self) -> str:
        return self._color


class Chip(QLabel):
    """A small rounded badge (e.g. ``库存已有``)."""

    def __init__(self, text: str, color_hex: str = theme.TERTIARY_CONTAINER, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        fg = theme.text_color_for(color_hex)
        self.setStyleSheet(
            f"Chip {{ background: {color_hex}; color: {fg}; border-radius: 10px;"
            f" padding: 3px 10px; font-size: 12px; font-weight: 600; }}"
        )
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)


class InfoRow(QWidget):
    """A label + value row used in component detail cards."""

    def __init__(self, label: str, value: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(12)
        self._label = QLabel(label)
        self._label.setObjectName("subtitle")
        self._label.setMinimumWidth(90)
        self._value = QLabel(value)
        self._value.setWordWrap(True)
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._label)
        layout.addWidget(self._value, 1)

    def set_value(self, value: str) -> None:
        self._value.setText(value if value else "—")


class ComponentThumbnail(QLabel):
    """Square thumbnail that loads a local image path, with a placeholder.

    If a local path is not available but a remote URL is set, the image is
    downloaded asynchronously via ``requests`` on a worker thread and
    displayed when ready. The image is also cached to disk via the
    ``ComponentImageStore`` for subsequent displays.
    """

    _image_ready = Signal(bytes)

    def __init__(self, size: int = 96, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"ComponentThumbnail {{ background: {theme.SURFACE_VARIANT};"
            f" border: 1px solid {theme.OUTLINE_VARIANT}; border-radius: 8px; }}"
        )
        self._placeholder_text = "无图"
        self._part_number: Optional[str] = None
        self._image_url: Optional[str] = None
        self._image_store = None
        self._loading = False
        self._image_ready.connect(self._on_downloaded)

    def set_image_path(self, path: Optional[str]) -> None:
        """Set the local file path. If the file exists, display it immediately."""
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                self.setPixmap(
                    pix.scaled(
                        self._size,
                        self._size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                return
        self._show_placeholder()

    def set_image_info(
        self,
        local_path: Optional[str],
        image_url: Optional[str] = None,
        part_number: Optional[str] = None,
        image_store=None,
    ) -> None:
        """Set image info — tries local path first, falls back to URL download."""
        self._image_url = image_url
        self._part_number = part_number
        self._image_store = image_store

        if local_path:
            pix = QPixmap(local_path)
            if not pix.isNull():
                self.setPixmap(
                    pix.scaled(
                        self._size, self._size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
                return

        if image_url:
            self._download_and_display(image_url)
            return

        self._show_placeholder()

    def _download_and_display(self, url: str) -> None:
        """Download the image asynchronously and display it."""
        if self._loading:
            return
        self._loading = True
        self._show_placeholder()
        loading_text = "加载中…"
        if self._has_i18n:
            from ..i18n import tr as _tr
            loading_text = _tr("common_loading")
        self.setText(loading_text)

        import threading

        def _fetch():
            import requests

            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    self._image_ready.emit(resp.content)
                    return
            except Exception:
                pass
            self._image_ready.emit(b"")

        threading.Thread(target=_fetch, daemon=True).start()

    @Slot(bytes)
    def _on_downloaded(self, data: bytes) -> None:
        self._loading = False
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                scaled = pix.scaled(
                    self._size, self._size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.setPixmap(scaled)
                if self._image_store and self._part_number:
                    self._image_store.persist_image_bytes(
                        self._part_number, self._image_url, data
                    )
                return
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        self.clear()
        self.setText(self._placeholder_text)

    @property
    def _has_i18n(self) -> bool:
        try:
            from ..i18n import tr
            tr("common_loading")
            return True
        except Exception:
            return False





class Heading(QWidget):
    """Page heading: large title + optional subtitle, used at the top of each page."""

    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)
        self._title = QLabel(title)
        self._title.setObjectName("h1")
        layout.addWidget(self._title)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("subtitle")
        self._subtitle.setWordWrap(True)
        if subtitle:
            layout.addWidget(self._subtitle)

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(subtitle)
        self._subtitle.setVisible(bool(subtitle))


def make_heading_font(point_size: int = 24, bold: bool = True) -> QFont:
    font = QFont()
    font.setPointSize(point_size)
    font.setBold(bold)
    return font


class ComponentDetailDialog(QDialog):
    """Detail dialog that shows every known field of a component.

    Accepts either a ``LocationInventoryItem`` / ``SearchInventoryRecord``
    (used by the inventory / search pages) or a ``ComponentDetail`` (used
    by the inbound pages).  The dialog renders:

    * A large thumbnail on the left
    * The part number as the heading
    * Brand / package / category / description rows
    * All specification key-value pairs
    * An "open source" button when a source URL is known
    """

    def __init__(self, item, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._item = item
        self.setWindowTitle(tr("component_detail_title", item.part_number))
        self.setMinimumWidth(560)
        self.setMinimumHeight(360)
        self.resize(640, 480)
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(
            "ComponentDetailDialog { background: white; }"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header: thumbnail + text
        header_row = QHBoxLayout()
        header_row.setSpacing(16)
        self._thumbnail = ComponentThumbnail(120)
        image_url = getattr(item, "image_url", None)
        local_path = getattr(item, "image_local_path", None)
        part_number = getattr(item, "part_number", "")
        self._thumbnail.set_image_info(local_path, image_url=image_url, part_number=part_number)
        header_row.addWidget(self._thumbnail, 0)

        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        title_label = QLabel(part_number or "")
        title_label.setObjectName("h2")
        title_label.setWordWrap(True)
        header_text.addWidget(title_label)
        name = getattr(item, "name", None)
        if name:
            name_label = QLabel(str(name))
            name_label.setWordWrap(True)
            header_text.addWidget(name_label)
        header_text.addStretch(1)
        header_row.addLayout(header_text, 1)
        layout.addLayout(header_row)

        # Content (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(8)

        self._add_info_rows(content_layout, item)

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # Buttons
        btn_row = QHBoxLayout()
        source_url = getattr(item, "source_url", None) or ""
        if source_url:
            open_btn = QPushButton(tr("component_detail_open_source"))
            open_btn.clicked.connect(lambda: self._open_url(source_url))
            btn_row.addWidget(open_btn)
        datasheet_url = getattr(item, "datasheet_url", None) or ""
        if datasheet_url:
            ds_btn = QPushButton(tr("component_detail_open_datasheet"))
            ds_btn.clicked.connect(lambda: self._open_url(datasheet_url))
            btn_row.addWidget(ds_btn)
        # Print component label button
        print_btn = QPushButton(tr("component_detail_print_label"))
        print_btn.clicked.connect(lambda: self._on_print_label())
        btn_row.addWidget(print_btn)
        btn_row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(tr("common_close"))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

    def _on_print_label(self) -> None:
        """Generate a component label image and show the print dialog."""
        from ..data.qr_exporter import create_label_image
        from .printing import save_label_image, print_image_at_size

        try:
            # Build a ComponentDetail from the item (works for all item types)
            from ..domain.models import ComponentDetail
            component = ComponentDetail(
                part_number=getattr(self._item, "part_number", "") or "",
                mpn=getattr(self._item, "mpn", None),
                name=getattr(self._item, "name", None),
                brand=getattr(self._item, "brand", None),
                package_name=getattr(self._item, "package_name", None),
                category=getattr(self._item, "category", None),
                description=getattr(self._item, "description", None),
                image_url=getattr(self._item, "image_url", None),
                image_local_path=getattr(self._item, "image_local_path", None),
                specifications=getattr(self._item, "specifications", None) or {},
            )

            # Generate the label image
            image = create_label_image(component)

            # Convert to QPixmap for preview
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
                path = save_label_image(image, f"component_{component.part_number}")

                if mode == "save":
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        tr("component_detail_print_label"),
                        tr("inventory_location_label_saved", str(path)),
                    )
                elif mode == "print":
                    print_image_at_size(image, size_cm[0], size_cm[1], self)
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        tr("component_detail_print_label"),
                        tr("printer_print_success"),
                    )
        except Exception as exc:  # noqa: BLE001
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                tr("component_detail_print_label"),
                tr("inventory_location_label_export_failed") + f"\n\n{exc}",
            )

    def _add_info_rows(self, layout: QVBoxLayout, item) -> None:
        part_number = getattr(item, "part_number", None)
        if part_number:
            layout.addWidget(InfoRow(tr("inbound_component_number"), str(part_number)))

        mpn = getattr(item, "mpn", None)
        if mpn:
            layout.addWidget(InfoRow(tr("inbound_component_mpn"), str(mpn)))

        brand = getattr(item, "brand", None)
        if brand:
            layout.addWidget(InfoRow(tr("inbound_component_brand"), str(brand)))

        package = getattr(item, "package_name", None)
        if package:
            layout.addWidget(InfoRow(tr("inbound_component_package"), str(package)))

        category = getattr(item, "category", None)
        if category:
            layout.addWidget(InfoRow(tr("inbound_component_category"), str(category)))

        description = getattr(item, "description", None)
        if description:
            desc_label = QLabel(str(description))
            desc_label.setWordWrap(True)
            desc_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            desc_card = Card()
            desc_title = QLabel(tr("inbound_component_description"))
            desc_title.setObjectName("subtitle")
            desc_card.addWidget(desc_title)
            desc_card.addWidget(desc_label)
            layout.addWidget(desc_card)

        # Quantity / stock info
        qty = getattr(item, "quantity", None)
        if qty is not None:
            layout.addWidget(InfoRow(tr("inventory_quantity_label"), str(qty)))
        stock = getattr(item, "stock_quantity", None)
        if stock is not None:
            layout.addWidget(InfoRow(tr("inbound_component_stock"), str(stock)))
        price = getattr(item, "price", None)
        if price is not None:
            try:
                layout.addWidget(InfoRow(tr("inbound_component_price"), f"¥{float(price):.2f}"))
            except (TypeError, ValueError):
                pass

        # Location info
        location_code = getattr(item, "location_code", None)
        if location_code:
            layout.addWidget(InfoRow(tr("inventory_location_code"), str(location_code)))
        location_display = getattr(item, "location_display_name", None)
        if location_display:
            layout.addWidget(InfoRow(tr("inventory_location_name"), str(location_display)))

        inbound_at = getattr(item, "last_inbound_at", None)
        if inbound_at:
            from datetime import datetime
            try:
                ts_text = datetime.fromtimestamp(inbound_at / 1000).strftime("%Y-%m-%d %H:%M")
                layout.addWidget(InfoRow(tr("inventory_inbound_time"), ts_text))
            except (ValueError, OSError):
                pass

        # Specifications
        specs = getattr(item, "specifications", None) or {}
        if specs:
            specs_card = Card()
            specs_title = QLabel(tr("inbound_component_specifications"))
            specs_title.setObjectName("subtitle")
            specs_card.addWidget(specs_title)
            for key, value in specs.items():
                if value is None or str(value).strip() == "" or str(value).strip().lower() == "null":
                    continue
                specs_card.addWidget(InfoRow(str(key), str(value)))
            layout.addWidget(specs_card)

        # Fallback when nothing was displayed
        if layout.count() == 0:
            empty = QLabel(tr("component_detail_no_info"))
            empty.setObjectName("subtitle")
            empty.setWordWrap(True)
            layout.addWidget(empty)

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:  # noqa: BLE001
            try:
                webbrowser.open(url)
            except Exception:
                pass


class LabelPrintDialog(QDialog):
    """Dialog for choosing print mode and label size."""

    # Preset label sizes in cm (width:height = 2:1)
    PRESET_SIZES = [
        (4, 2),
        (6, 3),
        (8, 4),
        (10, 5),
        (15, 7.5),
        (20, 10),
        (30, 15),
        (40, 20),
        (50, 25),
        (60, 30),
    ]

    def __init__(self, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("printer_label_settings"))
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)
        self.setStyleSheet("LabelPrintDialog { background: white; }")

        self._pixmap = pixmap
        self._selected_size = self.PRESET_SIZES[5]  # Default: 20x10 cm
        self._preview_scale = 1.0
        self._mode = "save"  # Default mode

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Preview area
        preview_title = QLabel(tr("printer_preview"))
        preview_title.setObjectName("h3")
        layout.addWidget(preview_title)

        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setMinimumHeight(180)
        self._preview_label.setStyleSheet(
            "QLabel { border: 1px dashed #999; border-radius: 4px; background: #f5f5f5; }"
        )
        layout.addWidget(self._preview_label, 1)

        # Size selection
        size_title = QLabel(tr("printer_label_size"))
        size_title.setObjectName("h3")
        layout.addWidget(size_title)

        self._size_group = QButtonGroup(self)
        self._size_group.setExclusive(True)

        sizes_grid = QHBoxLayout()
        sizes_grid.setSpacing(8)

        self._size_buttons = []
        for i, (w, h) in enumerate(self.PRESET_SIZES):
            btn = QPushButton(f"{int(w)}×{int(h)} {tr('unit_cm')}")
            btn.setCheckable(True)
            btn.setObjectName("labelSizeBtn")
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda checked, idx=i: self._on_size_selected(idx))
            self._size_group.addButton(btn, i)
            self._size_buttons.append(btn)
            sizes_grid.addWidget(btn)

        layout.addLayout(sizes_grid)

        # Show selected size info
        self._size_info = QLabel()
        self._size_info.setObjectName("subtitle")
        layout.addWidget(self._size_info)

        # Actions
        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)

        self._save_btn = OutlineButton(tr("printer_save_image"))
        self._save_btn.clicked.connect(self._on_save)
        action_layout.addWidget(self._save_btn)

        action_layout.addStretch()

        self._print_btn = SuccessButton(tr("printer_print_direct"))
        self._print_btn.clicked.connect(self._on_print)
        action_layout.addWidget(self._print_btn)

        layout.addLayout(action_layout)

        # Select default size
        self._size_buttons[self.PRESET_SIZES.index(self._selected_size)].setChecked(True)
        self._update_preview()

    def _on_size_selected(self, index: int) -> None:
        self._selected_size = self.PRESET_SIZES[index]
        self._update_preview()

    def _update_preview(self) -> None:
        w_cm, h_cm = self._selected_size
        self._size_info.setText(
            tr("printer_selected_size", f"{int(w_cm)}×{int(h_cm)} {tr('unit_cm')}")
        )

        # Update preview
        if self._pixmap.isNull():
            return

        # Scale preview to fit label
        label_width = self._preview_label.width() - 30
        label_height = self._preview_label.height() - 30

        # Calculate scale factor based on aspect ratio (2:1)
        aspect_ratio = w_cm / h_cm  # Should be 2:1

        # Fit into preview area
        if label_width / aspect_ratio <= label_height:
            preview_w = label_width
            preview_h = label_width / aspect_ratio
        else:
            preview_h = label_height
            preview_w = label_height * aspect_ratio

        # Scale pixmap to fit within preview dimensions
        pix_w = self._pixmap.width()
        pix_h = self._pixmap.height()

        # Calculate scale to fit pixmap into preview
        scale = min(preview_w / pix_w, preview_h / pix_h, 1.0)

        target_w = int(pix_w * scale)
        target_h = int(pix_h * scale)

        scaled = self._pixmap.scaled(
            target_w, target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self._preview_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_preview()

    def selected_size_cm(self) -> tuple:
        """Return selected (width_cm, height_cm)."""
        return self._selected_size

    def mode(self) -> str:
        """Return 'save' or 'print'."""
        return self._mode

    def _on_save(self) -> None:
        self._mode = "save"
        self.accept()

    def _on_print(self) -> None:
        self._mode = "print"
        self.accept()
