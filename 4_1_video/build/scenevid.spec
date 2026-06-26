# -*- mode: python ; coding: utf-8 -*-
"""CLI 단일 실행 파일 (콘솔)."""

import os

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))

a = Analysis(
    [os.path.join(proot, "run_scenevid.py")],
    pathex=[proot],
    binaries=[],
    datas=[],
    hiddenimports=[
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
        "scenevid.gui_app",
        "scenevid.subprocess_util",
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
    name="4_1_video",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
