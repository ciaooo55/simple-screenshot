using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

namespace SimpleScreenshot
{
    enum InkTool { Pen, Highlight, Arrow, Rectangle, Ellipse, Number, Mosaic, Text }

    sealed class Ink
    {
        internal InkTool Tool;
        internal Color Color;
        internal float Width;
        internal PointF Start, End;
        internal List<PointF> Points;
        internal string Text;

        internal RectangleF Bounds => RectangleF.FromLTRB(
            Math.Min(Start.X, End.X), Math.Min(Start.Y, End.Y), Math.Max(Start.X, End.X), Math.Max(Start.Y, End.Y));

        internal static Bitmap Render(Bitmap source, IEnumerable<Ink> commands)
        {
            var result = source.Clone(new Rectangle(Point.Empty, source.Size), PixelFormat.Format32bppPArgb);
            using (var canvas = Graphics.FromImage(result))
                foreach (var command in commands) command.Draw(canvas, source);
            return result;
        }

        internal void Draw(Graphics g, Bitmap source)
        {
            var previous = g.Save();
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var color = Tool == InkTool.Highlight ? Color.FromArgb(103, Color) : Color;
            using (var pen = new Pen(color, Math.Max(1f, Width))
            {
                StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round
            })
            using (var fill = new SolidBrush(color))
            {
                var bounds = Bounds;
                switch (Tool)
                {
                    case InkTool.Pen:
                    case InkTool.Highlight:
                        if (Points.Count > 1)
                        {
                            using (var line = new GraphicsPath())
                            {
                                line.AddLines(Points.ToArray());
                                g.DrawPath(pen, line);
                            }
                        }
                        break;
                    case InkTool.Arrow:
                        float dx = End.X - Start.X, dy = End.Y - Start.Y;
                        float length = (float)Math.Sqrt(dx * dx + dy * dy);
                        if (length < 1) break;
                        float size = Math.Min(length, Math.Max(10, Width * 3.8f));
                        var back = new PointF(End.X - size * dx / length, End.Y - size * dy / length);
                        var mid = new PointF(End.X - .72f * size * dx / length, End.Y - .72f * size * dy / length);
                        g.DrawLine(pen, Start, mid);
                        g.FillPolygon(fill, new[] { End,
                            new PointF(back.X - .48f * size * dy / length, back.Y + .48f * size * dx / length),
                            new PointF(back.X + .48f * size * dy / length, back.Y - .48f * size * dx / length) });
                        break;
                    case InkTool.Rectangle: g.DrawRectangle(pen, bounds.X, bounds.Y, bounds.Width, bounds.Height); break;
                    case InkTool.Ellipse: g.DrawEllipse(pen, bounds); break;
                    case InkTool.Number:
                        float radius = Math.Max(9, Width * 2.2f);
                        var pill = new RectangleF(Start.X - radius, Start.Y - radius, radius * 2, radius * 2);
                        g.FillEllipse(fill, pill);
                        using (var font = new Font("Microsoft YaHei UI", radius * 1.12f, FontStyle.Bold, GraphicsUnit.Pixel))
                        using (var format = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                            g.DrawString(Text, font, color.GetBrightness() > .65f ? Brushes.Black : Brushes.White, pill, format);
                        break;
                    case InkTool.Text:
                        using (var font = new Font("Microsoft YaHei UI", Math.Max(12f, Width), FontStyle.Regular, GraphicsUnit.Pixel))
                            g.DrawString(Text, font, fill, new RectangleF(Start.X, Start.Y, Math.Max(80, source.Width - Start.X), 10000));
                        break;
                    case InkTool.Mosaic:
                        DrawMosaic(g, source, bounds);
                        break;
                }
            }
            g.Restore(previous);
        }

        static void DrawMosaic(Graphics g, Bitmap source, RectangleF rect)
        {
            var region = Rectangle.Intersect(new Rectangle(Point.Empty, source.Size), Rectangle.Round(rect));
            if (region.Width <= 0 || region.Height <= 0) return;
            int block = Math.Max(8, Math.Min(20, Math.Min(region.Width, region.Height) / 20));
            int columns = Math.Max(1, (region.Width + block - 1) / block);
            int rows = Math.Max(1, (region.Height + block - 1) / block);
            using (var mini = new Bitmap(columns, rows))
            {
                using (var sampler = Graphics.FromImage(mini))
                {
                    sampler.InterpolationMode = InterpolationMode.HighQualityBilinear;
                    sampler.DrawImage(source, new Rectangle(0, 0, columns, rows), region, GraphicsUnit.Pixel);
                }
                g.InterpolationMode = InterpolationMode.NearestNeighbor;
                g.PixelOffsetMode = PixelOffsetMode.Half;
                g.DrawImage(mini, region, new Rectangle(0, 0, columns, rows), GraphicsUnit.Pixel);
            }
        }
    }
}
