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
    os.path.join(wisdom_repo, "wisdom_content_paths.py"),
]

a = Analysis(
    [os.path.join(proot, "run_scenevid_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.font",
        "scenevid",
        "scenevid.cli",
        "scenevid.compose_render",
        "scenevid.compose_overrides",
        "scenevid.ffmpeg_render",
        "scenevid.subtitles",
        "scenevid.srt_parse",
        "scenevid.schema",
        "scenevid.script_parse",
        "scenevid.assets",
        "scenevid.media_paths",
        "scenevid.repo_paths",
        "scenevid.motion",
        "scenevid.srt_image_effects",
        "scenevid.gui_app",
        "scenevid.subprocess_util",
        "wisdom_root",
        "wisdom_bootstrap",
        "wisdom_workspace",
        "wisdom_content_paths",
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
    name="4_1_video_gui",
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
