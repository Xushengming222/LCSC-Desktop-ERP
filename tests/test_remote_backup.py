"""Offline checks for cross-device backup and Git Contents transport."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import requests
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from openpyxl import Workbook, load_workbook
from PySide6.QtWidgets import QApplication

from app.app_container import AppContainer
from app.data.remote_backup import BackupAccount, BackupAccountsStore, GitContentsBackupClient, RemoteBackupError
from app.ui.remote_backup_widget import RemoteBackupWidget


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
                if name not in self.files:
                    return Response(404)
                response = Response(200, {"content": base64.b64encode(self.files[name]).decode(), "encoding": "base64", "sha": "old"})
                if kwargs["headers"]["Accept"] == "application/vnd.github.raw+json":
                    response.content = self.files[name]
                return response
            if method == "PUT":
                self.files[name] = base64.b64decode(kwargs["json"]["content"])
                if name == ".gitkeep":
                    self.folder_exists = True
                return Response(201)
            if method == "DELETE":
                if name not in self.files:
                    return Response(404)
                if kwargs["json"]["sha"] != "old":
                    return Response(409)
                del self.files[name]
                return Response(200)
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
        locations.append(["编号", "显示名", "颜色", "排序方式", "备注", "创建时间"])
        locations.append(["A1", "Rack", "#C8E6C9", "", "", "2026-11-19 12:43"])
        locations.append(["B2", "Shelf", "#B3E5FC", "", "", "2026-11-19 12:44"])
        components = book.create_sheet("物料")
        components.append(["料号", "名称", "品牌", "封装", "类目", "规格", "描述", "商品链接", "更新时间"])
        components.append(["C123", "Resistor", "Brand", "0603", "R", "{}", "Test", "", 1000])
        components.append(["C456", "Capacitor", "Brand", "0805", "C", "{}", "Test", "", 1000])
        inventory = book.create_sheet("库存")
        inventory.append(["料号", "库位编号", "数量", "最近入库时间", "更新时间"])
        inventory.append(["C123", "A1", 12, 1000, 1000])
        inventory.append(["C456", "B2", 7, 1000, 1000])
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
            calls_before_download = len(session.calls)
            client.download(name, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            file_calls = [call for call in session.calls[calls_before_download:] if call[1].endswith(name)]
            self.assertEqual(len(file_calls), 1)
            self.assertEqual(file_calls[0][2]["headers"]["Accept"], "application/vnd.github.raw+json")
            with self.assertRaises(RemoteBackupError):
                client.download("../secret", target)
        self.assertTrue(all(call[2]["headers"]["Authorization"] == "Bearer secret" for call in session.calls))

    def test_local_proxy_tls_eof_falls_back_only_for_reads(self):
        class BrokenProxy:
            trust_env = True

            def __init__(self):
                self.calls = []
                self.closed = False

            def request(self, method, url, **kwargs):
                self.calls.append(method)
                raise requests.exceptions.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING]")

            def close(self):
                self.closed = True

        account = BackupAccount("warehouse", "github", "owner", "repo", "main", "backups", "secret")
        proxy = BrokenProxy()
        direct = FakeSession()
        with (patch("app.data.remote_backup.requests.Session", side_effect=[proxy, direct]) as factory,
              patch("app.data.remote_backup.requests.utils.get_environ_proxies", return_value={"https": "http://127.0.0.1:7890"})):
            client = GitContentsBackupClient(account)
            self.assertEqual(client.probe(), "main")
            self.assertTrue(proxy.closed)
            self.assertEqual(proxy.calls, ["GET"])
            self.assertFalse(direct.trust_env)
            self.assertEqual(len(direct.calls), 2)
            self.assertEqual(factory.call_count, 2)

        proxy = BrokenProxy()
        direct = FakeSession()
        with (TemporaryDirectory() as root,
              patch("app.data.remote_backup.requests.Session", side_effect=[proxy, direct]),
              patch("app.data.remote_backup.requests.utils.get_environ_proxies", return_value={"https": "http://127.0.0.1:7890"})):
            source = Path(root) / "inventory.xlsx"
            source.write_bytes(b"workbook")
            GitContentsBackupClient(account).upload(source)
            self.assertEqual(proxy.calls, ["GET"])
            self.assertIn("PUT", [call[0] for call in direct.calls])

        class InterruptedDirect:
            trust_env = False

            def __init__(self):
                self.closed = False

            def request(self, method, url, **kwargs):
                raise requests.exceptions.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING]")

            def close(self):
                self.closed = True

        proxy = BrokenProxy()
        interrupted = InterruptedDirect()
        final = FakeSession()
        with (patch("app.data.remote_backup.requests.Session", side_effect=[proxy, interrupted, final]) as factory,
              patch("app.data.remote_backup.requests.utils.get_environ_proxies", return_value={"https": "http://127.0.0.1:7890"}),
              patch("app.data.remote_backup.time.sleep")):
            self.assertEqual(GitContentsBackupClient(account).probe(), "main")
            self.assertTrue(interrupted.closed)
            self.assertFalse(final.trust_env)
            self.assertEqual(factory.call_count, 3)

        proxy = BrokenProxy()
        with patch("app.data.remote_backup.requests.Session", return_value=proxy) as factory:
            client = GitContentsBackupClient(account)
            with self.assertRaises(RemoteBackupError):
                client._request("PUT", client._contents_url("lcsc_inventory_backup_20261119_1200.xlsx"))
            self.assertEqual(factory.call_count, 1)

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

    def test_retention_keeps_latest_five_and_manual_delete_is_scoped(self):
        session = FakeSession()
        names = [f"lcsc_inventory_backup_20261119_{hour:02d}00.xlsx" for hour in range(8)]
        session.files = {name: b"workbook" for name in names}
        session.files["other.xlsx"] = b"keep"
        client = GitContentsBackupClient(
            BackupAccount("warehouse", "github", "owner", "repo", "main", "backups", "secret"), session,
        )
        self.assertEqual(client.retain_latest(5), 3)
        self.assertEqual(set(session.files), set(names[3:]) | {"other.xlsx"})
        self.assertTrue(client.delete(names[3]))
        self.assertFalse(client.delete(names[3]))
        with self.assertRaises(RemoteBackupError):
            client.delete("../other.xlsx")
        self.assertIn("other.xlsx", session.files)
        deletes = [call for call in session.calls if call[0] == "DELETE"]
        self.assertTrue(all(call[2]["json"]["branch"] == "main" for call in deletes))

    def test_backup_selection_survives_state_refresh(self):
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as root:
            container = AppContainer(Path(root) / "data", project_dir=root)
            vm = container.settings_view_model
            widget = RemoteBackupWidget(vm)
            try:
                vm._remote_backups = [
                    {"name": f"lcsc_inventory_backup_20261119_0{i}00.xlsx", "sha": "old", "size": 10}
                    for i in range(3)
                ]
                vm._do_recompute()
                widget.backups.setCurrentRow(0)
                widget.backups.item(1).setSelected(True)
                self.assertTrue(widget.restore_btn.isEnabled())
                self.assertTrue(widget.delete_btn.isEnabled())
                vm._do_recompute()
                self.assertEqual(len(widget.backups.selectedItems()), 2)
                self.assertEqual(widget.backups.currentRow(), 0)
            finally:
                widget.close()
                for _ in range(4):
                    app.processEvents()
                vm._remote_timer.stop()
                container._thread_pool.waitForDone()
                container.close()

    def test_retention_setting_prunes_on_enable_and_after_upload(self):
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as root:
            container = AppContainer(Path(root) / "data", project_dir=root)
            vm = container.settings_view_model
            account = BackupAccount("warehouse", "github", "owner", "repo", "main", "backups", "test-token")
            vm.save_account(account)
            session = FakeSession()
            session.files = {
                f"lcsc_inventory_backup_20261119_{hour:02d}00.xlsx": b"old"
                for hour in range(7)
            }

            def client(selected):
                self.assertEqual(selected, account)
                return GitContentsBackupClient(selected, session)

            def finish():
                deadline = time.monotonic() + 5
                while vm.ui_state.remote_busy and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
                self.assertFalse(vm.ui_state.remote_busy)

            try:
                with patch("app.viewmodels.settings_viewmodel.GitContentsBackupClient", client):
                    vm.set_auto_retention(True)
                    finish()
                    self.assertTrue(vm.ui_state.remote_auto_retention)
                    self.assertEqual(len(session.files), 5)
                    vm.upload_remote()
                    finish()
                    self.assertEqual(len(session.files), 5)
                    self.assertEqual(len(vm.ui_state.remote_backups), 5)
                    chosen = vm.ui_state.remote_backups[-1]["name"]
                    vm.delete_remote([chosen])
                    finish()
                    self.assertNotIn(chosen, session.files)
                    self.assertEqual(len(vm.ui_state.remote_backups), 4)
                self.assertTrue(BackupAccountsStore(Path(root) / "data" / "remote_backup.json").load()[1]["auto_retention"])
            finally:
                vm._remote_timer.stop()
                for _ in range(4):
                    app.processEvents()
                container._thread_pool.waitForDone()
                container.close()

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
                self.assertEqual(container._conn.execute("SELECT COUNT(*) FROM inventory_item").fetchone()[0], 2)
                self.assertEqual(container._conn.execute("SELECT COUNT(*) FROM component_master").fetchone()[0], 2)
                self.assertEqual(container._conn.execute("SELECT COUNT(*) FROM storage_location").fetchone()[0], 2)
                self.assertFalse(container._conn.execute("PRAGMA foreign_key_check").fetchall())
                self.assertGreater(container._conn.execute("SELECT createdAt FROM storage_location").fetchone()[0], 1_700_000_000_000)
            finally:
                for _ in range(4):
                    app.processEvents()
                container.settings_view_model._remote_timer.stop()
                container._thread_pool.waitForDone()
                container.close()

    def test_import_preserves_explicit_ids_and_generates_missing_ids(self):
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as root:
            path = Path(root) / "mixed.xlsx"
            self._phone_workbook(path)
            workbook = load_workbook(path)
            for sheet_name, first_id in (("库位", 10), ("物料", 20), ("库存", 30)):
                sheet = workbook[sheet_name]
                sheet.insert_cols(1)
                sheet.cell(1, 1, "id")
                sheet.cell(2, 1, first_id)
            workbook.save(path)
            container = AppContainer(Path(root) / "data", project_dir=root)
            try:
                self.assertIsNone(container._backup_manager.import_from_path(path))
                for table, expected in (("storage_location", [10, 11]),
                                        ("component_master", [20, 21]),
                                        ("inventory_item", [30, 31])):
                    actual = [row[0] for row in container._conn.execute(f"SELECT id FROM {table} ORDER BY id")]
                    self.assertEqual(actual, expected)
                self.assertFalse(container._conn.execute("PRAGMA foreign_key_check").fetchall())
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
