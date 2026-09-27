from __future__ import annotations

from typing import Callable

from src.cleaner.executor import CleanExecutor
from src.models.items import CleanItem, CleanResult, Recommendation, effective_clean_targets
from src.scanners.registry import all_scanners, scanner_category_order
from src.utils import drives
from src.utils.paths import canonical_path_key


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
        self.last_scan_cancelled = False
        self.last_scan_fast = False
        self.last_scan_partial_categories: list[str] = []
        #: 本次扫描的目标盘
        self.last_drive: str = drives.target_drive()
        #: 因盘范围不适用而被跳过的扫描器：``[(名称, 理由), ...]``
        self.last_skipped_scanners: list[tuple[str, str]] = []
        #: 被跨盘过滤丢掉的条目数（诊断用，正常应该是 0）
        self.last_cross_drive_dropped: int = 0

    def scanners_for(self, drive: str) -> tuple[list, list[tuple[str, str]]]:
        """按目标盘挑出该跑的扫描器，以及被跳过的那些和理由。

        这一步是「扫其它盘」的正确性核心。用户配置类扫描器读的是
        ``Path.home()``，用户目录只在一个盘上 —— 在 D 盘重跑它们
        会把 C 盘的结果再报一遍，属于**假重复**：用户以为在 D 盘发现了
        20 GB 垃圾，其实那 20 GB 全在 C 盘。
        """
        runnable: list = []
        skipped: list[tuple[str, str]] = []
        for scanner in all_scanners():
            if scanner.applies_to(drive):
                runnable.append(scanner)
            else:
                skipped.append((scanner.name, scanner.skip_reason(drive)))
        return runnable, skipped

    def scan(
        self,
        progress: ProgressCb | None = None,
        cancel_flag: dict | None = None,
        *,
        fast: bool = False,
        drive: str | None = None,
    ) -> list[CleanItem]:
        self.last_scan_fast = fast
        self.last_scan_cancelled = False
        target = drives.set_target_drive(drive) if drive else drives.target_drive()
        self.last_drive = target
        scan_flag = cancel_flag if cancel_flag is not None else {}
        scan_flag["_scan_meta"] = {"partial_categories": set()}
        scanners, skipped = self.scanners_for(target)
        self.last_skipped_scanners = skipped
        if fast:
            scanners = [s for s in scanners if s.name not in _SLOW_SCANNER_NAMES]
        items: list[CleanItem] = []
        total = len(scanners)
        order = scanner_category_order()
        stats: dict[str, int] = {name: 0 for name in order}
        cancelled = False
        dropped = 0

        for idx, scanner in enumerate(scanners):
            if scan_flag.get("cancel"):
                cancelled = True
                break
            scan_flag["_scan_current"] = scanner.name

            def _inner(name: str, frac: float, _idx=idx, _total=total) -> None:
                if progress:
                    overall = (_idx + max(0.0, min(1.0, frac))) / max(_total, 1)
                    progress(name, overall, _idx + 1, _total)

            if progress:
                progress(f"正在扫描: {scanner.name}", idx / max(total, 1), idx + 1, total)
            part = scanner.scan(cancel_flag=scan_flag, progress=_inner)
            # 只保留目标盘上的条目。跨盘展示要显式声明（cross_drive），
            # 而且 CleanItem.make 只对不可删除的报告项放行 ——
            # 可删除条目跨盘会让「在 D 盘勾选、实际删掉 C 盘文件」成为可能。
            kept = [it for it in part if it.cross_drive or not it.drive or it.drive == target]
            dropped += len(part) - len(kept)
            part = kept
            stats[scanner.name] = len(part)
            items.extend(part)
            if progress:
                progress(
                    f"完成: {scanner.name}（{len(part)} 项）",
                    (idx + 1) / max(total, 1),
                    idx + 1,
                    total,
                )

        self.last_scan_cancelled = cancelled or bool(scan_flag.get("cancel"))
        self.last_cross_drive_dropped = dropped
        meta = scan_flag.get("_scan_meta", {})
        self.last_scan_partial_categories = sorted(meta.get("partial_categories", set()))
        scan_flag.pop("_scan_current", None)

        by_id: dict[str, CleanItem] = {}
        for it in items:
            by_id[it.id] = it

        by_path: dict[str, CleanItem] = {}
        for it in by_id.values():
            key = canonical_path_key(it.path)
            current = by_path.get(key)
            if current is None or self._dedup_priority(it) > self._dedup_priority(current):
                by_path[key] = it
        self.last_items = list(by_path.values())
        cat_rank = {name: i for i, name in enumerate(order)}
        self.last_items.sort(
            key=lambda x: (cat_rank.get(x.category, 999), -x.size_bytes)
        )
        self.last_category_stats = stats
        return self.last_items

    @staticmethod
    def items_for_safe_clean(items: list[CleanItem]) -> list[CleanItem]:
        return effective_clean_targets(
            [i for i in items if i.deletable and i.recommendation == Recommendation.RECOMMEND]
        )

    @staticmethod
    def items_for_deep_clean(items: list[CleanItem]) -> list[CleanItem]:
        return effective_clean_targets(
            [
                i
                for i in items
                if i.deletable and i.recommendation in (Recommendation.RECOMMEND, Recommendation.OPTIONAL)
            ]
        )

    @staticmethod
    def selected_items(items: list[CleanItem]) -> list[CleanItem]:
        return effective_clean_targets([i for i in items if i.deletable and i.selected])

    @staticmethod
    def _dedup_priority(item: CleanItem) -> tuple[int, int]:
        if item.category == "扩展名占用汇总" and not item.deletable:
            return (-1, 0)
        recommendation_rank = {
            Recommendation.RECOMMEND: 0,
            Recommendation.OPTIONAL: 1,
            Recommendation.NOT_RECOMMENDED: 2,
        }
        return (int(not item.deletable), recommendation_rank.get(item.recommendation, 9))

    def clean(
        self,
        items: list[CleanItem],
        cancel_flag: dict | None = None,
        *,
        dry_run: bool = False,
        use_recycle_bin: bool = False,
    ) -> CleanResult:
        return self.executor.execute(
            effective_clean_targets(items),
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
