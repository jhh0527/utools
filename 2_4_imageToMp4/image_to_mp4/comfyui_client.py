# -*- coding: utf-8 -*-
"""ComfyUI REST API 클라이언트."""

from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from image_to_mp4.workflow import (
    build_animatediff_workflow,
    load_custom_workflow,
    patch_custom_workflow,
    resolve_seed,
)


class ComfyUIError(RuntimeError):
    pass


ProgressCallback = Callable[[str], None]


def _base_url(url: str) -> str:
    u = url.strip().rstrip("/")
    if not u:
        raise ComfyUIError("ComfyUI URL이 비어 있습니다.")
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    return u


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> bytes:
    url = urljoin(base + "/", path.lstrip("/"))
    req = Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ComfyUIError(f"ComfyUI HTTP {e.code}: {body or e.reason}") from e
    except URLError as e:
        raise ComfyUIError(f"ComfyUI 연결 실패: {e.reason}") from e


def probe_server(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """ComfyUI 서버 연결 확인. (성공 여부, 안내 메시지)"""
    try:
        base = _base_url(url)
    except ComfyUIError as e:
        return False, str(e)

    last_err = ""
    for path in ("/system_stats", "/queue", "/"):
        try:
            _request(base, path, timeout=timeout)
            return True, f"ComfyUI 서버 연결 OK — {base}"
        except ComfyUIError as e:
            last_err = str(e)

    if "10061" in last_err or "refused" in last_err.lower() or "거부" in last_err:
        hint = (
            f"ComfyUI가 실행 중이 아닙니다.\n{base}\n\n"
            "ComfyUI를 먼저 실행한 뒤 다시 「서버 확인」을 누르세요.\n"
            "(ComfyUI 기본 포트: 8188)"
        )
    elif "timed out" in last_err.lower() or "timeout" in last_err.lower():
        hint = f"ComfyUI 응답 시간 초과입니다.\n{base}\n\n서버 주소·방화벽을 확인하세요."
    else:
        hint = f"ComfyUI 서버에 연결할 수 없습니다.\n{base}\n\n{last_err}"
    return False, hint


def check_server(url: str, timeout: float = 5.0) -> bool:
    ok, _ = probe_server(url, timeout=timeout)
    return ok


def upload_image(url: str, image_path: Path) -> str:
    base = _base_url(url)
    mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    boundary = f"----ComfyUIBoundary{uuid.uuid4().hex}"
    body_parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body_parts.append(value.encode())
        body_parts.append(b"\r\n")

    add_field("overwrite", "true")
    add_field("type", "input")
    add_field("subfolder", "")

    file_bytes = image_path.read_bytes()
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(
        (
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
    )
    body_parts.append(file_bytes)
    body_parts.append(b"\r\n")
    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    raw = _request(
        base,
        "/upload/image",
        method="POST",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=120.0,
    )
    info = json.loads(raw.decode("utf-8"))
    name = info.get("name")
    if not isinstance(name, str) or not name:
        raise ComfyUIError(f"이미지 업로드 실패: {info}")
    return name


def queue_prompt(url: str, workflow: dict[str, Any], client_id: str | None = None) -> str:
    base = _base_url(url)
    cid = client_id or str(uuid.uuid4())
    payload = json.dumps({"prompt": workflow, "client_id": cid}).encode("utf-8")
    raw = _request(
        base,
        "/prompt",
        method="POST",
        data=payload,
        headers={"Content-Type": "application/json"},
        timeout=60.0,
    )
    info = json.loads(raw.decode("utf-8"))
    prompt_id = info.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        err = info.get("error") or info.get("node_errors") or info
        raise ComfyUIError(f"워크플로 제출 실패: {err}")
    return prompt_id


def wait_for_prompt(
    url: str,
    prompt_id: str,
    *,
    timeout_sec: float = 900.0,
    poll_sec: float = 2.0,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    base = _base_url(url)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        raw = _request(base, f"/history/{prompt_id}", timeout=30.0)
        hist = json.loads(raw.decode("utf-8"))
        if prompt_id in hist:
            entry = hist[prompt_id]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = status.get("messages") or entry
                raise ComfyUIError(f"ComfyUI 처리 오류: {msgs}")
            return entry
        if on_progress:
            on_progress("ComfyUI 처리 중…")
        time.sleep(poll_sec)
    raise ComfyUIError(f"ComfyUI 처리 시간 초과 ({int(timeout_sec)}초)")


def _download_file(base: str, filename: str, subfolder: str, file_type: str, dest: Path) -> Path:
    q = urlencode({"filename": filename, "subfolder": subfolder, "type": file_type})
    data = _request(base, f"/view?{q}", timeout=120.0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def collect_output_files(history: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(filename, subfolder, type) 목록."""
    outputs = history.get("outputs") or {}
    found: list[tuple[str, str, str]] = []
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for key in ("gifs", "videos", "images"):
            items = node_out.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                fn = item.get("filename")
                if not isinstance(fn, str):
                    continue
                sub = item.get("subfolder") or ""
                typ = item.get("type") or "output"
                found.append((fn, sub, typ))
    return found


def download_outputs(
    url: str,
    history: dict[str, Any],
    output_dir: Path,
    *,
    prefer_video: bool = True,
) -> list[Path]:
    base = _base_url(url)
    files = collect_output_files(history)
    if not files:
        raise ComfyUIError("ComfyUI 출력 파일을 찾을 수 없습니다.")

    if prefer_video:
        video_ext = {".mp4", ".webm", ".gif", ".avi", ".mov"}
        videos = [f for f in files if Path(f[0]).suffix.lower() in video_ext]
        if videos:
            files = videos

    saved: list[Path] = []
    for fn, sub, typ in files:
        dest = output_dir / fn
        saved.append(_download_file(base, fn, sub, typ, dest))
    return saved


def build_workflow(
    *,
    image_name: str,
    positive: str,
    negative: str,
    checkpoint: str,
    motion_module: str,
    frames: int,
    fps: int,
    seed: int,
    steps: int,
    cfg: float,
    denoise: float,
    workflow_path: Path | None = None,
) -> dict[str, Any]:
    if workflow_path and workflow_path.is_file():
        wf = load_custom_workflow(workflow_path)
        return patch_custom_workflow(
            wf,
            image_name=image_name,
            positive=positive,
            negative=negative,
            frames=frames,
            fps=fps,
            seed=seed,
        )
    return build_animatediff_workflow(
        image_name=image_name,
        positive=positive,
        negative=negative,
        checkpoint=checkpoint,
        motion_module=motion_module,
        frames=frames,
        fps=fps,
        seed=seed,
        steps=steps,
        cfg=cfg,
        denoise=denoise,
    )


def animate_image_to_mp4(
    *,
    url: str,
    image_path: Path,
    output_dir: Path,
    positive: str,
    negative: str,
    checkpoint: str,
    motion_module: str,
    frames: int,
    fps: int,
    seed: int,
    steps: int,
    cfg: float,
    denoise: float,
    workflow_path: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """이미지 1장을 ComfyUI AnimateDiff로 MP4로 변환."""
    if not image_path.is_file():
        raise ComfyUIError(f"입력 이미지 없음: {image_path}")

    if on_progress:
        on_progress(f"업로드: {image_path.name}")
    uploaded = upload_image(url, image_path)

    actual_seed = resolve_seed(seed)
    workflow = build_workflow(
        image_name=uploaded,
        positive=positive,
        negative=negative,
        checkpoint=checkpoint,
        motion_module=motion_module,
        frames=frames,
        fps=fps,
        seed=actual_seed,
        steps=steps,
        cfg=cfg,
        denoise=denoise,
        workflow_path=workflow_path,
    )

    if on_progress:
        on_progress("워크플로 제출…")
    prompt_id = queue_prompt(url, workflow)

    if on_progress:
        on_progress(f"AnimateDiff 처리 중 (seed={actual_seed})…")
    history = wait_for_prompt(url, prompt_id, on_progress=on_progress)

    out_name = f"{image_path.stem}.mp4"
    saved = download_outputs(url, history, output_dir, prefer_video=True)
    if len(saved) == 1:
        final = output_dir / out_name
        if saved[0] != final:
            if final.is_file():
                final.unlink()
            saved[0].replace(final)
            return final
        return saved[0]

    for p in saved:
        if p.suffix.lower() == ".mp4":
            final = output_dir / out_name
            if p != final:
                if final.is_file():
                    final.unlink()
                p.replace(final)
                return final
            return p

    raise ComfyUIError("MP4 출력을 찾을 수 없습니다.")
