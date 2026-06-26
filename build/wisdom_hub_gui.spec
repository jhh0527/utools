# -*- mode: python ; coding: utf-8 -*-
"""wisdom 통합 허브 — 파이프라인 GUI 탭 (단일 exe)."""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

specdir = os.path.dirname(os.path.abspath(SPEC))
wisdom_repo = os.path.normpath(os.path.join(specdir, ".."))
_module_dirs = (
    "1_1_textTo700Text",
    "2_1_ttsToVoice",
    "2_2_srtToImage",
    "2_3_stt",
    "2_4_imageToMp4",
    "3_1_pngFileName",
    "3_2_pngToJpg",
    "4_1_video",
    "4_2_ShortVideo",
    "6_thumbnail",
    "7_utube",
    "7_2_utubeEdit",
    "9_mdFile",
)
_pathex = [wisdom_repo] + [
    os.path.join(wisdom_repo, d) for d in _module_dirs
]

_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
    os.path.join(wisdom_repo, "wisdom_content_paths.py"),
    os.path.join(wisdom_repo, "wisdom_gui_host.py"),
    os.path.join(wisdom_repo, "wisdom_hub", "__init__.py"),
    os.path.join(wisdom_repo, "wisdom_hub", "pipeline.py"),
    os.path.join(wisdom_repo, "wisdom_hub", "loaders.py"),
    os.path.join(wisdom_repo, "wisdom_hub", "gui_app.py"),
    os.path.join(wisdom_repo, "1_1_textTo700Text", "manuscript_700_splitter.py"),
    os.path.join(wisdom_repo, "1_1_textTo700Text", "genspark_chat.py"),
]
_pw_datas, _pw_binaries, _pw_hidden = collect_all("playwright")

_example = os.path.join(wisdom_repo, "2_1_ttsToVoice", "elsub_config.example.json")
_image_guide = os.path.join(wisdom_repo, "2_2_srtToImage", "md", "image.md.txt")
datas = []
if os.path.isfile(_example):
    datas.append((_example, "."))
if os.path.isfile(_image_guide):
    datas.append((_image_guide, "md"))

_hidden_pkgs = (
    "elsub",
    "prompt2image",
    "stt",
    "image_to_mp4",
    "png_rename",
    "png2jpg",
    "scenevid",
    "shortvid",
    "utube",
    "utube_edit",
    "thumbnail_gui",
    "md_file",
    "wisdom_hub",
)
hiddenimports: list[str] = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.font",
    "tkinter.scrolledtext",
    "tkinter.colorchooser",
    "wisdom_root",
    "wisdom_bootstrap",
    "wisdom_workspace",
    "wisdom_content_paths",
    "wisdom_gui_host",
    "manuscript_700_splitter",
    "genspark_chat",
    "browser_cookie3",
    "playwright",
    "playwright.async_api",
    "faster_whisper",
    *_pw_hidden,
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageTk",
    "PIL._tkinter_finder",
]
for _pkg in _hidden_pkgs:
    hiddenimports += collect_submodules(_pkg)
hiddenimports += collect_submodules("yt_dlp")

a = Analysis(
    [os.path.join(wisdom_repo, "run_wisdom_hub_gui.py"), *_wisdom_scripts],
    pathex=_pathex,
    binaries=_pw_binaries,
    datas=datas + _pw_datas,
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
    name="wisdom_hub_gui",
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
