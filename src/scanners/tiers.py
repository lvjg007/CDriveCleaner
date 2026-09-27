"""扫描器共用的分级词汇与目标结构。

「AI 工具数据」和「家目录残留」面对的是同一类问题：一长串候选路径，
风险高低不同，但删不删最终由用户在界面上逐项确认。两个扫描器必须用
同一套口径描述风险，否则界面上的语义会随改动漂移，所以把词汇抽在这里。

分级只表达风险，不剥夺选择权 —— 三档都保持可勾选，与 large_files /
old_downloads 既有的「不建议，请确认后勾选」语义一致。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from src.models.items import Recommendation

SAFE = "safe"
OPTIONAL = "optional"
CAUTION = "caution"

TIER_RECOMMENDATION = {
    SAFE: Recommendation.RECOMMEND,
    OPTIONAL: Recommendation.OPTIONAL,
    CAUTION: Recommendation.NOT_RECOMMENDED,
}

# 追加在理由末尾，让用户在勾选前就看清代价
TIER_SUFFIX = {
    SAFE: "",
    OPTIONAL: "；默认不勾选，需二次确认",
    CAUTION: "；不建议删除，确认后仍可勾选",
}


@dataclass(frozen=True)
class Target:
    label: str
    path: Path
    tier: str
    reason: str
    admin: bool = False
    # 非空则把 path 当作目录、按该 glob 展开成多个条目
    pattern: str = ""
    # 展示分类，空则回落到扫描器名
    group: str = ""


def group_targets(name: str, prefix: str, targets: list[Target]) -> list[Target]:
    """给一组目标打上分类 —— 界面上按此分列，方便逐类筛选、逐项勾选。"""
    return [replace(t, group=prefix + name) for t in targets]


def is_never_touch(path: Path, names: frozenset[str]) -> bool:
    """凭据/密钥类路径的兜底防线：目标清单里误加进来会被拦下。"""
    lowered = path.name.lower()
    if lowered in names:
        return True
    return any(part.lower() in names for part in path.parts)
