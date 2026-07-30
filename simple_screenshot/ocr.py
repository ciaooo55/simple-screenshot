"""文字识别:内置高精度引擎为主,系统引擎兜底。

主引擎是 RapidOCR(PaddleOCR 模型 + onnxruntime,与微信同类技术):
模型内置在包里、完全离线。默认使用 CPU 推理，避免部分显卡驱动的
DirectML 原生崩溃；识别仍在独立进程运行，不阻塞截图界面。
主引擎不可用(包缺失/初始化失败)时回退 Windows.Media.Ocr。

重依赖(numpy/cv2/onnxruntime/winrt)全部函数内导入,不拖慢启动;
引擎实例首次使用后常驻,后续识别免加载。
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)

_availability: bool | None = None
_rapid_engine = None
_rapid_failed = False
_rapid_lock = threading.Lock()

# 引擎内部超过 Global.max_side_len 会整图降采样;默认 2000 会把 4K
# 全屏压掉一半、小字直接不可识别。8192 覆盖双 4K 虚拟桌面(7680px)。
_RAPID_MAX_SIDE = 8192


@dataclass(slots=True)
class OcrSpan:
    text: str
    line_index: int
    order: int
    left: float
    top: float
    right: float
    bottom: float


@dataclass(slots=True)
class OcrOutcome:
    text: str
    line_count: int
    spans: tuple[OcrSpan, ...] = ()


def _box_bounds(box) -> tuple[float, float, float, float]:  # type: ignore[no-untyped-def]
    xs = [float(point[0]) for point in box]
    ys = [float(point[1]) for point in box]
    return min(xs), min(ys), max(xs), max(ys)


def _append_text_spans(
    spans: list[OcrSpan],
    text: str,
    box,
    line_index: int,
    coordinate_scale: float,
) -> None:  # type: ignore[no-untyped-def]
    """Append character spans, evenly splitting a line/word box when needed."""
    if not text:
        return
    left, top, right, bottom = _box_bounds(box)
    width = max(1.0, right - left)
    count = len(text)
    for index, char in enumerate(text):
        char_left = left + width * index / count
        char_right = left + width * (index + 1) / count
        spans.append(
            OcrSpan(
                char,
                line_index,
                len(spans),
                char_left / coordinate_scale,
                top / coordinate_scale,
                char_right / coordinate_scale,
                bottom / coordinate_scale,
            )
        )


def _rapid_available() -> bool:
    """内置引擎的包是否存在(不真正初始化,保持轻量)。"""
    import importlib.util

    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def _get_rapid_engine():  # type: ignore[no-untyped-def]
    """懒加载并常驻内置引擎;初始化失败只试一次,之后走系统引擎。

    加锁:并发探测与首次按 W 的识别线程可能同时进来。
    这里显式禁用 DirectML：Windows 错误报告已确认部分 NVIDIA
    驱动会在 nvwgf2umx.dll 内原生崩溃，Python 无法捕获。
    """
    global _rapid_engine, _rapid_failed, _availability
    if _rapid_engine is not None or _rapid_failed:
        return _rapid_engine
    with _rapid_lock:
        if _rapid_engine is not None or _rapid_failed:
            return _rapid_engine
        try:
            from rapidocr_onnxruntime import RapidOCR

            _rapid_engine = RapidOCR(
                det_use_dml=False,
                cls_use_dml=False,
                rec_use_dml=False,
                max_side_len=_RAPID_MAX_SIDE,
            )
        except Exception:
            logger.warning("内置 OCR 引擎初始化失败", exc_info=True)
            _rapid_failed = True
            _rapid_engine = None
            # 让 is_available 重新走系统引擎的真实检测,
            # UI 才能正确退回"禁用+装语言包提示"。
            _availability = None
    return _rapid_engine


def engine_ready() -> bool:
    """内置引擎是否已完成加载(用于首次识别的等待提示)。"""
    return _rapid_engine is not None


def warmup() -> None:
    """后台预热:加载引擎并跑一次微型推理,把冷启动成本挪出关键路径。"""
    engine = _get_rapid_engine()
    if engine is None:
        is_available()
        return
    try:
        import numpy as np

        engine(np.full((32, 32, 3), 255, dtype=np.uint8))
    except Exception:
        logger.warning("内置 OCR 引擎预热失败", exc_info=True)


def is_available() -> bool:
    """是否有任一可用的识别引擎。

    只缓存 True:装好语言包立即生效,不用重启应用;偶发异常也
    不会把功能永久禁用。重查很便宜(模块导入本身有 Python 缓存)。
    """
    global _availability
    if _availability:
        return True
    # rapid 包存在只代表"大概率可用",不写缓存:一旦初始化失败,
    # 下一次查询会落到系统引擎的真实检测。
    if _rapid_available() and not _rapid_failed:
        return True
    try:
        from winrt.windows.media.ocr import OcrEngine

        _availability = (
            OcrEngine.try_create_from_user_profile_languages() is not None
        )
    except Exception:
        _availability = False
    return _availability


def image_bgr_array(image: QImage):  # type: ignore[no-untyped-def]
    """QImage → 连续 BGR ndarray(内置引擎的输入格式,含 stride 处理)。"""
    import numpy as np

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = converted.width(), converted.height()
    stride = converted.bytesPerLine()
    buffer = np.frombuffer(converted.constBits(), dtype=np.uint8).reshape(
        height, stride // 4, 4
    )[:, :width, :3]
    return np.ascontiguousarray(buffer[:, :, ::-1])


def _recognize_with_rapid(image: QImage) -> OcrOutcome | None:
    """内置引擎识别;引擎不可用返回 None(交给系统引擎兜底)。

    行文本直接取模型输出:实测真实屏幕渲染(ClearType/Qt)下
    12-16px 英文的词间空格模型都能正确给出;按字符框几何重建
    空格反而会过切分(词间距与词内距分布重叠),已验证放弃。
    """
    engine = _get_rapid_engine()
    if engine is None:
        return None
    # 超过引擎上限的图先自己等比缩,内存可控且不触发内部粗暴降采样。
    original_width = image.width()
    original_height = image.height()
    largest = max(original_width, original_height)
    coordinate_scale = 1.0
    if largest > _RAPID_MAX_SIDE:
        factor = _RAPID_MAX_SIDE / largest
        image = image.scaled(
            max(1, round(image.width() * factor)),
            max(1, round(image.height() * factor)),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        coordinate_scale = min(
            image.width() / original_width,
            image.height() / original_height,
        )
    result, _elapse = engine(image_bgr_array(image), return_word_box=True)
    lines: list[str] = []
    spans: list[OcrSpan] = []
    for item in result or []:
        line_text = str(item[1]).strip()
        if not line_text:
            continue
        line_index = len(lines)
        lines.append(line_text)
        char_boxes = item[3] if len(item) > 4 else None
        char_texts = item[4] if len(item) > 4 else None
        if char_boxes and char_texts and len(char_boxes) == len(char_texts):
            for char_box, char_text in zip(char_boxes, char_texts):
                _append_text_spans(
                    spans,
                    str(char_text),
                    char_box,
                    line_index,
                    coordinate_scale,
                )
        else:
            _append_text_spans(
                spans,
                line_text,
                item[0],
                line_index,
                coordinate_scale,
            )
    return OcrOutcome(
        text="\n".join(lines),
        line_count=len(lines),
        spans=tuple(spans),
    )


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
    """同步识别一张图片;失败抛 RuntimeError(带用户可读的原因)。

    内置高精度引擎优先;它不可用或推理失败时回退系统引擎。
    """
    if image.isNull():
        raise RuntimeError("图片内容为空")
    rapid_error: Exception | None = None
    try:
        outcome = _recognize_with_rapid(image)
    except Exception as exc:
        # 推理阶段炸了(显卡驱动/内存等):记录后回退系统引擎,
        # 引擎实例保留,下次仍优先尝试。
        logger.warning("内置引擎推理失败,回退系统引擎", exc_info=True)
        rapid_error = exc
        outcome = None
    if outcome is not None and outcome.line_count > 0:
        return outcome
    # 内置引擎没识别到任何内容时也让系统引擎再试一次:
    # 两个引擎的盲区不同,别把旧引擎能读的图报成"没有文字"。
    try:
        fallback = _recognize_with_windows(image)
    except RuntimeError as windows_error:
        if outcome is not None:
            return outcome  # 真空白图:内置引擎的空结果就是答案
        if rapid_error is not None:
            raise RuntimeError(
                f"{windows_error}(内置引擎推理时也出错:{rapid_error})"
            ) from rapid_error
        raise
    if outcome is not None and fallback.line_count == 0:
        return outcome
    return fallback


def recognize_png_bytes(payload: bytes) -> OcrOutcome:
    """Process-safe entry point used by the isolated OCR worker."""
    image = QImage.fromData(payload, "PNG")
    if image.isNull():
        raise RuntimeError("无法读取待识别图片")
    return recognize_image(image)


def _recognize_with_windows(image: QImage) -> OcrOutcome:
    try:
        from winrt.windows.graphics.imaging import (
            BitmapPixelFormat,
            SoftwareBitmap,
        )
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.security.cryptography import CryptographicBuffer
    except Exception as exc:
        raise RuntimeError(
            "没有可用的文字识别引擎:内置引擎不可用,系统引擎也不可用。"
        ) from exc

    if OcrEngine.try_create_from_user_profile_languages() is None:
        raise RuntimeError(
            "当前系统没有可用的文字识别语言。"
            "请在 Windows 设置 → 时间和语言 → 语言中添加中文或英文语言包。"
        )

    # 实测(11-20px 屏幕文字):放大 2 倍普遍带来 5-15 个百分点的
    # 准确率提升,小字号提升最大(13px:81%→96%);3 倍以上无增益。
    # min(2, limit/largest) 保证 (limit/2, limit] 区间也有部分放大,
    # 不出现 5000/5001px 一像素之差增益归零的悬崖;面积上限防止
    # 双 4K 大选区放大后内存暴涨(RGBA 每 MP 4MB,上限约 132MB/份)。
    limit = int(OcrEngine.max_image_dimension)
    largest = max(image.width(), image.height())
    max_pixels = 33_000_000
    factor = min(2.0, limit / largest)
    if factor > 1.0:
        area = image.width() * image.height()
        if area > 0:
            factor = max(1.0, min(factor, math.sqrt(max_pixels / area)))
    try:
        if factor != 1.0:
            image = image.scaled(
                max(1, round(image.width() * factor)),
                max(1, round(image.height() * factor)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        raw, width, height = image_rgba_bytes(image)
        del image
        buffer = CryptographicBuffer.create_from_byte_array(raw)
        # 及时释放中间拷贝:字节串/缓冲各持一份全尺寸数据,
        # 大图识别期间峰值内存能省一半。
        del raw
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buffer, BitmapPixelFormat.RGBA8, width, height
        )
        del buffer
    except MemoryError as exc:
        raise RuntimeError("内存不足,图片过大,无法完成识别") from exc
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("文字识别引擎初始化失败")

    async def _run():  # type: ignore[no-untyped-def]
        return await engine.recognize_async(bitmap)

    try:
        result = asyncio.run(_run())
    except Exception as exc:  # WinRT 错误信息对用户不友好,包一层。
        raise RuntimeError(f"识别过程出错:{exc}") from exc

    lines: list[str] = []
    spans: list[OcrSpan] = []
    for source_line in result.lines:
        words = [word for word in source_line.words if word.text]
        line_text = join_ocr_words([word.text for word in words])
        if not line_text.strip():
            continue
        line_index = len(lines)
        lines.append(line_text)
        for word_index, word in enumerate(words):
            if word_index:
                previous = words[word_index - 1].text[-1]
                if not (_is_cjk(previous) and _is_cjk(word.text[0])):
                    previous_span = spans[-1]
                    spans.append(
                        OcrSpan(
                            " ",
                            line_index,
                            len(spans),
                            previous_span.right,
                            previous_span.top,
                            previous_span.right,
                            previous_span.bottom,
                        )
                    )
            rect = word.bounding_rect
            box = (
                (rect.x, rect.y),
                (rect.x + rect.width, rect.y),
                (rect.x + rect.width, rect.y + rect.height),
                (rect.x, rect.y + rect.height),
            )
            _append_text_spans(
                spans,
                word.text,
                box,
                line_index,
                factor,
            )
    return OcrOutcome(
        text="\n".join(lines),
        line_count=len(lines),
        spans=tuple(spans),
    )
