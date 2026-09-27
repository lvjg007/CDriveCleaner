"""家目录内「软件自己拉下来的东西」扫描。

与「AI 工具数据」的分工：那边按 AI 客户端收口，这边按**残留类型**收口，
覆盖非 AI 的软件 —— 应用更新器、编辑器扩展安装包、包管理器下载缓存、
日志与备份、自动化浏览器内核。

清单不是凭印象写的：先遍历整个家目录，找出「占空间且没有任何扫描器覆盖」
的位置，再逐层下钻把每个候选量准，最后才决定哪些收进来、算哪一档。
每一项的大小都在本机实测过。

分级沿用 ``tiers.py`` 的三档语义，三档都可勾选，删/留由用户在界面上确认。

安全边界：
- 目标是 junction/symlink 的一律跳过。家目录里有 117 个 junction，其中
  ``Application Data`` 指向 ``AppData\\Roaming``、``Local Settings`` 指向
  ``AppData\\Local`` —— 顺着它删一次等于清空整个 Roaming。
- 只收「软件自己下载/生成」的残留；已安装程序本体（如
  ``AppData\\Local\\Programs\\Python``、``Local\\OpenAI\\Codex``）不收，
  那属于卸载而不是清理。
"""
from __future__ import annotations

import time
from pathlib import Path

from src.models.items import CleanItem
from src.scanners.base import ProgressCb, Scanner, SCOPE_PROFILE
from src.scanners.tiers import (
    CAUTION,
    OPTIONAL,
    SAFE,
    TIER_RECOMMENDATION,
    TIER_SUFFIX,
    Target,
    group_targets,
    is_never_touch,
)
from src.utils.paths import dir_size_ex, is_hard_excluded, is_reparse_point, mark_scan_partial

# 单项目统计上限。定得比较宽是因为本扫描器的目标是「已装扩展」「模块数据」
# 这类小文件极多的目录：实测 .trae-cn/extensions 要 3.6s 才量得完 1.69 GB，
# 给 2s 只能量到 73 MB —— 差 23 倍的数字会直接把用户的删/留判断带偏。
_PER_TARGET_SECONDS = 5.0
# glob 展开出的目录通常较小，单独给一个更短的预算，避免一个 glob 吃掉整个配额
_GLOB_DIR_SECONDS = 1.5
# 整个扫描器的总预算，超了就标记为部分结果（UI 会提示）
_TOTAL_BUDGET_SECONDS = 60.0
# 目录项下限：低于此值不产出，避免几十 KB 的行把界面刷满
_MIN_BYTES = 256 * 1024
# glob 展开的下限更高：一个模式可能匹配几十个条目
_GLOB_MIN_BYTES = 1 * 1024 * 1024

# 大小统计被超时截断时的标注。必须说出来：小文件多的目录几秒钟只量得完一小部分，
# 实测 .trae-cn/extensions 真实 1.69 GB 而 2 秒只量到 56 MB。
_TRUNCATED_NOTE = "（大小统计超时，实际不小于此值）"

# 分类前缀，让本扫描器的分类在下拉里排在一起
_GROUP_PREFIX = "家目录 · "

# 凭据/密钥类路径名。这些永远不会被本扫描器产出，作为兜底防线：
# 后续往清单里加目标时若不小心写进来，_is_never_touch 会拦下。
_NEVER_TOUCH_NAMES = frozenset({
    "ntuser.dat",
    "ntuser.ini",
    ".ssh",
    ".aws",
    ".gnupg",
    ".gitconfig",
    ".npmrc",
    ".credentials.yaml",
    ".credentials.json",
    "credentials.json",
    "settings.json",
    "config.toml",
    ".env",
    "auth.json",
    "token",
    "tokens.json",
    "api_key",
})


