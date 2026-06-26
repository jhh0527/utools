# -*- mode: python ; coding: utf-8 -*-
"""GUI 단일 실행 파일 (콘솔 없음)."""

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
    [os.path.join(proot, "run_shortvid_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.font",
        "shortvid",
        "shortvid.compose_render",
        "shortvid.compose_overrides",
        "shortvid.ffmpeg_render",
        "shortvid.subtitles",
        "shortvid.srt_parse",
        "shortvid.schema",
        "shortvid.assets",
        "shortvid.media_paths",
        "shortvid.repo_paths",
        "shortvid.motion",
        "shortvid.srt_image_effects",
        "shortvid.gui_app",
        "shortvid.subprocess_util",
        "wisdom_root",
        "wisdom_bootstrap",
        "wisdom_workspace",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
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
    name="4_2_shortvideo_gui",
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
