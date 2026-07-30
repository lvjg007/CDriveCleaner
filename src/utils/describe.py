from __future__ import annotations

from pathlib import Path

_EXT_ZH: dict[str, str] = {
    ".exe": "可执行程序/安装包",
    ".msi": "Windows 安装包",
    ".msix": "应用安装包",
    ".iso": "光盘镜像",
    ".img": "磁盘镜像",
    ".zip": "压缩包",
    ".rar": "压缩包",
    ".7z": "压缩包",
    ".tar": "压缩包",
    ".gz": "压缩包",
    ".cab": "系统压缩柜文件",
    ".dll": "动态链接库（慎删）",
    ".sys": "系统驱动文件（勿删）",
    ".log": "日志文件",
    ".tmp": "临时文件",
    ".temp": "临时文件",
    ".bak": "备份文件",
    ".old": "旧版残留",
    ".dmp": "崩溃转储",
    ".mdmp": "崩溃转储",
    ".etl": "跟踪日志",
    ".db": "数据库/缓存库",
    ".sqlite": "SQLite 数据库",
    ".cache": "缓存文件",
    ".dat": "数据文件",
    ".bin": "二进制数据",
    ".pkg": "安装包数据",
    ".vhd": "虚拟硬盘",
    ".vhdx": "虚拟硬盘",
    ".vmdk": "虚拟机磁盘",
    ".ova": "虚拟机镜像",
    ".mp4": "视频",
    ".mkv": "视频",
    ".avi": "视频",
    ".mov": "视频",
    ".wmv": "视频",
    ".mp3": "音频",
    ".flac": "音频",
    ".wav": "音频",
    ".jpg": "图片",
    ".jpeg": "图片",
    ".png": "图片",
    ".gif": "图片",
    ".webp": "图片",
    ".psd": "图片工程",
    ".pdf": "PDF 文档",
    ".doc": "Word 文档",
    ".docx": "Word 文档",
    ".xls": "Excel 表格",
    ".xlsx": "Excel 表格",
    ".ppt": "PPT 文稿",
    ".pptx": "PPT 文稿",
    ".txt": "文本",
    ".json": "配置/数据",
    ".xml": "配置/数据",
    ".csv": "表格数据",
    ".apk": "安卓安装包",
    ".dmg": "Mac 镜像",
    ".crdownload": "未下完的浏览器文件",
    ".partial": "未下完的文件",
    ".torrent": "种子文件",
}

_PATH_HINTS: list[tuple[str, str]] = [
    ("softwareDistribution\\download", "Windows 更新下载缓存"),
    ("deliveryoptimization", "传递优化下载缓存"),
    ("$recycle.bin", "回收站内容"),
    ("\\temp\\", "临时目录中的文件/文件夹"),
    ("\\tmp\\", "临时目录中的文件/文件夹"),
    ("npm-cache", "npm 包缓存"),
    ("\\pip\\cache", "Python pip 缓存"),
    (".nuget\\packages", "NuGet 包缓存"),
    (".m2\\repository", "Maven 依赖仓库"),
    (".gradle\\caches", "Gradle 构建缓存"),
    ("\\cache\\", "程序缓存目录"),
    ("code cache", "浏览器代码缓存"),
    ("thumbcache_", "资源管理器缩略图缓存"),
    ("iconcache", "图标缓存"),
    ("crashdumps", "程序崩溃转储"),
    ("\\wer\\", "Windows 错误报告"),
    ("windows.old", "升级前旧系统（体积通常很大）"),
    ("\\prefetch\\", "预读取加速文件"),
    ("inetcache", "IE/旧版网络缓存"),
    ("d3dscache", "DirectX 着色器缓存"),
    ("\\downloads\\", "下载文件夹中的内容"),
    ("\\下载\\", "下载文件夹中的内容"),
    ("node_modules", "前端依赖目录"),
    ("\\.git\\", "Git 仓库数据"),
]


def describe_path(path: str, category: str = "") -> str:
    """给人看的一句话：这是什么文件/目录。"""
    p = Path(path)
    low = str(p).lower().replace("/", "\\")
    parts: list[str] = []

    for key, hint in _PATH_HINTS:
        if key in low:
            parts.append(hint)
            break

    if p.exists():
        try:
            if p.is_dir():
                parts.append("目录（将清空其中内容）")
            else:
                ext = p.suffix.lower()
                parts.append(_EXT_ZH.get(ext, f"{ext or '无扩展名'} 文件" if ext else "无扩展名文件"))
        except OSError:
            ext = p.suffix.lower()
            if ext:
                parts.append(_EXT_ZH.get(ext, f"{ext} 文件"))
    else:
        ext = p.suffix.lower()
        if ext:
            parts.append(_EXT_ZH.get(ext, f"{ext} 文件"))
        else:
            parts.append("路径（扫描时存在）")

    name = p.name
    if name and len(name) <= 40:
        parts.append(f"名称: {name}")

    if category and category not in "".join(parts):
        parts.insert(0, category)

    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for x in parts:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return " · ".join(out[:4])
