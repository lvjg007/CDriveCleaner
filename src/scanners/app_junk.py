from __future__ import annotations

from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner, SCOPE_PROFILE
from src.utils.paths import dir_size, is_hard_excluded


class AppJunkScanner(Scanner):
    """其它软件缓存（微信明细已拆到「微信（可定制）」扫描器）。"""

    name = "软件缓存与聊天附件"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_PROFILE
    _REPORT_ONLY_LABELS = {
        "微信程序缓存 Roaming",
        "微信 xwechat 程序缓存",
        "QQ 缓存",
        "钉钉缓存",
        "飞书缓存",
        "企业微信",
        "Steam 本地数据",
        "Telegram Cache",
        "百度网盘缓存",
        "迅雷缓存",
        "Sogou 输入法",
        "Edge 更新包",
        "Google 更新包",
    }

    def _fixed_targets(self) -> list[tuple[str, Path, Recommendation, str]]:
        home = Path.home()
        local = home / "AppData" / "Local"
        roaming = home / "AppData" / "Roaming"
        return [
            ("微信程序缓存 Roaming", roaming / "Tencent" / "WeChat", Recommendation.RECOMMEND, "微信程序缓存（不含聊天附件）"),
            ("微信 xwechat 程序缓存", roaming / "Tencent" / "xwechat", Recommendation.RECOMMEND, "新版微信程序缓存"),
            ("QQ 临时", roaming / "Tencent" / "QQ" / "Temp", Recommendation.RECOMMEND, "QQ 临时文件"),
            ("QQ 缓存", local / "Tencent" / "QQ", Recommendation.RECOMMEND, "QQ 本地缓存"),
            ("钉钉缓存", roaming / "DingTalk", Recommendation.RECOMMEND, "钉钉缓存/日志"),
            ("飞书缓存", roaming / "LarkShell", Recommendation.RECOMMEND, "飞书缓存"),
            ("企业微信", roaming / "Tencent" / "WXWork", Recommendation.RECOMMEND, "企业微信缓存"),
            ("网易云缓存", local / "NetEase" / "CloudMusic" / "Cache", Recommendation.RECOMMEND, "网易云音乐缓存"),
            ("QQ音乐缓存", local / "Tencent" / "QQMusic" / "Cache", Recommendation.RECOMMEND, "QQ 音乐缓存"),
            ("Steam 本地数据", local / "Steam", Recommendation.OPTIONAL, "Steam 本地数据（含着色器等）"),
            ("Discord Cache", roaming / "discord" / "Cache", Recommendation.RECOMMEND, "Discord 缓存"),
            ("Telegram Cache", roaming / "Telegram Desktop" / "tdata", Recommendation.OPTIONAL, "Telegram 数据（谨慎）"),
            ("百度网盘缓存", local / "BaiduNetdisk", Recommendation.RECOMMEND, "百度网盘缓存"),
            ("迅雷缓存", local / "Thunder Network", Recommendation.RECOMMEND, "迅雷相关缓存"),
            ("Edge 更新包", local / "Microsoft" / "EdgeUpdate", Recommendation.RECOMMEND, "Edge 更新残留"),
            ("Google 更新包", local / "Google" / "Update", Recommendation.RECOMMEND, "Chrome 更新残留"),
            ("Sogou 输入法", local / "SogouPY", Recommendation.OPTIONAL, "搜狗输入法缓存"),
        ]

    def _qq_file_roots(self) -> list[Path]:
        home = Path.home()
        roots: list[Path] = []
        for parent in (home / "Documents", home / "文档", home):
            p = parent / "Tencent Files"
            if p.exists():
                roots.append(p)
        return roots

    def _collect_account_subdirs(
        self,
        roots: list[Path],
        rel_parts: list[str],
        *,
        label_prefix: str,
        recommendation: Recommendation,
        reason: str,
        cancel_flag: dict | None,
        items: list[CleanItem],
    ) -> None:
        for root in roots:
            if is_hard_excluded(root):
                continue
            try:
                accounts = [x for x in root.iterdir() if x.is_dir()]
            except OSError:
                continue
            for acc in accounts:
                if cancel_flag and cancel_flag.get("cancel"):
                    return
                target = acc
                for part in rel_parts:
                    target = target / part
                if not target.exists() or is_hard_excluded(target):
                    continue
                size = dir_size(target, cancel_flag, max_seconds=6.0)
                if size <= 0:
                    continue
                items.append(
                    CleanItem.make(
                        id=f"appjunk:{label_prefix}:{target}",
                        category=self.name,
                        path=str(target),
                        size_bytes=size,
                        recommendation=recommendation,
                        reason=reason,
                        detail=f"QQ · {label_prefix} · {acc.name}",
                    )
                )

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        fixed = self._fixed_targets()
        for i, (label, path, reco, reason) in enumerate(fixed):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if path.exists() and not is_hard_excluded(path):
                size = dir_size(path, cancel_flag, max_seconds=6.0)
                if size > 0:
                    report_only = label in self._REPORT_ONLY_LABELS
                    if report_only:
                        reco = Recommendation.NOT_RECOMMENDED
                        reason = f"{reason}；整目录尚未拆分为明确缓存子目录，仅报告不直接删除"
                    items.append(
                        CleanItem.make(
                            id=f"appjunk:{label}",
                            category=self.name,
                            path=str(path),
                            size_bytes=size,
                            recommendation=reco,
                            reason=f"{label}：{reason}",
                            deletable=not report_only,
                            protection_reason="应用数据整目录，尚未拆分缓存范围" if report_only else "",
                        )
                    )
            if progress:
                progress(f"{self.name}: {label}", (i + 1) / max(len(fixed) + 1, 1))

        qq_roots = self._qq_file_roots()
        for rel, tag, why in (
            (["Image"], "qq-image", "QQ 聊天图片"),
            (["Video"], "qq-video", "QQ 聊天视频"),
            (["Audio"], "qq-audio", "QQ 聊天语音"),
            (["File"], "qq-file", "QQ 聊天文件"),
        ):
            self._collect_account_subdirs(
                qq_roots,
                rel,
                label_prefix=tag,
                recommendation=Recommendation.OPTIONAL,
                reason=why,
                cancel_flag=cancel_flag,
                items=items,
            )
        if progress:
            progress(self.name, 1.0)
        return items
