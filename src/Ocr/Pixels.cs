using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace SimpleScreenshot.Ocr
{
    sealed class Pixels
    {
        readonly byte[] bytes;
        internal readonly int Width, Height;

        Pixels(byte[] bytes, int width, int height) { this.bytes = bytes; Width = width; Height = height; }

        internal static Pixels From(Bitmap image)
        {
            using (var converted = image.Clone(new Rectangle(Point.Empty, image.Size), PixelFormat.Format32bppArgb))
            {
                var data = converted.LockBits(new Rectangle(Point.Empty, image.Size), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    var bytes = new byte[data.Width * data.Height * 4];
                    int width = data.Width * 4;
                    if (data.Stride == width) Marshal.Copy(data.Scan0, bytes, 0, bytes.Length);
                    else
                        for (int y = 0; y < data.Height; y++)
                            Marshal.Copy(IntPtr.Add(data.Scan0, y * data.Stride), bytes, y * width, width);
                    return new Pixels(bytes, data.Width, data.Height);
                }
                finally { converted.UnlockBits(data); }
            }
        }

        internal byte[] Bgra => bytes;

        internal void Put(float[] dest, int batch, int w, int h, int x, int y, double sourceX, double sourceY)
        {
            double sx = Math.Max(0, Math.Min(Width - 1, sourceX));
            double sy = Math.Max(0, Math.Min(Height - 1, sourceY));
            int x0 = (int)sx, x1 = Math.Min(x0 + 1, Width - 1);
            int y0 = (int)sy, y1 = Math.Min(y0 + 1, Height - 1);
            double u = sx - x0, v = sy - y0;
            int p0 = (y0 * Width + x0) * 4, p1 = (y0 * Width + x1) * 4;
            int p2 = (y1 * Width + x0) * 4, p3 = (y1 * Width + x1) * 4;
            int plane = w * h;
            int destination = 3 * batch * plane + y * w + x;
            for (int i = 0; i < 3; i++)
            {
                double value = (bytes[p0 + i] * (1 - u) + bytes[p1 + i] * u) * (1 - v)
                    + (bytes[p2 + i] * (1 - u) + bytes[p3 + i] * u) * v;
                dest[destination + i * plane] = (float)(value / 127.5 - 1);
            }
        }
    }
}
