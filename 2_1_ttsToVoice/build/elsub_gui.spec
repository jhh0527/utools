# -*- mode: python ; coding: utf-8 -*-
"""2_1_ttsToVoice GUI 빌드 스펙 (콘솔 없음)."""

import os

from PyInstaller.utils.hooks import collect_submodules

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))
wisdom_repo = os.path.normpath(os.path.join(proot, ".."))
_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
    os.path.join(wisdom_repo, "wisdom_content_paths.py"),
]

_example = os.path.join(proot, "elsub_config.example.json")
datas = [(_example, ".")] if os.path.isfile(_example) else []

hidden = collect_submodules("elsub")
hidden += [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.font",
    "tkinter.scrolledtext",
    "wisdom_root",
    "wisdom_bootstrap",
    "wisdom_workspace",
    "wisdom_content_paths",
]

a = Analysis(
    [os.path.join(proot, "run_elsub_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
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
    name="2_1_ttsToVoice_gui",
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
