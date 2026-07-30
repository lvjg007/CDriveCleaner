from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded


class OfficeCommsScanner(Scanner):
    """借鉴 BitBroom/BleachBit：办公与通讯软件缓存。"""

    name = "办公与通讯缓存"

    def _targets(self) -> list[tuple[str, Path, Recommendation, str]]:
        home = Path.home()
        local = home / "AppData" / "Local"
        roaming = home / "AppData" / "Roaming"
        return [
            ("Office 临时", local / "Microsoft" / "Office" / "16.0" / "OfficeFileCache", Recommendation.OPTIONAL, "Office 文件缓存（确认无未同步编辑）"),
            ("Teams 缓存", local / "Packages", Recommendation.OPTIONAL, "需在下面对 UWP Teams 细化；占位跳过"),  # will filter
            ("Teams Classic Cache", local / "Microsoft" / "Teams" / "Cache", Recommendation.RECOMMEND, "经典 Teams 缓存"),
            ("Teams Classic blob", local / "Microsoft" / "Teams" / "blob_storage", Recommendation.RECOMMEND, "Teams blob 缓存"),
            ("Zoom 缓存", roaming / "Zoom" / "data" / "WebviewCache", Recommendation.RECOMMEND, "Zoom WebView 缓存"),
            ("Zoom logs", roaming / "Zoom" / "logs", Recommendation.RECOMMEND, "Zoom 日志"),
            ("Slack Cache", roaming / "Slack" / "Cache", Recommendation.RECOMMEND, "Slack 缓存"),
            ("Slack Code Cache", roaming / "Slack" / "Code Cache", Recommendation.RECOMMEND, "Slack 代码缓存"),
            ("Spotify Storage", local / "Spotify" / "Storage", Recommendation.OPTIONAL, "Spotify 下载缓存（可能含离线歌）"),
            ("Spotify Data", local / "Spotify" / "Data", Recommendation.OPTIONAL, "Spotify 数据缓存"),
            ("OBS logs", roaming / "obs-studio" / "logs", Recommendation.RECOMMEND, "OBS 日志"),
            ("Adobe Common", local / "Adobe" / "Acrobat" / "DC" / "Temp", Recommendation.RECOMMEND, "Acrobat 临时"),
            ("Adobe CEP Cache", roaming / "Adobe" / "CEP" / "extensions", Recommendation.OPTIONAL, "Adobe CEP（谨慎）"),
            ("OneNote 备份缓存", local / "Microsoft" / "OneNote", Recommendation.OPTIONAL, "OneNote 本地数据"),
            ("Outlook INetCache", local / "Microsoft" / "Windows" / "INetCache" / "Content.Outlook", Recommendation.RECOMMEND, "Outlook 临时附件缓存"),
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        targets = [(a, b, c, d) for a, b, c, d in self._targets() if "占位" not in d]
        # 额外：新版 Teams（MSTeams）
        packages = Path.home() / "AppData" / "Local" / "Packages"
        if packages.exists():
            try:
                for p in packages.iterdir():
                    if "MSTeams" in p.name or "MicrosoftTeams" in p.name:
                        cache = p / "LocalCache"
                        if cache.exists():
                            targets.append(
                                (
                                    f"Teams UWP {p.name[:20]}",
                                    cache,
                                    Recommendation.OPTIONAL,
                                    "新版 Teams 本地缓存",
                                )
                            )
            except OSError:
                pass

        for i, (label, path, reco, reason) in enumerate(targets):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if path.exists() and not is_hard_excluded(path):
                size = dir_size(path, cancel_flag, max_seconds=5.0)
                if size > 0:
                    items.append(
                        CleanItem.make(
                            id=f"office:{label}",
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
