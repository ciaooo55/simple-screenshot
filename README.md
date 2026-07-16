# 简易截图工具

<img src="assets/icon.png" alt="简易截图工具图标" width="96" height="96">

一个常驻 Windows 托盘的轻量截图工具，支持跨显示器区域截图、画笔、文字，以及复制到剪贴板或保存 PNG 文件。

## 使用方式

1. 双击 SimpleScreenshot.exe，程序显示启动通知后进入系统托盘。
2. 按 Alt+A，框选并标注后复制到剪贴板；按 Alt+S 则保存为文件。
3. 截图时按 Esc 取消；选区完成后按 Enter 执行当前动作。
4. 右键托盘图标可手动截图、打开设置、切换开机启动或退出。
5. 在设置页点击快捷键输入框，直接按下新按键或组合键，再点击“保存”。

默认截图目录是程序所在目录下的 tp 文件夹，可在设置中修改。配置保存在当前用户的 AppData\Roaming\SimpleScreenshot 目录。

## 标注操作

- 画笔：可选择颜色与 2、4、8 像素粗细。
- 文字：点击选区后输入；Ctrl+Enter 完成文字，普通 Enter 可换行。
- 支持撤销、清空、取消和完成；截图任意阶段按 Esc 都会取消。

## 从源码运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

## 构建便携 EXE

```powershell
.\build.ps1
```

构建结果位于 dist\SimpleScreenshot.exe。它是无控制台的单文件便携程序，不需要安装。

## 测试

```powershell
python -m pytest -q
```

自动测试覆盖配置恢复、热键解析与注册回滚、文件命名、PNG 写入、选区裁剪和标注合成。托盘通知、真实全局热键、开机启动以及多显示器不同缩放比例需要在 Windows 桌面环境中手工验收。
