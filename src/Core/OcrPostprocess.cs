using System;
using System.Collections.Generic;
using System.Linq;

namespace SimpleScreenshot.Core
{
    public readonly struct OcrPoint
    {
        public readonly double X, Y;
        public OcrPoint(double x, double y) { X = x; Y = y; }
        public static OcrPoint operator +(OcrPoint a, OcrPoint b) => new OcrPoint(a.X + b.X, a.Y + b.Y);
        public static OcrPoint operator -(OcrPoint a, OcrPoint b) => new OcrPoint(a.X - b.X, a.Y - b.Y);
        public static OcrPoint operator *(OcrPoint a, double b) => new OcrPoint(a.X * b, a.Y * b);
        public double Length => Math.Sqrt(X * X + Y * Y);
        public double Dot(OcrPoint b) => X * b.X + Y * b.Y;
        public double Cross(OcrPoint b) => X * b.Y - Y * b.X;
    }

    public static class OcrPostprocess
    {
        public readonly struct Token
        {
            public readonly string Text;
            public readonly int Column;
            public readonly float Score;
            public Token(string text, int column, float score) { Text = text; Column = column; Score = score; }
        }

        public static IReadOnlyList<Token> Decode(IReadOnlyList<int> ids, IReadOnlyList<float> scores,
            IReadOnlyList<string> alphabet)
        {
            if (ids.Count != scores.Count) throw new ArgumentException("识别序列长度不匹配。");
            var tokens = new List<Token>();
            int previous = 0;
            for (int i = 0; i < ids.Count; i++)
            {
                int id = ids[i];
                if (id != 0 && id != previous)
                {
                    if (id < 0 || id > alphabet.Count + 1)
                        throw new ArgumentException("识别模型与字典不匹配。");
                    tokens.Add(new Token(id > alphabet.Count ? " " : alphabet[id - 1], i, scores[i]));
                }
                previous = id;
            }
            return tokens;
        }

        static bool Cjk(char c) => (c >= '\u2e80' && c <= '\u9fff') ||
            (c >= '\uf900' && c <= '\ufaff') || (c >= '\uff00' && c <= '\uffef');

        public static bool NeedsWordSpace(string previous, string next) =>
            previous.Length > 0 && next.Length > 0 && !(Cjk(previous[previous.Length - 1]) && Cjk(next[0]));

        public static string JoinWords(IEnumerable<string> words)
        {
            var result = new System.Text.StringBuilder();
            string previous = "";
            foreach (var word in words)
            {
                if (string.IsNullOrEmpty(word)) continue;
                if (NeedsWordSpace(previous, word)) result.Append(' ');
                result.Append(word);
                previous = word;
            }
            return result.ToString();
        }

        public static (int Width, int Height) DetectorDimensions(int width, int height)
        {
            double ratio = Math.Max(1, 736d / Math.Min(width, height));
            ratio = Math.Min(ratio, 8192d / Math.Max(width, height));
            ratio = Math.Min(ratio, Math.Sqrt(20000000d / ((double)width * height)));
            int Grid(double side) => Math.Max(32, (int)Math.Round(side / 32) * 32);
            return (Grid(width * ratio), Grid(height * ratio));
        }

        public static IReadOnlyList<OcrPoint[]> Detect(float[] probability, int width, int height,
            float threshold = .3f, float boxThreshold = .5f, double unclip = 1.6)
        {
            if (width < 1 || height < 1 || probability.Length != checked(width * height))
                throw new ArgumentException("检测概率图尺寸不匹配。");
            var mask = new byte[probability.Length];
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    int index = y * width + x;
                    if (probability[index] > threshold || x > 0 && probability[index - 1] > threshold ||
                        y > 0 && probability[index - width] > threshold ||
                        x > 0 && y > 0 && probability[index - width - 1] > threshold)
                        mask[index] = 1;
                }
            var queue = new int[mask.Length];
            var result = new List<OcrPoint[]>();
            int candidates = 0;
            for (int index = mask.Length - 1; index >= 0 && candidates < 1000; index--)
            {
                if (mask[index] != 1) continue;
                candidates++;
                int count = 1;
                queue[0] = index;
                mask[index] = 2;
                var contour = new List<OcrPoint>();
                for (int head = 0; head < count; head++)
                {
                    int position = queue[head], x = position % width, y = position / width;
                    if (x == 0 || x == width - 1 || y == 0 || y == height - 1 ||
                        mask[position - 1] == 0 || mask[position + 1] == 0 ||
                        mask[position - width] == 0 || mask[position + width] == 0)
                        contour.Add(new OcrPoint(x, y));

                    for (int dy = Math.Max(-1, -y); dy <= Math.Min(1, height - 1 - y); dy++)
                        for (int dx = Math.Max(-1, -x); dx <= Math.Min(1, width - 1 - x); dx++)
                        {
                            int next = (y + dy) * width + x + dx;
                            if (mask[next] != 1) continue;
                            mask[next] = 2;
                            queue[count++] = next;
                        }
                }
                if (contour.Count < 4) continue;
                var box = MinimumBox(Hull(contour));
                if (Math.Min(box.Width, box.Height) < 3 || Mean(probability, width, height, box) < boxThreshold)
                    continue;
                double radius = box.Width * box.Height * unclip / (2 * (box.Width + box.Height));
                box = box.Expand(radius);
                if (Math.Min(box.Width, box.Height) < 5) continue;
                var corners = box.Corners.OrderBy(point => point.X).ThenBy(point => point.Y).ToArray();
                if (corners[0].Y > corners[1].Y) (corners[0], corners[1]) = (corners[1], corners[0]);
                if (corners[2].Y > corners[3].Y) (corners[2], corners[3]) = (corners[3], corners[2]);
                result.Add(new[] { corners[0], corners[2], corners[3], corners[1] });
            }
            return result;
        }

