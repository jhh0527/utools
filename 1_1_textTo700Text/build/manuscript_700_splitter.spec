# -*- mode: python ; coding: utf-8 -*-
"""대본 700자 분할 GUI (콘솔 없음, 단일 exe)."""

import os
from PyInstaller.utils.hooks import collect_all

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))
wisdom_repo = os.path.normpath(os.path.join(proot, ".."))
app_py = os.path.join(proot, "manuscript_700_splitter.py")
_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
]
_pw_datas, _pw_binaries, _pw_hidden = collect_all("playwright")

hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.font",
    "wisdom_root",
    "wisdom_bootstrap",
    "wisdom_workspace",
]

a = Analysis(
    [app_py, *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=_pw_binaries,
    datas=_pw_datas,
    hiddenimports=hiddenimports
    + [
        "genspark_chat",
        "playwright",
        "playwright.async_api",
        *_pw_hidden,
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
    name="manuscript_700_splitter",
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
