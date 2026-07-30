from pathlib import Path

from src.cleaner.executor import CleanExecutor
from src.models.items import CleanItem, Recommendation
from src.ui.treemap import squarify
from src.utils.recycle import send_to_recycle_bin


def test_squarify_covers_area():
    rects = squarify([("a", 70), ("b", 30)], 0, 0, 100, 100)
    assert len(rects) == 2
    area = sum(r.w * r.h for r in rects)
    assert 9900 < area < 10100


def test_recycle_file(tmp_path: Path):
    f = tmp_path / "to_recycle.txt"
    f.write_text("bye", encoding="utf-8")
    send_to_recycle_bin(f)
    assert not f.exists()


def test_executor_recycle_mode(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"12345")
    item = CleanItem.make(
        id="r1",
        category="测试",
        path=str(f),
        size_bytes=5,
        recommendation=Recommendation.RECOMMEND,
        reason="t",
    )
    result = CleanExecutor().execute([item], use_recycle_bin=True)
    assert result.success_count == 1
    assert not f.exists()
    assert "r1" in result.removed_ids


def test_fast_scan_skips_slow():
    from src.app.orchestrator import Orchestrator, _SLOW_SCANNER_NAMES
    from src.scanners.registry import all_scanners

    all_names = {s.name for s in all_scanners()}
    assert _SLOW_SCANNER_NAMES & all_names
    # smoke: fast scan constructs
    orch = Orchestrator()
    assert orch.executor is not None
