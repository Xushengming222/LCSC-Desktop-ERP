"""Label printing — desktop replacement for the Android Deli Q5 Bluetooth printer.

The Android app drives a Deli Q5 Bluetooth label printer (Android-only). On
desktop we replace that with two steps, both user-confirmed in the summary:

1. **Save** the rendered label PNG to ``~/Pictures/LCSC ERP/`` (mirroring the
   Android ``MediaStore.Images`` gallery save).
2. **Print** via the system ``QPrintDialog``, scaling the 1200×720 image to
   fit the chosen printer's page, or printing at exact physical size.

This module wraps both steps. The label images themselves are produced by
``app/data/qr_exporter.py`` (component inbound label) and
``app/data/label_exporter.py`` (storage location label).
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QMessageBox, QWidget

from ..i18n import tr

# Default label output directory (mirrors Android's Pictures/LCSC ERP).
_DEFAULT_LABEL_DIR = Path.home() / "Pictures" / "LCSC ERP"

# Conversion: 1 cm = 37.7952755906 pixels at 96 DPI
_CM_TO_PX_96DPI = 37.7952755906


def label_output_dir() -> Path:
    """Return (creating if needed) the directory where label PNGs are saved."""
    try:
        _DEFAULT_LABEL_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fall back to a temp-ish dir under the user home if Pictures is unavailable.
        fallback = Path.home() / ".lcsc_erp" / "labels"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    return _DEFAULT_LABEL_DIR


def _build_file_name(base: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_base = "".join(c if c.isalnum() or c in "._-" else "_" for c in base.strip()) or "label"
    return f"{safe_base}_{timestamp}.png"


def save_label_image(image: Image.Image, base_name: str) -> Path:
    """Save a PIL image as a PNG to the label directory and return its path."""
    out_dir = label_output_dir()
    file_name = _build_file_name(base_name)
    path = out_dir / file_name
    image.save(str(path), format="PNG")
    return path


def _pil_to_pixmap(image: Image.Image) -> QPixmap:
    """Convert a PIL RGB image to a QPixmap."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    from io import BytesIO

    buf = BytesIO()
    image.save(buf, format="PNG")
    pix = QPixmap()
    pix.loadFromData(buf.getvalue(), "PNG")
    return pix


def print_image(image: Image.Image, parent: Optional[QWidget] = None) -> bool:
    """Open the system print dialog and print ``image`` scaled to fit the page.

    Returns True if a print job was actually started, False otherwise.
    """
    printer = QPrinter(QPrinter.HighResolution)
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(tr("printer_print_label"))
    if dialog.exec() != QPrintDialog.Accepted:
        return False

    pixmap = _pil_to_pixmap(image)
    if pixmap.isNull():
        QMessageBox.warning(parent, tr("printer_print_label"), tr("printer_not_connected"))
        return False

    painter = QPainter(printer)
    try:
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        target = QRectF(0, 0, page_rect.width(), page_rect.height())
        source = QRectF(0, 0, pixmap.width(), pixmap.height())
        # Scale to fit while preserving aspect ratio (centered).
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scaled = source
        scale = min(target.width() / source.width(), target.height() / source.height())
        draw_w = source.width() * scale
        draw_h = source.height() * scale
        draw_x = (target.width() - draw_w) / 2.0
        draw_y = (target.height() - draw_h) / 2.0
        painter.drawPixmap(QRectF(draw_x, draw_y, draw_w, draw_h), pixmap, source)
    finally:
        painter.end()
    return True


def print_image_at_size(
    image: Image.Image,
    width_cm: float,
    height_cm: float,
    parent: Optional[QWidget] = None,
) -> bool:
    """Print image at exact physical size in centimeters.

    Converts the requested physical size to printer pixels using the
    printer's actual resolution (DPI), so the printed label matches the
    chosen dimensions regardless of driver DPI, device-pixel ratio, or
    coordinate-mode quirks.

    Returns True if a print job was actually started, False otherwise.
    """
    printer = QPrinter(QPrinter.HighResolution)
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(tr("printer_print_label"))
    if dialog.exec() != QPrintDialog.Accepted:
        return False

    pixmap = _pil_to_pixmap(image)
    if pixmap.isNull():
        QMessageBox.warning(parent, tr("printer_print_label"), tr("printer_not_connected"))
        return False

    # Printer resolution is in dots-per-inch (DPI). 1 inch = 25.4 mm.
    resolution = printer.resolution() or 300  # sensible fallback
    mm_to_px = resolution / 25.4

    # Target size in printer pixels (true physical size).
    target_w_px = width_cm * 10.0 * mm_to_px
    target_h_px = height_cm * 10.0 * mm_to_px

    painter = QPainter(printer)
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Page rect in device pixels for correct centering.
        page_rect = printer.pageRect(QPrinter.DevicePixel)

        # Center the label on the page.
        draw_x = (page_rect.width() - target_w_px) / 2.0
        draw_y = (page_rect.height() - target_h_px) / 2.0

        target_rect = QRectF(draw_x, draw_y, target_w_px, target_h_px)
        source_rect = QRectF(0, 0, pixmap.width(), pixmap.height())

        painter.drawPixmap(target_rect, pixmap, source_rect)
    finally:
        painter.end()
    return True


def save_and_print_component_label(
    component,
    parent: Optional[QWidget] = None,
    *,
    part_number_label: str = "编号",
    do_print: bool = True,
    print_size_cm: Optional[tuple] = None,
) -> Optional[Path]:
    """Render, save (and optionally print) a component inbound label.

    ``component`` is a ``ComponentDetail``. Returns the saved PNG path.
    """
    from ..data.qr_exporter import create_label_image

    image = create_label_image(component, part_number_label=part_number_label)
    path = save_label_image(image, f"component_{component.part_number}")
    if do_print:
        if print_size_cm:
            w_cm, h_cm = print_size_cm
            print_image_at_size(image, w_cm, h_cm, parent)
        else:
            print_image(image, parent)
    return path


def save_and_print_location_label(
    cell,
    inventory_count: int,
    parent: Optional[QWidget] = None,
    *,
    do_print: bool = True,
    print_size_cm: Optional[tuple] = None,
) -> Optional[Path]:
    """Render, save (and optionally print) a storage location label.

    ``cell`` is a ``StockLocationCell``. Returns the saved PNG path.
    """
    from ..data.label_exporter import create_location_label_image

    image = create_location_label_image(cell, inventory_count)
    path = save_label_image(image, f"location_{cell.code}")
    if do_print:
        if print_size_cm:
            w_cm, h_cm = print_size_cm
            print_image_at_size(image, w_cm, h_cm, parent)
        else:
            print_image(image, parent)
    return path
