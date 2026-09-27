"""AI 工具数据扫描器的分级与安全边界测试。"""
from pathlib import Path

from src.models.items import Recommendation
from src.scanners import ai_tools
from src.scanners.ai_tools import AiToolsScanner, _Target
from src.scanners.registry import scanner_category_order
from src.utils.paths import is_deletion_protected

_MB = 1024 * 1024


def _dir_with_size(root: Path, size: int) -> Path:
    """造一个目录，内含一个指定大小的文件（要超过 _MIN_BYTES 才会被产出）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "payload.bin").write_bytes(b"\0" * size)
    return root


def _scan_with(monkeypatch, targets: list[_Target]) -> dict[str, object]:
    scanner = AiToolsScanner()
    monkeypatch.setattr(scanner, "_targets", lambda: targets)
    return {item.id: item for item in scanner.scan()}


def test_ai_tool_category_is_registered():
    assert "AI 工具数据" in scanner_category_order()


def test_logs_are_recommended_and_preselected(monkeypatch, tmp_path: Path):
    logs = _dir_with_size(tmp_path / "logs", 2 * _MB)
    by_id = _scan_with(
        monkeypatch,
        [_Target("某工具日志", logs, ai_tools._SAFE, "运行日志")],
    )
    item = by_id["ai:某工具日志"]
    assert item.recommendation == Recommendation.RECOMMEND
    assert item.deletable is True
    assert item.selected is True


def test_session_history_is_optional_and_not_preselected(monkeypatch, tmp_path: Path):
    sessions = _dir_with_size(tmp_path / "sessions", 4 * _MB)
    by_id = _scan_with(
        monkeypatch,
        [_Target("某工具会话历史", sessions, ai_tools._OPTIONAL, "历史会话，删除后无法恢复")],
    )
    item = by_id["ai:某工具会话历史"]
    assert item.recommendation == Recommendation.OPTIONAL
    assert item.deletable is True
    # 含用户内容的东西不能被默认勾上
    assert item.selected is False


def test_live_state_database_is_selectable_but_discouraged(monkeypatch, tmp_path: Path):
    """分层只表达风险，不剥夺选择权：不建议删，但仍可勾选。"""
    db = tmp_path / "state.vscdb"
    db.write_bytes(b"\0" * (3 * _MB))
    by_id = _scan_with(
        monkeypatch,
        [_Target("某编辑器全局状态库", db, ai_tools._CAUTION, "活跃状态库，删了会丢全部状态")],
    )
    item = by_id["ai:某编辑器全局状态库"]
    assert item.recommendation == Recommendation.NOT_RECOMMENDED
    assert item.deletable is True
    # 但默认不能勾上
    assert item.selected is False
    # 代价必须写在理由里，用户勾选前就能看到
    assert "不建议删除" in item.reason


def test_every_tier_stays_selectable(monkeypatch, tmp_path: Path):
    """三层都必须可勾选 —— 这是「由我来确认删除和保留」的产品承诺。"""
    targets = [
        _Target("甲", _dir_with_size(tmp_path / "a", 2 * _MB), ai_tools._SAFE, "日志"),
        _Target("乙", _dir_with_size(tmp_path / "b", 2 * _MB), ai_tools._OPTIONAL, "历史"),
        _Target("丙", _dir_with_size(tmp_path / "c", 2 * _MB), ai_tools._CAUTION, "状态库"),
    ]
    by_id = _scan_with(monkeypatch, targets)
    assert len(by_id) == 3
    assert all(item.deletable for item in by_id.values())
    # 只有建议删除层默认勾选
    assert [i.id for i in by_id.values() if i.selected] == ["ai:甲"]


def test_credential_files_are_never_emitted(monkeypatch, tmp_path: Path):
    """凭据类路径即便被写进目标清单，也必须被兜底拦下。"""
    targets = []
    for name in ("oauth_creds.json", ".credentials.json", "settings.json", "installation_id", ".env"):
        f = tmp_path / name
        f.write_bytes(b"\0" * (2 * _MB))
        targets.append(_Target(f"误加的 {name}", f, ai_tools._SAFE, "不该出现"))
    by_id = _scan_with(monkeypatch, targets)
    assert by_id == {}


def test_tiny_targets_are_skipped(monkeypatch, tmp_path: Path):
    tiny = _dir_with_size(tmp_path / "tiny", 1000)
    by_id = _scan_with(
        monkeypatch,
        [_Target("过小的缓存", tiny, ai_tools._SAFE, "只有 1 KB")],
    )
    assert by_id == {}


def test_glob_expansion_keeps_big_files_only(monkeypatch, tmp_path: Path):
    root = tmp_path / "codex"
    root.mkdir()
    (root / "big.sqlite.bak-old").write_bytes(b"\0" * (2 * _MB))
    (root / "small.toml.bak-old").write_bytes(b"\0" * 100)
    by_id = _scan_with(
        monkeypatch,
        [_Target("旧备份残留", root, ai_tools._SAFE, "历史 .bak", pattern="*.bak*")],
    )
    assert list(by_id) == ["ai:旧备份残留:big.sqlite.bak-old"]


def test_cancel_stops_scan(monkeypatch, tmp_path: Path):
    root = _dir_with_size(tmp_path / "logs", 2 * _MB)
    scanner = AiToolsScanner()
    monkeypatch.setattr(scanner, "_targets", lambda: [_Target("日志", root, ai_tools._SAFE, "x")])
    assert scanner.scan(cancel_flag={"cancel": True}) == []


def test_budget_exhaustion_marks_partial(monkeypatch, tmp_path: Path):
    root = _dir_with_size(tmp_path / "logs", 2 * _MB)
    scanner = AiToolsScanner()
    monkeypatch.setattr(scanner, "_targets", lambda: [_Target("日志", root, ai_tools._SAFE, "x")])
    monkeypatch.setattr(ai_tools, "_TOTAL_BUDGET_SECONDS", -1.0)
    flag: dict = {}
    assert scanner.scan(cancel_flag=flag) == []
    assert "AI 工具数据" in flag["_scan_meta"]["partial_categories"]


def test_declared_targets_are_not_deletion_protected():
    """回归：目标路径若被 is_deletion_protected 拦下，用户勾了也会静默失败。

    只检查声明的目标，不做目录遍历，所以很快且与机器是否装了这些工具无关。
    """
    scanner = AiToolsScanner()
    blocked = [str(t.path) for t in scanner._targets() if is_deletion_protected(t.path)]
    assert blocked == [], f"以下目标会被保护规则误拦：{blocked}"


def test_declared_targets_avoid_credentials():
    scanner = AiToolsScanner()
    offenders = [
        str(t.path) for t in scanner._targets() if scanner._is_never_touch(t.path)
    ]
    assert offenders == [], f"目标清单里混入了凭据类路径：{offenders}"


def test_target_labels_and_ids_are_unique():
    scanner = AiToolsScanner()
    labels = [t.label for t in scanner._targets()]
    assert len(labels) == len(set(labels))


# ---------- 按 AI 客户端分列（界面上逐个客户端筛选/勾选）----------

def test_real_targets_are_split_into_client_groups():
    """回归：不能把 40 多项全塞进一个「AI 工具数据」桶，必须按客户端拆开。"""
    scanner = AiToolsScanner()
    groups = [t.group for t in scanner._targets()]
    assert "" not in groups, "有目标没打分组，会退回扫描器名"
    assert all(g.startswith(ai_tools._GROUP_PREFIX) for g in groups)
    distinct = set(groups)
    assert len(distinct) >= 8, f"客户端分组太少: {sorted(distinct)}"


def test_item_category_follows_its_group(monkeypatch, tmp_path: Path):
    targets = [
        _Target("甲日志", _dir_with_size(tmp_path / "a", 2 * _MB), ai_tools._SAFE, "日志", group="AI · 甲"),
        _Target("乙日志", _dir_with_size(tmp_path / "b", 2 * _MB), ai_tools._SAFE, "日志", group="AI · 乙"),
    ]
    by_id = _scan_with(monkeypatch, targets)
    assert by_id["ai:甲日志"].category == "AI · 甲"
    assert by_id["ai:乙日志"].category == "AI · 乙"


def test_missing_group_falls_back_to_scanner_name(monkeypatch, tmp_path: Path):
    """没打分组的目标仍要能正常产出，不能变成空分类。"""
    targets = [_Target("无分组", _dir_with_size(tmp_path / "c", 2 * _MB), ai_tools._SAFE, "日志")]
    by_id = _scan_with(monkeypatch, targets)
    assert by_id["ai:无分组"].category == "AI 工具数据"
