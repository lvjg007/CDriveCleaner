from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from src.utils.describe import describe_path
from src.utils.paths import canonical_path_key, is_reparse_point


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Recommendation(str, Enum):
    RECOMMEND = "recommend"
    OPTIONAL = "optional"
    NOT_RECOMMENDED = "not_recommended"

    @property
    def label_zh(self) -> str:
        return {
            Recommendation.RECOMMEND: "建议删除",
            Recommendation.OPTIONAL: "可选",
            Recommendation.NOT_RECOMMENDED: "不建议",
        }[self]


@dataclass
class CleanItem:
    id: str
    category: str
    path: str
    size_bytes: int
    risk: Risk
    recommendation: Recommendation
    reason: str
    detail: str = ""
    needs_admin: bool = False
    selected: bool = False
    deletable: bool = True
    protection_reason: str = ""
    #: 是否允许跨盘展示。默认 False —— 扫描目标盘的扫描器只应产出目标盘上的条目。
    #: 打开它的唯一理由是「纯说明性条目」，例如选了 C 盘时告知
    #: 「页面文件其实在 D 盘」。可删除的条目一律不允许跨盘，
    #: 否则会出现「在 D 盘扫描结果里勾选，实际删掉的是 C 盘文件」。
    cross_drive: bool = False

    @property
    def drive(self) -> str:
        """条目所在盘，形如 ``"C:"``。取不到时返回空串。"""
        try:
            return Path(self.path).drive.upper()
        except (OSError, ValueError):
            return ""

    @staticmethod
    def make(
        *,
        id: str,
        category: str,
        path: str,
        size_bytes: int,
        recommendation: Recommendation,
        reason: str,
        needs_admin: bool = False,
        selected: Optional[bool] = None,
        detail: Optional[str] = None,
        deletable: bool = True,
        protection_reason: str = "",
        cross_drive: bool = False,
    ) -> "CleanItem":
        risk = {
            Recommendation.RECOMMEND: Risk.LOW,
            Recommendation.OPTIONAL: Risk.MEDIUM,
            Recommendation.NOT_RECOMMENDED: Risk.HIGH,
        }[recommendation]
        if selected is None:
            selected = deletable and recommendation == Recommendation.RECOMMEND
        if detail is None:
            detail = describe_path(path, category=category)
        return CleanItem(
            id=id,
            category=category,
            path=path,
            size_bytes=max(0, int(size_bytes)),
            risk=risk,
            recommendation=recommendation,
            reason=reason,
            detail=detail,
            needs_admin=needs_admin,
            selected=selected,
            deletable=deletable,
            protection_reason=protection_reason,
            # 跨盘展示只对报告项开放。可删除条目跨盘会让「在 D 盘勾选、
            # 实际删掉 C 盘文件」成为可能，直接抹掉这个可能性。
            cross_drive=cross_drive and not deletable,
        )


def effective_clean_targets(items: list[CleanItem]) -> list[CleanItem]:
    """Return non-overlapping actionable targets and preserve report items."""
    candidates: list[CleanItem] = []
    seen: set[str] = set()
    for item in items:
        if not item.deletable:
            continue
        key = canonical_path_key(item.path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(item)

    ordered = sorted(
        enumerate(candidates),
        key=lambda pair: (len(Path(canonical_path_key(pair[1].path)).parts), pair[0]),
    )
    kept: list[CleanItem] = []
    for _, item in ordered:
        current_key = canonical_path_key(item.path)
        if any(
            parent_path.is_dir()
            # 重解析点不能当祖先：它指向的是另一棵树，把子项折叠进去等于删错地方。
            # 这里不能用 is_symlink()，它对 Windows 目录 junction 恒为 False。
            and not is_reparse_point(parent_path)
            and _is_strict_ancestor(canonical_path_key(parent.path), current_key)
            for parent in kept
            for parent_path in [Path(parent.path)]
        ):
            continue
        kept.append(item)
    kept_ids = {id(item) for item in kept}
    return [item for item in items if not item.deletable or id(item) in kept_ids]


def _is_strict_ancestor(parent_key: str, child_key: str) -> bool:
    if parent_key == child_key:
        return False
    try:
        Path(child_key).relative_to(Path(parent_key))
    except ValueError:
        return False
    return True


def format_size(num_bytes: int) -> str:
    n = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} TB"


@dataclass
class CleanResult:
    success_count: int = 0
    fail_count: int = 0
    freed_bytes: int = 0
    errors: list[str] = field(default_factory=list)
    log_path: str = ""
    removed_ids: list[str] = field(default_factory=list)
    cancelled: bool = False
    remaining_count: int = 0
    partial_count: int = 0
    estimated_bytes: int = 0
