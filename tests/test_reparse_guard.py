"""junction / 重解析点护栏测试。

背景：Windows 上 ``Path.is_symlink()`` 对目录 junction 恒为 ``False``
（实测 ``st_reparse_tag == 0xA0000003`` 时 ``S_ISLNK`` 为假），而
``shutil.rmtree`` 会顺着 junction 删掉**目标目录的真实内容**。
家目录里的 ``Application Data`` 就指向 ``AppData\\Roaming``，
``Local Settings`` 指向 ``AppData\\Local`` —— 删一次等于清空整个 Roaming。

所以「这个路径能不能删」的判断必须走 ``is_reparse_point``，不能走 ``is_symlink``。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from src.cleaner.executor import CleanExecutor
from src.utils import paths
from src.utils.paths import canonical_path_key, is_deletion_protected, is_reparse_point

# Windows 用户配置文件里默认存在的兼容性 junction。
# 名字 → 它指向的真实目录。
_HOME_ALIASES = {
    "Application Data": ("AppData", "Roaming"),
    "Local Settings": ("AppData", "Local"),
    "My Documents": ("Documents",),
}


def _fake_junction(monkeypatch, link: Path) -> None:
    """把 isjunction 限制成只对 link 生效，用来在任意文件系统上验证判定分支。"""
    monkeypatch.setattr(
        paths.os.path,
        "isjunction",
        lambda p, _link=link: Path(p) == _link,
        raising=False,
    )


# --------------------------------------------------------------- 判定逻辑

def test_symlink_is_a_reparse_point(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")
    assert is_reparse_point(link) is True


def test_junction_is_a_reparse_point_even_though_is_symlink_says_no(monkeypatch, tmp_path: Path):
    """核心回归：is_symlink() 对 junction 返回 False，判定不能只靠它。"""
    fake = tmp_path / "Application Data"
    fake.mkdir()
    assert fake.is_symlink() is False  # 普通目录，本来就不是 link
    _fake_junction(monkeypatch, fake)
    assert is_reparse_point(fake) is True


def test_plain_directory_is_not_a_reparse_point(tmp_path: Path):
    plain = tmp_path / "logs"
    plain.mkdir()
    assert is_reparse_point(plain) is False


def test_deletion_protected_rejects_junctions(monkeypatch, tmp_path: Path):
    fake = tmp_path / "Local Settings"
    fake.mkdir()
    _fake_junction(monkeypatch, fake)
    assert is_deletion_protected(fake) is True


def test_deletion_protected_still_allows_plain_dirs(tmp_path: Path):
    """护栏不能过宽：普通目录必须保持可删，否则清理工具就没用了。"""
    plain = tmp_path / "logs"
    plain.mkdir()
    assert is_deletion_protected(plain) is False


# --------------------------------------------------------------- 真机回归

@pytest.mark.parametrize("name", sorted(_HOME_ALIASES))
def test_home_legacy_junctions_are_protected(name: str):
    """真机回归：家目录里的兼容性 junction 必须被保护规则拦下。

    环境里没有这个 junction 就跳过，而不是失败 —— 缺它说明这条风险不存在。
    """
    alias = Path.home() / name
    if not alias.exists() or not is_reparse_point(alias):
        pytest.skip(f"本机没有 {name} junction")
    assert is_deletion_protected(alias) is True


@pytest.mark.parametrize("name", sorted(_HOME_ALIASES))
def test_home_alias_and_target_share_one_key(name: str):
    """别名必须折叠成同一个 key。

    否则父子折叠去重会把 ``Application Data`` 与 ``AppData\\Roaming``
    当成两棵树：空间重复计量，同一份内容被两条路径各删一次。
    """
    home = Path.home()
    alias = home / name
    if not alias.exists() or not is_reparse_point(alias):
        pytest.skip(f"本机没有 {name} junction")
    real = home.joinpath(*_HOME_ALIASES[name])
    assert canonical_path_key(alias) == canonical_path_key(real)


def test_canonical_key_unchanged_for_plain_paths():
    """普通路径不能被 realpath 改写 —— 会影响所有既有的去重逻辑。"""
    p = Path.home() / ".codex" / "logs_2.sqlite"
    key = canonical_path_key(p)
    assert key == canonical_path_key(str(p))
    assert key.endswith(f".codex{os.sep}logs_2.sqlite")


# --------------------------------------------------------------- 真实 junction 行为

def test_real_junction_is_protected_and_not_measured_twice(tmp_path: Path, make_junction):
    """真 junction：既要被保护，也不能让父目录把目标内容算第二遍。"""
    real = tmp_path / "real"
    real.mkdir()
    (real / "payload.bin").write_bytes(b"\0" * 4096)
    link = tmp_path / "link"
    if not make_junction(link, real):
        pytest.skip("当前环境无法创建 junction")

    assert is_reparse_point(link) is True
    assert is_deletion_protected(link) is True
    assert paths.dir_size(tmp_path) == 4096


def test_executor_does_not_delete_through_a_junction(tmp_path: Path, make_junction):
    """最有价值的一条：清空目录时不能顺着 junction 删到目标目录里去。

    修复前 ``_clear_dir_contents`` 用的是 ``child.is_symlink()``，对 junction
    恒为 False，于是 ``shutil.rmtree(link)`` 会把 ``real/keep.txt`` 一起删掉。
    """
    real = tmp_path / "real"
    real.mkdir()
    keep = real / "keep.txt"
    keep.write_text("must survive", encoding="utf-8")

    container = tmp_path / "container"
    container.mkdir()
    junk = container / "junk.tmp"
    junk.write_text("junk", encoding="utf-8")

    link = container / "link"
    if not make_junction(link, real):
        pytest.skip("当前环境无法创建 junction")

    CleanExecutor()._clear_dir_contents(container, logging.getLogger("test-reparse"))

    assert keep.exists(), "junction 目标被删穿了"
    assert keep.read_text(encoding="utf-8") == "must survive"
    assert not junk.exists(), "普通文件应该被正常清掉"
