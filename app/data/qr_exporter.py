"""Material QR code label exporter — port of feature/inbound/MaterialQrCodeExporter.kt.

Renders the 1200×720 inbound label (QR on the left, component info on the right)
to a PIL image and saves it as a PNG. The Android version uses Canvas/Bitmap;
here we use Pillow + qrcode. The gallery-save path becomes a filesystem write
to a user-chosen directory.
"""
from __future__ import annotations

import time
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

from ..domain.models import ComponentDetail

_BG = "#F5F7FA"
_CARD = "#FFFFFF"
_BORDER = "#DCE3EA"
_MEDIA_BG = "#EEF2F6"
_TITLE = "#111827"
_SUBTITLE = "#5B6470"
_BODY = "#111827"

_PREFERRED_SPEC_KEYS = ["电阻类型", "阻值", "容值", "精度", "功率"]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates += ["msyhbd.ttc", "msyhbd.ttf", "C:/Windows/Fonts/msyhbd.ttc"]
    candidates += ["msyh.ttc", "msyh.ttf", "C:/Windows/Fonts/msyh.ttc",
                   "DejaVuSans.ttf", "Arial.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    # final fallback (no CJK support but won't crash)
    return ImageFont.load_default()


def _wrap_text(text: str, font, draw: ImageDraw.ImageDraw, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        try:
            bbox = draw.textbbox((0, 0), candidate, font=font)
            width = bbox[2] - bbox[0]
        except AttributeError:
            width = draw.textlength(candidate, font=font)
        if width > max_width and current:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    color: str,
    x: int,
    y: int,
    max_width: int,
    max_lines: int,
    line_height: int,
) -> int:
    lines = _wrap_text(text, font, draw, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            while lines[-1] and _measure_width(draw, lines[-1] + "…", font) > max_width:
                lines[-1] = lines[-1][:-1]
            lines[-1] = lines[-1] + "…"
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += line_height
    return y - y + len(lines) * line_height if lines else 0


def _measure_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except AttributeError:
        return int(draw.textlength(text, font=font))


def _exporter_secondary_summary(component: ComponentDetail) -> str | None:
    items: list[str] = []
    for key in _PREFERRED_SPEC_KEYS:
        value = component.specifications.get(key)
        if value and value.strip():
            items.append(value.strip())
    remaining = {k: v for k, v in component.specifications.items() if k not in _PREFERRED_SPEC_KEYS}
    for key in sorted(remaining.keys()):
        value = remaining[key]
        if value and value.strip():
            items.append(value.strip())
    # distinct preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    summary = " · ".join(unique)
    return summary or None


def _create_qr_image(content: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size, size), Image.Resampling.NEAREST)


def create_label_image(
    component: ComponentDetail,
    part_number_label: str = "编号",
) -> Image.Image:
    """Render the 1200×720 inbound label as a PIL image."""
    width, height = 1200, 720
    image = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(60, bold=True)
    subtitle_font = _load_font(38)
    body_font = _load_font(38)

    outer_padding = 12
    content_padding = 22
    section_gap = 22
    card_radius = 28
    card_left = outer_padding
    card_top = outer_padding
    card_right = width - outer_padding
    card_bottom = height - outer_padding
    media_size = height - outer_padding * 2 - content_padding * 2
    media_left = card_left + content_padding
    media_top = card_top + content_padding
    media_right = media_left + media_size
    media_bottom = media_top + media_size
    qr_inset = 18
    text_left = media_right + section_gap
    text_top = media_top
    text_right = card_right - content_padding
    text_width = text_right - text_left

    subtitle_parts = [
        p for p in [component.brand, component.package_name, component.category] if p and p.strip()
    ]
    subtitle = " · ".join(subtitle_parts)
    secondary_summary = _exporter_secondary_summary(component)
    detail_line = f"{part_number_label}: {component.part_number}"

    # card
    draw.rounded_rectangle(
        [card_left, card_top, card_right, card_bottom], radius=card_radius, fill=_CARD
    )
    draw.rounded_rectangle(
        [card_left, card_top, card_right, card_bottom], radius=card_radius, outline=_BORDER, width=2
    )
    # media bg
    draw.rounded_rectangle(
        [media_left, media_top, media_right, media_bottom], radius=22, fill=_MEDIA_BG
    )

    payload = (
        f"{{on:,pc:{component.part_number.strip()},pm:,qty:,mc:,cc:,pdi:,hp:}}"
    )
    qr = _create_qr_image(payload, media_size - qr_inset * 2)
    image.paste(qr, (media_left + qr_inset, media_top + qr_inset))

    current_y = text_top
    title_text = component.name or component.mpn or component.part_number
    line_height = 68
    drawn = _draw_text_block(
        draw, title_text, title_font, _TITLE, text_left, current_y, text_width, 3, line_height
    )
    current_y += drawn + 8

    if subtitle:
        line_height = 46
        drawn = _draw_text_block(
            draw, subtitle, subtitle_font, _SUBTITLE, text_left, current_y, text_width, 3, line_height
        )
        current_y += drawn + 10

    if secondary_summary:
        line_height = 46
        drawn = _draw_text_block(
            draw, secondary_summary, body_font, _BODY, text_left, current_y, text_width, 3, line_height
        )
        current_y += drawn + 12

    line_height = 46
    _draw_text_block(
        draw, detail_line, body_font, _BODY, text_left, current_y, text_width, 3, line_height
    )
    return image


def build_file_name(part_number: str) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"material_qr_{part_number.strip()}_{timestamp}.png"


def save_label_image(
    component: ComponentDetail,
    output_dir: str | Path,
    part_number_label: str = "编号",
) -> str:
    """Render the label and save as PNG to ``output_dir``. Returns the file path."""
    image = create_label_image(component, part_number_label)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    file_name = build_file_name(component.part_number)
    target = out / file_name
    image.save(str(target), format="PNG")
    return str(target)
