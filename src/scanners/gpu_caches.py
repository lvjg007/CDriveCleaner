from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_PROFILE
from src.utils.paths import dir_size, is_hard_excluded


class GpuCacheScanner(Scanner):
    """借鉴 BitBroom：NVIDIA/AMD/Intel 着色器与驱动缓存。"""

    name = "GPU 着色器缓存"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_PROFILE

    def _targets(self) -> list[tuple[str, Path, Recommendation, str]]:
        local = Path.home() / "AppData" / "Local"
        return [
            ("NVIDIA GLCache", local / "NVIDIA" / "GLCache", Recommendation.RECOMMEND, "OpenGL 着色器缓存，删后会重建"),
            ("NVIDIA DXCache", local / "NVIDIA" / "DXCache", Recommendation.RECOMMEND, "DirectX 着色器缓存"),
            ("NVIDIA ComputeCache", local / "NVIDIA" / "ComputeCache", Recommendation.RECOMMEND, "CUDA/计算缓存"),
            ("AMD DXCache", local / "AMD" / "DxCache", Recommendation.RECOMMEND, "AMD DirectX 缓存"),
            ("AMD GLCache", local / "AMD" / "GLCache", Recommendation.RECOMMEND, "AMD OpenGL 缓存"),
            ("Intel ShaderCache", local / "Intel" / "ShaderCache", Recommendation.RECOMMEND, "Intel 着色器缓存"),
            ("D3DSCache", local / "D3DSCache", Recommendation.RECOMMEND, "系统 DirectX 着色器缓存"),
        ]

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        targets = self._targets()
        for i, (label, path, reco, reason) in enumerate(targets):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if path.exists() and not is_hard_excluded(path):
                size = dir_size(path, cancel_flag, max_seconds=5.0)
                if size > 0:
                    items.append(
                        CleanItem.make(
                            id=f"gpu:{label}",
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
