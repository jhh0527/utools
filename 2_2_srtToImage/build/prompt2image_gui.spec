# -*- mode: python ; coding: utf-8 -*-
"""GUI 단일 실행 파일 (콘솔 없음)."""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))
wisdom_repo = os.path.normpath(os.path.join(proot, ".."))
_png_rename_root = os.path.join(wisdom_repo, "3_1_pngFileName")
_hidden_png = collect_submodules("png_rename")
_pw_datas, _pw_binaries, _pw_hidden = collect_all("playwright")
_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
]

a = Analysis(
    [os.path.join(proot, "run_prompt2image_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo, _png_rename_root],
    binaries=_pw_binaries,
    datas=(
        [(os.path.join(proot, "md", "image.md.txt"), "md")]
        if os.path.isfile(os.path.join(proot, "md", "image.md.txt"))
        else []
    )
    + _pw_datas,
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.font",
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        "pytesseract",
        "prompt2image.browser_launch",
        "prompt2image.clipboard_util",
        "prompt2image.guide_loader",
        "prompt2image.srt_cues",
        "prompt2image.cue_match",
        "prompt2image.download_watch",
        "prompt2image.image_ocr",
        "prompt2image.settings",
        "prompt2image.srt_naming",
        "prompt2image.genspark_automation",
        "prompt2image.genspark_selectors",
        "prompt2image.genspark_cookies",
        "browser_cookie3",
        "playwright",
        "playwright.async_api",
        *_pw_hidden,
        "wisdom_root",
        "wisdom_bootstrap",
        "wisdom_workspace",
        *_hidden_png,
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
    name="2_2_srtToImage_gui",
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
