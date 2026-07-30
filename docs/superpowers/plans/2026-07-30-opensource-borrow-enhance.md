# 开源清理工具借鉴增强 Implementation Plan

> **For agentic workers:** 按 Task 顺序实施。步骤用 checkbox 跟踪。未经用户明确要求 **禁止 git commit**。

**Goal:** 吸收 WinDirStat / Capacitra / BitBroom / DiskMap / WindowsCleaner / BleachBit / Scour / NeatDisk 的扫描覆盖与交互优点，分阶段增强本仓库 `CDriveCleaner`。

**Architecture:** 继续「扫描器注册表 + CleanItem + Orchestrator + 极简 GUI」；新增类别以独立 Scanner 或扩展现有 Scanner；「占空间报告」类只展示不默认删除。

**Tech Stack:** Python 3.11+、customtkinter、pytest、现有 `src/scanners/*`

## Global Constraints

- 操作范围仅 `D:\workspace\tools\CDriveCleaner`
- 永久删除策略保持（用户已选）；新增项仍要推荐分级与硬排除
- 不做：注册表清理、强制 Prefetch 默认删除、删 `C:\Windows\Installer` 整库、清浏览器密码/Cookie
- 不上传网络；不自动提交 git

---

## 竞品扫描覆盖对照（摘要）

| 来源 | 主要扫描/清理项 | 可借鉴优点 |
|---|---|---|
| **BitBroom** | Temp/更新缓存/WER/Defender 日志/缩略图；多浏览器；Discord/Slack/Teams/Zoom/Spotify/Adobe/OBS；GPU 着色器；Steam/Epic 等游戏缓存；开发缓存；Space Hogs（休眠/页面文件/WSL vhdx/搜索索引报告）；重复文件；空目录；dry-run | 分类极全；PathGuard；24h 新文件跳过；打开资源管理器；占坑报告 |
| **DiskMap / Capacitra / WinDirStat** | 目录占用分析、大文件 TopN、类型统计、treemap、回收站删除、Reveal | 排序、悬停详情、导出、打开位置（部分已做） |
| **Scour / NeatDisk** | 重复文件、空目录、旧文件、驱动存储清理、临时/零字节 | 空目录、旧文件、驱动冗余 |
| **BleachBit** | 系统日志/临时/回收站；Explorer 最近项/缩略图；Office/第三方应用专用规则 | 应用级规则清单 |
| **WindowsCleaner** | 面向 C 盘爆红一键清理 | 场景定位一致 |

### 本工具已有

临时/更新缓存/回收站/缩略图/浏览器/系统扩展/开发缓存/安装包/媒体/旧下载/大文件/软件缓存/微信定制/排序/悬停/右键打开

### 缺口（本计划要补）

1. GPU 着色器缓存、更多办公/通讯/游戏缓存  
2. Defender 日志、Office 缓存、Teams/Zoom/Slack/Spotify/OBS/Adobe 等  
3. Space Hogs **仅报告**（休眠文件/页面文件/WSL·Docker vhdx 体积提示）  
4. 扫描时跳过 24h 内新建/修改的临时文件（更安全）  
5. UI：按分类筛选、导出 CSV、模拟清理（dry-run 只记日志不删）  
6. （后续）空目录扫描、重复文件、TopN 文件类型汇总 —— 放 Phase 2

---

## File Structure（新增/修改）

```
docs/superpowers/plans/2026-07-30-opensource-borrow-enhance.md  # 本计划
src/scanners/gpu_caches.py          # NVIDIA/AMD/Intel 着色器
src/scanners/office_comms.py        # Office/Teams/Zoom/Slack/Spotify/OBS/Adobe
src/scanners/game_caches.py         # Epic/EA/Battle.net/Ubisoft + Steam 细化
src/scanners/space_hogs.py          # 占空间报告（不建议默认删）
src/utils/freshness.py              # 24h 新鲜文件跳过
src/cleaner/executor.py             # dry_run 支持
src/app/orchestrator.py             # dry_run 透传；筛选辅助
src/scanners/registry.py            # 注册新扫描器
src/ui/app_window.py                # 分类筛选、导出 CSV、模拟清理
tests/test_freshness.py
tests/test_space_hogs.py
tests/test_dry_run.py
README.md                           # 更新借鉴表
```

---

### Task 1: 扩展缓存扫描器（GPU + 办公通讯 + 游戏）

**Files:** Create `gpu_caches.py`, `office_comms.py`, `game_caches.py`; Modify `registry.py`

**Produces:** 新 CleanItem 类别，默认多为 `recommend`/`optional`

- [x] Step 1: 实现三个扫描器（已知路径 + dir_size 限时）
- [x] Step 2: 注册到 `all_scanners()`
- [x] Step 3: `pytest` 相关冒烟 / 导入通过

---

### Task 2: Space Hogs 报告扫描器（只展示）

**Files:** Create `space_hogs.py`, `tests/test_space_hogs.py`

**Produces:** `recommendation=not_recommended`，原因写清「官方工具处理，勿直接删」

覆盖：`hiberfil.sys`、`pagefile.sys`、常见 `*.vhdx`（WSL/Docker）、提示 WinSxS/DriverStore 体积（若可统计）

- [x] Step 1: 实现 + 单测（路径存在性逻辑可用 mock/tmp）
- [x] Step 2: 注册扫描器

---

### Task 3: 临时类 24h 新鲜文件保护

**Files:** Create `utils/freshness.py`; Modify `temp_files.py` / `executor` 清理 Temp 时跳过新文件；`tests/test_freshness.py`

- [x] Step 1: `is_fresh(path, hours=24)` 
- [x] Step 2: Temp 清理改为逐文件删并跳过 fresh（目录清空逻辑增强）
- [x] Step 3: 测试 PASS

---

### Task 4: Dry-run（模拟清理）+ 导出 CSV + 分类筛选 UI

**Files:** Modify `executor.py`, `orchestrator.py`, `app_window.py`

- [x] Step 1: `CleanExecutor.execute(..., dry_run=False)` 写日志但不删；UI 增加「模拟清理勾选项」
- [x] Step 2: 「导出结果 CSV」
- [x] Step 3: 分类下拉筛选（全部 / 某一 category）
- [x] Step 4: 手动冒烟 / pytest dry-run

---

### Task 5: Phase 2

- [x] 空目录扫描（`empty_folders.py`）
- [x] 重复文件（`duplicates.py`，下载/桌面等用户目录）
- [x] 扩展名占用汇总（`extension_stats.py`，WinDirStat 风格报告）
- [x] 简单 treemap（`ui/treemap.py` + 「占用图」按钮，按分类面积）
- [x] 快速扫描开关（跳过慢扫描器；**原生 MFT 解析仍未做**，作为后续专项）
- [x] 回收站删除模式（勾选「进回收站」，默认仍永久删除）

---

## 实施顺序与验收

1. Task1 → 扫完列表里能看到 GPU/办公/游戏项  
2. Task2 → 能看到休眠/vhdx 等报告项且默认不勾选  
3. Task3 → Temp 下新建文件不会被删  
4. Task4 → 模拟清理日志有记录、文件还在；CSV 能导出；筛选可用  

**跳过 commit（用户禁止自动提交）。**
