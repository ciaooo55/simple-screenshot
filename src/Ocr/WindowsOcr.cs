using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using SimpleScreenshot.Core;

namespace SimpleScreenshot.Ocr
{
    static class WindowsOcr
    {
        static Type RuntimeType(string name) => Type.GetType(name + ", Windows, ContentType=WindowsRuntime", true);

        internal static Tuple<string, RectangleF>[] Recognize(Bitmap image)
        {
            var engineType = RuntimeType("Windows.Media.Ocr.OcrEngine");
            var softwareBitmap = RuntimeType("Windows.Graphics.Imaging.SoftwareBitmap");
            var format = RuntimeType("Windows.Graphics.Imaging.BitmapPixelFormat");
            var crypto = RuntimeType("Windows.Security.Cryptography.CryptographicBuffer");
            var engine = engineType.GetMethod("TryCreateFromUserProfileLanguages").Invoke(null, null);
            if (engine == null)
                throw new InvalidOperationException("未安装可用的 Windows 文字识别语言包。");

            int limit = Convert.ToInt32(engineType.GetProperty("MaxImageDimension").GetValue(null), CultureInfo.InvariantCulture);
            double scale = Math.Min(2, limit / (double)Math.Max(image.Width, image.Height));
            if (scale > 1)
                scale = Math.Max(1, Math.Min(scale, Math.Sqrt(33000000d / ((double)image.Width * image.Height))));
            int width = Math.Max(1, (int)Math.Round(image.Width * scale));
            int height = Math.Max(1, (int)Math.Round(image.Height * scale));

            object bitmap;
            using (var scaled = new Bitmap(width, height))
            {
                using (var graphics = Graphics.FromImage(scaled))
                {
                    graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                    graphics.DrawImage(image, 0, 0, width, height);
                }
                byte[] bgra = Pixels.From(scaled).Bgra;
                var buffer = crypto.GetMethod("CreateFromByteArray").Invoke(null, new object[] { bgra });
                var create = softwareBitmap.GetMethods().Single(method =>
                    method.Name == "CreateCopyFromBuffer" && method.GetParameters().Length == 4);
                bitmap = create.Invoke(null, new[] { buffer, Enum.Parse(format, "Bgra8"), (object)width, height });
            }

            try
            {
                var operation = engineType.GetMethod("RecognizeAsync").Invoke(engine, new[] { bitmap });
                var operationType = engineType.GetMethod("RecognizeAsync").ReturnType;
                var extensionType = Type.GetType(
                    "System.WindowsRuntimeSystemExtensions, System.Runtime.WindowsRuntime, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089", true);
                var convert = extensionType.GetMethods().Single(method => method.Name == "AsTask" &&
                    method.IsGenericMethodDefinition && method.GetGenericArguments().Length == 1 &&
                    method.GetParameters().Length == 1 && method.GetParameters()[0].ParameterType.Name == operationType.Name);
                var resultType = operationType.GetGenericArguments()[0];
                var task = (Task)convert.MakeGenericMethod(resultType).Invoke(null, new[] { operation });
                task.GetAwaiter().GetResult();
                var result = task.GetType().GetProperty("Result").GetValue(task);
                var lineType = RuntimeType("Windows.Media.Ocr.OcrLine");
                var wordType = RuntimeType("Windows.Media.Ocr.OcrWord");
                var spans = new List<Tuple<string, RectangleF>>();
                foreach (var line in (IEnumerable)resultType.GetProperty("Lines").GetValue(result))
                {
                    string previous = "";
                    foreach (var word in (IEnumerable)lineType.GetProperty("Words").GetValue(line))
                    {
                        string text = (string)wordType.GetProperty("Text").GetValue(word);
                        if (string.IsNullOrEmpty(text)) continue;
                        if (spans.Count > 0 && previous == "") spans.Add(Tuple.Create("\n", RectangleF.Empty));
                        if (OcrPostprocess.NeedsWordSpace(previous, text)) spans.Add(Tuple.Create(" ", RectangleF.Empty));
                        object rect = wordType.GetProperty("BoundingRect").GetValue(word);
                        float Get(string name) => Convert.ToSingle(rect.GetType().GetProperty(name).GetValue(rect), CultureInfo.InvariantCulture);
                        Engine.AddText(spans, text, new RectangleF(Get("X") * image.Width / width, Get("Y") * image.Height / height,
                            Get("Width") * image.Width / width, Get("Height") * image.Height / height));
                        previous = text;
                    }
                }
                return spans.ToArray();
            }
            finally { (bitmap as IDisposable)?.Dispose(); }
        }
    }
}
