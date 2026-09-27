from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.models.items import CleanItem, effective_clean_targets, format_size
from src.ui.treemap import COLORS, squarify


def category_totals(items: list[CleanItem]) -> dict[str, int]:
    """Return non-overlapping totals for actionable scan items."""
    totals: dict[str, int] = {}
    targets = effective_clean_targets([item for item in items if item.deletable])
    for it in targets:
        totals[it.category] = totals.get(it.category, 0) + max(0, it.size_bytes)
    return totals


def show_category_treemap(parent, items: list[CleanItem]) -> None:
    """弹出按分类汇总的占用矩形图。"""
    totals = category_totals(items)
    data = sorted(totals.items(), key=lambda x: -x[1])
    if not data:
        return

    win = tk.Toplevel(parent)
    win.title("占用分布图（按分类）")
    win.geometry("900x560")
    tip = ttk.Label(win, text="色块面积 ≈ 该分类可清理项合计大小；悬停查看数值。借鉴 WinDirStat/Capacitra。")
    tip.pack(fill="x", padx=8, pady=6)

    canvas = tk.Canvas(win, bg="#111111", highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=8, pady=8)
    status = ttk.Label(win, text="")
    status.pack(fill="x", padx=8, pady=(0, 8))

    pad = 8

    def redraw(_event=None) -> None:
        canvas.delete("all")
        cw = max(canvas.winfo_width() - pad * 2, 100)
        ch = max(canvas.winfo_height() - pad * 2, 100)
        rects = squarify(data, pad, pad, cw, ch)
        canvas._rects = rects  # type: ignore[attr-defined]
        for i, r in enumerate(rects):
            color = COLORS[i % len(COLORS)]
            canvas.create_rectangle(
                r.x, r.y, r.x + r.w, r.y + r.h,
                fill=color, outline="#0d0d0d", width=2, tags=("cell", f"i{i}"),
            )
            if r.w > 70 and r.h > 36:
                text = f"{r.label}\n{format_size(r.value)}"
                canvas.create_text(
                    r.x + r.w / 2,
                    r.y + r.h / 2,
                    text=text,
                    fill="white",
                    font=("Microsoft YaHei UI", 10, "bold"),
                    width=max(r.w - 10, 40),
                    tags=("cell", f"i{i}"),
                )

    def on_move(event) -> None:
        rects = getattr(canvas, "_rects", [])
        hit = None
        for r in rects:
            if r.x <= event.x <= r.x + r.w and r.y <= event.y <= r.y + r.h:
                hit = r
                break
        if hit:
            status.configure(text=f"{hit.label}  ·  {format_size(hit.value)}")
        else:
            status.configure(text="")

    canvas.bind("<Configure>", redraw)
    canvas.bind("<Motion>", on_move)
    win.after(50, redraw)
