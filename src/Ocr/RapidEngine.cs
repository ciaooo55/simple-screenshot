using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using SimpleScreenshot.Core;

namespace SimpleScreenshot.Ocr
{
    sealed class RapidEngine
    {
        const int BatchSize = 6;
        readonly InferenceSession detector, classifier, recognizer;
        readonly string[] alphabet;

        internal RapidEngine(string folder)
        {
            using (var options = new SessionOptions
            {
                GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL,
                IntraOpNumThreads = Math.Max(1, Math.Min(4, Environment.ProcessorCount)),
                InterOpNumThreads = 1
            })
            {
                try
                {
                    detector = new InferenceSession(Path.Combine(folder, "ch_PP-OCRv4_det_infer.onnx"), options);
                    classifier = new InferenceSession(Path.Combine(folder, "ch_ppocr_mobile_v2.0_cls_infer.onnx"), options);
                    recognizer = new InferenceSession(Path.Combine(folder, "ch_PP-OCRv4_rec_infer.onnx"), options);
                    alphabet = recognizer.ModelMetadata.CustomMetadataMap["character"]
                        .Replace("\r\n", "\n").TrimEnd('\n').Split('\n');
                }
                catch
                {
                    detector?.Dispose();
                    classifier?.Dispose();
                    recognizer?.Dispose();
                    throw;
                }
            }
        }

        internal Tuple<string, RectangleF>[] Recognize(Bitmap image)
        {
            var source = Pixels.From(image);
            double globalScale = Math.Min(1, 8192d / Math.Max(source.Width, source.Height));
            if (Math.Min(source.Width, source.Height) * globalScale < 30)
                globalScale = Math.Min(8192d / Math.Max(source.Width, source.Height),
                    30d / Math.Min(source.Width, source.Height));
            int dataW = Math.Max(1, (int)Math.Round(source.Width * globalScale));
            int dataH = Math.Max(1, (int)Math.Round(source.Height * globalScale));
            int padding = dataH <= 30 || dataW / (double)dataH > 8
                ? Math.Abs(2 * Math.Max(dataW / 8, 30) - dataH) / 2 : 0;
            int paddedH = dataH + padding * 2;
            var (detW, detH) = OcrPostprocess.DetectorDimensions(dataW, paddedH);

            var detInput = new float[3 * detW * detH];
            for (int y = 0; y < detH; y++)
            {
                double py = (y + .5) * paddedH / detH - .5 - padding;
                for (int x = 0; x < detW; x++)
                {
                    double px = (x + .5) * dataW / detW - .5;
                    if (py < -.5 || py >= dataH - .5)
                    {
                        int index = y * detW + x;
                        int plane = detW * detH;
                        detInput[index] = detInput[index + plane] = detInput[index + plane * 2] = -1;
                    }
                    else source.Put(detInput, 0, detW, detH, x, y,
                        (px + .5) * source.Width / dataW - .5, (py + .5) * source.Height / dataH - .5);
                }
            }

            var det = Run(detector, detInput, 1, detH, detW, out var shape);
            if (shape.Length != 4 || shape[1] != 1)
                throw new InvalidDataException("检测模型输出尺寸无效。");
            int mapH = shape[2], mapW = shape[3];
            List<OcrPoint[]> boxes = OcrPostprocess.Detect(det, mapW, mapH)
                .Select(box => box.Select(p => new OcrPoint(
                    Clamp(Math.Round(p.X / mapW * dataW) * source.Width / dataW, 0, source.Width - 1),
                    Clamp((Math.Round(p.Y / mapH * paddedH) - padding) * source.Height / dataH, 0, source.Height - 1))).ToArray())
                .Where(box => (box[1] - box[0]).Length > 3 && (box[3] - box[0]).Length > 3)
                .OrderBy(box => box[0].Y).ThenBy(box => box[0].X).ToList();
            for (int index = 0; index + 1 < boxes.Count; index++)
                for (int j = index; j >= 0 && Math.Abs(boxes[j + 1][0].Y - boxes[j][0].Y) < 10
                    && boxes[j + 1][0].X < boxes[j][0].X; j--)
                    (boxes[j], boxes[j + 1]) = (boxes[j + 1], boxes[j]);

            var lines = boxes.Select(box => new Line(box)).ToArray();
            var sorted = lines.OrderBy(line => line.Ratio).ToArray();
            for (int i = 0; i < sorted.Length; i += BatchSize)
            {
                int count = Math.Min(BatchSize, sorted.Length - i);
                Classify(source, sorted, i, count);
                Read(source, sorted, i, count);
            }

            var result = new List<Tuple<string, RectangleF>>();
            foreach (var line in lines)
            {
                if (line.Tokens == null || line.Tokens.Length == 0) continue;
                if (result.Count > 0) result.Add(Tuple.Create("\n", RectangleF.Empty));
                double[] centers = line.Tokens.Select(token =>
                    Clamp((token.Column + .5) / line.Steps / line.UsedFraction, 0, 1)).ToArray();
                for (int i = 0; i < line.Tokens.Length; i++)
                {
                    double left = i == 0 ? Math.Max(0, centers[0] - .5 / line.Steps / line.UsedFraction) :
                        (centers[i - 1] + centers[i]) / 2;
                    double right = i + 1 == centers.Length ? Math.Min(1, centers[i] + .5 / line.Steps / line.UsedFraction) :
                        (centers[i + 1] + centers[i]) / 2;
                    if (right <= left) right = Math.Min(1, left + .005);
                    var area = Engine.Bounds(line.Project(left, 0), line.Project(right, 0),
                        line.Project(right, 1), line.Project(left, 1));
                    Engine.AddText(result, line.Tokens[i].Text, area);
                }
            }
            return result.ToArray();
        }

