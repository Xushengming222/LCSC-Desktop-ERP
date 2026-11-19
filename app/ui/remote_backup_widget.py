"""Remote backup settings and account editor."""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..data.remote_backup import BackupAccount
from ..i18n import tr
from ..viewmodels.settings_viewmodel import SettingsViewModel
from .widgets import Card, OutlineButton


class AccountDialog(QDialog):
    def __init__(self, account: BackupAccount | None = None, parent=None) -> None:
        super().__init__(parent)
        self._editing = account is not None
        self.setWindowTitle(tr("remote_edit_account") if account else tr("remote_add_account"))
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.label = QLineEdit(account.label if account else "")
        self.provider = QComboBox()
        self.provider.addItem("GitHub", "github")
        self.provider.addItem("Gitee", "gitee")
        self.provider.setCurrentIndex(0 if not account or account.provider == "github" else 1)
        self.owner = QLineEdit(account.owner if account else "")
        self.repo = QLineEdit(account.repo if account else "")
        self.branch = QLineEdit(account.branch if account else "")
        self.branch.setPlaceholderText(tr("remote_branch_hint"))
        self.path = QLineEdit(account.path if account else "backups")
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText(tr("remote_token_keep") if account else tr("remote_token_hint"))
        self.show_token = QCheckBox(tr("remote_show_token"))
        self.show_token.toggled.connect(lambda checked: self.token.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
        for label, field in (("remote_label", self.label), ("remote_provider", self.provider),
                             ("remote_owner", self.owner), ("remote_repo", self.repo),
                             ("remote_branch", self.branch), ("remote_path", self.path),
                             ("remote_token", self.token)):
            form.addRow(tr(label), field)
        form.addRow("", self.show_token)
        hint = QLabel(tr("remote_token_help"))
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept_checked(self) -> None:
        try:
            account = self.account()
            if self._editing and not account.token:
                account.token = "retained-token"
            account.validate()
        except Exception as exc:
            QMessageBox.warning(self, tr("remote_backup"), str(exc))
            return
        self.accept()

    def account(self) -> BackupAccount:
        return BackupAccount(self.label.text().strip(), self.provider.currentData(),
                             self.owner.text().strip(), self.repo.text().strip(),
                             self.branch.text().strip(), self.path.text().strip(), self.token.text().strip())


class RemoteBackupWidget(Card):
    def __init__(self, vm: SettingsViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vm = vm
        self.title = QLabel()
        self.title.setObjectName("h3")
        self.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.addWidget(self.summary)
        self.enabled = QCheckBox()
        self.enabled.toggled.connect(vm.set_remote_enabled)
        self.addWidget(self.enabled)
        self.multi = QCheckBox()
        self.multi.toggled.connect(vm.set_multi_account)
        self.addWidget(self.multi)
        self.multi_hint = QLabel()
        self.multi_hint.setWordWrap(True)
        self.addWidget(self.multi_hint)
        self.retention = QCheckBox()
        self.retention.toggled.connect(self._set_retention)
        self.addWidget(self.retention)
        self.retention_hint = QLabel()
        self.retention_hint.setWordWrap(True)
        self.addWidget(self.retention_hint)
        self.account_title = QLabel()
        self.account_title.setObjectName("h3")
        self.addWidget(self.account_title)
        self.accounts = QListWidget()
        self.accounts.setObjectName("remoteAccountList")
        self.accounts.setMaximumHeight(135)
        self.accounts.currentRowChanged.connect(vm.select_account)
        self.addWidget(self.accounts)
        self.empty_accounts = QLabel()
        self.addWidget(self.empty_accounts)
        row = QHBoxLayout()
        self.add_btn = OutlineButton()
        self.add_btn.clicked.connect(self._add)
        row.addWidget(self.add_btn)
        self.edit_btn = OutlineButton()
        self.edit_btn.clicked.connect(self._edit)
        row.addWidget(self.edit_btn)
        self.remove_btn = OutlineButton()
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        row.addStretch()
        self.addLayout(row)
        row = QHBoxLayout()
        self.upload_btn = OutlineButton()
        self.upload_btn.clicked.connect(vm.upload_remote)
        row.addWidget(self.upload_btn)
        self.pull_btn = OutlineButton()
        self.pull_btn.clicked.connect(vm.list_remote)
        row.addWidget(self.pull_btn)
        self.test_btn = OutlineButton()
        self.test_btn.clicked.connect(vm.probe_remote)
        row.addWidget(self.test_btn)
        row.addStretch()
        self.addLayout(row)
        self.last = QLabel()
        self.last.setWordWrap(True)
        self.addWidget(self.last)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.addWidget(self.message)
        self.backups = QListWidget()
        self.backups.setObjectName("remoteBackupList")
        self.backups.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.backups.setMaximumHeight(150)
        self.backups.itemSelectionChanged.connect(self._update_backup_buttons)
        self.addWidget(self.backups)
        backup_actions = QHBoxLayout()
        self.restore_btn = OutlineButton()
        self.restore_btn.clicked.connect(self._restore)
        backup_actions.addWidget(self.restore_btn)
        self.delete_btn = OutlineButton()
        self.delete_btn.clicked.connect(self._delete_backups)
        backup_actions.addWidget(self.delete_btn)
        backup_actions.addStretch()
        self.addLayout(backup_actions)
        vm.ui_state_changed.connect(self.refresh)
        self.refresh()

    def _add(self) -> None:
        dialog = AccountDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.vm.save_account(dialog.account())
            except Exception as exc:
                QMessageBox.warning(self, tr("remote_backup"), str(exc))

    def _edit(self) -> None:
        index = self.accounts.currentRow()
        state = self.vm.ui_state
        if index < 0 or index >= len(state.remote_accounts):
            return
        dialog = AccountDialog(state.remote_accounts[index], self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.vm.save_account(dialog.account(), index)
            except Exception as exc:
                QMessageBox.warning(self, tr("remote_backup"), str(exc))

    def _remove(self) -> None:
        index = self.accounts.currentRow()
        if index < 0:
            return
        if QMessageBox.question(self, tr("remote_backup"), tr("remote_remove_confirm"),
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.vm.remove_account(index)

    def _restore(self) -> None:
        item = self.backups.currentItem()
        if item is None or not item.isSelected():
            return
        name = item.text()
        if QMessageBox.warning(self, tr("remote_backup"), tr("remote_restore_confirm").format(name=name),
                               QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.vm.restore_remote(name)

    def _set_retention(self, enabled: bool) -> None:
        if enabled and QMessageBox.question(
            self, tr("remote_backup"), tr("remote_retention_confirm"),
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            self.retention.blockSignals(True)
            self.retention.setChecked(False)
            self.retention.blockSignals(False)
            return
        self.vm.set_auto_retention(enabled)

    def _delete_backups(self) -> None:
        names = [item.text() for item in self.backups.selectedItems()]
        if not names:
            return
        if QMessageBox.question(
            self, tr("remote_backup"), tr("remote_delete_confirm").format(count=len(names)),
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self.vm.delete_remote(names)

    def _update_backup_buttons(self) -> None:
        state = self.vm.ui_state
        item = self.backups.currentItem()
        self.restore_btn.setEnabled(item is not None and item.isSelected() and not state.remote_busy)
        self.delete_btn.setEnabled(bool(self.backups.selectedItems()) and not state.remote_busy)

    def refresh(self) -> None:
        state = self.vm.ui_state
        if state is None:
            return
        self.title.setText(tr("remote_backup"))
        self.summary.setText(tr("remote_summary"))
        for checkbox, value in ((self.enabled, state.remote_enabled), (self.multi, state.remote_multi_account),
                                (self.retention, state.remote_auto_retention)):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)
        self.enabled.setText(tr("remote_enable"))
        self.multi.setText(tr("remote_multi"))
        self.multi_hint.setText(tr("remote_multi_hint"))
        self.retention.setText(tr("remote_retention"))
        self.retention_hint.setText(tr("remote_retention_hint"))
        self.account_title.setText(tr("remote_accounts"))
        self.accounts.blockSignals(True)
        self.accounts.clear()
        for account in state.remote_accounts:
            self.accounts.addItem(f"{account.label or account.repo} · {account.provider} · {account.owner}/{account.repo}")
        if state.remote_accounts:
            self.accounts.setCurrentRow(min(state.remote_selected_index, len(state.remote_accounts) - 1))
        self.accounts.blockSignals(False)
        self.accounts.setVisible(bool(state.remote_accounts))
        self.accounts.setFixedHeight(min(135, max(42, len(state.remote_accounts) * 34 + 8)))
        self.empty_accounts.setText(tr("remote_no_accounts"))
        self.empty_accounts.setVisible(not state.remote_accounts)
        for button, label in ((self.add_btn, "remote_add_account"), (self.edit_btn, "remote_edit_account"),
                              (self.remove_btn, "remote_remove_account"), (self.upload_btn, "remote_upload"),
                              (self.pull_btn, "remote_pull"), (self.test_btn, "remote_test"),
                              (self.restore_btn, "remote_restore"), (self.delete_btn, "remote_delete")):
            button.setText(tr(label))
        self.last.setText(tr("remote_last_success").format(time=state.remote_last_success or tr("remote_never")))
        self.message.setText(state.remote_message)
        backup_names = [row["name"] for row in state.remote_backups]
        current_names = [self.backups.item(index).text() for index in range(self.backups.count())]
        if backup_names != current_names:
            selected_names = {item.text() for item in self.backups.selectedItems()}
            current_name = self.backups.currentItem().text() if self.backups.currentItem() else None
            self.backups.clear()
            self.backups.addItems(backup_names)
            for index, name in enumerate(backup_names):
                if name in selected_names:
                    self.backups.item(index).setSelected(True)
            if current_name in backup_names:
                self.backups.setCurrentItem(self.backups.item(backup_names.index(current_name)),
                                            QItemSelectionModel.NoUpdate)
        self.backups.setVisible(bool(state.remote_backups))
        self.restore_btn.setVisible(bool(state.remote_backups))
        self.delete_btn.setVisible(bool(state.remote_backups))
        self._update_backup_buttons()
        for button in (self.edit_btn, self.remove_btn, self.upload_btn, self.pull_btn, self.test_btn):
            button.setEnabled(bool(state.remote_accounts) and not state.remote_busy)
        self.add_btn.setEnabled(not state.remote_busy)
        self.retention.setEnabled(not state.remote_busy)
