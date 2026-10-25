# PyInstaller spec, shared by the Linux and Windows builds: pyinstaller packaging/skibasar.spec
import subprocess
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
pkg = root / "src" / "skibasar"

# Stamp the build with the git tag, e.g. "v0.3.0-beta" (untagged: "v0.3.0-beta-2-g1a2b3c4")
try:
    version = subprocess.run(
        ["git", "describe", "--tags", "--always", "--dirty"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.strip()
except (OSError, subprocess.CalledProcessError):
    version = "unbekannt"
version_file = pkg / "_version.py"
version_file.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
print(f"Version: {version}")

a = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root / "src")],
    datas=[
        (str(pkg / "templates"), "skibasar/templates"),
        (str(pkg / "static"), "skibasar/static"),
    ],
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("skibasar"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="skibasar",
    console=True,  # the console shows the LAN URL, PIN and QR code
    upx=False,
)

# Only the bundled exe should carry the stamp; dev runs report "dev"
version_file.unlink()
