from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, existing_paths, is_hard_excluded


class DevCacheScanner(Scanner):
    name = "开发工具缓存"

    def _candidates(self) -> list[tuple[str, str]]:
        home = Path.home()
        local = home / "AppData" / "Local"
        return [
            ("npm cache", str(home / "AppData" / "Local" / "npm-cache")),
            ("yarn cache", str(home / "AppData" / "Local" / "Yarn" / "Cache")),
            ("pnpm store", str(home / "AppData" / "Local" / "pnpm-store")),
            ("pnpm store alt", str(home / "AppData" / "Local" / "pnpm" / "store")),
            ("pip cache", str(home / "AppData" / "Local" / "pip" / "Cache")),
            ("NuGet cache", str(home / ".nuget" / "packages")),
            ("Maven repo", str(home / ".m2" / "repository")),
            ("Gradle caches", str(home / ".gradle" / "caches")),
            ("Cargo registry", str(home / ".cargo" / "registry")),
            ("go module cache", str(home / "go" / "pkg" / "mod")),
            ("VS Code Cache", str(home / "AppData" / "Roaming" / "Code" / "Cache")),
            ("VS Code CachedData", str(home / "AppData" / "Roaming" / "Code" / "CachedData")),
            ("Cursor Cache", str(home / "AppData" / "Roaming" / "Cursor" / "Cache")),
            ("Cursor CachedData", str(home / "AppData" / "Roaming" / "Cursor" / "CachedData")),
            ("JetBrains caches", str(local / "JetBrains")),
            ("Docker wsl data hint", str(local / "Docker")),
            ("npm _cacache", str(home / "AppData" / "Roaming" / "npm-cache")),
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        cands = self._candidates()
        for i, (label, raw) in enumerate(cands):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            paths = existing_paths([raw])
            for p in paths:
                if is_hard_excluded(p):
                    continue
                size = dir_size(p, cancel_flag, max_seconds=6.0)
                if size <= 0:
                    continue
                # Docker/JetBrains 整树可能极大：标可选，避免误伤
                reco = Recommendation.RECOMMEND
                if "JetBrains" in label or "Docker" in label:
                    reco = Recommendation.OPTIONAL
                items.append(
                    CleanItem.make(
                        id=f"dev:{label}",
                        category=self.name,
                        path=str(p),
                        size_bytes=size,
                        recommendation=reco,
                        reason=f"{label}，删除后可能需要重新下载依赖/缓存",
                    )
                )
            if progress:
                progress(self.name, (i + 1) / max(len(cands), 1))
        if progress:
            progress(self.name, 1.0)
        return items
