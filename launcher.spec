# -*- mode: python ; coding: utf-8 -*-

# All ui.* and core.* modules are loaded via importlib.import_module() at
# runtime, so PyInstaller's static analysis misses them. List them explicitly.
_hidden = [
    "core.state",
    "core.config",
    "core.interpreter",
    "core.process",
    "core.build",
    "core.coder",
    "core.automation",
    "core.ollama",
    "core.repl",
    "core.notifications",
    "core.diagnostics",
    "ui.theme",
    "ui.main_window",
    "ui.coder_window",
    "ui.config_window",
    "ui.tool_windows",
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
