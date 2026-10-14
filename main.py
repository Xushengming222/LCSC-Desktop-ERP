"""LCSC Desktop ERP — application entry point.

Bootstraps the ``AppContainer`` (DB, repositories, view models), applies the
saved language, constructs the ``MainWindow``, and runs the Qt event loop.

Usage:
    python main.py
"""
from __future__ import annotations

import configparser
import logging
import os
import sys
from pathlib import Path

# Make the ``app`` package importable when running ``python main.py`` from the
# project root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

_PROJECT_DIR = Path(__file__).resolve().parent


def _default_data_dir() -> Path:
    """Return the default data directory when no custom path is configured."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "LCSC_ERP"
    return Path.home() / ".lcsc_erp"


def _config_dir() -> Path:
    """Use writable settings for installed/frozen apps; retain source-checkout config."""
    if getattr(sys, "frozen", False) or not (_PROJECT_DIR / "pyproject.toml").exists():
        return _default_data_dir()
    return _PROJECT_DIR


def _resolve_data_dir() -> Path:
    """Return the per-user data directory for the ERP database + preferences."""
    override = os.environ.get("LCSC_ERP_DATA_DIR")
    if override:
        return Path(override)
    config_path = _config_dir() / "config.ini"
    if config_path.exists():
        try:
            config = configparser.ConfigParser()
            config.read(config_path, encoding="utf-8")
            if config.has_section("data") and config.has_option("data", "dir"):
                candidate = config.get("data", "dir").strip()
                if candidate:
                    return Path(candidate)
        except Exception:
            pass
    return _default_data_dir()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # High-DPI scaling (Qt6 enables this by default, but be explicit).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("LCSC Desktop ERP")
    app.setOrganizationName("LCSC")

    # Apply the QSS theme.
    from app import theme

    app.setStyleSheet(theme.QSS)

    from app.app_container import AppContainer
    from app.ui.main_window import MainWindow

    data_dir = _resolve_data_dir()
    container = AppContainer(data_dir, project_dir=_config_dir())

    window = MainWindow(
        home_vm=container.home_view_model,
        inbound_vm=container.inbound_view_model,
        search_vm=container.search_view_model,
        inventory_vm=container.inventory_view_model,
        settings_vm=container.settings_view_model,
    )
    window.show()

    exit_code = app.exec()
    container.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
