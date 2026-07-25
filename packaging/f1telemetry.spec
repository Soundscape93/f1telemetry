# -*- mode: python ; coding: utf-8 -*-
"""One-folder Windows build. Run from the repo root (f1telemetry/):

    pip install -e ".[package]"
    pyinstaller packaging/f1telemetry.spec

Output dist/f1telemetry/f1telemetry.exe (+ its _internal folder).
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# SPECPATH resolves to the repo root on some PyInstaller/OS combos and the packaging/
# subdir on others. Detect the repo root by marker (the dir that contains 'src') rather than
# assuming a fixed deph, so this pec works on Windows and Linux alike.
_here = os.path.abspath(SPECPATH)
REPO_ROOT = _here if os.path.isdir(os.path.join(_here, "src")) else os.path.dirname(_here)      # .../f1-telemetry/f1telemetry
IMPORT_ROOT = os.path.dirname(REPO_ROOT)                          # .../f1-telemetry (has the f1telemetry pkg)

entry = os.path.join(REPO_ROOT, "packaging", "entry.py")

# Flag SVGs must ship preserving the f1telemetry/sr/... layout, so resource_path() finds them
# under sys_MEIPASS (see paths.resource_path /docs/PACKAGING.md "Contract Phase 1 must honor").
flags_src = os.path.join(REPO_ROOT, "src", "ui", "assets", "flags")
datas = [(flags_src, "f1telemetry/src/ui/assets/flags")]
datas += collect_data_files("pyqtgraph")                # colormaps / icons pyqtgraph loads at runtime

# Lazy import PyInstaller can't see by static analysis (imported inside branches).
hiddenimports = (
    collect_submodules("pyqtgraph")
    + collect_submodules("zstandard")
    + ["zstandard.backend_c", "PySide6.QtSvg"]
)

# Trim heavy Qt modules we never use. If Qt fails to start on a user's machine, this is the first place to check.
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DAnimation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql",
    "tkinter", "matplotlib", "IPython",
]

a = Analysis(
    [entry],
    pathex=[IMPORT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="f1telemetry",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                           # UPX raises AV false positives; not worth it for trusted testers
    console=False,                      # windowed; cras dialog + file log handle errors. True to debug.
    disable_windowed_traceback=False,
    icon=None,                          # add an .ico here later
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="f1telemetry",
)