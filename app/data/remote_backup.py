"""GitHub/Gitee Contents API transport for cross-device inventory workbooks."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, urlparse

import requests


BACKUP_NAME = re.compile(r"^lcsc_inventory_backup_(\d{8})_(\d{4})\.xlsx$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")
_API = {"github": "https://api.github.com", "gitee": "https://gitee.com/api/v5"}


@dataclass
class BackupAccount:
    label: str
    provider: str
    owner: str
    repo: str
    branch: str = ""
    path: str = "backups"
    token: str = ""

    def validate(self) -> None:
        if self.provider not in _API:
            raise ValueError("Unsupported Git provider")
        if not self.owner or not self.repo or not all(_IDENTIFIER.fullmatch(s) for s in (self.owner, self.repo)):
            raise ValueError("Invalid repository owner or name")
        if not self.token.strip():
            raise ValueError("Access token is required")
        parts = self.path.replace("\\", "/").strip("/").split("/")
        if not parts or any(p in ("", ".", "..") for p in parts):
            raise ValueError("Invalid backup path")
        if self.branch and (self.branch.startswith("/") or ".." in self.branch or "?" in self.branch):
            raise ValueError("Invalid branch")

    @property
    def folder(self) -> str:
        return self.path.replace("\\", "/").strip("/")


class RemoteBackupError(RuntimeError):
    pass


class GitContentsBackupClient:
    def __init__(self, account: BackupAccount, session: requests.Session | None = None) -> None:
        account.validate()
        self.account = account
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.root = f"{_API[account.provider]}/repos/{quote(account.owner)}/{quote(account.repo)}"

    def _can_retry_direct(self, method: str, url: str, exc: requests.RequestException) -> bool:
        if (method != "GET" or not self._owns_session or not self.session.trust_env or
                not isinstance(exc, requests.exceptions.SSLError) or
                "UNEXPECTED_EOF_WHILE_READING" not in str(exc)):
            return False
        proxies = requests.utils.get_environ_proxies(url)
        proxy = requests.utils.select_proxy(url, proxies)
        return bool(proxy and urlparse(proxy).hostname in {"127.0.0.1", "::1", "localhost"})

    @staticmethod
    def _transient_read_error(exc: requests.RequestException) -> bool:
        if isinstance(exc, (requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError)):
            return True
        return (isinstance(exc, requests.exceptions.SSLError) and
                "UNEXPECTED_EOF_WHILE_READING" in str(exc))

    def _new_session(self, trust_env: bool) -> None:
        self.session.close()
        self.session = requests.Session()
        self.session.trust_env = trust_env

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        token = self.account.token.strip()
        accept = kwargs.pop("accept", None)
        headers = {"Accept": accept or ("application/vnd.github+json" if self.account.provider == "github" else "application/json"),
                   "User-Agent": "LCSC-Desktop-ERP"}
        if self.account.provider == "github":
            headers["Authorization"] = f"Bearer {token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        else:
            kwargs.setdefault("params", {})["access_token"] = token
        attempts = 3 if method == "GET" and self._owns_session else 1
        used_direct_fallback = False
        for attempt in range(attempts):
            try:
                response = self.session.request(method, url, headers=headers, timeout=(10, 60), **kwargs)
                break
            except requests.RequestException as exc:
                switch_direct = self._can_retry_direct(method, url, exc)
                retry = switch_direct or self._transient_read_error(exc)
                if method == "GET" and self._owns_session and retry and attempt + 1 < attempts:
                    if switch_direct:
                        used_direct_fallback = True
                    self._new_session(False if switch_direct else self.session.trust_env)
                    time.sleep(min(2.0, 0.5 * (2 ** attempt)))
                    continue
                detail = str(exc).replace(token, "[redacted]")
                if used_direct_fallback:
                    detail = f"Proxy TLS failed; direct connection failed after retries: {detail}"
                raise RemoteBackupError(detail) from exc
        if not response.ok and response.status_code != 404:
            detail = ""
            try:
                detail = str(response.json().get("message", ""))
            except (ValueError, AttributeError):
                pass
            raise RemoteBackupError(f"HTTP {response.status_code}: {detail or response.reason}")
        return response

    def _contents_url(self, name: str = "") -> str:
        return self._contents_url_for(self.account.folder + ("/" + name if name else ""))

    def probe(self) -> str:
        response = self._request("GET", self.root)
        if response.status_code == 404:
            raise RemoteBackupError("Repository not found or token has no access")
        metadata = response.json()
        branch = self.account.branch or metadata.get("default_branch") or "main"
        check = self._request("GET", f"{self.root}/branches/{quote(branch, safe='')}")
        if check.status_code == 404:
            raise RemoteBackupError(f"Branch not found: {branch}")
        return branch

    def _branch(self) -> str:
        return self.account.branch or self.probe()

    def list_backups(self) -> list[dict]:
        branch = self._branch()
        response = self._request("GET", self._contents_url(), params={"ref": branch})
        if response.status_code == 404:
            return []
        rows = response.json()
        if not isinstance(rows, list):
            raise RemoteBackupError("Backup path is not a directory")
        return sorted(({"name": item["name"], "sha": item.get("sha", ""), "size": item.get("size", 0)}
                       for item in rows if item.get("type") == "file" and BACKUP_NAME.fullmatch(item.get("name", ""))),
                      key=lambda item: item["name"], reverse=True)

    def _ensure_directories(self, branch: str) -> None:
        parts = self.account.folder.split("/")
        for index in range(1, len(parts) + 1):
            folder = "/".join(parts[:index])
            response = self._request("GET", self._contents_url_for(folder), params={"ref": branch})
            if response.status_code != 404:
                continue
            payload = {"message": f"Create backup directory {folder}", "branch": branch, "content": ""}
            if self.account.provider == "gitee":
                payload["access_token"] = self.account.token.strip()
            created = self._request("PUT", self._contents_url_for(folder + "/.gitkeep"), json=payload)
            if created.status_code not in (200, 201):
                raise RemoteBackupError(f"Could not create backup directory: HTTP {created.status_code}")

    def _contents_url_for(self, path: str) -> str:
        encoded = "/".join(quote(part, safe="") for part in path.split("/"))
        return f"{self.root}/contents/{encoded}"

    def upload(self, source: str | Path) -> str:
        branch = self._branch()
        self._ensure_directories(branch)
        name = datetime.now().strftime("lcsc_inventory_backup_%Y%m%d_%H%M.xlsx")
        url = self._contents_url(name)
        current = self._request("GET", url, params={"ref": branch})
        payload = {"message": f"Inventory backup {name}", "branch": branch,
                   "content": base64.b64encode(Path(source).read_bytes()).decode("ascii")}
        if self.account.provider == "gitee":
            payload["access_token"] = self.account.token.strip()
        if current.status_code != 404:
            payload["sha"] = current.json()["sha"]
        response = self._request("PUT", url, json=payload)
        if response.status_code not in (200, 201):
            raise RemoteBackupError(f"Upload failed: HTTP {response.status_code}")
        return name

    def download(self, name: str, target: str | Path) -> None:
        if not BACKUP_NAME.fullmatch(name):
            raise RemoteBackupError("Invalid backup name")
        if self.account.provider == "github":
            response = self._request("GET", self._contents_url(name), params={"ref": self._branch()},
                                     accept="application/vnd.github.raw+json")
            if response.status_code == 404:
                raise RemoteBackupError("Backup no longer exists")
            Path(target).write_bytes(response.content)
            return
        response = self._request("GET", self._contents_url(name), params={"ref": self._branch()})
        if response.status_code == 404:
            raise RemoteBackupError("Backup no longer exists")
        item = response.json()
        content = item.get("content")
        if content and item.get("encoding") == "base64":
            data = base64.b64decode(content, validate=False)
        elif item.get("download_url"):
            download_url = item["download_url"]
            parsed = urlparse(download_url)
            if parsed.scheme != "https" or parsed.hostname not in ("gitee.com", "raw.gitee.com"):
                raise RemoteBackupError("Untrusted download URL")
            raw = self._request("GET", download_url)
            if raw.status_code == 404:
                raise RemoteBackupError("Backup no longer exists")
            data = raw.content
        else:
            raise RemoteBackupError("Backup has no downloadable content")
        Path(target).write_bytes(data)

    def delete(self, name: str) -> bool:
        """Delete one named backup, using its current blob SHA."""
        if not BACKUP_NAME.fullmatch(name):
            raise RemoteBackupError("Invalid backup name")
        branch = self._branch()
        url = self._contents_url(name)
        current = self._request("GET", url, params={"ref": branch})
        if current.status_code == 404:
            return False
        payload = {"message": f"Delete inventory backup {name}", "branch": branch,
                   "sha": current.json()["sha"]}
        if self.account.provider == "gitee":
            payload["access_token"] = self.account.token.strip()
        response = self._request("DELETE", url, json=payload)
        if response.status_code not in (200, 204):
            raise RemoteBackupError(f"Delete failed: HTTP {response.status_code}")
        return True

    def retain_latest(self, count: int = 5) -> int:
        """Keep the newest timestamped backups in this account's folder."""
        if count < 1:
            raise ValueError("At least one backup must be retained")
        rows = self.list_backups()
        return sum(self.delete(row["name"]) for row in rows[count:])


