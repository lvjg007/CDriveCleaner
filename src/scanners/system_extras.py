from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded


class SystemExtrasScanner(Scanner):
    """补充常见占空间点：传递优化、错误报告、崩溃转储、旧系统等。"""

    name = "系统与其它缓存"

    def _targets(self) -> list[tuple[str, Path, Recommendation, str, bool]]:
        home = Path.home()
        local = home / "AppData" / "Local"
        win = Path(r"C:\Windows")
        return [
            (
                "传递优化缓存",
                Path(r"C:\Windows\SoftwareDistribution\DeliveryOptimization"),
                Recommendation.RECOMMEND,
                "Windows 传递优化下载缓存，删后可再下载",
                True,
            ),
            (
                "传递优化 Cache",
                Path(r"C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache"),
                Recommendation.RECOMMEND,
                "传递优化缓存目录",
                True,
            ),
            (
                "Windows 错误报告",
                Path(r"C:\ProgramData\Microsoft\Windows\WER"),
                Recommendation.RECOMMEND,
                "错误报告队列，一般可清",
                True,
            ),
            (
                "崩溃转储",
                local / "CrashDumps",
                Recommendation.RECOMMEND,
                "程序崩溃 dump，排查完可删",
                False,
            ),
            (
                "DirectX 着色器缓存",
                local / "D3DSCache",
                Recommendation.RECOMMEND,
                "游戏/图形着色器缓存，删后会重建",
                False,
            ),
            (
                "网络缓存 INetCache",
                local / "Microsoft" / "Windows" / "INetCache",
                Recommendation.RECOMMEND,
                "旧版网络/IE 缓存",
                False,
            ),
            (
                "WebCache",
                local / "Microsoft" / "Windows" / "WebCache",
                Recommendation.OPTIONAL,
                "WebCache 数据库，关闭浏览器后再清更稳",
                False,
            ),
            (
                "Windows 日志",
                win / "Logs",
                Recommendation.OPTIONAL,
                "系统日志目录，可清部分占用",
                True,
            ),
            (
                "Prefetch",
                win / "Prefetch",
                Recommendation.OPTIONAL,
                "预读取文件，删除后开机/启动略慢，随后重建",
                True,
            ),
            (
                "FontCache",
                local / "Microsoft" / "Windows" / "Fonts",
                Recommendation.OPTIONAL,
                "字体相关本地数据（谨慎）",
                False,
            ),
            (
                "Windows.old",
                Path(r"C:\Windows.old"),
                Recommendation.OPTIONAL,
                "升级前旧系统，确认不回退后可删，通常很大",
                True,
            ),
            (
                "Installer 补丁缓存",
                Path(r"C:\Windows\Installer\$PatchCache$"),
                Recommendation.OPTIONAL,
                "安装补丁缓存，删后部分程序修复可能失败",
                True,
            ),
            (
                "Windows Defender 日志",
                Path(r"C:\ProgramData\Microsoft\Windows Defender\Support"),
                Recommendation.RECOMMEND,
                "Defender 支持日志，一般可清",
                True,
            ),
            (
                "Windows Defender Scans History",
                Path(r"C:\ProgramData\Microsoft\Windows Defender\Scans\History"),
                Recommendation.OPTIONAL,
                "扫描历史，可选清理",
                True,
            ),
            (
                "LiveKernelReports",
                win / "LiveKernelReports",
                Recommendation.RECOMMEND,
                "内核实时转储报告",
                True,
            ),
            (
                "内存转储 Minidump",
                win / "Minidump",
                Recommendation.RECOMMEND,
                "蓝屏小转储，排查完可删",
                True,
            ),
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
        for i, (label, path, reco, reason, admin) in enumerate(targets):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if not path.exists() or is_hard_excluded(path):
                if progress:
                    progress(self.name, (i + 1) / max(len(targets), 1))
                continue
            size = dir_size(path, cancel_flag, max_seconds=6.0)
            if size <= 0:
                if progress:
                    progress(self.name, (i + 1) / max(len(targets), 1))
                continue
            items.append(
                CleanItem.make(
                    id=f"extra:{label}",
                    category=self.name,
                    path=str(path),
                    size_bytes=size,
                    recommendation=reco,
                    reason=f"{label}：{reason}",
                    needs_admin=admin,
                )
            )
            if progress:
                progress(f"{self.name}: {label}", (i + 1) / max(len(targets), 1))
        if progress:
            progress(self.name, 1.0)
        return items
