from __future__ import annotations

import csv
import os
import subprocess
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from src.app.orchestrator import Orchestrator
from src.models.items import CleanItem, Recommendation, effective_clean_targets, format_size
from src.ui import theme
from src.utils import drives
from src.utils.disk import is_admin
from src.utils.logging_util import logs_dir

_SEL_ON = "✔ 已选"
_SEL_OFF = "□ 未选"

_HEADINGS = {
    "selected": "选择",
    "category": "分类",
    "advice": "建议",
    "size": "大小",
    "admin": "权限",
    "detail": "文件说明",
    "reason": "原因",
    "path": "路径（可左右滑动）",
}

# 悬停预览：小、浅、且永不遮挡鼠标指针
_HOVER_DELAY_MS = 260          # 停留多久才弹出
_HOVER_MUTE_MS = 600           # 刚点过之后短暂不再弹出
_PREVIEW_GAP = 16              # 与指针的间距
_PREVIEW_WRAP = 430            # 文本折行宽度
_PREVIEW_FONT = ("Microsoft YaHei UI", 10)
_PREVIEW_MARGIN = 8            # 与屏幕边缘的最小距离
_PREVIEW_CLIP = {"detail": 60, "reason": 46, "path": 110}
_PREVIEW_SKIP_COLUMNS = {"selected"}  # 勾选列不弹预览，避免挡住点击


def compute_preview_position(
    x_root: int,
    y_root: int,
    w: int,
    h: int,
    screen_w: int,
    screen_h: int,
    *,
    gap: int = _PREVIEW_GAP,
    margin: int = _PREVIEW_MARGIN,
) -> tuple[int, int]:
    """给悬停预览挑一个既不越出屏幕、也绝不压住鼠标指针的位置。

    弹框是 topmost 的独立窗口，一旦盖住指针就会把点击整个吃掉，
    所以「指针不在弹框矩形内」是硬约束。
    """
    candidates = (
        (x_root + gap, y_root + gap),          # 右下（首选）
        (x_root - gap - w, y_root + gap),      # 左下
        (x_root + gap, y_root - gap - h),      # 右上
        (x_root - gap - w, y_root - gap - h),  # 左上
    )
    first = None
    for cx, cy in candidates:
        px = max(margin, min(cx, screen_w - w - margin))
        py = max(margin, min(cy, screen_h - h - margin))
        if first is None:
            first = (px, py)
        if not (px <= x_root <= px + w and py <= y_root <= py + h):
            return px, py
    px, py = first or (margin, margin)
    # 兜底：垂直方向彻底让开指针（宁可超出屏幕也不能挡住点击）
    if px <= x_root <= px + w and py <= y_root <= py + h:
        above = y_root - gap - h
        py = above if above >= margin else y_root + gap
    return px, py


