# -*- mode: python ; coding: utf-8 -*-
"""7_2_utubeEdit GUI — 7_2_utube_edit_gui.exe."""

import os

from PyInstaller.utils.hooks import collect_submodules

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))
wisdom_repo = os.path.normpath(os.path.join(proot, ".."))
_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
    os.path.join(wisdom_repo, "wisdom_gui_host.py"),
]

hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "utube_edit",
    "utube_edit.download",
    "utube_edit.gui_app",
    "utube_edit.media_paths",
    "utube_edit.models",
    "utube_edit.paths",
    "utube_edit.scene_detect",
    "utube_edit.subprocess_util",
    "utube_edit.video_edit",
    "utube_edit.video_preview",
    "wisdom_root",
    "wisdom_bootstrap",
    "wisdom_workspace",
    "wisdom_gui_host",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
]
hiddenimports += collect_submodules("yt_dlp")

a = Analysis(
    [os.path.join(proot, "run_utube_edit_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
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
    name="7_2_utube_edit_gui",
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
