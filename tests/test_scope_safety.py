from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.app_junk import AppJunkScanner
from src.scanners.dev_cache import DevCacheScanner
from src.scanners.office_comms import OfficeCommsScanner
from src.scanners.system_extras import SystemExtrasScanner
from src.scanners.media_downloads import MediaDownloadsScanner
from src.scanners.recycle_bin import RecycleBinScanner
from src.scanners.wechat import WeChatScanner
from src.ui.app_window import AppWindow
from src.utils import drives

#: 条目 id 现在带盘符（同一个扫描器在多个盘上跑时不能撞 id）。
#: 测试用当前目标盘拼 id，不写死 C: —— 用户目录可能被搬到别的盘。
_C = drives.target_drive()


def _directory_with_file(root: Path) -> Path:
    root.mkdir()
    (root / "payload.bin").write_bytes(b"payload")
    return root


def test_app_junk_reports_whole_app_roots_without_deleting(monkeypatch, tmp_path: Path):
    unsafe = _directory_with_file(tmp_path / "steam")
    safe = _directory_with_file(tmp_path / "cache")
    scanner = AppJunkScanner()
    monkeypatch.setattr(
        scanner,
        "_fixed_targets",
        lambda: [
            ("Steam 本地数据", unsafe, Recommendation.OPTIONAL, "Steam root"),
            ("Discord Cache", safe, Recommendation.RECOMMEND, "cache"),
        ],
    )
    items = scanner.scan()
    by_label = {item.id.rsplit(":", 1)[-1]: item for item in items}
    assert by_label["Steam 本地数据"].deletable is False
    assert by_label["Steam 本地数据"].recommendation == Recommendation.NOT_RECOMMENDED
    assert by_label["Discord Cache"].deletable is True


def test_dev_cache_reports_jetbrains_and_docker_roots(monkeypatch, tmp_path: Path):
    jetbrains = _directory_with_file(tmp_path / "jetbrains")
    npm = _directory_with_file(tmp_path / "npm")
    maven = _directory_with_file(tmp_path / "maven")
    scanner = DevCacheScanner()
    monkeypatch.setattr(
        scanner,
        "_candidates",
        lambda: [("JetBrains caches", str(jetbrains)), ("npm cache", str(npm)), ("Maven repo", str(maven))],
    )
    items = scanner.scan()
    by_id = {item.id: item for item in items}
    # 整目录混着配置的只能展示
    assert by_id["dev:JetBrains caches"].deletable is False
    assert by_id["dev:npm cache"].deletable is True
    # 标准包仓库允许勾选，但降级为「可选」并默认不勾 —— 删除只意味着重新下载
    assert by_id["dev:Maven repo"].deletable is True
    assert by_id["dev:Maven repo"].recommendation == Recommendation.OPTIONAL
    assert by_id["dev:Maven repo"].selected is False


def test_office_scanner_reports_user_data_directories(monkeypatch, tmp_path: Path):
    spotify = _directory_with_file(tmp_path / "spotify")
    teams = _directory_with_file(tmp_path / "teams")
    scanner = OfficeCommsScanner()
    monkeypatch.setattr(
        scanner,
        "_targets",
        lambda: [
            ("Spotify Data", spotify, Recommendation.OPTIONAL, "offline data"),
            ("Teams Classic Cache", teams, Recommendation.RECOMMEND, "cache"),
        ],
    )
    items = scanner.scan()
    by_id = {item.id: item for item in items}
    spotify_item = next(item for item in items if item.id.startswith("office:Spotify Data:"))
    teams_item = next(item for item in items if item.id.startswith("office:Teams Classic Cache:"))
    assert spotify_item.deletable is False
    assert spotify_item.recommendation == Recommendation.NOT_RECOMMENDED
    assert teams_item.deletable is True


def test_system_extras_reports_system_data_roots(monkeypatch, tmp_path: Path):
    font_cache = _directory_with_file(tmp_path / "fonts")
    crash = _directory_with_file(tmp_path / "crash")
    scanner = SystemExtrasScanner()
    monkeypatch.setattr(
        scanner,
        "_targets",
        lambda drive: [
            ("FontCache", font_cache, Recommendation.OPTIONAL, "fonts", False),
            ("崩溃转储", crash, Recommendation.RECOMMEND, "dumps", False),
        ],
    )
    items = scanner.scan()
    by_id = {item.id: item for item in items}
    assert by_id[f"extra:{_C}:FontCache"].deletable is False
    assert by_id[f"extra:{_C}:崩溃转储"].deletable is True


