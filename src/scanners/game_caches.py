from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded


class GameCacheScanner(Scanner):
    """借鉴 BitBroom：游戏平台着色器/下载缓存。"""

    name = "游戏平台缓存"

    def _targets(self) -> list[tuple[str, Path, Recommendation, str]]:
        local = Path.home() / "AppData" / "Local"
        roaming = Path.home() / "AppData" / "Roaming"
        programdata = Path(r"C:\ProgramData")
        return [
            ("Steam htmlcache", local / "Steam" / "htmlcache", Recommendation.RECOMMEND, "Steam 内置浏览器缓存"),
            ("Steam logs", local / "Steam" / "logs", Recommendation.RECOMMEND, "Steam 日志"),
            ("Steam shadercache hint", local / "Steam" / "steamapps" / "shadercache", Recommendation.OPTIONAL, "Steam 着色器（在库目录时）"),
            ("Epic Cache", local / "EpicGamesLauncher" / "Saved" / "webcache_4430", Recommendation.RECOMMEND, "Epic 启动器缓存"),
            ("Epic Logs", local / "EpicGamesLauncher" / "Saved" / "Logs", Recommendation.RECOMMEND, "Epic 日志"),
            ("EA Cache", local / "Electronic Arts" / "EA Desktop" / "CEF", Recommendation.RECOMMEND, "EA Desktop CEF 缓存"),
            ("Battle.net Cache", local / "Battle.net" / "BrowserCache", Recommendation.RECOMMEND, "战网浏览器缓存"),
            ("Ubisoft Cache", local / "Ubisoft Game Launcher" / "cache", Recommendation.RECOMMEND, "育碧缓存"),
            ("GOG Cache", local / "GOG.com" / "Galaxy" / "webcache", Recommendation.RECOMMEND, "GOG Galaxy 缓存"),
            ("Xbox GameBar Cache", local / "Packages", Recommendation.OPTIONAL, "占位"),
            ("Unity Cache", local / "Unity" / "Caches", Recommendation.RECOMMEND, "Unity Editor 缓存"),
            ("Unreal DerivedDataCache", local / "UnrealEngine" / "Common" / "DerivedDataCache", Recommendation.OPTIONAL, "UE 派生数据缓存"),
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        targets = [(a, b, c, d) for a, b, c, d in self._targets() if d != "占位"]
        for i, (label, path, reco, reason) in enumerate(targets):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if path.exists() and not is_hard_excluded(path):
                size = dir_size(path, cancel_flag, max_seconds=5.0)
                if size > 0:
                    items.append(
                        CleanItem.make(
                            id=f"game:{label}",
                            category=self.name,
                            path=str(path),
                            size_bytes=size,
                            recommendation=reco,
                            reason=f"{label}：{reason}",
                        )
                    )
            if progress:
                progress(self.name, (i + 1) / max(len(targets), 1))
        if progress:
            progress(self.name, 1.0)
        return items
