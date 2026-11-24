using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using SimpleScreenshot.Core;

namespace SimpleScreenshot.Ocr
{
    public static class Engine
    {
        static RapidEngine rapid;

        public static Tuple<string, RectangleF>[] Recognize(Bitmap image, string directory, bool safeMode)
        {
            Exception failure = null;
            bool rapidWorked = false;
            if (!safeMode)
            {
                try
                {
                    if (rapid == null) rapid = new RapidEngine(Path.Combine(directory, "models"));
                    var result = rapid.Recognize(image);
                    rapidWorked = true;
                    if (result.Length > 0) return result;
                }
                catch (Exception error)
                {
                    failure = error;
                    Trace.TraceWarning("内置 OCR 失败：{0}", error);
                }
            }
            try { return WindowsOcr.Recognize(image); }
            catch (Exception error)
            {
                if (rapidWorked) return Array.Empty<Tuple<string, RectangleF>>();
                if (failure != null)
                    throw new InvalidOperationException("内置文字识别不可用，系统文字识别也无法启动。请检查 OCR 文件与 Windows 语言包。",
                        new AggregateException(failure, error));
                throw new InvalidOperationException("系统文字识别无法启动。请检查 Windows 文字识别语言包，或重启以恢复内置识别。", error);
            }
        }

        internal static void AddText(List<Tuple<string, RectangleF>> target, string text, RectangleF box)
        {
            var items = new System.Globalization.StringInfo(text);
            int count = items.LengthInTextElements;
            for (int i = 0; i < count; i++)
            {
                float left = box.X + box.Width * i / count, right = box.X + box.Width * (i + 1) / count;
                target.Add(Tuple.Create(items.SubstringByTextElements(i, 1),
                    RectangleF.FromLTRB(left, box.Top, right, box.Bottom)));
            }
        }

        internal static RectangleF Bounds(params OcrPoint[] points) => RectangleF.FromLTRB(
            (float)points.Min(p => p.X), (float)points.Min(p => p.Y), (float)points.Max(p => p.X), (float)points.Max(p => p.Y));
    }
}
