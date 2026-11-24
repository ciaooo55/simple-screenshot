using System;
using System.Globalization;
using System.IO;

namespace SimpleScreenshot.Core
{
    public static class OutputNames
    {
        public static string UniquePng(string directory, DateTime timestamp, Func<string, bool> exists)
        {
            string stem = "Screenshot_" + timestamp.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture);
            string path = Path.Combine(directory, stem + ".png");
            for (int suffix = 1; exists(path); suffix++)
                path = Path.Combine(directory, stem + "_" + suffix.ToString(CultureInfo.InvariantCulture) + ".png");
            return path;
        }

        public static string WithPngExtension(string path) =>
            string.Equals(Path.GetExtension(path), ".png", StringComparison.OrdinalIgnoreCase) ? path : path + ".png";
    }
}
