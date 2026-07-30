from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from src.models.items import CleanItem, Recommendation
from src.scanners.base import ProgressCb, Scanner
from src.utils.paths import dir_size, is_hard_excluded

_CHATROOM_RE = re.compile(r"[\w\-\.]+@chatroom")
_WXID_RE = re.compile(r"wxid_[\w\-]+")
# 其它可能的微信号（字母数字下划线，长度受限，降低误报）
_ALIAS_RE = re.compile(r"\b[a-zA-Z][\w\-]{5,31}\b")

_MEDIA_SUBS = (
    ("Image", "聊天图片", Recommendation.OPTIONAL),
    ("Thumb", "缩略图", Recommendation.RECOMMEND),
    ("Video", "聊天视频", Recommendation.OPTIONAL),
    ("File", "聊天文件", Recommendation.OPTIONAL),
    ("Img", "聊天图片", Recommendation.OPTIONAL),  # xwechat
)


def _md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def discover_chat_id_map(account_dir: Path, cancel_flag: dict | None = None) -> dict[str, tuple[str, str]]:
    """
    尽量从配置/日志中收集聊天对象 ID，并用 MD5 映射到 MsgAttach 目录名。
    返回: {md5: (chat_id, 'group'|'friend')}
    """
    found: set[str] = set()
    # 限制扫描范围，避免拖慢整体
    scan_roots = [
        account_dir / "config",
        account_dir / "Config",
        account_dir / "Msg",
        account_dir,
    ]
    checked_files = 0
    for root in scan_roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            # 不走进超大媒体目录反查
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower()
                not in {"filestorage", "msgattach", "image", "video", "file", "cache", "temp"}
            ]
            for name in filenames:
                if checked_files > 80:
                    break
                fp = Path(dirpath) / name
                if fp.suffix.lower() not in {".ini", ".txt", ".xml", ".json", ".cfg", ".dat", ".info", ""}:
                    if fp.suffix.lower() not in {".log"}:
                        continue
                try:
                    if fp.stat().st_size > 2 * 1024 * 1024:
                        continue
                    raw = fp.read_bytes()
                except OSError:
                    continue
                checked_files += 1
                # 二进制里也可能有 ASCII 字符串
                try:
                    text = raw.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                for m in _CHATROOM_RE.findall(text):
                    found.add(m)
                for m in _WXID_RE.findall(text):
                    found.add(m)

    mapping: dict[str, tuple[str, str]] = {}
    for chat_id in found:
        kind = "group" if "@chatroom" in chat_id else "friend"
        mapping[_md5_hex(chat_id)] = (chat_id, kind)
        # 个别版本可能用大写 MD5
        mapping[_md5_hex(chat_id).upper()] = (chat_id, kind)
    return mapping


def classify_session(folder_name: str, id_map: dict[str, tuple[str, str]]) -> tuple[str, str, str]:
    """
    返回 (会话类型中文, 显示名, chat_id或短哈希)
    """
    key = folder_name.strip()
    low = key.lower()
    if "chatroom" in low or key.endswith("@chatroom"):
        return "群聊", key, key
    if key in id_map:
        chat_id, kind = id_map[key]
        if kind == "group":
            return "群聊", chat_id, chat_id
        return "个人", chat_id, chat_id
    # 未反查到：仍按会话拆分，便于定制
    short = key[:10] + "…" if len(key) > 12 else key
    return "会话", f"未命名会话({short})", short


