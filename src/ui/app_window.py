from __future__ import annotations

import csv
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from src.app.orchestrator import Orchestrator
from src.models.items import CleanItem, Recommendation, format_size
from src.utils.disk import get_c_drive_usage, is_admin

_SEL_ON = "✔ 已选"
_SEL_OFF = "□ 未选"

_HEADINGS = {
    "selected": "选择（点整行）",
    "category": "分类",
    "size": "大小",
    "reco": "推荐",
    "risk": "风险",
    "detail": "文件说明",
    "reason": "原因",
    "path": "路径（可左右滑动）",
}


class AppWindow(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CDriveCleaner - C 盘清理工具")
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
        self._preview: tk.Toplevel | None = None
        self._item_by_iid: dict[str, CleanItem] = {}

        self._build()
        self._refresh_disk_status()

    def _build(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Clean.Treeview", rowheight=32, font=("Microsoft YaHei UI", 10))
        style.configure("Clean.Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

        self.status_label = ctk.CTkLabel(self, text="", anchor="w", justify="left")
        self.status_label.pack(fill="x", padx=12, pady=(12, 4))

        btn_row = ctk.CTkFrame(self)
        btn_row.pack(fill="x", padx=12, pady=4)

        self.btn_scan = ctk.CTkButton(btn_row, text="开始扫描", width=100, command=self.on_scan)
        self.btn_scan.pack(side="left", padx=3)
        self.btn_safe = ctk.CTkButton(btn_row, text="一键安全清理", width=110, command=self.on_safe, state="disabled")
        self.btn_safe.pack(side="left", padx=3)
        self.btn_deep = ctk.CTkButton(btn_row, text="深度清理", width=90, command=self.on_deep, state="disabled")
        self.btn_deep.pack(side="left", padx=3)
        self.btn_selected = ctk.CTkButton(btn_row, text="清理勾选项", width=100, command=self.on_selected, state="disabled")
        self.btn_selected.pack(side="left", padx=3)
        self.btn_dry = ctk.CTkButton(btn_row, text="模拟清理", width=90, command=self.on_dry_run, state="disabled")
        self.btn_dry.pack(side="left", padx=3)
        self.btn_export = ctk.CTkButton(btn_row, text="导出CSV", width=80, command=self.on_export_csv, state="disabled")
        self.btn_export.pack(side="left", padx=3)
        self.btn_treemap = ctk.CTkButton(btn_row, text="占用图", width=80, command=self.on_show_treemap, state="disabled")
        self.btn_treemap.pack(side="left", padx=3)
        self.btn_cancel = ctk.CTkButton(btn_row, text="取消", width=70, command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=3)

        self.chk_fast = ctk.CTkCheckBox(btn_row, text="快速扫描", width=90)
        self.chk_fast.pack(side="left", padx=6)
        self.chk_recycle = ctk.CTkCheckBox(btn_row, text="进回收站", width=90)
        self.chk_recycle.pack(side="left", padx=4)

        self.filter_box = ctk.CTkComboBox(btn_row, values=["全部"], width=160, command=self.on_filter_change, state="disabled")
        self.filter_box.set("全部")
        self.filter_box.pack(side="right", padx=4)
        ctk.CTkLabel(btn_row, text="分类筛选").pack(side="right")

        sel_row = ctk.CTkFrame(self)
        sel_row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(
            sel_row,
            text="表头排序｜悬停放大｜右键打开｜快速扫描跳过慢项｜默认永久删，勾选「进回收站」可恢复",
            anchor="w",
        ).pack(side="left", padx=4)
        self.btn_sort_size = ctk.CTkButton(sel_row, text="按大小↓", width=90, command=self.sort_by_size, state="disabled")
        self.btn_sort_size.pack(side="right", padx=3)
        self.btn_sel_reco = ctk.CTkButton(sel_row, text="全选「建议」", width=100, command=self.select_recommend, state="disabled")
        self.btn_sel_reco.pack(side="right", padx=3)
        self.btn_sel_opt = ctk.CTkButton(sel_row, text="全选「建议+可选」", width=120, command=self.select_deep, state="disabled")
        self.btn_sel_opt.pack(side="right", padx=3)
        self.btn_sel_none = ctk.CTkButton(sel_row, text="全不选", width=80, command=self.select_none, state="disabled")
        self.btn_sel_none.pack(side="right", padx=3)
        self.btn_sel_inv = ctk.CTkButton(sel_row, text="反选", width=70, command=self.select_invert, state="disabled")
        self.btn_sel_inv.pack(side="right", padx=3)

        self.progress = ctk.CTkProgressBar(self)
        self.progress.pack(fill="x", padx=12, pady=4)
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(self, text="就绪", anchor="w")
        self.progress_label.pack(fill="x", padx=12)

        table_frame = ctk.CTkFrame(self)
        table_frame.pack(fill="both", expand=True, padx=12, pady=8)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        columns = ("selected", "category", "size", "reco", "risk", "detail", "reason", "path")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", style="Clean.Treeview")
        widths = {"selected": 110, "category": 140, "size": 100, "reco": 80, "risk": 50, "detail": 260, "reason": 220, "path": 520}
        for col in columns:
            self.tree.heading(col, text=_HEADINGS[col], command=lambda c=col: self.on_heading_click(c))
            self.tree.column(col, width=widths[col], anchor="center" if col in {"selected", "size"} else "w", minwidth=80)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<ButtonRelease-1>", self.on_row_click)
        self.tree.bind("<space>", self.on_space_toggle)
        self.tree.bind("<Return>", self.on_space_toggle)
        self.tree.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        self.tree.bind("<Motion>", self.on_tree_motion)
        self.tree.bind("<Leave>", self.on_tree_leave)
        self.tree.bind("<Button-3>", self.on_right_click)

        self.summary_label = ctk.CTkLabel(self, text="已选合计: 0 B", anchor="w")
        self.summary_label.pack(fill="x", padx=12, pady=(0, 12))
        self._refresh_heading_labels()

    def _on_shift_wheel(self, event):
        self.tree.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _refresh_heading_labels(self) -> None:
        arrow = "↓" if self._sort_desc else "↑"
        for col, base in _HEADINGS.items():
            self.tree.heading(col, text=f"{base} {arrow}" if col == self._sort_by else base)
        if hasattr(self, "btn_sort_size"):
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
            self._sort_desc = col in {"size", "risk"}
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
        risk_rank = {"low": 0, "medium": 1, "high": 2}

        def sk(item: CleanItem):
            if key == "size":
                return item.size_bytes
            if key == "category":
                return item.category.lower()
            if key == "reco":
                return reco_rank.get(item.recommendation, 9)
            if key == "risk":
                return risk_rank.get(item.risk.value, 9)
            if key == "detail":
                return (item.detail or "").lower()
            if key == "reason":
                return (item.reason or "").lower()
            if key == "path":
                return item.path.lower()
            return item.size_bytes

        self.items.sort(key=sk, reverse=desc)
        self._refresh_heading_labels()

    def _refresh_disk_status(self) -> None:
        u = get_c_drive_usage()
        admin = "是" if is_admin() else "否（部分系统项可能无法清理）"
        self.status_label.configure(
            text=f"C 盘: 总量 {format_size(u.total)} / 已用 {format_size(u.used)} / 可用 {format_size(u.free)} ({u.used_pct:.1f}%)    管理员: {admin}"
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        idle = "normal" if not busy and self.items else "disabled"
        self.btn_scan.configure(state="disabled" if busy else "normal")
        for b in (
            self.btn_safe, self.btn_deep, self.btn_selected, self.btn_dry, self.btn_export, self.btn_treemap,
            self.btn_sel_reco, self.btn_sel_opt, self.btn_sel_none, self.btn_sel_inv, self.btn_sort_size,
        ):
            b.configure(state=idle)
        self.filter_box.configure(state=idle)
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        # 扫描中也可改选项；快速扫描仅影响下次扫描
        self.chk_fast.configure(state="disabled" if busy else "normal")
        self.chk_recycle.configure(state="disabled" if busy else "normal")

    def on_cancel(self) -> None:
        self.cancel_flag["cancel"] = True
        self.progress_label.configure(text="正在取消…")

    def on_scan(self) -> None:
        if self._busy:
            return
        self.cancel_flag = {"cancel": False}
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
                    cancel_flag=self.cancel_flag,
                    fast=bool(self.chk_fast.get()),
                )
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._scan_failed(str(exc)))
                return
            self.after(0, lambda: self._scan_done(items))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_failed(self, err: str) -> None:
        self._set_busy(False)
        messagebox.showerror("扫描失败", err)

    def _scan_done(self, items: list[CleanItem]) -> None:
        self.items = items
        self._sort_by, self._sort_desc = "size", True
        self._apply_sort()
        cats = sorted({i.category for i in items})
        self.filter_box.configure(values=["全部"] + cats)
        self.filter_box.set("全部")
        self._filter_category = "全部"
        self._reload_table()
        self._set_busy(False)
        self.progress.set(1)
        stats = self.orch.last_category_stats
        parts = [f"{k}:{v}" for k, v in stats.items() if v > 0]
        self.progress_label.configure(text=f"扫描完成，共 {len(items)} 项｜按大小↓｜{('，'.join(parts) if parts else '无命中')}")
        self._refresh_disk_status()

    def on_filter_change(self, value: str) -> None:
        self._filter_category = value or "全部"
        self._reload_table()

    def _visible_items(self) -> list[CleanItem]:
        if self._filter_category in ("", "全部"):
            return list(self.items)
        return [i for i in self.items if i.category == self._filter_category]

    def _mark(self, selected: bool) -> str:
        return _SEL_ON if selected else _SEL_OFF

    def _reload_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._item_by_iid.clear()
        risk_zh = {"low": "低", "medium": "中", "high": "高"}
        for item in self._visible_items():
            self._item_by_iid[item.id] = item
            self.tree.insert(
                "", "end", iid=item.id,
                values=(
                    self._mark(item.selected), item.category, format_size(item.size_bytes),
                    item.recommendation.label_zh, risk_zh.get(item.risk.value, item.risk.value),
                    item.detail, item.reason, item.path,
                ),
            )
        self._update_selected_sum()
        self._refresh_heading_labels()

    def on_row_click(self, event) -> None:
        if self._busy or self.tree.identify_region(event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        self._toggle_iid(row)

    def on_space_toggle(self, _event=None):
        if self._busy:
            return "break"
        row = self.tree.focus()
        if row:
            self._toggle_iid(row)
        return "break"

    def _toggle_iid(self, iid: str) -> None:
        item = self._item_by_iid.get(iid)
        if not item:
            return
        item.selected = not item.selected
        vals = list(self.tree.item(iid, "values"))
        vals[0] = self._mark(item.selected)
        self.tree.item(iid, values=vals)
        self._update_selected_sum()

    def on_tree_motion(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            self._schedule_hide_preview()
            return
        if row == self._hover_iid and self._preview is not None:
            return
        self._hover_iid = row
        if self._hover_job:
            self.after_cancel(self._hover_job)
        self._hover_job = self.after(180, lambda r=row, x=event.x_root, y=event.y_root: self._show_preview(r, x, y))

    def on_tree_leave(self, _event=None) -> None:
        self._schedule_hide_preview()

    def _schedule_hide_preview(self) -> None:
        self._hover_iid = None
        if self._hover_job:
            self.after_cancel(self._hover_job)
            self._hover_job = None
        self.after(120, self._hide_preview)

    def _hide_preview(self) -> None:
        if self._preview is not None:
            try:
                self._preview.destroy()
            except Exception:
                pass
            self._preview = None

    def _show_preview(self, iid: str, x_root: int, y_root: int) -> None:
        item = self._item_by_iid.get(iid)
        if not item or self._hover_iid != iid:
            return
        self._hide_preview()
        win = tk.Toplevel(self)
        win.wm_overrideredirect(True)
        win.attributes("-topmost", True)
        frame = tk.Frame(win, bg="#1e1e1e", padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        text = (
            f"【放大预览】\n分类：{item.category}\n大小：{format_size(item.size_bytes)}\n"
            f"推荐：{item.recommendation.label_zh}　风险：{item.risk.value}\n"
            f"说明：{item.detail}\n原因：{item.reason}\n路径：{item.path}"
        )
        tk.Label(frame, text=text, justify="left", anchor="nw", bg="#1e1e1e", fg="#f5f5f5",
                 font=("Microsoft YaHei UI", 12), wraplength=720).pack(fill="both", expand=True)
        win.update_idletasks()
        w, h = max(win.winfo_reqwidth(), 420), win.winfo_reqheight()
        px = min(x_root + 18, win.winfo_screenwidth() - w - 8)
        py = min(y_root + 18, win.winfo_screenheight() - h - 8)
        win.geometry(f"+{px}+{py}")
        self._preview = win

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
        for item in self.items:
            item.selected = bool(predicate(item))
        self._reload_table()

    def select_recommend(self) -> None:
        self._apply_selection(lambda i: i.recommendation == Recommendation.RECOMMEND)

    def select_deep(self) -> None:
        self._apply_selection(lambda i: i.recommendation in (Recommendation.RECOMMEND, Recommendation.OPTIONAL))

    def select_none(self) -> None:
        self._apply_selection(lambda _i: False)

    def select_invert(self) -> None:
        for item in self.items:
            item.selected = not item.selected
        self._reload_table()

    def _update_selected_sum(self) -> None:
        total = sum(i.size_bytes for i in self.items if i.selected)
        count = sum(1 for i in self.items if i.selected)
        self.summary_label.configure(text=f"已选 {count} 项，合计: {format_size(total)}")

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
            w.writerow(["selected", "category", "size_bytes", "size", "recommendation", "risk", "detail", "reason", "path"])
            for i in self.items:
                w.writerow([i.selected, i.category, i.size_bytes, format_size(i.size_bytes), i.recommendation.label_zh, i.risk.value, i.detail, i.reason, i.path])
        messagebox.showinfo("导出完成", f"已保存到:\n{path}")

    def _confirm_and_clean(self, targets: list[CleanItem], *, mode: str, force_second: bool = False, dry_run: bool = False) -> None:
        if not targets:
            messagebox.showinfo("提示", "没有可清理的项目")
            return
        total = sum(i.size_bytes for i in targets)
        use_recycle = bool(self.chk_recycle.get()) and not dry_run
        if dry_run:
            msg = f"【模拟清理】不会真正删除。\n预览 {len(targets)} 项，约 {format_size(total)}。\n仅写本地日志。是否继续？"
        elif use_recycle:
            msg = f"将移入【回收站】{len(targets)} 项，约 {format_size(total)}。\n可在回收站还原。\n模式: {mode}\n是否继续？"
        else:
            msg = f"即将【永久删除】{len(targets)} 项，约 {format_size(total)}。\n不会进入回收站。\n模式: {mode}\n是否继续？"
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
        messagebox.showerror("清理失败", err)

    def _clean_done(self, result, *, dry_run: bool = False, use_recycle: bool = False) -> None:
        if not dry_run:
            removed = set(result.removed_ids or [])
            if removed:
                self.items = [i for i in self.items if i.id not in removed]
                self._apply_sort()
                self._reload_table()
        self._set_busy(False)
        self._refresh_disk_status()
        if dry_run:
            title, extra = "模拟完成", "（未实际删除）"
        elif use_recycle:
            title, extra = "已移入回收站", f"已从列表移除: {len(result.removed_ids or [])} 项"
        else:
            title, extra = "清理完成", f"已从列表移除: {len(result.removed_ids or [])} 项"
        messagebox.showinfo(
            title,
            f"成功: {result.success_count}\n失败: {result.fail_count}\n释放约: {format_size(result.freed_bytes)} {extra}\n日志: {result.log_path}",
        )
        self.progress_label.configure(
            text=f"模拟完成，日志：{result.log_path}" if dry_run else f"{title}，剩余 {len(self.items)} 项"
        )


def run_app() -> None:
    AppWindow().mainloop()
