from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded


class BrowserCacheScanner(Scanner):
    name = "浏览器缓存"

    def _profile_cache_dirs(self) -> list[tuple[str, Path]]:
        local = Path.home() / "AppData" / "Local"
        out: list[tuple[str, Path]] = []
        browsers = [
            ("Chrome", local / "Google" / "Chrome" / "User Data"),
            ("Edge", local / "Microsoft" / "Edge" / "User Data"),
            ("Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
        ]
        for browser, root in browsers:
            if not root.exists():
                continue
            try:
                children = list(root.iterdir())
            except OSError:
                continue
            for prof in children:
                if not prof.is_dir():
                    continue
                name = prof.name
                if name not in {"Default", "Guest Profile"} and not name.startswith("Profile"):
                    continue
                for sub in ("Cache", "Code Cache", "GPUCache"):
                    p = prof / sub
                    if p.exists():
                        out.append((f"{browser} {name} {sub}", p))
        ff = local / "Mozilla" / "Firefox" / "Profiles"
        if ff.exists():
            try:
                for prof in ff.iterdir():
                    cache2 = prof / "cache2"
                    if cache2.exists():
                        out.append((f"Firefox {prof.name}", cache2))
            except OSError:
                pass
        return out

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        targets = self._profile_cache_dirs()
        for i, (label, path) in enumerate(targets):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if is_hard_excluded(path):
                continue
            size = dir_size(path, cancel_flag, max_seconds=6.0)
            if size <= 0:
                if progress:
                    progress(self.name, (i + 1) / max(len(targets), 1))
                continue
            items.append(
                CleanItem.make(
                    id=f"browser:{label}",
                    category=self.name,
                    path=str(path),
                    size_bytes=size,
                    recommendation=Recommendation.RECOMMEND,
                    reason=f"{label}，不影响书签/密码/登录态主数据",
                )
            )
            if progress:
                progress(f"{self.name}: {label}", (i + 1) / max(len(targets), 1))
        if progress:
            progress(self.name, 1.0)
        return items
