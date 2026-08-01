# 简易截图工具

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4?logo=windows)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/GUI-PySide6-41CD52?logo=qt&logoColor=white)
![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)
![Package](https://img.shields.io/badge/package-portable%20EXE-6b7280)

> 一款常驻 Windows 托盘的轻量截图、标注、OCR 与置顶贴图工具。

## 📌 项目速览

| 项目 | 说明 |
| --- | --- |
| 中文名称 | 简易截图工具 |
| GitHub 仓库名 | `simple-screenshot` |
| 名称状态 | 保持当前名称，本轮没有改名 |
| 主要用途 | Windows 区域截图、窗口吸附、标注、OCR 和置顶贴图 |
| 使用方式 | 下载便携版直接运行，或从 Python 源码启动 |
| 适用平台 | Windows 10/11 |

如果只是使用软件，直接看“下载”和“使用方式”；如果需要修改或打包，再看文末的源码、构建与测试说明。

<img src="assets/icon.png" alt="简易截图工具图标" width="96" height="96">

一个常驻 Windows 托盘的轻量截图工具：跨显示器区域截图、窗口吸附、丰富标注（画笔/箭头/矩形/椭圆/序号/马赛克/文字）、取色放大镜、置顶贴图，支持复制到剪贴板或保存 PNG 文件。

## ✨ 功能亮点

- 跨显示器区域截图、窗口自动吸附、全屏与上次选区恢复。
- 画笔、荧光、箭头、矩形、椭圆、序号、马赛克和文字标注，支持撤销与重做。
- RapidOCR 优先、Windows OCR 兜底的本地文字识别；可按位置拖选并复制识别结果。
- 置顶贴图支持缩放、透明度、鼠标穿透、边缘吸附、即时标注和拖出 PNG。
- 三组可配置全局快捷键、托盘菜单、开机启动和单实例保护。
- 保存失败自动回退到剪贴板，诊断日志按当前用户写入 AppData。

## 📦 下载与安装

Windows 便携版在 [GitHub Releases](https://github.com/ciaooo55/simple-screenshot/releases/latest) 提供。主分支每次更新会自动运行测试；推送 `v*` 或 `r*` 版本标签后，GitHub Actions 会远程打包并创建 Release。

下载 `SimpleScreenshot.exe` 后放到一个长期固定目录，双击即可运行，无需安装。默认截图目录 `tp` 位于程序所在目录，因此不要把 EXE 长期留在浏览器下载临时目录；需要迁移时，可先在设置中改为固定截图目录。

## 🧭 使用方式

1. 双击 SimpleScreenshot.exe，程序显示启动通知后进入系统托盘（开机自启时静默启动，不打扰）。
2. 默认全局快捷键：**Alt+A** 截图并复制；**Alt+S** 截图并保存；**Alt+Q** 截图并钉住（贴图）。单击托盘图标立即截图，双击打开设置，悬停可查看当前快捷键。
3. 移动鼠标会自动高亮窗口并显示窗口标题，单击即可吸附选择；按住拖动则自由框选（按住 **Shift** 拉正方形）；**Ctrl+A** 直接全选整个屏幕；**R** 恢复上次选区。
4. 框选阶段带取色放大镜：实时显示光标坐标与像素颜色（HEX 与 RGB），按 **C** 复制颜色值（#RRGGBB）。拖动选区手柄微调时放大镜同样可用，尺寸标签显示的是导出 PNG 的实际像素。
5. 松开框选后打开普通的**截图会话窗口**：它贴合截图内容，仅保留 6px 窄边和一行紧凑工具栏，显示在任务栏、可最小化/最大化且不置顶，不影响其他应用。画笔、箭头、矩形在首层，荧光、椭圆、序号、马赛克、文字位于“更多”；双击且位移很小时执行本次快捷键的默认动作（Alt+A 复制，Alt+S 保存）并关闭窗口。滚轮只缩放图片。W 识别文字后可拖选复制，标注操作会暂时隐藏，退出识别后恢复。
6. 右键托盘图标可手动截图（复制 / 保存 / 钉住 / 全屏）、**把剪贴板里的图片直接钉成贴图**（网页复制、微信图片都行）、保存最近一张截图、关闭所有贴图、打开截图文件夹、打开设置、切换开机启动或退出。
7. 在设置页点击快捷键输入框，直接按下新按键或组合键，再点击"保存"；录制期间全局热键会临时失效，因此可以直接互换两个热键或重录同一组合键。"恢复默认"可一键填回出厂设置。单个字母/数字不允许注册为全局热键（会屏蔽其他程序），F1–F24 和 PrintScreen 可单独使用。若某个热键被其他程序占用，启动时会跳过它并保留其余热键，同时弹出提醒。
8. 保存成功后点击通知气泡，可直接打开文件所在文件夹并选中文件；保存失败时截图会自动复制到剪贴板兜底。
9. 开启“开机启动”后会同步 Windows 的启动许可状态；若曾被任务管理器静默禁用，重新勾选一次即可修复。异常信息保存在 `%APPDATA%\SimpleScreenshot\app.log`，便于定位偶发问题。

默认截图目录是程序所在目录下的 tp 文件夹，可在设置中修改。配置保存在当前用户的 AppData\Roaming\SimpleScreenshot 目录（旧版本配置会自动迁移）。

## ✏️ 标注操作

框选完成后会打开普通截图会话窗口，而不是置顶预览。它可以最小化并从任务栏切换，窗口位置和大小在缩放时不会变化。

- 画笔、箭头、矩形是首层工具；“更多”中保留荧光、椭圆、序号、马赛克、文字，“样式”可调颜色和粗细。画笔默认启用，直接在图片上按住左键拖动即可绘制；小于系统拖拽阈值的点击和抖动不会留下笔迹。
- **双击图片**执行本次快捷键的默认动作：Alt+A 复制、Alt+S 保存，并自动关闭会话窗口。Ctrl+C 和 Ctrl+S 也可直接完成。
- **W 识别文字**：会话图片固定不动，画笔操作暂时隐藏；识别在独立进程以稳定的 CPU 模式完成，界面和其他程序保持可用。识别结果可拖选、双击选词、Ctrl+A 全选、Ctrl+C 复制；Esc 或右键回到画笔。OCR 始终使用未烧入笔迹的原图。
- 右键逐级回退：先取消正在拖动的一笔，再撤销最后一笔；没有笔迹时回到同一张桌面快照重新框选；尚未框选时取消本次截图。

## 📌 贴图（钉住）

把截图钉在屏幕最上层，随时对照参考（类似 Snipaste）：

- 截图后点击"钉住"（或 Ctrl+D、全局 Alt+Q），截图会原位置顶显示，高分屏下按物理像素 1:1 渲染不发虚。
- 贴图是真正的无边框置顶图层；定住后默认就是画笔，左键拖动直接标注；按住鼠标中键（滚轮）拖动才移动贴图，贴近屏幕边缘自动吸附；方向键微调 1 像素（Shift+方向键 10 像素）。
- 滚轮以光标为中心缩放（20%–500%），也可用 +/- 键；Ctrl+滚轮调整透明度；调整时中央会短暂显示当前数值。
- 双击或 Ctrl+0 恢复原始大小与不透明度。
- 右键菜单可撤销一笔或暂停画笔，P 也可开关画笔；暂停后左键可作为备用移动手势。复制、保存和拖出文件都会包含已完成的笔迹，OCR 仍读取干净原图。
- 贴图上 Ctrl+C 复制、Ctrl+S 保存、Ctrl+Shift+S 另存为（都有窗口内即时提示）、Esc 关闭；右键菜单显示当前缩放/透明度，还可一键关闭所有贴图（托盘菜单同样可以）。
- **Ctrl+按住拖动可把贴图拖出为 PNG 文件**，直接拖进聊天窗口、网页上传框就能发送。
- 右键菜单可开启**鼠标穿透**：贴图变成纯参考图，点击直接落到下方窗口；托盘菜单"恢复贴图可点击"一键解除。
- 缩小有下限保护（短边不低于 48px），不会缩到点不中；剪贴板贴出的超大图会自动缩小到屏幕内，滚轮可再放大。
- 定住后仍可继续使用 Alt+A / Alt+S / Alt+Q 截更多图片；默认会把已有贴图一起截入，适合叠图、对照和二次标注。若不想截入贴图，可在设置中开启“截图时隐藏已有贴图”。
- 可同时钉住多张贴图，互不影响。

## 🧱 目录结构

```text
simple-screenshot/
├─ main.py                       源码启动入口
├─ simple_screenshot/
│  ├─ app.py                     托盘应用与操作编排
│  ├─ capture.py                 桌面捕获与选区交互
│  ├─ capture_session.py         截图会话窗口
│  ├─ annotations.py             标注模型与合成
│  ├─ ocr.py                     RapidOCR / Windows OCR
│  ├─ pin_window.py              置顶贴图
│  ├─ config.py                  设置加载、迁移与保存
│  └─ hotkeys.py                 全局快捷键解析与注册
├─ tests/                        pytest 自动测试
├─ assets/                       应用图标
├─ SimpleScreenshot.spec         PyInstaller 打包配置
└─ build.ps1                     Windows 构建入口
```

## 💻 在新电脑恢复开发环境

仓库保存完整源码、测试、图标、依赖清单、构建配置和 GitHub Actions；EXE 仅作为 GitHub Release 资产发布，不提交进 Git 仓库。首次在另一台 Windows 电脑继续开发时：

```powershell
git clone https://github.com/ciaooo55/simple-screenshot.git
cd simple-screenshot
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps "rapidocr_onnxruntime>=1.4,<2"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
```

以后继续已有工作，先同步主分支，再从新分支修改：

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/功能名称
# 修改并测试后：
git add .
git commit -m "feat: 描述本次改动"
git push -u origin feature/功能名称
```

不要复制单独的源码压缩包作为开发目录；完整 `git clone` 才会保留提交历史、标签和远程关联。

### 从现有源码目录运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --no-deps "rapidocr_onnxruntime>=1.4,<2"
python main.py
```

项目以 Python 3.12 为 CI 验证版本。Windows OCR 依赖按平台标记安装；RapidOCR 包按 CI 的方式单独安装，避免其依赖解析改写仓库锁定的运行依赖。

## 🛠️ 构建便携 EXE

```powershell
.\build.ps1
```

构建结果位于 dist\SimpleScreenshot.exe。它是无控制台的单文件便携程序，不需要安装。默认使用增量构建；需要清理全部缓存时运行 `.\build.ps1 -Clean`。

spec 文件只打包实际用到的 Qt 组件（裁掉了 QtQuick/Qml、软件 OpenGL、OpenSSL、多余的图片格式插件与翻译等），产物约 23MB；单文件版每次启动要先解包到临时目录，体积直接决定启动速度，往 spec 里加东西前请先确认运行时真的需要。

## 📁 配置、数据与日志

| 数据 | 默认位置 | 说明 |
| --- | --- | --- |
| 用户设置 | `%APPDATA%\SimpleScreenshot\settings.json` | 快捷键、保存目录、贴图与截图偏好 |
| 设置恢复日志 | `%APPDATA%\SimpleScreenshot\settings.error.log` | 配置损坏或迁移失败时记录 |
| 应用诊断日志 | `%APPDATA%\SimpleScreenshot\app.log` | 未捕获异常与运行诊断 |
| 原生崩溃日志 | `%APPDATA%\SimpleScreenshot\native-crash.log` | 原生组件故障排查 |
| 默认截图 | `<程序目录>\tp\` | 可在设置中修改 |
| 拖出临时 PNG | 系统临时目录下的 `SimpleScreenshot` | 供拖放到其他应用使用 |

旧版配置会在加载时迁移。若设置异常，先退出程序，备份上述目录后再重置配置；不要在程序运行中直接编辑 `settings.json`。

## 🔐 隐私与权限

- 截图和 OCR 均在本机完成，项目代码中没有云端上传流程；把图片拖入网页或聊天软件后，则受目标应用的隐私规则约束。
- 截图、贴图、OCR 文本与日志可能包含敏感画面、文件名或窗口信息，分享前请检查并打码。
- 全局热键、开机启动、剪贴板和屏幕捕获需要当前 Windows 会话权限；首次运行若被安全软件拦截，请核对下载来源与 Release 文件。
- `tp`、`dist`、构建缓存和本地配置不应提交到版本库。发布 EXE 前应在干净环境运行测试并手工验证多显示器缩放。

## 🧪 测试

```powershell
python -m pytest -q
```

自动测试覆盖配置恢复与 v1→v2 迁移、热键解析（含裸键拦截）与注册回滚、文件命名、PNG 写入、选区裁剪、全部标注类型合成、撤销/重做、序号自增、工具栏点击防穿透、右键分级返回、键盘调整选区、上次选区恢复、样式记忆、文字输入框键盘抓取回归，以及贴图窗口的锚点缩放、键盘微调、边缘吸附与快捷键。托盘通知、真实全局热键、开机启动以及多显示器不同缩放比例需要在 Windows 桌面环境中手工验收。