def test_system_extras_does_not_offer_broad_system_roots_as_deletable(monkeypatch, tmp_path: Path):
    logs = _directory_with_file(tmp_path / "logs")
    cache = _directory_with_file(tmp_path / "cache")
    scanner = SystemExtrasScanner()
    monkeypatch.setattr(
        scanner,
        "_targets",
        lambda drive: [
            ("Windows 日志", logs, Recommendation.OPTIONAL, "logs", True),
            ("DirectX 着色器缓存", cache, Recommendation.RECOMMEND, "shader", False),
        ],
    )
    items = scanner.scan()
    by_id = {item.id: item for item in items}
    assert by_id[f"extra:{_C}:Windows 日志"].deletable is False
    assert by_id[f"extra:{_C}:DirectX 着色器缓存"].deletable is True


def test_media_files_never_enter_safe_clean(monkeypatch, tmp_path: Path):
    media = _directory_with_file(tmp_path / "Downloads")
    video = media / "movie.mp4"
    video.write_bytes(b"x" * (20 * 1024 * 1024))
    scanner = MediaDownloadsScanner()
    monkeypatch.setattr(scanner, "_roots", lambda: [media])
    items = scanner.scan()
    assert items and items[0].recommendation == Recommendation.OPTIONAL
    assert items[0].selected is False


def test_recycle_bin_is_not_safe_clean(monkeypatch, tmp_path: Path):
    scanner = RecycleBinScanner()
    root = tmp_path / "recycle"
    root.mkdir()
    (root / "item.bin").write_bytes(b"x")
    monkeypatch.setattr(scanner, "scan", lambda cancel_flag=None, progress=None: [
        CleanItem.make(
            id="recycle", category="回收站", path=str(root), size_bytes=1,
            recommendation=Recommendation.OPTIONAL, reason="recycle"
        )
    ])
    item = scanner.scan()[0]
    assert item.selected is False


def test_wechat_chat_database_is_report_only(monkeypatch, tmp_path: Path):
    scanner = WeChatScanner()
    account = tmp_path / "account"
    account.mkdir()
    db = account / "Msg"
    db.mkdir()
    (db / "messages.db").write_bytes(b"db")
    monkeypatch.setattr(scanner, "_account_dirs", lambda: [account])
    monkeypatch.setattr("src.scanners.wechat.discover_chat_id_map", lambda *_args, **_kwargs: {})
    items = scanner.scan()
    databases = [item for item in items if "聊天记录库" in item.detail]
    assert databases and databases[0].deletable is False


def test_ui_selection_never_selects_report_items():
    deletable = CleanItem.make(
        id="clean",
        category="缓存",
        path="clean",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="cache",
    )
    report = CleanItem.make(
        id="report",
        category="报告",
        path="report",
        size_bytes=1,
        recommendation=Recommendation.OPTIONAL,
        reason="report",
        deletable=False,
        selected=True,
    )
    window = object.__new__(AppWindow)
    window.items = [deletable, report]
    window._filter_category = "全部"
    window._scan_cancelled = False
    window._reload_table = lambda: None
    window._report_selection_scope = lambda: None
    AppWindow._apply_selection(window, lambda _item: True)
    assert deletable.selected is True
    assert report.selected is False


def _selectable_window(items, category: str):
    """搭一个只带选择逻辑所需属性的半构造窗口。

    故意不桩掉 _report_selection_scope —— 它内部对半构造实例有 __dict__ 护栏，
    正好顺带验证那条护栏有效（否则会撞上 tkinter 的 Misc.__getattr__ 递归）。
    """
    window = object.__new__(AppWindow)
    window.items = items
    window._filter_category = category
    window._scan_cancelled = False
    window._reload_table = lambda: None
    return window


def _item_in(category: str, item_id: str, *, recommendation=Recommendation.RECOMMEND):
    item = CleanItem.make(
        id=item_id,
        category=category,
        path=f"C:\\x\\{item_id}",
        size_bytes=1,
        recommendation=recommendation,
        reason="r",
    )
    # make() 会把 RECOMMEND 项默认勾上，测试需要干净的初始状态
    item.selected = False
    return item


