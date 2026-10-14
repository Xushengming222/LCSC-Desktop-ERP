"""Settings page — port of feature/settings/SettingsScreen.kt.

Language picker, inventory backup (export/import to .xlsx with progress), and
an about section. Mirrors the Android ``SettingsContent`` sections, sourced
from the zh/en string tables.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..data.preferences import LANGUAGE_EN, LANGUAGE_ZH
from ..i18n import tr
from ..viewmodels.settings_viewmodel import SettingsViewModel
from .widgets import Card, Heading, OutlineButton, Subtitle


class SettingsPage(QWidget):
    def __init__(self, view_model: SettingsViewModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._vm = view_model

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        self._heading = Heading(tr("settings_title"))
        root.addWidget(self._heading)

        # Language
        self._lang_card = Card()
        self._lang_title = QLabel()
        self._lang_title.setObjectName("h3")
        self._lang_card.addWidget(self._lang_title)
        self._radio_zh = QRadioButton()
        self._radio_en = QRadioButton()
        self._radio_zh.toggled.connect(self._on_language_toggled)
        self._radio_en.toggled.connect(self._on_language_toggled)
        self._lang_card.addWidget(self._radio_zh)
        self._lang_card.addWidget(self._radio_en)
        root.addWidget(self._lang_card)

        # Inventory backup
        self._backup_card = Card()
        self._backup_title = QLabel()
        self._backup_title.setObjectName("h3")
        self._backup_card.addWidget(self._backup_title)

        self._export_btn = OutlineButton()
        self._export_btn.clicked.connect(self._on_export)
        self._export_summary = QLabel()
        self._export_summary.setObjectName("subtitle")
        export_row = QHBoxLayout()
        export_row.addWidget(self._export_btn)
        export_row.addWidget(self._export_summary, 1)
        self._backup_card.addLayout(export_row)

        self._import_btn = OutlineButton()
        self._import_btn.clicked.connect(self._on_import)
        self._import_summary = QLabel()
        self._import_summary.setObjectName("subtitle")
        import_row = QHBoxLayout()
        import_row.addWidget(self._import_btn)
        import_row.addWidget(self._import_summary, 1)
        self._backup_card.addLayout(import_row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._backup_card.addWidget(self._progress)
        self._backup_message = QLabel()
        self._backup_message.setWordWrap(True)
        self._backup_card.addWidget(self._backup_message)
        root.addWidget(self._backup_card)

        # Data directory
        self._datadir_card = Card()
        self._datadir_title = QLabel()
        self._datadir_title.setObjectName("h3")
        self._datadir_card.addWidget(self._datadir_title)
        self._datadir_summary = QLabel()
        self._datadir_summary.setObjectName("subtitle")
        self._datadir_summary.setWordWrap(True)
        self._datadir_card.addWidget(self._datadir_summary)

        self._datadir_current_label = QLabel()
        self._datadir_current_label.setObjectName("subtitle")
        self._datadir_card.addWidget(self._datadir_current_label)
        self._datadir_current_value = QLabel()
        self._datadir_current_value.setStyleSheet(
            f"background: {theme.SURFACE_VARIANT}; border-radius: 6px; padding: 6px 10px;"
        )
        self._datadir_current_value.setWordWrap(True)
        self._datadir_card.addWidget(self._datadir_current_value)

        self._datadir_default_label = QLabel()
        self._datadir_default_label.setObjectName("subtitle")
        self._datadir_card.addWidget(self._datadir_default_label)
        self._datadir_default_value = QLabel()
        self._datadir_default_value.setStyleSheet(
            f"background: {theme.SURFACE_VARIANT}; border-radius: 6px; padding: 6px 10px;"
        )
        self._datadir_default_value.setWordWrap(True)
        self._datadir_card.addWidget(self._datadir_default_value)

        self._datadir_copy_check = QCheckBox()
        self._datadir_card.addWidget(self._datadir_copy_check)

        datadir_btn_row = QHBoxLayout()
        self._datadir_browse_btn = OutlineButton()
        self._datadir_browse_btn.clicked.connect(self._on_browse_data_dir)
        datadir_btn_row.addWidget(self._datadir_browse_btn)
        self._datadir_reset_btn = OutlineButton()
        self._datadir_reset_btn.clicked.connect(self._on_reset_data_dir)
        datadir_btn_row.addWidget(self._datadir_reset_btn)
        datadir_btn_row.addStretch()
        self._datadir_card.addLayout(datadir_btn_row)

        self._datadir_restart_hint = QLabel()
        self._datadir_restart_hint.setStyleSheet(
            f"color: {theme.ERROR}; font-weight: 500;"
        )
        self._datadir_restart_hint.setWordWrap(True)
        self._datadir_card.addWidget(self._datadir_restart_hint)
        root.addWidget(self._datadir_card)

        # About
        self._about_card = Card()
        self._about_title = QLabel()
        self._about_title.setObjectName("h3")
        self._about_card.addWidget(self._about_title)
        self._about_summary = QLabel()
        self._about_summary.setObjectName("subtitle")
        self._about_card.addWidget(self._about_summary)
        self._about_body = QLabel()
        self._about_body.setWordWrap(True)
        self._about_body.setOpenExternalLinks(True)
        self._about_card.addWidget(self._about_body)
        self._stack_title = QLabel()
        self._stack_title.setObjectName("h3")
        self._about_card.addWidget(self._stack_title)
        self._stack_body = QLabel()
        self._stack_body.setWordWrap(True)
        self._stack_body.setStyleSheet(
            f"background: {theme.SURFACE_VARIANT}; border-radius: 8px; padding: 8px;"
        )
        self._about_card.addWidget(self._stack_body)
        root.addWidget(self._about_card)
        root.addStretch()

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._vm.ui_state_changed.connect(self.refresh)
        self.refresh()

    def _on_language_toggled(self) -> None:
        # Avoid feedback loops: only act when a radio becomes checked.
        if not self._radio_zh.isChecked() and not self._radio_en.isChecked():
            return
        state = self._vm.ui_state
        if state is None:
            return
        desired = LANGUAGE_ZH if self._radio_zh.isChecked() else LANGUAGE_EN
        if desired != state.selected_language_tag:
            self._vm.on_language_selected(desired)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("settings_export_inventory"), "lcsc_inventory_backup.xlsx", "Excel files (*.xlsx)"
        )
        if not path:
            return
        self._vm.export_inventory(path)

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("settings_import_inventory"), "", "Excel files (*.xlsx)"
        )
        if not path:
            return
        confirm = QMessageBox.question(
            self,
            tr("settings_import_inventory"),
            tr("settings_import_inventory_summary"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._vm.import_inventory(path)

    def _on_browse_data_dir(self) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        start_dir = state.current_data_dir or state.default_data_dir
        path = QFileDialog.getExistingDirectory(
            self,
            tr("settings_data_dir_browse"),
            start_dir,
            QFileDialog.ShowDirsOnly,
        )
        if not path:
            return
        copy_data = self._datadir_copy_check.isChecked()
        if copy_data:
            confirm = QMessageBox.question(
                self,
                tr("settings_data_dir"),
                tr("settings_data_dir_copy_confirm"),
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
        else:
            confirm = QMessageBox.warning(
                self,
                tr("settings_data_dir"),
                tr("settings_data_dir_no_copy_warning"),
                QMessageBox.Ok | QMessageBox.Cancel,
            )
            if confirm != QMessageBox.Ok:
                return
        error = self._vm.set_data_dir(path, copy_data=copy_data)
        if error:
            QMessageBox.warning(self, tr("settings_data_dir"), error)
        else:
            QMessageBox.information(
                self,
                tr("settings_data_dir"),
                tr("settings_data_dir_need_restart"),
            )

    def _on_reset_data_dir(self) -> None:
        confirm = QMessageBox.question(
            self,
            tr("settings_data_dir"),
            tr("settings_data_dir_reset_confirm"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        error = self._vm.reset_data_dir()
        if error:
            QMessageBox.warning(self, tr("settings_data_dir"), error)
        else:
            QMessageBox.information(
                self,
                tr("settings_data_dir"),
                tr("settings_data_dir_need_restart"),
            )

    def refresh(self) -> None:
        state = self._vm.ui_state
        if state is None:
            return
        content = state.content
        self._lang_title.setText(content.language_title)
        self._radio_zh.setText(content.language_chinese)
        self._radio_en.setText(content.language_english)
        if state.selected_language_tag == LANGUAGE_EN:
            if not self._radio_en.isChecked():
                self._radio_en.setChecked(True)
        else:
            if not self._radio_zh.isChecked():
                self._radio_zh.setChecked(True)

        self._backup_title.setText(content.inventory_backup_title)
        self._export_btn.setText(content.export_inventory_title)
        self._export_summary.setText(content.export_inventory_summary)
        self._import_btn.setText(content.import_inventory_title)
        self._import_summary.setText(content.import_inventory_summary)

        self._progress.setVisible(state.is_processing_inventory_backup)
        if state.inventory_backup_progress is not None:
            self._progress.setValue(int(state.inventory_backup_progress * 100))
        else:
            self._progress.setValue(0)
        self._backup_message.setText(state.inventory_backup_message or "")
        self._export_btn.setEnabled(not state.is_processing_inventory_backup)
        self._import_btn.setEnabled(not state.is_processing_inventory_backup)

        self._datadir_title.setText(content.data_dir_title)
        self._datadir_summary.setText(content.data_dir_summary)
        self._datadir_current_label.setText(content.data_dir_current)
        self._datadir_current_value.setText(state.current_data_dir)
        self._datadir_default_label.setText(content.data_dir_default)
        self._datadir_default_value.setText(state.default_data_dir)
        self._datadir_copy_check.setText(content.data_dir_copy)
        self._datadir_browse_btn.setText(content.data_dir_browse)
        self._datadir_reset_btn.setText(content.data_dir_reset)
        self._datadir_reset_btn.setVisible(state.has_custom_data_dir)
        self._datadir_restart_hint.setText(
            content.data_dir_need_restart if state.has_custom_data_dir else ""
        )

        self._about_title.setText(content.about_title)
        self._about_summary.setText(content.about_summary)
        self._about_body.setText(content.about_body)
        self._stack_title.setText(tr("settings_stack_title"))
        self._stack_body.setText(content.stack_body)

    def retranslate_ui(self) -> None:
        self._heading.set_title(tr("settings_title"))
        self.refresh()
