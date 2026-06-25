"""명령줄 진입점."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prompt2image import __version__
from prompt2image.backends.openai_image import OpenAIImageBackend
from prompt2image.backends.pollinations import PollinationsBackend
from prompt2image.generator import generate_scenes
from prompt2image.prompt_parser import Scene, parse_markdown_file


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _win_utf8_stdio() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def _pause() -> None:
    if not _frozen():
        return
    try:
        input("\nEnter 키를 누르면 종료합니다...")
    except (EOFError, KeyboardInterrupt):
        pass


def _print_double_click_help() -> None:
    print(
        "prompt2image — 이미지 프롬프트 마크다운을 그림으로 변환합니다.\n\n"
        "이 프로그램은 명령줄 도구입니다. 더블클릭만으로는 동작이 끝나지 않습니다.\n"
        "그래픽 화면이 필요하면 같은 폴더의 2_2_srtToImage_gui.exe 를 실행하세요.\n"
        "  (또는: prompt2image.exe --gui)\n\n"
        "예시:\n"
        r'  prompt2image.exe -i "C:\경로\로스차일드_이미지프롬프트.md" -o "C:\경로\out" --scenes 1,17,32' "\n\n"
        "자세한 옵션: prompt2image.exe --help\n",
        flush=True,
    )


def _select_scenes(scenes: list[Scene], spec: str) -> list[Scene]:
    if not spec.strip():
        return list(scenes)
    wanted: set[str] = set()
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, b = tok.split("-", 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
            for n in range(min(lo, hi), max(lo, hi) + 1):
                wanted.add(f"{n:02d}")
                wanted.add(str(n))
        else:
            try:
                n = int(tok)
                wanted.add(f"{n:02d}")
                wanted.add(str(n))
            except ValueError:
                wanted.add(tok)
    return [s for s in scenes if s.number in wanted or s.number.lstrip("0") in wanted]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prompt2image",
        description="이미지 프롬프트 마크다운(.md)을 그림 파일로 변환합니다.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--gui",
        action="store_true",
        help="파일 선택 창이 있는 그래픽 화면을 엽니다.",
    )
    p.add_argument("-i", "--input", type=Path, help="이미지 프롬프트 마크다운(.md)")
    p.add_argument("-o", "--output", type=Path, help="저장할 폴더 경로")
    p.add_argument(
        "--scenes",
        default="",
        help="장면 번호 선택. 예: '1,17,32' 또는 '1-5,10' (비우면 전체)",
    )
    p.add_argument(
        "--backend",
        choices=("pollinations", "openai"),
        default="pollinations",
        help="이미지 백엔드 (기본: pollinations, 키 불필요)",
    )
    p.add_argument(
        "--model",
        default="",
        help="모델 이름. pollinations: flux/turbo 등, openai: gpt-image-1 등",
    )
    p.add_argument("--width", type=int, default=1024, help="가로 픽셀(pollinations)")
    p.add_argument("--height", type=int, default=1024, help="세로 픽셀(pollinations)")
    p.add_argument("--size", default="1024x1024", help="OpenAI size 문자열")
    p.add_argument("--quality", default="high", help="OpenAI quality")
    p.add_argument("--seed", type=int, default=None, help="pollinations seed")
    p.add_argument(
        "--list-scenes",
        action="store_true",
        help="마크다운에서 장면 목록만 출력하고 종료합니다.",
    )
    return p


def _make_backend(args: argparse.Namespace):
    if args.backend == "openai":
        model = args.model or "gpt-image-1"
        return OpenAIImageBackend(model=model, size=args.size, quality=args.quality)
    model = args.model or "flux"
    return PollinationsBackend(
        model=model,
        width=args.width,
        height=args.height,
        seed=args.seed,
    )


def _cmd_list_scenes(md: Path) -> int:
    scenes = parse_markdown_file(md)
    if not scenes:
        print("장면을 찾을 수 없습니다. 마크다운 형식을 확인하세요.", file=sys.stderr)
        return 1
    for s in scenes:
        head = f"[{s.number}] {s.title}"
        if s.summary:
            head += f"  — {s.summary}"
        print(head)
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    if args.input is None or args.output is None:
        print("-i/--input 과 -o/--output 이 필요합니다.", file=sys.stderr)
        return 2
    if not args.input.is_file():
        print(f"입력 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 1

    scenes_all = parse_markdown_file(args.input)
    if not scenes_all:
        print("장면을 찾을 수 없습니다.", file=sys.stderr)
        return 1
    scenes = _select_scenes(scenes_all, args.scenes)
    if not scenes:
        print("선택된 장면이 없습니다. --scenes 표현을 확인하세요.", file=sys.stderr)
        return 1

    backend = _make_backend(args)

    def report(i: int, total: int, scene, path, err) -> None:
        pct = int(100 * i / total) if total else 0
        if err:
            print(f"[{pct:>3}%] [{scene.number}] 실패: {err}")
        else:
            print(f"[{pct:>3}%] [{scene.number}] 저장: {path}")

    saved = generate_scenes(scenes, backend, args.output, on_progress=report)
    print(f"\n완료: {len(saved)} / {len(scenes)} 장면 저장됨 → {args.output.resolve()}")
    return 0 if saved else 1


def main(argv: list[str] | None = None) -> int:
    _win_utf8_stdio()
    eff: list[str] = list(argv) if argv is not None else sys.argv[1:]
    if _frozen() and len(eff) == 0:
        _print_double_click_help()
        _pause()
        return 0

    parser = _build_parser()
    args = parser.parse_args(eff)

    if args.gui:
        from prompt2image.gui_app import main as gui_main

        gui_main()
        return 0

    if args.list_scenes:
        if args.input is None:
            print("--list-scenes 에는 -i/--input 이 필요합니다.", file=sys.stderr)
            return 2
        return _cmd_list_scenes(args.input)

    code = _cmd_generate(args)
    if _frozen() and code not in (0, None):
        _pause()
    return int(code) if code is not None else 0
