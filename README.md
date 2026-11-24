# 简易截图工具

面向 Windows 10 / 11（x64）的便携截图工具。使用系统自带的 .NET Framework 4.8、WinForms 和 Win32，启动后只在托盘常驻。OCR 在使用时才启动独立工作进程，不影响正常截图；文字识别不上传图片。

## 获取与启动

进入仓库的 **Actions → Windows build and package**，打开已成功的运行，在 **Artifacts** 下载 `SimpleScreenshot-win-x64`。解压下载文件，再解压其中的 `SimpleScreenshot-win-x64.zip`。将整个目录放在固定位置，双击 `SimpleScreenshot.exe`。不需要安装 Python 或 Qt，也没有安装程序。如果 Windows 缺少 .NET Framework 4.8，请先启用或从微软安装它。

- **只需要截图、标注和贴图**：可以单独带走 `SimpleScreenshot.exe`。
- **需要文字识别**：保留 EXE 旁的整个 `ocr` 目录。它包含 CPU 版 ONNX Runtime、相关 DLL 和模型；主程序不需要预加载这些文件。
- 在设置中启用开机启动后，登录将静默启动。移动 EXE 后可重新启用，以更新 Windows 的启动入口。

## 截图与标注

| 操作 | 快捷键 |
| --- | --- |
| 框选后打开复制会话 | Alt+A |
| 框选后打开保存会话 | Alt+S |
| 框选后原位置顶贴图 | Alt+Q |
| 框选时全选桌面／恢复上次选区 | Ctrl+A／R |
| 框选时保留选区进行精调 | Tab |
| 复制选区处光标的 HEX 色值 | C |
| 查看截图快捷键 | F1 |

可以跨显示器框选、按 Shift 拉正方形，或单击吸附窗口。光标附近的放大镜显示像素坐标、HEX 与 RGB，选区标签显示导出后的像素尺寸。按 Tab 或从标注窗口点 **精调**，即可拖动选区或八个手柄；方向键移动，Ctrl+方向键调整大小，Shift 将步长增至 10 像素。Enter 或双击确认精调。

标注窗口是普通任务栏窗口，可最小化、最大化，滚轮只缩放图片。默认画笔（P），另有箭头（A）、矩形（R）、荧光（G）、椭圆（O）、编号（N）、马赛克（M）及文字（T）。用 **样式** 设置颜色、线宽和字号；Shift 可约束正圆、正方形和 45° 箭头；Ctrl+滚轮调整线宽或字号；Ctrl+Z/Y 撤销/重做。双击按当前入口复制或保存；Ctrl+C/S、Ctrl+Shift+S 分别复制、保存、另存为。右键或 Esc 退出文字识别、取消当前笔迹、撤销或返回原桌面快照重选。

按 **W** 或点 **识别** 会对未标注的原图本地识别。支持拖选文字、双击选词、Ctrl+A 全选及 Ctrl+C 复制，Esc 或右键退出。内置引擎失败或无结果时会尝试系统 OCR，取决于 Windows 支持的 API 和已安装的识别语言；不依赖该兜底提供基本 OCR 功能。排查兼容性问题时，可在启动前设置环境变量 `SIMPLESCREENSHOT_OCR_SAFE_MODE=1`，跳过内置模型。

## 置顶贴图与托盘

- 可同时钉住多张图，也可从托盘将剪贴板图片贴出。按住中键拖动，或按 P 暂停画笔后用左键拖动；靠近屏幕边缘会吸附，方向键及 Shift+方向键可微调。
- 滚轮以光标为中心缩放，`+/-` 也可缩放，Ctrl+滚轮调透明度；双击或 Ctrl+0 恢复原始大小及不透明度。
- 左键可直接画笔标注；右键菜单可撤销一笔、复制、保存、另存、OCR、鼠标穿透或关掉贴图。Ctrl+拖动可向其他应用拖出带标注的 PNG。Esc 关闭当前贴图。
- 托盘左单击截图，双击设置；右键还有全屏截图、贴剪贴板图片、恢复穿透贴图可点击、保存最近截图、关闭全部贴图、打开截图目录、设置、开机启动、关于及退出。默认新截图会截到已有贴图，可在设置里关闭。

所有截图保存为 PNG，默认目录是 EXE 同级的 `tp`。点击保存通知可在资源管理器中选中文件；保存失败时尝试复制到剪贴板。设置兼容旧版同路径的 v1/v2/v3 JSON：`%APPDATA%\SimpleScreenshot\settings.json`，日志在同目录。贴图拖出的临时 PNG 保存在 `%TEMP%\SimpleScreenshot`，下次启动清理超过一天的文件。

## 源码构建

安装 .NET 10 SDK 用来构建和测试；程序目标仍是 **.NET Framework 4.8**，用户不需要 .NET 10。

```powershell
dotnet build src/App/SimpleScreenshot.csproj -c Release -p:EnableWindowsTargeting=true
dotnet build src/Ocr/SimpleScreenshot.Ocr.csproj -c Release -p:EnableWindowsTargeting=true
dotnet test tests-dotnet/SimpleScreenshot.Tests.csproj -c Release
```

以上命令可在 Windows 或 Linux 执行；只有 Windows 能运行 WinForms 主程序。命令行测试覆盖设置迁移、热键校验、文件名、混合 DPI 坐标数学、标注历史、OCR 文本解码和检测框后处理。Windows Actions 另在打包后启动 OCR 工作进程并识别合成截图。真实托盘、全局热键、混合缩放双屏、鼠标穿透及开机启动仍应在 Windows 桌面验收。

如需在 Windows 本地打包，先用上述命令编译，再用 PowerShell 7 执行：

```powershell
./scripts/package.ps1
powershell.exe -NoProfile -File ./scripts/check-ocr.ps1 -PackageDir dist/staging
```

打包需 Visual Studio 的 x64 C++ Redistributable 组件，脚本将使用应用本地 DLL，不另运行安装程序。脚本从 PyPI 下载并校验固定版本 `rapidocr_onnxruntime==1.4.4` wheel，只解出同款 PaddleOCR 检测、方向和识别模型。字典位于识别模型的 `character` 元数据，与旧版 RapidOCR 用法一致；模型和运行时 DLL 不提交到仓库。GitHub Actions 只上传 ZIP，不创建 Release 或版本标签。
