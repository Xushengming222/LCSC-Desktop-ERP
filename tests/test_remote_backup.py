"""Offline checks for cross-device backup and Git Contents transport."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from openpyxl import Workbook
from PySide6.QtWidgets import QApplication

from app.app_container import AppContainer
from app.data.remote_backup import BackupAccount, BackupAccountsStore, GitContentsBackupClient, RemoteBackupError


class Response:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data or {}
        self.ok = 200 <= status < 300
        self.reason = "test"
        self.content = b""

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.files = {}
        self.calls = []
        self.folder_exists = True

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/repos/owner/repo"):
            return Response(200, {"default_branch": "main"})
        if url.endswith("/branches/main"):
            return Response(200, {})
        if "/contents/backups" in url:
            name = url.rsplit("/", 1)[-1]
            if name == "backups":
                return Response(200, [{"name": n, "type": "file", "sha": "old", "size": len(v)} for n, v in self.files.items()]) if self.folder_exists else Response(404)
            if method == "GET":
                return Response(200, {"content": base64.b64encode(self.files[name]).decode(), "encoding": "base64", "sha": "old"}) if name in self.files else Response(404)
            if method == "PUT":
                self.files[name] = base64.b64decode(kwargs["json"]["content"])
                if name == ".gitkeep":
                    self.folder_exists = True
                return Response(201)
        return Response(404)


class RemoteBackupTests(unittest.TestCase):
    @staticmethod
    def _phone_workbook(path: Path) -> None:
        book = Workbook()
        meta = book.active
        meta.title = "元数据"
        meta.append(["键", "值"])
        meta.append(["schema版本", "2"])
        locations = book.create_sheet("库位")
        locations.append(["id", "编号", "显示名", "颜色", "排序方式", "备注", "创建时间"])
        locations.append([1, "A1", "Rack", "#C8E6C9", "", "", "2026-11-19 12:43"])
        components = book.create_sheet("物料")
        components.append(["id", "料号", "名称", "品牌", "封装", "类目", "规格", "描述", "商品链接", "更新时间"])
        components.append([2, "C123", "Resistor", "Brand", "0603", "R", "{}", "Test", "", 1000])
        inventory = book.create_sheet("库存")
        inventory.append(["id", "料号", "库位编号", "数量", "最近入库时间", "更新时间"])
        inventory.append([3, "C123", "A1", 12, 1000, 1000])
        book.save(path)

    def test_contents_roundtrip_and_token_is_not_logged(self):
        account = BackupAccount("warehouse", "github", "owner", "repo", "", "backups", "secret")
        session = FakeSession()
        client = GitContentsBackupClient(account, session)
        with TemporaryDirectory() as root:
            source = Path(root) / "input.xlsx"
            source.write_bytes(b"test workbook")
            name = client.upload(source)
            self.assertRegex(name, r"^lcsc_inventory_backup_\d{8}_\d{4}\.xlsx$")
            self.assertEqual([item["name"] for item in client.list_backups()], [name])
            target = Path(root) / "output.xlsx"
            client.download(name, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            with self.assertRaises(RemoteBackupError):
                client.download("../secret", target)
        self.assertTrue(all(call[2]["headers"]["Authorization"] == "Bearer secret" for call in session.calls))

    def test_upload_creates_missing_backup_directory(self):
        session = FakeSession()
        session.folder_exists = False
        client = GitContentsBackupClient(BackupAccount("warehouse", "github", "owner", "repo", "main", "backups", "secret"), session)
        with TemporaryDirectory() as root:
            source = Path(root) / "input.xlsx"
            source.write_bytes(b"data")
            client.upload(source)
        self.assertIn(".gitkeep", session.files)
        self.assertTrue(session.folder_exists)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_token_encrypted_for_current_windows_user(self):
        with TemporaryDirectory() as root:
            store = BackupAccountsStore(Path(root) / "remote_backup.json")
            account = BackupAccount("warehouse", "github", "owner", "repo", "main", "backups", "private-token")
            store.save([account], {"enabled": True})
            self.assertNotIn("private-token", store.path.read_text(encoding="utf-8"))
            self.assertEqual(store.load()[0], [account])

    def test_android_schema_two_chinese_workbook_imports_inventory(self):
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as root:
            container = AppContainer(Path(root) / "data", project_dir=root)
            try:
                path = Path(root) / "phone.xlsx"
                self._phone_workbook(path)
                self.assertIsNone(container._backup_manager.import_from_path(path))
                self.assertEqual(container._conn.execute("SELECT quantity FROM inventory_item").fetchone()[0], 12)
                self.assertGreater(container._conn.execute("SELECT createdAt FROM storage_location").fetchone()[0], 1_700_000_000_000)
            finally:
                for _ in range(4):
                    app.processEvents()
                container.settings_view_model._remote_timer.stop()
                container._thread_pool.waitForDone()
                container.close()

    def test_remote_restore_creates_safety_copy_and_refreshes_inventory(self):
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as root:
            root_path = Path(root)
            data_dir = root_path / "data"
            phone_file = root_path / "phone.xlsx"
            self._phone_workbook(phone_file)
            container = AppContainer(data_dir, project_dir=root)
            vm = container.settings_view_model
            account = BackupAccount("warehouse", "github", "owner", "repo", "main", "backups", "test-token")
            vm.save_account(account)

            class FakeClient:
                def __init__(self, selected):
                    assert selected == account

                def download(self, name, target):
                    Path(target).write_bytes(phone_file.read_bytes())

            changes = []
            container._inventory_repository.changed.connect(lambda: changes.append(True))
            try:
                with patch("app.viewmodels.settings_viewmodel.GitContentsBackupClient", FakeClient):
                    vm.restore_remote("lcsc_inventory_backup_20261119_1220.xlsx")
                    deadline = time.monotonic() + 5
                    while vm.ui_state.remote_busy and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(0.01)
                self.assertFalse(vm.ui_state.remote_busy)
                self.assertIn("恢复成功", vm.ui_state.remote_message)
                self.assertEqual(container._conn.execute("SELECT quantity FROM inventory_item").fetchone()[0], 12)
                self.assertEqual(len(list((data_dir / "before-remote-restore").glob("*.xlsx"))), 1)
                self.assertTrue(changes)
            finally:
                for _ in range(4):
                    app.processEvents()
                container.settings_view_model._remote_timer.stop()
                container._thread_pool.waitForDone()
                container.close()

    def test_automatic_backup_runs_daily_and_after_changes(self):
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as root:
            container = AppContainer(Path(root) / "data", project_dir=root)
            vm = container.settings_view_model
            account = BackupAccount("warehouse", "github", "owner", "repo", "main", "backups", "test-token")
            vm.save_account(account)
            uploads = []

            class FakeClient:
                def __init__(self, selected):
                    assert selected == account

                def upload(self, path):
                    uploads.append(Path(path).read_bytes())
                    return "lcsc_inventory_backup_20261119_1220.xlsx"

            def finish():
                deadline = time.monotonic() + 5
                while vm.ui_state.remote_busy and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
                self.assertFalse(vm.ui_state.remote_busy)

            try:
                with patch("app.viewmodels.settings_viewmodel.GitContentsBackupClient", FakeClient):
                    vm.set_remote_enabled(True)
                    finish()
                    self.assertEqual(len(uploads), 1)
                    self.assertTrue(vm.ui_state.remote_last_success)
                    container._conn.execute("INSERT INTO storage_location (code, sortMode, createdAt) VALUES ('A1', '', 1000)")
                    vm._check_automatic_backup()
                    vm._change_time = time.time() - 61
                    vm._last_attempt = time.time() - 901
                    vm._check_automatic_backup()
                    finish()
                    self.assertEqual(len(uploads), 2)
            finally:
                vm._remote_timer.stop()
                for _ in range(4):
                    app.processEvents()
                container.close()


if __name__ == "__main__":
    unittest.main()
