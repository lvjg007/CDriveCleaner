# 安全清理与状态透明化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 阻止高风险路径误删，并让扫描/清理取消与部分失败在模型、编排和 UI 中可见。

**Architecture:** 保持 `CleanItem`、`CleanResult`、`Orchestrator` 和 `CleanExecutor` 的现有调用关系；在模型增加保护/状态字段，在路径工具集中执行保护判定，在执行器和 UI 消费这些状态。测试覆盖核心纯逻辑，不依赖真实 Tk 窗口。

**Tech Stack:** Python 3.11+、pytest、现有 pathlib/dataclasses/customtkinter。

## Global Constraints

- 保留 Windows C 盘硬排除和逐项错误记录。
- 不新增依赖，不改变现有扫描器 `scan()` 签名。
- 不执行 git commit；所有修改保持在当前工作区。

---

### Task 1: 执行层保护与清理状态

**Files:**
- Modify: `src/models/items.py`
- Modify: `src/utils/paths.py`
- Modify: `src/cleaner/executor.py`
- Test: `tests/test_executor.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- `CleanItem.make(..., deletable: bool = True, protection_reason: str = "")` 继续兼容现有调用。
- 新增 `is_deletion_protected(path)`，返回 `bool`。
- `CleanResult` 新增 `cancelled: bool`、`remaining_count: int`。

- [x] **Step 1: Write failing tests** for protected report items, protected system file paths, symlink paths, pre-cancelled execution, and remaining count.
- [x] **Step 2: Run focused tests** and verify each fails for the missing behavior.
- [x] **Step 3: Implement model/path guards and executor status accounting.**
- [x] **Step 4: Run focused tests** and verify they pass.

### Task 2: 扫描编排与 UI 状态

**Files:**
- Modify: `src/app/orchestrator.py`
- Modify: `src/ui/app_window.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- `Orchestrator` exposes `last_scan_cancelled` and `last_scan_fast` after `scan()` without changing its return type.
- UI uses these fields to label results and disable cleaning after cancellation.

- [x] **Step 1: Write failing tests** for fast/cancelled scan metadata and fake scanner progress aggregation.
- [x] **Step 2: Run focused tests** and verify the metadata assertions fail.
- [x] **Step 3: Implement metadata tracking, admin column, cancellation labels, and failure summary display.**
- [x] **Step 4: Run focused tests** and a compile check.

### Task 3: Full regression verification

**Files:**
- Modify: `.memory/today.md`, `.memory/progress.json`

- [x] **Step 1: Run `py -m pytest -q`.**
- [x] **Step 2: Run `py -m compileall -q src tests`.**
- [x] **Step 3: Review the diff for unrelated changes and update acceptance criteria with evidence.**