        static List<OcrPoint> Hull(List<OcrPoint> points)
        {
            var sorted = points.OrderBy(point => point.X).ThenBy(point => point.Y).ToArray();
            var hull = new List<OcrPoint>();
            void Add(OcrPoint point, int first)
            {
                while (hull.Count >= first + 2)
                {
                    var previous = hull[hull.Count - 2];
                    var current = hull[hull.Count - 1];
                    if ((current - previous).Cross(point - current) > 0) break;
                    hull.RemoveAt(hull.Count - 1);
                }
                hull.Add(point);
            }
            foreach (var point in sorted) Add(point, 0);
            int halfway = hull.Count - 1;
            for (int i = sorted.Length - 2; i >= 0; i--) Add(sorted[i], halfway);
            hull.RemoveAt(hull.Count - 1);
            return hull;
        }

        static OrientedBox MinimumBox(List<OcrPoint> hull)
        {
            double min = double.PositiveInfinity;
            var best = new OrientedBox();
            for (int index = 0; index < hull.Count; index++)
            {
                var edge = hull[(index + 1) % hull.Count] - hull[index];
                if (edge.Length == 0) continue;
                var u = edge * (1 / edge.Length);
                var v = new OcrPoint(-u.Y, u.X);
                double x0 = double.PositiveInfinity, x1 = double.NegativeInfinity;
                double y0 = double.PositiveInfinity, y1 = double.NegativeInfinity;
                foreach (var point in hull)
                {
                    double x = point.Dot(u), y = point.Dot(v);
                    x0 = Math.Min(x0, x); x1 = Math.Max(x1, x);
                    y0 = Math.Min(y0, y); y1 = Math.Max(y1, y);
                }
                double area = (x1 - x0) * (y1 - y0);
                if (area < min)
                {
                    min = area;
                    best = new OrientedBox(u, v, x0, x1, y0, y1);
                }
            }
            return best;
        }

        static double Mean(float[] data, int width, int height, OrientedBox box)
        {
            var corners = box.Corners;
            int left = Math.Max(0, (int)Math.Floor(corners.Min(p => p.X)));
            int right = Math.Min(width - 1, (int)Math.Ceiling(corners.Max(p => p.X)));
            int top = Math.Max(0, (int)Math.Floor(corners.Min(p => p.Y)));
            int bottom = Math.Min(height - 1, (int)Math.Ceiling(corners.Max(p => p.Y)));
            double sum = 0;
            int count = 0;
            for (int y = top; y <= bottom; y++)
                for (int x = left; x <= right; x++)
                    if (box.Contains(new OcrPoint(x, y)))
                    {
                        sum += data[y * width + x];
                        count++;
                    }
            return count == 0 ? 0 : sum / count;
        }

        readonly struct OrientedBox
        {
            readonly OcrPoint u, v;
            readonly double x0, x1, y0, y1;
            internal OrientedBox(OcrPoint u, OcrPoint v, double x0, double x1, double y0, double y1)
            {
                this.u = u; this.v = v; this.x0 = x0; this.x1 = x1; this.y0 = y0; this.y1 = y1;
            }
            internal double Width => x1 - x0;
            internal double Height => y1 - y0;
            internal OcrPoint[] Corners => new[] { u * x0 + v * y0, u * x1 + v * y0, u * x1 + v * y1, u * x0 + v * y1 };
            internal OrientedBox Expand(double by) => new OrientedBox(u, v, x0 - by, x1 + by, y0 - by, y1 + by);
            internal bool Contains(OcrPoint point)
            {
                double x = point.Dot(u), y = point.Dot(v);
                return x >= x0 - .001 && x <= x1 + .001 && y >= y0 - .001 && y <= y1 + .001;
            }
        }
    }
}
