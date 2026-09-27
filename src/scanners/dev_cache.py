from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_PROFILE
from src.utils.paths import dir_size, existing_paths, is_hard_excluded


class DevCacheScanner(Scanner):
    name = "开发工具缓存"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_PROFILE

    # 整目录混着配置/虚拟磁盘，无法安全拆分，只能展示
    _REPORT_ONLY_LABELS = {
        "JetBrains caches",
        "Docker wsl data hint",
    }

    # 标准包仓库：删除只导致下次构建重新下载，不丢任何用户数据，
    # 因此允许勾选，但默认不勾、需要二次确认。
    _OPTIONAL_LABELS = {
        "NuGet cache",
        "Maven repo",
        "Gradle caches",
        "Cargo registry",
        "go module cache",
        "pnpm store",
        "pnpm store alt",
    }

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
            # VS Code 本体（Cursor 等 AI 编辑器已移交「AI 工具数据」扫描器）
            ("VS Code Cache", str(home / "AppData" / "Roaming" / "Code" / "Cache")),
            ("VS Code CachedData", str(home / "AppData" / "Roaming" / "Code" / "CachedData")),
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
                # Docker/JetBrains 整树可能极大且混着配置：仅报告，避免误伤
                report_only = label in self._REPORT_ONLY_LABELS
                optional = label in self._OPTIONAL_LABELS
                if report_only:
                    reco = Recommendation.NOT_RECOMMENDED
                    reason = f"{label}，整目录尚未拆分，暂仅报告"
                elif optional:
                    reco = Recommendation.OPTIONAL
                    reason = f"{label}，标准包仓库缓存；删除后下次构建会重新下载，不丢数据"
                else:
                    reco = Recommendation.RECOMMEND
                    reason = f"{label}，删除后可能需要重新下载依赖/缓存"
                items.append(
                    CleanItem.make(
                        id=f"dev:{label}",
                        category=self.name,
                        path=str(p),
                        size_bytes=size,
                        recommendation=reco,
                        reason=reason,
                        deletable=not report_only,
                        protection_reason="开发工具整目录，尚未拆分缓存范围" if report_only else "",
                    )
                )
            if progress:
                progress(self.name, (i + 1) / max(len(cands), 1))
        if progress:
            progress(self.name, 1.0)
        return items
