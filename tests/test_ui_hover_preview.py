"""悬停预览的定位约束：弹框是 topmost 独立窗口，一旦盖住鼠标指针就会吃掉点击。"""
from src.ui.app_window import (
    _PREVIEW_CLIP,
    _PREVIEW_SKIP_COLUMNS,
    AppWindow,
    compute_preview_position,
)

SW, SH = 1920, 1080
W, H = 457, 155


def _covers(rect, x, y):
    px, py = rect
    return px <= x <= px + W and py <= y <= py + H


def test_never_covers_pointer_across_screen():
    for x in range(40, SW, 40):
        for y in range(40, SH, 40):
            rect = compute_preview_position(x, y, W, H, SW, SH)
            assert not _covers(rect, x, y), f"弹框压住指针 cursor=({x},{y}) rect={rect}"


def test_stays_on_screen_in_common_positions():
    for x, y in ((100, 100), (900, 500), (600, 300)):
        px, py = compute_preview_position(x, y, W, H, SW, SH)
        assert 0 <= px and px + W <= SW
        assert 0 <= py and py + H <= SH


def test_prefers_bottom_right_of_pointer():
    px, py = compute_preview_position(300, 300, W, H, SW, SH)
    assert px > 300 and py > 300


def test_flips_away_near_bottom_right_corner():
    px, py = compute_preview_position(1900, 1070, W, H, SW, SH)
    assert not _covers((px, py), 1900, 1070)
    assert py < 1070


def test_pointer_outside_rect_is_the_hard_guarantee():
    # 极端：弹框比剩余空间还大时，也必须垂直让开指针
    px, py = compute_preview_position(960, 540, 1800, 1000, SW, SH)
    assert py + 1000 <= 540 or py >= 540


def test_checkbox_column_has_no_hover_preview():
    assert "selected" in _PREVIEW_SKIP_COLUMNS


def test_preview_text_is_clipped_and_compact():
    from src.models.items import CleanItem, Recommendation

    item = CleanItem.make(
        id="x",
        category="开发缓存",
        path="C:\\" + "very-long-folder\\" * 40 + "file.dat",
        size_bytes=2048,
        recommendation=Recommendation.RECOMMEND,
        reason="原因" * 200,
        detail="说明" * 200,
    )
    app = object.__new__(AppWindow)
    text = AppWindow._preview_text(app, item)
    lines = text.split("\n")
    assert len(lines) <= 4
    assert "…" in text
    assert len(lines[-1]) <= _PREVIEW_CLIP["path"] + 4


def test_press_hides_preview_and_click_still_toggles():
    from src.models.items import CleanItem, Recommendation

    class _Label:
        def configure(self, **_kwargs):
            pass

    class _Tree:
        def __init__(self):
            self.values = {"row": ["□ 未选"]}

        def item(self, iid, *args, **kwargs):
            if "values" in kwargs:
                self.values[iid] = list(kwargs["values"])
            return tuple(self.values[iid])

    app = object.__new__(AppWindow)
    app._hover_mute_until = 0.0
    app._hover_iid = "row"
    app._hover_job = None
    app._preview = None
    app._preview_visible = True
    app._busy = False
    app._scan_cancelled = False
    app.tree = _Tree()
    app.progress_label = _Label()
    item = CleanItem.make(
        id="row",
        category="临时文件",
        path="C:\\Temp\\a.tmp",
        size_bytes=10,
        recommendation=Recommendation.RECOMMEND,
        reason="r",
    )
    item.selected = False
    app._item_by_iid = {"row": item}
    app._update_selected_sum = lambda: None

    app.on_tree_press()
    assert app._preview_visible is False

    app._toggle_iid("row")
    assert item.selected is True
    assert app.tree.values["row"][0] == "✔ 已选"


def test_non_deletable_row_reports_hint_instead_of_silence():
    from src.models.items import CleanItem, Recommendation

    class _Label:
        def __init__(self):
            self.text = ""

        def configure(self, **kwargs):
            self.text = kwargs.get("text", self.text)

    app = object.__new__(AppWindow)
    app._scan_cancelled = False
    app.progress_label = _Label()
    app._update_selected_sum = lambda: None
    item = CleanItem.make(
        id="rep",
        category="扩展名占用汇总",
        path="C:\\sample.dat",
        size_bytes=1,
        recommendation=Recommendation.OPTIONAL,
        reason="仅报告",
        deletable=False,
    )
    app._item_by_iid = {"rep": item}

    app._toggle_iid("rep")

    assert item.selected is False
    assert "不可勾选" in app.progress_label.text
