from src.models.items import CleanItem, Recommendation, Risk, format_size


def test_format_size():
    assert format_size(500) == "500 B"
    assert "KB" in format_size(2048)
    assert "MB" in format_size(5 * 1024 * 1024)


def test_clean_item_make_recommend_selected():
    item = CleanItem.make(
        id="t1",
        category="临时文件",
        path=r"C:\Temp\x",
        size_bytes=100,
        recommendation=Recommendation.RECOMMEND,
        reason="可安全清理",
    )
    assert item.selected is True
    assert item.risk == Risk.LOW


def test_clean_item_make_not_recommended_unselected():
    item = CleanItem.make(
        id="t2",
        category="大文件",
        path=r"C:\big.bin",
        size_bytes=10**9,
        recommendation=Recommendation.NOT_RECOMMENDED,
        reason="需人工确认",
    )
    assert item.selected is False
    assert item.risk == Risk.HIGH