class HomeResidueScanner(Scanner):
    """家目录里由软件下载/生成、可回收的缓存、日志与备份。"""

    name = "家目录残留"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_PROFILE

    # ------------------------------------------------------------------ 目标

    def _targets(self) -> list[Target]:
        home = Path.home()
        local = home / "AppData" / "Local"
        roaming = home / "AppData" / "Roaming"
        out: list[Target] = []

        # --- 应用更新器残留：electron-updater 把下好的安装包留在 <app>-updater 里 ---
        # 实测 9 个目录约 1.67 GB，是这份清单里性价比最高的一块。
        out += group_targets("更新器残留", _GROUP_PREFIX, [
            Target(
                "应用更新器残留",
                local,
                SAFE,
                "各应用自动更新时下载的安装包残留，下次更新会重新下载",
                pattern="*-updater",
            ),
        ])

        # --- 编辑器扩展安装包缓存：装完就只剩下载副本 ---
        for name, root in (
            ("Trae CN", roaming / "Trae CN"),
            ("TRAE SOLO CN", roaming / "TRAE SOLO CN"),
            ("Qoder", roaming / "Qoder"),
            ("VS Code", roaming / "Code"),
        ):
            out += group_targets("扩展安装包缓存", _GROUP_PREFIX, [
                Target(
                    f"{name} 扩展安装包缓存",
                    root / "CachedExtensionVSIXs",
                    SAFE,
                    "已安装扩展的下载副本；扩展本体已解压到 extensions 目录，删除不影响已装扩展",
                ),
            ])

        # --- 编辑器缓存与日志（与 Cursor/Void 同一套 Electron 目录结构）---
        for tool, root in (
            ("Trae CN", roaming / "Trae CN"),
            ("TRAE SOLO CN", roaming / "TRAE SOLO CN"),
            ("Qoder", roaming / "Qoder"),
        ):
            out += group_targets("编辑器缓存", _GROUP_PREFIX, [
                Target(f"{tool} 缓存", root / "Cache", SAFE, "Chromium 缓存，自动重建"),
                Target(f"{tool} CachedData", root / "CachedData", SAFE, "编译产物缓存，自动重建"),
                Target(f"{tool} GPU 缓存", root / "GPUCache", SAFE, "Chromium GPU 缓存，自动重建"),
                Target(f"{tool} Dawn 缓存", root / "DawnWebGPUCache", SAFE, "WebGPU 着色器缓存，自动重建"),
                Target(f"{tool} Dawn Graphite", root / "DawnGraphiteCache", SAFE, "WebGPU 着色器缓存，自动重建"),
                Target(f"{tool} 崩溃转储", root / "Crashpad", SAFE, "崩溃转储，排查完可删"),
                Target(f"{tool} 日志", root / "logs", SAFE, "运行日志"),
            ])
        out += group_targets("编辑器缓存", _GROUP_PREFIX, [
            Target(
                "Qoder 共享客户端缓存",
                roaming / "Qoder" / "SharedClientCache",
                OPTIONAL,
                "编辑器各组件共用的下载缓存（实测 737 MB），删除后首次启动会重新拉取",
            ),
        ])

        # --- 包与构建缓存 ---
        out += group_targets("包与构建缓存", _GROUP_PREFIX, [
            Target("uv 下载缓存", local / "uv" / "cache", OPTIONAL,
                   "uv 的 wheel/源码缓存，删除后需重新下载"),
            Target("uv 托管的 Python", roaming / "uv" / "python", OPTIONAL,
                   "uv 下载的 Python 解释器，删除后 uv 会按需重新下载"),
            Target("electron 下载缓存", local / "electron" / "Cache", SAFE,
                   "electron 二进制下载缓存，删除后需重新下载"),
            Target("electron-builder 缓存", local / "electron-builder" / "Cache", SAFE,
                   "打包工具缓存，会自动重建"),
            Target("node-gyp 头文件缓存", local / "node-gyp" / "Cache", SAFE,
                   "node-gyp 的 node 头文件缓存，会自动重建"),
            Target("Dart pub 缓存", local / "Pub" / "Cache", OPTIONAL,
                   "Dart 包缓存，删除后需重新下载"),
            Target("Go 构建缓存", local / "go-build", SAFE, "go build 缓存，会自动重建"),
            Target("Dart 分析服务缓存", local / ".dartServer" / ".analysis-driver", SAFE,
                   "分析驱动缓存，会自动重建"),
            Target("SonarQube 扫描缓存", home / ".sonar" / "cache", SAFE, "扫描器缓存，会自动重建"),
            Target("Gradle 临时目录", home / ".gradle" / ".tmp", SAFE, "Gradle 临时文件"),
            Target("Gradle daemon 日志", home / ".gradle" / "daemon", SAFE, "Gradle 守护进程日志"),
            Target("Gradle wrapper 发行包", home / ".gradle" / "wrapper", OPTIONAL,
                   "各版本 Gradle 发行包，删除后构建时重新下载"),
        ])

        # --- 自动化 / 浏览器运行时：都是下载来的浏览器内核 ---
        out += group_targets("浏览器运行时", _GROUP_PREFIX, [
            Target("Playwright 浏览器", local / "ms-playwright", OPTIONAL,
                   "Playwright 下载的 Chromium/FFmpeg；实测含 3 个 Chromium 版本，可只留最新，删除后需重新下载"),
            Target("Playwright Go 浏览器", local / "ms-playwright-go", OPTIONAL,
                   "Playwright-Go 下载的浏览器内核"),
            Target("rod 浏览器", roaming / "rod" / "browser", OPTIONAL, "go-rod 下载的 Chromium"),
            Target("Puppeteer 浏览器", home / ".cache" / "puppeteer", OPTIONAL,
                   "Puppeteer 下载的 Chromium"),
            Target("BurpSuite 内置浏览器", roaming / "BurpSuite" / "burpbrowser", OPTIONAL,
                   "Burp 内置 Chromium，删除后需重新下载"),
            Target("agent-browser Edge 配置", local / "agent-browser-edge-profile", SAFE,
                   "自动化浏览器临时配置，会自动重建"),
            Target("agent-browser CDP 配置", local / "agent-browser-cdp-profile", SAFE,
                   "自动化浏览器临时配置，会自动重建"),
            Target("Android SDK", local / "Android" / "Sdk", OPTIONAL,
                   "Android SDK 下载物，可用 sdkmanager --uninstall 精简；删除后需重新下载"),
        ])

        # --- 日志与备份残留 ---
        out += group_targets("日志与备份", _GROUP_PREFIX, [
            Target("cc-switch 数据库备份", home / ".cc-switch" / "backups", OPTIONAL,
                   "每天一份的数据库自动备份；实测 11 份约 800 MB，主库正常时可只留最近几份"),
            Target("Kiro 账号管理器代理日志",
                   roaming / "kiro-account-manager" / "proxy-logs.json", SAFE,
                   "代理请求日志（单文件 131 MB），删除后自动重建"),
            Target("IdeaShareKey 日志", local / "IdeaShareKey" / "log", SAFE, "投屏工具运行日志"),
            Target("微信盘日志", roaming / "WXDrive" / "logs", SAFE, "微信文件传输助手日志"),
            Target("OneDrive 日志", local / "Microsoft" / "OneDrive" / "logs", SAFE,
                   "OneDrive 客户端日志，实测 186 MB，删除后自动重建"),
            Target("Postman 缓存", roaming / "Postman" / "Cache", SAFE, "Chromium 缓存，自动重建"),
            Target("Clash Verge 更新缓存",
                   roaming / "io.github.clash-verge-rev.clash-verge-rev" / "update_cache", SAFE,
                   "内核更新下载残留"),
            Target("搜狗 PDF 更新残留", local / "sogoupdf" / "ktool_update", SAFE,
                   "更新器下载残留"),
            Target("WorkBuddy 日志", home / ".workbuddy" / "logs", SAFE, "运行日志"),
            Target("Everything 索引库", local / "Everything" / "Everything.db", OPTIONAL,
                   "文件名索引数据库，删除后 Everything 会重建（重建需要几分钟）"),
            Target("CodeBuddy 日志", home / ".codebuddy" / "logs", SAFE, "运行日志"),
            Target("Antigravity 备份", home / ".antigravity_cockpit" / "backups", OPTIONAL,
                   "账号配置备份"),
            Target("agents 技能备份", home / ".agents" / "skills.backups", OPTIONAL,
                   "技能目录的历史备份"),
        ])

        # --- 家目录杂项：散落的日志/转储/安装包 ---
        out += group_targets("家目录杂项", _GROUP_PREFIX, [
            Target("家目录残留日志", home, SAFE,
                   "家目录根下的进程重放日志，属运行时残留", pattern="replay_pid*.log"),
            Target("家目录崩溃转储", home, SAFE,
                   "家目录根下的进程崩溃转储", pattern="*.dmp"),
            Target("家目录孤立安装包", home, OPTIONAL,
                   "家目录根下遗留的安装程序", pattern="*.exe"),
            Target("Roaming 孤立安装包", roaming, OPTIONAL,
                   "Roaming 根目录遗留的安装程序/更新目录", pattern="*.exe"),
            Target("IdeaSnapshots 性能快照", home / "IdeaSnapshots", SAFE,
                   "IDE 启动性能快照，排查完可删"),
            Target("家目录 logs", home / "logs", SAFE, "家目录根下的日志目录"),
        ])

        # --- 已装扩展目录：删了编辑器功能就缺了，只列出来供确认 ---
        out += group_targets("已装扩展", _GROUP_PREFIX, [
            Target("Trae CN 已装扩展", home / ".trae-cn" / "extensions", CAUTION,
                   "已安装的编辑器扩展（实测 1.69 GB），删除后对应功能消失，建议在编辑器内管理"),
            Target("Void 已装扩展", home / ".void-editor" / "extensions", CAUTION,
                   "已安装的编辑器扩展，删除后对应功能消失，建议在编辑器内管理"),
            Target("VS Code 已装扩展", home / ".vscode" / "extensions", CAUTION,
                   "已安装的编辑器扩展，删除后对应功能消失，建议在编辑器内管理"),
        ])

        # --- 体积大、用途未确认：只列出来，由用户判断 ---
        out += group_targets("用途待确认", _GROUP_PREFIX, [
            Target("TRAE SOLO 模块数据", roaming / "TRAE SOLO CN" / "ModularData", CAUTION,
                   "含 ai-agent 的 database.db（386 MB）等模块数据，可能是会话/索引，确认前不建议删"),
            Target("Trae CN 模块数据", roaming / "Trae CN" / "ModularData", CAUTION,
                   "含 ai-agent 的 database.db 等模块数据，可能是会话/索引，确认前不建议删"),
            Target("pas 工作区", home / "pas_workspaces", CAUTION,
                   "未知软件的持久化工作区（实测 529 MB），用途待确认"),
            Target("dsh profiles", home / ".dsh" / "profiles", CAUTION,
                   "未知工具的 profile 目录（实测 373 MB），用途待确认"),
        ])

        return out

    # -------------------------------------------------------------- 安全护栏

    @staticmethod
    def _is_never_touch(path: Path) -> bool:
        """凭据/配置类路径一律不产出，防止后续改动误加进来。"""
        return is_never_touch(path, _NEVER_TOUCH_NAMES)

    # ------------------------------------------------------------------ 扫描

    def scan(
        self,
        cancel_flag: dict | None = None,
        progress: ProgressCb | None = None,
    ) -> list[CleanItem]:
        if progress:
            progress(self.name, 0.0)
        items: list[CleanItem] = []
        targets = self._targets()
        deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS
        seen_ids: set[str] = set()

        for i, t in enumerate(targets):
            if cancel_flag and cancel_flag.get("cancel"):
                break
            if progress:
                progress(f"{self.name}: {t.label}", i / max(len(targets), 1))

            if time.monotonic() >= deadline:
                mark_scan_partial(cancel_flag, self.name)
                break

            remaining = max(0.5, min(_PER_TARGET_SECONDS, deadline - time.monotonic()))
            for path, size, truncated in self._expand(t, cancel_flag, remaining):
                if size < _MIN_BYTES:
                    continue
                item_id = f"home:{t.label}" if t.pattern == "" else f"home:{t.label}:{path.name}"
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                reason = f"{t.label}：{t.reason}{TIER_SUFFIX[t.tier]}"
                if truncated:
                    reason += _TRUNCATED_NOTE
                # 三档都保持可勾选：分层只表达风险，删/留由用户在界面上确认
                items.append(
                    CleanItem.make(
                        id=item_id,
                        category=t.group or self.name,
                        path=str(path),
                        size_bytes=size,
                        recommendation=TIER_RECOMMENDATION[t.tier],
                        reason=reason,
                        needs_admin=t.admin,
                    )
                )

        if progress:
            progress(self.name, 1.0)
        return items

    def _expand(
        self,
        t: Target,
        cancel_flag: dict | None,
        max_seconds: float,
    ):
        """把一个目标展开成 (路径, 大小, 是否被超时截断) 序列。"""
        if self._is_never_touch(t.path):
            return
        if t.pattern:
            if not t.path.is_dir() or is_hard_excluded(t.path):
                return
            try:
                matches = sorted(t.path.glob(t.pattern))
            except OSError:
                return
            for m in matches:
                # 重解析点绝不产出：删它会打到目标目录上
                if is_hard_excluded(m) or is_reparse_point(m) or self._is_never_touch(m):
                    continue
                if m.is_dir():
                    size, truncated = dir_size_ex(
                        m, cancel_flag, max_seconds=min(max_seconds, _GLOB_DIR_SECONDS)
                    )
                elif m.is_file():
                    try:
                        size = m.stat().st_size
                    except OSError:
                        continue
                    truncated = False
                else:
                    continue
                if size < _GLOB_MIN_BYTES:
                    continue
                yield m, size, truncated
            return

        if not t.path.exists() or is_hard_excluded(t.path) or is_reparse_point(t.path):
            return
        size, truncated = dir_size_ex(t.path, cancel_flag, max_seconds=max_seconds)
        yield t.path, size, truncated
