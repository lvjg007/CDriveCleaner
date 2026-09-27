# 报告项范围与物理路径去重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让报告项、可清理项和重复物理路径在扫描结果中保持一致。

**Architecture:** 继续使用 `CleanItem.deletable` 作为跨 UI/执行器的边界；在路径工具提供不解析符号链接的规范化键；扫描器只为明确缓存子目录保留可清理标记，编排层负责最终去重和清理队列过滤。

**Tech Stack:** Python 3.11+、pytest、pathlib。

## Global Constraints

- 不改变现有 `Scanner.scan()` 签名和清理入口。
- 不新增依赖；保护逻辑必须在执行器之外再由编排层过滤。
- 不执行 git commit。

---

### Task 1: 报告项与应用目录范围

**Files:**
- Modify: `src/scanners/extension_stats.py`
- Modify: `src/scanners/app_junk.py`
- Modify: `src/scanners/dev_cache.py`
- Modify: `src/scanners/office_comms.py`
- Test: `tests/test_phase2.py`
- Test: `tests/test_scope_safety.py`

- [x] 为扩展名汇总和整目录应用项设置 `deletable=False` 与保护原因。
- [x] 为明确缓存子目录保留可清理标记。
- [x] 用扫描器边界测试验证两类结果。

### Task 2: 物理路径去重与清理队列

**Files:**
- Modify: `src/utils/paths.py`
- Modify: `src/app/orchestrator.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_executor.py`

- [x] 增加不解析符号链接的规范化路径键。
- [x] 按 ID、再按物理路径去重，并优先保留更安全的结果。
- [x] 清理入口过滤不可删除报告项。

### Task 3: 文档与验证

**Files:**
- Modify: `README.md`

- [x] 说明报告项保护、应用整目录范围和重复路径去重行为。
- [x] 运行 `py -m pytest -q`、`py -m compileall -q src tests` 和 `git diff --check`。

### Task 4: 父子目录有效范围

**Files:**
- Modify: `src/models/items.py`
- Modify: `src/app/orchestrator.py`
- Modify: `src/cleaner/executor.py`
- Modify: `src/ui/treemap_window.py`
- Modify: `src/ui/app_window.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_executor.py`
- Test: `tests/test_phase2_remain.py`

- [x] 同时可删除的父子目录只保留父目录执行；报告父目录不覆盖可清理子目录。
- [x] 执行器对直接调用再次归并，避免顺序导致重复释放统计。
- [x] 占用图和清理后列表使用有效范围。
- [x] 运行完整测试、编译检查和 UI 模块导入检查。

### Task 5: 扫描时限状态与无窗口 UI 回归

**Files:**
- Modify: `src/utils/paths.py`
- Modify: `src/app/orchestrator.py`
- Modify: `src/ui/app_window.py`
- Modify: `src/scanners/large_files.py`
- Modify: `src/scanners/duplicates.py`
- Modify: `src/scanners/extension_stats.py`
- Modify: `src/scanners/empty_folders.py`
- Test: `tests/test_paths.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_scope_safety.py`

- [x] 目录/文件遍历和有独立 deadline 的扫描器记录部分结果分类。
- [x] 编排层暴露 `last_scan_partial_categories`，UI 显示部分结果并在确认中提示。
- [x] 扫描线程使用主线程快照，避免后台读取 Tk 控件。
- [x] 覆盖无窗口筛选、排序、选择、取消状态和部分结果状态测试。
