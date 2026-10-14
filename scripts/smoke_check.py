"""Check startup and resources with isolated data, without contacting LCSC."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import main
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.app_container import AppContainer
from app.i18n import translator, tr
from app.ui.main_window import MainWindow


def run() -> None:
    with TemporaryDirectory(prefix="lcsc-erp-smoke-") as directory:
        root = Path(directory)
        with patch.dict(os.environ, {"APPDATA": str(root), "LCSC_ERP_DATA_DIR": ""}):
            with patch.object(sys, "frozen", True, create=True):
                config_dir = main._config_dir()
                config_dir.mkdir(parents=True, exist_ok=True)
                custom_dir = root / "inventory"
                (config_dir / "config.ini").write_text(
                    "[data]\ndir=" + str(custom_dir) + "\n", encoding="utf-8"
                )
                assert main._resolve_data_dir() == custom_dir
                assert main._config_dir() == config_dir
            application = QApplication([])
            container = AppContainer(root / "data", project_dir=root)
            window = MainWindow(
                home_vm=container.home_view_model,
                inbound_vm=container.inbound_view_model,
                search_vm=container.search_view_model,
                inventory_vm=container.inventory_view_model,
                settings_vm=container.settings_view_model,
            )
            try:
                assert tr("settings_title") != "settings_title"
                translator().set_language("en")
                assert tr("settings_title") == "Settings"
                translator().set_language("zh")
                assert window._stack.count() == 5
                window.show()
                QTimer.singleShot(200, application.quit)
                assert application.exec() == 0
            finally:
                window.close()
                container._thread_pool.waitForDone()
                container.close()
    print("PASS: persistent config, zh/en resources, five pages, startup event loop")


if __name__ == "__main__":
    run()
