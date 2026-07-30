from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.utils.describe import describe_path


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
    ) -> "CleanItem":
        risk = {
            Recommendation.RECOMMEND: Risk.LOW,
            Recommendation.OPTIONAL: Risk.MEDIUM,
            Recommendation.NOT_RECOMMENDED: Risk.HIGH,
        }[recommendation]
        if selected is None:
            selected = recommendation == Recommendation.RECOMMEND
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
        )


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