def test_apply_selection_only_touches_the_filtered_category():
    items = [
        _item_in("AI · Codex", "codex-safe"),
        _item_in("AI · Codex", "codex-opt", recommendation=Recommendation.OPTIONAL),
        _item_in("AI · Cursor", "cursor-safe"),
        _item_in("系统临时文件", "temp-safe"),
    ]
    window = _selectable_window(items, "AI · Codex")
    AppWindow._apply_selection(window, lambda i: i.recommendation == Recommendation.RECOMMEND)
    picked = {i.id for i in items if i.selected}
    assert picked == {"codex-safe"}


def test_apply_selection_with_no_filter_still_covers_everything():
    items = [
        _item_in("AI · Codex", "codex-safe"),
        _item_in("AI · Cursor", "cursor-safe"),
        _item_in("系统临时文件", "temp-safe"),
    ]
    window = _selectable_window(items, "全部")
    AppWindow._apply_selection(window, lambda i: i.recommendation == Recommendation.RECOMMEND)
    assert {i.id for i in items if i.selected} == {"codex-safe", "cursor-safe", "temp-safe"}


def test_select_none_clears_only_the_filtered_category():
    items = [
        _item_in("AI · Codex", "codex-safe"),
        _item_in("AI · Cursor", "cursor-safe"),
    ]
    for i in items:
        i.selected = True
    window = _selectable_window(items, "AI · Codex")
    AppWindow.select_none(window)
    assert [i.id for i in items if i.selected] == ["cursor-safe"]


def test_select_invert_only_touches_the_filtered_category():
    items = [
        _item_in("AI · Codex", "codex-safe"),
        _item_in("AI · Cursor", "cursor-safe"),
    ]
    window = _selectable_window(items, "AI · Cursor")
    AppWindow.select_invert(window)
    assert items[0].selected is False     # 不在筛选内，不该被翻动
    assert items[1].selected is True


def test_selection_button_labels_follow_the_filter():
    """标签不能写「全选」却只选一类 —— 作用域变了文案就得跟着变。"""

    class _Btn:
        def __init__(self):
            self.text = ""

        def configure(self, **kw):
            self.text = kw.get("text", self.text)

    window = object.__new__(AppWindow)
    buttons = {n: _Btn() for n in ("btn_sel_reco", "btn_sel_opt", "btn_sel_none", "btn_sel_inv")}
    for name, btn in buttons.items():
        setattr(window, name, btn)

    window._filter_category = "AI · Codex"
    AppWindow._sync_selection_scope(window)
    assert buttons["btn_sel_reco"].text == "本类「建议」"
    assert buttons["btn_sel_opt"].text == "本类「建议+可选」"
    assert buttons["btn_sel_none"].text == "本类不选"
    assert buttons["btn_sel_inv"].text == "本类反选"

    window._filter_category = "全部"
    AppWindow._sync_selection_scope(window)
    assert buttons["btn_sel_reco"].text == "全选「建议」"
    assert buttons["btn_sel_opt"].text == "全选「建议+可选」"
    assert buttons["btn_sel_none"].text == "全不选"
    assert buttons["btn_sel_inv"].text == "反选"


def test_cancelled_scan_keeps_review_actions_but_disables_clean_actions():
    class Widget:
        def __init__(self):
            self.states = []

        def configure(self, **kwargs):
            if "state" in kwargs:
                self.states.append(kwargs["state"])

    window = object.__new__(AppWindow)
    window.items = [CleanItem.make(
        id="item",
        category="缓存",
        path="item",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="cache",
    )]
    window._scan_cancelled = True
    window._busy = False
    for name in (
        "btn_scan", "btn_safe", "btn_deep", "btn_selected", "btn_dry", "btn_export", "btn_treemap",
        "btn_sel_reco", "btn_sel_opt", "btn_sel_none", "btn_sel_inv", "btn_sort_size", "filter_box",
        "btn_cancel", "chk_fast", "chk_recycle", "drive_box",
    ):
        setattr(window, name, Widget())
    AppWindow._set_busy(window, False)
    assert window.btn_safe.states[-1] == "disabled"
    assert window.btn_deep.states[-1] == "disabled"
    assert window.btn_selected.states[-1] == "disabled"
    assert window.btn_dry.states[-1] == "disabled"
    # 空闲时盘符选择器要可用，否则用户切不了盘
    assert window.drive_box.states[-1] == "normal"
    assert window.btn_export.states[-1] == "normal"
    assert window.btn_treemap.states[-1] == "normal"
    assert window.btn_sort_size.states[-1] == "normal"
    assert window.filter_box.states[-1] == "normal"
    assert window.btn_sel_reco.states[-1] == "disabled"
    assert window.btn_sel_opt.states[-1] == "disabled"


