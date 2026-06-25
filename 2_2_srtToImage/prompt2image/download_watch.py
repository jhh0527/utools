# -*- coding: utf-8 -*-
"""다운로드·PNG 폴더 감시 → SRT_XXX.png 로 정리."""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from prompt2image.srt_naming import (
    IMAGE_EXTS,
    format_srt_filename,
    is_image_file,
    is_incomplete_download,
    list_srt_pngs,
    parse_srt_number,
)


def _file_stable(path: Path, *, wait_s: float = 0.35) -> bool:
    try:
        s1 = path.stat().st_size
    except OSError:
        return False
    time.sleep(wait_s)
    try:
        s2 = path.stat().st_size
    except OSError:
        return False
    return s1 > 0 and s1 == s2


def _to_png(src: Path, dest: Path) -> None:
    if src.suffix.lower() == ".png":
        if src.resolve() != dest.resolve():
            shutil.move(str(src), str(dest))
        return
    from PIL import Image

    with Image.open(src) as im:
        im.convert("RGB").save(dest, format="PNG")
    if src.resolve() != dest.resolve():
        try:
            src.unlink()
        except OSError:
            pass


class DownloadWatcher:
    """png 폴더·시스템 Downloads 에 생기는 이미지를 SRT_XXX.png 로 이름 변경."""

    def __init__(
        self,
        png_dir: Path,
        *,
        on_renamed: Callable[[Path], None] | None = None,
        next_number: Callable[[], int] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.png_dir = png_dir
        self.on_renamed = on_renamed
        self._next_number = next_number
        self.poll_interval = poll_interval
        self._processed: set[str] = set()
        self._sizes: dict[str, tuple[int, float]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def default_downloads_dir(self) -> Path:
        home = Path.home()
        for name in ("Downloads", "다운로드"):
            p = home / name
            if p.is_dir():
                return p
        return home / "Downloads"

    def _next_target_number(self) -> int:
        if self._next_number is not None:
            return self._next_number()
        from prompt2image.srt_naming import next_scene_number

        return next_scene_number(self.png_dir)

    def _mark_processed(self, path: Path) -> None:
        self._processed.add(str(path.resolve()))

    def _already_processed(self, path: Path) -> bool:
        return str(path.resolve()) in self._processed

    def _unique_dest(self, number: int) -> Path:
        n = number
        while True:
            dest = self.png_dir / format_srt_filename(n)
            if not dest.exists():
                return dest
            n += 1

    def _assign_srt_name(self, src: Path) -> Path | None:
        if not is_image_file(src):
            return None
        if parse_srt_number(src.name) is not None and src.parent.resolve() == self.png_dir.resolve():
            self._mark_processed(src)
            return src
        if not _file_stable(src):
            return None
        if self._already_processed(src):
            return None

        target_n = self._next_target_number()
        dest = self._unique_dest(target_n)
        self.png_dir.mkdir(parents=True, exist_ok=True)
        try:
            if src.parent.resolve() != self.png_dir.resolve():
                tmp = self.png_dir / f"_incoming_{src.stem}{src.suffix.lower()}"
                if tmp.exists():
                    tmp.unlink()
                shutil.move(str(src), str(tmp))
                _to_png(tmp, dest)
            else:
                _to_png(src, dest)
        except OSError:
            return None

        self._mark_processed(dest)
        if self.on_renamed:
            self.on_renamed(dest)
        return dest

    def _scan_dir(self, folder: Path, *, include_named: bool) -> None:
        if not folder.is_dir():
            return
        try:
            entries = list(folder.iterdir())
        except OSError:
            return
        for path in entries:
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            if is_incomplete_download(path):
                continue
            key = str(path.resolve())
            try:
                st = path.stat()
            except OSError:
                continue
            prev = self._sizes.get(key)
            self._sizes[key] = (st.st_size, st.st_mtime)
            if prev and prev == (st.st_size, st.st_mtime):
                if include_named or parse_srt_number(path.name) is None:
                    self._assign_srt_name(path)

    def scan_once(self) -> None:
        self.png_dir.mkdir(parents=True, exist_ok=True)
        self._scan_dir(self.png_dir, include_named=False)
        self._scan_dir(self.default_downloads_dir(), include_named=False)
        for p in list_srt_pngs(self.png_dir):
            self._mark_processed(p)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.scan_once()

        def loop() -> None:
            while not self._stop.wait(self.poll_interval):
                try:
                    self.scan_once()
                except Exception:
                    pass

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