class WeChatScanner(Scanner):
    name = "微信（可定制）"

    def _account_dirs(self) -> list[Path]:
        home = Path.home()
        roots: list[Path] = []
        for base_name in ("WeChat Files", "xwechat_files", "WeChatFiles"):
            for parent in (home / "Documents", home / "文档", home):
                p = parent / base_name
                if p.exists() and p.is_dir():
                    roots.append(p)
        accounts: list[Path] = []
        for root in roots:
            if is_hard_excluded(root):
                continue
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    name = child.name.lower()
                    if name in {"all users", "wmpf", "backup"}:
                        continue
                    accounts.append(child)
            except OSError:
                continue
        return accounts

    def _add_item(
        self,
        items: list[CleanItem],
        *,
        account: str,
        path: Path,
        kind: str,
        media: str,
        display: str,
        recommendation: Recommendation,
        reason: str,
        cancel_flag: dict | None,
    ) -> None:
        if not path.exists() or is_hard_excluded(path):
            return
        size = dir_size(path, cancel_flag, max_seconds=5.0)
        if size <= 0:
            return
        detail = f"微信 · {kind} · {media} · {display} · 账号:{account}"
        items.append(
            CleanItem.make(
                id=f"wechat:{account}:{kind}:{media}:{path}",
                category=self.name,
                path=str(path),
                size_bytes=size,
                recommendation=recommendation,
                reason=reason,
                detail=detail,
            )
        )

    def _scan_msg_attach(
        self,
        account_dir: Path,
        attach_root: Path,
        id_map: dict[str, tuple[str, str]],
        items: list[CleanItem],
        cancel_flag: dict | None,
        progress: ProgressCb | None,
        progress_base: float,
    ) -> None:
        if not attach_root.exists():
            return
        try:
            sessions = [p for p in attach_root.iterdir() if p.is_dir()]
        except OSError:
            return
        total = max(len(sessions), 1)
        for i, session in enumerate(sessions):
            if cancel_flag and cancel_flag.get("cancel"):
                return
            kind, display, _cid = classify_session(session.name, id_map)
            for sub_name, media_label, reco in _MEDIA_SUBS:
                sub = session / sub_name
                if not sub.exists():
                    continue
                reason = (
                    f"微信{kind}「{display}」的{media_label}；"
                    f"删除后该{kind}历史里对应媒体可能无法查看"
                )
                if media_label == "缩略图":
                    reason = f"微信{kind}「{display}」缩略图，一般可删"
                self._add_item(
                    items,
                    account=account_dir.name,
                    path=sub,
                    kind=kind,
                    media=media_label,
                    display=display,
                    recommendation=reco,
                    reason=reason,
                    cancel_flag=cancel_flag,
                )
            # 若会话目录下没有标准子目录，整目录作为「会话附件」
            if not any((session / s).exists() for s, _, _ in _MEDIA_SUBS):
                self._add_item(
                    items,
                    account=account_dir.name,
                    path=session,
                    kind=kind,
                    media="会话附件",
                    display=display,
                    recommendation=Recommendation.OPTIONAL,
                    reason=f"微信{kind}「{display}」附件汇总",
                    cancel_flag=cancel_flag,
                )
            if progress and i % 5 == 0:
                progress(
                    f"{self.name}: {account_dir.name} {kind} {display[:16]}",
                    progress_base + 0.4 * (i + 1) / total,
                )

    def _scan_legacy_months(
        self,
        account_dir: Path,
        items: list[CleanItem],
        cancel_flag: dict | None,
    ) -> None:
        """旧版按月份汇总的 Image/Video/File（未按好友拆分）。"""
        fs = account_dir / "FileStorage"
        for folder, media, reco in (
            ("Image", "聊天图片(按月汇总)", Recommendation.OPTIONAL),
            ("Video", "聊天视频(按月汇总)", Recommendation.OPTIONAL),
            ("File", "聊天文件(按月汇总)", Recommendation.OPTIONAL),
        ):
            root = fs / folder
            if not root.exists():
                continue
            try:
                children = list(root.iterdir())
            except OSError:
                continue
            month_dirs = [p for p in children if p.is_dir()]
            if month_dirs:
                for month in month_dirs:
                    self._add_item(
                        items,
                        account=account_dir.name,
                        path=month,
                        kind="汇总",
                        media=media,
                        display=month.name,
                        recommendation=reco,
                        reason=f"旧版结构：未按好友拆分的{media}（{month.name}）",
                        cancel_flag=cancel_flag,
                    )
            else:
                self._add_item(
                    items,
                    account=account_dir.name,
                    path=root,
                    kind="汇总",
                    media=media,
                    display=folder,
                    recommendation=reco,
                    reason=f"旧版结构：{media}",
                    cancel_flag=cancel_flag,
                )

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        accounts = self._account_dirs()
        if not accounts:
            if progress:
                progress(self.name, 1.0)
            return items

        for ai, account_dir in enumerate(accounts):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            base = ai / max(len(accounts), 1)
            if progress:
                progress(f"{self.name}: 账号 {account_dir.name}", base)

            id_map = discover_chat_id_map(account_dir, cancel_flag)

            # 通用缓存
            for rel, media, reco, why in (
                (("FileStorage", "Cache"), "程序缓存", Recommendation.RECOMMEND, "缓存可删"),
                (("FileStorage", "Temp"), "临时文件", Recommendation.RECOMMEND, "临时文件可删"),
            ):
                p = account_dir.joinpath(*rel)
                self._add_item(
                    items,
                    account=account_dir.name,
                    path=p,
                    kind="账号",
                    media=media,
                    display=account_dir.name,
                    recommendation=reco,
                    reason=why,
                    cancel_flag=cancel_flag,
                )

            # 经典 MsgAttach：按人/群 × 图片/视频/文件
            self._scan_msg_attach(
                account_dir,
                account_dir / "FileStorage" / "MsgAttach",
                id_map,
                items,
                cancel_flag,
                progress,
                base + 0.2,
            )

            # 新版 xwechat: msg/attach
            self._scan_msg_attach(
                account_dir,
                account_dir / "msg" / "attach",
                id_map,
                items,
                cancel_flag,
                progress,
                base + 0.55,
            )

            # 旧版按月汇总
            self._scan_legacy_months(account_dir, items, cancel_flag)

            # 聊天记录库（慎删）
            for rel, label in (
                (("Msg",), "聊天记录库"),
                (("db_storage",), "聊天记录库(新版)"),
                (("msg", "db_storage"), "聊天记录库"),
            ):
                p = account_dir.joinpath(*rel)
                self._add_item(
                    items,
                    account=account_dir.name,
                    path=p,
                    kind="账号",
                    media=label,
                    display=account_dir.name,
                    recommendation=Recommendation.NOT_RECOMMENDED,
                    reason="删除会导致本地聊天记录丢失，仅在确定不需要时勾选",
                    cancel_flag=cancel_flag,
                )

            if progress:
                progress(f"{self.name}: 完成 {account_dir.name}", (ai + 1) / max(len(accounts), 1))

        # 体积大的靠前，方便定制勾选
        items.sort(key=lambda x: -x.size_bytes)
        if progress:
            progress(self.name, 1.0)
        return items
