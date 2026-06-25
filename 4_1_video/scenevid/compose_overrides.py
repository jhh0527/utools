"""compose_overrides.json — SRT 큐(구간)별 이미지 교체·삭제(검은 화면)·큐 뒤 삽입."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenevid.motion import _same_compose_image_path, normalize_effect

# 이미지·영상 파일 확장자 (SRT 번호 매핑·팔레트)
COMPOSE_IMAGE_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
COMPOSE_VIDEO_EXTS: tuple[str, ...] = (".mp4",)
COMPOSE_MEDIA_EXTS: tuple[str, ...] = COMPOSE_IMAGE_EXTS + COMPOSE_VIDEO_EXTS


def is_compose_video_path(path: Path) -> bool:
    return path.suffix.lower() in COMPOSE_VIDEO_EXTS

# 파일명에서 SRT 번호를 뽑는 패턴. 대소문자 무시, 자리수 무관, 밑줄 선택.
# 매치되는 예) srt_1, srt_01, SRT_001, srt001, SRT-1
_SRT_IMAGE_STEM_RE = re.compile(r"^srt[-_]?0*(\d+)$", re.IGNORECASE)

BLACK_TOKENS = frozenset(
    {
        "",
        "__black__",
        "__delete__",
        "__remove__",
        "black",
        "delete",
        "remove",
        "none",
        "삭제",
        "검정",
        "블랙",
    }
)


def _is_black_token(v: Any) -> bool:
    if v is None:
        return True
    s = str(v).strip().lower()
    return s in BLACK_TOKENS


def _parse_image_effects(raw: Any, assets_root: Path) -> dict[str, str]:
    """이미지 파일(절대 경로 문자열 키) → 효과. JSON 키는 assets 기준 상대 경로 또는 절대 경로."""
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    root = assets_root.resolve()
    for k, val in raw.items():
        sk = str(k).strip()
        sv = str(val).strip()
        if not sk or not sv:
            continue
        p = Path(sk)
        if not p.is_absolute():
            p = (root / p).resolve()
        else:
            p = p.resolve()
        out[str(p)] = sv
    return out


def _parse_cue_effects(raw: Any) -> dict[int, str]:
    """1-based 큐 순번 또는 SRT 표시 번호 → 효과 문자열(원문, 렌더 시 normalize)."""
    out: dict[int, str] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            idx = int(str(k).strip())
        except ValueError:
            continue
        if idx < 1:
            continue
        s = str(v).strip()
        if s:
            out[idx] = s
    return out


def _parse_cue_images(raw: Any, assets_root: Path) -> dict[int, Path | None]:
    """1-based 큐 인덱스 → Path(교체 이미지) 또는 None(검은 화면)."""
    out: dict[int, Path | None] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            idx = int(str(k).strip())
        except ValueError:
            continue
        if idx < 1:
            continue
        if _is_black_token(v):
            out[idx] = None
            continue
        p = Path(str(v).strip())
        if not p.is_absolute():
            p = (assets_root / p).resolve()
        out[idx] = p
    return out


@dataclass(frozen=True)
class InsertClipSpec:
    after_cue_index: int  # 1-based: 해당 큐 **뒤**에 삽입
    duration_sec: float
    image: Path
    subtitle: str
    effect: str


def _parse_inserts(raw: Any, assets_root: Path) -> list[InsertClipSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    inserts: list[InsertClipSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            after = int(item.get("after_cue_index", item.get("after_cue", 0)))
        except (TypeError, ValueError):
            continue
        if after < 0:
            continue
        try:
            dur = float(item.get("duration_sec", item.get("duration", 0)))
        except (TypeError, ValueError):
            continue
        if dur <= 0:
            continue
        img_raw = item.get("image") or item.get("path")
        if not img_raw:
            continue
        ip = Path(str(img_raw).strip())
        if not ip.is_absolute():
            ip = (assets_root / ip).resolve()
        sub = str(item.get("subtitle", item.get("text", "")) or "").strip()
        eff = str(item.get("effect") or "none").strip() or "none"
        inserts.append(
            InsertClipSpec(
                after_cue_index=after,
                duration_sec=dur,
                image=ip,
                subtitle=sub,
                effect=eff,
            )
        )
    inserts.sort(key=lambda x: (x.after_cue_index, x.duration_sec))
    return inserts


def inserts_by_after_cue(inserts: list[InsertClipSpec]) -> dict[int, list[InsertClipSpec]]:
    g: dict[int, list[InsertClipSpec]] = defaultdict(list)
    for ins in inserts:
        g[ins.after_cue_index].append(ins)
    for k in g:
        g[k].sort(key=lambda x: (str(x.image), x.duration_sec))
    return g


def load_compose_overrides(
    path: Path | None, assets_root: Path
) -> tuple[dict[int, Path | None], list[InsertClipSpec], dict[int, str], dict[str, str]]:
    """JSON 로드. path가 None이거나 없으면 빈 규칙.

    - ``cue_effects``: 큐 순번(1…) 또는 SRT 블록 표시 번호 → 효과
    - ``image_effects``: 이미지 경로(상대·절대) → 효과 (같은 파일이 여러 큐에 쓰이면 동일 효과)
    """
    if path is None or not path.is_file():
        return {}, [], {}, {}
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, dict):
        return {}, [], {}, {}
    ar = assets_root.resolve()
    cue_raw = data.get("cue_images") or data.get("replace_by_cue") or data.get("cue_image")
    cues = _parse_cue_images(cue_raw, ar)
    ins = _parse_inserts(data.get("insert_after_cue") or data.get("inserts"), ar)
    fx = _parse_cue_effects(data.get("cue_effects"))
    imx = _parse_image_effects(data.get("image_effects"), ar)
    return cues, ins, fx, imx


def default_overrides_path(assets_root: Path) -> Path:
    return assets_root.resolve() / "compose_overrides.json"


class _NoOverride:
    """per_cue_images_srt_mapping 내부용: 오버라이드 없음."""


_NO_OVERRIDE = _NoOverride()


def _override_for_block(
    overrides: dict[int, Path | None],
    block_index_1: int,
    image_map_id: int,
) -> Path | None | _NoOverride:
    """GUI는 보통 순번 키, JSON은 SRT 표시 번호 키를 쓸 수 있어 둘 다 조회합니다."""
    if block_index_1 in overrides:
        return overrides[block_index_1]
    if image_map_id in overrides:
        return overrides[image_map_id]
    return _NO_OVERRIDE


def resolve_cue_effect_override(
    block_index_1: int,
    image_map_id: int,
    cue_effects: dict[int, str],
) -> str | None:
    """cue_images와 동일하게 순번(1…) 또는 SRT 표시 번호 키로 조회."""
    if block_index_1 in cue_effects:
        return cue_effects[block_index_1]
    if image_map_id in cue_effects:
        return cue_effects[image_map_id]
    return None


def resolved_motion_effects_per_cue(
    map_ids: list[int],
    resolved_imgs: list[Path | None],
    cue_fx: dict[int, str],
    img_fx: dict[str, str],
    eff_lines: list[str],
) -> list[str]:
    """큐별 최종 모션 토큰.

    직전 큐와 해석된 이미지 경로가 같으면(이전 유지) 모션 토큰도 그대로 이어 씁니다.
    이미지가 바뀐 큐만 ``cue_effects`` → ``image_effects`` → ``compose_effects`` 줄 순으로
    새 효과를 고릅니다. 검은 구간(이미지 없음)은 효과를 이어받지 않으며,
    직전에 보이던 이미지·효과 상태는 다음 이미지 큐까지 유지됩니다.
    """
    n = len(map_ids)
    if n == 0:
        return []
    if len(resolved_imgs) != n or len(eff_lines) != n:
        raise ValueError("map_ids, resolved_imgs, eff_lines 길이가 같아야 합니다.")

    out: list[str] = []
    prev_img: Path | None = None
    prev_eff: str = "none"

    for i in range(n):
        cue_i = i + 1
        mid = map_ids[i]
        img = resolved_imgs[i]
        if img is not None and is_compose_video_path(img):
            out.append("none")
            prev_img = img
            prev_eff = "none"
            continue
        if img is not None and _same_compose_image_path(img, prev_img):
            e = prev_eff
        else:
            ov = resolve_cue_effect_override(cue_i, mid, cue_fx)
            if ov is not None:
                e = normalize_effect(ov)
            elif img is not None:
                ik = str(img.resolve())
                e = normalize_effect(img_fx[ik]) if ik in img_fx else normalize_effect(eff_lines[i])
            else:
                e = normalize_effect(eff_lines[i])
        out.append(e)
        if img is not None:
            prev_img = img
            prev_eff = e

    return out


def index_srt_numbered_images(images_dir: Path) -> dict[int, Path]:
    """``images_dir`` 안의 ``srt_NN.*`` / ``SRT_NNN.*`` 등을 한 번 스캔해 ``{번호: 경로}`` 로 인덱스합니다.

    인식 규칙:
      - 대소문자 무시: ``srt``, ``SRT`` 모두 허용
      - 구분자 선택: ``srt_001``, ``srt-1``, ``srt001`` 모두 허용
      - 자릿수 무관: ``1`` 도, ``001`` 도 같은 번호로 인식
    같은 번호의 파일이 여러 개면 정렬 후 첫 번째 파일을 사용합니다.
    """
    idx: dict[int, Path] = {}
    d = images_dir.resolve()
    if not d.is_dir():
        return idx
    for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in COMPOSE_MEDIA_EXTS:
            continue
        m = _SRT_IMAGE_STEM_RE.match(p.stem)
        if not m:
            continue
        n = int(m.group(1))
        idx.setdefault(n, p.resolve())
    return idx


def image_stem_number(path: Path) -> int | None:
    """``SRT_150.jpg`` → 150. 패턴에 맞지 않으면 ``None``."""
    m = _SRT_IMAGE_STEM_RE.match(path.stem)
    return int(m.group(1)) if m else None


def pick_image_for_srt_second(image_index: dict[int, Path], start_ms: int) -> Path | None:
    """구간 시작 시각(초)에 맞는 이미지: 파일 번호 ≤ 시작초 인 것 중 **가장 큰** 번호.

    ``2_2_srtToImage`` 라벨과 동일: ``SRT_000`` = 0초, ``SRT_150`` = 150초.

    예: 0ms 구간 → ``SRT_000``; 1500ms → ``SRT_001`` (000·001 있을 때).
    해당 초 이하 이미지가 없으면 ``None``.
    """
    sec = max(0, int(start_ms) // 1000)
    leq = [n for n in image_index if n <= sec]
    if not leq:
        return None
    return image_index[max(leq)]


def pick_image_for_srt_id(image_index: dict[int, Path], map_id: int) -> Path | None:
    """SRT 블록 첫 줄 번호 기준(레거시). 합성·GUI는 ``pick_image_for_srt_second`` 를 사용."""
    mid = int(map_id)
    leq = [n for n in image_index if n <= mid]
    if not leq:
        return None
    return image_index[max(leq)]


def try_srt_numbered_image(images_dir: Path, map_id: int) -> Path | None:
    """SRT 자막 번호 → 매칭 이미지 (번호 ≤ SRT 인 것 중 최대 번호)."""
    return pick_image_for_srt_id(index_srt_numbered_images(images_dir), map_id)


def per_cue_images_srt_mapping(
    image_map_ids: list[int],
    images_dir: Path,
    overrides: dict[int, Path | None],
    *,
    cue_start_ms: list[int] | None = None,
) -> list[Path | None]:
    """큐 재생 순서대로 각 구간에 쓸 이미지 경로.

    - 기본: ``images/SRT_NNN.*`` 의 NNN(초) ≤ 구간 ``start_ms`` 의 초 인 것 중 **가장 큰** 번호
      (예: 0초 → ``SRT_000``; 150초 → ``SRT_150``; ``SRT_449`` 가 있으면 449초부터 그 파일).
    - ``cue_start_ms`` 가 없으면 SRT 블록 첫 줄 번호(``image_map_ids``)로 매칭합니다.
    - 그런 이미지가 없으면 직전 구간과 같은 이미지를 유지합니다. 첫 구간부터 매치되는
      파일이 없으면 ``None`` (검은 화면)입니다.
    - ``compose_overrides.json`` 의 ``cue_images``: 블록 순번(1…) 또는 SRT 표시 번호 키 모두 허용.
    - 오버라이드가 ``null`` (검은 화면)이면 해당 구간만 검정이며, 다음 구간의 "이전 이미지" 캐리 값은 바꾸지 않습니다.
    """
    image_index = index_srt_numbered_images(images_dir)
    last: Path | None = None
    out: list[Path | None] = []
    for block_i, mid in enumerate(image_map_ids, start=1):
        ov = _override_for_block(overrides, block_i, mid)
        if ov is not _NO_OVERRIDE:
            if ov is None:
                out.append(None)
            else:
                out.append(ov)
                last = ov
            continue
        # SRT가 커지면 더 큰 번호의 키프레임 이미지로 갱신 (예: 147→120, 151→150).
        # 직전 이미지 유지는 pick 결과가 없을 때만 적용합니다.
        if cue_start_ms is not None and block_i - 1 < len(cue_start_ms):
            hit = pick_image_for_srt_second(image_index, cue_start_ms[block_i - 1])
        else:
            hit = pick_image_for_srt_id(image_index, mid)
        if hit is not None:
            out.append(hit)
            last = hit
        elif last is not None:
            out.append(last)
        else:
            out.append(None)
    return out


def _rel_or_abs(path: Path, assets_root: Path) -> str:
    """JSON 저장용: assets_root 아래면 상대 POSIX."""
    try:
        ar = assets_root.resolve()
        pr = path.resolve()
        rel = pr.relative_to(ar)
        return rel.as_posix()
    except ValueError:
        return path.resolve().as_posix()


def save_compose_overrides_json(
    path: Path,
    assets_root: Path,
    cue_images: dict[int, Path | None],
    inserts: list[InsertClipSpec],
    *,
    cue_effects: dict[int, str] | None = None,
    image_effects: dict[str, str] | None = None,
) -> None:
    """GUI 편집 결과를 JSON으로 저장(백업·공유용)."""
    root = assets_root.resolve()
    data: dict[str, Any] = {}
    if cue_images:
        data["cue_images"] = {
            str(k): (None if v is None else _rel_or_abs(v, root))
            for k, v in sorted(cue_images.items(), key=lambda x: x[0])
        }
    if cue_effects:
        data["cue_effects"] = {str(k): v for k, v in sorted(cue_effects.items(), key=lambda x: x[0])}
    if image_effects:
        img_out: dict[str, str] = {}
        for k, v in sorted(image_effects.items(), key=lambda x: x[0]):
            try:
                p = Path(k).resolve()
            except OSError:
                continue
            if not p.is_file():
                continue
            img_out[_rel_or_abs(p, root)] = str(v).strip()
        if img_out:
            data["image_effects"] = img_out
    if inserts:
        data["insert_after_cue"] = [
            {
                "after_cue_index": ins.after_cue_index,
                "duration_sec": ins.duration_sec,
                "image": _rel_or_abs(ins.image, root),
                "subtitle": ins.subtitle,
                "effect": ins.effect,
            }
            for ins in inserts
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
