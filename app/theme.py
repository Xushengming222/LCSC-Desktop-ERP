"""Material-style color tokens and QSS stylesheet (mirrors ui/theme/Color.kt)."""
from __future__ import annotations

# Light palette (from Color.kt)
PRIMARY = "#1565C0"          # Blue40
ON_PRIMARY = "#FFFFFF"
PRIMARY_CONTAINER = "#D1E4FF"
SECONDARY = "#5F6B7A"        # Slate40
TERTIARY = "#2E7D32"         # Green40 (confirm / in-stock accent)
TERTIARY_CONTAINER = "#C8E6C9"
BACKGROUND = "#F5F7FA"       # LightBackground
SURFACE = "#FFFFFF"          # LightSurface
SURFACE_VARIANT = "#E7ECF3"  # LightSurfaceVariant
OUTLINE = "#728196"          # LightOutline
OUTLINE_VARIANT = "#D1D9E4"  # LightOutlineVariant
ON_SURFACE = "#12181F"       # LightOnSurface
ON_SURFACE_VARIANT = "#5B6470"
ERROR = "#B00020"
ERROR_CONTAINER = "#FDE7E9"
WARNING_BG = "#FFF3C4"
WARNING_FG = "#6B4F00"
WARNING_FG_DARK = "#4A3600"
TAOBAO_DOT = "#FF6A00"
LABEL_BG = "#F5F7FA"
LABEL_CARD = "#FFFFFF"
LABEL_BORDER = "#DCE3EA"
LABEL_MEDIA = "#EEF2F6"
LABEL_TITLE = "#111827"
LABEL_SUBTITLE = "#5B6470"

PRESET_LOCATION_COLORS = ["#C8E6C9", "#B3E5FC", "#F8BBD0", "#D1C4E9", "#FFE0B2"]

QSS = f"""
QWidget {{
    color: {ON_SURFACE};
    font-size: 14px;
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
}}
QMainWindow, QWidget#central {{ background: {BACKGROUND}; }}

/* Side navigation */
QListWidget#navList {{
    background: {SURFACE};
    border: none;
    border-right: 1px solid {OUTLINE_VARIANT};
    outline: none;
    font-size: 15px;
    padding: 8px 0px;
}}
QListWidget#navList::item {{
    padding: 14px 20px;
    border-left: 3px solid transparent;
}}
QListWidget#navList::item:selected {{
    background: {PRIMARY_CONTAINER};
    color: {PRIMARY};
    border-left: 3px solid {PRIMARY};
    font-weight: 600;
}}
QListWidget#navList::item:hover {{
    background: {SURFACE_VARIANT};
}}

QStackedWidget {{ background: {BACKGROUND}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: {SURFACE_VARIANT}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {OUTLINE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: {SURFACE_VARIANT}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {OUTLINE}; border-radius: 5px; min-width: 30px; }}

QLabel#h1 {{ font-size: 24px; font-weight: 700; color: {ON_SURFACE}; }}
QLabel#h2 {{ font-size: 20px; font-weight: 600; color: {ON_SURFACE}; }}
QLabel#h3 {{ font-size: 16px; font-weight: 600; color: {ON_SURFACE}; }}
QLabel#subtitle {{ color: {ON_SURFACE_VARIANT}; }}
QLabel#value {{ font-size: 22px; font-weight: 700; }}

QPushButton {{
    background: {PRIMARY};
    color: {ON_PRIMARY};
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 500;
}}
QPushButton:hover {{ background: #0D47A1; }}
QPushButton:pressed {{ background: #0A3D8F; }}
QPushButton:disabled {{ background: {OUTLINE_VARIANT}; color: {OUTLINE}; }}

QPushButton#outline {{
    background: transparent;
    color: {PRIMARY};
    border: 1px solid {PRIMARY};
    padding: 6px 16px;
    border-radius: 4px;
}}
QPushButton#outline:hover {{ background: {PRIMARY_CONTAINER}; }}

QPushButton#textBtn {{
    background: transparent;
    color: {PRIMARY};
    padding: 4px 8px;
    border: none;
    text-decoration: none;
}}
QPushButton#textBtn:hover {{
    background: transparent;
    text-decoration: underline;
}}

QPushButton#danger {{
    background: {ERROR};
    color: white;
    padding: 4px 12px;
    border: none;
}}
QPushButton#danger:hover {{ background: #8E0018; }}

QPushButton#success {{
    background: {TERTIARY};
    color: white;
    padding: 6px 16px;
    border: none;
}}
QPushButton#success:hover {{ background: #1B5E20; }}

QPushButton#labelSizeBtn {{
    background: {SURFACE};
    color: {ON_SURFACE};
    border: 1px solid {OUTLINE};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}
QPushButton#labelSizeBtn:hover {{ background: {SURFACE_VARIANT}; }}
QPushButton#labelSizeBtn:checked {{
    background: {PRIMARY_CONTAINER};
    color: {PRIMARY};
    border: 1px solid {PRIMARY};
    font-weight: 600;
}}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {SURFACE};
    border: 1px solid {OUTLINE};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {PRIMARY_CONTAINER};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {PRIMARY};
    padding: 7px 9px;
}}

QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {OUTLINE_VARIANT};
    selection-background-color: {PRIMARY_CONTAINER};
    selection-color: {PRIMARY};
    outline: none;
}}

QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {ON_SURFACE_VARIANT};
    padding: 10px 22px;
    border: none;
    border-bottom: 3px solid transparent;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    color: {PRIMARY};
    border-bottom: 3px solid {PRIMARY};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ color: {PRIMARY}; }}

QGroupBox#card {{
    background: {SURFACE};
    border: 1px solid {OUTLINE_VARIANT};
    border-radius: 12px;
    margin-top: 14px;
    padding: 14px;
}}
QGroupBox#card::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: {ON_SURFACE};
    font-weight: 600;
}}

QDialog {{ background: {SURFACE}; }}

QProgressBar {{
    background: {SURFACE_VARIANT};
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 6px; }}

QToolBar {{ background: {SURFACE}; border: none; border-top: 1px solid {OUTLINE_VARIANT}; spacing: 4px; padding: 4px; }}
QToolBar QToolButton {{ background: transparent; border: none; padding: 8px 16px; border-radius: 8px; }}
QToolBar QToolButton:checked {{ background: {PRIMARY_CONTAINER}; color: {PRIMARY}; }}

QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; }}
QRadioButton::indicator {{ border: 2px solid {OUTLINE}; border-radius: 10px; background: {SURFACE}; }}
QRadioButton::indicator:checked {{ border-color: {PRIMARY}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {PRIMARY}, stop:0.4 {PRIMARY}, stop:0.5 white, stop:1 white); }}

QSplitter::handle {{ background: {OUTLINE_VARIANT}; }}
QListView#locGrid {{ background: transparent; }}
QListView::item {{ border-radius: 8px; }}
"""


def luminance(hex_color: str) -> float:
    """Relative luminance of a #RRGGBB color (0..1)."""
    color = hex_color.lstrip("#")
    if len(color) != 6:
        return 1.0
    r = int(color[0:2], 16) / 255
    g = int(color[2:4], 16) / 255
    b = int(color[4:6], 16) / 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_color_for(hex_color: str | None) -> str:
    """Pick black/white text for a background color (luminance > 0.62 -> dark text)."""
    if not hex_color:
        return ON_SURFACE
    return "#111827" if luminance(hex_color) > 0.62 else "#FFFFFF"
