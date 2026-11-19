"""SettingsViewModel — port of feature/settings/SettingsViewModel.kt.

Combines the user preferences with a mutable screen state (backup progress /
message) and the loaded settings content (which is just the i18n strings, since
the Android ``settings_content.json`` asset is replaced by the zh/en string
tables in this desktop port). Export/import run on the thread pool and report
progress via callbacks.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Callable, Optional

from PySide6.QtCore import QThreadPool, QTimer

from ..data.backup_manager import InventoryBackupManager
from ..data.preferences import UserPreferencesRepository
from ..data.remote_backup import BackupAccount, BackupAccountsStore, GitContentsBackupClient
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
    remote_accounts: list[BackupAccount] = field(default_factory=list)
    remote_selected_index: int = 0
    remote_enabled: bool = False
    remote_multi_account: bool = False
    remote_busy: bool = False
    remote_message: str = ""
    remote_last_success: str = ""
    remote_backups: list[dict] = field(default_factory=list)
    content: SettingsContent = field(default_factory=SettingsContent)


class SettingsViewModel(ViewModel):
    def __init__(
        self,
        user_preferences_repository: UserPreferencesRepository,
        inventory_backup_manager: InventoryBackupManager,
        translator: Translator,
        thread_pool: Optional[QThreadPool] = None,
        remote_store: BackupAccountsStore | None = None,
        data_dir: str | Path | None = None,
        inventory_repository=None,
        db_connection=None,
    ) -> None:
        super().__init__(thread_pool)
        self._preferences = user_preferences_repository
        self._backup_manager = inventory_backup_manager
        self._translator = translator
        self._remote_store = remote_store
        self._data_dir = Path(data_dir) if data_dir else None
        self._inventory_repository = inventory_repository
        self._db_connection = db_connection
        self._remote_accounts: list[BackupAccount] = []
        self._remote_config: dict = {}
        self._remote_backups: list[dict] = []
        self._remote_busy = False
        self._remote_message = ""
        self._last_change = db_connection.total_changes if db_connection else 0
        self._last_uploaded_change = self._last_change
        self._last_fingerprint = self._data_fingerprint()
        self._change_time = 0.0
        self._last_attempt = 0.0
        if remote_store:
            try:
                self._remote_accounts, self._remote_config = remote_store.load()
            except Exception as exc:
                self._remote_message = f"Remote backup configuration could not be read: {exc}"
        self._remote_timer = QTimer(self)
        self._remote_timer.setInterval(30_000)
        self._remote_timer.timeout.connect(self._check_automatic_backup)
        self._remote_timer.start()
        QTimer.singleShot(5_000, self._check_automatic_backup)

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
            remote_accounts=[replace(a, token="") for a in self._remote_accounts],
            remote_selected_index=int(self._remote_config.get("selected_index", 0)),
            remote_enabled=bool(self._remote_config.get("enabled", False)),
            remote_multi_account=bool(self._remote_config.get("multi_account", False)),
            remote_busy=self._remote_busy,
            remote_message=self._remote_message,
            remote_last_success=str(self._remote_config.get("last_success", "")),
            remote_backups=list(self._remote_backups),
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

    # ---- remote backup ----
    def _save_remote(self) -> None:
        if self._remote_store:
            self._remote_store.save(self._remote_accounts, self._remote_config)
        self._do_recompute()

    def save_account(self, account: BackupAccount, index: int | None = None) -> None:
        if index is None:
            account.validate()
            self._remote_accounts.append(account)
            self._remote_config["selected_index"] = len(self._remote_accounts) - 1
        else:
            if not account.token:
                account.token = self._remote_accounts[index].token
            account.validate()
            self._remote_accounts[index] = account
        self._save_remote()

    def remove_account(self, index: int) -> None:
        self._remote_accounts.pop(index)
        self._remote_config["selected_index"] = min(int(self._remote_config.get("selected_index", 0)), max(0, len(self._remote_accounts) - 1))
        self._save_remote()

    def select_account(self, index: int) -> None:
        if index < 0 or index >= len(self._remote_accounts):
            return
        self._remote_config["selected_index"] = index
        self._remote_backups = []
        self._save_remote()

    def set_remote_enabled(self, enabled: bool) -> None:
        self._remote_config["enabled"] = enabled
        self._save_remote()
        if enabled:
            self._check_automatic_backup()

    def set_multi_account(self, enabled: bool) -> None:
        self._remote_config["multi_account"] = enabled
        self._save_remote()

    def _selected_account(self) -> BackupAccount:
        if not self._remote_accounts:
            raise ValueError(tr("remote_no_accounts"))
        index = int(self._remote_config.get("selected_index", 0))
        return self._remote_accounts[min(max(index, 0), len(self._remote_accounts) - 1)]

    def _start_remote(self, work, done) -> None:
        if self._remote_busy:
            return
        self._remote_busy = True
        self._remote_message = tr("remote_working")
        self._do_recompute()

        def on_done(result, exc):
            self._remote_busy = False
            self._remote_message = str(exc) if exc else done(result)
            self._do_recompute()

        self._run_async(work, on_done)

    def probe_remote(self) -> None:
        try:
            account = self._selected_account()
        except Exception as exc:
            self._remote_message = str(exc)
            self._do_recompute()
            return
        self._start_remote(lambda: GitContentsBackupClient(account).probe(),
                           lambda branch: tr("remote_connection_ok").format(branch=branch))

    def upload_remote(self) -> None:
        if self._remote_busy:
            return
        try:
            accounts = list(self._remote_accounts) if self._remote_config.get("multi_account") else [self._selected_account()]
            if not accounts:
                raise ValueError(tr("remote_no_accounts"))
            for account in accounts:
                account.validate()
        except Exception as exc:
            self._remote_message = str(exc)
            self._do_recompute()
            return
        self._last_attempt = time.time()
        change_snapshot = self._db_connection.total_changes if self._db_connection else 0
        fingerprint_snapshot = self._data_fingerprint()

        def work():
            with TemporaryDirectory(prefix="lcsc-remote-") as directory:
                path = Path(directory) / "inventory.xlsx"
                error = self._backup_manager.export_to_path(path, enrich_components=False)
                if error:
                    raise RuntimeError(error)
                uploaded = []
                failures = []
                for account in accounts:
                    try:
                        name = GitContentsBackupClient(account).upload(path)
                        uploaded.append(f"{account.label or account.repo}: {name}")
                    except Exception as exc:
                        failures.append(f"{account.label or account.repo}: {exc}")
                return uploaded, failures

        def done(result):
            uploaded, failures = result
            if not failures:
                self._remote_config["last_success"] = datetime.now().isoformat(timespec="seconds")
                self._remote_config["last_data_fingerprint"] = fingerprint_snapshot
                self._last_uploaded_change = change_snapshot
                self._save_remote()
            return (tr("remote_upload_success") + " " + "; ".join(uploaded) if uploaded else "") + ("; ".join(failures) if failures else "")

        self._start_remote(work, done)

    def _data_fingerprint(self) -> str:
        if self._data_dir is None:
            return ""
        values = []
        for suffix in ("", "-wal"):
            path = self._data_dir / ("lcsc_erp.db" + suffix)
            if path.exists():
                stat = path.stat()
                values.append(f"{suffix}:{stat.st_mtime_ns}:{stat.st_size}")
        return "|".join(values)

    def list_remote(self) -> None:
        try:
            account = self._selected_account()
        except Exception as exc:
            self._remote_message = str(exc)
            self._do_recompute()
            return

        def done(rows):
            self._remote_backups = rows
            return tr("remote_list_empty") if not rows else tr("remote_list_count").format(count=len(rows))

        self._start_remote(lambda: GitContentsBackupClient(account).list_backups(), done)

    def restore_remote(self, name: str) -> None:
        try:
            account = self._selected_account()
            if self._data_dir is None:
                raise RuntimeError("Data directory unavailable")
        except Exception as exc:
            self._remote_message = str(exc)
            self._do_recompute()
            return

        def work():
            with TemporaryDirectory(prefix="lcsc-remote-") as directory:
                path = Path(directory) / name
                GitContentsBackupClient(account).download(name, path)
                safety_dir = self._data_dir / "before-remote-restore"
                safety_dir.mkdir(parents=True, exist_ok=True)
                safety = safety_dir / datetime.now().strftime("inventory_%Y%m%d_%H%M%S.xlsx")
                error = self._backup_manager.export_to_path(safety, enrich_components=False)
                if error:
                    safety.unlink(missing_ok=True)
                    raise RuntimeError(tr("remote_safety_failed").format(error=error))
                error = self._backup_manager.import_from_path(path)
                if error:
                    raise RuntimeError(error)
                return str(safety)

        def done(safety):
            if self._inventory_repository:
                self._inventory_repository.changed.emit()
            return tr("remote_restore_success").format(path=safety)

        self._start_remote(work, done)

    def _check_automatic_backup(self) -> None:
        if self._db_connection is None or not self._remote_config.get("enabled") or not self._remote_accounts or self._remote_busy:
            return
        current = self._db_connection.total_changes
        fingerprint = self._data_fingerprint()
        if current != self._last_change or fingerprint != self._last_fingerprint:
            self._last_change = current
            self._last_fingerprint = fingerprint
            self._change_time = time.time()
        last = self._remote_config.get("last_success", "")
        try:
            last_date = datetime.fromisoformat(last)
        except ValueError:
            last_date = datetime.min
        daily_due = last_date.date() < datetime.now().date()
        changed = (current != self._last_uploaded_change or
                   fingerprint != self._remote_config.get("last_data_fingerprint", ""))
        if time.time() - self._last_attempt < 900:
            return
        if daily_due or (changed and time.time() - self._change_time >= 60):
            self.upload_remote()
