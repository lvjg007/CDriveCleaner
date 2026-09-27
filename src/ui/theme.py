"""设计 token —— 由 docs/design/design-plan.md 落成的代码常量。

surface: b_end / utilitarian-enterprise。
视觉宪法（禁止项）：无阴影、无渐变、无卡片墙；主色 #1677FF；
中文正文不用 Inter / Roboto / Arial / system-ui；间距只用 4 的允许档位。
"""
from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

# ---------- 间距 / 圆角（只允许这几档，禁止 13/18/22 之类随意值）----------
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32
SPACE_HUGE = 48

RADIUS_BUTTON = 6
RADIUS_CARD = 8
RADIUS_TAG = 4

# ---------- 字体（Windows 端等价替换，见 design-plan §3）----------
FONT_BODY = "Microsoft YaHei UI"   # 替代 macOS 专属的 PingFang SC
FONT_DATA = "Consolas"             # 替代 macOS 专属的 SF Mono

FONT_PAGE_TITLE = (FONT_BODY, 20, "bold")
FONT_SECTION = (FONT_BODY, 15, "bold")
FONT_BODY_13 = (FONT_BODY, 13)
FONT_BODY_BOLD = (FONT_BODY, 13, "bold")
FONT_CAPTION = (FONT_BODY, 12)
FONT_TABLE = (FONT_BODY, 13)
FONT_TABLE_HEAD = (FONT_BODY, 13, "bold")
FONT_DATA_12 = (FONT_DATA, 12)

# ---------- 尺寸 ----------
TOPBAR_HEIGHT = 48
ROW_HEIGHT = 34
BUTTON_HEIGHT = 32


@dataclass(frozen=True)
class Palette:
    primary: str
    primary_hover: str
    page_bg: str
    surface: str
    surface_alt: str
    border: str
    text_primary: str
    text_secondary: str
    text_tertiary: str
    success: str
    warning: str
    danger: str
    danger_hover: str
    row_optional_bg: str
    row_danger_bg: str
    row_report_bg: str
    row_selected_bg: str
    table_header_bg: str
    on_primary: str


LIGHT = Palette(
    primary="#1677FF",
    primary_hover="#4096FF",
    page_bg="#F0F2F5",
    surface="#FFFFFF",
    surface_alt="#FAFAFA",
    border="#E8E8E8",
    text_primary="#141414",
    text_secondary="#595959",
    text_tertiary="#8C8C8C",
    success="#52C41A",
    warning="#FAAD14",
    danger="#FF4D4F",
    danger_hover="#FFF1F0",
    row_optional_bg="#FFF7E6",
    row_danger_bg="#FFF1F0",
    row_report_bg="#FAFAFA",
    row_selected_bg="#E6F4FF",
    table_header_bg="#FAFAFA",
    on_primary="#FFFFFF",
)

DARK = Palette(
    primary="#3C89FF",
    primary_hover="#5C9DFF",
    page_bg="#1A1A1A",
    surface="#242424",
    surface_alt="#2E2E2E",
    border="#3A3A3A",
    text_primary="#F0F0F0",
    text_secondary="#A6A6A6",
    text_tertiary="#737373",
    success="#52C41A",
    warning="#FAAD14",
    danger="#FF4D4F",
    danger_hover="#3A1F1F",
    row_optional_bg="#2A2118",
    row_danger_bg="#2A1A1A",
    row_report_bg="#232323",
    row_selected_bg="#132A42",
    table_header_bg="#2E2E2E",
    on_primary="#FFFFFF",
)


def palette() -> Palette:
    """当前外观模式对应的色板。"""
    return DARK if ctk.get_appearance_mode() == "Dark" else LIGHT


def is_dark() -> bool:
    return ctk.get_appearance_mode() == "Dark"


def capacity_color(used_pct: float) -> str:
    """容量语义色：<70% 健康 / 70–90% 偏高 / >90% 告急。

    这是本产品的 Signature —— 同一色阶贯穿容量条、建议徽标与行底色。
    """
    p = palette()
    if used_pct >= 90.0:
        return p.danger
    if used_pct >= 70.0:
        return p.warning
    return p.success


# 语义徽标：符号 + 文案，保证状态不只靠颜色（a11y 底线）
ADVICE_BADGE = {
    "recommend": ("●", "建议删除", "success"),
    "optional": ("◐", "可选", "warning"),
    "not_recommended": ("○", "不建议", "danger"),
    "report_only": ("—", "仅报告", "text_tertiary"),
}

RISK_ZH = {"low": "低", "medium": "中", "high": "高"}


def button_style(variant: str) -> dict:
    """按钮变体。每屏 primary 只允许 1 个（Anti-Slop B6）。"""
    p = palette()
    if variant == "primary":
        return {
            "fg_color": p.primary,
            "hover_color": p.primary_hover,
            "text_color": p.on_primary,
            "border_width": 0,
        }
    if variant == "secondary":
        return {
            "fg_color": "transparent",
            "hover_color": p.row_selected_bg,
            "text_color": p.primary,
            "border_width": 1,
            "border_color": p.primary,
        }
    if variant == "danger":
        return {
            "fg_color": "transparent",
            "hover_color": p.danger_hover,
            "text_color": p.danger,
            "border_width": 1,
            "border_color": p.danger,
        }
    # ghost —— 默认次级动作
    return {
        "fg_color": "transparent",
        "hover_color": p.surface_alt,
        "text_color": p.text_secondary,
        "border_width": 1,
        "border_color": p.border,
    }


def row_tag_styles() -> dict[str, dict[str, str]]:
    """Treeview 行底色。语义底色取代斑马纹（见 design-plan Anti-Slop 额外自查）。"""
    p = palette()
    return {
        "safe": {"background": p.surface, "foreground": p.text_primary},
        "optional": {"background": p.row_optional_bg, "foreground": p.text_primary},
        "danger": {"background": p.row_danger_bg, "foreground": p.text_primary},
        "report": {"background": p.row_report_bg, "foreground": p.text_tertiary},
    }


def tree_style_config() -> dict[str, dict]:
    """ttk.Treeview 的 style 配置，浅深色各一套。"""
    p = palette()
    return {
        "Clean.Treeview": {
            "rowheight": ROW_HEIGHT,
            "font": FONT_TABLE,
            "background": p.surface,
            "fieldbackground": p.surface,
            "foreground": p.text_primary,
            "bordercolor": p.border,
        },
        "Clean.Treeview.Heading": {
            "font": FONT_TABLE_HEAD,
            "background": p.table_header_bg,
            "foreground": p.text_secondary,
        },
    }
