# CDriveCleaner

面向 Windows 的 **C 盘手动清理工具**：扫描可释放空间，预览后再删，默认本地运行、不上网。

> Python + CustomTkinter GUI，可用 PyInstaller 打成单文件 exe，目标机无需安装 Python。

## 为什么做这个

C 盘爆红时，系统自带清理不够细，第三方工具又常「一把梭」。本工具强调：

- **只手动扫描**，没有定时任务、没有后台常驻
- **每条结果带推荐标签**（建议删除 / 可选 / 不建议）和原因
- **先预览、再勾选、再清理**；支持模拟清理（dry-run）
- **硬排除** `System32`、`WinSxS` 等关键路径，降低误删风险
- **隐私**：不上传任何数据；日志只写在本机

## 功能一览

### 扫描与清理

| 能力 | 说明 |
|---|---|
| 手动扫描 | 一键扫 C 盘常见可清理项 |
| 快速扫描 | 跳过微信 / 重复文件 / 大文件等慢项，先出结果 |
| 安全 / 深度 / 自定义 | 一键清建议项、深度项，或只清勾选项 |
| 模拟清理 | dry-run：只记日志、不真删 |
| 删除方式 | 默认永久删除；可勾选「进回收站」以便恢复 |
| 新鲜文件保护 | 临时类清理跳过 24 小时内新建/修改的文件 |

### 交互

- 表头排序、按分类筛选、悬停放大预览
- 右键：打开所在位置 / 复制路径
- 导出扫描结果 CSV
- 分类占用图（Treemap）

### 扫描覆盖（部分）

- 临时文件、Windows Update 缓存、回收站、缩略图缓存
- 多浏览器缓存、Defender 等系统扩展日志
- GPU 着色器缓存（NVIDIA / AMD / Intel）
- 开发缓存（npm、pip、Gradle、VS Code 等常见路径）
- 办公与通讯（Office、Teams、Zoom、Slack 等）
- 游戏平台缓存（Steam / Epic 等）
- 安装包残留、下载目录媒体与长期未访问文件、大文件
- 空目录、重复文件、扩展名占用汇总
- **微信定制扫描**（个人/群聊 × 图片/视频/文件/缩略图等；聊天附件 ≠ 聊天记录）
- Space Hogs **仅报告**（休眠文件、页面文件、WSL/Docker vhdx 等，默认不建议直接删）

## 截图

<!-- 开源后把截图放到 docs/images/ 并取消注释
![主界面](docs/images/main.png)
![占用图](docs/images/treemap.png)
-->

（建议推送前补 1～2 张主界面 / 占用图截图。）

## 环境要求

- Windows 10 / 11（x64）
- 开发运行：Python 3.11+
- 清理部分系统目录时，建议「以管理员身份」运行

## 快速开始（源码）

```powershell
git clone https://github.com/lvjg007/CDriveCleaner.git
cd CDriveCleaner

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m src.main
```

## 打包成 exe

```powershell
pip install -r requirements.txt
pyinstaller build.spec
```

产物一般为 `dist/CDriveCleaner.exe`。杀软可能误报，可自行加白名单。

## 测试

```powershell
python -m pytest tests -v
```

## 使用建议

1. 先点 **开始扫描**（磁盘很大时可勾选 **快速扫描**）。
2. 看推荐列：**建议删除** 相对安全；**不建议** 默认不要勾。
3. 不确定时先勾 **模拟清理**，看日志里会删什么。
4. 需要可恢复时勾选 **进回收站**；不勾则为永久删除。
5. 微信相关：优先清缩略图 / 缓存 / 视频附件；「聊天记录库」勿轻易删。

## 项目结构

```
CDriveCleaner/
├── src/
│   ├── main.py              # 入口
│   ├── app/                 # 编排（扫描 / 清理）
│   ├── scanners/            # 各类扫描器（可注册扩展）
│   ├── cleaner/             # 执行删除 / dry-run / 回收站
│   ├── models/              # CleanItem 等数据模型
│   ├── ui/                  # CustomTkinter 界面与占用图
│   └── utils/               # 路径安全、新鲜度、回收站、日志等
├── tests/
├── docs/                    # 设计与实现计划
├── build.spec               # PyInstaller 配置
└── requirements.txt
```

架构简述：`UI → Orchestrator → Scanners → CleanItem → CleanExecutor`。

新增扫描类别：实现 `Scanner` 子类并在 `src/scanners/registry.py` 注册即可。

## 安全与隐私

- 不会联网上传扫描结果或路径
- 硬排除系统关键目录；Space Hogs 类仅展示体积提示
- 删除操作不可撤销（除非勾选进回收站）——请先阅读推荐标签
- 本工具按「尽力而为」提供，作者不对误删造成的数据损失承担责任；开源使用请自行评估风险

## 路线图（可选）

- [ ] 原生 NTFS MFT 极速全盘扫描（当前用「快速扫描」跳过慢项代替）
- [ ] 更细的应用级清理规则
- [ ] 界面多语言 / 夜间主题

欢迎在 Issues 里提需求或缺陷。

## 致谢（功能借鉴）

本工具在交互与扫描覆盖上参考了以下开源项目（实现独立，非 fork）：

| 项目 | 借鉴点 |
|---|---|
| [WinDirStat](https://github.com/windirstat/windirstat) | 按大小浏览、资源管理器定位、treemap 思路 |
| [Capacitra](https://github.com/Capacitra/capacitra) | 悬停详情、可选回收站删除 |
| [BitBroom](https://github.com/pwnapplehat/BitBroom) | 分类扫描、安全提示、dry-run / 新鲜文件保护思路 |
| [DiskMap](https://github.com/aldo-mcs/DiskMap) | 垃圾分类、Reveal in Explorer |
| [WindowsCleaner](https://github.com/darkmatter2048/WindowsCleaner) | C 盘清理场景定位 |
| [BleachBit](https://www.bleachbit.org/) | 应用级清理规则思路 |

## 贡献

1. Fork 本仓库并创建分支
2. 改动尽量小而清晰；扫描器请带推荐分级与排除逻辑
3. 本地跑通 `pytest`
4. 提交 PR，说明动机与测试方式

Issue / PR 请用中文或英文均可。

## 许可证

本项目采用 [MIT License](LICENSE)。

---

**免责声明**：清理磁盘有风险。重要数据请先备份；系统文件、聊天记录、项目工程目录请谨慎勾选。
