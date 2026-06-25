"""이미지 배치 → 썸네일 생성 + 다중 텍스트 레이어·프리셋 저장/삭제."""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, font as tkfont, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_PRESET_VERSION = 1
_FONT_PRESET_DIRECT = "(파일에서 직접…)"  # 구 preset 호환용, UI 에는 미표시


def _wisdom_repo_root() -> Path:
    """저장소 루트 — IDE·탐색기에서 연 wisdom 폴더."""
    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (base / "wisdom_root.py").is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            break
    from wisdom_root import resolve_wisdom_root

    return resolve_wisdom_root()


def wisdom_fonts_dir() -> Path:
    """thumbnailPG: 다운로드 폰트는 ``wisdom/fonts``."""
    return _wisdom_repo_root() / "fonts"


def default_thumbnail_output_dir() -> Path:
    """thumbnailPG: 썸네일 저장 기본 폴더."""
    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (base / "wisdom_root.py").is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            break
    from wisdom_workspace import resolve_module_output

    return resolve_module_output("6_thumbnail")


def wisdom_font_combobox_values() -> tuple[str, ...]:
    """Selectbox에는 ``wisdom/fonts`` 에 실제로 있는 파일만 표시."""
    d = wisdom_fonts_dir()
    d.mkdir(parents=True, exist_ok=True)
    ex = {".ttf", ".otf", ".ttc"}
    names = sorted(
        (p.name for p in d.iterdir() if p.suffix.lower() in ex and p.is_file()),
        key=str.lower,
    )
    return tuple(names)


def resolve_wisdom_font_choice(title: str) -> str:
    """프리셋 제목(파일명) → 절대 경로. 없으면 빈 문자열."""
    if not title or title == _FONT_PRESET_DIRECT:
        return ""
    p = wisdom_fonts_dir() / title
    if p.is_file():
        return str(p.resolve())
    return ""


def combobox_title_for_font_path(fp: str) -> str:
    s = (fp or "").strip()
    vals = wisdom_font_combobox_values()
    if not s:
        return vals[0] if vals else ""
    try:
        want = Path(s).resolve()
    except OSError:
        return vals[0] if vals else ""
    cand = wisdom_fonts_dir() / want.name
    if not cand.is_file():
        return vals[0] if vals else ""
    try:
        if cand.resolve() == want:
            return want.name
    except OSError:
        pass
    return vals[0] if vals else ""


def install_font_file_windows(font_path: Path) -> None:
    """Windows '글꼴 설치' UI(ShellExecute install)."""
    if os.name != "nt":
        raise OSError("Windows에서만 지원합니다.")
    path = font_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
        raise ValueError("TTF / OTF / TTC만 설치할 수 있습니다.")
    SW_SHOWNORMAL = 1
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "install",
        str(path),
        None,
        None,
        SW_SHOWNORMAL,
    )
    if rc <= 32:
        raise OSError(f"폰트 설치 실행에 실패했습니다(코드 {rc}). 관리자 권한이 필요할 수 있습니다.")


def natural_sort_key(path: Path) -> list[str | int]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def default_source_image_path() -> str:
    """저장 폴더 안 첫 이미지 경로(없으면 빈 문자열)."""
    d = default_thumbnail_output_dir()
    if not d.is_dir():
        return ""
    files = sorted(
        [p for p in d.iterdir() if p.suffix.lower() in _IMAGE_EXT and p.is_file()],
        key=natural_sort_key,
    )
    return str(files[0].resolve()) if files else ""


