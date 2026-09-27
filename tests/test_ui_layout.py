"""界面改版的回归护栏：token 合规、语义徽标、行底色、排序方向。

对应 docs/design/design-plan.md 的 Anti-Slop 结论 —— 这些断言就是"别再退回 AI 默认皮"的闸门。
"""
from __future__ import annotations

import inspect

from src.models.items import CleanItem, Recommendation
from src.ui import theme
from src.ui.app_window import AppWindow

FORBIDDEN_FONTS = ("Inter", "Roboto", "Arial", "system-ui", "Space Grotesk")
ALLOWED_SPACING = {4, 8, 12, 16, 24, 32, 48}


def _item(**kw):
    base = dict(
        id=kw.pop("id", "x"),
        category=kw.pop("category", "临时文件"),
        path=kw.pop("path", "C:\\Temp\\a.tmp"),
        size_bytes=kw.pop("size_bytes", 1024),
        recommendation=kw.pop("recommendation", Recommendation.RECOMMEND),
        reason=kw.pop("reason", "原因"),
    )
    base.update(kw)
    return CleanItem.make(**base)


# ---------- Token 合规（Anti-Slop A1 / A2 / B3）----------

def test_body_font_is_not_in_forbidden_list():
    assert theme.FONT_BODY not in FORBIDDEN_FONTS
    assert theme.FONT_DATA not in FORBIDDEN_FONTS
    assert "YaHei" in theme.FONT_BODY


def test_primary_is_not_ai_default_indigo():
    assert theme.LIGHT.primary.upper() != "#6366F1"
    assert theme.DARK.primary.upper() != "#6366F1"
    assert theme.LIGHT.primary.upper() == "#1677FF"   # B 端轨主色


def test_spacing_constants_are_on_the_allowed_scale():
    values = [
        getattr(theme, name)
        for name in dir(theme)
        if name.startswith("SPACE_")
    ]
    assert values, "至少要有几个间距常量"
    assert set(values) <= ALLOWED_SPACING


def test_palette_has_no_shadow_or_gradient_tokens():
    src = inspect.getsource(theme)
    assert "gradient" not in src.lower()
    assert "shadow" not in src.lower()


# ---------- 容量语义色（Signature）----------

def test_capacity_color_thresholds():
    p = theme.palette()
    assert theme.capacity_color(10.0) == p.success
    assert theme.capacity_color(69.9) == p.success
    assert theme.capacity_color(70.0) == p.warning
    assert theme.capacity_color(89.9) == p.warning
    assert theme.capacity_color(90.0) == p.danger
    assert theme.capacity_color(99.0) == p.danger


# ---------- 建议列：推荐与风险合并成一格 ----------

def test_advice_cell_merges_recommendation_and_risk():
    assert AppWindow._advice_cell(_item(recommendation=Recommendation.RECOMMEND)) == "● 建议删除"
    assert AppWindow._advice_cell(_item(recommendation=Recommendation.OPTIONAL)) == "◐ 可选"
    assert AppWindow._advice_cell(_item(recommendation=Recommendation.NOT_RECOMMENDED)) == "○ 不建议"


def test_advice_cell_marks_report_only_rows():
    item = _item(recommendation=Recommendation.OPTIONAL, deletable=False)
    assert AppWindow._advice_cell(item) == "— 仅报告"


def test_advice_badge_is_never_color_only():
    """a11y 底线：每个语义都要有符号 + 文案，不能只靠颜色。"""
    for key, (glyph, label, _role) in theme.ADVICE_BADGE.items():
        assert glyph and label, key


# ---------- 行底色 ----------

def test_row_tag_by_recommendation():
    assert AppWindow._row_tag(_item(recommendation=Recommendation.RECOMMEND)) == "safe"
    assert AppWindow._row_tag(_item(recommendation=Recommendation.OPTIONAL)) == "optional"
    assert AppWindow._row_tag(_item(recommendation=Recommendation.NOT_RECOMMENDED)) == "danger"


def test_row_tag_weakens_report_only_rows():
    assert AppWindow._row_tag(_item(deletable=False)) == "report"
    assert "report" in theme.row_tag_styles()
    assert "safe" in theme.row_tag_styles()


# ---------- 排序方向 ----------

def _sortable_window(items, key):
    window = object.__new__(AppWindow)
    window.items = items
    window._sort_by = key
    window._sort_desc = False
    window._refresh_heading_labels = lambda: None
    return window


def test_advice_sort_puts_safest_first_and_report_last():
    items = [
        _item(id="report", recommendation=Recommendation.OPTIONAL, deletable=False),
        _item(id="no", recommendation=Recommendation.NOT_RECOMMENDED),
        _item(id="maybe", recommendation=Recommendation.OPTIONAL),
        _item(id="yes", recommendation=Recommendation.RECOMMEND),
    ]
    window = _sortable_window(items, "advice")
    AppWindow._apply_sort(window)
    assert [i.id for i in window.items] == ["yes", "maybe", "no", "report"]


def test_size_sort_is_descending_by_default():
    items = [_item(id="small", size_bytes=1), _item(id="big", size_bytes=999)]
    window = _sortable_window(items, "size")
    window._sort_desc = True
    AppWindow._apply_sort(window)
    assert [i.id for i in window.items] == ["big", "small"]


# ---------- 空态与表格互斥 ----------

class _Stub:
    def __init__(self):
        self.calls = []

    def grid(self, **kw):
        self.calls.append(("grid", kw))

    def grid_forget(self):
        self.calls.append(("grid_forget", {}))


def test_show_table_hides_empty_state():
    window = object.__new__(AppWindow)
    window.table_frame = _Stub()
    window.empty_frame = _Stub()
    AppWindow._show_table(window)
    assert ("grid_forget", {}) in window.empty_frame.calls
    assert any(c[0] == "grid" for c in window.table_frame.calls)


def test_show_empty_state_hides_table():
    window = object.__new__(AppWindow)
    window.table_frame = _Stub()
    window.empty_frame = _Stub()
    AppWindow._show_empty_state(window)
    assert ("grid_forget", {}) in window.table_frame.calls
    assert any(c[0] == "grid" for c in window.empty_frame.calls)


def test_view_switchers_tolerate_partially_built_window():
    """object.__new__ 造出来的实例没有 tk 句柄，不能因为 hasattr 递归爆栈。"""
    window = object.__new__(AppWindow)
    AppWindow._show_table(window)
    AppWindow._show_empty_state(window)
    AppWindow._apply_row_tags(window)
    AppWindow._refresh_capacity_bar(window)
