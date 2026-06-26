# -*- mode: python ; coding: utf-8 -*-
"""7_utube GUI — 7_utube_gui.exe."""

import os

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))
wisdom_repo = os.path.normpath(os.path.join(proot, ".."))
_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
]

a = Analysis(
    [os.path.join(proot, "run_utube_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "utube",
        "utube.api",
        "utube.cli",
        "utube.config",
        "utube.gui_app",
        "utube.format_util",
        "utube.models",
        "utube.export_util",
        "utube.categories",
        "utube.thumb_util",
        "utube.translate_util",
        "openpyxl",
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        "wisdom_root",
        "wisdom_bootstrap",
        "wisdom_workspace",
    ],
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
    name="7_utube_gui",
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
)
