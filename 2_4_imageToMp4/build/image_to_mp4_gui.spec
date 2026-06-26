# -*- mode: python ; coding: utf-8 -*-
"""2_4_imageToMp4 GUI 단일 실행 파일 (콘솔 없음)."""

import os

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))
wisdom_repo = os.path.normpath(os.path.join(proot, ".."))
_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
    os.path.join(wisdom_repo, "wisdom_gui_host.py"),
]

a = Analysis(
    [os.path.join(proot, "run_image_to_mp4_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.font",
        "image_to_mp4",
        "image_to_mp4.gui_app",
        "image_to_mp4.comfyui_client",
        "image_to_mp4.generator",
        "image_to_mp4.workflow",
        "image_to_mp4.settings",
        "image_to_mp4.paths",
        "wisdom_root",
        "wisdom_bootstrap",
        "wisdom_workspace",
        "wisdom_gui_host",
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
    name="2_4_imageToMp4_gui",
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
