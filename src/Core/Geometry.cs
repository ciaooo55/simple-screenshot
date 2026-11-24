using System;

namespace SimpleScreenshot.Core
{
    public static class Geometry
    {
        public static int ScalePixel(double value, double dpi) =>
            (int)Math.Round(value * dpi / 96, MidpointRounding.AwayFromZero);

        public static double ScaleLogical(double value, double dpi) => value * 96 / dpi;

        public static int Clamp(int value, int low, int high) => Math.Max(low, Math.Min(value, high));

        public static int DragAxis(int fixedPoint, int pointer, int lower, int upper, int minSize)
        {
            if (pointer >= fixedPoint)
                return Clamp(Math.Max(fixedPoint + minSize, pointer), lower, upper);
            return Clamp(Math.Min(fixedPoint - minSize, pointer), lower, upper);
        }

        public static int AnchorOrigin(int origin, double point, double zoomRatio) =>
            (int)Math.Round(origin + point * (1 - zoomRatio), MidpointRounding.AwayFromZero);
    }
}
