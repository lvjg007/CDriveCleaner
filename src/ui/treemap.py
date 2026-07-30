"""简单矩形树图（squarify 简化版），用于按分类展示占用。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    label: str
    value: int


def _layout_row(
    items: list[tuple[str, int]],
    x: float,
    y: float,
    w: float,
    h: float,
    horizontal: bool,
) -> list[Rect]:
    total = sum(v for _, v in items) or 1
    rects: list[Rect] = []
    offset = 0.0
    for label, value in items:
        frac = value / total
        if horizontal:
            rw = w * frac
            rects.append(Rect(x + offset, y, rw, h, label, value))
            offset += rw
        else:
            rh = h * frac
            rects.append(Rect(x, y + offset, w, rh, label, value))
            offset += rh
    return rects


def squarify(items: list[tuple[str, int]], x: float, y: float, w: float, h: float) -> list[Rect]:
    """
    简化 squarify：按面积比例切分。
    items: [(label, size_bytes), ...] 已按大小降序更佳。
    """
    cleaned = [(lab, max(0, int(val))) for lab, val in items if val > 0]
    if not cleaned:
        return []
    cleaned.sort(key=lambda t: -t[1])
    # 递归二分：前半 / 后半
    return _squarify_rec(cleaned, x, y, w, h)


def _squarify_rec(
    items: list[tuple[str, int]],
    x: float,
    y: float,
    w: float,
    h: float,
) -> list[Rect]:
    if not items:
        return []
    if len(items) == 1:
        lab, val = items[0]
        return [Rect(x, y, w, h, lab, val)]
    total = sum(v for _, v in items) or 1
    acc = 0
    split = 1
    for i, (_, v) in enumerate(items):
        acc += v
        split = i + 1
        if acc >= total / 2:
            break
    left, right = items[:split], items[split:]
    if not right:
        return _layout_row(items, x, y, w, h, horizontal=w >= h)
    frac = sum(v for _, v in left) / total
    if w >= h:
        lw = w * frac
        return _squarify_rec(left, x, y, lw, h) + _squarify_rec(right, x + lw, y, w - lw, h)
    lh = h * frac
    return _squarify_rec(left, x, y, w, lh) + _squarify_rec(right, x, y + lh, w, h - lh)


# 固定调色（避免刺眼紫）
COLORS = [
    "#2A9D8F",
    "#E9C46A",
    "#F4A261",
    "#E76F51",
    "#264653",
    "#457B9D",
    "#A8DADC",
    "#1D3557",
    "#8AB17D",
    "#BC6C25",
    "#6D597A",
    "#B56576",
    "#E56B6F",
    "#EAAC8B",
    "#355070",
]