        void Classify(Pixels source, Line[] lines, int start, int count)
        {
            const int h = 48, w = 192;
            var input = new float[count * 3 * h * w];
            for (int i = 0; i < count; i++)
                FillLine(source, input, i, lines[start + i], h, w);
            float[] scores = Run(classifier, input, count, h, w, out var shape);
            if (shape.Length != 2 || shape[0] != count || shape[1] != 2)
                throw new InvalidDataException("方向模型输出尺寸无效。");
            for (int i = 0; i < count; i++)
                if (scores[i * 2 + 1] > scores[i * 2] && scores[i * 2 + 1] > .9f)
                    lines[start + i].Flipped = true;
        }

        void Read(Pixels source, Line[] lines, int start, int count)
        {
            const int h = 48;
            int w = 320;
            for (int i = 0; i < count; i++)
                w = Math.Max(w, Math.Min(8192, (int)Math.Ceiling(h * lines[start + i].Ratio)));
            var input = new float[count * 3 * h * w];
            for (int i = 0; i < count; i++)
                lines[start + i].UsedFraction = FillLine(source, input, i, lines[start + i], h, w) / (double)w;
            float[] tensor = Run(recognizer, input, count, h, w, out var shape);
            if (shape.Length != 3 || shape[0] != count || shape[2] != alphabet.Length + 2)
                throw new InvalidDataException("识别模型输出尺寸与字典不匹配。");
            int steps = shape[1], classes = shape[2];
            for (int row = 0; row < count; row++)
            {
                var ids = new int[steps];
                var scores = new float[steps];
                for (int col = 0; col < steps; col++)
                {
                    int offset = (row * steps + col) * classes;
                    int best = 0;
                    for (int id = 1; id < classes; id++)
                        if (tensor[offset + id] > tensor[offset + best]) best = id;
                    ids[col] = best;
                    scores[col] = tensor[offset + best];
                }
                var tokens = OcrPostprocess.Decode(ids, scores, alphabet);
                if (tokens.Count == 0 || tokens.Average(token => token.Score) < .5f) continue;
                var line = lines[start + row];
                line.Steps = steps;
                line.Tokens = tokens.SkipWhile(token => string.IsNullOrWhiteSpace(token.Text)).Reverse()
                    .SkipWhile(token => string.IsNullOrWhiteSpace(token.Text)).Reverse().ToArray();
            }
        }

        static int FillLine(Pixels source, float[] destination, int batch, Line line, int height, int width)
        {
            int resizedWidth = Math.Max(1, Math.Min(width, (int)Math.Ceiling(height * line.Ratio)));
            for (int y = 0; y < height; y++)
                for (int x = 0; x < resizedWidth; x++)
                {
                    var point = line.Project((x + .5) / resizedWidth, (y + .5) / height);
                    source.Put(destination, batch, width, height, x, y, point.X, point.Y);
                }
            return resizedWidth;
        }

        static float[] Run(InferenceSession session, float[] buffer, int batch, int height, int width, out int[] shape)
        {
            var input = new DenseTensor<float>(buffer, new[] { batch, 3, height, width });
            using (var result = session.Run(new[] { NamedOnnxValue.CreateFromTensor(session.InputNames[0], input) }))
            {
                var tensor = result.First().AsTensor<float>();
                shape = tensor.Dimensions.ToArray();
                return tensor.ToArray();
            }
        }

        static double Clamp(double value, double lower, double upper) => Math.Max(lower, Math.Min(value, upper));

        sealed class Line
        {
            readonly OcrPoint origin, uStep, vStep;
            readonly double uPerspective, vPerspective;
            readonly bool vertical;
            internal double Ratio, UsedFraction;
            internal bool Flipped;
            internal int Steps;
            internal OcrPostprocess.Token[] Tokens;

            internal Line(OcrPoint[] box)
            {
                var p0 = box[0]; var p1 = box[1]; var p2 = box[2]; var p3 = box[3];
                double width = Math.Max((p1 - p0).Length, (p2 - p3).Length);
                double height = Math.Max((p3 - p0).Length, (p2 - p1).Length);
                vertical = height / width >= 1.5;
                Ratio = vertical ? height / width : width / height;

                var d1 = p1 - p2;
                var d2 = p3 - p2;
                var diff = p0 - p1 + p2 - p3;
                double determinant = d1.Cross(d2);
                if (Math.Abs(determinant) > .0001)
                {
                    uPerspective = diff.Cross(d2) / determinant;
                    vPerspective = d1.Cross(diff) / determinant;
                }
                origin = p0;
                uStep = p1 * (1 + uPerspective) - p0;
                vStep = p3 * (1 + vPerspective) - p0;
            }

            internal OcrPoint Project(double x, double y)
            {
                if (Flipped) { x = 1 - x; y = 1 - y; }
                if (vertical) (x, y) = (1 - y, x);
                double divisor = 1 + x * uPerspective + y * vPerspective;
                if (Math.Abs(divisor) < .000001) divisor = .000001;
                return (origin + uStep * x + vStep * y) * (1 / divisor);
            }
        }
    }
}
