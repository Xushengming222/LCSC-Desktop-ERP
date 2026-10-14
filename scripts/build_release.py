"""Build the Windows portable package, including dependency license notices."""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "LCSC-Desktop-ERP"


def copy_licenses(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    packages = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "")):
        name = dist.metadata.get("Name", "unknown")
        packages.append({
            "name": name,
            "version": dist.version,
            "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
            "project_urls": dist.metadata.get_all("Project-URL") or [],
        })
        for file in dist.files or ():
            parts = file.parts
            if not parts or ".." in parts:
                continue
            in_metadata = any(p.endswith((".dist-info", ".egg-info")) for p in parts)
            is_license = re.match(r"^(LICENSE|LICENCE|COPYING|NOTICE|COPYRIGHT)([._-]|$)", file.name, re.I)
            in_license_dir = any(p.lower() in {"licenses", "licences"} for p in parts)
            if not ((in_metadata and (is_license or in_license_dir)) or
                    (parts[0] in {"PySide6", "shiboken6"} and (is_license or in_license_dir))):
                continue
            source = Path(dist.locate_file(file))
            if source.is_file():
                safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
                target = destination / safe_name / Path(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for filename in ("LICENSE.txt", "LICENSE"):
        source = Path(sys.base_prefix) / filename
        if source.is_file():
            shutil.copy2(source, destination / "Python-LICENSE.txt")
            break
    (destination.parent / "BUILD-DEPENDENCIES.json").write_text(
        json.dumps({"python": sys.version, "packages": packages}, indent=2), encoding="utf-8"
    )


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the Windows package on Windows.")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir", "--windowed", "--name", NAME,
        "--collect-data", "app", "--distpath", "dist", "--workpath", "build/pyinstaller",
        "--specpath", "build", "main.py",
    ], cwd=ROOT, check=True)
    assemble_release()


def assemble_release() -> None:
    """Assemble already-built binaries and notices into a portable ZIP."""
    package = ROOT / "dist" / NAME
    # Qt 6.12 uses the ICU API provided by Windows 10/11. PyInstaller can
    # accidentally collect a third-party ICU from the builder's PATH instead;
    # its version-suffixed exports cannot satisfy QtCore's Windows ICU imports.
    for binary in (package / "_internal").glob("icu*.dll"):
        binary.unlink()
    for filename in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.txt"):
        shutil.copy2(ROOT / filename, package / filename)
    copy_licenses(package / "licenses")
    (package / "README.txt").write_text(
        "LCSC Desktop ERP 1.0.0\n\n"
        "Extract the entire folder, then run LCSC-Desktop-ERP.exe.\n"
        "Keep the _internal folder beside the executable.\n"
        "Data and settings: %APPDATA%\\LCSC_ERP\n"
        "Source and build instructions: https://github.com/Xushengming222/LCSC-Desktop-ERP\n"
        "Original Android project: https://github.com/BrokenClient/LCSC_android_erp\n"
        "GPL-3.0-only. See LICENSE and NOTICE. No warranty.\n",
        encoding="utf-8",
    )
    release_dir = ROOT / "release"
    release_dir.mkdir(exist_ok=True)
    archive = release_dir / f"{NAME}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(package.parent))
    with archive.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    (release_dir / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Built {archive}")


if __name__ == "__main__":
    main()
