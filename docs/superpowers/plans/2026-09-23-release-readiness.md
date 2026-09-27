# Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前发布阻塞问题并生成经过测试和启动冒烟验证的 Windows 单文件 EXE。

**Architecture:** 保持现有 `UI → Orchestrator → CleanExecutor` 架构。执行器继续用 `PartialCleanupError` 表示目录级部分失败；日志目录独立为运行时路径解析函数；窗口关闭只通过共享取消标志协调后台 worker，不强制终止线程。依赖和构建配置保持简单，不新增安装器或提权行为。

**Tech Stack:** Python 3.11+、pathlib、Tk/CustomTkinter、pytest、PyInstaller 6+、Windows x64。

## Global Constraints

- 不扩大扫描器或清理目录范围。
- 不对真实浏览器、微信、系统缓存或回收站执行删除；真实删除只在测试临时目录验证。
- `%LOCALAPPDATA%\\CDriveCleaner\\logs` 优先，失败时回退到 `%TEMP%\\CDriveCleaner\\logs`。
- 窗口关闭使用协作式取消，不强杀后台线程。
- `requirements.txt` 只保留运行依赖；测试和打包工具放入开发依赖文件。
- PyInstaller 不启用全局 UAC 提权。

---

### Task 1: Preserve partial temp cleanup results

**Files:**
- Modify: `src/cleaner/executor.py:200-233`
- Test: `tests/test_executor.py`

**Interfaces:**
- Consumes existing `CleanExecutor.execute()` and `PartialCleanupError(freed_bytes)`.
- Produces unchanged `CleanResult` semantics: partial failures increment `partial_count` and retain `freed_bytes`; the item remains retryable.

- [ ] **Step 1: Write the failing test**

Add a test that creates a temp directory with one stale file, patches the second child deletion to fail after the first succeeds, and asserts partial status and released bytes:

```python
def test_executor_temp_directory_preserves_bytes_on_late_failure(monkeypatch, tmp_path):
    root = tmp_path / "temp"
    root.mkdir()
    first = root / "first.tmp"
    second = root / "second.tmp"
    first.write_bytes(b"1234")
    second.write_bytes(b"567890")

    real_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if Path(path) == second:
            raise OSError("locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr("src.cleaner.executor.is_fresh", lambda _path: False)
    monkeypatch.setattr(Path, "unlink", unlink)
    item = CleanItem.make(
        id="temp-late-failure", category="系统临时文件", path=str(root),
        size_bytes=10, recommendation=Recommendation.RECOMMEND, reason="test",
    )

    result = CleanExecutor().execute([item])

    assert result.partial_count == 1
    assert result.fail_count == 1
    assert result.freed_bytes == 4
    assert result.removed_ids == []
    assert not first.exists()
    assert second.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m pytest tests/test_executor.py::test_executor_temp_directory_preserves_bytes_on_late_failure -q`

Expected: FAIL because `_clear_temp_contents()` currently raises `RuntimeError` without carrying the accumulated byte count, so `freed_bytes` remains `0` and `partial_count` remains `0`.

- [ ] **Step 3: Write minimal implementation**

Change the final failure branch in `_clear_temp_contents()` to raise `PartialCleanupError("；".join(failures[:3]), freed)` when `failures` is non-empty. Keep the existing `changed` handling and do not add a new result type.

- [ ] **Step 4: Run focused and full tests**

Run: `py -m pytest tests/test_executor.py::test_executor_temp_directory_preserves_bytes_on_late_failure tests/test_executor.py -q`

Expected: PASS, followed by `py -m pytest -q` with all tests passing.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_executor.py src/cleaner/executor.py
git commit -m "fix: preserve partial temp cleanup results"
```

### Task 2: Persist logs outside the PyInstaller extraction directory

**Files:**
- Modify: `src/utils/logging_util.py`
- Modify: `tests/test_executor.py`
- Create: `tests/test_logging.py`

**Interfaces:**
- Produces `logs_dir() -> Path` and `setup_clean_logger() -> tuple[logging.Logger, Path]` with the existing signatures.
- `logs_dir()` reads `LOCALAPPDATA` first and uses `TEMP`/`TMP` as fallback; tests can monkeypatch `os.environ`.

- [ ] **Step 1: Write failing path-selection tests**

Create tests covering configured local app data and fallback:

```python
def test_logs_dir_uses_localappdata(monkeypatch, tmp_path):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.delenv("TMP", raising=False)
    assert logs_dir() == local / "CDriveCleaner" / "logs"

def test_logs_dir_falls_back_to_temp_without_localappdata(monkeypatch, tmp_path):
    fallback = tmp_path / "temp"
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("TEMP", str(fallback))
    monkeypatch.delenv("TMP", raising=False)
    assert logs_dir() == fallback / "CDriveCleaner" / "logs"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_logging.py -q`

Expected: FAIL because the current implementation always uses the source repository `logs` directory.

- [ ] **Step 3: Implement the runtime directory resolver**

Use `os.environ.get("LOCALAPPDATA")`, then `TEMP`, then `TMP`, and create `<base>/CDriveCleaner/logs`. If the preferred directory cannot be created, try the fallback. Raise the original filesystem error only after both locations fail. Remove the `project_root()` dependency from `logs_dir()`; leave it only if another module imports it.

- [ ] **Step 4: Verify logger output path and full suite**

Add an assertion that `setup_clean_logger()` returns a path below the selected directory and closes/removes its handler. Run `py -m pytest tests/test_logging.py tests/test_executor.py -q` and then `py -m pytest -q`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_logging.py tests/test_executor.py src/utils/logging_util.py
git commit -m "fix: persist cleanup logs in user data"
```

### Task 3: Make window close cooperative while workers are active

**Files:**
- Modify: `src/ui/app_window.py:34-57,240-274,526-611`
- Create: `tests/test_ui_close.py`

**Interfaces:**
- Add `AppWindow._on_close_request()` and a small `_closing` boolean state.
- Existing scan/clean callbacks remain scheduled through `after`; callbacks check `_closing` before showing dialogs or touching destroyed widgets.

- [ ] **Step 1: Write isolated state tests before UI implementation**

Because a display may be unavailable in CI, test the close decision with a lightweight object created via `object.__new__(AppWindow)`, fake `after`/`destroy` methods, and monkeypatched `messagebox.askyesno`. Cover idle close, busy user cancellation, busy user rejection, and callback completion after cancellation.

```python
def test_close_when_idle_destroys_window():
    app = object.__new__(AppWindow)
    app._busy = False
    app._closing = False
    app.destroy = lambda: setattr(app, "destroyed", True)
    app.destroyed = False
    app._on_close_request()
    assert app.destroyed is True

def test_close_when_busy_sets_cancel_after_confirmation(monkeypatch):
    app = object.__new__(AppWindow)
    app._busy = True
    app._closing = False
    app.cancel_flag = {"cancel": False}
    app.destroy = lambda: setattr(app, "destroyed", True)
    app.destroyed = False
    monkeypatch.setattr("src.ui.app_window.messagebox.askyesno", lambda *_args, **_kwargs: True)
    app._on_close_request()
    assert app.cancel_flag["cancel"] is True
    assert app._closing is True
    assert app.destroyed is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_ui_close.py -q`

Expected: FAIL because `_on_close_request()` and `_closing` do not exist.

- [ ] **Step 3: Implement close protocol**

Initialize `_closing = False`, register `self.protocol("WM_DELETE_WINDOW", self._on_close_request)` after building the window, and implement:

```python
def _on_close_request(self) -> None:
    if self._closing:
        return
    if not self._busy:
        self._hide_preview()
        self.destroy()
        return
    if not messagebox.askyesno("任务进行中", "当前任务仍在运行，确认取消并退出吗？"):
        return
    self._closing = True
    self.cancel_flag["cancel"] = True
    self.progress_label.configure(text="正在取消，完成当前文件操作后退出…")
```

In `_scan_failed`, `_scan_done`, `_clean_failed`, and `_clean_done`, return early from dialogs/UI updates when `_closing` is true; after restoring worker state, call `self.destroy()` only from the Tk callback. Do not call `join()` from the UI thread.

- [ ] **Step 4: Run focused, import, and full tests**

Run: `py -m pytest tests/test_ui_close.py -q`; then `py -c "import src.ui.app_window"`; then `py -m pytest -q`.

Expected: focused tests and full suite pass; import exits with code 0.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_ui_close.py src/ui/app_window.py
git commit -m "fix: close UI cooperatively during background work"
```

### Task 4: Split runtime and development dependencies and update documentation

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`
- Modify: `README.md`
- Test: `tests/test_release_config.py`

**Interfaces:**
- Runtime install remains `pip install -r requirements.txt`.
- Development/build install becomes `pip install -r requirements-dev.txt`.

- [ ] **Step 1: Write configuration assertions**

Create a test that reads both files and asserts `customtkinter` appears only in runtime requirements, while `pytest` and `pyinstaller` appear in development requirements and not runtime requirements.

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_release_config.py -q`

Expected: FAIL because `requirements.txt` currently contains all three packages and `requirements-dev.txt` is absent.

- [ ] **Step 3: Update files**

Leave `customtkinter>=5.2.0` in `requirements.txt`; move `pytest>=7.0.0` and `pyinstaller>=6.0.0` into `requirements-dev.txt`. Update README commands for runtime setup, test setup, and `py -m PyInstaller --clean --noconfirm build.spec`.

- [ ] **Step 4: Run configuration and documentation checks**

Run: `py -m pytest tests/test_release_config.py -q`; then `git diff --check`.

- [ ] **Step 5: Commit**

```powershell
git add requirements.txt requirements-dev.txt README.md tests/test_release_config.py
git commit -m "chore: separate runtime and development dependencies"
```

### Task 5: Build and verify the release artifact

**Files:**
- Modify only generated build outputs: `build/`, `dist/`
- Verify: `build.spec`, `src/main.py`

**Interfaces:**
- Produces a fresh `dist/CDriveCleaner.exe` using the existing spec, without changing `uac_admin=False`.

- [ ] **Step 1: Run the complete source verification**

Run:

```powershell
py -m pytest -q
py -m compileall -q src tests
git diff --check
```

Expected: all tests pass, compileall exits 0, and diff check emits no errors.

- [ ] **Step 2: Build from a clean PyInstaller state**

Run: `py -m PyInstaller --clean --noconfirm build.spec`

Expected: exit code 0 and a newly timestamped `dist/CDriveCleaner.exe`.

- [ ] **Step 3: Run EXE startup smoke test**

Start the new EXE with a short PowerShell process check. Confirm it remains alive long enough to create the GUI, then close it via `CloseMainWindow()`/window close and verify the process exits. Do not trigger scan or cleanup buttons.

- [ ] **Step 4: Record artifact evidence**

Run `Get-Item dist/CDriveCleaner.exe | Select-Object FullName,Length,LastWriteTime` and `Get-FileHash dist/CDriveCleaner.exe -Algorithm SHA256`. Record test count, build exit code, file size, timestamp, and hash in the final response and append the high-value release decision to `.memory/today.md`.

- [ ] **Step 5: Commit source changes and release notes**

```powershell
git add src tests README.md requirements.txt requirements-dev.txt build.spec .memory/today.md
git commit -m "chore: prepare release artifact"
```

Do not commit generated `build/` or `dist/` unless the repository policy explicitly requires binary artifacts; report their paths and hashes instead.