class BackupAccountsStore:
    """Persists account metadata and Windows user encrypted access tokens."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _crypt(data: bytes, decrypt: bool) -> bytes:
        import ctypes
        from ctypes import wintypes
        import sys
        if sys.platform != "win32":
            raise RuntimeError("Credential storage requires Windows")

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        source = ctypes.create_string_buffer(data)
        input_blob = DATA_BLOB(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
        output_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        ok = function(ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob))
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(ctypes.cast(output_blob.pbData, ctypes.c_void_p))

    def load(self) -> tuple[list[BackupAccount], dict]:
        if not self.path.exists():
            return [], {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        accounts = []
        for item in raw.get("accounts", []):
            account = BackupAccount(**{k: item.get(k, "") for k in ("label", "provider", "owner", "repo", "branch", "path")})
            encrypted = item.get("token_encrypted", "")
            if encrypted:
                account.token = self._crypt(base64.b64decode(encrypted), True).decode("utf-8")
            accounts.append(account)
        return accounts, raw

    def save(self, accounts: list[BackupAccount], settings: dict) -> None:
        rows = []
        for account in accounts:
            row = {k: v for k, v in asdict(account).items() if k != "token"}
            row["token_encrypted"] = base64.b64encode(self._crypt(account.token.encode("utf-8"), False)).decode("ascii")
            rows.append(row)
        data = {**settings, "accounts": rows}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