class AppWindow(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CDriveCleaner - 磁盘清理工具")
        self.geometry("1400x780")
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.orch = Orchestrator()
        self.items: list[CleanItem] = []
        self.cancel_flag = {"cancel": False}
        self._busy = False
        self._sort_by = "size"
        self._sort_desc = True
        self._filter_category = "全部"
        self._hover_iid: str | None = None
        self._hover_job: str | None = None
        self._hover_mute_until = 0.0
        self._preview: tk.Toplevel | None = None
        self._preview_label: tk.Label | None = None
        self._preview_frame: tk.Frame | None = None
        self._preview_visible = False
        self._item_by_iid: dict[str, CleanItem] = {}
        self._scan_cancelled = False
        self._scan_partial_categories: list[str] = []
        self._closing = False
        #: 界面选中的目标盘。以界面为准，不用全局状态当真相来源 ——
        #: 全局状态是给扫描器读的，界面状态是给用户看的，两者不该互相顶替。
        self._target_drive: str = drives.target_drive()
        self._drive_infos: list = []

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._refresh_disk_status()

    def _build(self) -> None:
        self._themed_frames: list[tuple[ctk.CTkFrame, str]] = []
        self._themed_labels: list[tuple[ctk.CTkLabel, str]] = []
        self._themed_buttons: list[tuple[ctk.CTkButton, str]] = []
        self._themed_checks: list[ctk.CTkCheckBox] = []

        self._apply_tree_style()

        # ── 概览条：语义容量条（本产品 Signature）+ 管理员徽标 + 主题 ──────
        overview = self._mk_frame(self, "surface")
        overview.pack(fill="x")
        self._mk_divider(self, horizontal=True)
        ov = ctk.CTkFrame(overview, fg_color="transparent")
        ov.pack(fill="x", padx=theme.SPACE_LG, pady=theme.SPACE_MD)

        self._mk_label(ov, "目标盘", "section").pack(side="left", padx=(0, theme.SPACE_SM))
        self.drive_box = ctk.CTkOptionMenu(
            ov,
            values=self._drive_values(),
            width=170,
            command=self.on_drive_change,
            font=theme.FONT_BODY_13,
            dropdown_font=theme.FONT_BODY_13,
        )
        self.drive_box.set(self._drive_label(self._current_drive()))
        self.drive_box.pack(side="left", padx=(0, theme.SPACE_MD))
        self.capacity_bar = ctk.CTkProgressBar(ov, width=180, height=10, corner_radius=5)
        self.capacity_bar.set(0)
        self.capacity_bar.pack(side="left", padx=(0, theme.SPACE_MD))
        self.status_label = self._mk_label(ov, "读取中…", "body")
        self.status_label.pack(side="left")

        self.btn_theme = self._mk_button(ov, self._theme_button_text(), "ghost", self.on_toggle_theme, width=104)
        self.btn_theme.pack(side="right", padx=(theme.SPACE_SM, 0))
        self.admin_label = self._mk_label(ov, "权限检查中…", "caption")
        self.admin_label.pack(side="right", padx=(0, theme.SPACE_MD))

        # ── 工具条：按「扫描 / 清理 / 查看」分组，主次与危险动作分级 ──────
        toolbar = self._mk_frame(self, "surface")
        toolbar.pack(fill="x")
        self._mk_divider(self, horizontal=True)
        tb = ctk.CTkFrame(toolbar, fg_color="transparent")
        tb.pack(fill="x", padx=theme.SPACE_LG, pady=theme.SPACE_MD)

        g_scan = ctk.CTkFrame(tb, fg_color="transparent")
        g_scan.pack(side="left")
        self._mk_label(g_scan, "扫描", "caption").pack(anchor="w")
        scan_row = ctk.CTkFrame(g_scan, fg_color="transparent")
        scan_row.pack(anchor="w", pady=(theme.SPACE_XS, 0))
        # 全屏唯一的 primary（Anti-Slop B6）
        self.btn_scan = self._mk_button(scan_row, "开始扫描", "primary", self.on_scan, width=100)
        self.btn_scan.pack(side="left")
        self.btn_cancel = self._mk_button(scan_row, "取消", "ghost", self.on_cancel, width=64, state="disabled")
        self.btn_cancel.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.chk_fast = self._mk_check(scan_row, "快速扫描")
        self.chk_fast.pack(side="left", padx=(theme.SPACE_MD, 0))
        self.chk_recycle = self._mk_check(scan_row, "进回收站")
        self.chk_recycle.pack(side="left", padx=(theme.SPACE_MD, 0))

        self._mk_divider(tb)

        g_clean = ctk.CTkFrame(tb, fg_color="transparent")
        g_clean.pack(side="left")
        self._mk_label(g_clean, "清理", "caption").pack(anchor="w")
        clean_row = ctk.CTkFrame(g_clean, fg_color="transparent")
        clean_row.pack(anchor="w", pady=(theme.SPACE_XS, 0))
        self.btn_safe = self._mk_button(clean_row, "一键安全清理", "secondary", self.on_safe, width=116, state="disabled")
        self.btn_safe.pack(side="left")
        self.btn_selected = self._mk_button(clean_row, "清理勾选项", "danger", self.on_selected, width=100, state="disabled")
        self.btn_selected.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.btn_deep = self._mk_button(clean_row, "深度清理", "danger", self.on_deep, width=92, state="disabled")
        self.btn_deep.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.btn_dry = self._mk_button(clean_row, "模拟清理", "secondary", self.on_dry_run, width=92, state="disabled")
        self.btn_dry.pack(side="left", padx=(theme.SPACE_SM, 0))

        self._mk_divider(tb)

        g_view = ctk.CTkFrame(tb, fg_color="transparent")
        g_view.pack(side="left")
        self._mk_label(g_view, "查看", "caption").pack(anchor="w")
        view_row = ctk.CTkFrame(g_view, fg_color="transparent")
        view_row.pack(anchor="w", pady=(theme.SPACE_XS, 0))
        self.btn_treemap = self._mk_button(view_row, "占用图", "ghost", self.on_show_treemap, width=84, state="disabled")
        self.btn_treemap.pack(side="left")
        self.btn_export = self._mk_button(view_row, "导出 CSV", "ghost", self.on_export_csv, width=88, state="disabled")
        self.btn_export.pack(side="left", padx=(theme.SPACE_SM, 0))

        # ── 选择与筛选条 ────────────────────────────────────────────
        filterbar = self._mk_frame(self, "surface")
        filterbar.pack(fill="x")
        self._mk_divider(self, horizontal=True)
        fb = ctk.CTkFrame(filterbar, fg_color="transparent")
        fb.pack(fill="x", padx=theme.SPACE_LG, pady=theme.SPACE_MD)

        self.btn_sel_reco = self._mk_button(fb, "全选「建议」", "ghost", self.select_recommend, width=100, state="disabled")
        self.btn_sel_reco.pack(side="left")
        self.btn_sel_opt = self._mk_button(fb, "全选「建议+可选」", "ghost", self.select_deep, width=124, state="disabled")
        self.btn_sel_opt.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.btn_sel_none = self._mk_button(fb, "全不选", "ghost", self.select_none, width=84, state="disabled")
        self.btn_sel_none.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.btn_sel_inv = self._mk_button(fb, "反选", "ghost", self.select_invert, width=80, state="disabled")
        self.btn_sel_inv.pack(side="left", padx=(theme.SPACE_SM, 0))

        self.btn_sort_size = self._mk_button(fb, "按大小↓", "ghost", self.sort_by_size, width=88, state="disabled")
        self.btn_sort_size.pack(side="right")
        self.filter_box = ctk.CTkComboBox(
            fb, values=["全部"], width=150, command=self.on_filter_change, state="disabled",
            font=theme.FONT_BODY_13, dropdown_font=theme.FONT_BODY_13,
        )
        self.filter_box.set("全部")
        self.filter_box.pack(side="right", padx=(theme.SPACE_SM, theme.SPACE_MD))
        self._mk_label(fb, "分类筛选", "caption").pack(side="right")

        # ── 主区：flat table（不外包 card），空态与表格互斥切换 ──────────
        self.main_area = ctk.CTkFrame(self, fg_color=theme.palette().surface, corner_radius=0)
        self.main_area.pack(fill="both", expand=True)
        self.main_area.grid_rowconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)

        self.table_frame = ctk.CTkFrame(self.main_area, fg_color="transparent", corner_radius=0)
        self.table_frame.grid(row=0, column=0, sticky="nsew", padx=theme.SPACE_LG, pady=theme.SPACE_MD)
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)

        columns = ("selected", "category", "advice", "size", "admin", "detail", "reason", "path")
        self.tree = ttk.Treeview(
            self.table_frame, columns=columns, show="headings",
            selectmode="browse", style="Clean.Treeview",
        )
        widths = {"selected": 96, "category": 130, "advice": 116, "size": 96,
                  "admin": 84, "detail": 250, "reason": 210, "path": 460}
        for col in columns:
            self.tree.heading(col, text=_HEADINGS[col], command=lambda c=col: self.on_heading_click(c))
            self.tree.column(
                col, width=widths[col], minwidth=72,
                anchor="center" if col in {"selected", "advice", "size", "admin"} else "w",
            )
        self._apply_row_tags()

        vsb = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<ButtonPress-1>", self.on_tree_press, add="+")
        self.tree.bind("<ButtonRelease-1>", self.on_row_click)
        self.tree.bind("<space>", self.on_space_toggle)
        self.tree.bind("<Return>", self.on_space_toggle)
        self.tree.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        self.tree.bind("<MouseWheel>", self.on_tree_scroll, add="+")
        self.tree.bind("<Motion>", self.on_tree_motion)
        self.tree.bind("<Leave>", self.on_tree_leave)
        self.tree.bind("<Button-3>", self.on_right_click)
        self.bind("<Configure>", self.on_root_configure, add="+")

        self.empty_frame = ctk.CTkFrame(self.main_area, fg_color="transparent", corner_radius=0)
        self._build_empty_state(self.empty_frame)

        # ── 状态栏：已选合计 + 进度 + 当前扫描器 ────────────────────
        statusbar = self._mk_frame(self, "surface")
        statusbar.pack(fill="x")
        self._mk_divider(self, horizontal=True)
        sb = ctk.CTkFrame(statusbar, fg_color="transparent")
        sb.pack(fill="x", padx=theme.SPACE_LG, pady=theme.SPACE_SM)

        self.summary_label = self._mk_label(sb, "已选 0 项 · 合计 0 B", "body_bold")
        self.summary_label.pack(side="left")

        self.progress_label = self._mk_label(sb, "就绪", "secondary", anchor="e")
        self.progress_label.pack(side="right")
        self.progress = ctk.CTkProgressBar(sb, width=200, height=8, corner_radius=4)
        self.progress.set(0)
        self.progress.pack(side="right", padx=(0, theme.SPACE_MD))

        self._apply_theme()
        self._refresh_heading_labels()
        self._show_empty_state()

    # ── 主题与组件工厂 ───────────────────────────────────────────

    def _apply_tree_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        for name, conf in theme.tree_style_config().items():
            style.configure(name, **conf)

    def _apply_row_tags(self) -> None:
        if self.__dict__.get("tree") is None:
            return
        for tag, conf in theme.row_tag_styles().items():
            self.tree.tag_configure(tag, **conf)

    def _mk_frame(self, parent, role: str = "surface") -> ctk.CTkFrame:
        p = theme.palette()
        bg = {"surface": p.surface, "page": p.page_bg, "alt": p.surface_alt}[role]
        frame = ctk.CTkFrame(parent, fg_color=bg, corner_radius=0)
        self._themed_frames.append((frame, role))
        return frame

    def _mk_divider(self, parent, *, horizontal: bool = False):
        """1px 描边分区 —— 用描边替代卡片阴影墙（Anti-Slop B3）。"""
        p = theme.palette()
        d = ctk.CTkFrame(parent, fg_color=p.border, corner_radius=0,
                         height=1 if horizontal else 0, width=1)
        if horizontal:
            d.pack(fill="x")
        else:
            d.pack(side="left", fill="y", padx=theme.SPACE_XL)
        return d

    def _mk_label(self, parent, text: str, role: str = "body", **kw) -> ctk.CTkLabel:
        p = theme.palette()
        spec = {
            "page_title": (theme.FONT_PAGE_TITLE, p.text_primary),
            "section": (theme.FONT_SECTION, p.text_primary),
            "body": (theme.FONT_BODY_13, p.text_primary),
            "body_bold": (theme.FONT_BODY_BOLD, p.text_primary),
            "secondary": (theme.FONT_BODY_13, p.text_secondary),
            "caption": (theme.FONT_CAPTION, p.text_tertiary),
            "data": (theme.FONT_DATA_12, p.text_primary),
            "danger": (theme.FONT_BODY_13, p.danger),
            "success": (theme.FONT_BODY_13, p.success),
        }[role]
        anchor = kw.pop("anchor", "w")
        label = ctk.CTkLabel(parent, text=text, font=spec[0], text_color=spec[1], anchor=anchor, **kw)
        self._themed_labels.append((label, role))
        return label

    def _mk_button(self, parent, text: str, variant: str, command, *, width: int = 96,
                   height: int = theme.BUTTON_HEIGHT, state: str = "normal") -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent, text=text, width=width, height=height, command=command,
            corner_radius=theme.RADIUS_BUTTON, font=theme.FONT_BODY_13, state=state,
            **theme.button_style(variant),
        )
        self._themed_buttons.append((btn, variant))
        return btn

    def _mk_check(self, parent, text: str) -> ctk.CTkCheckBox:
        p = theme.palette()
        chk = ctk.CTkCheckBox(
            parent, text=text, font=theme.FONT_BODY_13, text_color=p.text_secondary,
            fg_color=p.primary, hover_color=p.primary_hover, border_color=p.text_tertiary,
            corner_radius=theme.RADIUS_TAG, checkbox_width=16, checkbox_height=16,
        )
        self._themed_checks.append(chk)
        return chk

    def _apply_theme(self) -> None:
        """把当前色板重新刷到所有已登记控件上（支持运行时切换主题）。"""
        p = theme.palette()
        self.configure(fg_color=p.page_bg)
        for frame, role in self._themed_frames:
            bg = {"surface": p.surface, "page": p.page_bg, "alt": p.surface_alt}[role]
            frame.configure(fg_color=bg)
        for label, role in self._themed_labels:
            label.configure(text_color={
                "page_title": p.text_primary,
                "section": p.text_primary,
                "body": p.text_primary,
                "body_bold": p.text_primary,
                "secondary": p.text_secondary,
                "caption": p.text_tertiary,
                "data": p.text_primary,
                "danger": p.danger,
                "success": p.success,
            }[role])
        for btn, variant in self._themed_buttons:
            btn.configure(**theme.button_style(variant))
        for chk in self._themed_checks:
            chk.configure(text_color=p.text_secondary, fg_color=p.primary,
                          hover_color=p.primary_hover, border_color=p.text_tertiary)
        if self.__dict__.get("main_area") is not None:
            self.main_area.configure(fg_color=p.surface)
        self._apply_tree_style()
        self._apply_row_tags()
        if self.__dict__.get("btn_theme") is not None:
            self.btn_theme.configure(text=self._theme_button_text())
        self._refresh_capacity_bar()

    def _theme_button_text(self) -> str:
        return "◐ 切到浅色" if theme.is_dark() else "◐ 切到深色"

    def on_toggle_theme(self) -> None:
        ctk.set_appearance_mode("Light" if theme.is_dark() else "Dark")
        self._apply_theme()
        self._refresh_heading_labels()
        self._refresh_disk_status()

    def _build_empty_state(self, parent) -> None:
        """未扫描时的引导态：说明 + 安全承诺。刻意不放第二个 primary 按钮（Anti-Slop B6）。"""
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.place(relx=0.5, rely=0.42, anchor="center")
        self._mk_label(box, "还没有扫描结果", "section").pack()
        self._mk_label(
            box,
            "选好目标盘后点「开始扫描」，逐条给出推荐级别与原因，勾选后再清理。",
            "secondary",
        ).pack(pady=(theme.SPACE_SM, theme.SPACE_LG))
        self._mk_label(box, "↑ 点击左上角「开始扫描」", "body_bold").pack()
        self._mk_label(
            box,
            "默认永久删除 · 勾选「进回收站」可恢复 · 关键系统路径硬排除 · 日志只写本机",
            "caption",
        ).pack(pady=(theme.SPACE_LG, 0))

    def _show_empty_state(self) -> None:
        # 注意：这里必须用 __dict__ 判断。tkinter 的 Misc.__getattr__ 会去取 self.tk，
        # 对未完整构造的实例（object.__new__ 造出来的）用 hasattr 会直接递归爆栈。
        if self.__dict__.get("empty_frame") is None:
            return
        self.table_frame.grid_forget()
        self.empty_frame.grid(row=0, column=0, sticky="nsew")

    def _show_table(self) -> None:
        if self.__dict__.get("table_frame") is None:
            return
        self.empty_frame.grid_forget()
        self.table_frame.grid(row=0, column=0, sticky="nsew", padx=theme.SPACE_LG, pady=theme.SPACE_MD)

    def _on_shift_wheel(self, event):
        self.tree.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _refresh_heading_labels(self) -> None:
        arrow = "↓" if self._sort_desc else "↑"
        for col, base in _HEADINGS.items():
            self.tree.heading(col, text=f"{base} {arrow}" if col == self._sort_by else base)
        if self.__dict__.get("btn_sort_size") is not None:
            self.btn_sort_size.configure(
                text=f"按大小{'↓' if self._sort_desc else '↑'}" if self._sort_by == "size" else "按大小"
            )

    def on_heading_click(self, col: str) -> None:
        if col == "selected":
            return
        if self._sort_by == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_by = col
            # 只有「大小」默认降序（先看最占地方的）；其余列默认升序
            # 建议列升序 = 建议删除 → 可选 → 不建议 → 仅报告，最安全的排最前
            self._sort_desc = col == "size"
        self._apply_sort()
        self._reload_table()

    def sort_by_size(self) -> None:
        if self._sort_by == "size":
            self._sort_desc = not self._sort_desc
        else:
            self._sort_by, self._sort_desc = "size", True
        self._apply_sort()
        self._reload_table()

    def _apply_sort(self) -> None:
        key, desc = self._sort_by, self._sort_desc
        reco_rank = {Recommendation.RECOMMEND: 0, Recommendation.OPTIONAL: 1, Recommendation.NOT_RECOMMENDED: 2}

        def sk(item: CleanItem):
            if key == "size":
                return item.size_bytes
            if key == "category":
                return item.category.lower()
            if key in {"advice", "reco"}:
                # 仅报告项永远排在最后
                return (0 if item.deletable else 1, reco_rank.get(item.recommendation, 9))
            if key == "admin":
                return item.needs_admin
            if key == "detail":
                return (item.detail or "").lower()
            if key == "reason":
                return (item.reason or "").lower()
            if key == "path":
                return item.path.lower()
            return item.size_bytes

        self.items.sort(key=sk, reverse=desc)
        self._refresh_heading_labels()

    # ── 目标盘 ────────────────────────────────────────────────────────

    def _drive_values(self) -> list[str]:
        """下拉框选项。盘枚举失败时退回当前盘，保证控件永远有值可选。"""
        self._drive_infos = drives.list_drives()
        labels = [d.title for d in self._drive_infos]
        if not labels:
            labels = [drives.target_drive()]
        return labels

    def _drive_label(self, letter: str) -> str:
        for d in self.__dict__.get("_drive_infos") or []:
            if d.letter == letter:
                return d.title
        return letter

    def _current_drive(self) -> str:
        """当前选中的盘。以界面上的选择为准，没选过就看全局目标盘。"""
        return self.__dict__.get("_target_drive") or drives.target_drive()

    def on_drive_change(self, value: str) -> None:
        """切换目标盘。

        切盘会**清空已有结果**。理由：表格里的条目全部属于上一个盘，
        留着它们再点清理，删的就是别的盘的文件。宁可让用户重扫一次，
        也不能让「看到的」和「会删的」不一致。
        """
        letter = value.split()[0] if value else ""
        normalized = drives.normalize_letter(letter)
        if not normalized:
            return
        if normalized == self._current_drive():
            return
        self._target_drive = normalized
        drives.set_target_drive(normalized)
        self._reset_results(f"已切换到 {normalized}，请点「开始扫描」")
        self._refresh_disk_status()

    def _reset_results(self, hint: str) -> None:
        """清空扫描结果与筛选状态，回到空态。"""
        self.items = []
        self._scan_cancelled = False
        self._scan_partial_categories = []
        self._filter_category = "全部"
        if self.__dict__.get("tree") is not None:
            self.tree.delete(*self.tree.get_children())
        self._item_by_iid.clear()
        self._hide_preview()
        self._show_empty_state()
        self._set_busy(False)
        progress = self.__dict__.get("progress")
        if progress is not None:
            progress.set(0)
        if self.__dict__.get("progress_label") is not None:
            self.progress_label.configure(text=hint)

    def _refresh_capacity_bar(self) -> None:
        """容量条按已用率取三档语义色；文字永远带上，状态不只靠颜色。"""
        if self.__dict__.get("capacity_bar") is None:
            return
        try:
            u = drives.drive_usage(self._current_drive())
        except OSError:
            self.capacity_bar.set(0)
            self.capacity_bar.configure(progress_color=theme.palette().text_tertiary)
            return
        pct = max(0.0, min(1.0, u.used_pct / 100.0))
        self.capacity_bar.set(pct)
        self.capacity_bar.configure(progress_color=theme.capacity_color(u.used_pct))

    def _refresh_disk_status(self) -> None:
        drive = self._current_drive()
        try:
            u = drives.drive_usage(drive)
        except OSError:
            self._refresh_capacity_bar()
            self.status_label.configure(text=f"{drive} 容量读取失败")
            self._refresh_admin_label()
            return
        self._refresh_capacity_bar()
        self.status_label.configure(
            text=(
                f"{drive}　已用 {format_size(u.used)} / {format_size(u.total)}（{u.used_pct:.1f}%）"
                f"　·　可用 {format_size(u.free)}"
            )
        )
        self._refresh_admin_label()

    def _refresh_admin_label(self) -> None:
        if is_admin():
            self.admin_label.configure(text="管理员 ✓")
        else:
            self.admin_label.configure(text="非管理员 · 部分系统项可能无法清理")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        review_idle = "normal" if not busy and self.items else "disabled"
        has_cleanable = any(item.deletable for item in self.items)
        clean_idle = "normal" if not busy and has_cleanable and not self._scan_cancelled else "disabled"
        self.btn_scan.configure(state="disabled" if busy else "normal")
        for b in (
            self.btn_safe, self.btn_deep, self.btn_selected, self.btn_dry,
        ):
            b.configure(state=clean_idle)
        for b in (self.btn_export, self.btn_treemap, self.btn_sort_size):
            b.configure(state=review_idle)
        for b in (self.btn_sel_reco, self.btn_sel_opt, self.btn_sel_none, self.btn_sel_inv):
            b.configure(state=clean_idle)
        self.filter_box.configure(state=review_idle)
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        # 扫描中不许切盘：切了结果就属于上一个盘，清理时会删错地方。
        # 用 __dict__ 取，不用 self.drive_box —— tkinter 的 Misc.__getattr__ 会去取
        # self.tk，对 object.__new__ 造出来的未完整实例会直接递归爆栈。
        drive_box = self.__dict__.get("drive_box")
        if drive_box is not None:
            drive_box.configure(state="disabled" if busy else "normal")
        # 扫描中也可改选项；快速扫描仅影响下次扫描
        self.chk_fast.configure(state="disabled" if busy else "normal")
        self.chk_recycle.configure(state="disabled" if busy else "normal")

    def on_cancel(self) -> None:
        self.cancel_flag["cancel"] = True
        self.progress_label.configure(text="正在取消…")

    def report_callback_exception(self, exc, val, tb) -> None:
        """打包后 console=False，回调异常会被静默吞掉（表现为「点了没反应」），这里显式兜住。"""
        text = "".join(traceback.format_exception(exc, val, tb))
        log_path = None
        try:
            log_path = logs_dir() / "ui_error.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}")
        except Exception:
            pass
        if self.__dict__.get("_error_dialog_open"):
            return
        self._error_dialog_open = True
        try:
            tail = f"\n\n已记录到: {log_path}" if log_path else ""
            messagebox.showerror("界面操作出错", f"{val}{tail}")
        except Exception:
            pass
        finally:
            self._error_dialog_open = False

    def _on_close_request(self) -> None:
        if self.__dict__.get("_closing", False):
            return
        if not self._busy:
            self._hide_preview()
            self.destroy()
            return
        if not messagebox.askyesno("任务进行中", "当前任务仍在运行，确认取消并退出吗？"):
            return
        self._closing = True
        self.cancel_flag["cancel"] = True
        self.progress_label.configure(text="正在取消，完成当前文件操作后退出…")

    def on_scan(self) -> None:
        if self._busy:
            return
        self.cancel_flag = {"cancel": False}
        self._scan_cancelled = False
        self._scan_partial_categories = []
        scan_flag = self.cancel_flag
        fast_scan = bool(self.chk_fast.get())
        self._set_busy(True)
        self.progress.set(0)
        self.progress_label.configure(text="扫描中…")
        self._hide_preview()

        def worker() -> None:
            def progress(name: str, overall: float, cur: int, total: int) -> None:
                def _ui(name=name, overall=overall, cur=cur, total=total) -> None:
                    self.progress.set(overall)
                    self.progress_label.configure(text=f"扫描中 ({cur}/{total}) {overall*100:.0f}%  {name}")
                self.after(0, _ui)
            try:
                items = self.orch.scan(
                    progress=progress,
                    cancel_flag=scan_flag,
                    fast=fast_scan,
                    drive=self._target_drive,
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._scan_failed(str(exc)))
                return
            self.after(0, lambda: self._scan_done(items))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_failed(self, err: str) -> None:
        self.items = []
        self._scan_cancelled = True
        self._scan_partial_categories = []
        if self.__dict__.get("tree") is not None:
            self.tree.delete(*self.tree.get_children())
        self._item_by_iid.clear()
        self._show_empty_state()
        self._set_busy(False)
        if self.__dict__.get("_closing", False):
            self.destroy()
            return
        messagebox.showerror("扫描失败", err)

    def _scan_done(self, items: list[CleanItem]) -> None:
        if self.__dict__.get("_closing", False):
            self._busy = False
            self.destroy()
            return
        self.items = items
        self._scan_cancelled = self.orch.last_scan_cancelled
        self._scan_partial_categories = list(self.orch.last_scan_partial_categories)
        self._sort_by, self._sort_desc = "size", True
        self._apply_sort()
        cats = sorted({i.category for i in items})
        self.filter_box.configure(values=["全部"] + cats)
        self.filter_box.set("全部")
        self._filter_category = "全部"
        self._sync_selection_scope()
        if items:
            self._show_table()
        else:
            self._show_empty_state()
        self._reload_table()
        self._set_busy(False)
        self.progress.set(1)
        stats = self.orch.last_category_stats
        parts = [f"{k}:{v}" for k, v in stats.items() if v > 0]
        skipped = self.orch.last_skipped_scanners
        if self._scan_cancelled:
            status = "扫描已取消，清理操作已禁用"
        elif self._scan_partial_categories:
            status = f"扫描完成（部分结果：{'、'.join(self._scan_partial_categories)}）"
        elif self.orch.last_scan_fast:
            status = "快速扫描完成"
        else:
            status = "扫描完成"
        status = f"{self._target_drive} {status}，共 {len(items)} 项"
        if skipped:
            # 必须说出来。用户会奇怪「为什么 D 盘只扫出这么点东西」，
            # 不解释的话看起来像漏扫。
            status += f"｜{len(skipped)} 个扫描器不适用于本盘"
        status += f"｜按大小↓｜{('，'.join(parts) if parts else '无命中')}"
        self.progress_label.configure(text=status)
        self._refresh_disk_status()

    def on_filter_change(self, value: str) -> None:
        self._filter_category = value or "全部"
        self._sync_selection_scope()
        self._reload_table()

    def _visible_items(self) -> list[CleanItem]:
        if self._filter_category in ("", "全部"):
            return list(self.items)
        return [i for i in self.items if i.category == self._filter_category]

    def _mark(self, selected: bool) -> str:
        return _SEL_ON if selected else _SEL_OFF

    @staticmethod
    def _advice_cell(item: CleanItem) -> str:
        """推荐与风险合并成一列语义徽标 —— 二者本是同一套规则的两个说法。"""
        if not item.deletable:
            glyph, label, _ = theme.ADVICE_BADGE["report_only"]
            return f"{glyph} {label}"
        glyph, label, _ = theme.ADVICE_BADGE.get(item.recommendation.value, ("", item.recommendation.label_zh, ""))
        return f"{glyph} {label}"

    @staticmethod
    def _row_tag(item: CleanItem) -> str:
        if not item.deletable:
            return "report"
        if item.recommendation == Recommendation.NOT_RECOMMENDED:
            return "danger"
        if item.recommendation == Recommendation.OPTIONAL:
            return "optional"
        return "safe"

    def _reload_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._item_by_iid.clear()
        for item in self._visible_items():
            self._item_by_iid[item.id] = item
            self.tree.insert(
                "", "end", iid=item.id, tags=(self._row_tag(item),),
                values=(
                    self._mark(item.selected), item.category,
                    self._advice_cell(item), format_size(item.size_bytes),
                    "需管理员" if item.needs_admin else "",
                    item.detail, item.reason, item.path,
                ),
            )
        self._update_selected_sum()
        self._refresh_heading_labels()

    def on_row_click(self, event) -> None:
        if self._busy:
            return
        # 预览弹框已在 ButtonPress 阶段收起，这里正常处理点击
        region = self.tree.identify_region(event.x, event.y)
        if region not in ("cell", "tree"):
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        self._toggle_iid(row)

    def on_tree_press(self, _event=None) -> None:
        """按下鼠标立刻收起预览，保证点击一定落到表格上。"""
        self._hover_mute_until = time.monotonic() + _HOVER_MUTE_MS / 1000.0
        self._hover_iid = None
        if self._hover_job:
            try:
                self.after_cancel(self._hover_job)
            except Exception:
                pass
            self._hover_job = None
        self._hide_preview()

    def on_tree_scroll(self, _event=None) -> None:
        self._hide_preview()

    def on_root_configure(self, event=None) -> None:
        if event is not None and getattr(event, "widget", None) is not self:
            return
        self._hide_preview()

    def on_space_toggle(self, _event=None):
        if self._busy or self._scan_cancelled:
            return "break"
        row = self.tree.focus()
        if row:
            self._toggle_iid(row)
        return "break"

    def _toggle_iid(self, iid: str) -> None:
        item = self._item_by_iid.get(iid)
        if self._scan_cancelled:
            self.progress_label.configure(text="扫描已取消，请重新扫描后再勾选")
            return
        if not item:
            return
        if not item.deletable:
            self.progress_label.configure(
                text=f"该项不可勾选（仅报告）：{item.protection_reason or item.reason or item.path}"
            )
            return
        item.selected = not item.selected
        vals = list(self.tree.item(iid, "values"))
        vals[0] = self._mark(item.selected)
        self.tree.item(iid, values=vals)
        self._update_selected_sum()

    def on_tree_motion(self, event) -> None:
        if self._busy or time.monotonic() < self._hover_mute_until:
            return
        col = self.tree.identify_column(event.x)
        if self._column_name(col) in _PREVIEW_SKIP_COLUMNS:
            self._schedule_hide_preview()
            return
        row = self.tree.identify_row(event.y)
        if not row:
            self._schedule_hide_preview()
            return
        if row == self._hover_iid and self._preview_visible:
            return
        self._hover_iid = row
        if self._hover_job:
            try:
                self.after_cancel(self._hover_job)
            except Exception:
                pass
        self._hover_job = self.after(
            _HOVER_DELAY_MS,
            lambda r=row, x=event.x_root, y=event.y_root: self._show_preview(r, x, y),
        )

    def _column_name(self, col_id: str) -> str:
        cols = self.tree["columns"]
        try:
            idx = int(str(col_id).lstrip("#")) - 1
        except (TypeError, ValueError):
            return ""
        return cols[idx] if 0 <= idx < len(cols) else ""

    def on_tree_leave(self, _event=None) -> None:
        self._schedule_hide_preview()

    def _schedule_hide_preview(self) -> None:
        self._hover_iid = None
        if self._hover_job:
            try:
                self.after_cancel(self._hover_job)
            except Exception:
                pass
            self._hover_job = None
        self.after(120, self._hide_preview)

    def _hide_preview(self) -> None:
        self._preview_visible = False
        if self._preview is not None:
            try:
                self._preview.withdraw()
            except Exception:
                pass

    def _preview_colors(self) -> tuple[str, str, str]:
        p = theme.palette()
        # 用 text_tertiary 描边，保证浮层在白色表格上仍有可辨边界（无阴影可用）
        return p.surface, p.text_primary, p.text_tertiary

    def _ensure_preview(self) -> tk.Toplevel:
        if self._preview is not None and self._preview.winfo_exists():
            return self._preview
        win = tk.Toplevel(self)
        win.wm_overrideredirect(True)
        win.attributes("-topmost", True)
        bg, fg, border = self._preview_colors()
        frame = tk.Frame(win, bg=bg, highlightthickness=1,
                         highlightbackground=border, highlightcolor=border)
        frame.pack(fill="both", expand=True)
        label = tk.Label(frame, text="", justify="left", anchor="nw", bg=bg, fg=fg,
                         font=_PREVIEW_FONT, wraplength=_PREVIEW_WRAP, padx=11, pady=8)
        label.pack(fill="both", expand=True)
        self._preview, self._preview_frame, self._preview_label = win, frame, label
        return win

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        flat = " ".join((text or "").split())
        return flat if len(flat) <= limit else flat[: limit - 1] + "…"

    def _preview_text(self, item: CleanItem) -> str:
        head = (
            f"{item.category}　·　{format_size(item.size_bytes)}"
            f"　·　{item.recommendation.label_zh}／{theme.RISK_ZH.get(item.risk.value, item.risk.value)}风险"
        )
        if not item.deletable:
            head += "　·　仅报告，不可清理"
        lines = [head]
        if item.detail:
            lines.append(f"说明：{self._clip(item.detail, _PREVIEW_CLIP['detail'])}")
        if item.reason and item.reason != item.detail:
            lines.append(f"原因：{self._clip(item.reason, _PREVIEW_CLIP['reason'])}")
        lines.append(f"路径：{self._clip(item.path, _PREVIEW_CLIP['path'])}")
        return "\n".join(lines)

    def _preview_position(self, x_root: int, y_root: int, w: int, h: int) -> tuple[int, int]:
        return compute_preview_position(
            x_root, y_root, w, h, self.winfo_screenwidth(), self.winfo_screenheight()
        )

    def _show_preview(self, iid: str, x_root: int, y_root: int) -> None:
        item = self._item_by_iid.get(iid)
        if self._busy or not item or self._hover_iid != iid:
            return
        if time.monotonic() < self._hover_mute_until:
            return
        win = self._ensure_preview()
        bg, fg, border = self._preview_colors()
        self._preview_frame.configure(bg=bg, highlightbackground=border, highlightcolor=border)
        self._preview_label.configure(text=self._preview_text(item), bg=bg, fg=fg)
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        px, py = self._preview_position(x_root, y_root, w, h)
        win.geometry(f"{w}x{h}+{px}+{py}")
        win.deiconify()
        self._preview_visible = True

    def on_right_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="打开所在文件夹", command=lambda: self.open_in_explorer(row))
        menu.add_command(label="复制路径", command=lambda: self.copy_path(row))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def open_in_explorer(self, iid: str) -> None:
        item = self._item_by_iid.get(iid)
        if not item:
            return
        path = Path(item.path)
        try:
            if path.is_file():
                subprocess.run(["explorer", "/select,", str(path)], check=False)
            elif path.exists():
                os.startfile(str(path))  # noqa: S606
            elif path.parent.exists():
                os.startfile(str(path.parent))  # noqa: S606
            else:
                messagebox.showwarning("提示", "路径不存在")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败", str(exc))

    def copy_path(self, iid: str) -> None:
        item = self._item_by_iid.get(iid)
        if not item:
            return
        self.clipboard_clear()
        self.clipboard_append(item.path)
        self.progress_label.configure(text=f"已复制路径：{item.path}")

    def _apply_selection(self, predicate) -> None:
        """只作用于当前筛选视图 —— 筛选到某个分类时，「全选」就只选那个分类。"""
        if self._scan_cancelled:
            return
        for item in self._visible_items():
            item.selected = item.deletable and bool(predicate(item))
        self._reload_table()
        self._report_selection_scope()

    def select_recommend(self) -> None:
        self._apply_selection(lambda i: i.recommendation == Recommendation.RECOMMEND)

    def select_deep(self) -> None:
        self._apply_selection(lambda i: i.recommendation in (Recommendation.RECOMMEND, Recommendation.OPTIONAL))

    def select_none(self) -> None:
        self._apply_selection(lambda _i: False)

    def select_invert(self) -> None:
        if self._scan_cancelled:
            return
        for item in self._visible_items():
            if item.deletable:
                item.selected = not item.selected
        self._reload_table()
        self._report_selection_scope()

    def _selection_scope_label(self) -> str:
        cat = self._filter_category
        return "全部" if cat in ("", "全部") else cat

    def _report_selection_scope(self) -> None:
        """把作用范围说出来，避免用户以为动了全部项目。"""
        summary = self.__dict__.get("summary_label")
        progress = self.__dict__.get("progress_label")
        if summary is None or progress is None:
            return
        scope = self._selection_scope_label()
        picked = len([i for i in self._visible_items() if i.selected and i.deletable])
        progress.configure(text=f"已在「{scope}」内选中 {picked} 项（{summary.cget('text')}）")

    def _sync_selection_scope(self) -> None:
        """选择按钮的作用范围跟着筛选走，标签必须如实反映，不能写「全选」却只选一类。

        用 self.__dict__.get 取控件：在 object.__new__ 造出的半构造实例上，
        属性访问会经 tkinter 的 Misc.__getattr__ 去查 self.tk 而无限递归。
        """
        scoped = self._filter_category not in ("", "全部")
        labels = {
            "btn_sel_reco": "本类「建议」" if scoped else "全选「建议」",
            "btn_sel_opt": "本类「建议+可选」" if scoped else "全选「建议+可选」",
            "btn_sel_none": "本类不选" if scoped else "全不选",
            "btn_sel_inv": "本类反选" if scoped else "反选",
        }
        for name, text in labels.items():
            button = self.__dict__.get(name)
            if button is not None:
                button.configure(text=text)

    def _update_selected_sum(self) -> None:
        targets = effective_clean_targets([i for i in self.items if i.selected and i.deletable])
        total = sum(i.size_bytes for i in targets)
        count = len(targets)
        self.summary_label.configure(text=f"已选 {count} 项 · 合计 {format_size(total)}")

    def on_safe(self) -> None:
        self._confirm_and_clean(self.orch.items_for_safe_clean(self.items), mode="安全清理")

    def on_deep(self) -> None:
        self._confirm_and_clean(self.orch.items_for_deep_clean(self.items), mode="深度清理", force_second=True)

    def on_selected(self) -> None:
        self._confirm_and_clean(self.orch.selected_items(self.items), mode="勾选清理")

    def on_dry_run(self) -> None:
        self._confirm_and_clean(self.orch.selected_items(self.items), mode="模拟清理", dry_run=True)

    def on_show_treemap(self) -> None:
        if not self.items:
            messagebox.showinfo("提示", "请先扫描")
            return
        from src.ui.treemap_window import show_category_treemap

        show_category_treemap(self, self.items)

    def on_export_csv(self) -> None:
        if not self.items:
            messagebox.showinfo("提示", "没有可导出的结果")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="clean_scan_result.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["drive", "selected", "category", "size_bytes", "size", "recommendation", "risk", "needs_admin", "detail", "reason", "path"])
            for i in self.items:
                w.writerow([i.drive or self._target_drive, i.selected, i.category, i.size_bytes, format_size(i.size_bytes), i.recommendation.label_zh, i.risk.value, i.needs_admin, i.detail, i.reason, i.path])
        messagebox.showinfo("导出完成", f"已保存到:\n{path}")

    def _confirm_and_clean(self, targets: list[CleanItem], *, mode: str, force_second: bool = False, dry_run: bool = False) -> None:
        if self._scan_cancelled:
            messagebox.showinfo("提示", "扫描已取消，请重新扫描后再清理")
            return
        if not targets:
            messagebox.showinfo("提示", "没有可清理的项目")
            return
        total = sum(i.size_bytes for i in targets)
        use_recycle = bool(self.chk_recycle.get()) and not dry_run
        if dry_run:
            msg = f"【模拟清理】不会真正删除。\n预览 {len(targets)} 项，约 {format_size(total)}。\n仅写本地日志。是否继续？"
        elif use_recycle and any(i.category == "回收站" for i in targets):
            msg = f"将清空【回收站】中的内容，共 {len(targets)} 项，约 {format_size(total)}。\n该操作不可恢复。\n模式: {mode}\n是否继续？"
        elif use_recycle:
            msg = f"将移入【回收站】{len(targets)} 项，约 {format_size(total)}。\n可在回收站还原。\n模式: {mode}\n是否继续？"
        else:
            msg = f"即将【永久删除】{len(targets)} 项，约 {format_size(total)}。\n不会进入回收站。\n模式: {mode}\n是否继续？"
        if self._scan_partial_categories:
            msg += f"\n注意：以下分类达到扫描时限，结果可能不完整：{'、'.join(self._scan_partial_categories)}。"
        if not messagebox.askyesno("确认", msg):
            return
        if not dry_run and not use_recycle and (force_second or self.orch.needs_second_confirm(targets)):
            if not messagebox.askyesno("二次确认", "包含可选/不建议或深度项，确认永久删除？"):
                return
        self.cancel_flag = {"cancel": False}
        self._set_busy(True)
        self._hide_preview()
        self.progress_label.configure(text=f"{mode} 执行中…")

        def worker() -> None:
            try:
                result = self.orch.clean(
                    targets,
                    cancel_flag=self.cancel_flag,
                    dry_run=dry_run,
                    use_recycle_bin=use_recycle,
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._clean_failed(str(exc)))
                return
            self.after(0, lambda: self._clean_done(result, dry_run=dry_run, use_recycle=use_recycle))

        threading.Thread(target=worker, daemon=True).start()

    def _clean_failed(self, err: str) -> None:
        self._set_busy(False)
        if self.__dict__.get("_closing", False):
            self.destroy()
            return
        messagebox.showerror("清理失败", err)

    def _clean_done(self, result, *, dry_run: bool = False, use_recycle: bool = False) -> None:
        if self._closing:
            self._busy = False
            self.destroy()
            return
        if not dry_run:
            removed = set(result.removed_ids or [])
            if removed:
                self.items = [
                    i
                    for i in self.items
                    if i.id not in removed and (not i.deletable or Path(i.path).exists())
                ]
                self._apply_sort()
                if self.items:
                    self._reload_table()
                else:
                    self._show_empty_state()
        self._set_busy(False)
        self._refresh_disk_status()
        if result.partial_count:
            title, extra = "清理部分完成", f"部分失败: {result.partial_count} 项，已释放: {format_size(result.freed_bytes)}"
        elif result.cancelled:
            title, extra = "清理已取消", f"尚未处理: {result.remaining_count} 项"
        elif dry_run:
            title, extra = "模拟完成", "（未实际删除）"
        elif use_recycle:
            title, extra = "已移入回收站", f"已从列表移除: {len(result.removed_ids or [])} 项"
        else:
            title, extra = "清理完成", f"已从列表移除: {len(result.removed_ids or [])} 项"
        error_text = ""
        if result.errors:
            error_text = "\n失败示例:\n" + "\n".join(f"- {error}" for error in result.errors[:3])
        amount_label = "预计释放" if dry_run else "释放约"
        amount = result.estimated_bytes if dry_run else result.freed_bytes
        messagebox.showinfo(
            title,
            f"成功: {result.success_count}\n失败: {result.fail_count}\n部分完成: {result.partial_count}\n{amount_label}: {format_size(amount)}\n{extra}\n日志: {result.log_path}{error_text}",
        )
        self.progress_label.configure(
            text=f"模拟完成，日志：{result.log_path}" if dry_run else f"{title}，剩余 {len(self.items)} 项"
        )


def run_app() -> None:
    AppWindow().mainloop()
