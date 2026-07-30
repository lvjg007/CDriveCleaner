from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import is_hard_excluded, looks_like_project_dir, safe_iter_files

_INSTALLER_EXTS = {".exe", ".msi", ".iso", ".msix", ".msixbundle"}
_MIN_SIZE = 20 * 1024 * 1024  # 20MB


class InstallerResidueScanner(Scanner):
    name = "安装包残留"

    def _roots(self) -> list[Path]:
        home = Path.home()
        return [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        roots = [r for r in self._roots() if r.exists()]
        for i, root in enumerate(roots):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if is_hard_excluded(root):
                continue
            for f in safe_iter_files(root, cancel_flag=cancel_flag):
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
                    )
                )
            if progress:
                progress(self.name, (i + 1) / max(len(roots), 1))
        if progress:
            progress(self.name, 1.0)
        return items
