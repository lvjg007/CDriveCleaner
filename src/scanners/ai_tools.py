"""AI 编程工具 / 本地大模型运行时产生的数据扫描。

与「开发工具缓存」的区别：这里针对的是 AI 工具自己写出来的东西 ——
会话日志、CLI 临时目录、更新包残留、Electron 缓存、Agent 运行时。

分级原则（沿用项目既有语义 —— 与 large_files / old_downloads 的
「不建议，请确认后勾选」一致：分层只表达风险高低，不剥夺用户的选择权）：
- safe（建议删除）：工具会自动重建、不含用户内容的派生数据，默认勾选。
- optional（可选）：含用户内容或删了要重新下载的东西，默认不勾。
- caution（不建议）：凭据、配置、活跃状态库、模型权重 —— 删了工具可能起不来或丢历史，
  默认不勾、标记为不建议，但**仍可勾选**，由用户自行确认。

粒度刻意做到子目录/单文件，而不是整个 ``~/.codex``：
``~/.codex`` 里 ``logs_2.sqlite`` 是 2.6 GB 纯日志，
而 ``sessions/`` 是 4.6 GB 会话历史，两者必须区别对待。
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from src.models.items import CleanItem
from src.scanners.base import ProgressCb, Scanner, SCOPE_PROFILE
from src.scanners.tiers import (
    CAUTION as _CAUTION,
    OPTIONAL as _OPTIONAL,
    SAFE as _SAFE,
    TIER_RECOMMENDATION as _TIER_RECOMMENDATION,
    TIER_SUFFIX as _TIER_SUFFIX,
    Target as _Target,
)
from src.utils.paths import dir_size, is_hard_excluded, mark_scan_partial

# 单项目大小统计上限：命中后按已统计部分计，避免 7 GB 的库把扫描拖死
_PER_TARGET_SECONDS = 2.5
# 整个扫描器的总预算，超了就标记为部分结果（UI 会提示）
_TOTAL_BUDGET_SECONDS = 15.0
# 目录项下限：低于此值不产出，避免 144 B 这种没有信息量的行
_MIN_BYTES = 256 * 1024
# glob 展开的下限更高：一个逻辑目标可能匹配几十个 .bak，太低会刷屏
_GLOB_MIN_BYTES = 1 * 1024 * 1024

# 凭据/密钥类文件名。这些路径永远不会被本扫描器产出，作为兜底防线。
# 改动扫描目标时若不小心把它们写进来，_is_never_touch 会拦下。
_NEVER_TOUCH_NAMES = {
    "oauth_creds.json",
    ".credentials.json",
    "credentials.json",
    "auth.json",
    "auth.toml",
    "api_key",
    "apikey",
    "token",
    "tokens.json",
    ".env",
    "installation_id",
    "settings.json",
    "config.toml",
}


# 分类前缀，让所有 AI 客户端在分类下拉里排在一起、且排在 CJK 分类之前
_GROUP_PREFIX = "AI · "


class AiToolsScanner(Scanner):
    """AI 工具与本地模型运行时的日志/缓存/历史数据。"""

    name = "AI 工具数据"
    #: 见 base.SCOPE_* 说明
    drive_scope = SCOPE_PROFILE

    # ------------------------------------------------------------------ 目标

    @staticmethod
    def _group(name: str, targets: list[_Target]) -> list[_Target]:
        """给一组目标打上客户端分类 —— 界面上按此分列，方便逐客户端勾选。"""
        return [replace(t, group=_GROUP_PREFIX + name) for t in targets]

    def _targets(self) -> list[_Target]:
        home = Path.home()
        local = home / "AppData" / "Local"
        roaming = home / "AppData" / "Roaming"
        cursor = roaming / "Cursor"
        kiro = roaming / "Kiro"
        void = roaming / "Void"
        out: list[_Target] = []

        # --- Claude Code ---
        claude = home / ".claude"
        out += self._group("Claude Code", [
            _Target("Claude Code 遥测", claude / "telemetry", _SAFE, "遥测上报队列，可随时清空"),
            _Target("Claude Code 缓存", claude / "cache", _SAFE, "CLI 本地缓存，会自动重建"),
            _Target("Claude Code shell 快照", claude / "shell-snapshots", _SAFE, "shell 环境快照，会自动重建"),
            _Target("Claude Code 粘贴缓存", claude / "paste-cache", _SAFE, "粘贴内容暂存，会自动重建"),
            _Target("Claude Code 项目历史", claude / "projects", _OPTIONAL, "会话记录，删除后无法恢复历史对话"),
            _Target("Claude Code 文件历史", claude / "file-history", _OPTIONAL, "编辑前快照，删除后失去回滚能力"),
            _Target("Claude Code 插件", claude / "plugins", _OPTIONAL, "已装插件，删除后需重新安装"),
        ])

        # --- OpenAI Codex CLI ---
        codex = home / ".codex"
        out += self._group("Codex", [
            _Target("Codex 日志库", codex / "logs_2.sqlite", _SAFE, "运行日志数据库，删除后自动重建"),
            _Target("Codex 临时目录", codex / ".tmp", _SAFE, "CLI 临时文件"),
            _Target(
                "Codex 旧备份残留",
                codex,
                _SAFE,
                "历史 .bak 备份文件，属改配置时留下的残留",
                pattern="*.bak*",
            ),
            _Target("Codex 会话历史", codex / "sessions", _OPTIONAL, "历史会话记录，删除后无法恢复"),
            _Target("Codex 线程历史库", codex / "thread_history_1.sqlite", _OPTIONAL, "线程历史数据库，删除后丢失历史"),
            _Target("Codex 沙箱运行时", codex / ".sandbox-bin", _OPTIONAL, "沙箱二进制，删除后需重新下载"),
            _Target("Codex 沙箱数据", codex / ".sandbox", _OPTIONAL, "沙箱工作目录"),
            _Target("Codex 插件", codex / "plugins", _OPTIONAL, "已装插件，删除后需重新安装"),
        ])

        # --- Cursor ---
        out += self._group("Cursor", [
            _Target("Cursor 日志", cursor / "logs", _SAFE, "运行日志"),
            _Target("Cursor 调试数据", cursor / "debugging-data", _SAFE, "调试采样数据"),
            _Target("Cursor GPU 缓存", cursor / "GPUCache", _SAFE, "Chromium GPU 缓存，自动重建"),
            _Target("Cursor Dawn 缓存", cursor / "DawnWebGPUCache", _SAFE, "WebGPU 着色器缓存，自动重建"),
            _Target("Cursor Dawn Graphite", cursor / "DawnGraphiteCache", _SAFE, "WebGPU 着色器缓存，自动重建"),
            _Target("Cursor 代码缓存", cursor / "Code Cache", _SAFE, "V8 代码缓存，自动重建"),
            _Target("Cursor CachedData", cursor / "CachedData", _SAFE, "编译产物缓存，自动重建"),
            _Target("Cursor 进程监控", cursor / "process-monitor", _SAFE, "进程监控采样数据"),
            _Target("Cursor 本地快照", cursor / "snapshots", _OPTIONAL, "本地文件快照，删除后失去撤销历史"),
            _Target("Cursor 编辑历史", cursor / "User" / "History", _OPTIONAL, "文件编辑历史，删除后失去撤销历史"),
            _Target(
                "Cursor Agent 运行时",
                cursor / "User" / "globalStorage" / "anysphere.cursor-agent-worker",
                _OPTIONAL,
                "Agent CLI 运行时，删除后需重新下载",
            ),
            _Target(
                "Cursor 状态库备份",
                cursor / "User" / "globalStorage" / "state.vscdb.backup",
                _OPTIONAL,
                "全局状态库的旧备份，主库正常时可删",
            ),
            _Target(
                "Cursor 全局状态库",
                cursor / "User" / "globalStorage" / "state.vscdb",
                _CAUTION,
                "Cursor 活跃状态库，实测无空洞、非缓存膨胀；"
                "删除会丢失全部聊天记录与工作区状态，建议在 Cursor 内清理历史会话",
            ),
        ])

        # --- 其它 AI 编辑器（同一套 Electron 缓存结构）---
        for tool, root in (
            ("Kiro", kiro),
            ("Void", void),
            ("Windsurf", roaming / "Windsurf"),
            ("Trae", roaming / "Trae"),
            ("Zed", roaming / "Zed"),
            ("PearAI", roaming / "PearAI"),
        ):
            out += self._group(tool, [
                _Target(f"{tool} 日志", root / "logs", _SAFE, "运行日志"),
                _Target(f"{tool} 缓存", root / "Cache", _SAFE, "Chromium 缓存，自动重建"),
                _Target(f"{tool} CachedData", root / "CachedData", _SAFE, "编译产物缓存，自动重建"),
                _Target(f"{tool} GPU 缓存", root / "GPUCache", _SAFE, "Chromium GPU 缓存，自动重建"),
                _Target(f"{tool} Dawn 缓存", root / "DawnWebGPUCache", _SAFE, "WebGPU 着色器缓存，自动重建"),
                _Target(f"{tool} Dawn Graphite", root / "DawnGraphiteCache", _SAFE, "WebGPU 着色器缓存，自动重建"),
            ])

        # --- VS Code 系 AI 扩展（聊天记录与索引都存在 globalStorage 里）---
        vscode_gs = roaming / "Code" / "User" / "globalStorage"
        out += self._group("VS Code 扩展", [
            _Target(
                "Cline 对话历史",
                vscode_gs / "saoudrizwan.claude-dev",
                _OPTIONAL,
                "Cline 扩展的对话与任务记录，删除后无法恢复",
            ),
            _Target(
                "Roo Code 对话历史",
                vscode_gs / "rooveterinaryinc.roo-cline",
                _OPTIONAL,
                "Roo Code 扩展的对话与任务记录，删除后无法恢复",
            ),
            _Target(
                "Continue 扩展数据",
                vscode_gs / "continue.continue",
                _OPTIONAL,
                "Continue 扩展的索引与对话数据",
            ),
            _Target(
                "Copilot Chat 历史",
                vscode_gs / "github.copilot-chat",
                _OPTIONAL,
                "Copilot Chat 会话记录，删除后无法恢复",
            ),
        ])

        # --- Qwen Code ---
        qwen = home / ".qwen"
        out += self._group("Qwen Code", [
            _Target("Qwen 更新包缓存", qwen / "updates", _SAFE, "CLI 自更新下载残留，可安全删除"),
            _Target("Qwen 临时目录", qwen / "tmp", _SAFE, "CLI 临时文件"),
            _Target("Qwen 项目历史", qwen / "projects", _OPTIONAL, "会话记录，删除后无法恢复"),
            _Target("Qwen 文件历史", qwen / "file-history", _OPTIONAL, "编辑前快照，删除后失去回滚能力"),
        ])

        # --- Gemini CLI / Antigravity ---
        gemini = home / ".gemini"
        antig = gemini / "antigravity-cli"
        out += self._group("Gemini CLI", [
            _Target("Gemini 临时目录", gemini / "tmp", _SAFE, "CLI 临时文件"),
            _Target("Antigravity 日志", antig / "cli.log", _SAFE, "CLI 运行日志"),
            _Target("Antigravity 缓存", antig / "cache", _SAFE, "本地缓存，自动重建"),
            _Target("Antigravity 崩溃转储", antig / "crashes", _SAFE, "崩溃转储，排查完可删"),
            _Target("Antigravity 对话记录", antig / "conversations", _OPTIONAL, "会话记录，删除后无法恢复"),
            _Target("Antigravity 记忆库", antig / "brain", _OPTIONAL, "Agent 长期记忆，删除后丢失上下文"),
        ])

        # --- 其它 AI 编码 CLI（数据都放在用户目录的点目录里）---
        for tool, label, root, why in (
            ("Aider", "Aider 历史", home / ".aider", "Aider 会话与缓存"),
            ("Codeium", "Codeium 数据", home / ".codeium", "Codeium 索引与缓存"),
            ("Tabnine", "Tabnine 数据", home / ".tabnine", "Tabnine 本地索引"),
            ("Augment", "Augment 数据", home / ".augment", "Augment 索引与缓存"),
            ("Cody", "Cody 数据", home / ".cody", "Sourcegraph Cody 索引与缓存"),
            ("通义灵码", "通义灵码数据", home / ".lingma", "通义灵码索引与缓存"),
        ):
            out += self._group(tool, [_Target(label, root, _OPTIONAL, f"{why}，删除后需重新建立索引")])

        # --- 本地大模型运行时 ---
        out += self._group("本地模型", [
            _Target("Ollama 模型权重", home / ".ollama" / "models", _CAUTION, "模型权重，删了要重新下载数十 GB，建议用 ollama rm 逐个管理"),
            _Target("LM Studio 模型", home / ".lmstudio" / "models", _CAUTION, "模型权重，请用 LM Studio 内部管理"),
            _Target("HuggingFace 模型缓存", home / ".cache" / "huggingface", _CAUTION, "模型缓存，删除后需重新下载"),
        ])

        return out

    # -------------------------------------------------------------- 安全护栏

    @staticmethod
    def _is_never_touch(path: Path) -> bool:
        """凭据/配置类路径一律不产出，防止后续改动误加进来。"""
        name = path.name.lower()
        if name in _NEVER_TOUCH_NAMES:
            return True
        return any(part.lower() in _NEVER_TOUCH_NAMES for part in path.parts)

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
            for path, size in self._expand(t, cancel_flag, remaining):
                if size < _MIN_BYTES:
                    continue
                item_id = f"ai:{t.label}" if t.pattern == "" else f"ai:{t.label}:{path.name}"
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                # 三层都保持可勾选：分层只表达风险，删/留由用户在界面上确认
                items.append(
                    CleanItem.make(
                        id=item_id,
                        # 按 AI 客户端分列，界面上可逐个客户端筛选、逐个勾选
                        category=t.group or self.name,
                        path=str(path),
                        size_bytes=size,
                        recommendation=_TIER_RECOMMENDATION[t.tier],
                        reason=f"{t.label}：{t.reason}{_TIER_SUFFIX[t.tier]}",
                        needs_admin=t.admin,
                    )
                )

        if progress:
            progress(self.name, 1.0)
        return items

    def _expand(
        self,
        t: _Target,
        cancel_flag: dict | None,
        max_seconds: float,
    ):
        """把一个目标展开成 (路径, 大小) 序列。"""
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
                if not m.is_file() or is_hard_excluded(m) or self._is_never_touch(m):
                    continue
                try:
                    size = m.stat().st_size
                except OSError:
                    continue
                if size < _GLOB_MIN_BYTES:
                    continue
                yield m, size
            return

        if not t.path.exists() or is_hard_excluded(t.path):
            return
        size = dir_size(t.path, cancel_flag, max_seconds=max_seconds)
        yield t.path, size