def _load_font(size: int, font_path: str) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fp = (font_path or "").strip()
    if fp and Path(fp).is_file():
        try:
            return ImageFont.truetype(fp, size=size)
        except OSError:
            pass
    for name in ("malgun.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _anchor_point(anchor: str, tw: int, th: int, m: int) -> tuple[int, int]:
    a = anchor.lower()
    if a == "lt":
        return (m, m)
    if a == "mt":
        return (tw // 2, m)
    if a == "rt":
        return (tw - m, m)
    if a == "lm":
        return (m, th // 2)
    if a == "mm":
        return (tw // 2, th // 2)
    if a == "rm":
        return (tw - m, th // 2)
    if a == "lb":
        return (m, th - m)
    if a == "mb":
        return (tw // 2, th - m)
    if a == "rb":
        return (tw - m, th - m)
    # 가로 중앙 + 세로는 여백(m) 안쪽 구간을 4등분한 ¼·½·¾ 지점 (중상·중중·중하)
    if a in ("zs", "zz", "zh"):
        ih = max(1, th - 2 * m)
        x = tw // 2
        if a == "zs":
            return (x, m + ih // 4)
        if a == "zz":
            return (x, m + ih // 2)
        return (x, m + (3 * ih) // 4)
    return (tw // 2, th - m)


def _pillow_multiline_anchor(layer_anchor: str) -> str:
    """Pillow `multiline_text` anchor. 중상·중중·중하는 기준점이 글줄 박스 중심이 되도록 mm 사용."""
    a = (layer_anchor or "mb").lower()
    if a in ("zs", "zz", "zh"):
        return "mm"
    return a


def _paste_fit_cover(canvas: Image.Image, src: Image.Image) -> None:
    cw, ch = canvas.size
    sw, sh = src.size
    scale = max(cw / sw, ch / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    x0 = (cw - nw) // 2
    y0 = (ch - nh) // 2
    canvas.paste(resized, (x0, y0))


def _hex_rgb(h: str) -> tuple[int, int, int]:
    s = h.strip().lstrip("#")
    if len(s) == 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return 255, 255, 255


def default_text_layer() -> dict[str, str | int]:
    return {
        "text": "제목을 입력하세요",
        "font_path": "",
        "font_size": 56,
        "color": "#FFFFFF",
        "anchor": "mb",
        "margin": 32,
        "offset_x": 0,
        "offset_y": 0,
    }


def render_thumbnail_layers_image(
    src: Path,
    *,
    tw: int,
    th: int,
    layers: list[dict[str, str | int]],
) -> Image.Image:
    im = Image.open(src).convert("RGB")
    canvas = Image.new("RGB", (tw, th), (18, 18, 22))
    _paste_fit_cover(canvas, im)
    dr = ImageDraw.Draw(canvas)
    for layer in layers:
        text = str(layer.get("text") or "").strip()
        if not text:
            continue
        fp = str(layer.get("font_path") or "")
        try:
            fs = int(layer.get("font_size") or 56)
        except (TypeError, ValueError):
            fs = 56
        try:
            mg = int(layer.get("margin") or 32)
        except (TypeError, ValueError):
            mg = 32
        rgb = _hex_rgb(str(layer.get("color") or "#FFFFFF"))
        anchor = str(layer.get("anchor") or "mb")
        font = _load_font(fs, fp)
        xy = _anchor_point(anchor, tw, th, mg)
        try:
            ox = int(layer.get("offset_x", 0))
        except (TypeError, ValueError):
            ox = 0
        try:
            oy = int(layer.get("offset_y", 0))
        except (TypeError, ValueError):
            oy = 0
        xy = (xy[0] + ox, xy[1] + oy)
        dr.multiline_text(
            xy,
            text,
            font=font,
            fill=rgb,
            anchor=_pillow_multiline_anchor(anchor),
            align="center",
            spacing=4,
            stroke_width=max(2, fs // 24),
            stroke_fill=(0, 0, 0),
        )
    return canvas


def render_thumbnail_layers(
    src: Path,
    dst: Path,
    *,
    tw: int,
    th: int,
    layers: list[dict[str, str | int]],
) -> None:
    canvas = render_thumbnail_layers_image(src, tw=tw, th=th, layers=layers)
    dst.parent.mkdir(parents=True, exist_ok=True)
    suf = dst.suffix.lower()
    if suf == ".png":
        canvas.save(dst, format="PNG")
    else:
        canvas.save(dst, quality=92)


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import apply_window_chrome, run_mainloop, tk_host

    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title="썸네일 스튜디오 (6_thumbnail)",
        minsize=(560, 520),
        geometry="800x700",
    )

    wisdom_fonts_dir().mkdir(parents=True, exist_ok=True)

    try:
        f = tkfont.nametofont("TkDefaultFont")
        root.option_add("*Font", (f.actual("family"), max(10, int(f.actual("size")))))
    except tk.TclError:
        pass

    src_image = tk.StringVar(value=default_source_image_path())
    out_dir = tk.StringVar(value=str(default_thumbnail_output_dir()))
    tw_var = tk.StringVar(value="1280")
    th_var = tk.StringVar(value="720")
    _font_vals = wisdom_font_combobox_values()
    font_preset_var = tk.StringVar(value=_font_vals[0] if _font_vals else "")
    size_var = tk.StringVar(value="56")
    color_var = tk.StringVar(value="#FFFFFF")
    margin_var = tk.StringVar(value="32")
    anchor_var = tk.StringVar(value="mb")
    offset_info_var = tk.StringVar(value="미세 오프셋 X:0 Y:0")

    _init_font = resolve_wisdom_font_choice(_font_vals[0]) if _font_vals else ""
    layers: list[dict[str, str | int]] = [default_text_layer()]
    if _init_font:
        layers[0]["font_path"] = _init_font
    cur_layer_idx = tk.IntVar(value=0)
    resize_drag: dict[str, int | bool] = {"active": False, "x": 0, "y": 0, "tw": 0, "th": 0}
    text_drag: dict[str, int | bool] = {"active": False, "x": 0, "y": 0, "start_ox": 0, "start_oy": 0}
    preview_size: dict[str, int] = {"iw": 0, "ih": 0}

    anchors = [
        ("lt", "좌상"),
        ("mt", "상중"),
        ("zs", "중상"),
        ("rt", "우상"),
        ("lm", "좌중"),
        ("mm", "정중"),
        ("zz", "중중"),
        ("rm", "우중"),
        ("lb", "좌하"),
        ("mb", "하중"),
        ("zh", "중하"),
        ("rb", "우하"),
    ]

    preview_img_ref: dict[str, object] = {"ph": None}
    prev_wrap = ttk.Frame(root)
    prev_canvas = tk.Canvas(
        prev_wrap,
        width=640,
        height=380,
        bg="#222",
        highlightthickness=1,
        highlightbackground="#555",
    )
    pv_v = ttk.Scrollbar(prev_wrap, orient="vertical", command=prev_canvas.yview)
    pv_h = ttk.Scrollbar(prev_wrap, orient="horizontal", command=prev_canvas.xview)
    prev_canvas.configure(yscrollcommand=pv_v.set, xscrollcommand=pv_h.set)
    prev_canvas.grid(row=0, column=0, sticky="nsew")
    pv_v.grid(row=0, column=1, sticky="ns")
    pv_h.grid(row=1, column=0, sticky="ew")
    prev_wrap.grid_rowconfigure(0, weight=1)
    prev_wrap.grid_columnconfigure(0, weight=1)

    def _prev_canvas_wheel(e: tk.Event) -> None:
        if e.delta:
            prev_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    prev_canvas.bind("<MouseWheel>", _prev_canvas_wheel)

    def show_preview_empty() -> None:
        prev_canvas.delete("all")
        preview_img_ref["ph"] = None
        cw = int(prev_canvas.cget("width"))
        ch = int(prev_canvas.cget("height"))
        prev_canvas.create_text(
            cw // 2,
            ch // 2,
            text="(미리보기 없음)\n원본 이미지를 선택한 뒤 「미리보기」를 누르세요.",
            fill="#aaa",
            width=cw - 24,
            justify="center",
        )
        prev_canvas.configure(scrollregion=prev_canvas.bbox("all") or (0, 0, cw, ch))

    def pick_color() -> None:
        c = colorchooser.askcolor(color_var.get(), title="텍스트 색")
        if c and c[1]:
            color_var.set(c[1])

    def pick_src() -> None:
        from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

        init = Path(src_image.get().strip()).parent if src_image.get().strip() else default_thumbnail_output_dir()
        p = filedialog.askopenfilename(
            title="원본 이미지",
            initialdir=folder_dialog_initial(init),
            filetypes=[
                ("이미지", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("모든 파일", "*.*"),
            ],
        )
        if p:
            src_image.set(p)
            touch_workspace_from_path(p)

    def pick_out() -> None:
        from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

        init = Path(out_dir.get().strip()) if out_dir.get().strip() else default_thumbnail_output_dir()
        p = filedialog.askdirectory(
            title="썸네일 저장 폴더",
            initialdir=folder_dialog_initial(init),
        )
        if p:
            out_dir.set(p)
            touch_workspace_from_path(p)

    def sync_form_to_layer() -> None:
        i = cur_layer_idx.get()
        if not (0 <= i < len(layers)):
            return
        layers[i]["text"] = tx.get("1.0", "end").rstrip("\n")
        layers[i]["font_path"] = resolve_wisdom_font_choice(font_preset_var.get())
        try:
            layers[i]["font_size"] = int(size_var.get())
        except ValueError:
            layers[i]["font_size"] = 56
        layers[i]["color"] = color_var.get().strip() or "#FFFFFF"
        layers[i]["anchor"] = anchor_var.get()
        try:
            layers[i]["margin"] = int(margin_var.get())
        except ValueError:
            layers[i]["margin"] = 32
        if "offset_x" not in layers[i]:
            layers[i]["offset_x"] = 0
        if "offset_y" not in layers[i]:
            layers[i]["offset_y"] = 0

    def sync_layer_to_form() -> None:
        i = cur_layer_idx.get()
        if not (0 <= i < len(layers)):
            return
        L = layers[i]
        tx.delete("1.0", tk.END)
        tx.insert("1.0", str(L.get("text") or ""))
        font_preset_var.set(combobox_title_for_font_path(str(L.get("font_path") or "")))
        size_var.set(str(int(L.get("font_size") or 56)))
        color_var.set(str(L.get("color") or "#FFFFFF"))
        margin_var.set(str(int(L.get("margin") or 32)))
        anchor_var.set(str(L.get("anchor") or "mb"))
        try:
            ox = int(L.get("offset_x", 0))
        except (TypeError, ValueError):
            ox = 0
        try:
            oy = int(L.get("offset_y", 0))
        except (TypeError, ValueError):
            oy = 0
        offset_info_var.set(f"미세 오프셋 X:{ox} Y:{oy}")

    def refresh_layer_listbox() -> None:
        lb_layers.delete(0, tk.END)
        for j, L in enumerate(layers):
            t = str(L.get("text") or "").replace("\n", " ").strip()[:28]
            if not t:
                t = "(빈 텍스트)"
            lb_layers.insert(tk.END, f"{j + 1}. {t}")
        if 0 <= cur_layer_idx.get() < len(layers):
            lb_layers.selection_set(cur_layer_idx.get())
            lb_layers.see(cur_layer_idx.get())

    def on_layer_select(_e=None) -> None:
        sel = lb_layers.curselection()
        if not sel:
            return
        sync_form_to_layer()
        cur_layer_idx.set(int(sel[0]))
        sync_layer_to_form()

    def add_layer() -> None:
        sync_form_to_layer()
        layers.append(default_text_layer())
        cur_layer_idx.set(len(layers) - 1)
        sync_layer_to_form()
        refresh_layer_listbox()

    def delete_layer() -> None:
        if len(layers) <= 1:
            messagebox.showinfo("레이어 삭제", "텍스트 레이어는 최소 1개 필요합니다.")
            return
        i = cur_layer_idx.get()
        if not (0 <= i < len(layers)):
            return
        layers.pop(i)
        cur_layer_idx.set(min(i, len(layers) - 1))
        sync_layer_to_form()
        refresh_layer_listbox()

    def save_preset() -> None:
        sync_form_to_layer()
        p = filedialog.asksaveasfilename(
            title="설정 저장 (JSON)",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        data = {
            "version": _PRESET_VERSION,
            "src_image": src_image.get().strip(),
            "out_dir": out_dir.get().strip(),
            "tw": tw_var.get().strip(),
            "th": th_var.get().strip(),
            "layers": [dict(x) for x in layers],
        }
        try:
            Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("저장", f"저장했습니다.\n{p}")
        except OSError as e:
            messagebox.showerror("저장", str(e))

    def load_preset() -> None:
        p = filedialog.askopenfilename(
            title="설정 불러오기",
            filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")],
        )
        if not p or not Path(p).is_file():
            return
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("불러오기", str(e))
            return
        if not isinstance(data, dict):
            messagebox.showerror("불러오기", "형식이 올바르지 않습니다.")
            return
        loaded_src = str(data.get("src_image") or data.get("src_dir") or "").strip()
        if loaded_src and Path(loaded_src).is_dir():
            files = sorted(
                [p for p in Path(loaded_src).iterdir() if p.suffix.lower() in _IMAGE_EXT],
                key=natural_sort_key,
            )
            loaded_src = str(files[0]) if files else ""
        src_image.set(loaded_src)
        out_dir.set(str(data.get("out_dir") or ""))
        tw_var.set(str(data.get("tw") or "1280"))
        th_var.set(str(data.get("th") or "720"))
        raw_ls = data.get("layers")
        if isinstance(raw_ls, list) and raw_ls:
            new_layers: list[dict[str, str | int]] = []
            for item in raw_ls:
                if not isinstance(item, dict):
                    continue
                d = default_text_layer()
                d["text"] = str(item.get("text", d["text"]))
                d["font_path"] = str(item.get("font_path", ""))
                try:
                    d["font_size"] = int(item.get("font_size", 56))
                except (TypeError, ValueError):
                    d["font_size"] = 56
                d["color"] = str(item.get("color", "#FFFFFF"))
                d["anchor"] = str(item.get("anchor", "mb"))
                try:
                    d["margin"] = int(item.get("margin", 32))
                except (TypeError, ValueError):
                    d["margin"] = 32
                try:
                    d["offset_x"] = int(item.get("offset_x", 0))
                except (TypeError, ValueError):
                    d["offset_x"] = 0
                try:
                    d["offset_y"] = int(item.get("offset_y", 0))
                except (TypeError, ValueError):
                    d["offset_y"] = 0
                new_layers.append(d)
            if new_layers:
                layers.clear()
                layers.extend(new_layers)
        cur_layer_idx.set(0)
        sync_layer_to_form()
        refresh_layer_listbox()
        messagebox.showinfo("불러오기", f"불러왔습니다.\n{p}")

    def delete_preset_file() -> None:
        p = filedialog.askopenfilename(
            title="설정 파일 삭제",
            filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")],
        )
        if not p or not Path(p).is_file():
            return
        if not messagebox.askyesno("삭제", f"파일을 삭제할까요?\n{p}"):
            return
        try:
            Path(p).unlink()
            messagebox.showinfo("삭제", "삭제했습니다.")
        except OSError as e:
            messagebox.showerror("삭제", str(e))

    def _resolve_src_image() -> Path | None:
        p = Path(src_image.get().strip())
        if p.is_file() and p.suffix.lower() in _IMAGE_EXT:
            return p
        return None

    def _draw_resize_handle(iw: int, ih: int) -> None:
        hs = 12
        prev_canvas.create_rectangle(
            iw - hs,
            ih - hs,
            iw + hs,
            ih + hs,
            fill="#4af",
            outline="#fff",
            tags=("resize_handle",),
        )
        prev_canvas.create_text(
            iw,
            ih - 18,
            text="드래그로 가로·세로 조절",
            fill="#ccc",
            tags=("resize_handle",),
        )

    def _on_canvas_press(e: tk.Event) -> None:
        hit = prev_canvas.find_closest(e.x, e.y)
        if hit and "resize_handle" in prev_canvas.gettags(hit[0]):
            try:
                tw0, th0 = int(tw_var.get()), int(th_var.get())
            except ValueError:
                return
            resize_drag["active"] = True
            resize_drag["x"] = e.x
            resize_drag["y"] = e.y
            resize_drag["tw"] = tw0
            resize_drag["th"] = th0
            return
        if preview_img_ref["ph"] is None:
            return
        sync_form_to_layer()
        i = cur_layer_idx.get()
        if not (0 <= i < len(layers)):
            return
        L = layers[i]
        try:
            ox = int(L.get("offset_x", 0))
        except (TypeError, ValueError):
            ox = 0
        try:
            oy = int(L.get("offset_y", 0))
        except (TypeError, ValueError):
            oy = 0
        text_drag["active"] = True
        text_drag["x"] = e.x
        text_drag["y"] = e.y
        text_drag["start_ox"] = ox
        text_drag["start_oy"] = oy

    def _on_canvas_motion(e: tk.Event) -> None:
        if resize_drag["active"]:
            dx = e.x - int(resize_drag["x"])
            dy = e.y - int(resize_drag["y"])
            tw_var.set(str(max(64, int(resize_drag["tw"]) + dx)))
            th_var.set(str(max(64, int(resize_drag["th"]) + dy)))
            return
        if not text_drag["active"]:
            return
        dx = e.x - int(text_drag["x"])
        dy = e.y - int(text_drag["y"])
        i = cur_layer_idx.get()
        if not (0 <= i < len(layers)):
            return
        layers[i]["offset_x"] = int(text_drag["start_ox"]) + dx
        layers[i]["offset_y"] = int(text_drag["start_oy"]) + dy
        sync_layer_to_form()

    def _on_canvas_release(_e: tk.Event) -> None:
        if resize_drag["active"]:
            resize_drag["active"] = False
            if _resolve_src_image() is not None:
                do_preview()
            return
        if text_drag["active"]:
            text_drag["active"] = False
            if _resolve_src_image() is not None:
                do_preview()

    def do_preview() -> None:
        """화면 미리보기만 갱신 (파일 저장 없음 — videoPG)."""
        sync_form_to_layer()
        src = _resolve_src_image()
        if src is None:
            messagebox.showwarning("미리보기", "원본 이미지 파일을 선택하세요.")
            return
        try:
            tw, th = int(tw_var.get()), int(th_var.get())
        except ValueError:
            messagebox.showerror("미리보기", "가로·세로는 정수로 입력하세요.")
            return
        try:
            im = render_thumbnail_layers_image(src, tw=tw, th=th, layers=list(layers))
            ph = ImageTk.PhotoImage(im)
            prev_canvas.delete("all")
            iw, ih = ph.width(), ph.height()
            preview_size["iw"], preview_size["ih"] = iw, ih
            prev_canvas.create_image(0, 0, anchor="nw", image=ph, tags=("preview_img",))
            preview_img_ref["ph"] = ph
            _draw_resize_handle(iw, ih)
            prev_canvas.configure(scrollregion=(0, 0, max(iw + 16, 1), max(ih + 16, 1)))
        except Exception as e:
            messagebox.showerror("미리보기", str(e))

    def do_save() -> None:
        """저장 버튼으로만 최종 이미지 파일을 씁니다."""
        sync_form_to_layer()
        src = _resolve_src_image()
        if src is None:
            messagebox.showwarning("저장", "원본 이미지 파일을 선택하세요.")
            return
        od = Path(out_dir.get().strip())
        if not od.is_dir():
            try:
                od.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                messagebox.showerror("저장", f"저장 폴더를 만들 수 없습니다.\n{e}")
                return
        try:
            tw, th = int(tw_var.get()), int(th_var.get())
        except ValueError:
            messagebox.showerror("저장", "가로·세로는 정수로 입력하세요.")
            return
        dst = od / f"thumb_{src.stem}.jpg"
        try:
            render_thumbnail_layers(src, dst, tw=tw, th=th, layers=list(layers))
            messagebox.showinfo("저장", f"저장했습니다.\n{dst.resolve()}")
        except Exception as e:
            messagebox.showerror("저장", str(e))

    prev_canvas.bind("<ButtonPress-1>", _on_canvas_press)
    prev_canvas.bind("<B1-Motion>", _on_canvas_motion)
    prev_canvas.bind("<ButtonRelease-1>", _on_canvas_release)

    r = 0
    ttk.Label(root, text="원본 이미지").grid(row=r, column=0, sticky="w", padx=8, pady=(8, 2))
    ttk.Entry(root, textvariable=src_image, width=48).grid(row=r, column=1, sticky="ew", padx=(0, 6))
    ttk.Button(root, text="찾기…", command=pick_src).grid(row=r, column=2, padx=(0, 8))
    r += 1
    ttk.Label(root, text="저장 폴더").grid(row=r, column=0, sticky="w", padx=8, pady=2)
    ttk.Entry(root, textvariable=out_dir, width=48).grid(row=r, column=1, sticky="ew", padx=(0, 6))
    ttk.Button(root, text="찾기…", command=pick_out).grid(row=r, column=2, padx=(0, 8))
    r += 1
    sz = ttk.Frame(root)
    sz.grid(row=r, column=0, columnspan=3, sticky="w", padx=8, pady=6)
    ttk.Label(sz, text="썸네일 가로").pack(side=tk.LEFT)
    ttk.Entry(sz, textvariable=tw_var, width=6).pack(side=tk.LEFT, padx=(4, 12))
    ttk.Label(sz, text="세로").pack(side=tk.LEFT)
    ttk.Entry(sz, textvariable=th_var, width=6).pack(side=tk.LEFT, padx=(4, 16))
    ttk.Button(sz, text="설정 저장", command=save_preset).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(sz, text="설정 불러오기", command=load_preset).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(sz, text="설정 삭제", command=delete_preset_file).pack(side=tk.LEFT)
    r += 1

    lf = ttk.LabelFrame(root, text="텍스트 레이어 (위에서부터 순서대로 그림)")
    lf.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
    lf.grid_columnconfigure(0, weight=1)
    lb_layers = tk.Listbox(lf, height=4, exportselection=False)
    lb_layers.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
    lbtn = ttk.Frame(lf)
    lbtn.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=4)
    ttk.Button(lbtn, text="레이어 추가", command=add_layer).pack(fill=tk.X, pady=(0, 4))
    ttk.Button(lbtn, text="레이어 삭제", command=delete_layer).pack(fill=tk.X)
    r += 1

    ttk.Label(root, text="선택 레이어 편집 (여러 줄 가능)").grid(row=r, column=0, sticky="nw", padx=8, pady=4)
    tx = tk.Text(root, width=48, height=4, wrap=tk.WORD)
    tx.grid(row=r, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=4)
    tx.insert("1.0", str(layers[0].get("text") or ""))

    def _sync_text_out2(_e=None) -> None:
        sync_form_to_layer()

    tx.bind("<KeyRelease>", _sync_text_out2)
    tx.bind("<FocusOut>", _sync_text_out2)
    r += 1

    ff = ttk.Frame(root)
    ff.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
    ff.grid_columnconfigure(1, weight=1)
    ttk.Label(ff, text=f"폰트 ({wisdom_fonts_dir()})").grid(row=0, column=0, sticky="w")

    def refresh_font_combobox() -> None:
        vals = list(wisdom_font_combobox_values())
        cb_font["values"] = vals
        cur = font_preset_var.get()
        if vals and cur not in vals:
            font_preset_var.set(vals[0])

    cb_font = ttk.Combobox(
        ff,
        textvariable=font_preset_var,
        values=list(wisdom_font_combobox_values()),
        state="readonly",
        width=40,
    )
    cb_font.grid(row=0, column=1, sticky="ew", padx=6)

    def on_font_preset(_e: object | None = None) -> None:
        title = font_preset_var.get()
        resolved = resolve_wisdom_font_choice(title)
        if resolved == "":
            b = wisdom_fonts_dir()
            messagebox.showwarning(
                "폰트",
                f"다음 파일을 찾지 못했습니다.\n{title}\n\n"
                f"폰트를 받아 넣은 뒤 다시 선택하세요:\n{b}\n\n"
                "「폰트 설치…」로 Windows에 설치할 수 있습니다.",
            )
            vals = wisdom_font_combobox_values()
            if vals:
                font_preset_var.set(vals[0])
            return
        sync_form_to_layer()

    cb_font.bind("<<ComboboxSelected>>", on_font_preset)

    btnf = ttk.Frame(ff)
    btnf.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def do_install_font() -> None:
        b = wisdom_fonts_dir()
        b.mkdir(parents=True, exist_ok=True)
        p = filedialog.askopenfilename(
            title="Windows에 설치할 폰트 파일 (보통 아래 fonts 폴더)",
            initialdir=str(b),
            filetypes=[("Font", "*.ttf *.otf *.ttc"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        try:
            install_font_file_windows(Path(p))
            messagebox.showinfo("폰트 설치", "Windows 글꼴 설치 창이 열렸습니다. 안내에 따라 완료하세요.")
        except (OSError, ValueError, FileNotFoundError) as e:
            messagebox.showerror("폰트 설치", str(e))

    def do_open_fonts_dir() -> None:
        b = wisdom_fonts_dir()
        b.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(b)
            else:
                messagebox.showinfo("fonts 폴더", str(b))
            refresh_font_combobox()
        except OSError as e:
            messagebox.showerror("fonts 폴더", str(e))

    ttk.Button(btnf, text="폰트 설치…", command=do_install_font).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btnf, text="fonts 폴더 열기", command=do_open_fonts_dir).pack(side=tk.LEFT)
    r += 1

    opt = ttk.Frame(root)
    opt.grid(row=r, column=0, columnspan=3, sticky="w", padx=8, pady=4)
    ttk.Label(opt, text="글자 크기").pack(side=tk.LEFT)
    ttk.Entry(opt, textvariable=size_var, width=6).pack(side=tk.LEFT, padx=(4, 16))
    ttk.Label(opt, text="색").pack(side=tk.LEFT)
    ttk.Entry(opt, textvariable=color_var, width=10).pack(side=tk.LEFT, padx=(4, 6))
    ttk.Button(opt, text="색 선택…", command=pick_color).pack(side=tk.LEFT, padx=(0, 16))
    ttk.Label(opt, text="가장자리 여백(px)").pack(side=tk.LEFT)
    ttk.Entry(opt, textvariable=margin_var, width=6).pack(side=tk.LEFT, padx=(4, 0))
    r += 1

    ttk.Label(root, text="텍스트 위치 (앵커)").grid(row=r, column=0, sticky="nw", padx=8, pady=4)
    posf = ttk.Frame(root)
    posf.grid(row=r, column=1, columnspan=2, sticky="w", padx=(0, 8), pady=4)
    def on_anchor_change(*_args: object) -> None:
        sync_form_to_layer()

    anchor_var.trace_add("write", on_anchor_change)
    for aid, alab in anchors:
        ttk.Radiobutton(posf, text=alab, value=aid, variable=anchor_var).pack(side=tk.LEFT, padx=2)
    r += 1

    def nudge_offset(dx: int, dy: int) -> None:
        sync_form_to_layer()
        i = cur_layer_idx.get()
        if not (0 <= i < len(layers)):
            return
        L = layers[i]
        try:
            ox = int(L.get("offset_x", 0))
        except (TypeError, ValueError):
            ox = 0
        try:
            oy = int(L.get("offset_y", 0))
        except (TypeError, ValueError):
            oy = 0
        L["offset_x"] = ox + dx
        L["offset_y"] = oy + dy
        sync_layer_to_form()

    micro = ttk.LabelFrame(root, text="텍스트 미세 위치 (앵커 기준 10px)")
    micro.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
    ttk.Label(micro, textvariable=offset_info_var).pack(side=tk.LEFT, padx=(6, 12))
    ttk.Button(micro, text="상", width=4, command=lambda: nudge_offset(0, -10)).pack(side=tk.LEFT, padx=2)
    ttk.Button(micro, text="하", width=4, command=lambda: nudge_offset(0, 10)).pack(side=tk.LEFT, padx=2)
    ttk.Button(micro, text="좌", width=4, command=lambda: nudge_offset(-10, 0)).pack(side=tk.LEFT, padx=2)
    ttk.Button(micro, text="우", width=4, command=lambda: nudge_offset(10, 0)).pack(side=tk.LEFT, padx=2)
    r += 1

    ttk.Label(root, text="미리보기 (저장 안 함)").grid(row=r, column=0, sticky="nw", padx=8, pady=6)
    prev_wrap.grid(row=r, column=1, columnspan=2, sticky="nsew", padx=(0, 8), pady=6)
    root.grid_rowconfigure(r, weight=1)
    r += 1

    btns = ttk.Frame(root)
    btns.grid(row=r, column=0, columnspan=3, sticky="w", padx=8, pady=8)
    ttk.Button(btns, text="미리보기", command=do_preview).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btns, text="저장 (최종 저장)", command=do_save).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Label(
        btns,
        text="미리보기: 텍스트 드래그 → 위치 이동 · 우하 핸들 → 가로·세로 조절",
    ).pack(side=tk.LEFT, padx=(8, 0))
    r += 1

    lb_layers.bind("<<ListboxSelect>>", on_layer_select)
    refresh_layer_listbox()
    refresh_font_combobox()
    default_thumbnail_output_dir().mkdir(parents=True, exist_ok=True)
    show_preview_empty()

    root.grid_columnconfigure(1, weight=1)
    run_mainloop(root, standalone)
