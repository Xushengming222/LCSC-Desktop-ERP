"""SettingsViewModel — port of feature/settings/SettingsViewModel.kt.

Combines the user preferences with a mutable screen state (backup progress /
message) and the loaded settings content (which is just the i18n strings, since
the Android ``settings_content.json`` asset is replaced by the zh/en string
tables in this desktop port). Export/import run on the thread pool and report
progress via callbacks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QThreadPool

from ..data.backup_manager import InventoryBackupManager
from ..data.preferences import UserPreferencesRepository
from ..i18n import Translator, tr
from .base import ViewModel


@dataclass
class SettingsContent:
    title: str = ""
    language_title: str = ""
    language_chinese: str = ""
    language_english: str = ""
    about_title: str = ""
    about_summary: str = ""
    inventory_backup_title: str = ""
    export_inventory_title: str = ""
    export_inventory_summary: str = ""
    import_inventory_title: str = ""
    import_inventory_summary: str = ""
    about_body: str = ""
    stack_body: str = ""
    data_dir_title: str = ""
    data_dir_summary: str = ""
    data_dir_current: str = ""
    data_dir_default: str = ""
    data_dir_custom_label: str = ""
    data_dir_browse: str = ""
    data_dir_reset: str = ""
    data_dir_copy: str = ""
    data_dir_need_restart: str = ""


def _load_settings_content(language_tag: str) -> SettingsContent:
    return SettingsContent(
        title=tr("settings_title"),
        language_title=tr("settings_language"),
        language_chinese=tr("settings_language_chinese"),
        language_english=tr("settings_language_english"),
        about_title=tr("settings_about"),
        about_summary=tr("settings_about_summary"),
        inventory_backup_title=tr("settings_inventory_backup"),
        export_inventory_title=tr("settings_export_inventory"),
        export_inventory_summary=tr("settings_export_inventory_summary"),
        import_inventory_title=tr("settings_import_inventory"),
        import_inventory_summary=tr("settings_import_inventory_summary"),
        about_body=tr("settings_about_body"),
        stack_body=tr("settings_stack_body"),
        data_dir_title=tr("settings_data_dir"),
        data_dir_summary=tr("settings_data_dir_summary"),
        data_dir_current=tr("settings_data_dir_current"),
        data_dir_default=tr("settings_data_dir_default"),
        data_dir_custom_label=tr("settings_data_dir_custom_label"),
        data_dir_browse=tr("settings_data_dir_browse"),
        data_dir_reset=tr("settings_data_dir_reset"),
        data_dir_copy=tr("settings_data_dir_copy"),
        data_dir_need_restart=tr("settings_data_dir_need_restart"),
    )


@dataclass
class SettingsUiState:
    selected_language_tag: str = "zh"
    is_processing_inventory_backup: bool = False
    inventory_backup_progress: Optional[float] = None
    inventory_backup_message: Optional[str] = None
    current_data_dir: str = ""
    default_data_dir: str = ""
    has_custom_data_dir: bool = False
    content: SettingsContent = field(default_factory=SettingsContent)


class SettingsViewModel(ViewModel):
    def __init__(
        self,
        user_preferences_repository: UserPreferencesRepository,
        inventory_backup_manager: InventoryBackupManager,
        translator: Translator,
        thread_pool: Optional[QThreadPool] = None,
    ) -> None:
        super().__init__(thread_pool)
        self._preferences = user_preferences_repository
        self._backup_manager = inventory_backup_manager
        self._translator = translator

        self._screen_state: dict = {
            "is_processing_inventory_backup": False,
            "inventory_backup_progress": None,
            "inventory_backup_message": None,
        }

        self._preferences.preferences_changed.connect(self._schedule_recompute)
        self._translator.language_changed.connect(self._schedule_recompute)
        self._recompute()

    def _recompute(self) -> None:
        prefs = self._preferences.preferences
        s = self._screen_state
        self._state = SettingsUiState(
            selected_language_tag=prefs.app_language_tag,
            is_processing_inventory_backup=s["is_processing_inventory_backup"],
            inventory_backup_progress=s["inventory_backup_progress"],
            inventory_backup_message=s["inventory_backup_message"],
            current_data_dir=str(self._preferences.current_data_dir),
            default_data_dir=str(self._preferences.default_data_dir),
            has_custom_data_dir=self._preferences.has_custom_data_dir,
            content=_load_settings_content(prefs.app_language_tag),
        )

    # ---- language ----
    def on_language_selected(self, language_tag: str) -> None:
        self._preferences.set_app_language(language_tag)
        self._translator.set_language(language_tag)
        # both signals will trigger recompute

    def clear_inventory_backup_message(self) -> None:
        self._screen_state["inventory_backup_message"] = None
        self._do_recompute()

    # ---- export / import ----
    def export_inventory(self, path: str) -> None:
        self._screen_state.update(
            is_processing_inventory_backup=True,
            inventory_backup_progress=0.0,
            inventory_backup_message=None,
        )
        self._do_recompute()

        def _work():
            return self._backup_manager.export_to_path(
                path,
                on_components_progress=self._on_components_progress,
            )

        def _on_done(error, exc):
            if exc is not None:
                error_msg = str(exc) or tr("settings_backup_export_failed")
            else:
                error_msg = error
            self._screen_state.update(
                is_processing_inventory_backup=False,
                inventory_backup_progress=None,
                inventory_backup_message=error_msg or tr("settings_export_inventory_success"),
            )
            self._do_recompute()

        self._run_async(_work, _on_done)

    def import_inventory(self, path: str) -> None:
        self._screen_state.update(
            is_processing_inventory_backup=True,
            inventory_backup_progress=0.0,
            inventory_backup_message=None,
        )
        self._do_recompute()

        def _work():
            return self._backup_manager.import_from_path(
                path,
                on_components_progress=self._on_components_progress,
            )

        def _on_done(error, exc):
            if exc is not None:
                error_msg = str(exc) or tr("settings_backup_import_failed")
            else:
                error_msg = error
            self._screen_state.update(
                is_processing_inventory_backup=False,
                inventory_backup_progress=None,
                inventory_backup_message=error_msg or tr("settings_import_inventory_success"),
            )
            self._do_recompute()

        self._run_async(_work, _on_done)

    def _on_components_progress(self, processed: int, total: int) -> None:
        # called from worker thread; just stash the value — the next emit will
        # happen when the worker completes. For live progress we marshal via the
        # screen_state and trigger a recompute on the GUI thread.
        progress = (processed / total) if total > 0 else None
        self._screen_state["inventory_backup_progress"] = progress
        # Schedule a GUI-thread recompute so the progress bar updates live.
        self._schedule_recompute()

    # ---- data directory management ----
    def set_data_dir(self, path: str, copy_data: bool = False) -> str | None:
        """Set a custom data directory. Returns an error message or None on success."""
        try:
            if copy_data:
                self._preferences.copy_data_to(path)
            self._preferences.set_custom_data_dir(path)
            self._recompute()
            return None
        except Exception as exc:
            return str(exc) or "Failed to set data directory"

    def reset_data_dir(self) -> str | None:
        """Reset to default data directory. Returns an error message or None on success."""
        try:
            self._preferences.reset_data_dir()
            self._recompute()
            return None
        except Exception as exc:
            return str(exc) or "Failed to reset data directory"
