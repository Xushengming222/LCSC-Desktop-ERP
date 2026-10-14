"""Location label exporter — port of feature/inventory/LocationLabelExporter.kt.

Renders a 1200×720 storage-location label (large location code on the left,
title / item count / total quantity on the right) as a PIL image and saves it
as a PNG. The Android version uses Canvas/Bitmap + MediaStore; here we use
Pillow and write to a user-chosen directory.
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..domain.models import StockLocationCell
from .qr_exporter import _load_font, _wrap_text, _measure_width

_BG = "#F5F7FA"
_CARD = "#FFFFFF"
_BORDER = "#DCE3EA"
_MEDIA_BG = "#EEF2F6"
_CODE = "#111827"
_TITLE = "#111827"
_SUBTITLE = "#5B6470"
_BODY = "#111827"


def _fit_single_line_size(text: str, max_width: int, max_height: int, min_size: int, max_size: int) -> int:
    if not text.strip():
        return min_size
    low, high, best = min_size, max_size, min_size
    for _ in range(24):
        mid = (low + high) // 2
        font = _load_font(mid, bold=True)
        try:
            bbox = font.getbbox(text)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except Exception:  # noqa: BLE001
            w = h = mid
        if w <= max_width and h <= max_height:
            best = mid
            low = mid
        else:
            high = mid
    return best


def create_location_label_image(
    cell: StockLocationCell,
    inventory_count: int,
    *,
    type_label: str = "库位标签",
    count_label_format: str = "物料数量：%1$d",
    quantity_label_format: str = "库存总数：%1$s",
    unknown_quantity_label: str = "未知",
    default_title: str = "库位标签",
) -> Image.Image:
    width, height = 1200, 720
    image = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(image)

    outer_padding = 12
    content_padding = 22
    section_gap = 22
    card_radius = 28
    media_size = height - outer_padding * 2 - content_padding * 2
    card_left = outer_padding
    card_top = outer_padding
    card_right = width - outer_padding
    card_bottom = height - outer_padding
    media_left = card_left + content_padding
    media_top = card_top + content_padding
    media_right = media_left + media_size
    media_bottom = media_top + media_size
    text_left = media_right + section_gap
    text_top = media_top
    text_right = card_right - content_padding
    text_width = text_right - text_left

    title = cell.display_name.strip() if cell.display_name and cell.display_name.strip() else default_title
    subtitle = type_label
    count_line = count_label_format.replace("%1$d", str(inventory_count))
    qty_text = str(cell.total_quantity) if cell.total_quantity != 0 else unknown_quantity_label
    quantity_line = quantity_label_format.replace("%1$s", qty_text)

    draw.rounded_rectangle([card_left, card_top, card_right, card_bottom], radius=card_radius, fill=_CARD)
    draw.rounded_rectangle([card_left, card_top, card_right, card_bottom], radius=card_radius, outline=_BORDER, width=2)
    draw.rounded_rectangle([media_left, media_top, media_right, media_bottom], radius=22, fill=_MEDIA_BG)

    code_text = cell.code.strip() or "-"
    code_inset = 36
    code_size = _fit_single_line_size(
        code_text,
        max_width=max(media_size - code_inset * 2, 1),
        max_height=max(media_size - code_inset * 2, 1),
        min_size=120,
        max_size=460,
    )
    code_font = _load_font(code_size, bold=True)
    try:
        bbox = code_font.getbbox(code_text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except Exception:  # noqa: BLE001
        text_w = text_h = code_size
    cx = media_left + media_size // 2
    cy = media_top + media_size // 2
    draw.text((cx - text_w // 2, cy - text_h // 2), code_text, font=code_font, fill=_CODE)

    title_font = _load_font(60, bold=True)
    subtitle_font = _load_font(38)
    body_font = _load_font(38)

    current_y = text_top
    current_y += _draw_block(draw, title, title_font, _TITLE, text_left, current_y, text_width, 3, 68) + 8
    current_y += _draw_block(draw, subtitle, subtitle_font, _SUBTITLE, text_left, current_y, text_width, 2, 46) + 10
    current_y += _draw_block(draw, count_line, body_font, _BODY, text_left, current_y, text_width, 2, 46) + 10
    _draw_block(draw, quantity_line, body_font, _BODY, text_left, current_y, text_width, 2, 46)
    return image


def _draw_block(draw, text, font, color, x, y, max_width, max_lines, line_height) -> int:
    lines = _wrap_text(text, font, draw, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            while lines[-1] and _measure_width(draw, lines[-1] + "…", font) > max_width:
                lines[-1] = lines[-1][:-1]
            lines[-1] = lines[-1] + "…"
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += line_height
    return len(lines) * line_height if lines else 0


def build_location_label_file_name(location_code: str) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"location_label_{location_code.strip()}_{timestamp}.png"


def save_location_label_image(
    cell: StockLocationCell,
    inventory_count: int,
    output_dir: str | Path,
    **label_kwargs,
) -> str:
    image = create_location_label_image(cell, inventory_count, **label_kwargs)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / build_location_label_file_name(cell.code)
    image.save(str(target), format="PNG")
    return str(target)
