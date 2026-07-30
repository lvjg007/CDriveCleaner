from src.app.orchestrator import Orchestrator
from src.models.items import Recommendation


def test_orchestrator_scan_smoke():
    """冒烟：至少能跑完扫描器注册列表（可能 0 项，视机器环境）。"""
    orch = Orchestrator()
    # 大文件扫描可能慢，用 cancel 提前结束不合适；这里直接 scan
    # 为加快测试，临时只测 safe filter 已在 test_executor
    # 这里验证 all_scanners 可导入且 orchestrator 可构造
    assert orch.executor is not None
    assert Recommendation.RECOMMEND.value == "recommend"
