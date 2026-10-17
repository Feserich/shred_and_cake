# PyInstaller spec, shared by the Linux and Windows builds: pyinstaller packaging/skibasar.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
pkg = root / "src" / "skibasar"

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
