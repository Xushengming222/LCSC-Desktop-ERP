"""Component category → storage location code mapping.

Mirrors the PCB reference designator convention used on schematics:
resistors use ``R``, capacitors ``C``, ICs ``U``, diodes ``D``, etc.
When a component is searched for inbound, its LCSC ``category`` string
(e.g. ``电阻器``, ``电容器``, ``集成电路``) is matched against this
mapping to suggest a default warehouse code.
"""
from __future__ import annotations

import re

# PCB reference designator → list of category keywords (Chinese + English).
# The first matching entry wins; order matters (more specific first).
# Match rules (see ``suggest_location_code`` below):
#   1) An "anchor" keyword matched as a WHOLE TOKEN wins (e.g. "电阻"
#      inside "贴片电阻器" or "电阻网络" → R).
#   2) If no anchor matched, fall back to any single keyword substring.
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    # Resistors
    ("R", ["电阻", "电阻器", "resistor", "排阻", "resistor network", "可调电阻", "电位器"]),
    # Capacitors
    ("C", ["电容", "电容器", "capacitor", "陶瓷电容", "电解电容", "贴片电容", "钽电容"]),
    # Inductors / ferrite beads
    ("L", ["电感", "电感器", "inductor", "磁珠", "ferrite", "ferrite bead", "扼流圈"]),
    # Diodes (incl. TVS, Zener, Schottky, LED)
    ("D", ["二极管", "二极管/LED", "diode", "稳压二极管", "zener", "肖特基", "schottky",
           "TVS", "瞬态抑制", "整流二极管", "发光二极管", "led", "LED"]),
    # Transistors (BJT, MOSFET, IGBT)
    ("Q", ["三极管", "晶体管", "transistor", "MOSFET", "场效应管", "IGBT",
           "双极型", "bipolar", "达林顿", "darlington"]),
    # Integrated circuits
    ("U", ["集成电路", "IC", "芯片", "chip", "单片机", "MCU", "MPU",
           "运放", "op-amp", "operational amplifier", "逻辑IC", "logic",
           "电源IC", "power management", "PMIC", "存储器", "memory",
           "EEPROM", "Flash", "FPGA", "CPLD", "DSP", "SoC", "模块",
           "module", "传感器", "sensor", "继电器驱动"]),
    # Connectors / headers
    ("J", ["连接器", "connector", "排针", "header", "排母", "插座",
           "socket", "接线端子", "terminal", "航空插头"]),
    # Relays
    ("K", ["继电器", "relay", "干簧管", "reed relay"]),
    # Crystals / oscillators
    ("Y", ["晶振", "crystal", "振荡器", "oscillator", "谐振器", "resonator",
           "陶瓷晶振", "有源晶振", "无源晶振"]),
    # Fuses / PTC
    ("F", ["保险丝", "fuse", "PTC", "自恢复保险丝", "熔断器"]),
    # Switches / buttons
    ("SW", ["开关", "switch", "按键", "button", "拨码开关", "dip switch",
            "轻触开关", "微动开关", "toggle"]),
    # Transformers
    ("T", ["变压器", "transformer", "互感器", "电流互感器"]),
    # Optocouplers
    ("U", ["光耦", "optocoupler", "光隔离", "opto-isolator"]),
    # Buzzers / speakers
    ("BZ", ["蜂鸣器", "buzzer", "扬声器", "speaker"]),
    # Batteries / battery holders
    ("BAT", ["电池", "battery", "电池座", "battery holder", "纽扣电池"]),
    # Test points
    ("TP", ["测试点", "test point"]),
]


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", "", text.strip().lower())


def suggest_location_code(category: str | None, name: str | None = None) -> str | None:
    """Return a suggested storage-location code (e.g. ``R``) for a component.

    Matches against the LCSC ``category`` first, then falls back to the
    component ``name``.  The algorithm is robust to compound category
    strings like ``"贴片电阻器 / Chip Resistor"``:

    * Any anchor keyword (shorter than the full category) contained inside
      the normalized haystack is taken as a positive token match.
    * If no anchor matched, fall back to any substring match.

    Returns ``None`` if no rule matches.
    """
    haystack = _normalize(f"{category or ''} {name or ''}")
    if not haystack:
        return None

    # Pass 1: prefer short "anchor" keywords (≤ 3 chars) as token matches.
    for code, keywords in _CATEGORY_RULES:
        for kw in keywords:
            norm_kw = _normalize(kw)
            if not norm_kw:
                continue
            if len(norm_kw) <= 3 and norm_kw in haystack:
                return code

    # Pass 2: any keyword substring match.
    for code, keywords in _CATEGORY_RULES:
        for kw in keywords:
            norm_kw = _normalize(kw)
            if norm_kw and norm_kw in haystack:
                return code
    return None


def default_location_codes() -> list[str]:
    """Return the list of warehouse codes that should be bootstrapped.

    These correspond to the most common PCB reference designators so that
    every component type has a home on first run.
    """
    # Preserve insertion order, deduplicate (U appears twice in rules).
    seen: set[str] = set()
    codes: list[str] = []
    for code, _ in _CATEGORY_RULES:
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes
