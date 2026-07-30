# Windows C 盘清理工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现可打包为 exe 的 Windows C 盘清理 GUI：手动扫描、推荐标注、一键安全/深度/勾选清理、永久删除与本地日志。

**Architecture:** CustomTkinter 界面 → Orchestrator 顺序调度扫描器 → 统一 `CleanItem` 模型 → Executor 永久删除并写 `logs/`。硬排除优先于一切推荐与勾选。

**Tech Stack:** Python 3.11+、customtkinter、pytest、PyInstaller（Windows x64）

## Global Constraints

- 操作范围仅限 `D:\workspace\tools\CDriveCleaner`
- **禁止**未经用户明确要求执行 `git commit` / `git push` / 删除用户文件（程序运行时删除除外）
- 永久删除，不进回收站；日志仅本地
- 首版扫描器顺序执行，不做定时任务
- 界面极简，功能优先
- 对比设计文档：`docs/superpowers/specs/2026-07-30-c-drive-cleaner-design.md`

---

## File Structure

```
CDriveCleaner/
  requirements.txt
  README.md
  build.spec
  src/
    __init__.py
    main.py
    models/items.py
    utils/disk.py
    utils/paths.py
    utils/logging_util.py
    scanners/base.py
    scanners/temp_files.py
    scanners/windows_update.py
    scanners/recycle_bin.py
    scanners/thumbnails.py
    scanners/browser_cache.py
    scanners/dev_cache.py
    scanners/installer_residue.py
    scanners/large_files.py
    scanners/old_downloads.py
    scanners/registry.py
    cleaner/executor.py
    app/orchestrator.py
    ui/app_window.py
  tests/
    test_items.py
    test_paths.py
    test_orchestrator.py
    test_executor.py
```

---

### Task 1: 项目骨架 + CleanItem + 路径/磁盘工具

**Files:**
- Create: `requirements.txt`, `src/__init__.py`, `src/models/items.py`, `src/utils/disk.py`, `src/utils/paths.py`, `tests/test_items.py`, `tests/test_paths.py`

**Interfaces:**
- Produces: `CleanItem`, `Risk`, `Recommendation`, `format_size()`, `get_c_drive_usage()`, `is_admin()`, `is_hard_excluded()`, `looks_like_project_dir()`, `dir_size()`, `safe_iter_files()`

- [ ] **Step 1: 写入依赖与模型/工具代码 + 测试**
- [ ] **Step 2: 运行** `python -m pytest tests/test_items.py tests/test_paths.py -v` **期望 PASS**
- [ ] **Step 3: 跳过 commit（用户禁止自动提交）**

---

### Task 2: 扫描器基类 + 安全类扫描器（Temp/更新缓存/回收站/缩略图）

**Files:**
- Create: `src/scanners/base.py`, `temp_files.py`, `windows_update.py`, `recycle_bin.py`, `thumbnails.py`, `registry.py`

**Interfaces:**
- Consumes: `CleanItem`, path helpers
- Produces: `Scanner` 协议 `name` + `scan(cancel_flag) -> list[CleanItem]`；`all_scanners()`

- [ ] **Step 1: 实现基类与四个扫描器，条目默认 `recommend`/`low`**
- [ ] **Step 2: 手动或单测验证 Temp 扫描返回列表且不含 System32**
- [ ] **Step 3: 跳过 commit**

---

### Task 3: 浏览器 / 开发缓存 / 安装包 / 大文件 / 旧下载

**Files:**
- Create: `browser_cache.py`, `dev_cache.py`, `installer_residue.py`, `large_files.py`, `old_downloads.py`；更新 `registry.py`

**Interfaces:**
- 大文件默认阈值 `200 * 1024**2`；旧下载 `90` 天；推荐分别为 recommend / recommend / optional / not_recommended / not_recommended

- [ ] **Step 1: 实现上述扫描器并注册**
- [ ] **Step 2: 确认硬排除与项目目录不进「建议删除」**
- [ ] **Step 3: 跳过 commit**

---

### Task 4: 删除执行器 + 本地日志 + Orchestrator

**Files:**
- Create: `src/utils/logging_util.py`, `src/cleaner/executor.py`, `src/app/orchestrator.py`, `tests/test_executor.py`, `tests/test_orchestrator.py`

**Interfaces:**
- `CleanExecutor.execute(items, cancel_flag) -> CleanResult`
- `Orchestrator.scan(progress_cb, cancel_flag) -> list[CleanItem]`
- `Orchestrator.items_for_safe_clean(items)`, `items_for_deep_clean(items)`
- 删除前再次 `is_hard_excluded`；失败跳过继续

- [ ] **Step 1: 实现执行器（用临时目录测删除）与编排**
- [ ] **Step 2: pytest 相关测试 PASS**
- [ ] **Step 3: 跳过 commit**

---

### Task 5: 极简 GUI + 入口

**Files:**
- Create: `src/ui/app_window.py`, `src/main.py`

**Interfaces:**
- 状态区 / 开始扫描 / 一键安全 / 深度 / 清理勾选 / 表格 / 合计 / 结果摘要
- 扫描与删除在后台线程，UI 用 `after` 更新
- 永久删除确认；深度或含高风险二次确认

- [ ] **Step 1: 实现窗口并 `python -m src.main` 可启动**
- [ ] **Step 2: 跳过 commit**

---

### Task 6: README + PyInstaller 配置

**Files:**
- Create: `README.md`, `build.spec`

- [ ] **Step 1: 写使用说明与打包命令**
- [ ] **Step 2: 若环境允许，试跑 `pyinstaller build.spec`（失败则记录原因，不阻塞功能）**
- [ ] **Step 3: 对照设计文档做遗漏检查**
- [ ] **Step 4: 跳过 commit**

---

## Spec Coverage Checklist

| 设计项 | Task |
|---|---|
| CleanItem 模型 | 1 |
| 硬排除 / 管理员 / C 盘空间 | 1, 4, 5 |
| Temp/更新/回收站/缩略图 | 2 |
| 浏览器/开发/安装包/大文件/旧下载 | 3 |
| 一键安全/深度/勾选映射 | 4, 5 |
| 永久删除 + 日志 | 4 |
| 极简 GUI | 5 |
| exe 打包说明 | 6 |
| 无定时 | 全计划未包含定时 |
