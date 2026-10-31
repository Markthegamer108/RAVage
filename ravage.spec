import sys

datas = [("data/keytable.bin", "data")]

a = Analysis(
    ["rav_gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

gui = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ravage",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

b = Analysis(
    ["rav_cli.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyzb = PYZ(b.pure)

cli = EXE(
    pyzb,
    b.scripts,
    b.binaries,
    b.datas,
    [],
    name="ravage-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        gui,
        name="ravage.app",
        icon=None,
        bundle_identifier="io.github.ravage.ravage",
    )
