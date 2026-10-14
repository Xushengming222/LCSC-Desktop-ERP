"""LCSC inbound QR parser — port of feature/inbound/LcscQrParser.kt + InboundQrPayload.kt.

Parses the lightweight ``{on:,pc:C123,pm:,qty:10,...}`` QR payload format used
by LCSC inbound labels. Not real JSON — fields are comma-separated ``key:value``
pairs with optional quotes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InboundQrPayload:
    order_no: str | None
    part_number: str
    manufacturer_part_no: str | None
    quantity: int
    raw_text: str
    extra_fields: dict[str, str] = field(default_factory=dict)


def _first_case_insensitive_value(fields: dict[str, str], target_key: str) -> str | None:
    for key, value in fields.items():
        if key.lower() == target_key.lower():
            return value
    return None


def parse_lcsc_qr(raw_text: str) -> InboundQrPayload | None:
    normalized = raw_text.strip()
    if not normalized.startswith("{") or not normalized.endswith("}"):
        return None
    content = normalized[1:-1]
    if not content.strip():
        return None

    fields: dict[str, str] = {}
    for token in content.split(","):
        parts = token.split(":", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip().strip('"').strip("'").strip()
        value = parts[1].strip().strip('"').strip("'").strip()
        if key:
            fields[key] = value

    part_number_raw = _first_case_insensitive_value(fields, "pc")
    if part_number_raw is None:
        return None
    part_number = part_number_raw.strip().upper()
    if not part_number.startswith("C"):
        return None

    quantity_raw = _first_case_insensitive_value(fields, "qty")
    try:
        quantity = int(quantity_raw.strip()) if quantity_raw else 0
    except ValueError:
        quantity = 0

    order_no = _first_case_insensitive_value(fields, "on")
    manufacturer_part_no = _first_case_insensitive_value(fields, "pm")

    return InboundQrPayload(
        order_no=order_no if order_no and order_no.strip() else None,
        part_number=part_number,
        manufacturer_part_no=manufacturer_part_no if manufacturer_part_no and manufacturer_part_no.strip() else None,
        quantity=quantity,
        raw_text=raw_text,
        extra_fields=fields,
    )
