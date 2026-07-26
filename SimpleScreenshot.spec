# -*- mode: python ; coding: utf-8 -*-

# 只用了 QtCore/QtGui/QtWidgets/QtNetwork(本地套接字做单实例),
# 其余 Qt 组件与插件都是 hook 顺带打进来的死重,逐项裁掉:
# 体积直接决定 onefile 的解包时间,也就是启动速度。


def _keep_entry(dest: str) -> bool:
    low = dest.replace("\\", "/").lower()
    if low.startswith("cv2/opencv_videoio_ffmpeg"):
        # OpenCV 的视频解码 DLL(12.7MB),OCR 只用图像处理,cv2 对它是
        # 懒加载,缺失不影响 import(headless 发行版即如此)。
        return False
    if low.startswith("pil/_avif"):
        # PIL 的 AVIF 编解码器(4.2MB),识别管线只做格式转换用不到;
        # PIL 插件加载自带 try/except,缺失安全。
        return False
    if low in ("libcrypto-3-x64.dll", "libssl-3-x64.dll", "_hashlib.pyd"):
        # OpenSSL 由 _hashlib.pyd 的二进制依赖拉入(Python 侧 excludes 挡不住);
        # hashlib 会回退到内建 _sha2/_md5,Qt tls 插件也已裁掉,可安全移除。
        return False
    if low.startswith("pyside6/plugins/imageformats/"):
        # PNG 内建于 QtGui;只留 ico,其余格式(gif/tiff/webp/pdf…)用不到。
        return "qico" in low
    if low.startswith("pyside6/translations/"):
        # 界面是中文,Qt 自带对话框按钮只需要中文翻译。
        return low.endswith("qtbase_zh_cn.qm")
    drop_prefixes = (
        "pyside6/opengl32sw.dll",  # 软件 OpenGL 兜底,raster 绘制用不到
        "pyside6/qt6quick",
        "pyside6/qt6qml",
        "pyside6/qt6opengl",
        "pyside6/qt6pdf",
        "pyside6/qt6svg",
        "pyside6/qt6virtualkeyboard",
        "pyside6/plugins/platforms/qdirect2d",  # 只用 qwindows
        "pyside6/plugins/tls/",  # QLocalSocket 不走 TLS
        "pyside6/plugins/networkinformation/",
        "pyside6/plugins/generic/",
        "pyside6/plugins/iconengines/",  # svg 图标引擎,图标是代码画的
        "pyside6/plugins/platforminputcontexts/",
    )
    return not low.startswith(drop_prefixes)


from PyInstaller.utils.hooks import collect_data_files

# 内置 OCR 引擎的模型与配置(约 15MB,识别功能的核心资产)。
_ocr_datas = collect_data_files("rapidocr_onnxruntime")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/app.ico", "assets")] + _ocr_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 纯 Python 死重:代码不 import 这些。libcrypto/libssl 两个 DLL
        # 由 _hashlib 拉入,在上面 _keep_entry 里裁,不靠这里。
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
        "sqlite3",
        "multiprocessing",
        "xmlrpc",
        "curses",
        "lib2to3",
        "idlelib",
        "ssl",
        "_ssl",
        # onnxruntime-directml 连带安装的符号数学库,推理运行时不引用,
        # 纯 Python 死重约 25MB(压缩后)。
        "sympy",
        "mpmath",
    ],
    noarchive=False,
    optimize=2,
)

a.binaries = [entry for entry in a.binaries if _keep_entry(entry[0])]
a.datas = [entry for entry in a.datas if _keep_entry(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SimpleScreenshot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/app.ico"],
)