def test_cancelled_scan_ignores_keyboard_selection():
    item = CleanItem.make(
        id="item",
        category="缓存",
        path="item",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="cache",
    )
    window = object.__new__(AppWindow)
    window.items = [item]
    window._scan_cancelled = True
    window._busy = False
    window._item_by_iid = {item.id: item}
    assert AppWindow.on_space_toggle(window) == "break"
    assert item.selected is True


def test_ui_filter_sort_and_row_toggle_keep_item_state():
    first = CleanItem.make(
        id="small",
        category="缓存",
        path="small",
        size_bytes=1,
        recommendation=Recommendation.RECOMMEND,
        reason="small",
    )
    second = CleanItem.make(
        id="large",
        category="日志",
        path="large",
        size_bytes=10,
        recommendation=Recommendation.RECOMMEND,
        reason="large",
    )
    window = object.__new__(AppWindow)
    window.items = [first, second]
    window._filter_category = "日志"
    assert AppWindow._visible_items(window) == [second]
    window._filter_category = "全部"
    window._sort_by = "size"
    window._sort_desc = True
    window._refresh_heading_labels = lambda: None
    AppWindow._apply_sort(window)
    assert [item.id for item in window.items] == ["large", "small"]

    class Tree:
        def __init__(self):
            self.values = {"small": ["□ 未选"]}

        def item(self, iid, option=None, **kwargs):
            if "values" in kwargs:
                self.values[iid] = kwargs["values"]
            return self.values[iid]

    window._busy = False
    window._scan_cancelled = False
    window._item_by_iid = {first.id: first}
    window.tree = Tree()
    window._update_selected_sum = lambda: None
    AppWindow._toggle_iid(window, first.id)
    assert first.selected is False


def test_scan_done_exposes_partial_result_status():
    class Widget:
        def __init__(self):
            self.text = ""

        def configure(self, **kwargs):
            self.text = kwargs.get("text", self.text)

        def set(self, *_args):
            return None

    class Orch:
        last_scan_cancelled = False
        last_scan_fast = False
        last_scan_partial_categories = ["大文件扫描"]
        last_category_stats = {"大文件扫描": 2}
        # 多盘模式下 _scan_done 会读这两个字段（跨盘过滤统计 + 被跳过的扫描器）
        last_skipped_scanners = []
        last_drive = _C

    window = object.__new__(AppWindow)
    window.orch = Orch()
    window.items = []
    window._scan_cancelled = False
    window._scan_partial_categories = []
    window._sort_by = "size"
    window._sort_desc = True
    window._target_drive = _C
    window.filter_box = Widget()
    window.progress = Widget()
    window.progress_label = Widget()
    window._apply_sort = lambda: None
    window._reload_table = lambda: None
    window._set_busy = lambda _busy: None
    window._refresh_disk_status = lambda: None
    AppWindow._scan_done(window, [])
    assert "部分结果" in window.progress_label.text
    assert "大文件扫描" in window.progress_label.text


def test_selected_summary_uses_effective_parent_targets(tmp_path: Path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    parent_item = CleanItem.make(
        id="parent",
        category="缓存",
        path=str(parent),
        size_bytes=100,
        recommendation=Recommendation.RECOMMEND,
        reason="parent",
    )
    child_item = CleanItem.make(
        id="child",
        category="缓存",
        path=str(child),
        size_bytes=40,
        recommendation=Recommendation.RECOMMEND,
        reason="child",
    )
    class Label:
        def __init__(self):
            self.text = ""

        def configure(self, **kwargs):
            self.text = kwargs["text"]

    window = object.__new__(AppWindow)
    window.items = [parent_item, child_item]
    window.summary_label = Label()
    AppWindow._update_selected_sum(window)
    assert "100 B" in window.summary_label.text
