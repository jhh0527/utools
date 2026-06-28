# -*- mode: python ; coding: utf-8 -*-
"""7_3_mp4Search GUI 단일 실행 파일."""

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
_example = os.path.join(proot, "config", "stock_api.example.json")
datas = []
if os.path.isfile(_example):
    datas.append((_example, "config"))

a = Analysis(
    [os.path.join(proot, "run_mp4_search_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.font",
        "mp4_search",
        "mp4_search.gui_app",
        "mp4_search.stock_search",
        "mp4_search.download",
        "mp4_search.settings",
        "mp4_search.paths",
        "mp4_search.srt_parse",
        "mp4_search.naming",
        "mp4_search.timeline_compose",
        "mp4_search.section_group",
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        "PIL._tkinter_finder",
        "windnd",
        "wisdom_root",
        "wisdom_bootstrap",
        "wisdom_workspace",
        "wisdom_gui_host",
    ]
    + collect_submodules("mp4_search"),
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
    name="7_3_mp4Search_gui",
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
