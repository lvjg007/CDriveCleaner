from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from src.models.items import CleanItem

ProgressCb = Callable[[str, float], None]

# --- 扫描器的盘范围 ---------------------------------------------------------
#
# 工具从「只扫 C 盘」扩到「选盘扫」之后，最关键的问题变成：
# **这个扫描器在这个盘上到底有没有意义？**
#
# 答案分三类，写错了会静默产出错误结果而不是报错 —— 所以必须显式声明。

#: 任何盘都能扫，自己按目标盘适配根目录（回收站、临时文件、大文件…）
SCOPE_DRIVE = "drive"

#: 只在装了 Windows 的盘上有意义（更新缓存、WinSxS、WinRE 残留…）。
#: 在数据盘上跑它们只会得到一堆不存在的路径。
SCOPE_SYSTEM = "system"

#: 只在用户目录所在盘上有意义（AI 工具数据、家目录残留、浏览器缓存…）。
#: 这类扫描器读的是 ``Path.home()``，用户目录只在一个盘上 ——
#: 在别的盘重跑只会把同一个盘的结果再报一遍，属于**假重复**。
SCOPE_PROFILE = "profile"

_SCOPE_LABELS = {
    SCOPE_DRIVE: "任意盘",
    SCOPE_SYSTEM: "仅系统盘",
    SCOPE_PROFILE: "仅用户目录所在盘",
}


class Scanner(ABC):
    name: str = "base"

    #: 该扫描器适用的盘范围，取 ``SCOPE_DRIVE`` / ``SCOPE_SYSTEM`` / ``SCOPE_PROFILE``。
    #: 默认 ``SCOPE_DRIVE``，即不声明就按「任何盘都扫」处理。
    drive_scope: str = SCOPE_DRIVE

    @property
    def scope_label(self) -> str:
        return _SCOPE_LABELS.get(self.drive_scope, self.drive_scope)

    def applies_to(self, drive: str) -> bool:
        """该扫描器在指定盘上是否值得运行。

        判定只依赖盘的属性（是否装了 Windows、是否放着用户目录），
        与盘符本身无关 —— 用户目录可以被搬到 D 盘，系统盘也不一定是 C。
        """
        from src.utils import drives

        if self.drive_scope == SCOPE_SYSTEM:
            return drives.has_windows(drive)
        if self.drive_scope == SCOPE_PROFILE:
            return drives.normalize_letter(drive) == drives.profile_drive()
        return True

    def skip_reason(self, drive: str) -> str:
        """不适用时给用户看的一句话理由；适用时返回空串。

        判定与 ``applies_to`` 共用同一份逻辑，两者永远同真同假：
        ``skip_reason(drive) != ""`` 等价于 ``not applies_to(drive)``。

        早期版本是按 ``drive_scope`` 无条件返回理由的，于是
        「Windows 更新缓存」在 C 盘（确实装了 Windows）上也会说
        「C: 上没有 Windows 安装」—— 目前唯一的调用方只在跳过时才问，
        所以没暴露出来，但这是句假话，早晚会被别处引用到。
        """
        if self.applies_to(drive):
            return ""
        if self.drive_scope == SCOPE_SYSTEM:
            return f"{drive} 上没有 Windows 安装，此项不适用"
        if self.drive_scope == SCOPE_PROFILE:
            return f"用户目录不在 {drive}，此项不适用"
        return ""

    @abstractmethod
    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        raise NotImplementedError
