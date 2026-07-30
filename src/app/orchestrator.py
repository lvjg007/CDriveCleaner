from __future__ import annotations

from typing import Callable

from src.cleaner.executor import CleanExecutor
from src.models.items import CleanItem, CleanResult, Recommendation
from src.scanners.registry import all_scanners, scanner_category_order


ProgressCb = Callable[[str, float, int, int], None]

# 快速扫描跳过的慢项（真正 MFT 解析后续再做；先用实用加速）
_SLOW_SCANNER_NAMES = {
    "重复文件",
    "扩展名占用汇总",
    "大文件扫描",
    "下载的视频图片音频",
    "下载目录长期未访问",
    "微信（可定制）",
}


class Orchestrator:
    def __init__(self) -> None:
        self.executor = CleanExecutor()
        self.last_items: list[CleanItem] = []
        self.last_category_stats: dict[str, int] = {}

    def scan(
        self,
        progress: ProgressCb | None = None,
        cancel_flag: dict | None = None,
        *,
        fast: bool = False,
    ) -> list[CleanItem]:
        scanners = all_scanners()
        if fast:
            scanners = [s for s in scanners if s.name not in _SLOW_SCANNER_NAMES]
        items: list[CleanItem] = []
        total = len(scanners)
        order = scanner_category_order()
        stats: dict[str, int] = {name: 0 for name in order}

        for idx, scanner in enumerate(scanners):
            if cancel_flag and cancel_flag.get("cancel"):
                break

            def _inner(name: str, frac: float, _idx=idx, _total=total) -> None:
                if progress:
                    overall = (_idx + max(0.0, min(1.0, frac))) / max(_total, 1)
                    progress(name, overall, _idx + 1, _total)

            if progress:
                progress(f"正在扫描: {scanner.name}", idx / max(total, 1), idx + 1, total)
            part = scanner.scan(cancel_flag=cancel_flag, progress=_inner)
            stats[scanner.name] = len(part)
            items.extend(part)
            if progress:
                progress(
                    f"完成: {scanner.name}（{len(part)} 项）",
                    (idx + 1) / max(total, 1),
                    idx + 1,
                    total,
                )

        dedup: dict[str, CleanItem] = {}
        for it in items:
            dedup[it.id] = it
        self.last_items = list(dedup.values())
        cat_rank = {name: i for i, name in enumerate(order)}
        self.last_items.sort(
            key=lambda x: (cat_rank.get(x.category, 999), -x.size_bytes)
        )
        self.last_category_stats = stats
        return self.last_items

    @staticmethod
    def items_for_safe_clean(items: list[CleanItem]) -> list[CleanItem]:
        return [i for i in items if i.recommendation == Recommendation.RECOMMEND]

    @staticmethod
    def items_for_deep_clean(items: list[CleanItem]) -> list[CleanItem]:
        return [
            i
            for i in items
            if i.recommendation in (Recommendation.RECOMMEND, Recommendation.OPTIONAL)
        ]

    @staticmethod
    def selected_items(items: list[CleanItem]) -> list[CleanItem]:
        return [i for i in items if i.selected]

    def clean(
        self,
        items: list[CleanItem],
        cancel_flag: dict | None = None,
        *,
        dry_run: bool = False,
        use_recycle_bin: bool = False,
    ) -> CleanResult:
        return self.executor.execute(
            items,
            cancel_flag=cancel_flag,
            dry_run=dry_run,
            use_recycle_bin=use_recycle_bin,
        )

    @staticmethod
    def needs_second_confirm(items: list[CleanItem]) -> bool:
        return any(
            i.recommendation in (Recommendation.OPTIONAL, Recommendation.NOT_RECOMMENDED)
            for i in items
        )
