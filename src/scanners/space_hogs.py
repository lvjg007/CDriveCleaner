from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import is_hard_excluded


class SpaceHogsScanner(Scanner):
    """
    借鉴 BitBroom Space Hogs：只报告大户，默认不建议删除。
    休眠/页面文件/虚拟磁盘等应通过系统设置或官方工具处理。
    """

    name = "占空间报告(勿盲删)"

    def _file_item(self, label: str, path: Path, reason: str) -> CleanItem | None:
        if not path.exists() or is_hard_excluded(path):
            return None
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size <= 0:
            return None
        return CleanItem.make(
            id=f"hog:{label}",
            category=self.name,
            path=str(path),
            size_bytes=size,
            recommendation=Recommendation.NOT_RECOMMENDED,
            reason=reason,
            detail=f"报告项 · {label}",
        )

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        candidates = [
            (
                "休眠文件 hiberfil.sys",
                Path(r"C:\hiberfil.sys"),
                "关闭休眠可释放（powercfg /hibernate off），不要直接删系统文件",
            ),
            (
                "页面文件 pagefile.sys",
                Path(r"C:\pagefile.sys"),
                "在系统性能设置中调整虚拟内存，勿直接删除",
            ),
            (
                "交换文件 swapfile.sys",
                Path(r"C:\swapfile.sys"),
                "系统管理的交换文件，勿直接删除",
            ),
        ]
        for i, (label, path, reason) in enumerate(candidates):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            it = self._file_item(label, path, reason)
            if it:
                items.append(it)
            if progress:
                progress(self.name, (i + 1) / 8)

        # WSL / Docker vhdx（常见占坑）
        local = Path.home() / "AppData" / "Local"
        vhdx_globs = [
            local / "Packages" / "CanonicalGroupLimited.Ubuntu*" / "LocalState" / "ext4.vhdx",
            local / "Docker" / "wsl" / "**" / "*.vhdx",
            local / "wsl" / "**" / "*.vhdx",
        ]
        # 简化：有限深度搜索
        search_roots = [
            local / "Packages",
            local / "Docker",
            local / "wsl",
            Path(r"C:\Users") / Path.home().name / "AppData" / "Local" / "Packages",
        ]
        found = 0
        for root in search_roots:
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if not root.exists():
                continue
            try:
                for p in root.rglob("*.vhdx"):
                    if found >= 15:
                        break
                    if is_hard_excluded(p):
                        continue
                    try:
                        size = p.stat().st_size
                    except OSError:
                        continue
                    if size < 100 * 1024 * 1024:
                        continue
                    items.append(
                        CleanItem.make(
                            id=f"hog:vhdx:{p}",
                            category=self.name,
                            path=str(p),
                            size_bytes=size,
                            recommendation=Recommendation.NOT_RECOMMENDED,
                            reason="WSL/Docker 虚拟磁盘：请用 wsl --shutdown 后 diskpart compact，勿直接删正在使用的 vhdx",
                            detail=f"报告项 · 虚拟磁盘 · {p.name}",
                        )
                    )
                    found += 1
            except OSError:
                continue

        if progress:
            progress(self.name, 1.0)
        return items
