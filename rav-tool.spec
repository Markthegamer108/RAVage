# pyinstaller spec for rav-tool.
#
# builds two executables:
#   rav-tool  - the gui (no console window on win/mac)
#   rav-cli   - the command line converter
#
# pyinstaller cannot cross-compile, so each binary has to be built on its
# own OS:
#   windows  -> rav-tool.exe + rav-cli.exe
#   macos    -> rav-tool.app + rav-cli
#   linux    -> rav-tool (gui, no terminal output) + rav-cli
#
# build:  pyinstaller --noconfirm --clean rav-tool.spec

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
    name="rav-tool",
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
    name="rav-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

# on macos the gui becomes a proper .app, the cli stays a plain binary
if sys.platform == "darwin":
    app = BUNDLE(
        gui,
        name="rav-tool.app",
        icon=None,
        bundle_identifier="io.github.ravtool.rav-tool",
    )
