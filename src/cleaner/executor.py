from __future__ import annotations

import logging
import shutil
import stat
from pathlib import Path

from src.models.items import CleanItem, CleanResult, effective_clean_targets
from src.utils.disk import is_admin
from src.utils.drives import target_drive
from src.utils.freshness import is_fresh
from src.utils.logging_util import setup_clean_logger
from src.utils.paths import is_deletion_protected, is_reparse_point
from src.utils.recycle import empty_recycle_bin, send_to_recycle_bin


class PartialCleanupError(RuntimeError):
    def __init__(self, message: str, freed_bytes: int) -> None:
        super().__init__(message)
        self.freed_bytes = max(0, freed_bytes)


def _on_rm_error(func, path, _exc_info) -> None:
    try:
        Path(path).chmod(stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _recycle_bin_root(path: str | Path) -> str:
    """从回收站条目路径（``D:\\$Recycle.Bin``）取出盘根（``D:\\``）。

    必须按条目所在盘去清空：多盘模式下报告里会同时存在 C:/D:/E: 三个回收站条目，
    如果每次都调「清空所有盘」，清 D 盘那一项会连带清掉 C 盘的 ——
    用户点的是 D 盘，不该动 C 盘的东西。
    """
    try:
        anchor = Path(path).anchor
    except (OSError, ValueError):
        anchor = ""
    return anchor or ""


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
        items = effective_clean_targets(items)
        logger, log_path = setup_clean_logger()
        result = CleanResult(log_path=str(log_path), remaining_count=len(items))
        if dry_run:
            mode = "模拟清理"
        elif use_recycle_bin:
            mode = "回收站清理"
        else:
            mode = "永久清理"
        logger.info("%s 开始，共 %s 项", mode, len(items))

        processed = 0
        for item in items:
            if cancel_flag and cancel_flag.get("cancel"):
                result.cancelled = True
                logger.info("用户取消，停止后续删除")
                break
            path = Path(item.path)
            try:
                if item.needs_admin and not is_admin():
                    msg = f"需要管理员权限，跳过: {path}"
                    result.fail_count += 1
                    result.errors.append(msg)
                    logger.warning(msg)
                    continue
                if not item.deletable:
                    msg = f"保护项，跳过: {path} ({item.protection_reason or '该项目不可直接删除'})"
                    result.fail_count += 1
                    result.errors.append(msg)
                    logger.warning(msg)
                    continue
                # 跨盘兜底闸门。上游（编排层）已经按目标盘过滤过一轮，
                # 但这里是真正落盘删除的地方，不该把安全寄托在上游没写错上。
                # 场景：用户扫 C 盘 → 切到 D 盘 → 清理时用的还是旧的 items。
                if item.drive and item.drive != target_drive():
                    msg = f"条目不属于当前目标盘 {target_drive()}，跳过: {path}"
                    result.fail_count += 1
                    result.errors.append(msg)
                    logger.warning(msg)
                    continue
                if is_deletion_protected(path):
                    msg = f"受保护路径，跳过: {path}"
                    result.fail_count += 1
                    result.errors.append(msg)
                    logger.warning(msg)
                    continue
                if not path.exists():
                    result.success_count += 1
                    if not dry_run:
                        result.removed_ids.append(item.id)
                    logger.info("路径已不存在，从结果中移除但不计释放空间: %s", path)
                    continue
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
                    if item.category == "回收站":
                        empty_recycle_bin(_recycle_bin_root(item.path))
                    elif item.category == "缩略图缓存":
                        freed = self._recycle_thumb_dir(path, logger)
                    elif item.category == "系统临时文件":
                        freed = self._recycle_dir_children(path, logger, skip_fresh=True)
                    else:
                        send_to_recycle_bin(path)
                elif path.is_dir():
                    if item.category == "回收站":
                        empty_recycle_bin(_recycle_bin_root(item.path))
                    elif item.category == "缩略图缓存":
                        freed = self._clean_thumb_dir(path, logger)
                    elif item.category == "空目录":
                        shutil.rmtree(path, onerror=_on_rm_error)
                        freed = 0
                    elif item.category == "系统临时文件":
                        freed, changed = self._clear_temp_contents(path, logger)
                        if not changed:
                            msg = f"没有可安全删除的过期临时文件: {path}"
                            result.fail_count += 1
                            result.errors.append(msg)
                            logger.info(msg)
                            continue
                    else:
                        freed = self._clear_dir_contents(path, logger, skip_fresh=False)
                else:
                    if item.category == "系统临时文件" and is_fresh(path):
                        logger.info("跳过新鲜临时文件: %s", path)
                        result.fail_count += 1
                        continue
                    path.unlink(missing_ok=True)

                result.success_count += 1
                if dry_run:
                    result.estimated_bytes += max(0, freed)
                else:
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
            except PartialCleanupError as exc:
                result.partial_count += 1
                result.fail_count += 1
                result.freed_bytes += exc.freed_bytes
                msg = f"部分完成 path={path} freed={exc.freed_bytes} err={exc}"
                result.errors.append(msg)
                logger.error(msg)
            except Exception as exc:  # noqa: BLE001
                msg = f"失败 path={path} err={exc}"
                result.fail_count += 1
                result.errors.append(msg)
                logger.error(msg)
            finally:
                processed += 1

        result.remaining_count = max(0, len(items) - processed)

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
        failures: list[str] = []
        for child in list(path.iterdir()):
            try:
                # junction/symlink 必须整体跳过：child.is_symlink() 对 Windows
                # 目录 junction 恒为 False，删下去会打到目标目录的真实内容
                if is_reparse_point(child):
                    logger.info("跳过重解析点: %s", child)
                    continue
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
                msg = f"回收站删除失败 {child}: {exc}"
                failures.append(msg)
                logger.warning(msg)
        if failures:
            raise PartialCleanupError("；".join(failures[:3]), freed)
        return freed

    def _clear_temp_contents(self, path: Path, logger: logging.Logger) -> tuple[int, bool]:
        """Recursively remove stale temp files while preserving fresh files."""
        freed = 0
        changed = False
        failures: list[str] = []

        def visit(directory: Path) -> None:
            nonlocal freed, changed
            try:
                children = list(directory.iterdir())
            except OSError as exc:
                failures.append(f"无法读取 {directory}: {exc}")
                return
            for child in children:
                try:
                    if child.is_symlink():
                        continue
                    if child.is_dir():
                        visit(child)
                        try:
                            if not any(child.iterdir()):
                                child.rmdir()
                                changed = True
                        except OSError:
                            pass
                    else:
                        if is_fresh(child):
                            continue
                        size = child.stat().st_size
                        child.unlink(missing_ok=True)
                        freed += size
                        changed = True
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"子项删除失败 {child}: {exc}")

        visit(path)
        if failures:
            raise PartialCleanupError("；".join(failures[:3]), freed)
        return freed, changed

    def _recycle_thumb_dir(self, path: Path, logger: logging.Logger) -> int:
        freed = 0
        failures: list[str] = []
        for f in list(path.glob("thumbcache_*.db")) + (
            [path / "iconcache.db"] if (path / "iconcache.db").exists() else []
        ):
            try:
                freed += f.stat().st_size
                send_to_recycle_bin(f)
            except Exception as exc:  # noqa: BLE001
                msg = f"缩略图回收失败 {f}: {exc}"
                failures.append(msg)
                logger.warning(msg)
        if failures:
            raise PartialCleanupError("；".join(failures[:3]), freed)
        return freed

    def _clear_dir_contents(
        self,
        path: Path,
        logger: logging.Logger,
        *,
        skip_fresh: bool = False,
    ) -> int:
        freed = 0
        failures: list[str] = []
        for child in list(path.iterdir()):
            try:
                if skip_fresh and is_fresh(child):
                    logger.info("跳过 24h 内新鲜项: %s", child)
                    continue
                if is_reparse_point(child):
                    logger.info("跳过重解析点: %s", child)
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
                msg = f"子项删除失败 {child}: {exc}"
                failures.append(msg)
                logger.warning(msg)
        if failures:
            raise PartialCleanupError("；".join(failures[:3]), freed)
        return freed

    def _clean_thumb_dir(self, path: Path, logger: logging.Logger) -> int:
        freed = 0
        failures: list[str] = []
        for f in path.glob("thumbcache_*.db"):
            try:
                freed += f.stat().st_size
                f.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                msg = f"缩略图删除失败 {f}: {exc}"
                failures.append(msg)
                logger.warning(msg)
        icon = path / "iconcache.db"
        if icon.exists():
            try:
                freed += icon.stat().st_size
                icon.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                msg = f"iconcache 删除失败: {exc}"
                failures.append(msg)
                logger.warning(msg)
        if failures:
            raise RuntimeError("；".join(failures[:3]))
        return freed
