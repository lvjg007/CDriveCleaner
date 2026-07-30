from __future__ import annotations

import logging
import shutil
import stat
from pathlib import Path

from src.models.items import CleanItem, CleanResult
from src.utils.freshness import is_fresh
from src.utils.logging_util import setup_clean_logger
from src.utils.paths import is_hard_excluded
from src.utils.recycle import send_to_recycle_bin


def _on_rm_error(func, path, _exc_info) -> None:
    try:
        Path(path).chmod(stat.S_IWRITE)
        func(path)
    except Exception:
        pass


class CleanExecutor:
    """删除执行器：支持 dry-run、永久删除、回收站模式。"""

    def execute(
        self,
        items: list[CleanItem],
        cancel_flag: dict | None = None,
        *,
        dry_run: bool = False,
        use_recycle_bin: bool = False,
    ) -> CleanResult:
        logger, log_path = setup_clean_logger()
        result = CleanResult(log_path=str(log_path))
        if dry_run:
            mode = "模拟清理"
        elif use_recycle_bin:
            mode = "回收站清理"
        else:
            mode = "永久清理"
        logger.info("%s 开始，共 %s 项", mode, len(items))

        for item in items:
            if cancel_flag and cancel_flag.get("cancel"):
                logger.info("用户取消，停止后续删除")
                break
            path = Path(item.path)
            if is_hard_excluded(path):
                msg = f"硬排除，跳过: {path}"
                result.fail_count += 1
                result.errors.append(msg)
                logger.warning(msg)
                continue
            if not path.exists():
                result.success_count += 1
                if not dry_run:
                    result.removed_ids.append(item.id)
                result.freed_bytes += max(0, item.size_bytes)
                logger.info("路径已不存在，视为已清理: %s", path)
                continue
            try:
                freed = item.size_bytes
                if dry_run:
                    logger.info(
                        "[DRY-RUN] 将删除 path=%s size=%s category=%s recycle=%s",
                        path,
                        item.size_bytes,
                        item.category,
                        use_recycle_bin,
                    )
                elif use_recycle_bin:
                    # 缩略图：只回收匹配文件
                    if item.category == "缩略图缓存":
                        freed = self._recycle_thumb_dir(path, logger)
                    elif item.category == "系统临时文件":
                        freed = self._recycle_dir_children(path, logger, skip_fresh=True)
                    else:
                        send_to_recycle_bin(path)
                elif path.is_dir():
                    if item.category == "缩略图缓存":
                        freed = self._clean_thumb_dir(path, logger)
                    elif item.category == "空目录":
                        shutil.rmtree(path, onerror=_on_rm_error)
                        freed = 0
                    elif item.category == "系统临时文件":
                        freed = self._clear_dir_contents(path, logger, skip_fresh=True)
                    else:
                        freed = self._clear_dir_contents(path, logger, skip_fresh=False)
                else:
                    if item.category == "系统临时文件" and is_fresh(path):
                        logger.info("跳过新鲜临时文件: %s", path)
                        result.fail_count += 1
                        continue
                    path.unlink(missing_ok=True)

                result.success_count += 1
                result.freed_bytes += max(0, freed)
                if not dry_run:
                    result.removed_ids.append(item.id)
                logger.info(
                    "%s成功 path=%s size=%s category=%s",
                    "[DRY-RUN] " if dry_run else "",
                    path,
                    item.size_bytes,
                    item.category,
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"失败 path={path} err={exc}"
                result.fail_count += 1
                result.errors.append(msg)
                logger.error(msg)

        logger.info(
            "%s 结束 success=%s fail=%s freed=%s",
            mode,
            result.success_count,
            result.fail_count,
            result.freed_bytes,
        )
        for h in logger.handlers:
            h.close()
        logger.handlers.clear()
        return result

    def _recycle_dir_children(
        self,
        path: Path,
        logger: logging.Logger,
        *,
        skip_fresh: bool = False,
    ) -> int:
        freed = 0
        for child in list(path.iterdir()):
            try:
                if skip_fresh and is_fresh(child):
                    logger.info("跳过 24h 内新鲜项: %s", child)
                    continue
                try:
                    if child.is_file():
                        freed += child.stat().st_size
                    # 目录大小粗略不计
                except OSError:
                    pass
                send_to_recycle_bin(child)
            except Exception as exc:  # noqa: BLE001
                logger.warning("回收站删除失败 %s: %s", child, exc)
        return freed

    def _recycle_thumb_dir(self, path: Path, logger: logging.Logger) -> int:
        freed = 0
        for f in list(path.glob("thumbcache_*.db")) + (
            [path / "iconcache.db"] if (path / "iconcache.db").exists() else []
        ):
            try:
                freed += f.stat().st_size
                send_to_recycle_bin(f)
            except Exception as exc:  # noqa: BLE001
                logger.warning("缩略图回收失败 %s: %s", f, exc)
        return freed

    def _clear_dir_contents(
        self,
        path: Path,
        logger: logging.Logger,
        *,
        skip_fresh: bool = False,
    ) -> int:
        freed = 0
        for child in list(path.iterdir()):
            try:
                if skip_fresh and is_fresh(child):
                    logger.info("跳过 24h 内新鲜项: %s", child)
                    continue
                if child.is_symlink():
                    continue
                if child.is_dir():
                    size = 0
                    try:
                        for f in child.rglob("*"):
                            if f.is_file():
                                try:
                                    size += f.stat().st_size
                                except OSError:
                                    pass
                    except OSError:
                        pass
                    shutil.rmtree(child, onerror=_on_rm_error)
                    freed += size
                else:
                    try:
                        sz = child.stat().st_size
                    except OSError:
                        sz = 0
                    child.unlink(missing_ok=True)
                    freed += sz
            except Exception as exc:  # noqa: BLE001
                logger.warning("子项删除失败 %s: %s", child, exc)
        return freed

    def _clean_thumb_dir(self, path: Path, logger: logging.Logger) -> int:
        freed = 0
        for f in path.glob("thumbcache_*.db"):
            try:
                freed += f.stat().st_size
                f.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("缩略图删除失败 %s: %s", f, exc)
        icon = path / "iconcache.db"
        if icon.exists():
            try:
                freed += icon.stat().st_size
                icon.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("iconcache 删除失败: %s", exc)
        return freed
