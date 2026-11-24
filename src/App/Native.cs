using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace SimpleScreenshot
{
    static class Native
    {
        internal const int HotkeyMessage = 0x0312;
        internal const int ExtendedStyle = -20;
        internal const int Transparent = 0x20;

        [DllImport("user32", SetLastError = true)]
        internal static extern bool RegisterHotKey(IntPtr hwnd, int id, uint mods, uint key);
        [DllImport("user32")] internal static extern bool UnregisterHotKey(IntPtr hwnd, int id);
        [DllImport("user32")] internal static extern short GetKeyState(int key);
        [DllImport("user32")] internal static extern int GetWindowLong(IntPtr hwnd, int index);
        [DllImport("user32")] internal static extern int SetWindowLong(IntPtr hwnd, int index, int value);
        [DllImport("dwmapi")] internal static extern int DwmFlush();
        [DllImport("shell32", CharSet = CharSet.Unicode)]
        internal static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
        [DllImport("user32")] static extern IntPtr GetDC(IntPtr window);
        [DllImport("user32")] static extern int ReleaseDC(IntPtr window, IntPtr dc);
        [DllImport("gdi32", SetLastError = true)]
        static extern bool BitBlt(IntPtr destination, int dx, int dy, int width, int height,
            IntPtr source, int sx, int sy, uint operation);

        [DllImport("user32")] static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32")] static extern bool IsIconic(IntPtr window);
        [DllImport("user32")] static extern bool GetWindowRect(IntPtr window, out Rect rect);
        [DllImport("user32", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr window, StringBuilder title, int max);
        [DllImport("user32")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
        [DllImport("user32")] static extern bool EnumWindows(EnumWindow callback, IntPtr parameter);
        [DllImport("dwmapi")] static extern int DwmGetWindowAttribute(IntPtr window, int attribute, out Rect value, int size);
        [DllImport("dwmapi", EntryPoint = "DwmGetWindowAttribute")]
        static extern int GetCloaked(IntPtr window, int attribute, out int value, int size);

        delegate bool EnumWindow(IntPtr window, IntPtr parameter);
        [StructLayout(LayoutKind.Sequential)]
        struct Rect
        {
            public int Left, Top, Right, Bottom;
            public Rectangle Rectangle => Rectangle.FromLTRB(Left, Top, Right, Bottom);
        }

        internal sealed class WindowTarget
        {
            public Rectangle Bounds;
            public string Title;
        }

        internal static IReadOnlyList<WindowTarget> Discover(Rectangle bounds)
        {
            var targets = new List<WindowTarget>();
            var rects = new HashSet<Rectangle>();
            uint own = (uint)Process.GetCurrentProcess().Id;
            EnumWindows((window, _) =>
            {
                if (!IsWindowVisible(window) || IsIconic(window) ||
                    GetCloaked(window, 14, out int cloaked, sizeof(int)) == 0 && cloaked != 0)
                    return true;
                GetWindowThreadProcessId(window, out uint pid);
                if (pid == own)
                    return true;
                var title = new StringBuilder(1024);
                if (GetWindowText(window, title, title.Capacity) == 0)
                    return true;
                if (DwmGetWindowAttribute(window, 9, out Rect rect, Marshal.SizeOf<Rect>()) != 0 &&
                    !GetWindowRect(window, out rect))
                    return true;
                var local = Rectangle.Intersect(bounds, rect.Rectangle);
                local.Offset(-bounds.X, -bounds.Y);
                if (local.Width >= 24 && local.Height >= 24 && rects.Add(local))
                    targets.Add(new WindowTarget { Bounds = local, Title = title.ToString().Trim() });
                return true;
            }, IntPtr.Zero);
            return targets;
        }

        internal static bool WinDown => GetKeyState(0x5B) < 0 || GetKeyState(0x5C) < 0;

        internal static void CopyDesktop(Graphics target, Rectangle desktop, IEnumerable<Rectangle> monitors)
        {
            const uint sourceCopyWithLayeredWindows = 0x40CC0020;
            IntPtr screen = GetDC(IntPtr.Zero);
            if (screen == IntPtr.Zero) throw new InvalidOperationException("无法访问 Windows 桌面。");
            try
            {
                IntPtr destination = target.GetHdc();
                try
                {
                    foreach (Rectangle monitor in monitors)
                        if (!BitBlt(destination, monitor.X - desktop.X, monitor.Y - desktop.Y,
                            monitor.Width, monitor.Height, screen, monitor.X, monitor.Y, sourceCopyWithLayeredWindows))
                            throw new Win32Exception();
                }
                finally { target.ReleaseHdc(destination); }
            }
            finally { ReleaseDC(IntPtr.Zero, screen); }
        }
    }
}
