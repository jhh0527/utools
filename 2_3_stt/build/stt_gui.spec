# -*- mode: python ; coding: utf-8 -*-
"""2_3_stt GUI 단일 실행 파일 (콘솔 없음)."""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

specdir = os.path.dirname(os.path.abspath(SPEC))
proot = os.path.normpath(os.path.join(specdir, ".."))
wisdom_repo = os.path.normpath(os.path.join(proot, ".."))
_wisdom_scripts = [
    os.path.join(wisdom_repo, "wisdom_root.py"),
    os.path.join(wisdom_repo, "wisdom_bootstrap.py"),
    os.path.join(wisdom_repo, "wisdom_workspace.py"),
    os.path.join(wisdom_repo, "wisdom_gui_host.py"),
]

_fw_datas, _fw_binaries, _fw_hidden = collect_all("faster_whisper")
_ct2_datas, _ct2_binaries, _ct2_hidden = collect_all("ctranslate2")
_av_datas, _av_binaries, _av_hidden = collect_all("av")
_ort_datas, _ort_binaries, _ort_hidden = collect_all("onnxruntime")

a = Analysis(
    [os.path.join(proot, "run_stt_gui.py"), *_wisdom_scripts],
    pathex=[proot, wisdom_repo],
    binaries=_fw_binaries + _ct2_binaries + _av_binaries + _ort_binaries,
    datas=_fw_datas + _ct2_datas + _av_datas + _ort_datas,
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.font",
        "tkinter.scrolledtext",
        "stt",
        "stt.gui_app",
        "stt.whisper_stt",
        "stt.text_diff",
        "stt.settings",
        "stt.paths",
        "faster_whisper",
        "windnd",
        "wisdom_root",
        "wisdom_bootstrap",
        "wisdom_workspace",
        "wisdom_gui_host",
        *_fw_hidden,
        *_ct2_hidden,
        *_av_hidden,
        *_ort_hidden,
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
    name="2_3_stt_gui",
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
