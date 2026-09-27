from pathlib import Path

from src.utils.paths import dir_size, is_deletion_protected, is_hard_excluded, looks_like_project_dir, safe_iter_files


def test_system32_excluded():
    assert is_hard_excluded(r"C:\Windows\System32") is True
    assert is_hard_excluded(r"C:\Windows\System32\drivers") is True


def test_winsxs_excluded():
    assert is_hard_excluded(r"C:\Windows\WinSxS") is True


def test_temp_not_excluded():
    assert is_hard_excluded(r"C:\Windows\Temp") is False


def test_system_report_file_is_deletion_protected():
    assert is_deletion_protected(r"C:\hiberfil.sys")
    assert is_deletion_protected(r"C:\pagefile.sys")
    assert is_deletion_protected(r"C:\Windows\Fonts")


def test_project_directory_is_deletion_protected(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text("{}", encoding="utf-8")
    cache = project / "cache"
    cache.mkdir()
    assert is_deletion_protected(cache)


def test_symlink_is_deletion_protected(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    assert is_deletion_protected(link)


def test_existing_paths_ignores_empty_candidates(tmp_path: Path):
    from src.utils.paths import existing_paths

    assert existing_paths(["", "   ", str(tmp_path)]) == [tmp_path]


def _short_path(path: Path) -> str:
    """取 Windows 8.3 短名；本机没启用 8.3 时原样返回。"""
    import ctypes
    from ctypes import wintypes

    get_short = ctypes.windll.kernel32.GetShortPathNameW
    get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short.restype = wintypes.DWORD
    size = 32768
    buffer = ctypes.create_unicode_buffer(size)
    length = get_short(str(path), buffer, size)
    return buffer.value if length and length < size else str(path)


def test_existing_paths_dedupes_windows_8_3_short_names(tmp_path: Path):
    """同一个目录的短名与长名必须合并成一个。

    真机上 ``%TEMP%`` 的值就是 8.3 短名形式
    （``C:\\Users\\LVJING~1\\AppData\\Local\\Temp``），与
    ``<家目录>\\AppData\\Local\\Temp`` 指的是**同一个目录**。

    不去重的后果是双倍报告：「系统临时文件」把同一个目录量两遍、报两条，
    用户看到双倍的占用，清理后释放的空间也对不上。
    """
    from src.utils.paths import existing_paths

    short = _short_path(tmp_path)
    if short.lower() == str(tmp_path).lower():
        import pytest

        pytest.skip("本机未启用 8.3 短名，无法构造这个场景")

    out = existing_paths([str(tmp_path), short])
    assert len(out) == 1, f"短名与长名没有合并: {out}"
    assert out[0] == tmp_path, "应当保留候选里第一次出现的写法用于展示"


def test_canonical_path_key_collapses_short_and_long_names(tmp_path: Path):
    """去重键本身必须把 8.3 别名归一到同一个值。"""
    from src.utils.paths import canonical_path_key

    short = _short_path(tmp_path)
    if short.lower() == str(tmp_path).lower():
        import pytest

        pytest.skip("本机未启用 8.3 短名，无法构造这个场景")

    assert canonical_path_key(short) == canonical_path_key(tmp_path)


def test_canonical_path_key_collapses_windows_aliases(monkeypatch, tmp_path: Path):
    from src.utils import paths

    monkeypatch.setattr(paths.os, "name", "nt")
    monkeypatch.setattr(paths, "_windows_long_path", lambda value: value.replace("SHORT~1", "LongName"))
    assert paths.canonical_path_key(r"C:\Users\SHORT~1\Temp") == paths.canonical_path_key(r"C:\Users\LongName\Temp")


def test_dir_size_marks_partial_timeout(tmp_path: Path):
    (tmp_path / "payload.bin").write_bytes(b"123")
    flag = {"_scan_current": "测试扫描"}
    assert dir_size(tmp_path, flag, max_seconds=-1) == 0
    assert flag["_scan_meta"]["partial_categories"] == {"测试扫描"}


def test_dir_size_ex_reports_truncation(tmp_path: Path):
    """截断时必须如实上报 —— 返回的是下界，不是真实大小。"""
    from src.utils.paths import dir_size_ex

    (tmp_path / "payload.bin").write_bytes(b"123")

    size, truncated = dir_size_ex(tmp_path, max_seconds=-1)
    assert size == 0
    assert truncated is True

    size, truncated = dir_size_ex(tmp_path, max_seconds=30)
    assert size == 3
    assert truncated is False


def test_dir_size_ex_does_not_follow_junctions(tmp_path: Path, make_junction):
    """junction 的内容算在目标目录头上，不能被父目录重复计量。"""
    from src.utils.paths import dir_size_ex

    real = tmp_path / "real"
    real.mkdir()
    (real / "payload.bin").write_bytes(b"\0" * 4096)
    link = tmp_path / "link"
    if not make_junction(link, real):
        import pytest

        pytest.skip("当前环境无法创建 junction")

    size, truncated = dir_size_ex(tmp_path, max_seconds=30)
    assert size == 4096
    assert truncated is False


def test_safe_iter_files_marks_partial_timeout(tmp_path: Path):
    (tmp_path / "payload.bin").write_bytes(b"123")
    flag = {"_scan_current": "测试文件扫描"}
    assert list(safe_iter_files(tmp_path, cancel_flag=flag, max_seconds=-1)) == []
    assert flag["_scan_meta"]["partial_categories"] == {"测试文件扫描"}


def test_project_marker(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert looks_like_project_dir(nested) is True


def test_profile_marker_does_not_protect_all_user_children(monkeypatch, tmp_path: Path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    cache = tmp_path / "AppData" / "Local" / "Temp"
    cache.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert looks_like_project_dir(cache) is False
