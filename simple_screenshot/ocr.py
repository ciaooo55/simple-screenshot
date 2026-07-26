"""基于 Windows 系统自带引擎(Windows.Media.Ocr)的文字识别。

不携带任何模型文件:引擎与语言数据来自系统语言包,离线可用。
用 pywinrt 的按命名空间分包(winrt-*)而不是整块的 winsdk,
打包体积只增加约 1MB。winrt 的导入都放在函数内部,避免拖慢
程序启动;首次调用的初始化结果会被缓存。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

_availability: bool | None = None


@dataclass(slots=True)
class OcrOutcome:
    text: str
    line_count: int


def is_available() -> bool:
    """系统是否有可用的 OCR 语言引擎。

    只缓存 True:装好语言包立即生效,不用重启应用;偶发异常也
    不会把功能永久禁用。重查很便宜(模块导入本身有 Python 缓存)。
    """
    global _availability
    if _availability:
        return True
    try:
        from winrt.windows.media.ocr import OcrEngine

        _availability = (
            OcrEngine.try_create_from_user_profile_languages() is not None
        )
    except Exception:
        _availability = False
    return _availability


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x2E80 <= code <= 0x9FFF  # 汉字、部首、CJK 标点
        or 0xF900 <= code <= 0xFAFF  # 兼容汉字
        or 0xFF00 <= code <= 0xFFEF  # 全角字符
    )


def join_ocr_words(words: list[str]) -> str:
    """拼接 OCR 词:Windows 引擎把每个汉字当一个词,直接用空格连会变成
    "你 好 世 界";中文之间不留空格,拉丁词之间保留一个空格。"""
    parts: list[str] = []
    for word in words:
        if not word:
            continue
        if parts:
            previous = parts[-1][-1]
            # 仅当两侧都是 CJK 才不留空格;中英交界处保留空格更可读。
            if not (_is_cjk(previous) and _is_cjk(word[0])):
                parts.append(" ")
        parts.append(word)
    return "".join(parts)


def image_rgba_bytes(image: QImage) -> tuple[bytes, int, int]:
    """QImage → 紧凑 RGBA8888 字节串(剥掉行对齐 padding)。"""
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = converted.width(), converted.height()
    stride = converted.bytesPerLine()
    raw = converted.constBits().tobytes()
    if stride != width * 4:
        raw = b"".join(
            raw[y * stride : y * stride + width * 4] for y in range(height)
        )
    return raw, width, height


def recognize_image(image: QImage) -> OcrOutcome:
    """同步识别一张图片;失败抛 RuntimeError(带用户可读的原因)。"""
    if image.isNull():
        raise RuntimeError("图片内容为空")
    if not is_available():
        raise RuntimeError(
            "当前系统没有可用的文字识别语言。"
            "请在 Windows 设置 → 时间和语言 → 语言中添加中文或英文语言包。"
        )

    from winrt.windows.graphics.imaging import (
        BitmapPixelFormat,
        SoftwareBitmap,
    )
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.security.cryptography import CryptographicBuffer

    # 引擎有最大尺寸限制,超大截图先等比缩到限制内再识别。
    limit = int(OcrEngine.max_image_dimension)
    if max(image.width(), image.height()) > limit:
        image = image.scaled(
            limit,
            limit,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    raw, width, height = image_rgba_bytes(image)
    buffer = CryptographicBuffer.create_from_byte_array(raw)
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        buffer, BitmapPixelFormat.RGBA8, width, height
    )
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("文字识别引擎初始化失败")

    async def _run():  # type: ignore[no-untyped-def]
        return await engine.recognize_async(bitmap)

    try:
        result = asyncio.run(_run())
    except Exception as exc:  # WinRT 错误信息对用户不友好,包一层。
        raise RuntimeError(f"识别过程出错:{exc}") from exc

    lines = [
        join_ocr_words([word.text for word in line.words])
        for line in result.lines
    ]
    lines = [line for line in lines if line.strip()]
    return OcrOutcome(text="\n".join(lines), line_count=len(lines))
