"""Utube 인기·고조회 영상 조회 GUI."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from utube.api import (
    YouTubeApiError,
    fetch_keyword_search,
    fetch_popular_keywords,
    fetch_top_by_views,
    fetch_trending,
)
from utube.categories import (
    DEFAULT_EXCLUDED_CATEGORY_IDS,
    SELECTABLE_CATEGORIES,
    category_label,
)
from utube.config import load_api_key, module_root, persist_api_key_if_changed, save_api_key
from utube.export_util import export_videos_excel
from utube.format_util import duration_display_to_seconds, format_count, format_published
from utube.models import KeywordItem, VideoItem
from utube.thumb_util import load_thumbnail_photo
from utube.translate_util import is_mostly_korean, translate_to_korean

_REGIONS = ("KR", "US", "JP", "GB", "DE", "FR", "IN", "BR")
_MODES = ("인기 급상승", "키워드 검색", "조회수 TOP 검색", "인기 키워드")
_DAYS = ("7", "30", "90", "180", "365")

_COLS = ("rank", "views", "likes", "date", "duration", "shorts", "region", "channel", "category", "title", "title_ko")
_COL_LABELS = {
    "rank": "#",
    "views": "조회수",
    "likes": "좋아요",
    "date": "업로드",
    "duration": "길이",
    "shorts": "쇼츠",
    "region": "지역",
    "channel": "채널",
    "category": "카테고리",
    "title": "제목",
    "title_ko": "번역",
}
_DEFAULT_DESC_COLS = frozenset({"views", "likes", "date", "duration"})

_KW_COLS = ("rank", "keyword", "score", "source")
_KW_COL_LABELS = {
    "rank": "#",
    "keyword": "키워드",
    "score": "점수",
    "source": "출처",
}


def _sort_key(col: str, v: VideoItem, index: int, *, title_ko: dict[str, str]) -> object:
    if col == "rank":
        return index
    if col == "views":
        return v.view_count
    if col == "likes":
        return v.like_count if v.like_count is not None else -1
    if col == "date":
        return v.published_at or ""
    if col == "duration":
        return duration_display_to_seconds(v.duration)
    if col == "shorts":
        return (0 if v.is_shorts else 1, v.shorts_display.casefold())
    if col == "region":
        return v.region_code.casefold()
    if col == "channel":
        return v.channel.casefold()
    if col == "category":
        return category_label(v.category_id).casefold()
    if col == "title":
        return v.title.casefold()
    if col == "title_ko":
        if is_mostly_korean(v.title):
            return ""
        return title_ko.get(v.video_id, "").casefold()
    return index


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import bind_close, apply_window_chrome, run_mainloop, tk_host

    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title="7_utube — Utube 인기·고조회 영상",
        minsize=(960, 520),
        geometry="1100x640",
    )

    rows_state: list[VideoItem] = []
    keyword_rows_state: list[KeywordItem] = []
    title_translations: dict[str, str] = {}
    table_kind: str = "videos"
    sort_col: str = "views"
    sort_reverse: bool = True
    kw_sort_col: str = "score"
    kw_sort_reverse: bool = True

    frm = ttk.Frame(root, padding=8)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.columnconfigure(0, weight=1)
    frm.rowconfigure(3, weight=1)

    # API 키
    key_fr = ttk.LabelFrame(frm, text="YouTube Data API v3 키", padding=6)
    key_fr.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    key_fr.columnconfigure(1, weight=1)
    ttk.Label(key_fr, text="API 키").grid(row=0, column=0, sticky="w", padx=(0, 6))
    api_var = tk.StringVar(value=load_api_key())
    api_ent = ttk.Entry(key_fr, textvariable=api_var, show="*")
    api_ent.grid(row=0, column=1, sticky="ew")
    show_key = tk.BooleanVar(value=False)

    def toggle_show() -> None:
        api_ent.configure(show="" if show_key.get() else "*")

    ttk.Checkbutton(key_fr, text="표시", variable=show_key, command=toggle_show).grid(row=0, column=2, padx=4)
    ttk.Label(
        key_fr,
        text="키는 config/youtube_api.json에 저장·자동 로드 (조회 성공 시 자동 저장). exe는 dist/config/",
        font=("", 8),
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def save_key() -> None:
        k = api_var.get().strip()
        if not k:
            messagebox.showwarning("API 키", "키를 입력하세요.")
            return
        save_api_key(k)
        messagebox.showinfo("API 키", "저장했습니다.")

    ttk.Button(key_fr, text="키 저장", command=save_key).grid(row=0, column=3, padx=(6, 0))

    # 조회 옵션
    opt_fr = ttk.LabelFrame(frm, text="조회 조건", padding=6)
    opt_fr.grid(row=1, column=0, sticky="ew", pady=(0, 6))
    mode_var = tk.StringVar(value=_MODES[2])
    days_var = tk.StringVar(value="30")
    max_var = tk.StringVar(value="50")
    query_var = tk.StringVar(value="")
    exclude_shorts_var = tk.BooleanVar(value=False)
    hide_thumb_var = tk.BooleanVar(value=False)
    excluded_category_ids: set[str] = set(DEFAULT_EXCLUDED_CATEGORY_IDS)
    selected_region_codes: set[str] = {"KR"}
    thumb_photos: dict[str, tk.PhotoImage] = {}

    ttk.Label(opt_fr, text="모드").grid(row=0, column=0, sticky="w")
    mode_cb = ttk.Combobox(opt_fr, textvariable=mode_var, values=_MODES, state="readonly", width=16)
    mode_cb.grid(row=0, column=1, sticky="w", padx=(4, 12))

    ttk.Label(opt_fr, text="지역").grid(row=0, column=2, sticky="w")

    def region_button_text() -> str:
        if not selected_region_codes:
            return "지역 (KR)"
        codes = sorted(selected_region_codes)
        if len(codes) <= 3:
            return "지역: " + ", ".join(codes)
        return f"지역 ({len(codes)}개)"

    def open_region_picker() -> None:
        dlg = tk.Toplevel(root)
        dlg.title("지역 선택")
        dlg.transient(root)
        dlg.grab_set()
        dlg.resizable(False, False)

        body = ttk.Frame(dlg, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="조회할 지역을 선택하세요. (복수 선택 가능)").pack(anchor="w", pady=(0, 6))

        checks_fr = ttk.Frame(body)
        checks_fr.pack(anchor="w")
        check_vars: dict[str, tk.BooleanVar] = {}
        for code in _REGIONS:
            var = tk.BooleanVar(value=code in selected_region_codes)
            check_vars[code] = var
            ttk.Checkbutton(checks_fr, text=code, variable=var).pack(anchor="w")

        btn_fr = ttk.Frame(body)
        btn_fr.pack(fill=tk.X, pady=(10, 0))

        def apply_selection() -> None:
            selected_region_codes.clear()
            selected_region_codes.update(code for code, var in check_vars.items() if var.get())
            if not selected_region_codes:
                selected_region_codes.add("KR")
            region_btn.configure(text=region_button_text())
            dlg.destroy()

        def select_all() -> None:
            for var in check_vars.values():
                var.set(True)

        ttk.Button(btn_fr, text="전체", command=select_all).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_fr, text="확인", command=apply_selection).pack(side=tk.LEFT)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    region_btn = ttk.Button(opt_fr, text=region_button_text(), command=open_region_picker, width=14)
    region_btn.grid(row=0, column=3, sticky="w", padx=(4, 12))

    ttk.Label(opt_fr, text="제외").grid(row=0, column=4, sticky="w")

    def category_button_text() -> str:
        if not excluded_category_ids:
            return "카테고리 제외 없음"
        names = [n for n, cid in SELECTABLE_CATEGORIES if cid in excluded_category_ids]
        if len(names) <= 2:
            return "제외: " + ", ".join(names)
        return f"제외 ({len(excluded_category_ids)}개)"

    def open_category_picker() -> None:
        dlg = tk.Toplevel(root)
        dlg.title("카테고리 제외")
        dlg.transient(root)
        dlg.grab_set()
        dlg.resizable(False, False)

        body = ttk.Frame(dlg, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="체크한 카테고리는 결과에서 제외됩니다.").pack(anchor="w", pady=(0, 6))

        checks_fr = ttk.Frame(body)
        checks_fr.pack(anchor="w")
        check_vars: dict[str, tk.BooleanVar] = {}
        for name, cid in SELECTABLE_CATEGORIES:
            var = tk.BooleanVar(value=cid in excluded_category_ids)
            check_vars[cid] = var
            ttk.Checkbutton(checks_fr, text=name, variable=var).pack(anchor="w")

        btn_fr = ttk.Frame(body)
        btn_fr.pack(fill=tk.X, pady=(10, 0))

        def apply_selection() -> None:
            excluded_category_ids.clear()
            excluded_category_ids.update(cid for cid, var in check_vars.items() if var.get())
            cat_btn.configure(text=category_button_text())
            dlg.destroy()

        def reset_default() -> None:
            for cid, var in check_vars.items():
                var.set(cid in DEFAULT_EXCLUDED_CATEGORY_IDS)

        ttk.Button(btn_fr, text="기본(음악·게임)", command=reset_default).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_fr, text="제외 없음", command=lambda: [v.set(False) for v in check_vars.values()]).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btn_fr, text="확인", command=apply_selection).pack(side=tk.LEFT)

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    cat_btn = ttk.Button(opt_fr, text=category_button_text(), command=open_category_picker, width=18)
    cat_btn.grid(row=0, column=5, sticky="w", padx=(4, 12))

    ttk.Checkbutton(opt_fr, text="쇼츠 제외", variable=exclude_shorts_var).grid(
        row=0, column=6, sticky="w", padx=(0, 4)
    )

    def update_thumb_visibility() -> None:
        if table_kind != "videos" or hide_thumb_var.get():
            thumb_fr.grid_remove()
            thumb_lbl.configure(image="", text="행을 선택하세요")
            set_description_text("")
        else:
            thumb_fr.grid(row=0, column=2, sticky="ns", padx=(6, 0))
            sel = tree.selection()
            if sel and rows_state:
                show_thumbnail_for_index(int(sel[0]))

    ttk.Checkbutton(opt_fr, text="썸네일 감추기", variable=hide_thumb_var, command=update_thumb_visibility).grid(
        row=0, column=7, sticky="w", padx=(0, 4)
    )

    ttk.Label(opt_fr, text="검색어").grid(row=1, column=0, sticky="w", pady=(6, 0))
    query_ent = ttk.Entry(opt_fr, textvariable=query_var, width=28)
    query_ent.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(4, 12), pady=(6, 0))
    ttk.Label(
        opt_fr,
        text="(비우면 전체)",
        font=("", 8),
    ).grid(row=1, column=3, sticky="w", padx=(0, 4), pady=(6, 0))

    ttk.Label(opt_fr, text="기간(일)").grid(row=1, column=2, sticky="w", pady=(6, 0))
    days_cb = ttk.Combobox(opt_fr, textvariable=days_var, values=_DAYS, state="readonly", width=6)
    days_cb.grid(row=1, column=3, sticky="w", padx=(4, 12), pady=(6, 0))

    ttk.Label(opt_fr, text="개수").grid(row=1, column=4, sticky="w", pady=(6, 0))
    ttk.Combobox(
        opt_fr,
        textvariable=max_var,
        values=("10", "25", "50", "100", "150", "200", "300", "500"),
        state="readonly",
        width=6,
    ).grid(
        row=1, column=5, sticky="w", padx=(4, 12), pady=(6, 0)
    )

    def on_mode_change(_e=None) -> None:
        mode = mode_var.get()
        is_search = mode in (_MODES[1], _MODES[2])
        is_keywords = mode == _MODES[3]
        query_ent.configure(state="normal" if is_search else "disabled")
        days_cb.configure(state="readonly" if is_search else "disabled")
        rows_state.clear()
        keyword_rows_state.clear()
        configure_table(mode)
        if is_keywords:
            status_var.set("인기 키워드: 조회 후 더블클릭하면 해당 키워드로 영상 검색.")
        elif is_search:
            status_var.set("키워드·조회수 TOP: 검색어 비우면 기간·지역 전체 검색. Enter로 조회.")
        else:
            status_var.set("인기 급상승: 지역·카테고리 기준 조회.")

    mode_cb.bind("<<ComboboxSelected>>", on_mode_change)
    query_ent.bind("<Return>", lambda _e: do_fetch())

    status_var = tk.StringVar(
        value="조회수 TOP: 검색어 비우면 기간·지역 전체 검색. Enter로 조회."
    )
    ttk.Label(frm, textvariable=status_var).grid(row=2, column=0, sticky="w", pady=(0, 4))

    # 테이블 + 썸네일
    table_fr = ttk.Frame(frm)
    table_fr.grid(row=3, column=0, sticky="nsew")
    table_fr.columnconfigure(0, weight=1)
    table_fr.rowconfigure(0, weight=1)

    tree = ttk.Treeview(table_fr, columns=_COLS, show="headings", height=16, selectmode="browse")
    tree.column("rank", width=40, anchor="center", stretch=False)
    tree.column("views", width=72, anchor="e", stretch=False)
    tree.column("likes", width=72, anchor="e", stretch=False)
    tree.column("date", width=88, anchor="center", stretch=False)
    tree.column("duration", width=56, anchor="center", stretch=False)
    tree.column("shorts", width=48, anchor="center", stretch=False)
    tree.column("region", width=40, anchor="center", stretch=False)
    tree.column("channel", width=120, anchor="w", stretch=False)
    tree.column("category", width=88, anchor="center", stretch=False)
    tree.column("title", width=220, anchor="w", stretch=True)
    tree.column("title_ko", width=220, anchor="w", stretch=True)
    ysb = ttk.Scrollbar(table_fr, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ysb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ysb.grid(row=0, column=1, sticky="ns")

    thumb_fr = ttk.LabelFrame(table_fr, text="썸네일·설명", padding=4, width=220)
    thumb_fr.grid(row=0, column=2, sticky="ns", padx=(6, 0))
    thumb_fr.grid_propagate(False)
    thumb_lbl = ttk.Label(thumb_fr, text="행을 선택하세요", anchor="center", wraplength=200)
    thumb_lbl.pack(side=tk.TOP)

    desc_lf = ttk.LabelFrame(thumb_fr, text="설명", padding=2)
    desc_lf.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
    desc_sb = ttk.Scrollbar(desc_lf, orient="vertical")
    desc_txt = tk.Text(
        desc_lf,
        height=10,
        width=24,
        wrap=tk.WORD,
        font=("", 8),
        state=tk.DISABLED,
        yscrollcommand=desc_sb.set,
    )
    desc_sb.configure(command=desc_txt.yview)
    desc_sb.pack(side=tk.RIGHT, fill=tk.Y)
    desc_txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def set_description_text(text: str) -> None:
        desc_txt.configure(state=tk.NORMAL)
        desc_txt.delete("1.0", tk.END)
        desc_txt.insert("1.0", text.strip() if text.strip() else "(설명 없음)")
        desc_txt.configure(state=tk.DISABLED)
        desc_txt.yview_moveto(0)

    def configure_table(mode: str) -> None:
        nonlocal table_kind, sort_col, sort_reverse, kw_sort_col, kw_sort_reverse
        if mode == _MODES[3]:
            table_kind = "keywords"
            thumb_fr.grid_remove()
            tree.configure(columns=_KW_COLS)
            tree.column("rank", width=40, anchor="center", stretch=False)
            tree.column("keyword", width=420, anchor="w", stretch=True)
            tree.column("score", width=72, anchor="e", stretch=False)
            tree.column("source", width=120, anchor="center", stretch=False)
            kw_sort_col = "score"
            kw_sort_reverse = True
        else:
            table_kind = "videos"
            update_thumb_visibility()
            tree.configure(columns=_COLS)
            tree.column("rank", width=40, anchor="center", stretch=False)
            tree.column("views", width=72, anchor="e", stretch=False)
            tree.column("likes", width=72, anchor="e", stretch=False)
            tree.column("date", width=88, anchor="center", stretch=False)
            tree.column("duration", width=56, anchor="center", stretch=False)
            tree.column("shorts", width=48, anchor="center", stretch=False)
            tree.column("region", width=40, anchor="center", stretch=False)
            tree.column("channel", width=120, anchor="w", stretch=False)
            tree.column("category", width=88, anchor="center", stretch=False)
            tree.column("title", width=200, anchor="w", stretch=True)
            tree.column("title_ko", width=200, anchor="w", stretch=True)
            sort_col = "views"
            sort_reverse = True
        tree.delete(*tree.get_children())
        update_headings()

    def update_headings() -> None:
        if table_kind == "keywords":
            for col in _KW_COLS:
                label = _KW_COL_LABELS[col]
                if col == kw_sort_col:
                    label += " ▼" if kw_sort_reverse else " ▲"
                tree.heading(col, text=label, command=lambda c=col: on_sort_column(c))
            return
        for col in _COLS:
            label = _COL_LABELS[col]
            if col == sort_col:
                label += " ▼" if sort_reverse else " ▲"
            tree.heading(col, text=label, command=lambda c=col: on_sort_column(c))

    def apply_sort() -> None:
        indexed = list(enumerate(rows_state))
        indexed.sort(
            key=lambda pair: _sort_key(sort_col, pair[1], pair[0], title_ko=title_translations),
            reverse=sort_reverse,
        )
        rows_state[:] = [v for _, v in indexed]

    def _display_title_ko(v: VideoItem) -> str:
        if is_mostly_korean(v.title):
            return ""
        cached = title_translations.get(v.video_id)
        if cached is not None:
            return cached[:100]
        return "…"

    def refresh_table() -> None:
        sel_id = tree.selection()[0] if tree.selection() else None
        tree.delete(*tree.get_children())
        if table_kind == "keywords":
            for i, item in enumerate(keyword_rows_state):
                tree.insert(
                    "",
                    tk.END,
                    iid=str(i),
                    values=(i + 1, item.keyword[:120], item.score, item.source),
                )
        else:
            for i, v in enumerate(rows_state):
                tree.insert(
                    "",
                    tk.END,
                    iid=str(i),
                    values=(
                        i + 1,
                        format_count(v.view_count),
                        format_count(v.like_count),
                        format_published(v.published_at),
                        v.duration,
                        v.shorts_display,
                        v.region_code or "—",
                        v.channel[:36],
                        category_label(v.category_id)[:16],
                        v.title[:100],
                        _display_title_ko(v),
                    ),
                )
        update_headings()
        if sel_id and sel_id in tree.get_children():
            tree.selection_set(sel_id)
            tree.focus(sel_id)
        if table_kind == "videos" and rows_state and tree.get_children() and not hide_thumb_var.get():
            if not tree.selection():
                tree.selection_set("0")
            sel = tree.selection()
            show_thumbnail_for_index(int(sel[0]) if sel else 0)

    def show_thumbnail_for_index(index: int) -> None:
        if hide_thumb_var.get() or table_kind != "videos" or not (0 <= index < len(rows_state)):
            return
        v = rows_state[index]
        set_description_text(v.description)
        photo = thumb_photos.get(v.video_id)
        if photo is None:
            thumb_lbl.configure(image="", text="불러오는 중…")
            def load_one() -> None:
                p = load_thumbnail_photo(v.video_id)
                if p is not None:
                    thumb_photos[v.video_id] = p
                def apply() -> None:
                    if table_kind != "videos":
                        return
                    sel = tree.selection()
                    if not sel or int(sel[0]) != index:
                        return
                    if p is not None:
                        thumb_lbl.configure(image=p, text="")
                        thumb_lbl.image = p
                    else:
                        thumb_lbl.configure(image="", text="썸네일 없음")
                root.after(0, apply)
            threading.Thread(target=load_one, daemon=True).start()
            return
        thumb_lbl.configure(image=photo, text="")
        thumb_lbl.image = photo

    def prefetch_thumbnails(videos: list[VideoItem]) -> None:
        if hide_thumb_var.get():
            return
        def work() -> None:
            for v in videos[:50]:
                if v.video_id in thumb_photos:
                    continue
                p = load_thumbnail_photo(v.video_id)
                if p is not None:
                    thumb_photos[v.video_id] = p
            root.after(0, lambda: show_thumbnail_for_index(
                int(tree.selection()[0]) if tree.selection() else 0
            ))
        threading.Thread(target=work, daemon=True).start()

    def on_tree_select(_e=None) -> None:
        if table_kind != "videos" or hide_thumb_var.get():
            return
        sel = tree.selection()
        if sel:
            show_thumbnail_for_index(int(sel[0]))

    tree.bind("<<TreeviewSelect>>", on_tree_select)

    def on_sort_column(col: str) -> None:
        nonlocal sort_col, sort_reverse, kw_sort_col, kw_sort_reverse
        if table_kind == "keywords":
            if not keyword_rows_state:
                return
            if kw_sort_col == col:
                kw_sort_reverse = not kw_sort_reverse
            else:
                kw_sort_col = col
                kw_sort_reverse = col == "score"
            indexed = list(enumerate(keyword_rows_state))

            def kw_key(pair: tuple[int, KeywordItem]) -> object:
                idx, item = pair
                if col == "rank":
                    return idx
                if col == "keyword":
                    return item.keyword.casefold()
                if col == "score":
                    return item.score
                if col == "source":
                    return item.source.casefold()
                return idx

            indexed.sort(key=kw_key, reverse=kw_sort_reverse)
            keyword_rows_state[:] = [item for _, item in indexed]
            refresh_table()
            arrow = "내림차순" if kw_sort_reverse else "오름차순"
            status_var.set(f"{len(keyword_rows_state)}개 · {_KW_COL_LABELS[col]} {arrow} 정렬")
            return
        if not rows_state:
            return
        if sort_col == col:
            sort_reverse = not sort_reverse
        else:
            sort_col = col
            sort_reverse = col in _DEFAULT_DESC_COLS
        apply_sort()
        refresh_table()
        arrow = "내림차순" if sort_reverse else "오름차순"
        status_var.set(f"{len(rows_state)}개 · {_COL_LABELS[col]} {arrow} 정렬")

    update_headings()
    on_mode_change()

    def selected_video() -> VideoItem | None:
        sel = tree.selection()
        if not sel:
            return None
        i = int(sel[0])
        if 0 <= i < len(rows_state):
            return rows_state[i]
        return None

    def prefetch_title_translations(videos: list[VideoItem]) -> None:
        pending = [v for v in videos if v.video_id not in title_translations and not is_mostly_korean(v.title)]
        if not pending:
            return

        def work() -> None:
            for v in pending:
                title_translations[v.video_id] = translate_to_korean(v.title)
            root.after(0, refresh_table)

        threading.Thread(target=work, daemon=True).start()

    def fill_keyword_table(rows: list[KeywordItem]) -> None:
        nonlocal kw_sort_col, kw_sort_reverse
        keyword_rows_state.clear()
        keyword_rows_state.extend(rows)
        kw_sort_col = "score"
        kw_sort_reverse = True
        indexed = list(enumerate(keyword_rows_state))
        indexed.sort(key=lambda pair: pair[1].score, reverse=True)
        keyword_rows_state[:] = [item for _, item in indexed]
        refresh_table()
        status_var.set(f"{len(keyword_rows_state)}개 키워드 · 더블클릭하면 영상 검색")

    def fill_table(rows: list[VideoItem]) -> None:
        nonlocal sort_col, sort_reverse
        rows_state.clear()
        title_translations.clear()
        rows_state.extend(rows)
        sort_col = "views"
        sort_reverse = True
        apply_sort()
        refresh_table()
        prefetch_thumbnails(rows_state)
        prefetch_title_translations(rows_state)
        status_var.set(f"{len(rows_state)}개 영상 · 헤더 클릭 정렬 · 더블클릭 Utube 열기")

    def selected_regions() -> list[str]:
        if not selected_region_codes:
            return ["KR"]
        return sorted(selected_region_codes)

    def apply_result_filters(rows: list[VideoItem]) -> list[VideoItem]:
        exc = excluded_category_ids
        if exc:
            rows = [v for v in rows if not v.category_id or v.category_id not in exc]
        if exclude_shorts_var.get():
            rows = [v for v in rows if not v.is_shorts]
        return rows

    def do_fetch() -> None:
        key = api_var.get().strip() or load_api_key()
        if not key:
            messagebox.showwarning("조회", "YouTube API 키를 입력·저장하세요.")
            return
        try:
            mx = max(1, min(500, int(max_var.get())))
        except ValueError:
            mx = 50
        api_max = min(500, mx)

        def work() -> None:
            try:
                mode = mode_var.get()
                regs = selected_regions()
                if mode == _MODES[0]:
                    data = fetch_trending(
                        key,
                        regions=regs,
                        max_results=api_max,
                    )
                elif mode == _MODES[1]:
                    data = fetch_keyword_search(
                        key,
                        query=query_var.get(),
                        regions=regs,
                        days=int(days_var.get()),
                        max_results=api_max,
                    )
                elif mode == _MODES[2]:
                    data = fetch_top_by_views(
                        key,
                        query=query_var.get(),
                        regions=regs,
                        days=int(days_var.get()),
                        max_results=api_max,
                    )
                else:
                    keywords = fetch_popular_keywords(
                        key,
                        regions=regs,
                        max_results=mx,
                        exclude_shorts=exclude_shorts_var.get(),
                        excluded_category_ids=excluded_category_ids,
                    )

                    def done_keywords() -> None:
                        saved = persist_api_key_if_changed(key)
                        fill_keyword_table(keywords)
                        if saved:
                            status_var.set(
                                f"{len(keywords)}개 · API 키 저장됨 ({api_key_path_display()})"
                            )

                    root.after(0, done_keywords)
                    return
                data = apply_result_filters(data)[:mx]
            except (YouTubeApiError, ValueError) as e:
                root.after(0, lambda: messagebox.showerror("조회 실패", str(e)))
                root.after(0, lambda: status_var.set("조회 실패"))
                return
            def done() -> None:
                saved = persist_api_key_if_changed(key)
                fill_table(data)
                if not data:
                    status_var.set(
                        "조회 결과 없음 — 카테고리 제외·쇼츠 제외 설정을 확인하세요."
                    )
                elif saved:
                    status_var.set(
                        f"{len(data)}개 · API 키 저장됨 ({api_key_path_display()})"
                    )

            root.after(0, done)

        status_var.set("조회 중…")
        threading.Thread(target=work, daemon=True).start()

    def api_key_path_display() -> str:
        from utube.config import api_key_path

        try:
            return str(api_key_path().relative_to(module_root()))
        except ValueError:
            return str(api_key_path())

    def _export_rows() -> list[VideoItem]:
        return list(rows_state)

    def selected_keyword() -> KeywordItem | None:
        sel = tree.selection()
        if not sel:
            return None
        i = int(sel[0])
        if 0 <= i < len(keyword_rows_state):
            return keyword_rows_state[i]
        return None

    def search_selected_keyword() -> None:
        item = selected_keyword()
        if not item:
            messagebox.showinfo("키워드", "목록에서 키워드를 선택하세요.")
            return
        query_var.set(item.keyword)
        mode_var.set(_MODES[1])
        on_mode_change()
        do_fetch()

    def export_excel() -> None:
        if table_kind == "keywords":
            messagebox.showinfo("엑셀", "키워드 목록은 엑셀 저장을 지원하지 않습니다.")
            return
        rows = _export_rows()
        if not rows:
            messagebox.showinfo("엑셀", "먼저 조회하세요.")
            return
        default = module_root() / "output" / "youtube_videos.xlsx"
        path = filedialog.asksaveasfilename(
            title="엑셀 저장",
            initialdir=str(default.parent),
            initialfile=default.name,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != ".xlsx":
            p = p.with_suffix(".xlsx")
        try:
            export_videos_excel(p, rows, title_ko=title_translations)
        except RuntimeError as e:
            messagebox.showerror("엑셀", str(e))
            return
        except OSError as e:
            messagebox.showerror("엑셀", f"저장 실패: {e}")
            return
        messagebox.showinfo("엑셀", f"저장: {p}")

    btn_fr = ttk.Frame(frm)
    btn_fr.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    ttk.Button(btn_fr, text="조회", command=do_fetch).pack(side=tk.LEFT, padx=(0, 6))

    def open_youtube() -> None:
        v = selected_video()
        if v:
            webbrowser.open(v.url)

    ttk.Button(btn_fr, text="Utube에서 열기", command=open_youtube).pack(side=tk.LEFT, padx=(0, 6))

    def copy_url() -> None:
        v = selected_video()
        if not v:
            messagebox.showinfo("URL", "목록에서 영상을 선택하세요.")
            return
        root.clipboard_clear()
        root.clipboard_append(v.url)
        status_var.set(f"URL 복사: {v.url}")

    ttk.Button(btn_fr, text="URL 복사", command=copy_url).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_fr, text="엑셀 저장", command=export_excel).pack(side=tk.LEFT, padx=(0, 6))

    def on_tree_double_click(_e=None) -> None:
        if table_kind == "keywords":
            search_selected_keyword()
        else:
            open_youtube()

    tree.bind("<Double-1>", on_tree_double_click)

    def on_close() -> None:
        persist_api_key_if_changed(api_var.get())

    bind_close(root, standalone, on_close)
    if api_var.get().strip():
        root.after_idle(do_fetch)
    run_mainloop(root, standalone)


if __name__ == "__main__":
    main()
