from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_DRIVE
from src.utils import drives
from src.utils.paths import is_hard_excluded, looks_like_project_dir, safe_iter_files

_INSTALLER_EXTS = {".exe", ".msi", ".iso", ".msix", ".msixbundle"}
_MIN_SIZE = 20 * 1024 * 1024  # 20MB
#: 整盘找安装包时的时限。默认 8 秒在 100GB+ 的盘上连根目录都走不完。
_WHOLE_DRIVE_SECONDS = 40.0


class InstallerResidueScanner(Scanner):
    name = "安装包残留"
    #: 见 base.SCOPE_* 说明。
    #: 用 SCOPE_DRIVE 而不是 SCOPE_PROFILE：数据盘上「躺在根目录的旧安装包/镜像」
    #: 恰恰是这类盘最常见的垃圾，只扫用户目录会完全看不到。
    drive_scope = SCOPE_DRIVE

    def _roots(self) -> list[Path]:
        """用户盘看下载/桌面；其它盘从盘根走一遍。"""
        home = Path.home()
        home_roots = [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
        ]
        return drives.roots_for_search_scanner(drives.target_drive(), home_roots)

    def _budget(self) -> float:
        drive = drives.target_drive()
        if drives.normalize_letter(drive) == drives.profile_drive():
            return 8.0
        return _WHOLE_DRIVE_SECONDS

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        roots = [r for r in self._roots() if r.exists()]
        budget = self._budget()
        for i, root in enumerate(roots):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if is_hard_excluded(root):
                continue
            # 整盘遍历时必须带跳过表：Program Files 里的 exe 是装好的程序，不是残留
            files = safe_iter_files(
                root,
                cancel_flag=cancel_flag,
                max_seconds=budget,
                skip_names=drives.ROOT_SKIP_DIR_NAMES,
            )
            for f in files:
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if f.suffix.lower() not in _INSTALLER_EXTS:
                    continue
                if looks_like_project_dir(f):
                    continue
                try:
                    size = f.stat().st_size
                except OSError:
                    continue
                if size < _MIN_SIZE:
                    continue
                items.append(
                    CleanItem.make(
                        id=f"installer:{f}",
                        category=self.name,
                        path=str(f),
                        size_bytes=size,
                        recommendation=Recommendation.OPTIONAL,
                        reason="大型安装包/镜像，确认不再需要后再删",
                        detail=f"安装包 · {f.suffix.lstrip('.').upper()} · {f.name}",
                    )
                )
            if progress:
                progress(self.name, (i + 1) / max(len(roots), 1))
        if progress:
            progress(self.name, 1.0)
        return items
