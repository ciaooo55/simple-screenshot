using System;
using System.Drawing;

namespace SimpleScreenshot.Core
{
    public static class Geometry
    {
        public static int ScalePixel(double value, double dpi) =>
            (int)Math.Round(value * dpi / 96, MidpointRounding.AwayFromZero);

        public static double ScaleLogical(double value, double dpi) => value * 96 / dpi;

        public static int Clamp(int value, int low, int high) => Math.Max(low, Math.Min(value, high));

        public static Rectangle RestoreSelection(Rectangle screenSelection, Rectangle desktop)
        {
            var visible = Rectangle.Intersect(screenSelection, desktop);
            if (visible.Width <= 0 || visible.Height <= 0) return Rectangle.Empty;
            visible.Offset(-desktop.X, -desktop.Y);
            return visible;
        }

        public static Rectangle SelectionFromDrag(Point origin, Point pointer, Size bounds, bool square, Size dragSize,
            ref bool dragStarted)
        {
            int dx = Math.Abs(pointer.X - origin.X), dy = Math.Abs(pointer.Y - origin.Y);
            if (dx < Math.Max(1, dragSize.Width / 2) && dy < Math.Max(1, dragSize.Height / 2))
                return Rectangle.Empty;
            dragStarted = true;
            if (square)
            {
                bool left = pointer.X < origin.X, up = pointer.Y < origin.Y;
                int side = 1 + Math.Max(dx, dy);
                side = Math.Min(side, Math.Min(left ? origin.X + 1 : bounds.Width - origin.X,
                    up ? origin.Y + 1 : bounds.Height - origin.Y));
                pointer = new Point(origin.X + (left ? 1 - side : side - 1),
                    origin.Y + (up ? 1 - side : side - 1));
            }
            return Rectangle.FromLTRB(Math.Min(origin.X, pointer.X), Math.Min(origin.Y, pointer.Y),
                Math.Max(origin.X, pointer.X) + 1, Math.Max(origin.Y, pointer.Y) + 1);
        }

        public static int DragAxis(int fixedPoint, int pointer, int lower, int upper, int minSize)
        {
            if (pointer >= fixedPoint)
                return Clamp(Math.Max(fixedPoint + minSize, pointer), lower, upper);
            return Clamp(Math.Min(fixedPoint - minSize, pointer), lower, upper);
        }

        public static int AnchorOrigin(int origin, double point, double zoomRatio) =>
            (int)Math.Round(origin + point * (1 - zoomRatio), MidpointRounding.AwayFromZero);

        public static double FitScale(Size source, Size bounds) =>
            Math.Min((double)bounds.Width / source.Width, (double)bounds.Height / source.Height);
    }
}
