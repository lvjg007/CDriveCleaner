from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_PROFILE
from src.utils.paths import is_hard_excluded, looks_like_project_dir, safe_iter_files

_VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".rmvb"}
_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".raw", ".tiff"}
_AUDIO = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".wma"}

_VIDEO_MIN = 20 * 1024 * 1024
_IMAGE_MIN = 2 * 1024 * 1024
_AUDIO_MIN = 5 * 1024 * 1024


class MediaDownloadsScanner(Scanner):
    name = "下载的视频图片音频"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_PROFILE

    def _roots(self) -> list[Path]:
        home = Path.home()
        return [
            home / "Downloads",
            home / "下载",
            home / "Desktop",
            home / "桌面",
            home / "Videos",
            home / "视频",
            home / "Pictures",
            home / "图片",
            home / "Music",
            home / "音乐",
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
            if progress:
                progress(f"{self.name}: {root.name}", i / max(len(roots), 1))
            for f in safe_iter_files(root, cancel_flag=cancel_flag, max_seconds=15.0):
                if cancel_flag and cancel_flag.get("cancel"):
                    break
                if looks_like_project_dir(f):
                    continue
                ext = f.suffix.lower()
                try:
                    size = f.stat().st_size
                except OSError:
                    continue
                kind = ""
                # Media files are user content, even when stored in Downloads/Desktop.
                reco = Recommendation.OPTIONAL
                if ext in _VIDEO and size >= _VIDEO_MIN:
                    kind = "视频文件"
                elif ext in _IMAGE and size >= _IMAGE_MIN:
                    kind = "图片文件"
                elif ext in _AUDIO and size >= _AUDIO_MIN:
                    kind = "音频文件"
                else:
                    continue
                # 文档/图片库里的标可选，下载/桌面建议删
                low = str(root).lower()
                items.append(
                    CleanItem.make(
                        id=f"media:{f}",
                        category=self.name,
                        path=str(f),
                        size_bytes=size,
                        recommendation=reco,
                        reason=f"{kind}（位于 {root.name}），确认不需要后可删",
                        detail=f"{kind} · {f.name}",
                    )
                )
        items.sort(key=lambda x: x.size_bytes, reverse=True)
        items = items[:400]
        if progress:
            progress(self.name, 1.0)
        return items
