# PyInstaller spec for the Visual Cataloguer desktop app.
#
# Build (from the repo root, with the frontend already built):
#   pyinstaller packaging/desktop.spec
#
# Produces a single windowed executable in dist/ (wrapped in a .app
# bundle on macOS). Tesseract is intentionally NOT bundled: offline OCR
# mode needs a system install, AI identification works without it.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

repo_root = Path(SPECPATH).parent

datas = [
    # Built frontend, served by FastAPI relative to cataloguer/api/__file__.
    (str(repo_root / "cataloguer" / "api" / "static" / "dist"), "cataloguer/api/static/dist"),
]

hiddenimports = [
    # uvicorn loads its loops/protocols by string name at runtime.
    *collect_submodules("uvicorn"),
    "anthropic",
]

a = Analysis(
    [str(repo_root / "packaging" / "pyi_entry.py")],
    pathex=[str(repo_root)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="VisualCataloguer",
    console=False,
    upx=False,
    strip=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Visual Cataloguer.app",
        bundle_identifier="com.retroverse.visual-cataloguer",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
